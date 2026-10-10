"""格子とNTペアの全玉会計、数量、相対損益分解を独立に点検する。"""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd

from audit_guard import independent_account
import metrics
import pair_engine

OUT = Path(__file__).resolve().parent
OLD = OUT.parent/'wave_v13'


def load_json(name: str):
    """機能: 保存JSONを読み込む。

    引数: name (str)。返り値: object: 内容。
    """
    return json.loads((OUT/name).read_text(encoding='utf-8'))


def pair_full_account(prepared: dict, result: dict) -> np.ndarray:
    """機能: 個別脚の現金移動を２銘柄の全原本行へ再配置し、非同期約定も含めて評価する。

    引数: prepared/result (dict)。返り値: ndarray: 独立計算の全行評価損益。
    """
    full = result['full_curve']
    count = len(full)
    cash, realized, gross = np.zeros(count), np.zeros(count), np.zeros(count)
    positions, prices, maps = [], [], []
    for symbol_index,tape in enumerate(prepared['tapes']):
        indices = np.flatnonzero(full[:,6] == symbol_index)
        rows = full[indices,7].astype(int)
        assert len(rows) == len(tape['last'])
        mapping = np.full(len(tape['last']),-1,dtype=int)
        mapping[rows] = indices
        maps.append(mapping)
        values = np.full(count,np.nan)
        values[indices] = tape['last'][rows]
        prices.append(pd.Series(values).ffill().fillna(0).to_numpy())
        positions.append(np.zeros(count))
    for leg in result['legs']:
        j = ['NK225','TOPIX'].index(leg['symbol'])
        tape = prepared['tapes'][j]
        entry_row = np.searchsorted(tape['seq'],leg['entry_seq'])
        a = maps[j][entry_row]
        factor = leg['side']*leg['quantity']*leg['multiplier']
        standard = leg['quantity']*leg['multiplier']/(1000 if j == 0 else 10000)
        cash[a] -= factor*leg['entry_price']
        positions[j][a] += factor
        gross[a] += standard
        if leg['complete']:
            exit_row = np.searchsorted(tape['seq'],leg['exit_seq'])
            b = maps[j][exit_row]
            cash[b] += factor*leg['exit_price']
            positions[j][b] -= factor
            gross[b] -= standard
            realized[b] += factor*(leg['exit_price']-leg['entry_price'])
    equity = np.cumsum(cash)
    for position,price in zip(positions,prices):
        equity += np.cumsum(position)*price
    realized = np.cumsum(realized)
    instantaneous_dd = np.maximum.accumulate(np.r_[0.,equity])[1:]-equity
    for expected,actual in [(equity,full[:,3]),(realized,full[:,1]),(equity-realized,full[:,2]),
                            (np.cumsum(gross),full[:,5]),(instantaneous_dd,full[:,4])]:
        np.testing.assert_allclose(expected,actual,rtol=1e-8,atol=1e-5)
    np.testing.assert_allclose(instantaneous_dd.max(),result['summary']['max_drawdown_yen'],atol=1e-5)
    return equity


