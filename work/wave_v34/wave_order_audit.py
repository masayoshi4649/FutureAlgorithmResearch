"""全192条件の指定1536波を、保存注文からの現金・在庫で独立に検算する。"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
from pathlib import Path
import pickle
import socket
import urllib.request

import numpy as np

import scheduler_runner as runner
import chart_wave_design as design

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def deny_network() -> None:
    """機能: APIを含む全外部接続を拒否する。

    引数: なし。返り値: なし (None)。
    """
    socket.socket.connect = runner.wave_metrics.reject_network
    socket.create_connection = runner.wave_metrics.reject_network
    urllib.request.OpenerDirector.open = runner.wave_metrics.reject_network


def freeze() -> dict:
    """機能: 結果前の対象と本検算コード・元入力の指紋を結び付ける。

    引数: なし。返り値: 固定記録 (dict)。
    """
    frozen = design.prepare()
    paths = [Path(__file__), HERE / 'chart_wave_fixed.json', HERE.parent / 'wave_v23/inputs.pkl']
    record = {'対象': [row['id'] for row in frozen['全条件']], '全指定波数': 1536, '比較境界数': 3072,
              'SHA256': {p.relative_to(ROOT).as_posix(): runner.digest(p) for p in paths}}
    path = HERE / 'wave_order_fixed.json'
    if path.exists():
        assert runner.read(path) == record
    else:
        runner.save(path, record)
    return record


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


def main() -> None:
    """機能: 全192の保存台帳から全1536波を計算し、元の時価診断と照合する。

    引数: --prepare (bool)。返り値: なし (None)。注文器の再生・探索なし。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    deny_network()
    frozen = freeze()
    if args.prepare:
        print('全1536波・境界3072の独立注文検算を固定。結果読取なし。', flush=True)
        return
    inputs = pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    output, hashes = [], {}
    for identifier in frozen['対象']:
        lp, wp = HERE / 'ledgers' / (identifier + '.json.gz'), HERE / 'waves' / (identifier + '.json.gz')
        for path in (lp, wp):
            hashes[str(path.relative_to(HERE))] = runner.digest(path)
        ledgers = {(row['session'], row['symbol']): row for row in runner.read(lp)}
        waves = runner.read(wp)
        accounts = {}
        for wave in waves:
            key = wave['session'], wave['symbol']
            if key not in accounts:
                accounts[key] = reconstruct(inputs[key], ledgers[key])
            output.append(measure(inputs[key], ledgers[key], wave, accounts[key]))
        assert len(waves) == 8
    assert len(output) == 1536
    for name, fingerprint in hashes.items():
        assert runner.digest(HERE / name) == fingerprint
    assert freeze() == frozen
    runner.save(HERE / 'wave_order_audit.json', {'全合格': True, '全条件数': 192, '全指定波数': 1536, '比較境界数': 3072,
        '注文独立会計一致': True, '保有時間枚数分一致': True, '区間内全注文一致': True, '結果': output,
        '固定SHA256': runner.digest(HERE / 'wave_order_fixed.json'), '保存資料SHA256': hashes,
        'API取得数': 0, '現在保存物使用': False, '注文器再生': False})
    (HERE / 'wave_order_audit.md').write_text('# 指定波の独立注文検算\n\n全192条件・1536波・3,072境界について、全注文から現金と両在庫を再構成し、保存された時価・実現・含み損益、正逆保有分、枚数分、区間内全注文に一致した。\n\n4波は初期6セッションの目的適合参考であり、共通後半7の未知成績とは数えない。追加の注文器再生・探索・現在データ使用・API取得はない。\n', encoding='utf-8')
    print('全1536波・3072境界の全注文独立検算一致。', flush=True)


if __name__ == '__main__':
    main()
