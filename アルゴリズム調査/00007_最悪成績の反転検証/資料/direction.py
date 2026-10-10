"""過去の最悪条件を選び、予測方向だけを反転して通常の注文管理を再生する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle
import sys
import time

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
V11 = OUT.parent / 'wave_v11'
sys.path.insert(0, str(V11))
import catalog
import research
import signals
import single

COMPLETE = research.COMPLETE
SYMBOLS = research.SYMBOLS
METRICS = {'枚数上限換算': '枚数上限換算収支円', '実額': '収支円'}


def sha256(path: Path) -> str:
    """機能: 保存ファイルの内容ハッシュを計算する。

    引数: path (Path)。返り値: SHA256の16進文字列 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def select_worst(frame: pd.DataFrame, mapping: dict) -> list[dict]:
    """機能: 完全な過去区間だけから、各思想・対象・尺度の最悪条件を選ぶ。

    引数: frame (DataFrame)、mapping (dict)。返り値: 採用条件と学習範囲 (list[dict])。
    各対象銘柄に返済済み取引が１件以上ある条件に限り、同点は条件ID昇順で決める。
    """
    choices = []
    for n in [2, 3, 4, 5]:
        train = COMPLETE[:n]
        for philosophy in catalog.PHILOSOPHIES:
            ids = [key for key, cfg in mapping.items() if cfg['philosophy'] == philosophy]
            for target in ['両銘柄', *SYMBOLS]:
                symbols = SYMBOLS if target == '両銘柄' else [target]
                part = frame.loc[frame.セッション.isin(train) & frame.方式.isin(ids) & frame.銘柄.isin(symbols)]
                counts = part.groupby(['方式', '銘柄']).取引数.sum().unstack().reindex(columns=symbols).fillna(0)
                valid = counts.index[(counts >= 1).all(axis=1)]
                part = part.loc[part.方式.isin(valid)]
                for metric, field in METRICS.items():
                    totals = part.groupby('方式').agg(選択得点=(field, 'sum'), 実額収支円=('収支円', 'sum'),
                                                        上限換算収支円=('枚数上限換算収支円', 'sum'),
                                                        取引数=('取引数', 'sum')).reset_index()
                    totals = totals.sort_values(['選択得点', '方式'], kind='stable')
                    if totals.empty:
                        raise ValueError('取引のある最悪条件がありません。')
                    row = totals.iloc[0].to_dict()
                    cfg = mapping[row['方式']]
                    eligible = cfg['engine'] == 'single' or bool(cfg.get('signal_family'))
                    choices.append(dict(学習セッション数=n, 学習セッション=train, 評価セッション=COMPLETE[n] if n < 5 else None,
                                        思想=philosophy, 対象=target, 選択尺度=metric, 候補条件数=len(totals),
                                        方向反転対象=eligible, 不適用理由=None if eligible else '方向予測を持たない純注文方式', **row))
    return choices


def inverted_ready(ready: dict, config: dict) -> dict:
    """機能: 信号発生時刻と市場状態を維持し、選んだ予測の方向だけを反転する。

    引数: ready/config (dict)。返り値: 元入力を変更しない反転後入力 (dict)。
    損切り・利確・追跡は通常の規則で反転後の建玉へ適用する。
    """
    family_key = config.get('signal_family') or config['family']
    original = ready['families'].get(family_key)
    if original is None:
        return ready
    changed = dict(original, sides=-original['sides'],
                   rows=[dict(row, side=-row['side']) for row in original['rows']])
    return dict(ready, families=dict(ready['families'], **{family_key: changed}))


def load_saved_inputs() -> dict:
    """機能: 元検証の保存入力と、既に閲覧済みの01:53保存データを読み込む。

    引数: なし。返り値: データ区分・セッション・銘柄をキーとする入力 (dict)。
    API通信や旧成果物の再生成は行わない。
    """
    with (V11 / '再生入力.pkl').open('rb') as stream:
        original = pickle.load(stream)
    prepared = {(('完全５セッション' if session in COMPLETE else '既知ナイト00:02'), session, symbol): ready
                for (session, symbol), ready in original.items()}
    session = research.KNOWN_PARTIAL
    old_candles, old_features = dict(signals.CANDLE_OVERRIDES), dict(signals.FEATURE_OVERRIDES)
    try:
        signals.CANDLE_OVERRIDES[session] = V11 / 'live'
        signals.FEATURE_OVERRIDES[session] = V11 / 'live' / 'features'
        recent = research.prepared_inputs(signals.load_inputs([session]))
    finally:
        signals.CANDLE_OVERRIDES.clear()
        signals.CANDLE_OVERRIDES.update(old_candles)
        signals.FEATURE_OVERRIDES.clear()
        signals.FEATURE_OVERRIDES.update(old_features)
    for (session, symbol), ready in recent.items():
        prepared[('既読ナイト01:53全体', session, symbol)] = ready
    with (OUT / '既読ナイト入力.pkl').open('wb') as stream:
        pickle.dump(recent, stream, protocol=pickle.HIGHEST_PROTOCOL)
    return prepared


