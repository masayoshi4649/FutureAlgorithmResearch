"""四つの対照の経済出力を、旧92の保存台帳へ完全一致させる。"""

import hashlib
from pathlib import Path

import numpy as np

import accounting
import catalog
import data
import research
import strategy

HERE = Path(__file__).resolve().parent
OLD = HERE.parent / 'wave_v92'


def main() -> None:
    """
    機能: C00/C01/S00/S01の全31場を再生し、旧保存注文・会計を照合する。
    引数: なし。
    返り値: None。新部品の損益を計算せず、既知の四対照だけを検査する。
    """
    assert not (HERE / '事前固定.json').exists()
    material = data.load_inputs()
    configs = {value['id']: value for value in catalog.catalog()}
    pairs = dict(C00='R_B25_C', C01='R_B25_C_ESTOP', S00='J8', S01='J10')
    checks, input_paths = [], []
    for ident, old_id in pairs.items():
        old_ledgers, old_accounts = {}, {}
        for stage in ('front', 'back'):
            path = OLD / stage / 'ledgers' / (old_id + '.pkl')
            result_path = OLD / stage / 'results' / (old_id + '.json')
            old_result = research.read(result_path)
            assert data.digest(path) == old_result['ledger_SHA256']
            old_ledgers.update(research.read(path))
            old_accounts.update({(row['session'], row['symbol']): row for row in old_result['rows']})
            input_paths += [path, result_path]
        config = configs[ident]
        prepared = strategy.prepare(material, config)
        for key in sorted(prepared):
            output = strategy.play(config, key, prepared)
            old = old_ledgers[key]
            for name in ('orders', 'trades', 'events', 'stats', 'slots'):
                np.testing.assert_array_equal(output[name], old[name])
            for name in ('curve', 'source_curve', 'target_trace', 'range_state_trace'):
                digest = hashlib.sha256(output[name].tobytes()).hexdigest()
                stored_name = 'range_state_SHA256' if name == 'range_state_trace' else name + '_SHA256'
                assert digest == old[stored_name], (ident, key, name)
            assert accounting.account(key, output) == old_accounts[key], (ident, key, '会計')
            checks.append(dict(id=ident, 旧ID=old_id, session=key[0], symbol=key[1], 行数=len(output['curve'])))
        print(ident + ' 旧' + old_id + ' 全31場の注文と全原板経済状態が一致', flush=True)
    # ----------------------------------------
    # 新しい状態列は別に監査し、旧経済列の一致と混同しない。
    assert len(checks) == 248
    paths = [Path(__file__), HERE / 'catalog.py', HERE / 'engine.py', HERE / 'strategy.py',
             HERE / 'data.py', HERE / 'accounting.py', HERE / 'research.py'] + input_paths
    research.save(HERE / 'audit/四対照の全31注文と全原板経済状態の完全一致.json',
                  dict(全合格=True, 条件数=4, 口座数=len(checks), 各口座=checks,
                       対象='C00/C01/S00/S01の経済列と旧25状態列。新40状態と親診断は別監査。',
                       新部品損益実行=0, 全31既知=True, API取得=0, 実注文=0,
                       SHA256={str(path.relative_to(research.ROOT)): data.digest(path) for path in paths}))


if __name__ == '__main__':
    main()
