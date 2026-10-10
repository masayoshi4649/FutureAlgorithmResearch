"""全保存注文の独立現金・在庫から指定4波×両銘柄を再計算する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import pickle
import socket
from zoneinfo import ZoneInfo

import numpy as np

import partial_causality_audit as common

HERE, ROOT, runner, design, api = common.HERE, common.ROOT, common.runner, common.design, common.api
read, save, digest = common.read, common.save, common.digest
INPUTS, FIXED = {}, {}
EPISODES = (
    dict(id='W01', session='2026-09-21_Day', start='2026-09-21T10:45:00+09:00', end='2026-09-21T15:35:00+09:00', side=1, name='9/21デイ後半の上昇'),
    dict(id='W02', session='2026-09-22_Day', start='2026-09-22T09:20:00+09:00', end='2026-09-22T11:45:00+09:00', side=-1, name='9/22デイ前半の下落'),
    dict(id='W03', session='2026-09-23_Day', start='2026-09-23T09:05:00+09:00', end='2026-09-23T11:15:00+09:00', side=-1, name='9/23デイ前半の下落'),
    dict(id='W04', session='2026-09-22_Night', start='2026-09-23T00:40:00+09:00', end='2026-09-23T03:20:00+09:00', side=1, name='9/22ナイト深夜の上昇'),
)


def stamp(seconds: float) -> str:
    """機能: 秒を日本時間のISO表記へ変換する。

    引数: seconds (float)。返り値: 時刻 (str)。
    """
    return datetime.fromtimestamp(float(seconds), ZoneInfo('Asia/Tokyo')).isoformat()


def compare(actual: object, expected: object, location: str = '') -> None:
    """機能: 保存項目の欠落・余分・型・値を再帰的に検査する。

    引数: actual/expected (object)、location (str)。返り値: なし (None)。
    """
    if isinstance(expected, dict):
        assert isinstance(actual, dict) and actual.keys() == expected.keys(), location
        for key in expected:
            compare(actual[key], expected[key], location + '/' + key)
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), location
        for i, (a, b) in enumerate(zip(actual, expected, strict=True)):
            compare(a, b, location + '/' + str(i))
    elif isinstance(expected, bool) or expected is None or isinstance(expected, str):
        assert actual == expected and type(actual) is type(expected), location
    elif isinstance(expected, (int, float)):
        assert isinstance(actual, (int, float)) and not isinstance(actual, bool), location
        assert np.isfinite(actual) and np.isfinite(expected), location
        assert abs(actual - expected) <= 1e-6, (location, actual, expected)
    else:
        raise TypeError(location)


def reconstruct(ready: dict, orders: np.ndarray, trades: np.ndarray) -> dict:
    """機能: 全注文から現金・買売数量、全返済から実現益を独立集計する。

    引数: ready (dict)、orders/trades (ndarray)。返り値: 全原本行の現金・数量・実現・時価 (dict)。
    保存curve、主runnerの会計関数、保存trade損益列は集計の入力にしない。
    """
    n = len(ready['last'])
    assert orders.ndim == trades.ndim == 2 and orders.shape[1] == 8 and trades.shape[1] == 11
    assert np.isfinite(orders).all() and np.isfinite(trades).all()
    movement = np.zeros((n, 4))
    if len(orders):
        rows = orders[:, 0].astype(np.int64); sources = orders[:, 1].astype(np.int64)
        assert np.array_equal(rows, orders[:, 0]) and np.all((sources >= 0) & (sources < rows) & (rows < n))
        assert np.all(np.diff(rows) >= 0) and np.isin(orders[:, 3], (-1, 1)).all()
        qty = orders[:, 4]; assert np.all(qty > 0) and np.array_equal(qty, qty.astype(int))
        new = orders[:, 7] == 1; buy = orders[:, 3] == 1
        assert np.isin(orders[:, 7], (0, 1)).all()
        np.add.at(movement[:, 0], rows, -orders[:, 3] * qty * orders[:, 5])
        np.add.at(movement[:, 1], rows, np.where(new & buy, qty, np.where(~new & ~buy, -qty, 0.)))
        np.add.at(movement[:, 2], rows, np.where(new & ~buy, qty, np.where(~new & buy, -qty, 0.)))
    if len(trades):
        rows = trades[:, 7].astype(int)
        assert np.array_equal(rows, trades[:, 7]) and np.all((rows >= 0) & (rows < n))
        gains = trades[:, 2] * trades[:, 3] * (trades[:, 5] - trades[:, 4])
        np.testing.assert_allclose(gains, trades[:, 10], rtol=0, atol=1e-8)
        np.add.at(movement[:, 3], rows, gains)
    cumulative = np.cumsum(movement, axis=0)
    cash, long, short, realized = cumulative.T
    assert np.all(long >= 0) and np.all(short >= 0)
    net = long - short
    return dict(cash=cash, long=long, short=short, net=net, realized=realized,
                equity=cash + net * ready['last'])


def integrate(times: np.ndarray, values: np.ndarray, begin: float, end: float) -> float:
    """機能: 約定反映後の在庫を次原本行まで保持して波区間の分数を積分する。

    引数: times/values (ndarray)、begin/end (float)。返り値: 値×分 (float)。同時刻区間は0分。
    """
    left = np.maximum(times[:-1], begin); right = np.minimum(times[1:], end)
    length = np.clip(right - left, 0., None)
    return float(np.dot(length, values[:-1].astype(float)) / 60.)


def boundary(ready: dict, account: dict, seconds: float, factor: float) -> dict:
    """機能: 境界以前の最後の原本行で全在庫を時価評価する。

    引数: ready/account (dict)、seconds/factor (float)。返り値: 保存互換の境界評価 (dict)。
    """
    row = int(np.searchsorted(ready['time_s'], seconds, side='right') - 1)
    assert row >= 0 and ready['time_s'][row] <= seconds
    realized = float(account['realized'][row]); equity = float(account['equity'][row])
    return dict(境界時刻=stamp(seconds), 参照時刻=stamp(ready['time_s'][row]), 参照行=row,
        seq=int(ready['seq'][row]), last=float(ready['last'][row]), 買い枚数=int(account['long'][row]),
        売り枚数=int(account['short'][row]), ネット枚数=int(account['net'][row]),
        実現損益円=realized * factor, 含み損益円=(equity - realized) * factor, 時価損益円=equity * factor)


def order_records(ready: dict, state: np.ndarray, orders: np.ndarray) -> list[dict]:
    """機能: 原本行と注文決定元を区別して全約定一覧を作る。

    引数: ready (dict)、state/orders (ndarray)。返り値: 約定一覧 (list[dict])。
    """
    names = dict(common.engine.REASONS)
    names.update({20: '主玉新規', 21: 'カバー新規', 22: '追加新規', 23: '反転後の主玉補充'})
    output = []
    for index, o in enumerate(orders):
        filled, source = int(o[0]), int(o[1]); assert 0 <= source < filled
        output.append(dict(order_index=index, session=ready['session'], symbol=ready['symbol'],
            time_s=float(ready['time_s'][filled]), 時刻=stamp(ready['time_s'][filled]), 原本行=filled,
            seq=int(ready['seq'][filled]), 発注元時刻=stamp(ready['time_s'][source]), 発注元行=source,
            発注元seq=int(ready['seq'][source]), 種別='新規' if o[7] == 1 else '返済', direction=int(o[3]),
            枚数=int(o[4]), 価格=float(o[5]), 組番号=int(o[2]), 理由番号=int(o[6]),
            理由=names.get(int(o[6]), 'その他'), 発注元信号=int(state[source]), 約定時信号=int(state[filled])))
    return output


def measure(identifier: str, episode: dict, ready: dict, state: np.ndarray,
            orders: np.ndarray, trades: np.ndarray, factor: float, manager: dict) -> dict:
    """機能: 全注文から8波の保有・信号時間と境界損益を再計算する。

    引数: identifier (str)、episode/ready/manager (dict)、state/orders/trades (ndarray)、factor (float)。
    返り値: 一波・一市場の独立値 (dict)。利益と20分捕捉の目安を分ける。
    """
    begin = datetime.fromisoformat(episode['start']).timestamp(); end = datetime.fromisoformat(episode['end']).timestamp()
    times, side = ready['time_s'], episode['side']
    assert times[0] <= begin < end <= times[-1]
    account = reconstruct(ready, orders, trades)
    positive = account['long'] if side == 1 else account['short']
    negative = account['short'] if side == 1 else account['long']
    net = side * account['net']
    I = lambda values: integrate(times, values, begin, end)
    signal = (I(state == side), I(state == -side), I(state == 0))
    assert abs(sum(signal) - (end - begin) / 60.) <= 1e-8
    forward, reverse = I(net > 0), I(net < 0)
    first, last = boundary(ready, account, begin, factor), boundary(ready, account, end, factor)
    records = [r for r in order_records(ready, state, orders) if begin <= r['time_s'] <= end]
    changes = np.r_[True, state[1:] != state[:-1]] & (times >= begin) & (times <= end)
    signals = [dict(時刻=stamp(times[i]), time_s=float(times[i]), seq=int(ready['seq'][i]), direction=int(state[i]))
               for i in np.flatnonzero(changes)]
    return dict(method=identifier, wave=episode['id'], session=episode['session'], symbol=ready['symbol'],
        波名=episode['name'], 波方向=side, 開始=episode['start'], 終了=episode['end'], 区間分=(end - begin) / 60.,
        正方向信号分=signal[0], 逆方向信号分=signal[1], 中立信号分=signal[2],
        管理方向源=manager.get('context_source', 'entry'), 正方向管理分=signal[0], 逆方向管理分=signal[1], 中立管理分=signal[2],
        正方向ネット保有分=forward, 逆方向ネット保有分=reverse, ネット中立分=I(net == 0),
        正方向脚保有分=I(positive > 0), 逆方向脚保有分=I(negative > 0),
        正方向枚数分=I(positive), 逆方向枚数分=I(negative), 両建て保有分=I((positive > 0) & (negative > 0)),
        正方向ネット20分目安達成=bool(forward >= 20 - 1e-9), 開始境界=first, 終了境界=last,
        時価損益差円=last['時価損益円'] - first['時価損益円'],
        実現損益差円=last['実現損益円'] - first['実現損益円'], 含み損益差円=last['含み損益円'] - first['含み損益円'],
        区間内新規=[r for r in records if r['種別'] == '新規'], 区間内返済=[r for r in records if r['種別'] == '返済'],
        区間内方向変更=signals, 区間内管理方向変更=deepcopy(signals))


def synthetic() -> dict:
    """機能: 同時刻境界・減量復元・20分と赤字・未来不参照を人工台帳で確かめる。

    引数: なし。返り値: 検査結果 (dict)。新実データは読まない。
    """
    ready = dict(session='人工', symbol='TOPIX', time_s=np.array([0., 60., 60., 120., 1260., 1320.]),
        last=np.array([100., 101., 102., 104., 105., 101.]), seq=np.array([10, 14, 20, 22, 29, 40]))
    state = np.array([0, 1, 1, 1, 1, 0], dtype=np.int8)
    orders = np.array([[1, 0, 0, 1, 4, 101, 20, 1], [2, 1, 0, -1, 1, 102, 30, 0],
        [3, 2, 0, 1, 1, 104, 31, 1], [4, 3, 0, -1, 2, 105, 7, 0], [5, 4, 0, -1, 2, 101, 2, 0]], dtype=float)
    trades = np.array([[0, 0, 1, 1, 101, 102, 1, 2, 0, 30, 1],
        [0, 0, 1, 2, 101, 105, 1, 4, 0, 7, 8], [0, 0, 1, 1, 101, 101, 1, 5, 0, 2, 0],
        [0, 1, 1, 1, 104, 101, 3, 5, 0, 2, -3]], dtype=float)
    episode = dict(id='人工波', session='人工', start=stamp(60), end=stamp(1320), side=1, name='人工')
    row = measure('人工', episode, ready, state, orders, trades, 1000., {})
    assert row['開始境界']['参照行'] == 2 and row['開始境界']['買い枚数'] == 3
    assert row['開始境界']['時価損益円'] == 4000 and row['終了境界']['時価損益円'] == 6000
    assert row['正方向ネット保有分'] == 21 and row['正方向枚数分'] == 81 and row['正方向ネット20分目安達成']
    assert row['時価損益差円'] == 2000 and len(row['区間内新規']) == 2 and len(row['区間内返済']) == 3
    checks = ['同時刻群最後の境界', '減量復元と21分81枚数分', '両端包含約定と開始前保有の時価差']
    narrower = dict(episode, end=stamp(1260))
    future = dict(ready, last=ready['last'].copy()); future['last'][-1] = 9999.
    expected = measure('人工', narrower, ready, state, orders, trades, 1000., {})
    compare(measure('人工', narrower, future, state, orders, trades, 1000., {}), expected)
    checks.append('境界後の未来価格を使わない')
    reflected = dict(ready, last=300-ready['last'])
    mirrored_orders = orders.copy(); mirrored_orders[:, 3] *= -1; mirrored_orders[:, 5] = 300-mirrored_orders[:, 5]
    mirrored_trades = trades.copy(); mirrored_trades[:, 2] *= -1; mirrored_trades[:, 4:6] = 300-mirrored_trades[:, 4:6]
    mirrored = measure('人工', dict(episode, side=-1), reflected, -state, mirrored_orders, mirrored_trades, 10., {})
    assert mirrored['正方向ネット保有分'] == 21 and mirrored['時価損益差円'] == 20
    checks.append('上下反射とTOP1000円対NK10円倍率')
    losing = dict(ready, last=ready['last'].copy()); losing['last'][-1] = 90.
    lo = orders.copy(); lo[-1, 5] = 90.
    lt = trades.copy(); lt[-2:, 5] = 90.; lt[:, 10] = lt[:, 2]*lt[:, 3]*(lt[:, 5]-lt[:, 4])
    negative = measure('人工', episode, losing, state, lo, lt, 1000., {})
    assert negative['正方向ネット20分目安達成'] and negative['時価損益差円'] < 0
    checks.append('20分目安達成でも赤字を許す別指標')
    rejected = []
    for kind in ('金額', '枚数分', '欠落', '重複約定', 'NaN'):
        corrupted = deepcopy(row)
        if kind == '金額': corrupted['時価損益差円'] += 1
        if kind == '枚数分': corrupted['正方向枚数分'] += 1
        if kind == '欠落': del corrupted['開始境界']['seq']
        if kind == '重複約定': corrupted['区間内新規'].append(corrupted['区間内新規'][0])
        if kind == 'NaN': corrupted['時価損益差円'] = float('nan')
        try:
            compare(corrupted, row)
        except AssertionError:
            rejected.append(kind)
        else:
            raise AssertionError('人工破損を受理した: ' + kind)
    return dict(全合格=True, 合成検査数=len(checks), 合成検査=checks, 負例拒否数=len(rejected), 負例=rejected,
                新実相場損益=False, 売買再生=False)


def prepare() -> dict:
    """機能: 全427条件の波区間・単位・比較と人工証跡を新損益前に固定する。

    引数: なし。返り値: 固定規則 (dict)。
    """
    path = HERE / 'partial_wave_fixed.json'
    rules = dict(主条件ID=[s['id'] for s in design.catalog()], 補助条件ID=[s['id'] for s in design.supplementary()],
        指定波=list(EPISODES), 銘柄=['TOPIX', 'NK225'], 主波数=363*8, 補助波数=64*8, 全波数=427*8,
        全境界数=427*16, 目安='正方向ネット保有の累積20分以上。連続不要・統計有意ではない。',
        単位={'TOPIX': 1000., 'NK225': 10.}, 独立会計='全ordersの約定方向×枚数から現金・買売在庫、tradesの元値返済値から実現益。保存curve・主会計は不使用。',
        時間='当該行の約定反映後在庫を次行まで持つ。積分は開始以上終了未満。同時刻行間0秒。',
        境界='各境界以下の最後の原本行。境界前からの持玉を含む時価差。開始以上終了以下の全約定一覧。',
        管理方向欄='旧保存互換の入口列複写であり、悪化・回復による数量判断を表すものではない。',
        比較='全保存波の全項目・型・一覧順序・境界・数量を独立値へ照合。', 許容=dict(rtol=0, atol=1e-6),
        波の入口混入=False, 新候補選別=False, 新実相場損益未読=True, API取得数=0)
    if path.exists():
        value = read(path); assert value['規則'] == rules
        for name, sha in value['SHA256'].items(): assert digest(ROOT/name) == sha, name
        return value
    checks = synthetic(); save(HERE/'partial_wave_selftest.json', checks)
    paths = {Path(__file__), HERE/'partial_wave_selftest.json', HERE/'partial_causality_audit.py',
             HERE/'partial_design.py', HERE/'partial_input_fixed.json', HERE/'partial_inputs.py',
             HERE/'engine_partial_restore.py', HERE/'partial_runner.py', HERE.parent/'wave_v23/inputs.pkl'}
    material = read(HERE/'partial_input_fixed.json')
    for relative, sha in material['SHA256'].items():
        assert digest(ROOT/relative) == sha
        paths.add(ROOT/relative)
    value = dict(全合格=True, 合成検査合格=True, 新実相場損益=False, 規則=rules,
        固定日時=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
        SHA256={p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(paths)})
    save(path, value)
    return value


def initialize() -> None:
    """機能: 固定入力だけ読み込み、通信を拒否する。

    引数: なし。返り値: なし (None)。
    """
    global INPUTS, FIXED
    socket.socket.connect = runner.reject_network; socket.create_connection = runner.reject_network
    INPUTS = pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    FIXED = read(HERE/'探索条件の固定.json'); assert FIXED['指定波'] == list(EPISODES)
    api.initialize(INPUTS)


def evaluate(spec: dict, supplementary: bool) -> dict:
    """機能: 一条件の保存注文から8波を独立に照合する。

    引数: spec (dict)、supplementary (bool)。返り値: 全8波と指紋の記録 (dict)。
    """
    destination = HERE / ('supplementary' if supplementary else '')
    lp = destination/'ledgers'/(spec['id']+'.json.gz'); wp = destination/'waves'/(spec['id']+'.json.gz')
    ledgers, waves = read(lp), read(wp)
    by_key = {(r['session'], r['symbol']): r for r in ledgers}
    saved = {(r['wave'], r['symbol']): r for r in waves}
    assert len(ledgers) == len(by_key) == 26 and set(by_key) == set(INPUTS)
    assert len(waves) == len(saved) == 8 and set(saved) == {(w['id'], s) for w in EPISODES for s in ('TOPIX', 'NK225')}
    rows = []
    for wave in EPISODES:
        for symbol, factor in (('TOPIX', 1000.), ('NK225', 10.)):
            key = wave['session'], symbol; ready = INPUTS[key]; ledger = by_key[key]
            orders = np.asarray(ledger['orders'], dtype=float).reshape(-1, 8)
            trades = np.asarray(ledger['trades'], dtype=float).reshape(-1, 11)
            for name, array in (('orders', orders), ('trades', trades)):
                import hashlib
                expected = ledger['result_fingerprints'][name]
                assert expected == dict(shape=list(array.shape), dtype=array.dtype.str, SHA256=hashlib.sha256(array.tobytes()).hexdigest())
            state = api.entry(spec['signal_id'], spec['entry_scale'], key)
            row = measure(spec['id'], wave, ready, state, orders, trades, factor, FIXED['manager'])
            compare(row, saved[(wave['id'], symbol)], spec['id'] + '/' + wave['id'] + '/' + symbol)
            rows.append(row)
    assert len(rows) == 8
    result = dict(id=spec['id'], 全合格=True, 波数=8, 境界数=16, 全保存項目一致=True, 波=rows,
        主保存SHA256={lp.relative_to(ROOT).as_posix(): digest(lp), wp.relative_to(ROOT).as_posix(): digest(wp)},
        監査固定SHA256=digest(HERE/'partial_wave_fixed.json'))
    save(destination/'partial_wave_details'/(spec['id']+'.json.gz'), result)
    return result


def main() -> None:
    """機能: 人工固定のみ、又は全主・補助の波監査を実行する。

    引数: --prepare/--supplementary (bool)、--workers (int)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser(); parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--supplementary', action='store_true'); parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args(); fixed = prepare()
    if args.prepare:
        print('8波の独立式、人工6検査・破損5拒否を固定。新実データ損益なし。', flush=True)
        return
    guard = read(HERE/'起動前監査.json')
    assert guard['実行可能'] and guard['探索固定SHA256'] == digest(HERE/'探索条件の固定.json')
    destination = HERE / ('supplementary' if args.supplementary else '')
    specs = design.supplementary() if args.supplementary else design.catalog()
    assert read(destination/'主再生の完了.json')['全条件数'] == len(specs)
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize) as pool:
        jobs = [pool.submit(evaluate, spec, args.supplementary) for spec in specs]
        for job in as_completed(jobs):
            rows.append(job.result())
            print(f'{len(rows)}/{len(specs)} 保存全8波一致', flush=True)
    assert sum(r['波数'] for r in rows) == len(specs)*8
    prepare()
    value = dict(全合格=True, 条件数=len(specs), 波数=len(specs)*8, 境界数=len(specs)*16,
        全保存項目一致=True, 結果=sorted(rows, key=lambda r:r['id']), 監査規則=fixed,
        探索固定SHA256=digest(HERE/'探索条件の固定.json'), 新売買再生=False, 現在保存物使用=False, API取得数=0)
    save(destination/'partial_wave_audit.json', value)
    print(dict(全合格=True, 条件数=len(specs), 波数=len(specs)*8), flush=True)


if __name__ == '__main__':
    main()
