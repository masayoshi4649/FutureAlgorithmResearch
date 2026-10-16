"""原入力を読まず、可逆保存・型境界・時刻固定を人工値で確認する。"""

from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
from pathlib import Path

import numpy as np

import finance
import plan


def main() -> None:
    """
    機能: RLE全行同値、未知保持、日米時刻とJSON型を純人工で検査する。
    引数: なし。
    返り値: None。金融再生・原NPZ・保存eventNPZは0。
    """
    checks = 0
    rng = np.random.default_rng(115)
    for n in (0, 1, 2, 33, 100):
        for width in (1, 16):
            array = rng.integers(-3, 4, (n, width)).astype(float)
            if n > 2:
                array[1:3] = array[0]
                array[-1, 0] = np.nan
            restored = finance.curve_unpack(finance.curve_pack(array))
            np.testing.assert_array_equal(restored, array)
            checks += 1
    assert finance.primitive(dict(x=np.float64(np.nan), y=np.int64(5))) == dict(x=None, y=5)
    checks += 1
    jst, ny = ZoneInfo('Asia/Tokyo'), ZoneInfo('America/New_York')
    for date, expected in (('2026-10-01', 22), ('2026-11-03', 23)):
        start = datetime.fromisoformat(date + 'T17:00:00').replace(tzinfo=jst).timestamp()
        end = start + 12*3600 + 55*60
        policy = plan.time_policy(date + '_Night', start, end)
        center = sum(policy['quiet_windows'][0]) / 2
        assert datetime.fromtimestamp(center, jst).hour == expected
        assert datetime.fromtimestamp(center, ny).hour == 9
        assert policy['entry_start_s'] == start + 300
        assert policy['entry_end_s'] == end - 600 and policy['force_start_s'] == end - 300
        checks += 4
    start = datetime(2026, 10, 1, 8, 45, tzinfo=jst).timestamp()
    policy = plan.time_policy('2026-10-01_Day', start, start+6*3600+55*60)
    assert policy['entry_start_s'] == start+1800 and policy['quiet_windows'] == []
    checks += 1
    names = ('input_contract.py', 'plan.py', 'finance.py', 'artificial_root.py')
    evidence = dict(全合格=True, 人工境界=checks, 新金融=0, 原NPZ=0, 保存eventNPZ=0, API=0,
        source_SHA256={str((plan.HERE / name).relative_to(plan.ROOT).as_posix()):
            hashlib.sha256((plan.HERE/name).read_bytes()).hexdigest() for name in names})
    plan.write(plan.HERE / 'rootの可逆保存と時刻型の人工.json', evidence)
    print(evidence['人工境界'])


if __name__ == '__main__':
    main()
