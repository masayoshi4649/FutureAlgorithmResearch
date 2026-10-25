"""利益で支える残玉の因果性・費用・予約境界を人工価格だけで検査する。"""

import copy
import unittest
import numpy as np
import profit_residual143 as engine
from test_core_overlay143 import fixture, change, orders, mirror, check


def sample(n=120):
    """
    機能: 三枚新規後に十分な利益を得る人工価格と元全返済通知を作る。
    引数: n(int)は原行数。
    返り値: tuple[dict,ndarray,ndarray]は入力・公開履歴・十列元注文。
    """
    data, history = fixture(n)
    data['ready']['limit'] = 100.
    change(data, 10, n, 110.)
    baseline = native(data, [(0, 1, 1, 3, 1, 11), (30, 1, -1, 3, 0, 11)])
    return data, history, baseline


def native(data, events, reasons=None):
    """
    機能: 全返済を利益追尾理由にした元の人工約定通知を作る。
    引数: data(dict)、events(list[tuple])、reasons(list[int]|None)は入力・通知・理由上書き。
    返り値: ndarrayは次正常気配で作った元十列約定。
    """
    result = orders(data, events)
    result[result[:, 7] == 0, 6] = 70
    if reasons is not None:
        result[:, 6] = reasons
    return result


def crop(data, length):
    """
    機能: 未来部分だけを切り捨て、既存原行の入力値を保つ。
    引数: data(dict)、length(int)は人工入力と残す原行数。
    返り値: dictは途中までの入力。元の場末時刻は変更しない。
    """
    result = copy.deepcopy(data)
    for section in ('ready', 'quotes'):
        for key, value in result[section].items():
            if isinstance(value, np.ndarray):
                result[section][key] = value[:length].copy()
    result.pop('features', None)
    return result


