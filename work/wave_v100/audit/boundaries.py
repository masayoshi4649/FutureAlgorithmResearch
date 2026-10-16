"""capを元候補へ固定し、等号・再入域・取消先行・判断後の実fill超過を独立検査する。"""

import math

import numpy as np

import artificial
import common
import independent
import support
import watch


def fixture(symbol: str, side: int, changes: tuple) -> dict:
    """
    機能: 300秒LPが観測可能な人工候補95だけを起点に、候補相対の価格経路を作る。
    引数: symbol(str)、side(int)、changes(tuple[tuple[int,float]])はrowとW倍率。
    返り値: dict。正常な自己板と公表peer、独立LP原素材を別に保持する。
    """
    value = artificial.fixture(symbol, side)
    record, signal = value['record'], value['signal']
    width = max(2, math.ceil(value['reference_open'] * .001 / record['tick'] - 1e-10)) * record['tick']
    own_candidate = record['ask'][95] if side == 1 else record['bid'][95]
    peer_candidate = signal['entry_peer_bbo'][95, 4] if side == 1 else signal['entry_peer_bbo'][95, 3]
    progress = np.zeros(len(record['time_s']))
    for row, multiple in changes:
        progress[row:] = multiple
    quote = own_candidate + side * progress * width
    peer_width = width * (20. if symbol == 'TOPIX' else .05)
    peer_quote = peer_candidate + side * progress * peer_width
    record['bid'][95:] = (quote - record['tick'] if side == 1 else quote)[95:]
    record['ask'][95:] = (quote if side == 1 else quote + record['tick'])[95:]
    record['price'][95:] = (record['bid'][95:] + record['ask'][95:]) * .5
    signal['entry_peer_bbo'][95:, 3] = (peer_quote - signal['peer_tick'] if side == 1 else peer_quote)[95:]
    signal['entry_peer_bbo'][95:, 4] = (peer_quote if side == 1 else peer_quote + signal['peer_tick'])[95:]
    signal['event'][:] = 0
    signal['event'][95] = side
    return value


def arithmetic() -> list[dict]:
    """
    機能: 非呼値端点を丸めず、候補からの方向付き幅を比較する数理境界を確認する。
    引数: なし。
    返り値: list[dict]。買売反射・等号・未知価格の少数正負。
    ここはoracleの仕様確認。対象inline実装との照合は別の原板売買経路で行う。
    """
    rows = []
    for side in (-1, 1):
        for distance, valid, expected in ((2.25, True, True), (2.5, True, False),
                                         (-4., True, True), (math.nan, False, False)):
            state = dict(cap_multiple=.5, side=side, candidate_price=4500., width=4.5)
            quote = 4500. + side * distance
            own = np.array([1., 1., 310., quote-.5 if side == 1 else quote,
                            quote if side == 1 else quote+.5])
            result = watch.cap_status(state, dict(own=own, qok=valid))
            assert result['width'] == 2.25 and result['allowed'] == expected
            rows.append(dict(方向=side, 条件='未知quote' if not valid else '候補相対の数理幅',
                不利幅=None if not math.isfinite(distance) else distance, 上限=2.25, 許可=expected))
    return rows


