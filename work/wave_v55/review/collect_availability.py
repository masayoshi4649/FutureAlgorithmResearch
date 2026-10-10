"""固定済みの準備判定を変えず、各場で検証できた判断機会の範囲を集計する。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
JST = timezone(timedelta(hours=9))


def stamp(value: float | None) -> str | None:
    """機能: 秒単位時刻を日本時間の読みやすい文字列へ変換する。

    引数: value(float|None)。返り値: 日本時間文字列または欠測(str|None)。
    """
    return None if value is None else datetime.fromtimestamp(float(value), JST).isoformat()


def summarize(key: tuple, ready: dict, frame: object) -> dict:
    """機能: 公開済み足の準備可能行数を、固定の返済時刻・新規締切ごとに数える。

    引数: key(tuple)、ready(dict)、frame(pd.DataFrame)。返り値: 場別集計(dict)。
    1行を1回の分次判断機会と数え、欠測区間を準備可能な経過時間へ換算しない。
    """
    start, limit = float(ready['start']), float(ready['limit'])
    entry_end = limit - 300.
    exit_mask = frame['time_s'].between(start, limit, inclusive='left')
    entry_mask = frame['time_s'].between(start, entry_end, inclusive='left')
    valid = frame['can_trade']
    can = frame[entry_mask & valid]
    entry_minutes = (entry_end - start) / 60.
    result = dict(
        セッション=key[0], 銘柄=key[1],
        場開始時刻=stamp(start), 新規締切時刻=stamp(entry_end), 返済判断時刻=stamp(limit),
        検証対象セッション分数=(limit - start) / 60., 新規対象セッション分数=entry_minutes,
        返済判断までの観測分数=int(exit_mask.sum()),
        返済判断までの準備可能分数=int((exit_mask & valid).sum()),
        新規締切までの観測分数=int(entry_mask.sum()),
        新規締切までの準備可能分数=len(can),
        新規対象時間に対する準備可能率=len(can) / entry_minutes,
        全収録区間の観測分数=len(frame), 全収録区間の準備可能分数=int(valid.sum()),
        初回準備時刻=None if can.empty else stamp(can.iloc[0]['time_s']),
        最終準備時刻=None if can.empty else stamp(can.iloc[-1]['time_s']),
        最初の観測時刻=stamp(float(ready['time_s'][0])),
        最後の観測時刻=stamp(float(ready['time_s'][-1])),
    )
    return result


def main() -> None:
    """機能: 準備可能時間の記録と、時間範囲が短い場についての注意を保存する。

    引数: なし。返り値: なし(None)。特徴・取引条件・取引結果は変更しない。
    """
    inputs = pickle.loads((BASE / 'clean_inputs.pkl').read_bytes())
    features = pickle.loads((BASE / '特徴.pkl').read_bytes())
    records = [summarize(key, inputs[key], features[key]) for key in sorted(inputs)]
    sparse = [record for record in records if record['新規対象時間に対する準備可能率'] < .1]
    symbols = {}
    for symbol in ('TOPIX', 'NK225'):
        rows = [record for record in records if record['銘柄'] == symbol]
        ready = np.array([row['新規締切までの準備可能分数'] for row in rows])
        denominator = sum(row['新規対象セッション分数'] for row in rows)
        symbols[symbol] = dict(
            場数=len(rows), 観測分数合計=sum(row['新規締切までの観測分数'] for row in rows),
            準備可能分数合計=int(ready.sum()), 新規対象セッション分数合計=denominator,
            準備可能率=float(ready.sum() / denominator), 準備可能分数最小=int(ready.min()),
            準備可能分数中央値=float(np.median(ready)), 準備可能分数最大=int(ready.max()),
            準備可能0分の場数=int((ready == 0).sum()),
            準備可能率10パーセント未満の場数=sum(row['新規対象時間に対する準備可能率'] < .1 for row in rows),
        )
    result = dict(
        定義='1公開確定足を1回の分次判断機会として数える。準備可能分数はcan_trade=Trueの行数であり、売買回数や保有時間ではない。',
        分母='検証対象セッション分数はready.startから返済判断時刻limitまで。新規対象はlimitの5分前まで。公式取引時間全体を意味しない。',
        数え方='観測分数・準備可能分数は公開時刻が各対象区間内の行を数える。準備済みでも交差なし・保有中等で売買しない場合がある。',
        固定準備条件='場開始20分経過、現在を含む20連続確定分、公開遅延60秒以内。今回は変更しない。',
        欠測の意味='約定時刻に基づく分足の空白は受信欠落と約定時刻が進まない状態を区別できない。空白を架空価格で埋めず、新規準備を不成立とする。',
        注意='23場全てを評価母数に含めるが、場全体を同じ時間だけ試せたわけではない。準備可能時間が短い場の損益は、その場の全パターンへの対応力を示さない。',
        記述用区分='準備可能率10%未満を時間範囲が極端に短い場として下欄へ列挙する。取引閾値や成績除外の基準には使わない。',
        準備可能率10パーセント未満=sparse, 銘柄別=symbols, 各場=records,
    )
    target = HERE / '準備可能時間の記録.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    print(json.dumps(dict(保存先=str(target), 銘柄別=symbols,
                         短時間の場=[{key: row[key] for key in ('セッション', '銘柄', '新規対象セッション分数', '新規締切までの観測分数', '新規締切までの準備可能分数', '初回準備時刻')}
                                   for row in sparse]), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