def enrich(row: dict, curve: np.ndarray, dataset: str, reverse: bool) -> dict:
    """機能: 確定収支と未返済評価を合算し、データ区分と反転区分を付ける。

    引数: row (dict)、curve (ndarray)、dataset (str)、reverse (bool)。返り値: 集計 (dict)。
    """
    return dict(row, データ区分=dataset, 方向='予測方向反転' if reverse else '元の方向',
                清算価値円=float(curve[-1, 2]), 費用倍清算価値円=float(curve[-1, 3]),
                費用倍評価損益円=float(curve[-1, 3]) - row['費用倍収支円'])


def comparison_rows(choices: list[dict], frame: pd.DataFrame) -> pd.DataFrame:
    """機能: 選択に用いた過去と直後の評価を、元方向・反転方向で比較する。

    引数: choices (list[dict])、frame (DataFrame)。返り値: 用途別比較表 (DataFrame)。
    """
    output = []
    columns = ['取引数', '未返済数', '勝ち数', '負け数', '利益円', '損失円', '収支円',
               '費用倍収支円', '評価損益円', '清算価値円', '費用倍清算価値円']
    for choice in choices:
        if not choice['方向反転対象']:
            continue
        symbols = SYMBOLS if choice['対象'] == '両銘柄' else [choice['対象']]
        select = frame.loc[(frame.方式 == choice['方式']) & frame.銘柄.isin(symbols)]
        periods = [('選択に使った過去', '完全５セッション', choice['学習セッション'])]
        if choice['評価セッション']:
            periods.append(('直後１セッション', '完全５セッション', [choice['評価セッション']]))
        else:
            periods += [('既知ナイト00:02', '既知ナイト00:02', [research.KNOWN_PARTIAL]),
                        ('既読ナイト01:53全体', '既読ナイト01:53全体', [research.KNOWN_PARTIAL])]
        for purpose, dataset, sessions in periods:
            part = select.loc[(select.データ区分 == dataset) & select.セッション.isin(sessions)]
            for direction, rows in part.groupby('方向'):
                totals = rows[columns].sum().to_dict()
                cap = rows.設定最大枚数.iloc[0]
                output.append(dict(学習セッション数=choice['学習セッション数'], 思想=choice['思想'],
                                    対象=choice['対象'], 選択尺度=choice['選択尺度'], 方式=choice['方式'],
                                    集計用途=purpose, 評価セッション='、'.join(sessions), 方向=direction,
                                    設定最大枚数=cap, 上限換算清算価値円=totals['清算価値円']/cap,
                                    上限換算費用倍清算価値円=totals['費用倍清算価値円']/cap, **totals))
    return pd.DataFrame(output)


def check_transform(ready: dict, inverted: dict, config: dict) -> int:
    """機能: 反転が方向だけを変え、２回適用で元入力へ戻ることを検査する。

    引数: ready/inverted/config (dict)。返り値: 検査した信号件数 (int)。
    """
    key = config.get('signal_family') or config['family']
    if key not in ready['families']:
        assert inverted is ready
        return 0
    original, reverse = ready['families'][key], inverted['families'][key]
    twice = inverted_ready(inverted, config)['families'][key]
    assert np.array_equal(reverse['sides'], -original['sides'])
    assert np.array_equal(twice['sides'], original['sides'])
    assert twice['rows'] == original['rows']
    for field in ['indices', 'times', 'deadlines']:
        assert reverse[field] is original[field]
    for field in ['seq', 'time_s', 'bid', 'ask', 'atr', 'board_side', 'trend_side']:
        assert inverted[field] is ready[field]
    assert [row['side'] for row in reverse['rows']] == list(reverse['sides'])
    return len(original['sides'])


