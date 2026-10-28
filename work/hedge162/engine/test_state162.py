"""金融資料を読まず、主/逆玉/予約の時系列連鎖を人工価格で検査する。"""
import unittest

from state162 import Config, Engine, Policy, Quote


def quote(index: int, mid: float, at: float | None = None, phase: str = "Day", normal: bool = True) -> Quote:
    """人工の10円spread板を作る。

    引数: index(int)、mid(float)、at(float|None)、phase(str)、normal(bool)。返り値: Quote。
    """
    return Quote(index,float(index) if at is None else at,mid-5,mid+5 if normal else mid-5,phase)


def step(engine: Engine, index: int, mid: float, long: bool = False, short: bool = False, at: float | None = None,
         phase: str = "Day", normal: bool = True, policy: Policy | None = None) -> None:
    """未確定の金融値と区別した人工幅を一原行へ渡す。

    引数: engine(Engine)、価格/信号/時計/人工Policy。返り値: None。
    """
    engine.step(quote(index,mid,at,phase,normal),long,short,policy or Policy(20,10,10))


class StateTests(unittest.TestCase):
    """片方向上限と親別所有、次板約定を検査する。"""

    def test_next_normal_same_clock_and_opposite_main_allowed(self):
        """不正板を飛ばし同時計の次原行で約定し、反対主も空きまで建てる。

        引数: self(StateTests)。返り値: None。
        """
        e = Engine(Config(1000,0,use_cover=False))
        step(e,0,1000,long=True,at=0)
        self.assertEqual(e.held(1),0)
        self.assertEqual(e.reserved(1),10)
        step(e,1,1000,at=0,normal=False)
        self.assertEqual(e.held(1),0)
        step(e,2,1000,at=0)
        self.assertEqual(e.held(1),10)
        self.assertEqual(e.events[0]["fill_index"],2)
        step(e,3,1000,short=True,at=60)
        self.assertEqual(e.reserved(-1),10)
        step(e,4,1000,at=61)
        self.assertEqual((e.held(1),e.held(-1)),(10,10))
        self.assertEqual(e.realized,0)
        self.assertEqual(e.minimum_equity,-20000)

    def test_cover_four_then_new_main_six_and_parent_ownership(self):
        """買主10/売カバー4から売主6を許し、元買親の退出で別親を返さない。

        引数: self(StateTests)。返り値: None。
        """
        e = Engine(Config(1000,0))
        wide = Policy(20,1000,1000)
        step(e,0,1000,long=True,policy=wide)
        step(e,1,1000,policy=wide)
        self.assertEqual(e.reserved(-1),0)
        step(e,2,920,policy=wide)
        self.assertEqual(e.reserved(-1),4)
        step(e,3,920,policy=wide)
        step(e,4,920,short=True,at=65,policy=wide)
        self.assertEqual(e.reserved(-1),6)
        self.assertEqual(e.free(-1),0)
        step(e,5,920,at=66,policy=wide)
        parents = list(e.parents.values())
        self.assertEqual(parents[1].quantity,6)
        self.assertEqual(len(parents[1].slots),6)
        step(e,6,1120,at=67,policy=wide)
        self.assertTrue(e.close_pending(e.lots[parents[0].main_lot]))
        self.assertFalse(e.close_pending(e.lots[parents[1].main_lot]))
        self.assertEqual(e.free(-1),0)
        step(e,7,1120,at=68,policy=wide)
        self.assertEqual(e.lots[parents[1].main_lot].quantity,6)
        self.assertEqual(e.held(-1),6)
        self.assertEqual(sum(l.quantity for l in e.lots.values() if l.parent == parents[0].id),0)

    def test_activated_cover_closes_after_profit_vanishes_both_directions(self):
        """起動後は利益消失でも返済し、profit-only比較だけ拒否する買売鏡像を確認する。

        引数: self(StateTests)。返り値: None。
        """
        for side in (1,-1):
            for positive_only in (False,True):
                e = Engine(Config(1000,0,main_wanted=1,profit_only_after_activation=positive_only))
                prices = [1000,1000,980,980,950,980,990]
                for index, mid in enumerate(prices):
                    p = mid if side == 1 else 2000-mid
                    step(e,index,p,long=index == 0 and side == 1,short=index == 0 and side == -1)
                covers = [l for l in e.lots.values() if l.role == "cover"]
                self.assertEqual(len(covers),1)
                self.assertTrue(covers[0].active)
                self.assertEqual(covers[0].quantity,1 if positive_only else 0)
                if not positive_only:
                    self.assertEqual(covers[0].realized,-2000)
                    self.assertEqual(e.events[-1]["order"].reason,"cover_trail")

    def test_positive_decision_can_fill_loss_and_rearm_needs_new_cross(self):
        """利益返済判断後の赤字約定を残し、同段は内側復帰と再逆行まで再発火しない。

        引数: self(StateTests)。返り値: None。
        """
        e = Engine(Config(1000,0,main_wanted=1))
        for index, mid in enumerate([1000,1000,980,980,950,960,990]):
            step(e,index,mid,long=index == 0)
        cover = next(l for l in e.lots.values() if l.role == "cover")
        self.assertEqual(cover.realized,-2000)
        self.assertEqual(e.reserved(-1),0)
        parent = next(iter(e.parents.values()))
        self.assertEqual(parent.slots[0].state,"wait_inside")
        step(e,7,1000)
        self.assertEqual(e.reserved(-1),0)
        self.assertEqual(parent.slots[0].state,"armed")
        step(e,8,980)
        self.assertEqual(e.reserved(-1),1)
        step(e,9,980)
        newer = [l for l in e.lots.values() if l.role == "cover"][-1]
        self.assertEqual(newer.best,0)
        self.assertFalse(newer.active)
        self.assertIsNone(newer.floor)

    def test_moving_rearm_seeds_only_after_close(self):
        """移動再配置は完済後の新原行でseedし、旧極値やfill行で再発火しない。

        引数: self(StateTests)。返り値: None。
        """
        e = Engine(Config(1000,0,main_wanted=1,rearm="moving_stop"))
        for index, mid in enumerate([1000,1000,980,980,950,960,990]):
            step(e,index,mid,long=index == 0)
        slot = next(iter(e.parents.values())).slots[0]
        self.assertEqual(slot.state,"seed")
        step(e,7,980)
        self.assertEqual(slot.threshold,960)
        self.assertEqual(e.reserved(-1),0)
        step(e,8,960)
        self.assertEqual(e.reserved(-1),1)

    def test_boundary_pending_survives_invalid_quote(self):
        """境界前発注を次正常板で約定後、別原行で全返済し、異常板で境界を失わない。

        引数: self(StateTests)。返り値: None。
        """
        e = Engine(Config(1000,0,boundary="flatten",use_cover=False))
        step(e,0,1000,long=True,phase="preUS")
        step(e,1,1000,phase="postUS",normal=False)
        step(e,2,1000,phase="postUS")
        self.assertEqual(e.held(1),10)
        self.assertEqual(len(e.pending),1)
        self.assertEqual(e.pending[0].reason,"phase_boundary")
        step(e,3,990,phase="postUS")
        self.assertEqual(e.held(1),0)
        self.assertEqual(e.realized,-20000)
        self.assertFalse(e.boundary_pending)

    def test_force_close_does_not_cancel_prior_market_new(self):
        """場末前の新規判断を未来時刻で消さず、次板成立後に返済する。

        引数: self(StateTests)。返り値: None。
        """
        e = Engine(Config(100,0,use_cover=False))
        step(e,0,1000,long=True,at=99)
        step(e,1,1000,at=100)
        self.assertEqual(e.held(1),10)
        self.assertEqual(e.pending[0].reason,"session_end")
        step(e,2,990,at=101)
        self.assertEqual(e.held(1)+e.held(-1),0)
        self.assertEqual(e.realized,-20000)

    def test_full_same_side_signal_consumed_not_deferred(self):
        """枠不足信号を後回しせず、新しいfalse→trueが来るまで主を増やさない。

        引数: self(StateTests)。返り値: None。
        """
        e = Engine(Config(1000,0,use_cover=False))
        step(e,0,1000,long=True)
        step(e,1,1000)
        step(e,2,1000,long=True,at=61)
        self.assertEqual(e.rejections[-1]["reason"],"capacity")
        step(e,3,1120,long=True,at=62)
        step(e,4,1120,long=True,at=63)
        self.assertEqual(e.held(1),0)
        self.assertEqual(e.reserved(1),0)
        self.assertEqual(len(e.parents),1)

    def test_untriggered_slots_no_reservation_and_unknown_policy_refused(self):
        """未発火段を上限へ算入せず、幅未知は恣意的補間しない。

        引数: self(StateTests)。返り値: None。
        """
        e = Engine(Config(1000,0))
        step(e,0,1000,long=True)
        step(e,1,1000)
        self.assertEqual(len(next(iter(e.parents.values())).slots),10)
        self.assertEqual(e.reserved(-1),0)
        self.assertEqual(e.free(-1),10)
        with self.assertRaises(ValueError):
            step(e,2,1000,policy=Policy(float("nan"),10,10))

    def test_mid_anchor_does_not_trigger_from_spread_alone(self):
        """主約定中値で段を固定し、広いspreadだけで逆行stopを発火しない。

        引数: self(StateTests)。返り値: None。
        """
        e = Engine(Config(1000,0))
        e.step(Quote(0,0,980,1020,"Day"),True,False,Policy(20,20,10))
        e.step(Quote(1,1,980,1020,"Day"),False,False,Policy(20,20,10))
        p = next(iter(e.parents.values()))
        self.assertEqual(p.entry,1020)
        self.assertEqual(p.grid_anchor,1000)
        self.assertEqual(e.reserved(-1),0)

    def test_interval_per_phase_but_quantity_shared(self):
        """米国前後の60秒周期は別に保ち、数量枠だけは同じ口座へ共有する。

        引数: self(StateTests)。返り値: None。
        """
        e = Engine(Config(1000,0,use_cover=False))
        step(e,0,1000,long=True,phase="preUS")
        step(e,1,1000,phase="preUS")
        step(e,2,1000,short=True,phase="postUS")
        self.assertEqual(e.reserved(-1),10)
        step(e,3,1000,phase="postUS")
        step(e,4,1000,long=True,phase="postUS")
        self.assertEqual(e.reserved(1),0)
        self.assertEqual((e.held(1),e.held(-1)),(10,10))

    def test_terminal_proxy_cancels_new_and_clears_owned_lots(self):
        """場末の最終既知板で全玉代理精算し、未発注段と未約定新規を混同しない。

        引数: self(StateTests)。返り値: None。
        """
        e = Engine(Config(1000,0,use_cover=False))
        step(e,0,1000,long=True,at=640)
        step(e,1,1000,at=641)
        step(e,2,1000,short=True,at=700)
        self.assertEqual(e.reserved(-1),10)
        result = e.finish(1000)
        self.assertTrue(result["completed"])
        self.assertEqual(result["age"],300)
        self.assertEqual(result["cancelled_new"],1)
        self.assertEqual(e.held(1)+e.held(-1),0)
        event = e.events[-1]
        self.assertEqual(event["order"].reason,"terminal_proxy")
        self.assertEqual(event["quote_time"],700)
        self.assertEqual(event["fill_time"],1000)
        self.assertIsNone(event["fill_index"])
        self.assertEqual(e.realized,-10000)

    def test_terminal_old_quote_leaves_unresolved(self):
        """6分を超えた板で勝手に全精算せず、残玉を未解消で残す。

        引数: self(StateTests)。返り値: None。
        """
        e = Engine(Config(1000,0,use_cover=False))
        step(e,0,1000,long=True)
        step(e,1,1000)
        result = e.finish(1000)
        self.assertFalse(result["completed"])
        self.assertEqual(e.held(1),10)

    def test_immediate_trail_uses_actual_negative_spread_peak(self):
        """即追尾の最高値を0へ捏造せず、実返済側の初期負値から追跡する。

        引数: self(StateTests)。返り値: None。
        """
        for side in (1,-1):
            e = Engine(Config(1000,0,main_wanted=1,immediate_cover_trail=True))
            for index,mid in enumerate([1000,1000,980,980,980]):
                step(e,index,mid if side == 1 else 2000-mid,long=index == 0 and side == 1,short=index == 0 and side == -1)
            cover = next(l for l in e.lots.values() if l.role == "cover")
            self.assertTrue(cover.active)
            self.assertEqual(cover.trail_peak,-10)
            self.assertEqual(cover.floor,-20)
            self.assertFalse(e.close_pending(cover))
            step(e,5,990 if side == 1 else 1010)
            self.assertTrue(e.close_pending(cover))
            step(e,6,1000)
            self.assertEqual(cover.realized,-3000)


if __name__ == "__main__":
    unittest.main()
