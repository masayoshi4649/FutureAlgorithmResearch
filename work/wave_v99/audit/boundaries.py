"""支持源だけの資格と、硬い取消・再準備・候補競合の少数正負を独立検査する。"""

from copy import deepcopy

import numpy as np

import artificial
import common
import independent
import support


def feature_material(changes: tuple[float, float], side: int = 1) -> tuple[dict, dict]:
    """
    機能: 支持数式の境界だけを持つ一格子・二市場の人工特徴を作る。
    引数: changes(tuple[float,float])は方向付きbp、side(int)は上下反射。
    返り値: tuple[dict,dict]。価格資格と旧板/OFI資格を別辞書へ置く。
    これは窓生成・売買結果の証明ではなく、支持不等号の最小反例である。
    """
    price, execution = dict(grid=np.array([700.]), markets={}), dict(grid=np.array([700.]), markets={})
    for symbol, change in zip(('TOPIX', 'NK225'), changes):
        price['markets'][symbol] = dict(current=dict(valid=np.array([True]), value=np.array([4000.])),
            windows={300: dict(source_valid=np.array([True]), ret_bp=np.array([side * change]))})
        execution['markets'][symbol] = dict(current=dict(valid=np.array([True])),
            flow={15: dict(source_valid=np.array([True]), valid=np.array([True]),
                missing_ofi=np.array([False]), nonzero_ofi_count=np.array([3]), ofi_ratio=np.array([0.]))})
    return price, execution


def scalar_cases(strategy: object) -> list[dict]:
    """
    機能: 比率等号、LP未知、旧板未知、十分な逆OFIの境界を公差0で検査する。
    引数: strategy(object)は検査対象。
    返り値: list[dict]。上下各16の正負判定。未知OFIは逆証拠にも価格支持にも代用しない。
    """
    outcomes = []
    cases = [('正支持', (10., 10.), None, True), ('比率等号', (10., 2.5), None, True),
             ('比率未達', (10., 2.499), None, False), ('片側ゼロ', (10., 0.), None, False),
             ('片側反対', (10., -1.), None, False), ('価格未知', (10., 10.), ('price', 'valid', False), False),
             ('価格値ゼロ', (10., 10.), ('price', 'value', 0.), False),
             ('窓未知', (10., 10.), ('window', 'source_valid', False), False),
             ('旧板未知', (10., 10.), ('execution', 'valid', False), False),
             ('逆OFI等号', (10., 10.), ('flow', 'ofi_ratio', -.1), False),
             ('逆OFI弱い', (10., 10.), ('flow', 'ofi_ratio', -.099), True),
             ('逆OFI二回', (10., 10.), ('flow2', 'nonzero_ofi_count', 2), True),
             ('逆OFI欠測', (10., 10.), ('flow2', 'missing_ofi', True), True),
             ('逆OFI源未知', (10., 10.), ('flow2', 'source_valid', False), True),
             ('逆OFI数値未知', (10., 10.), ('flow', 'ofi_ratio', np.nan), True),
             ('価格進行未知', (10., np.nan), None, False)]
    for side in (-1, 1):
        for name, changes, mutation, expected in cases:
            price, execution = feature_material(changes, side)
            if mutation:
                lane, field, changed = mutation
                if lane.startswith('flow'):
                    target = execution['markets']['NK225']['flow'][15]
                    if lane == 'flow2':
                        target['ofi_ratio'][0] = side * -.5
                    if field == 'ofi_ratio':
                        changed *= side
                elif lane == 'execution':
                    target = execution['markets']['NK225']['current']
                elif lane == 'window':
                    target = price['markets']['NK225']['windows'][300]
                else:
                    target = price['markets']['NK225']['current']
                target[field][0] = changed
            oracle, actual = support.lp_allowed(price, execution), strategy.lp_allowed(price, execution)
            for direction in (-1, 1):
                common.exact(oracle[direction], actual[direction], name)
            assert bool(oracle[side][0]) == expected, (name, side)
            outcomes.append(dict(条件=name, 方向=side, 期待支持=expected))
    return outcomes


