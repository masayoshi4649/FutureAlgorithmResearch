"""人工価格だけで固定帯エピソードの因果順・上下対称・数量を確認する。"""

import copy
import unittest
import numpy as np
import episode143 as e


def fixture(family=1):
    """
    機能: 固定帯と外抜け回復・支持再確認・端反発を持つ人工入力を作る。
    引数: family(int)は入口型1～3。
    返り値: tuple[dict,ndarray]は日経形式入力と公開済み9列履歴。
    """
    n = 140
    times = np.arange(n, dtype=float)*5.
    mid = np.full(n, 100.)
    if family == 1:
        mid[:5], mid[5:15], mid[15:30] = 98., 101., 105.
        mid[30:40], mid[40:50], mid[50:] = 112., 121., 110.
    elif family == 2:
        mid[:5], mid[5:10], mid[10:15], mid[15:30] = 122., 126., 123., 125.
        mid[30:40], mid[40:50], mid[50:] = 132., 142., 130.
    else:
        mid[:5], mid[5:15], mid[15:30] = 100., 103., 106.
        mid[30:40], mid[40:50], mid[50:] = 112., 121., 110.
    h = np.tile(np.array([120., 100., .1, 0., 0., 110., 110., 110., -60.]), (n, 1))
    h[:, 8] = np.floor(times/60.)*60.-60.
    data = dict(ready=dict(time_s=times, start=0., limit=times[-3], session='人工_Day', symbol='NK225', tick=.5, us_open=np.nan),
                quotes=dict(bid=mid-.25, ask=mid+.25, quote_valid=np.ones(n, dtype=bool)),
                features=np.zeros((n, 30)))
    return data, h


def config(family=1):
    """
    機能: 人工場の長さへ発注締切だけを合わせた入口設定を得る。
    引数: family(int)は入口型1～3。
    返り値: dictは金融比較設定を変えない複製。
    """
    return dict(e.configurations()[(family-1)*3+1], entry_cutoff=10.)


def mirrored(data, h):
    """
    機能: 中心200の上下鏡像入力を作る。
    引数: data(dict)、h(ndarray)は原入力。
    返り値: tuple[dict,ndarray]は鏡像入力。
    """
    d = copy.deepcopy(data)
    d['quotes']['bid'], d['quotes']['ask'] = 400.-data['quotes']['ask'], 400.-data['quotes']['bid']
    b = h.copy()
    b[:, 0], b[:, 1] = 400.-h[:, 1], 400.-h[:, 0]
    b[:, 3:5] *= -1.
    b[:, 5:8] = 400.-h[:, 5:8]
    return d, b


def audit(data, orders, maximum):
    """
    機能: 注文の次正常板約定・手数料・玉の出入りと上限を独立検算する。
    引数: data(dict)、orders(ndarray)、maximum(int)は入力と結果と枚数上限。
    返り値: floatは全完結後の費用後収支。
    """
    inventory = {}
    q = data['quotes']
    cash = 0.
    for row in orders:
        i, source, parent, side, quantity, price, reason, new, uid, fee = row
        i, source = int(i), int(source)
        assert i > source
        valid = q['quote_valid'] & np.isfinite(q['bid']) & np.isfinite(q['ask']) & (q['bid'] > 0.) & (q['ask'] > q['bid'])
        assert i == source+1+np.flatnonzero(valid[source+1:])[0]
        assert price == (q['ask'][i] if side > 0 else q['bid'][i])
        assert fee == quantity*385//10
        key = (parent, uid)
        inventory[key] = inventory.get(key, 0)+(quantity if new else -quantity)
        assert inventory[key] >= 0 and sum(inventory.values()) <= maximum
        cash += -side*quantity*price*100-fee
    assert sum(inventory.values()) == 0
    return cash


