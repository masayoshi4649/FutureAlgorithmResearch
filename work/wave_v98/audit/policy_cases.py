"""四時計政策の意味境界を少数の明示正負価格経路で検査する。"""

import numpy as np

import artificial
import common
import independent


def set_prices(value: dict, moves: list[float], side: int) -> None:
    """
    機能: 始値からの自己と相手quote差を別呼値の上下反射経路へ設定する。
    引数: value(dict)、moves(list[float])はTOPIX尺度、side(int)。
    返り値: None。原seqは保存順のまま、価格代理時計を捏造しない。
    """
    record, signal = value['record'], value['signal']
    scale = 1. if record['symbol'] == 'TOPIX' else 20.
    peer_scale = 20. if record['symbol'] == 'TOPIX' else 1.
    movement = np.full(len(record['time_s']), moves[-1])
    movement[:len(moves)] = moves
    quote = value['reference_open'] + side * movement * scale
    record['bid'] = quote - record['tick'] if side == 1 else quote.copy()
    record['ask'] = quote if side == 1 else quote + record['tick']
    record['price'] = .5 * (record['bid'] + record['ask'])
    peer = signal['entry_peer_bbo']
    quote = (80000. if record['symbol'] == 'TOPIX' else 4000.) + side * movement * peer_scale
    peer[:, 3] = quote - signal['peer_tick'] if side == 1 else quote
    peer[:, 4] = quote if side == 1 else quote + signal['peer_tick']
    signal['event'][:] = 0
    signal['event'][1] = side


def clocks(value: dict, first: int, shift: float) -> None:
    """
    機能: 指定行からの価格代理時計を移し、公開格子とpeerの時計だけ整合させる。
    引数: value(dict)、first(int)、shift(float)は価格clockの追加秒数。
    返り値: None。真受信clock又は商品間seq対応とは主張しない。
    """
    record, signal = value['record'], value['signal']
    record['time_s'][first:] += shift
    signal['grid'][:] = record['time_s']
    signal['entry_peer_bbo'][:, 2] = record['time_s'] - 1.
    record['limit'] = record['time_s'][-1]


def fixture(name: str, symbol: str, side: int) -> tuple[dict, int, dict]:
    """
    機能: 旧入力だけからgap保持・sameclock・別epochの正負例を作る。
    引数: name/symbol(str)、side(int)。
    返り値: tuple[dict,int,dict]。素材、入口種別、政策ごとの明示最初触発。
    """
    value = artificial.fixture(symbol, side)
    record, signal = value['record'], value['signal']
    peer = signal['entry_peer_bbo']
    kind = 3
    set_prices(value, [0., 0., 4., 4., 5., 6., 7.], side)
    expected = {'C0': None, 'C1': 2, 'C2': 2, 'C3': 4}
    if name == 'gap行の発注差':
        clocks(value, 2, 7.)
    elif name == 'sameclock両源更新':
        record['time_s'][2] = record['time_s'][1]
        signal['grid'][2] = record['time_s'][2]
        peer[2, 2] = record['time_s'][1]
        expected = {'C0': 3, 'C1': 3, 'C2': 2, 'C3': 3}
    elif name == 'C2未知sameclock基準は同行不可':
        record['time_s'][2:4] = record['time_s'][1]
        signal['grid'][:4] = record['time_s'][:4]
        peer[2:4, 2] = record['time_s'][1]
        peer[:2, 5] = 0.
        set_prices(value, [0., 0., 4., 5., 5., 6., 7.], side)
        expected = {'C0': None, 'C1': 5, 'C2': 3, 'C3': 6}
    elif name == 'C3未知epochは基準と再準備を分離':
        clocks(value, 2, 7.)
        peer[2, 5] = 0.
        expected = {'C0': None, 'C1': 3, 'C2': 3, 'C3': 5}
    elif name == '再準備はquote順行を要求しない':
        kind = 7
        set_prices(value, [0., 0., 4., 0., 4., 0., 2., 3.], side)
        clocks(value, 2, 7.)
        expected = {'C0': None, 'C1': 4, 'C2': 4, 'C3': 6}
    elif name == 'gap新候補C3もepoch開始':
        clocks(value, 1, 10.)
        set_prices(value, [0., 0., 4., 5., 5.], side)
        expected = {'C0': None, 'C1': 2, 'C2': 2, 'C3': 3}
    elif name == 'epoch再発はTTL非延長':
        clocks(value, 2, 7.)
        clocks(value, 3, 7.)
        set_prices(value, [0., 0., 4., 4., 4., 5., 5.], side)
        expected = {'C0': None, 'C1': 2, 'C2': 2, 'C3': 5}
    elif name == 'gapとresetは全政策取消':
        clocks(value, 2, 7.)
        signal['reset'][2] = True
        expected = {policy: None for policy in ('C0', 'C1', 'C2', 'C3')}
    elif name == 'gapとTTLの同行候補は消費':
        set_prices(value, [0.] * 61 + [4., 5.], side)
        signal['event'][61] = side
        expected = {policy: None for policy in ('C0', 'C1', 'C2', 'C3')}
    elif name == '未来peerは支持及び基準不可':
        clocks(value, 2, 7.)
        peer[2:4, 2] = record['time_s'][2:4] + 1.
        expected = {'C0': None, 'C1': 4, 'C2': 4, 'C3': 6}
    else:
        raise ValueError(name)
    return value, kind, expected


