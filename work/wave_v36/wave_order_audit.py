"""全429条件の指定波を、注文会計と原本価格から独立に再計算する。"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import pickle
import socket
import urllib.request

import numpy as np

import band_runner as runner
import chart_wave_design as design

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def deny_network() -> None:
    """機能: 保存台帳の検算から外部通信を禁止する。

    引数: なし。返り値: なし (None)。
    """
    socket.socket.connect = runner.reject_network
    socket.create_connection = runner.reject_network
    urllib.request.OpenerDirector.open = runner.reject_network


def freeze() -> dict:
    """機能: 全429条件の検算対象と独立会計式を新損益前に固定する。

    引数: なし。返り値: 固定記録 (dict)。
    """
    fixed=design.prepare()
    paths=[Path(__file__),HERE/'chart_wave_fixed.json',HERE.parent/'wave_v23/inputs.pkl']
    value=dict(対象=[dict(id=r['spec']['id'],destination=r['destination']) for r in fixed['対象']],
        主条件数=364,補助条件数=65,全条件数=429,全指定波数=3432,比較境界数=6864,
        SHA256={p.relative_to(ROOT).as_posix():runner.digest(p) for p in paths})
    path=HERE/'wave_order_fixed.json'
    if path.exists(): assert runner.read(path)==value
    else: runner.save(path,value)
    return value


# ----------------------------------------
# v35の監査済み独立式を複写。売買エンジンの内部集計を呼び出さない。
def reconstruct(ready: dict, ledger: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """機能: 全注文の約定を符号付き現金と両保有へ、全返済の価格差を実現損益へ積算する。

    引数: ready/ledger (dict)。返り値: 現金・買い在庫・売り在庫・実現損益 (tuple[ndarray,...])。
    """
    n = len(ready['last'])
    moves = np.zeros((n, 4))
    orders = np.asarray(ledger['orders'], dtype=float).reshape(-1, 8)
    for row, source, _, side, qty, price, _, opening in orders:
        index = int(row)
        assert 0 <= source < row < n and qty >= 1 and qty == int(qty)
        moves[index, 0] -= side * qty * price
        held_side = side if opening else -side
        moves[index, 1 if held_side == 1 else 2] += qty if opening else -qty
    for trade in np.asarray(ledger['trades'], dtype=float).reshape(-1, 11):
        value = trade[2] * trade[3] * (trade[5] - trade[4])
        np.testing.assert_allclose(value, trade[10], atol=1e-9, rtol=0)
        moves[int(trade[7]), 3] += value
    cash, long, short, realized = np.cumsum(moves, axis=0).T
    cap = ledger['config']['audit_cap']
    assert np.all((long >= 0) & (short >= 0) & (long <= cap) & (short <= cap))
    assert long[-1] == short[-1] == 0
    np.testing.assert_allclose(cash[-1], realized[-1], atol=1e-6, rtol=0)
    endrow = np.searchsorted(ready['time_s'], ready['limit'], side='left') + 1
    assert not (long[endrow:] + short[endrow:]).any()
    return cash, long, short, realized


def measure(ready: dict, ledger: dict, expected: dict, accounts: tuple) -> dict:
    """機能: 一波の境界損益・正逆保有分・枚数分・区間注文を独立算出する。

    引数: ready/ledger/expected (dict)、accounts (tuple)。返り値: 波の検算値 (dict)。
    """
    start, end = (datetime.fromisoformat(expected[key]).timestamp() for key in ('開始', '終了'))
    times, prices, side = ready['time_s'], ready['last'], expected['波方向']
    cash, long, short, realized = accounts
    point = ledger['config']['point_value']
    values = {}
    for label, stamp in (('開始境界', start), ('終了境界', end)):
        index = int(np.searchsorted(times, stamp, side='right') - 1)
        equity = cash[index] + (long[index] - short[index]) * prices[index]
        actual = {'参照行': index, 'seq': int(ready['seq'][index]), 'last': float(prices[index]),
                  '買い枚数': int(long[index]), '売り枚数': int(short[index]), 'ネット枚数': int(long[index] - short[index]),
                  '時価損益円': float(equity * point), '実現損益円': float(realized[index] * point),
                  '含み損益円': float((equity - realized[index]) * point)}
        for key, value in actual.items():
            np.testing.assert_allclose(value, expected[label][key], atol=1e-6, rtol=0, err_msg=label + key)
        values[label] = actual
    weights = np.maximum(0., np.minimum(times[1:], end) - np.maximum(times[:-1], start)) / 60
    integrate = lambda column: float(np.dot(weights, np.asarray(column[:-1], dtype=float)))
    forward, opposite = (long, short) if side > 0 else (short, long)
    net = (long - short) * side
    measured = {'正方向ネット保有分': integrate(net > 0), '逆方向ネット保有分': integrate(net < 0),
                'ネット中立分': integrate(net == 0), '正方向脚保有分': integrate(forward > 0), '逆方向脚保有分': integrate(opposite > 0),
                '正方向枚数分': integrate(forward), '逆方向枚数分': integrate(opposite),
                '両建て保有分': integrate((forward > 0) & (opposite > 0))}
    for key, value in measured.items():
        np.testing.assert_allclose(value, expected[key], atol=1e-6, rtol=0, err_msg=key)
    for field in ('時価損益', '実現損益', '含み損益'):
        measured[field + '差円'] = values['終了境界'][field + '円'] - values['開始境界'][field + '円']
        np.testing.assert_allclose(measured[field + '差円'], expected[field + '差円'], atol=1e-6, rtol=0)
    assert (measured['正方向ネット保有分'] >= 20 - 1e-9) == expected['正方向ネット20分目安達成']
    orders = np.asarray(ledger['orders'], dtype=float).reshape(-1, 8)
    when = times[orders[:, 0].astype(int)]
    for opening, label in ((1, '区間内新規'), (0, '区間内返済')):
        selected = orders[(when >= start) & (when <= end) & (orders[:, 7] == opening)]
        assert len(selected) == len(expected[label])
        for raw, record in zip(selected, expected[label]):
            np.testing.assert_array_equal(raw[[0, 1, 3, 4, 5]], [record['原本行'], record['発注元行'], record['direction'], record['枚数'], record['価格']])
    return {'method': expected['method'], 'wave': expected['wave'], 'session': expected['session'], 'symbol': expected['symbol'],
            **values, **measured, '保存値一致': True, '位置付け': '初期6セッションの目的適合参考'}


def synthetic() -> dict:
    """機能: 部分返済・時価境界・枚数分の人工値と壊れた保存値の拒否を検査する。

    引数: なし。返り値: 成功記録 (dict)。新相場の再生は行わない。
    """
    ready=dict(last=np.array([99.,100.,103.,105.,110.,110.]),time_s=np.arange(6)*60.,
        seq=np.arange(6,dtype=np.int64),limit=240.)
    ledger=dict(config=dict(audit_cap=10,point_value=1.),
        orders=[[1,0,0,1,2,100,0,1],[3,2,0,-1,1,105,2,0],[4,3,0,-1,1,110,1,0]],
        trades=[[0,0,1,1,100,105,1,3,0,2,5],[0,0,1,1,100,110,1,4,0,1,10]])
    accounts=reconstruct(ready,ledger)
    cash,long,short,realized=accounts
    np.testing.assert_array_equal(long,[0,2,2,1,0,0])
    np.testing.assert_array_equal(short,[0]*6)
    assert cash[-1]==realized[-1]==15.
    expected=dict(method='人工',wave='人工波',session='人工',symbol='TOPIX',
        開始='1970-01-01T00:01:00+00:00',終了='1970-01-01T00:04:00+00:00',波方向=1,
        開始境界=dict(参照行=1,seq=1,last=100.,買い枚数=2,売り枚数=0,ネット枚数=2,
            時価損益円=0.,実現損益円=0.,含み損益円=0.),
        終了境界=dict(参照行=4,seq=4,last=110.,買い枚数=0,売り枚数=0,ネット枚数=0,
            時価損益円=15.,実現損益円=15.,含み損益円=0.),
        正方向ネット保有分=3.,逆方向ネット保有分=0.,ネット中立分=0.,正方向脚保有分=3.,逆方向脚保有分=0.,
        正方向枚数分=5.,逆方向枚数分=0.,両建て保有分=0.,時価損益差円=15.,実現損益差円=15.,含み損益差円=0.,
        正方向ネット20分目安達成=False,
        区間内新規=[dict(原本行=1,発注元行=0,direction=1,枚数=2,価格=100.)],
        区間内返済=[dict(原本行=3,発注元行=2,direction=-1,枚数=1,価格=105.),
                   dict(原本行=4,発注元行=3,direction=-1,枚数=1,価格=110.)])
    measure(ready,ledger,expected,accounts)
    rejected=0
    for field in ('正方向枚数分','時価損益差円'):
        bad=deepcopy(expected);bad[field]+=1.
        try: measure(ready,ledger,bad,accounts)
        except AssertionError: rejected+=1
    bad=deepcopy(ledger);bad['orders'][0][1]=1
    try: reconstruct(ready,bad)
    except AssertionError: rejected+=1
    bad=deepcopy(expected);bad['区間内返済'].pop()
    try: measure(ready,ledger,bad,accounts)
    except AssertionError: rejected+=1
    assert rejected==4
    return dict(全合格=True,部分返済と現金在庫実現値=True,波境界と保有枚数分=True,壊れた保存値拒否数=4)


def main() -> None:
    """機能: 主364と補助65の全波を再計算し、期間要約の通過数まで照合する。

    引数: --prepare (bool)。返り値: なし (None)。売買エンジンは呼ばない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true')
    args=parser.parse_args();deny_network();fixed=freeze()
    runner.save(HERE/'wave_order_synthetic.json',synthetic())
    if args.prepare:
        print('全3432波・6864境界を結果前固定、人工と破損拒否4件通過。',flush=True)
        return
    assert runner.read(HERE/'主再生の完了.json')['全条件数']==364
    assert runner.read(HERE/'supplementary/主再生の完了.json')['全条件数']==65
    rules=design.prepare();waves_by_id={w['id']:w for w in rules['指定波']}
    inputs=pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    output,hashes,passes=[],{},{}
    for item in fixed['対象']:
        identifier,destination=item['id'],item['destination']
        folder=HERE/destination
        paths={kind:folder/kind/(identifier+suffix) for kind,suffix in
            (('ledgers','.json.gz'),('waves','.json.gz'),('summaries','.json'))}
        for p in paths.values(): hashes[p.relative_to(HERE).as_posix()]=runner.digest(p)
        ledgers={(r['session'],r['symbol']):r for r in runner.read(paths['ledgers'])}
        saved=runner.read(paths['waves']);summary=runner.read(paths['summaries'])
        expected_keys={(identifier,w['id'],w['session'],symbol) for w in rules['指定波'] for symbol in runner.SYMBOLS}
        assert len(saved)==8 and {(r['method'],r['wave'],r['session'],r['symbol']) for r in saved}==expected_keys
        accounts={};count=0
        for row in saved:
            wave=waves_by_id[row['wave']]
            assert row['開始']==wave['start'] and row['終了']==wave['end'] and row['波方向']==wave['side']
            key=(row['session'],row['symbol'])
            if key not in accounts: accounts[key]=reconstruct(inputs[key],ledgers[key])
            result=measure(inputs[key],ledgers[key],row,accounts[key])
            result['診断区分']='補助' if destination else '主・時計・約定'
            passed=result['正方向ネット保有分']>=20.-1e-9
            result['正方向ネット20分目安達成']=bool(passed);count+=int(passed)
            output.append(result)
        assert count==summary['wave_passes']
        passes[identifier]=count
        if len(passes)%25==0: print(f'独立波 {len(passes)}/429',flush=True)
    assert len(output)==3432 and len(passes)==429
    for name,sha in hashes.items(): assert runner.digest(HERE/name)==sha
    assert freeze()==fixed
    runner.save(HERE/'wave_order_audit.json',dict(全合格=True,主条件数=364,補助条件数=65,全条件数=429,
        全指定波数=3432,比較境界数=6864,注文独立会計一致=True,保有時間枚数分一致=True,
        区間内全注文一致=True,波定義全件一致=True,全通過数一致=True,条件別通過数=passes,結果=output,
        固定SHA256=runner.digest(HERE/'wave_order_fixed.json'),保存資料SHA256=hashes,
        API取得数=0,現在保存物使用=False,注文器再生=False))
    (HERE/'wave_order_audit.md').write_text('# 指定波の独立注文検算\n\n主364条件と補助65条件、合計3432波・6864境界を注文からの現金と両在庫で再計算した。時価・実現・含み差、正逆保有分、枚数分、全区間注文、20分目安と期間要約の通過数が全件一致。売買エンジンの集計やSHAだけを根拠にした検査ではない。\n\n4波は初期6の既知目的適合参考であり、後7や未知成績の証明ではない。現在データ・API・追加の売買再生は使用していない。\n',encoding='utf-8')
    print('全3432波・6864境界の独立注文計算が一致。',flush=True)


if __name__=='__main__':
    main()


