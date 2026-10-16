"""取消・未知ペア・時計・押し位相の少数正負例を独立全経済へ接続する。"""

import numpy as np

import artificial
import common
import full
import independent


def price_path(value: dict, moves: list[float], side: int) -> None:
    """
    機能: 人工の候補からの価格差を自己とpeerへ別呼値で設定する。
    引数: value(dict)、moves(list[float])はTOPIX尺度の差、side(int)は反射方向。
    返り値: None。候補・時刻は変更せず新規側quoteを始値からの差へ置く。
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
    center = 80000. if record['symbol'] == 'TOPIX' else 4000.
    quote = center + side * movement * peer_scale
    peer[:, 3] = quote - signal['peer_tick'] if side == 1 else quote
    peer[:, 4] = quote if side == 1 else quote + signal['peer_tick']
    signal['event'][:] = 0
    signal['event'][1] = side


def case(name: str, symbol: str, side: int, configs: dict) -> tuple[dict, dict, dict]:
    """
    機能: 一つの意味の差を持つ人工入力と期待する最初触発又は取消を作る。
    引数: name/symbol(str)、side(int)、configs(dict[str,dict])。
    返り値: tuple[dict,dict,dict]。素材、条件、正負の明示assert根拠。
    """
    value = artificial.fixture(symbol, side)
    record, signal = value['record'], value['signal']
    config = configs['A2_X3']
    expected = dict(trigger=2, cancel=None)
    price_path(value, [0., 0., 4., 4., 4., 4.], side)
    peer = signal['entry_peer_bbo']
    if name == '未知pair_A2':
        peer[:4, 5] = 0.
        expected['trigger'] = 4
    elif name == '未知pair_BBO':
        config = configs['A3_X3']
        peer[:4, 5] = 0.
        price_path(value, [0., 0., 4., 4., 4., 5.], side)
        expected.update(trigger=5, fallback=4)
    elif name == '未来peer時計':
        peer[2, 2] = record['time_s'][2] + 1.
        expected['trigger'] = 3
    elif name == '同clockseq更新':
        config = configs['A3_X3']
        record['time_s'][2] = record['time_s'][1]
        signal['grid'][2] = record['time_s'][2]
        peer[2, 2] = record['time_s'][1]
        expected['trigger'] = 3
    elif name == '押しarmの旧min復活禁止':
        config = configs['A6_X3']
        price_path(value, [0., 0., 4., 2., 2., 4.], side)
        expected.update(trigger=5, arm=3)
    elif name == '押しと回復の同row禁止':
        config = configs['A7_X3']
        price_path(value, [0., 0., 4., 0., 2., 2.], side)
        expected.update(trigger=4, arm=3)
    elif name == '品質のみ発注停止':
        signal['quality'][2] = False
        expected['trigger'] = 3
    elif name == 'reset取消':
        signal['reset'][2] = True
        expected.update(trigger=None, cancel=2, flags=8, reason=4)
    elif name == 'rawgap10許容':
        record['time_s'][2:] += 5.
        signal['grid'][:] = record['time_s']
        peer[:, 2] = record['time_s'] - 1.
        record['limit'] = record['time_s'][-1]
    elif name == 'rawgap11取消と同行消費':
        record['time_s'][2:] += 6.
        signal['grid'][:] = record['time_s']
        peer[:, 2] = record['time_s'] - 1.
        record['limit'] = record['time_s'][-1]
        signal['event'][2] = side
        expected.update(trigger=None, cancel=2, flags=4, reason=3, consumed=2)
    elif name == 'TTL等号と同行新候補消費':
        price_path(value, [0.] * 61 + [4., 4., 4.], side)
        signal['event'][61] = side
        expected.update(trigger=None, cancel=61, flags=2, reason=2, consumed=61)
    elif name == '取消六証拠の共存':
        record['time_s'][2:] += 295.
        signal['grid'][:] = record['time_s']
        peer[:, 2] = record['time_s'] - 1.
        record['limit'] = record['time_s'][2] + 300.
        record['quote_valid'][2] = False
        signal['reset'][2] = True
        signal['wait_opposite_long' if side == 1 else 'wait_opposite_short'][2] = True
        expected.update(trigger=None, cancel=2, flags=63, reason=1)
    elif name == '市場予約後BBO欠測はfill待ち':
        record['quote_valid'][3:6] = False
        expected['fill'] = 6
    elif name == '市場予約受付cut取消':
        record['quote_valid'][3:] = False
        record['quote_valid'][-1] = True
        expected['market_cancel'] = True
    else:
        raise ValueError(name)
    return value, config, expected


def main() -> None:
    """
    機能: 少数の意味境界を両商品・上下反射で実行し、明示期待と独立oracleを同時照合する。
    引数: なし。
    返り値: None。正式P/L/API/注文を生成しない。失敗は例外で止める。
    """
    catalog = common.module('97境界条件', common.BASE / 'catalog.py')
    strategy = common.module('97境界戦略', common.BASE / 'strategy.py')
    research = common.module('97境界根台帳', common.BASE / 'research.py')
    configs = {config['id']: config for config in catalog.catalog()}
    names = ('未知pair_A2', '未知pair_BBO', '未来peer時計', '同clockseq更新',
        '押しarmの旧min復活禁止', '押しと回復の同row禁止', '品質のみ発注停止',
        'reset取消', 'rawgap10許容', 'rawgap11取消と同行消費',
        'TTL等号と同行新候補消費', '取消六証拠の共存', '市場予約後BBO欠測はfill待ち',
        '市場予約受付cut取消')
    results = []
    for name in names:
        for symbol in catalog.SYMBOLS:
            for side in (1, -1):
                value, config, expected = case(name, symbol, side, configs)
                record, signal = value['record'], value['signal']
                key = record['session'], symbol
                actual = strategy.play(config, key, {key: value})
                independent.compare(record, signal, config, value['reference_open'], actual)
                diagnostics = actual['entry_parent_diagnostics']
                expected_triggers = [] if expected['trigger'] is None else [expected['trigger']]
                common.exact(diagnostics[:, 28], expected_triggers, name + '/明示最初触発')
                events = actual['entry_wait_events']
                if expected['cancel'] is not None:
                    cancels = events[(events[:, 0] == expected['cancel']) & (events[:, 1] == 3)]
                    assert len(cancels) == 1
                    common.exact(cancels[0, [2, 55]], [expected['reason'], expected['flags']])
                if 'fallback' in expected:
                    fallback = events[events[:, 1] == 7]
                    common.exact(fallback[:, 0], [expected['fallback']])
                    assert not np.any(events[(events[:, 0] == expected['fallback']), 1] == 8)
                if 'arm' in expected:
                    arms = events[events[:, 1] == 5]
                    common.exact(arms[:, 0], [expected['arm']])
                    assert not np.any(events[(events[:, 0] == expected['arm']), 1] == 8)
                if 'consumed' in expected:
                    consumed = events[(events[:, 0] == expected['consumed']) & (events[:, 1] == 2)]
                    assert len(consumed) == 1 and consumed[0, 2] == 7
                if 'fill' in expected:
                    common.exact(actual['orders'][0, 0], expected['fill'])
                if expected.get('market_cancel'):
                    assert len(actual['orders']) == 0 and diagnostics[0, 41] == 2
                ledger = research.ledger(actual, value)
                _, counts = full.verify_account(key, value, config, ledger, True)
                results.append(dict(経路=name, 銘柄=symbol, 方向=side, 期待=expected, 検査件数=counts))
        print(name + ': 両商品上下の正負及び原板独立会計が一致', flush=True)
    paths = [common.HERE / name for name in ('common.py', 'watch.py', 'independent.py', 'artificial.py', 'full.py', 'boundaries.py')]
    paths += [common.BASE / name for name in ('catalog.py', 'engine.py', 'strategy.py', 'research.py')]
    common.save(common.HERE / '待機取消及び未知ペア時計と押し位相の少数正負と全経済.json',
        dict(合格=True, 経路数=len(results), 意味境界数=len(names), 検査=results,
             正式97損益=0, API取得=0, 実注文=0, SHA256=common.fingerprint(paths)))


if __name__ == '__main__':
    main()
