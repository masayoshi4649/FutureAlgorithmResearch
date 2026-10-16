"""98の厳密時計対照10条件を97保存18配列へ公差0で照合する。"""

import hashlib
from pathlib import Path

import numpy as np

import common


def array_sha(value: np.ndarray) -> str:
    """
    機能: 保存台帳と同じ配列バイトのSHA256を計算する。
    引数: value(ndarray)は経済又は原板状態。
    返り値: str。現在配列の16進指紋。
    """
    return hashlib.sha256(value.tobytes()).hexdigest()


def prepared_sha(prepared: dict) -> str:
    """
    機能: 共有原板/信号内の全配列と保存始値を順に読み、変更を検出する。
    引数: prepared(dict[tuple,dict])は共有入力。
    返り値: str。キー・型・形状と全配列の結合指紋。
    """
    digest = hashlib.sha256()
    for key in sorted(prepared):
        value = prepared[key]
        digest.update(repr((key, value['reference_open'])).encode('utf-8'))
        for section in ('record', 'signal'):
            for name, item in sorted(value[section].items()):
                if isinstance(item, np.ndarray):
                    digest.update(repr((section, name, item.dtype.str, item.shape)).encode('utf-8'))
                    digest.update(item.tobytes())
    return digest.hexdigest()


def main() -> None:
    """
    機能: C0八待機とA0二即時の全620口座を、旧97の18配列及び候補へ照合する。
    引数: なし。
    返り値: None。新C1〜3の実損益は計算しない。共有prepared及び旧650依存を保持する。
    """
    common.old_immutable()
    catalog = common.module('98独立null条件', common.BASE / 'catalog.py')
    data = common.module('98独立null入力', common.BASE / 'data.py')
    strategy = common.module('98独立null戦略', common.BASE / 'strategy.py')
    configs = [value for value in catalog.catalog() if value['entry_clock_policy'] == 'C0']
    assert len(configs) == 10
    material = data.load_inputs()
    prepared = strategy.prepare(material, configs[0])
    before = prepared_sha(prepared)
    counts, paths = dict(条件=10, 口座=0, 注文=0, 決済親=0, 原板行=0), []
    for config in configs:
        previous = {}
        for part in ('front', 'back'):
            path = common.ROOT / 'work/wave_v97' / part / 'ledgers' / (config['previous_id'] + '.pkl')
            previous.update(common.read(path))
            paths.append(path)
        assert len(previous) == 62 and set(previous) == set(prepared)
        for key in sorted(previous):
            actual = strategy.play(config, key, prepared)
            saved = previous[key]
            for name in ('orders', 'trades', 'events', 'stats', 'slots', 'range_parent_diagnostics',
                         'loss_reentry_events', 'trend_parent_diagnostics', 'entry_parent_diagnostics',
                         'entry_wait_events'):
                common.exact(actual[name], saved[name], config['id'] + '/' + str(key) + '/' + name)
            for name, field in (
                ('curve', 'curve_SHA256'), ('source_curve', 'source_curve_SHA256'),
                ('target_trace', 'target_trace_SHA256'), ('range_state_trace', 'range_state_SHA256'),
                ('risk_state_trace', 'risk_state_SHA256'), ('price_source_trace', 'price_source_SHA256'),
                ('trend_exit_state_trace', 'trend_exit_state_SHA256'), ('watch_state_trace', 'watch_state_SHA256')):
                assert array_sha(actual[name]) == saved[field], (config['id'], key, name)
            assert array_sha(prepared[key]['signal']['event']) == saved['trend_event_SHA256']
            counts['口座'] += 1
            counts['注文'] += len(actual['orders'])
            counts['決済親'] += len(actual['trades'])
            counts['原板行'] += len(prepared[key]['record']['time_s'])
        print(config['id'] + ': 対応97全62の旧18配列と候補が完全一致', flush=True)
    assert counts['口座'] == 620 and prepared_sha(prepared) == before
    common.old_immutable()
    paths += [common.BASE / name for name in ('engine.py', 'strategy.py', 'catalog.py', 'data.py')]
    paths += [Path(__file__), common.HERE / 'common.py', common.ROOT / 'work/wave_v97/事前固定.json']
    common.save(common.HERE / '厳密時計10条件の97全620口座及び旧18配列と共有入力の完全一致.json', dict(
        合格=True, 検査件数=counts, 公差=0, 共有prepared不変=True, 共有preparedSHA256=before,
        新政策正式損益=0, 旧変更=0, API取得=0, 実注文=0, SHA256=common.fingerprint(paths)))


if __name__ == '__main__':
    main()
