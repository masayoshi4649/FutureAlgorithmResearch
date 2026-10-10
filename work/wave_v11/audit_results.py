"""全数売買を注文器の集計関数を呼ばずに再集計し、選択範囲を検査する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle
import time

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
COMPLETE = ['2026-09-21_Day', '2026-09-21_Night', '2026-09-22_Day',
            '2026-09-22_Night', '2026-09-23_Day']


def equity_by_differences(ready: dict, raw: np.ndarray) -> np.ndarray:
    """機能: 新規と返済の差分配列から全観測時刻の評価・費用倍評価を再構成する。

    引数: ready (dict)、raw (ndarray)。返り値: ndarray。通常点・倍費用点・両ATR・総枚数。
    """
    n, tick = len(ready['seq']), ready['tick']
    delta = np.zeros((n, 9))
    for row in raw:
        side, first, last, scale = row[1], int(row[4]), int(row[5]), row[6]
        quote_column = 0 if side > 0 else 1
        delta[first, quote_column] += side
        delta[first, quote_column+3] += side/scale
        delta[first, 2] += -side*row[7]-2*tick
        delta[first, 5] += (-side*row[7]-2*tick)/scale
        delta[first, 6] += 2*tick
        delta[first, 7] += 2*tick/scale
        delta[first, 8] += 1
        if row[13]:
            delta[last, quote_column] -= side
            delta[last, quote_column+3] -= side/scale
            delta[last, 2] += side*row[8]
            delta[last, 5] += side*row[8]/scale
            delta[last, 8] -= 1
    x = delta.cumsum(axis=0)
    usual = x[:, 0]*ready['bid']+x[:, 1]*ready['ask']+x[:, 2]
    normalized = x[:, 3]*ready['bid']+x[:, 4]*ready['ask']+x[:, 5]
    return np.column_stack([usual, usual-x[:, 6], normalized, normalized-x[:, 7], x[:, 8]])


def expected_summary(ready: dict, raw: np.ndarray, cap: int) -> dict:
    """機能: 全取引の通常費用・倍費用・未返済評価・全行DDを独立計算する。

    引数: ready (dict)、raw (ndarray)、cap (int)。返り値: dict。照合すべき日本語集計列。
    """
    multiplier = 1000 if ready['symbol'] == 'NK225' else 10000
    closed, opened = raw[raw[:, 13] == 1], raw[raw[:, 13] == 0]
    net = closed[:, 14]*multiplier
    values = dict(取引数=len(closed), 未返済数=len(opened), 勝ち数=int((net > 0).sum()),
                  負け数=int((net < 0).sum()), 利益円=float(net[net > 0].sum()),
                  損失円=float(-net[net < 0].sum()), 収支円=float(net.sum()),
                  費用倍収支円=float(closed[:, 15].sum()*multiplier),
                  ATR収支=float(np.sum(closed[:, 14]/closed[:, 6])),
                  費用倍ATR収支=float(np.sum(closed[:, 15]/closed[:, 6])),
                  評価損益円=float(opened[:, 14].sum()*multiplier),
                  費用倍評価損益円=float(opened[:, 15].sum()*multiplier),
                  枚数上限換算収支円=float(net.sum()/cap),
                  枚数上限換算費用倍収支円=float(closed[:, 15].sum()*multiplier/cap))
    curve = equity_by_differences(ready, raw)
    for i, key in enumerate(['全行最大下落円', '費用倍全行最大下落円',
                             '全行最大下落ATR', '費用倍全行最大下落ATR']):
        peak = np.maximum.accumulate(np.r_[0., curve[:, i]])[1:]
        values[key] = float(np.max(peak-curve[:, i])*(multiplier if i < 2 else 1))
    values['最大保有枚数'] = int(curve[:, 4].max())
    assert values['最大保有枚数'] <= cap
    return values


def verify_selection(frame: pd.DataFrame, configs: list[dict], record: dict) -> None:
    """機能: 指定学習期間だけで全候補の得点・適格性・順位を独立再現する。

    引数: frame (DataFrame)、configs (list)、record (dict)。返り値: None。一致しなければ停止。
    """
    eligible = [c for c in configs if all(record.get(label) is None or c.get(field) == record[label]
                for label, field in [('思想', 'philosophy'), ('群', 'group'), ('系統', 'family')])]
    train = record['学習']
    assert train == COMPLETE[:len(train)] and len(train) in (2, 3, 4, 5)
    ranking = []
    for config in eligible:
        pair_scores, pair_trades = [], []
        symbols = [record['選択対象銘柄']] if record.get('選択対象銘柄') else ['NK225', 'TOPIX']
        for symbol in symbols:
            part = frame[(frame.方式 == config['id']) & frame.セッション.isin(train) & frame.銘柄.eq(symbol)]
            assert len(part) == len(train)
            cap = config.get('max_positions', 1)
            pair_scores.append(float(np.sum((part['費用倍ATR収支']-.25*part['費用倍全行最大下落ATR'])/cap)/len(train)))
            pair_trades.append(int(part.取引数.sum()))
        if min(pair_trades) >= 1:
            ranking.append((min(pair_scores), sum(pair_scores), config['id']))
    ranking.sort(key=lambda x: (-x[0], -x[1], x[2]))
    assert {x[2] for x in ranking} == {x['方式'] for x in record['全順位']}
    assert (ranking[0][2] if ranking else None) == (record['採用']['方式'] if record['採用'] else None)
    by_id = {r[2]:r for r in ranking}
    for row in record['全順位']:
        expected = by_id[row['方式']]
        np.testing.assert_allclose([row['主得点'], row['合計得点']], expected[:2])
    # CSV の往復で最下位桁だけ変わる同点候補は、丸め誤差の範囲で順位交換を許す。
    scores = [by_id[r['方式']][0] for r in record['全順位']]
    assert (np.diff(scores) <= 1e-10).all()


def main() -> None:
    """機能: 確定した全条件出力の数量・価格・損益・DD・学習選択を照合する。

    引数: なし。返り値: None。独立監査 JSON を保存する。
    """
    started = time.monotonic()
    protected = ['条件一覧.json', '数値形式.json', '全条件_セッション集計.csv', '全売買数値.npz',
                 '最終選択.json', '時間順選択.json', '実行前記録.json']
    input_hashes = {name:hashlib.sha256((OUT/name).read_bytes()).hexdigest() for name in protected}
    configs = json.loads((OUT/'条件一覧.json').read_text(encoding='utf-8'))
    schema = json.loads((OUT/'数値形式.json').read_text(encoding='utf-8'))
    frame = pd.read_csv(OUT/'全条件_セッション集計.csv').set_index(['方式', 'セッション', '銘柄'], drop=False)
    frozen = json.loads((OUT/'実行前記録.json').read_text(encoding='utf-8'))
    for name, expected in frozen['SHA256'].items():
        assert hashlib.sha256((OUT/name).read_bytes()).hexdigest() == expected, name
    with (OUT/'再生入力.pkl').open('rb') as stream:
        prepared = pickle.load(stream)
    archive = np.load(OUT/'全売買数値.npz')
    blocks = {}
    row_count = 0
    for engine, rows in archive.items():
        row_count += len(rows)
        for key, at in pd.DataFrame(rows[:, :2], columns=['設定', 'セル']).groupby(['設定', 'セル']).indices.items():
            blocks[tuple(map(int, key))] = rows[at, 2:]
    comparisons = 0
    for cell_i, key in enumerate(schema['セル']):
        ready = prepared[tuple(key)]
        for config_i, config in enumerate(configs):
            raw = blocks.get((config_i, cell_i), np.empty((0, 24 if config['engine'] == 'orders' else 21)))
            observed = frame.loc[(config['id'], *key)]
            for row in raw:
                entry, last = int(row[4]), int(row[5])
                assert row[7] == (ready['ask'][entry] if row[1] > 0 else ready['bid'][entry])
                assert row[8] == (ready['bid'][last] if row[1] > 0 else ready['ask'][last])
                np.testing.assert_allclose(row[14:16], row[1]*(row[8]-row[7])-ready['tick']*np.array([2., 4.]))
                quotes = ready['bid'][entry:last+1] if row[1] > 0 else ready['ask'][entry:last+1]
                np.testing.assert_allclose(row[11], max(0., np.max(row[1]*(quotes-row[7]))))
                assert row[2] <= row[3] < row[4]
                if row[13]:
                    assert row[17] < last and ready['time_s'][last] < ready['limit']+300
                assert row[6] > 0
            used_bid, used_ask = np.zeros(len(ready['seq'])), np.zeros(len(ready['seq']))
            for row in raw:
                (used_ask if row[1] > 0 else used_bid)[int(row[4])] += 1
                if row[13]:
                    (used_bid if row[1] > 0 else used_ask)[int(row[5])] += 1
            assert (used_bid <= ready['bid_qty']).all() and (used_ask <= ready['ask_qty']).all()
            for column, expected in expected_summary(ready, raw, config.get('max_positions', 1)).items():
                if column == '費用倍評価損益円' and pd.isna(observed[column]) and config['engine'] == 'single':
                    continue
                np.testing.assert_allclose(observed[column], expected, atol=1e-6, rtol=1e-9,
                                           err_msg=f'{config["id"]} {key} {column}')
                comparisons += 1
        print(f'{key}: {len(configs)} 条件の独立会計一致', flush=True)
    final = json.loads((OUT/'最終選択.json').read_text(encoding='utf-8'))
    walk = json.loads((OUT/'時間順選択.json').read_text(encoding='utf-8'))
    records = list(final['主選択'].values())+list(final['群別代表'].values())+walk
    if '銘柄別主選択' in final:
        records += [r for by_philosophy in final['銘柄別主選択'].values() for r in by_philosophy.values()]
        records += json.loads((OUT/'銘柄別時間順選択.json').read_text(encoding='utf-8'))
    for record in records:
        verify_selection(frame.reset_index(drop=True), configs, record)
    for name, expected in input_hashes.items():
        assert hashlib.sha256((OUT/name).read_bytes()).hexdigest() == expected, f'監査中に変更: {name}'
    for name, expected in frozen['SHA256'].items():
        assert hashlib.sha256((OUT/name).read_bytes()).hexdigest() == expected, f'監査中に変更: {name}'
    result = dict(一致=True, 条件数=len(configs), セル数=len(frame), 全売買数=row_count,
                  集計属性照合数=comparisons, 全順位選択照合数=len(records), 原本API取得数=0,
                  監査入力SHA256=input_hashes, 実装SHA256=frozen['SHA256'],
                  説明='注文器集計を呼ばず全脚価格・費用・最大順行・全生気配の含み損DDを差分配列から独立再計算。',
                  秒=time.monotonic()-started)
    (OUT/'全数損益と学習選択の独立監査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
