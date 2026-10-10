"""一回取得済みの追加区間を全脚の清算価値差から独立に再計算する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

from audit_results import equity_by_differences, expected_summary

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]


def load(name: str) -> object:
    """機能: 保存された JSON を通信せず読む。

    引数: name (str)。返り値: object。復号内容。
    """
    return json.loads((OUT/name).read_text(encoding='utf-8'))


def numeric(ready: dict, rows: list[dict]) -> np.ndarray:
    """機能: 約定辞書を独立会計の入力へ変換し、各脚の観測価格と順序を照合する。

    引数: ready (dict)、rows (list[dict])。返り値: ndarray。24列の会計入力。
    """
    output = np.zeros((len(rows), 24))
    for i, trade in enumerate(rows):
        first = np.searchsorted(ready['seq'], trade['entry_seq'])
        last = np.searchsorted(ready['seq'], trade['exit_seq']) if trade['closed'] else len(ready['seq'])-1
        assert ready['seq'][first] == trade['entry_seq']
        if trade['closed']:
            assert ready['seq'][last] == trade['exit_seq']
        side, quote = trade['side'], ready['bid'] if trade['side'] > 0 else ready['ask']
        entry = ready['ask'][first] if side > 0 else ready['bid'][first]
        assert entry == trade['entry_price']
        np.testing.assert_allclose(quote[last], trade['exit_price'] if trade['closed'] else trade['mark_price'])
        assert trade['source_last_seq'] <= trade['signal_seq'] <= trade['condition_seq'] <= trade['trigger_seq'] < trade['entry_seq']
        if trade['closed']:
            assert trade['entry_seq'] <= trade['exit_trigger_seq'] < trade['exit_seq']
        net = side*(quote[last]-entry)-2*ready['tick']
        np.testing.assert_allclose([net, net-2*ready['tick']], [trade['net_points'], trade['stress_points']])
        np.testing.assert_allclose(max(0., np.max(side*(quote[first:last+1]-entry))), trade['max_favorable'])
        output[i, [1, 4, 5, 6, 7, 8, 11, 13, 14, 15]] = [side, first, last, trade['atr'], entry,
            quote[last], trade['max_favorable'], trade['closed'], net, net-2*ready['tick']]
    return output


def boundary(ready: dict, raw: np.ndarray, index: int) -> dict:
    """機能: 指定気配までの確定収支と保有全脚の清算可能価値を区別する。

    引数: ready (dict)、raw (ndarray)、index (int)。返り値: dict。境界での会計値。
    """
    multiplier = 1000 if ready['symbol'] == 'NK225' else 10000
    closed = raw[(raw[:, 13] == 1) & (raw[:, 5] <= index)]
    held = raw[(raw[:, 4] <= index) & ((raw[:, 13] == 0) | (raw[:, 5] > index))]
    mark = sum(r[1]*((ready['bid'][index] if r[1] > 0 else ready['ask'][index])-r[7])-2*ready['tick'] for r in held)*multiplier
    realized = closed[:, 14].sum()*multiplier
    return dict(清算円=float(realized+mark), 評価円=float(mark), 確定円=float(realized),
                費用倍清算円=float(closed[:, 15].sum()*multiplier+mark-len(held)*2*ready['tick']*multiplier),
                未返済数=len(held))


def main() -> None:
    """機能: 凍結・６要求・54セルの確定分、含み損、追加区間の増分を独立監査する。

    引数: なし。返り値: None。現在照合_会計独立監査.json を保存する。
    """
    frozen = load('現在照合_凍結記録.json')
    receipt = load('live/取得記録.json')
    frozen_path = OUT/'現在照合_凍結記録.json'
    assert hashlib.sha256(frozen_path.read_bytes()).hexdigest() == receipt['manifest_sha256']
    assert (OUT/'live/凍結記録の写し.json').read_bytes() == frozen_path.read_bytes()
    for name, digest in frozen['files_sha256'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == digest, name
    assert pd.Timestamp(frozen['fixed_at']) <= pd.Timestamp(receipt['started_at'])
    requests = receipt['requests']
    assert len(requests) == 6 and len({r['name'] for r in requests}) == 6
    assert len(list((OUT/'live/要求記録').glob('*.json'))) == 6
    for request in requests:
        assert request['attempts'] == 1 and request['http_status'] == 200 and request['ok']
        assert pd.Timestamp(request['started_at']) >= pd.Timestamp(frozen['fixed_at'])
        query = parse_qs(urlparse(request['url']).query)
        assert query['from'] == [frozen['starts_at']] and query['to'] == [receipt['cutoff']]
        saved = (ROOT/request['path']).read_bytes()
        assert len(saved) == request['bytes'] and hashlib.sha256(saved).hexdigest() == request['sha256']
    trades = load('現在照合_全取引.json')
    curves = load('現在照合_評価曲線.json')
    frames = {name:pd.read_csv(OUT/f'現在照合_{name}.csv').set_index(['方式', '銘柄'])
              for name in ['セッション集計', '全体参考集計', '新信号起源集計', '既知起源集計']}
    configs = {c['id']:c for c in frozen['selected_configs']}
    known, cutoff = pd.Timestamp(frozen['known_cutoff']).timestamp(), pd.Timestamp(receipt['cutoff']).timestamp()
    reports, attributes = [], 0
    for symbol in ['NK225', 'TOPIX']:
        ready = dict(np.load(OUT/f'live/features/約定系列_{symbol}_{frozen["session"]}.npz'))
        ready['symbol'] = symbol
        ready['tick'] = 10. if symbol == 'NK225' else .5
        assert ready['time_s'][-1] < cutoff
        multiplier = 1000 if symbol == 'NK225' else 10000
        previous = np.searchsorted(ready['time_s'], known, side='left')-1
        for key in frozen['selected_ids']:
            selected = [r for r in trades if r['方式'] == key and r['銘柄'] == symbol]
            raw = numeric(ready, selected)
            used_bid, used_ask = np.zeros(len(ready['seq'])), np.zeros(len(ready['seq']))
            for row in raw:
                (used_ask if row[1] > 0 else used_bid)[int(row[4])] += 1
                if row[13]:
                    (used_bid if row[1] > 0 else used_ask)[int(row[5])] += 1
            assert (used_bid <= ready['bid_qty']).all() and (used_ask <= ready['ask_qty']).all()
            cap = configs[key].get('max_positions', 1)
            whole = expected_summary(ready, raw, cap)
            for name, expected in whole.items():
                observed = frames['全体参考集計'].loc[(key, symbol), name]
                if name == '費用倍評価損益円' and pd.isna(observed) and configs[key]['engine'] == 'single':
                    continue
                np.testing.assert_allclose(observed, expected, atol=1e-6, rtol=1e-9)
                attributes += 1
            values = equity_by_differences(ready, raw)
            saved_curve = np.array(curves[f'{key}|{frozen["session"]}|{symbol}'])
            locations = np.searchsorted(ready['seq'], saved_curve[:, 1])
            observed_curve = values[locations, :].copy()
            observed_curve[:, :2] *= multiplier
            np.testing.assert_allclose(saved_curve[:, 2:7], observed_curve, atol=1e-6, rtol=1e-9)
            before, after = boundary(ready, raw, previous), boundary(ready, raw, len(ready['seq'])-1)
            completed = [r for r in selected if r['closed'] and r['exit_time_s'] >= known]
            nets = np.array([r['net_points']*multiplier for r in completed])
            wanted = dict(追加清算価値円=after['清算円']-before['清算円'],
                費用倍追加清算価値円=after['費用倍清算円']-before['費用倍清算円'],
                枚数上限換算追加円=(after['清算円']-before['清算円'])/cap,
                開始清算価値円=before['清算円'], 終了清算価値円=after['清算円'],
                開始未返済数=before['未返済数'], 終了未返済数=after['未返済数'],
                開始評価損益円=before['評価円'], 終了評価損益円=after['評価円'],
                区間内返済数=len(completed), 区間内確定利益円=float(nets[nets > 0].sum()),
                区間内確定損失円=float(-nets[nets < 0].sum()), 区間内確定収支円=float(nets.sum()),
                区間内新規脚数=sum(r['entry_time_s'] >= known for r in selected),
                新信号起源脚数=sum(r['signal_time_s'] >= known for r in selected))
            for new in [False, True]:
                group = [r for r in selected if (r['signal_time_s'] >= known) == new]
                part = numeric(ready, group)
                group_before, group_after = boundary(ready, part, previous), boundary(ready, part, len(ready['seq'])-1)
                wanted['新信号起源追加円' if new else '旧起源追加円'] = group_after['清算円']-group_before['清算円']
                output = frames['新信号起源集計' if new else '既知起源集計'].loc[(key, symbol)]
                for name, expected in [('収支円', group_after['確定円']), ('評価損益円', group_after['評価円']),
                                       ('未返済数', group_after['未返済数'])]:
                    np.testing.assert_allclose(output[name], expected, atol=1e-6)
                    attributes += 1
            for name, expected in wanted.items():
                np.testing.assert_allclose(frames['セッション集計'].loc[(key, symbol), name], expected, atol=1e-6)
                attributes += 1
            assert np.isclose(wanted['追加清算価値円'], wanted['新信号起源追加円']+wanted['旧起源追加円'])
            reports.append(dict(方式=key, 銘柄=symbol, 全脚数=len(selected), **wanted))
    result = dict(一致=True, 凍結ファイル数=len(frozen['files_sha256']), 要求数=len(requests),
                  監査中API取得数=0, 全脚数=len(trades), セル数=len(reports), 属性照合数=attributes,
                  既知境界=frozen['known_cutoff'], 取得末尾=receipt['cutoff'], 検査=reports)
    (OUT/'現在照合_会計独立監査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k != '検査'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
