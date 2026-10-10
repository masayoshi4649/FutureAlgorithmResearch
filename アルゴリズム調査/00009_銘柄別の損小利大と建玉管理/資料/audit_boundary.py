"""既知代表の任意境界で、全資産差分と継続玉の扱いを独立に確認する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from audit_guard import independent_account
import details
import reference

OUT = Path(__file__).resolve().parent


def main() -> None:
    """機能: 保存済みの３区間・６方式に任意の切れ目を入れ、独立会計と比較する。

    引数: なし。返り値: None: 境界分割の独立監査.jsonを保存。通信は行わない。
    """
    prepared = reference.load_inputs()
    configs = {c['id']:c for c in json.loads((OUT/'全条件一覧.json').read_text(encoding='utf-8'))}
    targets = [
        ('2026-09-22_Day','TOPIX','N02_R-1_E1_X2_U0'),
        ('2026-09-23_Night','NK225','N10_R1_E3_X2_U1'),
        ('2026-09-24_Day','NK225','G01_T10'),
        ('2026-09-24_Day','TOPIX','G02_T10'),
        ('2026-09-23_Night','TOPIX','G15_T10'),
        ('2026-09-22_Day','NK225','G16_A10'),
    ]
    checks,carried_count,fresh_count = 0,0,0
    records = []
    for session,symbol,method in targets:
        ready,cfg = prepared[(session,symbol)],configs[method]
        result,cycles = details.single_result(ready,cfg)
        independent = independent_account(result['raw'],ready['last'])
        multiplier = reference.engine.MULTIPLIERS[symbol]
        times = ready['time_s']
        boundaries = [float(times[int(len(times)*f)]) for f in [.273,.587,.813]]
        if len(result['raw']):
            row = result['raw'][len(result['raw'])//2]
            middle = (int(row[5])+int(row[6]))//2
            if middle > 0:
                boundaries.append(float(times[middle]))
        for boundary in boundaries:
            first = np.searchsorted(times,boundary,side='left')
            base = independent[0][first-1]*multiplier
            expected = independent[0][first:]*multiplier-base
            peak = np.maximum.accumulate(np.r_[0.,expected])[1:]
            after,cs,diagnostic = details.split_single(ready,result,cycles,cfg,boundary)
            actual = independent_account(after['raw'],ready['last'])[0][first:]*multiplier
            np.testing.assert_allclose(actual,expected,atol=1e-5)
            np.testing.assert_allclose(diagnostic['baseline_equity_yen'],base,atol=1e-5)
            np.testing.assert_allclose(after['summary']['net_yen'],expected[-1],atol=1e-5)
            np.testing.assert_allclose(after['summary']['max_drawdown_yen'],max(peak-expected),atol=1e-5)
            np.testing.assert_allclose(sum(c['net_yen'] for c in cs),expected[-1],atol=1e-5)
            original_cycles = {c['cycle_id']:c for c in cycles}
            for c in cs:
                assert c['carried'] == (original_cycles[c['cycle_id']]['entry_time_s'] < boundary)
                if c['carried']:
                    carried_count += 1
                else:
                    fresh_count += 1
            for row in after['raw']:
                assert times[int(row[5])] >= boundary and times[int(row[6])] >= boundary
                matching = [r for r in result['raw'] if r[0]==row[0] and r[1]==row[1]
                            and r[6]==row[6] and r[9]==row[9]]
                assert len(matching)==1
                original = matching[0]
                wanted = ready['last'][first-1] if times[int(original[5])] < boundary else original[8]
                np.testing.assert_allclose(row[8],wanted,atol=1e-8)
            checks += 1
        records.append(dict(セッション=session,銘柄=symbol,条件=method,境界数=len(boundaries)))
    output = dict(成功=True,境界数=checks,継続サイクル延べ数=carried_count,
                  境界後新規サイクル延べ数=fresh_count,確認セル=records,API取得数=0,
                  注記='全行損益から境界直前資産を差し引き、返済利益だけでなく含み損益も一致。',
                  details_SHA256=hashlib.sha256((OUT/'details.py').read_bytes()).hexdigest())
    (OUT/'境界分割の独立監査.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(output,ensure_ascii=False))


if __name__ == '__main__':
    main()
