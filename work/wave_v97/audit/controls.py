"""97の即時四出口を96の全248保存口座へ経済nullとして照合する。"""

import hashlib
from pathlib import Path

import common


def array_sha(value: object) -> str:
    """
    機能: 旧15配列の保存指紋を現在配列から算出する。
    引数: value(ndarray)は本体配列。
    返り値: str。原バイトのSHA256。
    """
    return hashlib.sha256(value.tobytes()).hexdigest()


def main() -> None:
    """
    機能: A0四対照だけを実行し、対応96の全注文・会計・旧診断を完全比較する。
    引数: なし。
    返り値: None。新しい待機戦略の正式P/Lは計算しない。
    """
    common.old_immutable()
    catalog = common.module('97独立即時条件', common.BASE / 'catalog.py')
    data = common.module('97独立即時入力', common.BASE / 'data.py')
    strategy = common.module('97独立即時戦略', common.BASE / 'strategy.py')
    configs = [value for value in catalog.catalog() if value['entry_wait_kind'] == 0]
    assert len(configs) == 4
    material = data.load_inputs()
    prepared = strategy.prepare(material, configs[0])
    counts, paths = dict(条件=4, 口座=0, 注文=0, 決済親=0, 原板行=0), []
    for config in configs:
        previous = {}
        old_id = catalog.EXITS[int(config['id'].split('X')[1])]
        for part in ('front', 'back'):
            path = common.ROOT / 'work/wave_v96' / part / 'ledgers' / (old_id + '.pkl')
            previous.update(common.read(path))
            paths.append(path)
        assert len(previous) == 62 and set(previous) == set(prepared)
        for key in sorted(previous):
            actual = strategy.play(config, key, prepared)
            saved = previous[key]
            for name in ('orders', 'trades', 'events', 'stats', 'slots', 'range_parent_diagnostics',
                         'loss_reentry_events', 'trend_parent_diagnostics'):
                common.exact(actual[name], saved[name], config['id'] + '/' + str(key) + '/' + name)
            for name, field in (
                ('curve', 'curve_SHA256'), ('source_curve', 'source_curve_SHA256'),
                ('target_trace', 'target_trace_SHA256'), ('range_state_trace', 'range_state_SHA256'),
                ('risk_state_trace', 'risk_state_SHA256'), ('price_source_trace', 'price_source_SHA256'),
                ('trend_exit_state_trace', 'trend_exit_state_SHA256')):
                assert array_sha(actual[name]) == saved[field], (config['id'], key, name)
            assert array_sha(prepared[key]['signal']['event']) == saved['trend_event_SHA256']
            counts['口座'] += 1
            counts['注文'] += len(actual['orders'])
            counts['決済親'] += len(actual['trades'])
            counts['原板行'] += len(prepared[key]['record']['time_s'])
        print(config['id'] + ': 対応96全62の旧15経済及び候補が完全一致', flush=True)
    assert counts['口座'] == 248
    common.old_immutable()
    paths += [common.BASE / name for name in ('engine.py', 'strategy.py', 'catalog.py', 'data.py')]
    paths += [Path(__file__), common.HERE / 'common.py', common.ROOT / 'work/wave_v96/事前固定.json']
    common.save(common.HERE / '即時四出口の96全248口座及び旧15台帳と候補の完全一致.json', dict(
        合格=True, 検査件数=counts, 公差=0, 新待機正式損益=0, 旧変更=0,
        API取得=0, 実注文=0, SHA256=common.fingerprint(paths)))


if __name__ == '__main__':
    main()
