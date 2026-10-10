"""同一行で得た見送り情報を過去の有効注文へ遡及しないことを確認する。"""

from __future__ import annotations

import importlib.util
import os
import sys

import numpy as np

from independent_audit import HERE, ROOT, read, save, sha


def check() -> dict:
    """機能: 人工の最小価格列で取消と約定の順序を確認する。

    引数: なし。返り値: 4ケースの検査証跡 (dict)。
    約定行と同じ時刻でも原本順を守り、前行の注文だけを有効とする。
    """
    os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'numba_cache')
    sys.dont_write_bytecode = True
    path = ROOT / 'work/wave_v38/engine_shadow_plan.py'
    spec = importlib.util.spec_from_file_location('v49_audit_shadow', path)
    engine = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = engine
    spec.loader.exec_module(engine)
    ledger = read(ROOT / 'work/wave_v48/update_20261001/ledgers/F50_NONE__E11.json.gz')
    config = dict(next(row['config'] for row in ledger if row['symbol'] == 'TOPIX'),
                  tighten_atr=0., tight_width=1.)
    checks = []
    for duplicate in (False, True):
        for early_cancel in (False, True):
            state = np.asarray([1, 0 if early_cancel else 1, 0, 0, 0], dtype=np.int8)
            ready = dict(last=np.asarray([100., 100., 105., 105., 105.]),
                         atr=np.repeat(20., 5), time_s=np.asarray([1200., 1201., 1201. if duplicate else 1202., 1900., 1901.]),
                         tick=1., start=0., limit=1900., us_open=99999., session_close=2500.)
            result = engine.run(ready, state, config, detail=True)
            openings = result['orders'][result['orders'][:, 7] == 1]
            assert len(openings) == int(not early_cancel)
            if len(openings):
                assert openings[0, 0] == 2 and openings[0, 1] < 2
                assert state[2] == 0
                assert result['plans'][1, 21] == 1
            else:
                assert result['plans'][1, 21] == 0
            assert result['stats'][9] == 0
            checks.append(dict(同秒原本群=duplicate, 前行までに取消=early_cancel,
                               初回注文数=len(openings), 全合格=True))
    output = dict(全合格=True, ケース=checks, エンジンSHA256=sha(path),
                  結論='取消は観測した行の後に有効。同じ行で価格到達している旧注文を遡及取消しない。')
    save('新規取消の原本順検査.json', output)
    return output


if __name__ == '__main__':
    print(check()['結論'])