def main() -> None:
    """機能: 最悪条件選択、方向反転再生、時系列比較と因果順序監査を保存する。

    引数: なし。返り値: なし (None)。既読データによる追加探索であり未見検証ではない。
    """
    started = time.monotonic()
    OUT.mkdir(parents=True, exist_ok=True)
    mapping = {cfg['id']: cfg for cfg in catalog.configs()}
    original_frame = pd.read_csv(V11 / '全条件_セッション集計.csv')
    choices = select_worst(original_frame, mapping)
    single.save(OUT / '最悪条件選択.json', choices)
    pd.DataFrame([{k: v for k, v in row.items() if k != '学習セッション'} for row in choices]).to_csv(
        OUT / '最悪条件選択.csv', index=False, encoding='utf-8-sig')
    ids = sorted({choice['方式'] for choice in choices if choice['方向反転対象']})
    single.save(OUT / '方向反転_条件一覧.json', [mapping[key] for key in ids])
    protected = [V11 / path for path in ['signals.py', 'single.py', 'orders.py', 'accounting.py', 'catalog.py',
                                        'research.py', '全条件_セッション集計.csv', '再生入力.pkl',
                                        '現在照合_凍結記録.json', '現在照合_取得記録.json']]
    hashes = {str(path): sha256(path) for path in protected}
    single.save(OUT / '方向反転_設計記録.json', dict(条件数=len(ids), 条件ID=ids, 選択数=len(choices),
        実装SHA256=sha256(Path(__file__)), 使用データSHA256=hashes, API取得数=0,
        選択='各思想×対象銘柄×先頭2/3/4/5完全セッション×実額/設定枚数上限換算で元方式最悪を選ぶ。同点ID昇順。',
        反転='確定信号のsideだけ反転し、反転側で通常の入口・損切り・追跡・利確・リスク上限を再計算。',
        注意='全期間とも既に閲覧済み。過去選択→直後評価は計算上の時間順比較であり新規の未見検証ではない。'))
    print(f'最悪選択 {len(choices)} 件、逆信号条件 {len(ids)} 個: {ids}', flush=True)
    prepared = load_saved_inputs()
    rows, trades, curves, checks = [], [], {}, []
    for (dataset, session, symbol), ready in prepared.items():
        for key in ids:
            config = mapping[key]
            reverse = inverted_ready(ready, config)
            event_count = check_transform(ready, reverse, config)
            for flipped, current in [(False, ready), (True, reverse)]:
                row, raw, curve = research.run_one(current, config)
                enriched = enrich(row, curve, dataset, flipped)
                rows.append(enriched)
                if session in COMPLETE:
                    assert row['未返済数'] == 0
                if not flipped and dataset != '既読ナイト01:53全体':
                    reference = original_frame.loc[(original_frame.方式 == key) & (original_frame.セッション == session)
                                                   & (original_frame.銘柄 == symbol)].iloc[0]
                    for field in ['取引数', '利益円', '損失円', '収支円', '費用倍収支円', '評価損益円']:
                        assert np.isclose(row[field], reference[field]), (key, session, symbol, field)
                records = research.trade_records(current, config, raw)
                for trade in records:
                    assert trade['source_last_seq'] < trade['signal_seq'] <= trade['condition_seq'] <= trade['trigger_seq'] < trade['entry_seq']
                    if trade['closed']:
                        assert trade['entry_seq'] <= trade['exit_trigger_seq'] < trade['exit_seq'] and trade['exit_in_session']
                    trades.append(dict(trade, データ区分=dataset, 方向='予測方向反転' if flipped else '元の方向'))
                curves[f'{dataset}|{key}|{session}|{symbol}|{int(flipped)}'] = curve
            checks.append(dict(データ区分=dataset, セッション=session, 銘柄=symbol, 方式=key,
                               反転信号数=event_count, 二回反転一致=True, 元方向既存一致=dataset != '既読ナイト01:53全体'))
        print(f'{dataset} {session} {symbol}: 完了 {time.monotonic()-started:.1f}秒', flush=True)
    frame = pd.DataFrame(rows)
    frame.to_csv(OUT / '方向反転_セッション集計.csv', index=False, encoding='utf-8-sig')
    comparison = comparison_rows(choices, frame)
    comparison.to_csv(OUT / '方向反転_選択評価.csv', index=False, encoding='utf-8-sig')
    single.save(OUT / '方向反転_全取引.json', trades)
    single.save(OUT / '方向反転_評価曲線.json', curves)
    for path in protected:
        assert sha256(path) == hashes[str(path)], f'既存ファイル変更: {path}'
    single.save(OUT / '方向反転_監査.json', dict(合格=True, 条件数=len(ids), 集計数=len(rows),
        反転売買脚数=sum(trade['方向'] == '予測方向反転' for trade in trades),
        元方向売買脚数=sum(trade['方向'] == '元の方向' for trade in trades), 秒=time.monotonic()-started, API取得数=0,
        既存ファイル不変=True, 変換検査=checks, 未見データ検証=False))
    print('方向反転再生と選択・評価比較を保存しました。', flush=True)


if __name__ == '__main__':
    main()
