"""固定旧入口の実接頭部で、新出口の未来切断と自己・相手未来変更を検査する。"""

from copy import deepcopy
from pathlib import Path

import numpy as np

import common
import independent

REPRESENTATIVES = ('S10_M1_UNL', 'S40_M0_H30', 'S10_M2_UNL', 'S20_M1_H30')


def shorten(value: dict, cut: int) -> dict:
    """
    機能: 既知運用末を変更せず、原板と原板長の信号だけを切断する。
    引数: value(dict)は一口座のprepared、cut(int)は残す行数。
    返り値: dict。格子定義は保持し、端点返済を作らない接頭部。
    """
    n = len(value['record']['time_s'])
    result = dict(value)
    result['record'] = {k: v[:cut].copy() if isinstance(v, np.ndarray) and len(v) == n else deepcopy(v)
                         for k, v in value['record'].items()}
    raw_fields = {'event', 'mapped', 'quality', 'reset', 'execution_lp_index'}
    result['signal'] = {k: v[:cut].copy() if k in raw_fields else deepcopy(v)
                         for k, v in value['signal'].items()}
    return result


def compare_past(short: dict, longer: dict, cut: int, label: str) -> None:
    """
    機能: 接頭部までに公表済みの経済と新出口状態だけを厳密比較する。
    引数: short/longer(dict)、cut(int)、label(str)。
    返り値: None。未来による過去の変更は例外。
    """
    for name in ('orders', 'trades', 'trend_parent_diagnostics'):
        column = 2 if name == 'trend_parent_diagnostics' else 3 if name == 'trades' else 0
        common.exact(short[name], longer[name][longer[name][:, column] < cut], label + '/' + name)
    for name in ('target_trace', 'curve', 'trend_exit_state_trace'):
        common.exact(short[name], longer[name][:cut], label + '/' + name)


def main() -> None:
    """
    機能: 4代表、3場、両市場の少数実接頭と自己/相手未来poisonを保存する。
    引数: なし。
    返り値: None。完結した新条件セッション又は新正式P/Lは計算しない。
    """
    data = common.module('96独立接頭入力', common.BASE / 'data.py')
    strategy = common.module('96独立接頭戦略', common.BASE / 'strategy.py')
    catalog = common.module('96独立接頭条件', common.BASE / 'catalog.py')
    material = data.load_inputs()
    conditions = {value['id']: value for value in catalog.catalog()}
    prepared = strategy.prepare(material, conditions[catalog.CONTROL])
    sessions = material['metadata']['sessions']
    selected = list(dict.fromkeys((sessions[0], next(s for s in sessions if s.endswith('_Night')), sessions[-1])))
    old = {}
    old_paths = []
    for part in ('front', 'back'):
        path = common.ROOT / 'work/wave_v95' / part / 'ledgers/P0_R0.pkl'
        old.update(common.read(path))
        old_paths.append(path)
    counts = dict(代表条件=4, 商品場=0, 接頭部=0, 独立出口再生=0, 自己未来=0, 相手未来=0)
    for ident in REPRESENTATIVES:
        config = conditions[ident]
        for session in selected:
            for symbol in catalog.SYMBOLS:
                key = session, symbol
                value = prepared[key]
                n = len(value['record']['time_s'])
                trades = np.asarray(old[key]['trades'])
                cuts = [int(n * .75)]
                if len(trades):
                    cuts += [int(trades[0, 2]) + 1, int(trades[0, 3]) + 1]
                else:
                    cuts += [int(n * .25), int(n * .5)]
                counts['商品場'] += 1
                for cut in sorted(set(c for c in cuts if 0 < c < n - 50)):
                    piece = shorten(value, cut)
                    short = strategy.play(config, key, {key: piece}, finish=False)
                    independent.compare(piece['record'], piece['signal'], config, value['reference_open'], short)
                    counts['独立出口再生'] += 1
                    longer_value = shorten(value, cut + 50)
                    longer = strategy.play(config, key, {key: longer_value}, finish=False)
                    compare_past(short, longer, cut, ident + '/切断')
                    counts['接頭部'] += 1
                    own = deepcopy(longer_value)
                    for field in ('bid', 'ask', 'price'):
                        own['record'][field][cut:] += 100 * value['record']['tick']
                    own['record']['quote_valid'][cut:] = False
                    own['signal']['event'][cut:] *= -1
                    modified = strategy.play(config, key, {key: own}, finish=False)
                    compare_past(short, modified, cut, ident + '/自己未来')
                    counts['自己未来'] += 1
                    peer = deepcopy(longer_value)
                    future = peer['signal']['grid'] > piece['record']['time_s'][-1]
                    for field in ('peer_mid', 'peer_source', 'peer_source_time', 'arm_common',
                                  'arm_trend300', 'mode', 'peer_valid', 'peer_low', 'peer_high'):
                        if field in peer['signal']:
                            arr = peer['signal'][field]
                            if arr.dtype == np.bool_:
                                arr[future] = ~arr[future]
                            else:
                                arr[future] *= -1
                    modified = strategy.play(config, key, {key: peer}, finish=False)
                    compare_past(short, modified, cut, ident + '/相手未来')
                    counts['相手未来'] += 1
                print(ident + '/' + '/'.join(key) + ': 実接頭と未来不変が一致', flush=True)
    paths = [common.BASE / name for name in ('engine.py', 'strategy.py', 'catalog.py', 'data.py')]
    paths += [Path(__file__), common.HERE / 'common.py', common.HERE / 'independent.py', *old_paths]
    common.save(common.HERE / '4代表の実接頭と独立出口及び自己相手未来の不変.json', dict(
        合格=True, 代表=list(REPRESENTATIVES), 対象場=selected, 検査件数=counts,
        元入口='旧J8の素材と因果入力は95検査済みをそのまま読取。今回新しい候補学習又はLP分類を行わない。',
        完結した新条件口座=0, 正式96損益=0, 全31既知=True, 未見場数=0,
        API取得=0, 実注文=0, SHA256=common.fingerprint(paths)))


if __name__ == '__main__':
    main()