class EpisodeProperties(unittest.TestCase):
    """実市場の収益を計算せず、注文機構だけを確認する。"""

    def test_sixteen_configurations_and_small_band(self):
        """
        機能: 16条件の識別・追加対照・狭帯資格の差を人工価格で確認する。
        引数: self(EpisodeProperties)は検査状態。
        返り値: None。
        """
        configs = e.configurations()
        self.assertEqual([c['id'] for c in configs], [f'E{i:02d}' for i in range(1, 17)])
        for c in configs:
            data, h = fixture(c['family'])
            orders, _ = e.replay(data, h, dict(c, entry_cutoff=10.))
            audit(data, orders, c['maximum'])
        data, h = fixture()
        data['ready']['tick'] = 1.5
        data['quotes']['bid'][:5], data['quotes']['ask'][:5] = 95.75, 96.25
        data['quotes']['bid'][5:15], data['quotes']['ask'][5:15] = 102.75, 103.25
        old, _ = e.replay(data, h, dict(configs[1], entry_cutoff=10., confirmation=0.))
        narrow, _ = e.replay(data, h, dict(configs[12], entry_cutoff=10., confirmation=0.))
        self.assertEqual(len(old), 0)
        self.assertGreater(len(narrow), 0)
        audit(data, narrow, 5)

    def test_all_families_and_mirror(self):
        """
        機能: 3入口の発注と鏡像の約定・費用後収支を比較する。
        引数: self(EpisodeProperties)は検査状態。
        返り値: None。
        """
        for family in (1, 2, 3):
            data, h = fixture(family)
            orders, trace = e.replay(data, h, config(family))
            self.assertGreater(len(orders), 0)
            self.assertEqual(orders[0, 6], 1430+family)
            d, b = mirrored(data, h)
            reflected, reflected_trace = e.replay(d, b, config(family))
            np.testing.assert_array_equal(orders[:, [0, 1, 2, 4, 6, 7, 8, 9]], reflected[:, [0, 1, 2, 4, 6, 7, 8, 9]])
            np.testing.assert_allclose(orders[:, 3], -reflected[:, 3])
            np.testing.assert_allclose(orders[:, 5], 400.-reflected[:, 5])
            self.assertAlmostEqual(audit(data, orders, 5), audit(d, reflected, 5))
            self.assertEqual(trace.shape[1], len(e.TRACE_COLUMNS))

    def test_future_change_does_not_modify_prefix(self):
        """
        機能: 将来の価格と公開資料を変えても過去の発注・判断が変わらないことを確認する。
        引数: self(EpisodeProperties)は検査状態。
        返り値: None。
        """
        data, h = fixture()
        orders, trace = e.replay(data, h, config())
        d, b = copy.deepcopy(data), h.copy()
        d['quotes']['bid'][70:] += 30.
        d['quotes']['ask'][70:] += 30.
        b[70:, :2] += 30.
        changed, notes = e.replay(d, b, config())
        np.testing.assert_array_equal(orders[orders[:, 0] < 70], changed[changed[:, 0] < 70])
        np.testing.assert_array_equal(trace[trace[:, 0] < 70], notes[notes[:, 0] < 70])

    def test_same_band_does_not_repeat_after_loss(self):
        """
        機能: 損切り後に同じ帯へ戻るだけでは同方向を再発注しないことを確認する。
        引数: self(EpisodeProperties)は検査状態。
        返り値: None。
        """
        data, h = fixture()
        mid = np.full(len(h), 101.)
        mid[:5], mid[15:18], mid[30:35] = 98., 95., 98.
        data['quotes']['bid'], data['quotes']['ask'] = mid-.25, mid+.25
        orders, _ = e.replay(data, h, config())
        initial = orders[(orders[:, 7] == 1) & (orders[:, 8] == 0)]
        self.assertEqual(len(initial), 1)
        self.assertEqual(orders[-1, 6], 1436.)
        audit(data, orders, 5)

    def test_pending_executes_before_terminal_decision(self):
        """
        機能: 新規判断後に終端を跨いでも発注済み新規を約定し、その後に返済する。
        引数: self(EpisodeProperties)は検査状態。
        返り値: None。
        """
        data, h = fixture()
        reference, _ = e.replay(data, h, config())
        fill = int(reference[0, 0])
        data['ready']['limit'] = data['ready']['time_s'][fill]
        orders, _ = e.replay(data, h, dict(config(), entry_cutoff=0.))
        self.assertEqual(tuple(orders[0, :2]), tuple(reference[0, :2]))
        self.assertEqual(orders[1, 6], 93.)
        audit(data, orders, 5)

    def test_exit_fill_gap_is_not_a_new_episode(self):
        """
        機能: 損切り約定の不利なギャップを、同じ原行で新エピソードへ再利用しない。
        引数: self(EpisodeProperties)は検査状態。
        返り値: None。
        """
        data, h = fixture()
        mid = np.full(len(h), 101.)
        mid[:5], mid[15], mid[16], mid[30:35] = 98., 95., 94., 98.
        data['quotes']['bid'], data['quotes']['ask'] = mid-.25, mid+.25
        orders, _ = e.replay(data, h, config())
        self.assertEqual(len(orders[(orders[:, 7] == 1) & (orders[:, 8] == 0)]), 1)
        audit(data, orders, 5)

    def test_next_valid_and_maximum_two(self):
        """
        機能: 無効板を飛ばし、2枚枠へ変更しても返済と上限が整合することを確認する。
        引数: self(EpisodeProperties)は検査状態。
        返り値: None。
        """
        data, h = fixture()
        original, _ = e.replay(data, h, config())
        fill = int(original[0, 0])
        data['quotes']['quote_valid'][fill:fill+2] = False
        orders, _ = e.replay(data, h, dict(config(), maximum=2))
        self.assertEqual(orders[0, 0], fill+2)
        audit(data, orders, 2)


if __name__ == '__main__':
    unittest.main()
