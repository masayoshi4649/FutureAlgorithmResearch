"""図用の別式計算を人工相場だけで確認し、新実相場の図再生前に証跡を保存する。"""

from copy import deepcopy
import json
from pathlib import Path

import numpy as np

import conditional_engine_audit as cases
import chart_data_audit as independent
import chart_report as chart


def main() -> None:
    """機能: 合成注文器結果を図の別式と照合し、欠測・部分・反射・根拠源を検査する。

    引数: なし。返り値: なし (None)。保存された実相場損益は読まない。
    """
    chart.wave_order_audit.deny_network()
    fixtures = [
        cases.base.fixture([100., 101., 110., 120., 107.]),
        cases.base.fixture([100., 101., 120., 110., 110.], tracking=[4., 4., 4., 2., 2.]),
        cases.base.fixture([100., 101., 110., 110., 110., 109.], tracking=[4., 4., 4., 2., 20., 20.]),
        cases.base.fixture([100., 101., 106., 106., 107., 107.], tracking=[4., 4., 2., 2., 2., 2.]),
        cases.base.fixture([100., 101., 102., 103., 104., 105., 106., 107.],
                           tracking=[np.nan, np.nan, 3., np.nan, np.inf, -1., 0., .5]),
        cases.base.fixture([100., 101., 110., np.nan, 110., 100.], tracking=[4., 4., 4., 2., np.nan, 20.])]
    count = 0
    for ready, state, cfg, atr in fixtures:
        for reflect in (False, True):
            r = deepcopy(ready); s = state.copy()
            if reflect:
                r['last'] = 20000. - r['last']; s = -s
            # 初期A0列を同じままにし、追跡Atだけを図用独立式へ入力する。
            independent_ready = deepcopy(r); independent_ready['atr'] = atr
            bad = -s; bad[::3] = 0; source = cases.source_rows(bad)
            source[bad != 0] = np.maximum(0, source[bad != 0] - 1)
            for mode in (0, 1, 2):
                for observed in (False, True):
                    result = chart.runner.engine.run(r, s, cfg, True, width_mode=mode, observed_fill=observed,
                        trail_atr=atr, deterioration=bad, deterioration_source=source)
                    ledger = {'trades': result['trades'].tolist(), 'cycles': result['cycles'].tolist(), 'config': cfg}
                    with np.errstate(invalid='ignore'):
                        lines, events = independent.independent_lines(independent_ready, ledger, mode, bad, source)
                    expected_events = np.column_stack((r['time_s'][result['trail_events'][:, 0].astype(int)], result['trail_events']))
                    np.testing.assert_allclose(np.array(events, dtype=float).reshape(-1, 16), expected_events,
                                               atol=1e-7, rtol=0, equal_nan=True)
                    a = {name: i for i, name in enumerate(chart.runner.engine.ATR_COLUMNS)}
                    c = {name: i for i, name in enumerate(chart.runner.engine.CONDITIONAL_COLUMNS)}
                    for line in lines.values():
                        begin, end = line['begin'], line['end']; n = end - begin
                        expected = np.column_stack((np.full(n, line['A0']), line['At'], line['used_atr'],
                                                    line['stop'], line['trail']))
                        expected[~np.isfinite(expected)] = np.nan
                        np.testing.assert_allclose(result['atr_curve'][begin:end][:, [a[name] for name in
                            ('initial_atr', 'current_atr', 'used_width_atr', 'stop_level', 'trail_level')]],
                            expected, atol=1e-7, rtol=0, equal_nan=True)
                        np.testing.assert_allclose(result['conditional_curve'][begin:end, c['fixed_candidate']],
                                                   line['fixed_candidate'], atol=1e-7, rtol=0, equal_nan=True)
                        np.testing.assert_array_equal(result['conditional_curve'][begin:end, c['line_evidence_source_row']],
                                                       line['evidence_source_row'])
                    samples = chart.trace_samples(r, result)
                    for sample in samples:
                        _, row, campaign, direction = sample[:4]
                        if not direction:
                            continue
                        line = lines[campaign]; offset = row - line['begin']
                        expected = [line['A0'], line['At'][offset], line['used_atr'][offset], line['stop'][offset],
                            line['trail'][offset], line['fixed_candidate'][offset], line['bad_direction'][offset],
                            line['evidence_source_row'][offset]]
                        expected = [v if np.isfinite(v) else np.nan for v in expected]
                        np.testing.assert_allclose(np.array(sample[4:], dtype=float), expected, atol=1e-7, rtol=0, equal_nan=True)
                    count += 1
    result = {'全合格': True, '合成別式比較数': count, '全進行イベント一致': True, '図標本一致': True,
        '売買左右反射': True, '欠測と部分利確': True, '現在保存物使用': False, '新実相場再生': False,
        'API取得数': 0, '図固定SHA256': chart.runner.digest(chart.HERE / 'chart_fixed.json'),
        '検査実装SHA256': chart.runner.digest(Path(__file__))}
    (chart.HERE / 'chart_line_synthetic_audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('図用の独立式を人工', count, '条件で確認。新実相場再生なし。')


if __name__ == '__main__':
    main()