class ResidualProperties(unittest.TestCase):
    """実相場の成績を使わず、残玉の機械的な計算仕様を検査する。"""

    def test_reference_and_funded_budget(self):
        """
        機能: 無変更同値と、全新規費用を払った実現利益予算を確認する。
        引数: self(ResidualProperties)は試験状態。
        返り値: None。
        """
        data, _, base = sample()
        unchanged, log = engine.replay(data, base, engine.configurations()[0])
        np.testing.assert_array_equal(unchanged, base)
        self.assertEqual(log.shape, (0, 13))
        for cfg in engine.configurations()[1:]:
            actual, trace = engine.replay(data, base, cfg)
            check(data, actual)
            self.assertEqual(actual[:, 4].tolist(), [3, 2, 1])
            self.assertEqual(actual[:, 0].tolist(), [1, 31, 101])
            budget = trace[trace[:, 2] == 3][0]
            # 新規三枚115円、他玉二枚の利益1800円、返済77円。
            self.assertEqual(budget[7], 1608.)
            self.assertEqual(budget[8], 1608. * cfg['profit_fraction'])
            self.assertEqual(actual[:, 9].tolist(), [115, 77, 38])
            self.assertEqual(actual[-1, 6], 93.)

    def test_previous_partial_profit_can_fund_last_one(self):
        """
        機能: 部分利確後の最後一枚は既確定利益で残し、新たな同原行約定を作らない。
        引数: self(ResidualProperties)は試験状態。
        返り値: None。
        """
        data, _, _ = sample()
        base = native(data, [(0, 1, 1, 3, 1, 11), (20, 1, -1, 2, 0, 11),
                             (30, 1, -1, 1, 0, 11)], [81, 7, 70])
        actual, trace = engine.replay(data, base, engine.configurations()[1])
        check(data, actual)
        self.assertEqual(actual[:, 0].tolist(), [1, 21, 101])
        self.assertEqual(trace[trace[:, 2] == 2, 0].tolist(), [30])
        budget = trace[trace[:, 2] == 3][0]
        self.assertEqual(budget[0], 30.)
        self.assertEqual(budget[7], 1608.)
        self.assertEqual(budget[8], 804.)

    def test_initial_one_without_realized_profit_is_ineligible(self):
        """
        機能: 一枚だけの含み益を他玉の確定利益と取り違えない。
        引数: self(ResidualProperties)は試験状態。
        返り値: None。
        """
        data, _, _ = sample()
        base = native(data, [(0, 1, 1, 1, 1, 11), (30, 1, -1, 1, 0, 11)])
        actual, trace = engine.replay(data, base, engine.configurations()[1])
        np.testing.assert_array_equal(actual, base)
        self.assertEqual(sum(trace[:, 2] == 2), 0)
        check(data, actual)

    def test_parent_profit_does_not_substitute_for_other_profit(self):
        """
        機能: 親全体黒字でも、最古利益玉を除いた他玉が赤字なら残さない。
        引数: self(ResidualProperties)は試験状態。
        返り値: None。
        """
        data, _ = fixture()
        data['ready']['limit'] = 100.
        change(data, 5, 20, 109.)
        change(data, 20, 120, 108.)
        base = native(data, [(0, 1, 1, 2, 1, 11), (5, 1, 1, 1, 1, 12),
                             (7, 1, 1, 1, 1, 13), (9, 1, 1, 1, 1, 14),
                             (30, 1, -1, 2, 0, 11), (30, 1, -1, 1, 0, 12),
                             (30, 1, -1, 1, 0, 13), (30, 1, -1, 1, 0, 14)])
        actual, trace = engine.replay(data, base, engine.configurations()[1])
        np.testing.assert_array_equal(actual, base)
        self.assertEqual(sum(trace[:, 2] == 2), 0)
        check(data, actual)

    def test_issued_other_closes_fill_before_gap_failure_close(self):
        """
        機能: 他玉の次気配悪化で予算が負になったら、返済を消さず残玉をさらに次行で閉じる。
        引数: self(ResidualProperties)は試験状態。
        返り値: None。
        """
        data, _, _ = sample()
        change(data, 31, 120, 99.)
        base = native(data, [(0, 1, 1, 3, 1, 11), (30, 1, -1, 3, 0, 11)])
        actual, trace = engine.replay(data, base, engine.configurations()[1])
        self.assertEqual(actual[:, 0].tolist(), [1, 31, 32])
        self.assertEqual(actual[:, 4].tolist(), [3, 2, 1])
        self.assertEqual(actual[-1, 6], 14382.)
        budget = trace[trace[:, 2] == 3][0]
        self.assertEqual(budget[7], -592.)
        self.assertEqual(budget[8], 0.)
        check(data, actual)

    def test_stop_quiet_structural_and_partial_are_not_eligible(self):
        """
        機能: 損切り・静観・場末・支持破綻と部分利確を残玉化の契機にしない。
        引数: self(ResidualProperties)は試験状態。
        返り値: None。
        """
        data, _, base = sample()
        for reason in (7, 32, 72, 93, 94, 1435, 1436, 14312, 14317):
            changed = base.copy()
            changed[-1, 6] = reason
            actual, trace = engine.replay(data, changed, engine.configurations()[1])
            np.testing.assert_array_equal(actual, changed)
            self.assertEqual(sum(trace[:, 2] == 2), 0)
        for reason in (2, 70, 1437):
            changed = base.copy()
            changed[-1, 6] = reason
            actual, trace = engine.replay(data, changed, engine.configurations()[1])
            self.assertEqual(sum(trace[:, 2] == 2), 1)
            check(data, actual)

    def test_later_parent_is_rejected_at_first_notice(self):
        """
        機能: 残玉保有中の後続親全体を拒否し、残玉解消後の新しい親は採用できる。
        引数: self(ResidualProperties)は試験状態。
        返り値: None。
        """
        data, _, _ = sample(160)
        base = native(data, [(0, 1, 1, 3, 1, 11), (30, 1, -1, 3, 0, 11),
                             (40, 2, -1, 2, 1, 21), (45, 2, -1, 1, 1, 22),
                             (60, 2, 1, 2, 0, 21), (60, 2, 1, 1, 0, 22),
                             (102, 3, 1, 2, 1, 31), (110, 3, -1, 2, 0, 31)])
        actual, trace = engine.replay(data, base, engine.configurations()[1])
        self.assertEqual(sorted(set(actual[:, 2])), [1., 3.])
        rejection = trace[trace[:, 5] == 14384]
        self.assertEqual(rejection[:, 0].tolist(), [40.])
        self.assertEqual(rejection[:, 1].tolist(), [2.])
        check(data, actual)

    def test_quiet_and_terminal_do_not_cancel_native_reservations(self):
        """
        機能: 静観・場末時刻が来ても既発注の他玉返済を先に約定し、残玉を次行で閉じる。
        引数: self(ResidualProperties)は試験状態。
        返り値: None。
        """
        data, _, base = sample()
        data['ready']['us_open'] = 80.
        cfg = dict(engine.configurations()[1], quiet_seconds=10.)
        actual, trace = engine.replay(data, base, cfg)
        self.assertEqual(actual[-1, 0], 71.)
        self.assertEqual(actual[-1, 6], 94.)
        check(data, actual)
        data.pop('features')
        data['ready'].pop('us_open')
        base = native(data, [(0, 1, 1, 3, 1, 11), (99, 1, -1, 3, 0, 11)])
        actual, trace = engine.replay(data, base, cfg)
        self.assertEqual(actual[:, 0].tolist(), [1., 100., 101.])
        self.assertEqual(actual[-1, 6], 93.)
        check(data, actual)

    def test_gap_invalid_quotes_and_no_same_row_repayment(self):
        """
        機能: 無効板を約定に使わず、他玉返済から残玉返済まで別の正常原行を待つ。
        引数: self(ResidualProperties)は試験状態。
        返り値: None。
        """
        data, _, _ = sample()
        data['quotes']['quote_valid'][31:34] = False
        data['quotes']['quote_valid'][35:38] = False
        change(data, 31, 120, 99.)
        base = native(data, [(0, 1, 1, 3, 1, 11), (30, 1, -1, 3, 0, 11)])
        actual, trace = engine.replay(data, base, engine.configurations()[1])
        self.assertEqual(actual[:, 0].tolist(), [1., 34., 38.])
        self.assertEqual(actual[-1, 1], 34.)
        check(data, actual)

    def test_trailing_peak_restarts_and_fixed_r_does_not_move(self):
        """
        機能: 利確前の最高値を後付けせず、初回公開Rで残玉化後の最高値を追う。
        引数: self(ResidualProperties)は試験状態。
        返り値: None。
        """
        data, _, _ = sample()
        change(data, 15, 25, 140.)
        change(data, 40, 60, 130.)
        change(data, 60, 120, 109.)
        data['ready']['atr'][20:] = 1000.
        base = native(data, [(0, 1, 1, 3, 1, 11), (30, 1, -1, 3, 0, 11)])
        actual, trace = engine.replay(data, base, engine.configurations()[1])
        self.assertEqual(trace[trace[:, 2] == 3][0, 11], 9.)
        self.assertEqual(actual[-1, 1], 60.)
        self.assertEqual(actual[-1, 6], 14380.)
        self.assertEqual(trace[trace[:, 2] == 4][0, 9], 10.)
        check(data, actual)

    def test_budget_floor_reserves_exit_fee_and_gap_is_not_clipped(self):
        """
        機能: 残玉返済費用込みの損失床で判断し、次板の飛び越え損失をそのまま記録する。
        引数: self(ResidualProperties)は試験状態。
        返り値: None。
        """
        data, _, _ = sample()
        change(data, 50, 51, 93.)
        change(data, 51, 120, 90.)
        base = native(data, [(0, 1, 1, 3, 1, 11), (30, 1, -1, 3, 0, 11)])
        actual, trace = engine.replay(data, base, engine.configurations()[1])
        self.assertEqual(actual[-1, 1], 50.)
        self.assertEqual(actual[-1, 0], 51.)
        self.assertEqual(actual[-1, 5], 89.5)
        self.assertEqual(actual[-1, 6], 14381.)
        self.assertLess((89.5 - 100.5) * 100 - 38, -804.)
        check(data, actual)

    def test_oldest_profitable_ticket_is_retained(self):
        """
        機能: UID番号でなく実新規順の最古利益玉一枚だけを残す。
        引数: self(ResidualProperties)は試験状態。
        返り値: None。
        """
        data, _, _ = sample()
        change(data, 5, 10, 104.)
        base = native(data, [(0, 1, 1, 2, 1, 99), (5, 1, 1, 2, 1, 1),
                             (30, 1, -1, 2, 0, 99), (30, 1, -1, 2, 0, 1)])
        actual, trace = engine.replay(data, base, engine.configurations()[1])
        self.assertEqual(actual[-1, 8], 99.)
        self.assertEqual(actual[actual[:, 0] == 31, 4].tolist(), [1., 2.])
        check(data, actual)

    def test_all_policies_prefix_future_and_mirror(self):
        """
        機能: 全条件の上下対称・未来変更不変・途中打切り不変・元将来通知非参照を確認する。
        引数: self(ResidualProperties)は試験状態。
        返り値: None。
        """
        data, history, base = sample()
        mirrored, _, mb = mirror(data, history, base)
        future = copy.deepcopy(data)
        change(future, 60, 120, 90.)
        fb = base.copy()
        for k, row in enumerate(fb):
            fill = int(row[0])
            fb[k, 5] = future['quotes']['ask' if row[3] > 0 else 'bid'][fill]
        for cfg in engine.configurations():
            actual, trace = engine.replay(data, base, cfg)
            mo, mt = engine.replay(mirrored, mb, cfg)
            expected = actual.copy()
            expected[:, 3] *= -1.
            expected[:, 5] = 200. - expected[:, 5]
            np.testing.assert_allclose(mo, expected)
            expected_trace = trace.copy()
            expected_trace[:, 3] *= -1.
            np.testing.assert_allclose(mt, expected_trace)
            for length in (15, 30, 31, 32, 60, 101):
                part, pt = engine.replay(crop(data, length), base, cfg)
                np.testing.assert_allclose(part, actual[actual[:, 0] < length])
                np.testing.assert_allclose(pt, trace[trace[:, 0] < length])
            fo, ft = engine.replay(future, fb, cfg)
            np.testing.assert_allclose(fo[fo[:, 0] < 60], actual[actual[:, 0] < 60])
            np.testing.assert_allclose(ft[ft[:, 0] < 60], trace[trace[:, 0] < 60])
            check(data, actual)


if __name__ == '__main__':
    unittest.main()