def trading_cases(strategy: object, catalog: object) -> list[dict]:
    """
    機能: 同じ人工候補から旧支持不合格とLP支持、硬取消、gap再準備を比較する。
    引数: strategy/catalog(object)は対象実装・条件。
    返り値: list[dict]。両商品・買売各5経路の20口座。全raw幾何/経済も独立再生する。
    """
    configurations = {item['id']: item for item in catalog.catalog()}
    outcomes = []
    helper = common.module('99支持境界の人工素材読取', common.BASE / 'engine_preflight/support.py')
    for symbol in catalog.SYMBOLS:
        for side in (-1, 1):
            for name in ('LP支持', '旧支持不合格', '硬反対競合', 'C3待機不足', 'C3再準備'):
                config = configurations['L1_C3_A7_X3' if name.startswith('C3') else
                    'L0_C1_A7_X3' if name == '旧支持不合格' else 'L1_C1_A7_X3']
                value = artificial.fixture(symbol, side)
                signal, record = value['signal'], value['record']
                # ----------------------------------------
                # 同候補の支持だけを変える。旧候補・価格・時計・出口の別変更はしない。
                signal['entry_j2_long'][:] = False
                signal['entry_j2_short'][:] = False
                if name == '硬反対競合':
                    signal['wait_opposite_' + ('long' if side == 1 else 'short')][90:] = True
                if name.startswith('C3'):
                    record['time_s'][100:] += 20.
                    signal['grid'][100:] += 20.
                    signal['entry_peer_bbo'][100:, 2] += 20.
                if name == 'C3再準備':
                    scale, peer_scale = (1., 20.) if symbol == 'TOPIX' else (20., 1.)
                    for field in ('bid', 'ask', 'price'):
                        record[field][104] -= side * scale
                    signal['entry_peer_bbo'][104, 3:5] -= side * peer_scale
                key = record['session'], symbol
                helper.attach_support({key: value})
                support.verify_material(key, value['artificial_support_material'], value)
                actual = strategy.play(config, key, {key: value})
                independent.compare(record, signal, config, value['reference_open'], actual, value)
                if name in ('旧支持不合格', '硬反対競合', 'C3待機不足'):
                    assert len(actual['orders']) == 0
                else:
                    assert len(actual['trades']) >= 1, (name, symbol, side, actual['entry_policy_events'][:, :4])
                if name == '硬反対競合':
                    cancel = actual['entry_wait_events']
                    assert np.any((cancel[:, 1] == 3) & (cancel[:, 2] == 6))
                if name.startswith('C3'):
                    events = actual['entry_policy_events']
                    starts = events[events[:, 1] == 2, 0]
                    reprepare = events[events[:, 1] == 4, 0]
                    assert 100 in starts and len(reprepare) >= 1 and reprepare[0] > 100
                    reserve = actual['events'][actual['events'][:, 3] == 1, 0]
                    assert not np.isin(reserve, reprepare).any(), '再準備同行に発注した'
                outcomes.append(dict(条件=name, 商品=symbol, 方向=side, 決済親=len(actual['trades'])))
    return outcomes


def main() -> None:
    """
    機能: 支持32境界と売買20経路を実行し、現在コード指紋へ証跡を保存する。
    引数: なし。
    返り値: None。新正式P/L、現在API、実注文は行わない。
    """
    strategy = common.module('99独立支持境界戦略', common.BASE / 'strategy.py')
    catalog = common.module('99独立支持境界条件', common.BASE / 'catalog.py')
    scalar, trading = scalar_cases(strategy), trading_cases(strategy, catalog)
    paths = [common.HERE / name for name in ('common.py', 'support.py', 'watch.py', 'independent.py', 'artificial.py', 'boundaries.py')]
    paths += [common.BASE / name for name in ('catalog.py', 'strategy.py', 'engine.py', 'engine_preflight/support.py')]
    common.save(common.HERE / '支持源の資格と硬取消及び再準備の独立正負境界.json', dict(
        合格=True, 支持特徴境界=scalar, 人工売買=trading, 支持特徴数=len(scalar), 人工口座数=len(trading),
        検査範囲='支持数式の正負と上下反射、旧不支持/LP支持、旧硬反対優先、LP支持によるC3後続再準備と同行発注禁止。再準備前のpeakを復活させず、新局所押し量が不足なら不参加。',
        OFI未知の意味='未知のOFIは十分な逆証拠に数えない。支持の根拠は別に正常な両市場LP300進行と強弱比を要求する。',
        旧時計政策の全40列主張=False, 正式99損益=0, API取得=0, 実注文=0, SHA256=common.fingerprint(paths)))
    print('独立支持32境界と売買20経路: 合格', flush=True)


if __name__ == '__main__':
    main()