def main() -> None:
    """
    機能: 両商品・買売のcap等号/拒否保持/取消/未知/再入域/実fill超過を検査する。
    引数: なし。
    返り値: None。通常mainから独立最初trigger・全20/21列・会計を検算し証跡保存する。
    """
    catalog = common.module('100独立cap境界条件', common.BASE / 'catalog.py')
    strategy = common.module('100独立cap境界戦略', common.BASE / 'strategy.py')
    configs = {value['id']: value for value in catalog.catalog()}
    config = configs['P05_L0_C1_A1_X1']
    helper = common.module('99不変人工素材の100境界読取', common.ROOT / 'work/wave_v99/engine_preflight/support.py')
    rows = []
    for symbol in catalog.SYMBOLS:
        for side in (-1, 1):
            for name in ('等号', '上限外から再入域と候補競合', 'TTL先行', '硬反対先行',
                         '未知自己quote', '未知peer保持と復帰', '次normalfill上限外', '半呼値上限を広げない'):
                changes = ((96, .5), (100, 3.), (110, 0.))
                if name == '上限外から再入域と候補競合':
                    changes = ((96, 2.), (100, .5), (110, 3.), (120, 0.))
                elif name == 'TTL先行':
                    changes = ((96, 2.), (155, .5), (170, 3.), (180, 0.))
                elif name == '次normalfill上限外':
                    changes = ((96, .5), (97, 3.), (98, .5), (110, 0.))
                elif name == '未知peer保持と復帰':
                    changes = ((96, .5), (100, .5), (110, 3.), (120, 0.))
                value = fixture(symbol, side, changes)
                record, signal = value['record'], value['signal']
                if name == '半呼値上限を広げない':
                    opening = 4500. if symbol == 'TOPIX' else 45000.
                    shift = opening - value['reference_open']
                    value['reference_open'] = opening
                    for field in ('bid', 'ask', 'price'):
                        record[field] += shift
                    width = max(2, math.ceil(opening * .001 / record['tick'] - 1e-10)) * record['tick']
                    signal['trend_width'] = max(2, math.ceil(opening * .004 / record['tick'] - 1e-10)) * record['tick']
                    distances = np.zeros(len(record['time_s']))
                    distances[96:100] = math.ceil(.5 * width / record['tick']) * record['tick']
                    distances[100:110] = math.floor(.5 * width / record['tick']) * record['tick']
                    distances[110:120] = 3. * width
                    candidate = record['ask'][95] if side == 1 else record['bid'][95]
                    quotes = candidate + side * distances
                    record['bid'][95:] = (quotes-record['tick'] if side == 1 else quotes)[95:]
                    record['ask'][95:] = (quotes if side == 1 else quotes+record['tick'])[95:]
                    record['price'][95:] = (record['bid'][95:] + record['ask'][95:]) * .5
                    peer_candidate = signal['entry_peer_bbo'][95, 4] if side == 1 else signal['entry_peer_bbo'][95, 3]
                    peer_quote = peer_candidate + side * distances * (20. if symbol == 'TOPIX' else .05)
                    signal['entry_peer_bbo'][95:, 3] = (peer_quote-signal['peer_tick'] if side == 1 else peer_quote)[95:]
                    signal['entry_peer_bbo'][95:, 4] = (peer_quote if side == 1 else peer_quote+signal['peer_tick'])[95:]
                if name == '上限外から再入域と候補競合':
                    signal['event'][98] = -side
                elif name == '硬反対先行':
                    signal['wait_opposite_' + ('long' if side == 1 else 'short')][96:] = True
                elif name == '未知自己quote':
                    record['quote_valid'][96] = False
                elif name == '未知peer保持と復帰':
                    signal['entry_peer_bbo'][96:100, 5] = 0.
                key = record['session'], symbol
                helper.attach_support({key: value})
                support.verify_material(key, value['artificial_support_material'], value)
                actual = strategy.play(config, key, {key: value})
                independent.compare(record, signal, config, value['reference_open'], actual, value)
                trace, parents = actual['entry_cap_state_trace'], actual['entry_cap_parent_diagnostics']
                if name in ('TTL先行', '硬反対先行', '未知自己quote'):
                    assert not len(actual['orders'])
                    row, bit = (155, 2) if name == 'TTL先行' else (96, 32) if name == '硬反対先行' else (96, 16)
                    assert int(trace[row, 19]) & bit and not trace[row, 13:16].any()
                else:
                    assert len(actual['trades']) == 1 and parents[0, 14] == 1, (name, symbol, side)
                if name == '等号':
                    assert parents[0, 10] == 96 and parents[0, 13] == parents[0, 9]
                if name == '上限外から再入域と候補競合':
                    assert trace[96, 15] and trace[96:100, 3].all() and parents[0, 10] == 100
                    common.exact(trace[96:100, 6], np.full(4, trace[95, 6]), '元候補quote保持')
                    common.exact(trace[96:100, 16], np.full(4, record['time_s'][95]+300.), '元TTL保持')
                    common.exact(actual['target_trace'][95:100, 2 if side == 1 else 3], np.full(5, 8 if symbol == 'TOPIX' else 16), '拒否中も枠保持')
                    common.exact(actual['target_trace'][95:100, 4], np.full(5, 8 if symbol == 'TOPIX' else 16), '待機分を含む未新規枚数保持')
                    assert not trace[95:100, 18].any(), '上限外なのに市場予約した'
                    ev = actual['entry_wait_events']
                    assert np.any((ev[:, 0] == 98) & (ev[:, 1] == 2)) and len(parents) == 1
                if name == '未知peer保持と復帰':
                    assert trace[96:100, 3].all() and not trace[96:100, 14].any() and parents[0, 10] == 100
                if name == '次normalfill上限外':
                    assert parents[0, 10] == 96 and parents[0, 15] == 97 and parents[0, 19] > 0
                    assert len(actual['orders']) == 2, '予約後の未来fillで取り消した'
                if name == '半呼値上限を広げない':
                    assert trace[96, 2] == (2.25 if symbol == 'TOPIX' else 25.)
                    assert trace[96, 11] == (2.5 if symbol == 'TOPIX' else 30.) and trace[96, 15] == 1
                    assert parents[0, 10] == 100, '非呼値の上限を不利方向へ丸めた'
                rows.append(dict(条件=name, 商品=symbol, 方向=side, 決済親=len(actual['trades'])))
    numeric = arithmetic()
    paths = [common.HERE / name for name in ('common.py', 'support.py', 'watch.py', 'caps.py', 'independent.py', 'artificial.py', 'boundaries.py')]
    paths += [common.BASE / name for name in ('catalog.py', 'strategy.py', 'engine.py')]
    paths += [common.ROOT / 'work/wave_v99/engine_preflight/support.py']
    common.save(common.HERE / '判断価格上限の等号と保持及び取消と実約定超過の独立境界.json', dict(
        合格=True, 人工売買数=len(rows), 人工売買=rows, 数理確認数=len(numeric), 数理確認=numeric,
        範囲='候補quote固定・上限等号・拒否後watch枠/元TTL/幾何保持・再入域・busy候補不復活・TTL/硬取消/未知資格先行・次normal cap外fill。新20/21は独立算定。',
        価格上限の性質='発注判断gateであり、実指値の約定上限ではない。未来fillを入口判断へ渡さない。',
        全31既知=True, 未見場数=0, 正式100損益=0, API取得=0, 実注文=0, SHA256=common.fingerprint(paths)))
    print('cap独立売買32と数学8境界: 合格', flush=True)


if __name__ == '__main__':
    main()