def main() -> None:
    """
    機能: 少数10意味の政策対照を両商品上下で独立経済と明示触発へ照合する。
    引数: なし。
    返り値: None。新正式P/Lを計算しない。
    """
    catalog = common.module('98政策境界条件', common.BASE / 'catalog.py')
    strategy = common.module('98政策境界戦略', common.BASE / 'strategy.py')
    configs = {(config['entry_clock_policy'], config['entry_wait_kind']): config
        for config in catalog.catalog() if config['id'].endswith('X3') and config['entry_wait_kind']}
    names = ('gap行の発注差', 'sameclock両源更新', 'C2未知sameclock基準は同行不可',
        'C3未知epochは基準と再準備を分離', '再準備はquote順行を要求しない',
        'gap新候補C3もepoch開始', 'epoch再発はTTL非延長', 'gapとresetは全政策取消',
        'gapとTTLの同行候補は消費', '未来peerは支持及び基準不可')
    results = []
    for name in names:
        for symbol in catalog.SYMBOLS:
            for side in (1, -1):
                value, kind, expected = fixture(name, symbol, side)
                for policy, trigger in expected.items():
                    config = configs[policy, kind]
                    key = value['record']['session'], symbol
                    actual = strategy.play(config, key, {key: value})
                    checked = independent.compare(value['record'], value['signal'], config,
                        value['reference_open'], actual)
                    common.exact(actual['entry_parent_diagnostics'][:, 28], [] if trigger is None else [trigger],
                        name + '/' + policy + '/明示最初触発')
                    results.append(dict(意味=name, 政策=policy, 商品=symbol, 方向=side,
                        期待trigger=trigger, 独立照合件数=checked))
        print(name + ': 各政策/両商品/上下の因果幾何及び実経済が一致', flush=True)
    paths = [common.HERE / name for name in ('common.py', 'watch.py', 'independent.py', 'artificial.py', 'policy_cases.py')]
    paths += [common.BASE / name for name in ('catalog.py', 'engine.py', 'strategy.py')]
    paths += [common.ROOT / 'work/wave_v97/audit/watch.py']
    common.save(common.HERE / '少数時計政策の正負及び別epochと最初触発の独立検算.json',
        dict(合格=True, 意味数=len(names), 経路数=len(results), 検査=results,
             新正式損益=0, API取得=0, 実注文=0, SHA256=common.fingerprint(paths)))


if __name__ == '__main__':
    main()
