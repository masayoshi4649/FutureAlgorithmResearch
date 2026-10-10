"""既知区間の最悪方式を選び、反転の成績と分離して記録する。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
COMPLETE = ['2026-09-21_Day', '2026-09-21_Night', '2026-09-22_Day',
            '2026-09-22_Night', '2026-09-23_Day']
SYMBOLS = ['NK225', 'TOPIX']
GROUPS = ['全方式', '予測主導', '予測と注文の組合せ', '注文主導']


def choose_worst(frame: pd.DataFrame, train: list[str], target: str,
                 philosophy: str, value_column: str, normalize: bool) -> dict:
    """機能: 指定された過去だけの成績から最小得点の方式を選ぶ。

    引数: frame (DataFrame)、train (list[str])、target/philosophy/value_column (str)、
    normalize (bool)。返り値: 学習範囲・方式・得点・銘柄別取引数の記録 (dict)。
    """
    symbols = SYMBOLS if target == '両銘柄' else [target]
    part = frame[frame['セッション'].isin(train) & frame['銘柄'].isin(symbols)].copy()
    if philosophy != '全方式':
        part = part[part['思想'] == philosophy]
    part['選択得点'] = part[value_column] / part['設定最大枚数'] if normalize else part[value_column]
    counts = part.groupby(['方式', '銘柄'])['取引数'].sum().unstack(fill_value=0).reindex(columns=symbols, fill_value=0)
    valid = counts.index[(counts > 0).all(axis=1)]
    ranks = part.groupby('方式').agg(得点=('選択得点', 'sum'), 元学習収支円=('収支円', 'sum'),
                                  設定最大枚数=('設定最大枚数', 'max')).loc[valid].reset_index()
    ranks = ranks.sort_values(['得点', '方式'])
    selected = None
    if len(ranks):
        first = ranks.iloc[0]
        selected = dict(方式=first['方式'], 得点=float(first['得点']),
                        元学習収支円=float(first['元学習収支円']), 設定最大枚数=int(first['設定最大枚数']),
                        銘柄別取引数={s: int(v) for s, v in counts.loc[first['方式']].items()})
    return dict(学習=train, 対象=target, 思想=philosophy, 選択列=value_column,
                枚数上限換算=normalize, 選択=selected, 候補数=len(ranks))


def selections(frame: pd.DataFrame, value_column: str, normalize: bool) -> list[dict]:
    """機能: 思想・対象別に３回の時間順選択と５完全セッションの選択を作る。

    引数: frame (DataFrame)、value_column (str)、normalize (bool)。
    返り値: 選択記録の一覧 (list[dict])。
    """
    result = []
    for target in ['両銘柄', *SYMBOLS]:
        for philosophy in GROUPS:
            for count in [2, 3, 4, 5]:
                row = choose_worst(frame, COMPLETE[:count], target, philosophy, value_column, normalize)
                row['評価セッション'] = COMPLETE[count] if count < 5 else '2026-09-23_Night'
                row['区分'] = '時間順' if count < 5 else '５完全で選択'
                result.append(row)
    return result


def save(path: Path, value: object) -> None:
    """機能: 日本語のJSONをUTF-8で保存する。

    引数: path (Path)、value (object)。返り値: None。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def main() -> None:
    """機能: 反転成績を参照せず、元の純収支による最悪選択を固定する。

    引数: なし。返り値: None。現在データへの通信はしない。
    """
    frame = pd.read_csv(ROOT/'work/wave_v11/全条件_セッション集計.csv')
    choices = selections(frame, '収支円', True) + selections(frame, '収支円', False)
    save(OUT/'元純益による最悪選択.json', choices)
    chosen = sorted({row['選択']['方式'] for row in choices if row['選択']})
    save(OUT/'元純益最悪ID.json', chosen)
    print(json.dumps(dict(選択数=len(choices), 条件数=len(chosen), 条件=chosen), ensure_ascii=False))


if __name__ == '__main__':
    main()
