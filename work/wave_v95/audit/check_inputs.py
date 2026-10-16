"""全62のLP新窓・候補格子・実exit原seq対応を、別の源探索から検算する。"""

from pathlib import Path
import socket
import sys

import numba
import numpy as np

import common


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 保存入力の監査中に外部通信を呼べないようにする。
    引数: args(tuple)、kwargs(dict)。接続引数。
    返り値: None。呼出し時は例外。
    """
    raise RuntimeError('95監査は保存素材だけを読みます')


def points(targets: np.ndarray, raw: dict) -> tuple[np.ndarray, np.ndarray]:
    """
    機能: 時計の同値群を先に区切り、厳密過去の最新群の先頭だけを採用する。
    引数: targets(ndarray[float])。参照期限。raw(dict)。独立LP系列。
    返り値: tuple[ndarray[int32],ndarray[float32]]。採用indexと鮮度。
    無効な最新群を古い正常群又は同群後続へ救済しない。
    """
    times = raw['time_s']
    assert np.isfinite(times).all() and (np.diff(times) >= 0).all()
    indexes = np.full(len(targets), -1, np.int32)
    age = np.full(len(targets), np.nan, np.float32)
    if not len(times):
        return indexes, age
    beginnings = np.flatnonzero(np.r_[True, times[1:] != times[:-1]])
    clocks = times[beginnings]
    groups = np.searchsorted(clocks, targets, side='left') - 1
    present = np.flatnonzero((groups >= 0) & np.isfinite(targets))
    source = beginnings[groups[present]]
    elapsed = targets[present] - times[source]
    accepted = (raw['valid'][source] & np.isfinite(raw['last'][source]) & (raw['last'][source] > 0)
                & ~raw['reset'][source] & (elapsed > 0) & (elapsed <= 30.))
    selected = present[accepted]
    indexes[selected] = source[accepted]
    age[selected] = elapsed[accepted]
    return indexes, age


def restore(grid: np.ndarray, raw: dict) -> dict:
    """
    機能: 正式入力関数を呼ばず、LP currentと15/300秒窓の全列を再構成する。
    引数: grid(ndarray[float])。5秒格子。raw(dict)。原本LP系列。
    返り値: dict。currentとwindows。板の資格・気配・OFIは生成しない。
    """
    times, prices, sequences = (raw[name] for name in ('time_s', 'last', 'seq'))
    assert len(times) and len(times) == len(prices) == len(sequences)
    assert (np.diff(sequences) > 0).all()
    now, age = points(grid - 1., raw)
    safe_now = np.maximum(now, 0)
    value = prices[safe_now].copy()
    sequence = sequences[safe_now].copy()
    clock = times[safe_now].copy()
    value[now < 0] = np.nan
    sequence[now < 0] = -1
    clock[now < 0] = np.nan
    current = dict(index=now, raw_seq=sequence, time_s=clock, value=value, valid=now >= 0,
                   age=age, actual_age=age + 1.)
    # ----------------------------------------
    # すべての原行を破断判定へ含め、同時計群の不正後続も窓から消さない。
    invalid = (~raw['valid'] | ~np.isfinite(prices) | (prices <= 0) | raw['reset']).astype(np.int64)
    discontinuities = np.cumsum(invalid)
    windows = {}
    for seconds in (15, 300):
        old, old_age = points(grid - 1. - seconds, raw)
        safe_old = np.maximum(old, 0)
        available = (now >= 0) & (old >= 0)
        crossed = available & (discontinuities[safe_now] > discontinuities[safe_old])
        valid = available & (old < now) & ~crossed
        old_sequence = sequences[safe_old].copy()
        old_clock = times[safe_old].copy()
        old_price = prices[safe_old].copy()
        old_sequence[old < 0] = -1
        old_clock[old < 0] = np.nan
        old_price[old < 0] = np.nan
        with np.errstate(invalid='ignore', divide='ignore'):
            ret = (prices[safe_now] - prices[safe_old]) / prices[safe_old] * 10000.
            ratio_ret = (prices[safe_now] / prices[safe_old] - 1.) * 10000.
        elapsed = times[safe_now] - times[safe_old]
        ret[~valid] = np.nan
        ratio_ret[~valid] = np.nan
        elapsed[~valid] = np.nan
        windows[seconds] = dict(now=now.copy(), old=old, now_seq=sequence.copy(), old_seq=old_sequence,
                                source_valid=valid, same_row=available & (old == now),
                                reset_or_invalid_cross=crossed, now_time_s=clock.copy(), old_time_s=old_clock,
                                now_value=value.copy(), old_value=old_price, old_age=old_age,
                                actual_seconds=elapsed, ret_bp=ret, ratio_ret_bp=ratio_ret)
    return dict(current=current, windows=windows)


def sliced(raw: dict, cut: int) -> dict:
    """
    機能: LP原行の未来だけを取り除いた人工copyを作る。
    引数: raw(dict)。LP系列。cut(int)。残す原行数。
    返り値: dict。prefix素材。原本は変更しない。
    """
    size = len(raw['time_s'])
    return {key: value[:cut].copy() if isinstance(value, np.ndarray) and value.ndim == 1 and len(value) == size
            else value for key, value in raw.items()}


def production(producer: object, grid: np.ndarray, raw: dict) -> dict:
    """
    機能: rootの入力計算関数だけを呼び、cache設定を監査領域へ直ちに戻す。
    引数: producer(object)。prepare_pricesモジュール。grid(ndarray)、raw(dict)。
    返り値: dict。純入力features。ファイル生成mainや売買本体を呼ばない。
    """
    try:
        return producer.price_features(grid, raw)
    finally:
        numba.config.CACHE_DIR = str(common.HERE / 'jit')


def toy() -> dict:
    """
    機能: 正式素材を読む前に、同時計先頭不正・期限等号・reset窓の正負を検査する。
    引数: なし。
    返り値: dict。人工入力境界の証跡。
    """
    raw = dict(time_s=np.array([0., 1., 1., 10., 20., 25., 40.]), seq=np.arange(7),
               last=np.array([100., np.nan, 105., 110., 120., 125., 130.]),
               valid=np.array([True, False, True, True, True, True, True]), reset=np.zeros(7, bool))
    selected, _ = points(np.array([1., 2., 10., 11., 51., 71.]), raw)
    common.exact(selected, np.array([0, -1, -1, 3, 6, -1]))
    raw['reset'][4] = True
    result = restore(np.array([28.]), raw)
    assert result['current']['index'][0] == 5
    assert result['windows'][15]['reset_or_invalid_cross'][0]
    assert not result['windows'][15]['source_valid'][0]
    old = (5001.5 / 5000. - 1.) * 10000.
    new = (5001.5 - 5000.) / 5000. * 10000.
    assert old != new and old < 3. and new < 3.
    return dict(同時計先頭不正の救済なし=True, 期限同時計不採用=True, 鮮度30秒境界=True,
                reset窓無効=True, 旧候補ret=old, 新LPret=new, この例の3bp判定は双方未満=True,
                演算差の境界を公差で救済しない=True)


def main() -> None:
    """
    機能: 全62新窓と原seq対応、実prefix及び未来変形を純入力として監査する。
    引数: なし。
    返り値: None。新95/auditへ証跡を保存する。正式95損益・API・注文は0。
    """
    socket.socket.connect = deny
    socket.create_connection = deny
    artificial = toy()
    data = common.module('独立入力監査95の保存読取', common.WORK / 'data.py')
    previous_data = sys.modules.get('data')
    sys.modules['data'] = data
    try:
        producer = common.module('独立入力監査95の正式窓関数読取', common.WORK / 'prepare_prices.py')
    finally:
        if previous_data is None:
            del sys.modules['data']
        else:
            sys.modules['data'] = previous_data
    producer.data = data
    material = data.load_inputs()
    assert len(material['prices']) == 62 and len(material['grids']) == 31
    baseline = common.fingerprint(material['paths'])
    rows, counts = [], dict(口座=0, LP原行=0, 執行対応行=0, 全格子=0, 窓=0, 接頭=0, 未来変形=0)
    for session in material['metadata']['sessions']:
        channel = material['trend_prices']['I3'][session]
        reference = material['prices'][session, 'TOPIX']
        expected_grid = np.arange(reference['start'] + 300., reference['limit'] - 300., 15.)
        common.exact(expected_grid, channel['candidate_grid'])
        positions = np.flatnonzero(np.isin(channel['grid'], expected_grid))
        common.exact(positions, channel['candidate_positions'])
        for symbol in common.SYMBOLS:
            key = session, symbol
            raw, record = material['raw_last_records'][key], material['prices'][key]
            saved = channel['markets'][symbol]
            expected = restore(channel['grid'], raw)
            common.exact(expected, saved)
            # ----------------------------------------
            # retained板の行番号ではなく原本seqで独立LP位置を対応付ける。
            lookup = {int(sequence): index for index, sequence in enumerate(raw['seq'])}
            indexes = np.array([lookup[int(sequence)] for sequence in record['seq']], np.int32)
            common.exact(indexes, material['execution_lp_index'][key])
            common.exact(raw['time_s'][indexes], record['time_s'])
            common.exact(raw['last'][indexes], record['price'])
            common.exact(raw['seq'][indexes], record['seq'])
            for fraction in (.25, .5, .8):
                grid_cut = max(1, int(len(channel['grid']) * fraction))
                prefix_grid = channel['grid'][:grid_cut]
                clock = channel['grid'][grid_cut - 1] + 1.
                cut = int(np.searchsorted(raw['time_s'], clock, side='left'))
                prefix_expected = dict(current={name: value[:grid_cut] for name, value in saved['current'].items()},
                                       windows={window: {name: value[:grid_cut] for name, value in fields.items()}
                                                for window, fields in saved['windows'].items()})
                shortened = sliced(raw, cut)
                common.exact(restore(prefix_grid, shortened), prefix_expected)
                common.exact(production(producer, prefix_grid, shortened), prefix_expected)
                counts['接頭'] += 1
                changed = sliced(raw, len(raw['time_s']))
                changed['last'][cut:] *= 10.
                changed['valid'][cut:] = ~changed['valid'][cut:]
                changed['reset'][cut:] = ~changed['reset'][cut:]
                changed['seq'][cut:] += 10000000
                changed['time_s'][cut:] += 100000.
                common.exact(production(producer, prefix_grid, changed), prefix_expected)
                counts['未来変形'] += 1
            current = saved['current']
            valid = current['valid']
            assert (current['time_s'][valid] < channel['grid'][valid] - 1.).all()
            assert (current['raw_seq'][valid] == raw['seq'][current['index'][valid]]).all()
            counts['口座'] += 1
            counts['LP原行'] += len(raw['seq'])
            counts['執行対応行'] += len(record['seq'])
            counts['全格子'] += len(channel['grid'])
            counts['窓'] += 2 * len(channel['grid'])
            rows.append(dict(場=session, 商品=symbol, LP原行=len(raw['seq']), 執行対応行=len(record['seq']),
                             全格子=len(channel['grid']), 候補格子=len(expected_grid), 原価格と別執行源の全対応一致=True))
        print(f'{session}: 両源の15/300秒全窓・旧候補格子・実原seq対応・3接頭/3未来が一致', flush=True)
    assert counts['口座'] == 62 and counts['接頭'] == counts['未来変形'] == 186
    common.exact(common.fingerprint(material['paths']), baseline)
    baseline.update(common.fingerprint([Path(__file__), Path(common.__file__)]))
    common.save('全62新LP窓と旧候補格子及び別執行原seq対応の独立入力検算.json',
                dict(合格=True, 全31既知=True, 対象=counts, 人工=artificial, 全口座=rows,
                     同時計先頭及び厳密過去を独立計算=True, 価格とBBOのindex及び時計を混同しない=True,
                     旧Q及びOFI及び執行素材変更=0, 全読取入力の終端SHA一致=True, SHA256=baseline,
                     正式95損益実行=0, 正式95損益閲覧=0, API取得=0, 実注文=0,
                     限界='原LP代理時計と保存seq上の入力因果を検証。真受信clock又は価格予測精度の証明ではない。'))


if __name__ == '__main__':
    main()
