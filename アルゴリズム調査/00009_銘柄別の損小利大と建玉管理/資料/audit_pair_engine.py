"""NTペアの整数丸め・損益分解・未来打切りを点検する。"""

from __future__ import annotations

import hashlib
import json

import numpy as np

import pair_engine as engine


def main() -> None:
    """機能: 手計算と既知原本の未来削除でペア再生の因果性を監査する。

    引数: なし。返り値: なし (None)。監査結果だけを新作業へ保存する。
    """
    configs = engine.build_catalog()
    sizes = 0
    for pn in (20000., 50000., 65000., 100000.):
        for pt in (2000., 4000., 6000.):
            for beta in (.5, 1., 1.5, 2.):
                for mode in range(6):
                    qn, qt, mn, mt, wanted = engine.quantities(mode, pn, pt, beta)
                    assert qn > 0 and qt > 0
                    assert qn*mn/1000+qt*mt/10000 <= 20+1e-10
                    if mode != 5:
                        assert int(qn) == qn and int(qt) == qt
                    if mode in (1, 2, 4):
                        cap = 200 if mode == 4 else 20
                        best = min((abs(wanted*a*mn*pn-b*mt*pt)/(wanted*a*mn*pn+b*mt*pt), a+b, a, b)
                                   for a in range(1, cap) for b in range(1, cap-a+1))
                        expected = abs(wanted*qn*mn*pn-qt*mt*pt)/(wanted*qn*mn*pn+qt*mt*pt)
                        assert np.isclose(expected, best[0], atol=1e-13)
                    sizes += 1
    dec = engine.decomposition(1, 1, 2, 1000, 10000, 65000, 4000, 65650, 4040)
    np.testing.assert_allclose([dec['net_yen'], dec['relative_yen'], dec['common_residual_yen']], [-150000., 0., -150000.], atol=1e-6)
    decomposition_count = 0
    for side in (-1, 1):
        for rn in (-.03, 0., .02):
            for rt in (-.02, .01, .04):
                for beta in (.5, 1., 1.5):
                    dec = engine.decomposition(side, 3, 5, 1000, 10000, 65000, 4000, 65000*(1+rn), 4000*(1+rt), beta)
                    np.testing.assert_allclose(dec['net_yen'], dec['relative_yen']+dec['common_residual_yen'], atol=1e-6)
                    np.testing.assert_allclose(dec['net_yen'], dec['beta_relative_yen']+dec['beta_rounding_yen'], atol=1e-6)
                    decomposition_count += 1
    prefixes, cells, legs_checked = [], 0, 0
    for session in ['2026-09-21_Day', '2026-09-24_Night']:
        full = engine.prepare_session(session)
        baseline = {cfg['id']: engine.run(full, cfg) for cfg in configs}
        for fraction in (.4, .7):
            clock_index = int(len(full['clocks'])*fraction)
            cut = full['clocks'][clock_index]+15.
            tapes = [{key: value[tape['time_s'] <= cut] for key, value in tape.items()} for tape in full['tapes']]
            prefix = engine.prepare_session(session, tapes=tapes)
            n = len(prefix['clocks'])
            np.testing.assert_allclose(full['prices'][:n], prefix['prices'], equal_nan=True)
            np.testing.assert_allclose(full['features'][:n], prefix['features'], equal_nan=True)
            cut_actual = min(t['time_s'][-1] for t in tapes)
            for cfg in configs:
                old = baseline[cfg['id']]
                new = engine.run(prefix, cfg)
                split = engine.split_at_boundary(old, full, full['clocks'][clock_index])
                np.testing.assert_allclose(sum(c['net_yen'] for c in split['cycles']), split['net_yen'], atol=1e-5)
                for cycle in split['cycles']:
                    np.testing.assert_allclose(cycle['net_yen'], cycle['relative_yen']+cycle['common_residual_yen'], atol=1e-5)
                for result in (old, new):
                    summary = result['summary']
                    np.testing.assert_allclose(sum(c['net_yen'] for c in result['cycles']), summary['net_yen'], atol=1e-6)
                    np.testing.assert_allclose(sum(c['net_yen'] for c in result['legs']), summary['net_yen'], atol=1e-6)
                    np.testing.assert_allclose(sum(c['closed_yen'] for c in result['cycles']), summary['closed_net_yen'], atol=1e-6)
                    np.testing.assert_allclose(sum(c['open_yen'] for c in result['cycles']), summary['open_yen'], atol=1e-6)
                    for leg in result['legs']:
                        assert leg['entry_time'] > leg['entry_order']
                        if leg['complete']:
                            assert leg['exit_time'] > leg['exit_order']
                        legs_checked += 1
                old_closed = [c for c in old['legs'] if c['complete'] and c['exit_time'] <= cut_actual]
                new_closed = [c for c in new['legs'] if c['complete'] and c['exit_time'] <= cut_actual]
                assert old_closed == new_closed
                old_curve = old['full_curve'][old['full_curve'][:, 0] <= cut_actual]
                new_curve = new['full_curve'][new['full_curve'][:, 0] <= cut_actual]
                np.testing.assert_allclose(old_curve, new_curve, atol=1e-6)
                cells += 1
            prefixes.append(dict(session=session, cut=float(cut), 比較数=len(configs), 特徴不変=True, 過去確定脚不変=True, 全行資産曲線不変=True))
    engine.json_write('NT_自己監査.json', dict(合格=True, 整数丸め組数=sizes, 分解恒等式組数=decomposition_count,
        共通方向だけの手計算='NK65000→65650とTOPIX4000→4040が同じ＋1%でも、NK１枚買い/TOPIX２枚売りは−150000円。相対要因０円・端数共通要因−150000円。',
        未来打切り比較数=cells, 境界時価控除比較数=cells, 脚会計確認数=legs_checked, 切断=prefixes,
        条件SHA256=hashlib.sha256((engine.WORK/'NT_固定条件.json').read_bytes()).hexdigest(),
        ソースSHA256=hashlib.sha256((engine.WORK/'pair_engine.py').read_bytes()).hexdigest(), 通信回数=0))
    print(json.dumps(dict(合格=True, 未来打切り比較数=cells, 脚会計確認数=legs_checked), ensure_ascii=False))


if __name__ == '__main__':
    main()
