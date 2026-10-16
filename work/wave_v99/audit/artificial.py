"""34待機政策入口を生価格経路から独立再生し、両商品と買売の幾何を検算する。"""

from copy import deepcopy
import ast
from pathlib import Path

import numpy as np

import common
import independent
import support


def fixture(symbol: str, side: int = 1) -> dict:
    """
    機能: 根の公開人工原板を読取素材だけとして使用し、上下反射を加える。
    引数: symbol(str)、side(int)は売買方向。
    返り値: dict。人工原板、旧候補、公開peer、保存始値。
    根の注文や状態結果は使わず、この素材から独立oracleを起動する。
    """
    source = common.ROOT / 'work/wave_v97/根台帳の保存往復を確かめる.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    function = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == 'fixture')
    pure = ast.Module(body=[function], type_ignores=[])
    namespace = {'np': np}
    exec(compile(ast.fix_missing_locations(pure), str(source), 'exec'), namespace)
    value = deepcopy(namespace['fixture'](symbol))
    value['record']['session'] = '2099-01-01_Day'
    scale, peer_scale = (1., 20.) if symbol == 'TOPIX' else (20., 1.)
    extra = np.full(801, 36.)
    extra[:95] = np.nan
    extra[95:100] = np.arange(22., 32., 2.)
    extra[100:105] = np.arange(29., 24., -1.)
    extra[105:110] = np.arange(26., 31.)
    extra[110:125] = 60.
    record, signal = value['record'], value['signal']
    record['bid'][95:] = (3999.5 + extra[95:]) * scale
    record['ask'][95:] = record['bid'][95:] + .5 * scale
    record['price'][95:] = (record['bid'][95:] + record['ask'][95:]) * .5
    signal['entry_peer_bbo'][95:, 3] = (3999.5 + extra[95:]) * peer_scale
    signal['entry_peer_bbo'][95:, 4] = signal['entry_peer_bbo'][95:, 3] + .5 * peer_scale
    signal['event'][95] = 1
    if side == -1:
        record, signal = value['record'], value['signal']
        center = value['reference_open']
        old_bid = record['bid'].copy()
        record['bid'], record['ask'] = 2 * center - record['ask'], 2 * center - old_bid
        record['price'] = 2 * center - record['price']
        signal['event'] *= -1
        peer_center = 80000. if symbol == 'TOPIX' else 4000.
        peer = signal['entry_peer_bbo']
        old_bid = peer[:, 3].copy()
        peer[:, 3], peer[:, 4] = 2 * peer_center - peer[:, 4], 2 * peer_center - old_bid
    helper = common.module('99人工原支持素材だけ読取', common.BASE / 'engine_preflight/support.py')
    key = value['record']['session'], symbol
    helper.attach_support({key: value})
    support.verify_material(key, value['artificial_support_material'], value)
    return value


def main() -> None:
    """
    機能: 34基本経路を両商品/上下で実行し、生候補からの独立watchと経済へ照合する。
    引数: なし。
    返り値: None。新正式セッションを完結再生しない。
    """
    catalog = common.module('99独立人工条件', common.BASE / 'catalog.py')
    strategy = common.module('99独立人工戦略', common.BASE / 'strategy.py')
    counts = dict(経路=0, 注文=0, 決済親=0, 原板行=0, 候補受理=0, 触発=0)
    for config in catalog.catalog():
        for symbol in catalog.SYMBOLS:
            for side in (1, -1):
                value = fixture(symbol, side)
                key = value['record']['session'], symbol
                actual = strategy.play(config, key, {key: value})
                checked = independent.compare(value['record'], value['signal'], config, value['reference_open'], actual, value)
                assert len(actual['trades']) >= 1, '待機の成立へ未到達'
                counts['経路'] += 1
                for name, count in checked.items():
                    counts[name] += count
        print(config['id'] + ': 独立候補/待機/最初triggerと実経済が一致', flush=True)
    paths = [common.BASE / name for name in ('engine.py', 'strategy.py', 'catalog.py')]
    paths += [common.ROOT / 'work/wave_v97/根台帳の保存往復を確かめる.py']
    paths += [common.BASE / 'engine_preflight/support.py']
    paths += [common.HERE / name for name in ('common.py', 'watch.py', 'independent.py', 'support.py', 'artificial.py')]
    common.save(common.HERE / '全34基本人工の候補待機幾何及び独立最初触発と実経済.json', dict(
        合格=True, 検査件数=counts, 比較='生候補と自己raw/公開peerから再構成。注文/親/出口状態/全raw数量枠とwatch32及び入口45の因果部分。',
        新支持の検査='明示した人工LP原素材と旧BBO素材からscalar支持と59列を公差0で再構成。旧候補と硬取消は維持。',
        正式99損益=0, API取得=0, 実注文=0, SHA256=common.fingerprint(paths)))


if __name__ == '__main__':
    main()
