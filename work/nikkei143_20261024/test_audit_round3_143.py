"""実現純益・残玉費用・最高進捗の独立監査へ人工反例を与える。"""

import unittest
import numpy as np
import audit143_round3 as audit


def fixture():
    """
    機能: 2枚新規、1枚返済、残玉返済の人工会計を作る。
    引数: なし。返り値: tuple[ndarray,ndarray,dict,dict]は注文・判断・気配・条件。
    """
    orders = np.array([[1,0,0,1,2,100.5,1,1,0,77],
        [4,3,0,-1,1,110.5,2,0,0,38], [10,9,0,-1,1,106.5,14380,0,0,38]], dtype=float)
    trace = np.array([[4,0,3,1,1,0,900.,885.,442.5,10.,10.,10.,0.]])
    bid, ask = np.full(12, 100.), np.full(12, 101.)
    bid[4], ask[4] = 110.5, 111.5
    return orders, trace, dict(quotes=dict(bid=bid, ask=ask)), dict(profit_fraction=.5)


class BudgetAuditTests(unittest.TestCase):
    """源の実装とは別の計算で、監査が意図した費用・実現額を判別する。"""

    def test_realized_budget(self):
        """
        機能: 新規料77円を残玉分も含め控除し、実現885円の半分を予算にする。
        引数: self(BudgetAuditTests)。返り値: None。
        """
        orders, trace, data, config = fixture()
        result = audit.audit_budget(orders, trace, data, config)
        self.assertEqual(result[0]['realized_net'], 885.)
        self.assertEqual(result[0]['parent_net'], 1447.)
        self.assertAlmostEqual(result[0]['risk_floor_price'], 96.455)

    def test_remaining_entry_fee_not_deducted_twice(self):
        """
        機能: 既払新規料を再度引く誤りを検出する。
        引数: self(BudgetAuditTests)。返り値: None。
        """
        orders, trace, data, config = fixture()
        trace[0,7] -= 38.5
        with self.assertRaises(AssertionError):
            audit.audit_budget(orders, trace, data, config)

    def test_unrealized_not_in_budget(self):
        """
        機能: 残玉の含み益を実現純益へ足した誤りを検出する。
        引数: self(BudgetAuditTests)。返り値: None。
        """
        orders, trace, data, config = fixture()
        trace[0,7] += 1000.
        trace[0,8] += 500.
        with self.assertRaises(AssertionError):
            audit.audit_budget(orders, trace, data, config)

    def test_prior_peak_not_carried(self):
        """
        機能: 残玉化より前の最高値を追尾へ流用する誤りを検出する。
        引数: self(BudgetAuditTests)。返り値: None。
        """
        orders, trace, data, config = fixture()
        trace[0,11] = 20.
        with self.assertRaises(AssertionError):
            audit.audit_budget(orders, trace, data, config)

    def test_budget_gap_is_not_hidden(self):
        """
        機能: 次行の飛び越えで予算床を下回った最終損益を保持する。
        引数: self(BudgetAuditTests)。返り値: None。
        """
        orders, trace, data, config = fixture()
        orders[-1,5] = 80.
        result = audit.audit_budget(orders, trace, data, config)
        self.assertEqual(result[0]['parent_net'], -1203.)
        self.assertTrue(result[0]['final_below_budget_line'])

    def test_budget_mirror(self):
        """
        機能: 売りへ反転しても実現純益と最終純益が一致する。
        引数: self(BudgetAuditTests)。返り値: None。
        """
        orders, trace, data, config = fixture()
        original = audit.audit_budget(orders, trace, data, config)[0]
        mirrored_orders = audit.base.mirror_orders(orders, 100.)
        mirrored_trace = trace.copy()
        mirrored_trace[:,3] *= -1
        mirrored_data = dict(quotes=dict(bid=200.-data['quotes']['ask'], ask=200.-data['quotes']['bid']))
        result = audit.audit_budget(mirrored_orders, mirrored_trace, mirrored_data, config)[0]
        self.assertEqual(original['realized_net'], result['realized_net'])
        self.assertEqual(original['parent_net'], result['parent_net'])
        self.assertAlmostEqual(original['risk_floor_price'], 200.-result['risk_floor_price'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
