"""復元条件の名前と実設定、枚数予算、鏡像を人工価格で独立検査する。"""

import unittest
import numpy as np
import common143 as shared
import audit143 as base
import audit143_round2 as audit


def fixture(risk=10.):
    """
    機能: 過去帯の反発後に進行し、最後は全返済できる人工入力を作る。
    引数: risk(float)は準備時の固定幅。
    返り値: dictは旧売買核の24列入力。
    """
    n = 2000
    times = np.arange(n, dtype=float)
    mid = np.full(n, 118.)
    mid[:20], mid[20:80], mid[80:200], mid[200:300] = 98., 102., 115., 130.
    features = np.zeros((n, 24))
    features[:, :9] = np.array([120., 100., .1, 0., 0., 110., 110., 100., 0.])
    features[:, 9], features[:, 10], features[:, 11] = risk, mid, risk*.5
    features[:, 12:14] = .1
    features[:, 16:22] = np.array([.1, 100., risk, 100., .1, .1])
    features[:, 22] = times-1.
    return dict(ready=dict(time_s=times, start=0., limit=float(n-3), us_open=np.nan,
        symbol='NK225', session='人工_Day', tick=.5, last=mid.copy()),
        quotes=dict(bid=mid-.25, ask=mid+.25, quote_valid=np.ones(n, dtype=bool)), features=features)


class RestorationTests(unittest.TestCase):
    """金融利益を測らず、復元の機構差と人工注文の整合性だけを確認する。"""

    def test_config_reuse_and_one_mechanism(self):
        """
        機能: 旧設定との同値と、一つの比較元から実キー一個だけ変えたことを確認する。
        引数: self(RestorationTests)。返り値: None。
        """
        original = shared.previous.first.original
        configs = base.read(base.HERE/'episode_restore_configs143.json')
        groups = audit.validate_configs(configs, original)
        self.assertEqual(len(groups), 18)
        lookup = {config['id']:config for config in configs}
        for config in configs:
            if config.get('compare_to'):
                before = dict(audit.signature(lookup[config['compare_to']], original))
                after = dict(audit.signature(config, original))
                self.assertEqual(sum(before[key] != after[key] for key in before), 1)

    def test_all_unique_artificial_configs(self):
        """
        機能: 全実設定の人工発注を次正常気配・費用・数量・鏡像で照合する。
        引数: self(RestorationTests)。返り値: None。
        """
        original = shared.previous.first.original
        configs = base.read(base.HERE/'episode_restore_configs143.json')
        data = fixture()
        reflected = audit.mirror24(data, 100., 100.)
        restored = audit.mirror24(reflected, 100., 100.)
        np.testing.assert_array_equal(data['features'], restored['features'])
        for group in audit.validate_configs(configs, original):
            config = group['parameters']
            orders, curve = original.replay(data, config)
            mirror, mc = original.replay(reflected, config)
            self.assertGreater(len(orders), 0, group['labels'])
            account = base.orders_account(orders, data, config['maximum'])
            ma = base.orders_account(mirror, reflected, config['maximum'])
            base.assert_mirror(orders, mirror, 100.)
            self.assertAlmostEqual(account['net'], ma['net'])
            self.assertAlmostEqual(account['net'], curve[-1])
            np.testing.assert_allclose(curve, mc, rtol=0, atol=1e-8)

    def test_initial_budget_changes_quantity(self):
        """
        機能: 上限2でも初回予算2設定と1設定を混同しないことを確認する。
        引数: self(RestorationTests)。返り値: None。
        """
        original = shared.previous.first.original
        configs = {c['id']:c for c in base.read(base.HERE/'episode_restore_configs143.json')}
        data = fixture(risk=30.)
        larger, _ = original.replay(data, configs['R05'])
        smaller, _ = original.replay(data, configs['R07'])
        self.assertGreater(len(larger), 0)
        self.assertEqual(larger[0, 4], 1.)
        self.assertEqual(len(smaller), 0)
        base.orders_account(larger, data, 2)
        base.orders_account(smaller, data, 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
