"""新96の旧出口対照を、95保存J8全62口座へ完全照合する。"""

import hashlib
from pathlib import Path

import numpy as np

import common


def array_sha(value: np.ndarray) -> str:
    """
    機能: 配列の原バイトを変更せず指紋化する。
    引数: value(ndarray)は比較対象。
    返り値: str。SHA256指紋。
    """
    return hashlib.sha256(value.tobytes()).hexdigest()


def main() -> None:
    """
    機能: 旧対照だけを再生し、62口座の候補・経済・旧診断を保存95に照合する。
    引数: なし。
    返り値: None。新出口の正式P/Lは作らない。
    """
    common.old_immutable()
    catalog = common.module('96独立対照条件', common.BASE / 'catalog.py')
    data = common.module('96独立対照入力', common.BASE / 'data.py')
    strategy = common.module('96独立対照戦略', common.BASE / 'strategy.py')
    config = next(value for value in catalog.catalog() if value['id'] == catalog.CONTROL)
    material = data.load_inputs()
    prepared = strategy.prepare(material, config)
    previous = {}
    paths = []
    for part in ('front', 'back'):
        path = common.ROOT / 'work/wave_v95' / part / 'ledgers/P0_R0.pkl'
        previous.update(common.read(path))
        paths.append(path)
    assert set(prepared) == set(previous) and len(previous) == 62
    counts = dict(口座=0, 注文=0, 決済親=0, 原板行=0)
    for key in sorted(previous):
        actual = strategy.play(config, key, prepared)
        saved = previous[key]
        for name in ('orders', 'trades', 'events', 'stats', 'slots', 'range_parent_diagnostics', 'loss_reentry_events'):
            common.exact(actual[name], saved[name], str(key) + '/' + name)
        for name in ('curve', 'source_curve', 'target_trace', 'range_state_trace', 'risk_state_trace', 'price_source_trace'):
            field = name.replace('_trace', '') + '_SHA256' if name in ('range_state_trace', 'risk_state_trace', 'price_source_trace') else name + '_SHA256'
            assert array_sha(actual[name]) == saved[field], (key, name)
        signal = prepared[key]['signal']
        assert array_sha(signal['event']) == saved['trend_event_SHA256']
        # ----------------------------------------
        # 95台帳は格子modeの別指紋を保存しない。公開modeは既に22源全行指紋で照合済み。
        counts['口座'] += 1
        counts['注文'] += len(actual['orders'])
        counts['決済親'] += len(actual['trades'])
        counts['原板行'] += len(prepared[key]['record']['time_s'])
        print('/'.join(key) + ': 旧J8保存経済と全旧状態が完全一致', flush=True)
    common.old_immutable()
    paths.extend([common.BASE / name for name in ('engine.py', 'strategy.py', 'catalog.py', 'data.py')])
    paths.extend([Path(__file__), common.HERE / 'common.py', common.ROOT / 'work/wave_v95/事前固定.json'])
    common.save(common.HERE / '旧S40_M0_H30のJ8全62口座及び候補と経済の完全一致.json', dict(
        合格=True, 条件=catalog.CONTROL, 旧条件='95 P0_R0=94 J8', 検査件数=counts,
        全配列公差=0, 新出口正式損益=0, API取得=0, 実注文=0, 旧変更=0,
        SHA256=common.fingerprint(paths)))


if __name__ == '__main__':
    main()