def audit_pair() -> dict:
    """機能: 全ペア脚と恒等分解、代表４セルの全原本会計と途中境界を点検する。

    引数: なし。返り値: dict: 検査数と成功結果。
    """
    configs = {r['id']:r for r in load_json('NT_固定条件.json')}
    cycles,legs = load_json('NT_サイクル.json'),load_json('NT_全脚.json')
    tapes = {}
    grouped = defaultdict(list)
    for leg in legs:
        key = (leg['session'],leg['symbol'])
        if key not in tapes:
            root = OLD/'live/features' if key[0] == '2026-09-24_Night' else OLD/'features'
            tapes[key] = dict(np.load(root/f'約定系列_{key[1]}_{key[0]}.npz',allow_pickle=False))
        tape = tapes[key]
        config = configs[leg['method']]
        expected_multiplier = (100 if leg['symbol'] == 'NK225' else 1000) if config['mini_price_proxy'] else (1000 if leg['symbol'] == 'NK225' else 10000)
        assert leg['multiplier'] == expected_multiplier
        if config['executable_integer']:
            assert leg['quantity'] == int(leg['quantity'])
        assert leg['quantity'] > 0 and leg['entry_time'] > leg['entry_order']
        for prefix in ['entry','exit']:
            position = int(np.searchsorted(tape['seq'],leg[f'{prefix}_seq']))
            assert tape['seq'][position] == leg[f'{prefix}_seq']
            np.testing.assert_allclose(tape['last'][position],leg[f'{prefix}_price'])
            np.testing.assert_allclose(tape['time_s'][position],leg[f'{prefix}_time'])
        if leg['complete']:
            assert leg['exit_time'] > leg['exit_order']
        expected = leg['side']*leg['quantity']*leg['multiplier']*(leg['exit_price']-leg['entry_price'])
        np.testing.assert_allclose(expected,leg['net_yen'],atol=1e-5)
        grouped[(leg['method'],leg['session'],leg['cycle_id'])].append(leg)
    for cycle in cycles:
        part = grouped[(cycle['method'],cycle['session'],cycle['cycle_id'])]
        assert cycle['complete'] == all(p['complete'] for p in part)
        nk = next(p for p in part if p['symbol'] == 'NK225')
        top = next(p for p in part if p['symbol'] == 'TOPIX')
        an = nk['quantity']*nk['multiplier']*nk['entry_price']
        at = top['quantity']*top['multiplier']*top['entry_price']
        rn = (nk['exit_price']-nk['entry_price'])/nk['entry_price']
        rt = (top['exit_price']-top['entry_price'])/top['entry_price']
        side,beta = nk['side'],cycle['target_beta']
        expected_relative = side*(an+at)*(rn-rt)/2
        expected_common = side*(an-at)*(rn+rt)/2
        expected_beta_relative = side*an*(rn-beta*rt)
        expected_beta_rounding = side*(beta*an-at)*rt
        np.testing.assert_allclose([cycle['relative_yen'],cycle['common_residual_yen'],cycle['beta_relative_yen'],cycle['beta_rounding_yen']],
                                   [expected_relative,expected_common,expected_beta_relative,expected_beta_rounding],atol=1e-5)
        net = sum(p['net_yen'] for p in part)
        np.testing.assert_allclose([net,expected_relative+expected_common,expected_beta_relative+expected_beta_rounding],cycle['net_yen'],atol=1e-5)
        np.testing.assert_allclose(net/cycle['risk_yen'],cycle['net_r'],atol=1e-8)
        np.testing.assert_allclose(sum(p['net_yen'] for p in part if p['complete']),cycle['closed_yen'],atol=1e-5)
        np.testing.assert_allclose(sum(p['net_yen'] for p in part if not p['complete']),cycle['open_yen'],atol=1e-5)
        assert cycle['gross_standard'] <= 20+1e-8
        if cycle['session'] != '2026-09-24_Night':
            assert cycle['complete']
    representatives = [('2026-09-21_Day','NT_ratio_mr_Z1.5_S0'),
                       ('2026-09-23_Night','NT_residual_mr_Z2_S2'),
                       ('2026-09-24_Day','NT_ratio_mom_Z1_S4'),
                       ('2026-09-24_Night','NT_ratio_mom_Z1.5_S5')]
    full_rows, boundaries = 0,0
    for session,method in representatives:
        feature_root = OLD/'live/features' if session == '2026-09-24_Night' else OLD/'features'
        prepared = pair_engine.prepare_session(session,feature_root)
        result = pair_engine.run(prepared,configs[method],detail=True)
        independent = pair_full_account(prepared,result)
        full_rows += len(independent)
        for proportion in [.373,.737]:
            boundary = float(result['full_curve'][int(len(independent)*proportion),0])
            split = pair_engine.split_at_boundary(result,prepared,boundary)
            earlier = result['full_curve'][:,0] < boundary
            baseline = independent[earlier][-1] if earlier.any() else 0.
            np.testing.assert_allclose(split['baseline_equity_yen'],baseline,atol=1e-5)
            np.testing.assert_allclose(split['net_yen'],independent[-1]-baseline,atol=1e-5)
            np.testing.assert_allclose(sum(c['net_yen'] for c in split['cycles']),independent[-1]-baseline,atol=1e-5)
            boundaries += 1
    return dict(全脚数=len(legs),全サイクル数=len(cycles),代表全行会計セル数=len(representatives),
                代表原本と時計行数=full_rows,境界増分比較数=boundaries,数量倍率と２種分解恒等式=True)


def audit_grid() -> dict:
    """機能: 格子代表セルの全行含み損と再配置サイクルを独立に確認する。

    引数: なし。返り値: dict: 代表セル数・脚数・未完了の扱い。
    """
    with (OUT/'格子_再生結果.pkl').open('rb') as stream:
        results = pickle.load(stream)
    with (OUT/'既知入力.pkl').open('rb') as stream:
        inputs = pickle.load(stream)
    configs = {r['id']:r for r in load_json('格子条件一覧.json')}
    methods = ['G01_T10','G02_T10','G10_A05','G18_A05']
    checked,total_legs = 0,0
    for method in methods:
        for session,symbol in [('2026-09-22_Day','TOPIX'),('2026-09-23_Night','NK225'),('2026-09-24_Day','NK225'),('2026-09-24_Night','TOPIX')]:
            result = results[(method,session,symbol)]
            raw = result['raw']
            prices = inputs[(session,symbol)]['last']
            equity,atr,gross,realized,dd,maxdd,maxdda = independent_account(raw,prices)
            mult = 1000 if symbol == 'NK225' else 10000
            summary = result['summary']
            for key,expected in dict(net_yen=equity[-1]*mult,open_yen=(equity[-1]-realized[-1])*mult,
                closed_net_yen=realized[-1]*mult,max_drawdown_yen=maxdd*mult,max_drawdown_atr=maxdda,
                gross_peak=gross.max(),open_count=gross[-1]).items():
                np.testing.assert_allclose(summary[key],expected,rtol=1e-8,atol=1e-5)
            assert gross.max() <= configs[method]['max_legs']
            if session != '2026-09-24_Night':
                assert gross[-1] == 0
            cycles = metrics.from_raw(raw,method,symbol,session,configs[method]['max_legs'],
                                     incomplete_cycle_ids=result['incomplete_cycle_ids'])
            net = metrics.summarize(cycles,[session],'yen')
            np.testing.assert_allclose(net['all_net'],equity[-1]*mult,atol=1e-5)
            assert all(not c['complete'] for c in cycles if c['cycle_id'] in result['incomplete_cycle_ids'])
            total_legs += len(raw)
            checked += 1
    return dict(全行会計セル数=checked,代表脚数=total_legs,継続中心の未完了分離=True)


def main() -> None:
    """機能: 独立監査を実施し、元担当の自己検査と別の記録を作る。

    引数: なし。返り値: None: 格子とNTの独立監査.jsonを保存。API接続なし。
    """
    result = dict(成功=True,格子=audit_grid(),NT=audit_pair(),API取得数=0,
                  SHA256={name:hashlib.sha256((OUT/name).read_bytes()).hexdigest()
                          for name in ['pair_engine.py','grid_engine.py','metrics.py']})
    (OUT/'格子とNTの独立監査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()
