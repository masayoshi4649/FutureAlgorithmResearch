"""人工価格だけで所有・予約・次気配・全玉会計を独立照合する。金融資料を読まない。"""
from __future__ import annotations

from collections import defaultdict
import random
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
from state162 import Config, Engine, Policy, Quote


def replay_artificial(seed: int, mirror: bool = False) -> tuple[Engine, list[Quote]]:
    """疑似乱数の人工板で状態を進め、各行の口座を別の現金計算で確かめる。

    引数: seed(int)、mirror(bool)。返り値: tuple[Engine,list[Quote]]。
    """
    rng = random.Random(seed)
    engine = Engine(Config(900, 0, main_interval=5))
    policy = Policy(20, 40, 20)
    quotes = []
    mid, at = 2000., 0.
    cash, long_qty, short_qty = 0., 0, 0
    event_count, highest, lowest, drawdown = 0, 0., 0., 0.
    for index in range(501):
        at += rng.choice([0., 0., 1., 2., 5.])
        mid += rng.choice([-70., -30., -10., 0., 10., 30., 70.])
        mid = min(3400., max(600., mid))
        spread = rng.choice([10., 10., 20., 40.])
        normal = rng.randrange(12) != 0
        observation = normal and (not quotes or at > quotes[-1].time)
        side = rng.choice([-1, 0, 0, 0, 1])
        price = 4000.-mid if mirror else mid
        side = -side if mirror else side
        quote = Quote(index, at, price-spread/2, price+spread/2 if normal else price-spread/2,
                      "preUS" if at < 400 else "postUS", observation)
        quotes.append(quote)
        if normal:
            value = cash+(long_qty*quote.bid-short_qty*quote.ask)*100
            highest, lowest = max(highest, value), min(lowest, value)
            drawdown = max(drawdown, highest-value)
        engine.step(quote, side == 1, side == -1, policy)
        # ----------------------------------------
        # 約定列から現金と方向別実量だけを再構成し、内部の含み計算を使わない。
        for event in engine.events[event_count:]:
            order = event["order"]
            cash -= order.side*event["price"]*order.quantity*100
            if order.action == "new":
                if order.side == 1:
                    long_qty += order.quantity
                else:
                    short_qty += order.quantity
            elif order.side == -1:
                long_qty -= order.quantity
            else:
                short_qty -= order.quantity
            value = cash+(long_qty*quote.bid-short_qty*quote.ask)*100
            highest, lowest = max(highest, value), min(lowest, value)
            drawdown = max(drawdown, highest-value)
        event_count = len(engine.events)
        assert engine.held(1) == long_qty and engine.held(-1) == short_qty
        for direction in (-1, 1):
            pending_qty = sum(o.quantity for o in engine.pending if o.action == "new" and o.side == direction)
            assert engine.held(direction)+pending_qty <= 10
        if normal:
            value = cash+(long_qty*quote.bid-short_qty*quote.ask)*100
            assert abs(engine.last_mark["equity"]-value) < 1e-8
            assert abs(engine.minimum_equity-lowest) < 1e-8
            assert abs(engine.max_drawdown-drawdown) < 1e-8
    return engine, quotes


class IndependentStateTests(unittest.TestCase):
    """原資料を使わず、実装とは別の恒等式と原行探索を用いる。"""

    def test_cash_quantity_and_equity_extremes(self):
        """確定増加・含み悪化を含む全玉の現金恒等式と最悪時価を確認する。

        引数: self(IndependentStateTests)。返り値: None。
        """
        for seed in range(5):
            replay_artificial(seed)

    def test_mirror_prices_and_directions(self):
        """人工価格の上下と買売を鏡像化して収支と数量経路の対称性を確かめる。

        引数: self(IndependentStateTests)。返り値: None。
        """
        left, _ = replay_artificial(42)
        right, _ = replay_artificial(42, True)
        self.assertEqual(left.realized, right.realized)
        self.assertEqual(left.minimum_equity, right.minimum_equity)
        self.assertEqual(left.max_drawdown, right.max_drawdown)
        self.assertEqual(len(left.events), len(right.events))
        for a, b in zip(left.events, right.events):
            self.assertEqual(a["order"].side, -b["order"].side)
            self.assertEqual(a["order"].quantity, b["order"].quantity)
            self.assertEqual(a["fill_index"], b["fill_index"])
            self.assertEqual(a["price"]+b["price"], 4000.)
            self.assertEqual(a["gross"], b["gross"])

    def test_first_next_normal_and_no_double_fill(self):
        """各注文の次正常行を素朴探索し、架空の停止線約定や二重約定を検出する。

        引数: self(IndependentStateTests)。返り値: None。
        """
        engine, quotes = replay_artificial(77)
        used = set()
        for event in engine.events:
            order = event["order"]
            self.assertNotIn(order.id, used)
            used.add(order.id)
            next_quote = next(q for q in quotes if q.index > order.decision_index and q.valid)
            self.assertEqual(event["fill_index"], next_quote.index)
            self.assertEqual(event["price"], next_quote.ask if order.side == 1 else next_quote.bid)
            self.assertTrue(quotes[order.decision_index].valid)

    def test_lot_ownership_and_parent_cover_cap(self):
        """注文の親と返済対象を独立台帳で追い、他親転用とカバー上限超過を検出する。

        引数: self(IndependentStateTests)。返り値: None。
        """
        engine, _ = replay_artificial(8)
        owned, main_sizes, cover_qty = {}, {}, defaultdict(int)
        realized = 0.
        for event in engine.events:
            order = event["order"]
            if order.action == "new":
                owned[order.id] = [order.parent, order.side, order.quantity, event["price"], order.role]
                if order.role == "main":
                    self.assertNotIn(order.parent, main_sizes)
                    main_sizes[order.parent] = order.quantity
                else:
                    cover_qty[order.parent] += order.quantity
                    self.assertLessEqual(cover_qty[order.parent], main_sizes[order.parent])
            else:
                parent, side, quantity, entry, role = owned[order.target]
                self.assertEqual(order.parent, parent)
                self.assertEqual(order.side, -side)
                self.assertLessEqual(order.quantity, quantity)
                expected = side*(event["price"]-entry)*order.quantity*100
                self.assertEqual(event["gross"], expected)
                realized += expected
                owned[order.target][2] -= order.quantity
                if role == "cover":
                    cover_qty[parent] -= order.quantity
        self.assertEqual(engine.realized, realized)

    def test_incomplete_order_is_not_fabricated_fill(self):
        """次正常行のない新規予約を同じ原行で約定した扱いにしない。

        引数: self(IndependentStateTests)。返り値: None。
        """
        engine = Engine(Config(1000, 0))
        engine.step(Quote(0, 0, 990, 1000, "Day"), True, False, Policy(40, 20, 10))
        engine.step(Quote(1, 1, 1000, 1000, "Day", False), False, False, Policy(40, 20, 10))
        self.assertEqual(len(engine.events), 0)
        self.assertEqual(engine.held(1), 0)
        self.assertEqual(engine.reserved(1), 10)

    def test_immediate_trail_initial_peak_is_observed_negative_gain(self):
        """即追尾の初期ピークを未観測の0とせず、実際の負の返済気配から計算する。

        引数: self(IndependentStateTests)。返り値: None。
        """
        for side in (-1, 1):
            engine = Engine(Config(1000, 0, main_wanted=1, immediate_cover_trail=True))
            policy = Policy(20, 20, 10)
            for i, mid in enumerate([1000, 1000, 980, 980, 985, 990, 1000]):
                price = mid if side == 1 else 2000-mid
                quote = Quote(i, i, price-5, price+5, "Day")
                engine.step(quote, i == 0 and side == 1, i == 0 and side == -1, policy)
                if i == 3:
                    cover = next(lot for lot in engine.lots.values() if lot.role == "cover")
                    self.assertEqual(cover.trail_peak, -10)
                    self.assertEqual(cover.floor, -20)
                    self.assertFalse(engine.close_pending(cover))
                if i == 4:
                    self.assertFalse(engine.close_pending(cover))
                if i == 5:
                    self.assertTrue(engine.close_pending(cover))
            self.assertEqual(cover.realized, -3000)
            self.assertEqual(cover.quantity, 0)

    def test_main_grid_uses_fill_mid_not_entry_or_liquidation(self):
        """主玉の大きな初期気配差だけで逆行段へ触れないことを確認する。

        引数: self(IndependentStateTests)。返り値: None。
        """
        engine = Engine(Config(1000, 0, main_wanted=2))
        for index in range(3):
            engine.step(Quote(index, index, 970, 1030, "Day"), index == 0, False, Policy(20, 20, 10))
        parent = next(iter(engine.parents.values()))
        self.assertEqual(parent.entry, 1030)
        self.assertEqual(parent.grid_anchor, 1000)
        self.assertEqual([slot.threshold for slot in parent.slots], [980, 960])
        self.assertEqual(engine.reserved(-1), 0)
        self.assertEqual(engine.held(-1), 0)

    def test_terminal_proxy_age_and_existing_close_are_exact_once(self):
        """360秒の代理精算で既存返済を重複させず、360秒超の玉を消さない。

        引数: self(IndependentStateTests)。返り値: None。
        """
        for age in (359, 360, 361):
            engine = Engine(Config(1000, 0, use_cover=False))
            policy = Policy(20, 20, 10)
            engine.step(Quote(0, 0, 990, 1000, "Day"), True, False, policy)
            engine.step(Quote(1, 1, 990, 1000, "Day"), False, False, policy)
            engine.step(Quote(2, 2, 1100, 1110, "Day"), False, False, policy)
            self.assertEqual(len(engine.pending), 1)
            old_close = engine.pending[0].id
            engine.step(Quote(3, 3, 1110, 1110, "Day", False), False, False, policy)
            result = engine.finish(2+age)
            self.assertEqual(result["age"], age)
            self.assertEqual(result["completed"], age <= 360)
            if age <= 360:
                closes = [event for event in engine.events if event["order"].action == "close"]
                self.assertEqual(len(closes), 1)
                self.assertEqual(closes[0]["replaced_pending_close"], old_close)
                self.assertEqual(closes[0]["quote_index"], 2)
                self.assertIsNone(closes[0]["fill_index"])
                self.assertEqual(closes[0]["price"], 1100)
                self.assertEqual(engine.realized, 100000)
                self.assertEqual(engine.held(1), 0)
            else:
                self.assertEqual(engine.held(1), 10)
                self.assertEqual(engine.realized, 0)
                self.assertEqual(len(engine.pending), 1)

    def test_terminal_unfilled_new_is_cancelled_and_no_quote_rejected(self):
        """場末の未約定新規は取消し、正常板がなければ架空の精算を作らない。

        引数: self(IndependentStateTests)。返り値: None。
        """
        engine = Engine(Config(1000, 0))
        engine.step(Quote(0, 700, 990, 1000, "Day"), True, False, Policy(20, 20, 10))
        result = engine.finish(1000)
        self.assertTrue(result["completed"])
        self.assertEqual(result["cancelled_new"], 1)
        self.assertEqual(len(engine.events), 0)
        self.assertEqual(engine.realized, 0)
        self.assertEqual(len(engine.pending), 0)
        empty = Engine(Config(1000, 0))
        result = empty.finish(1000)
        self.assertFalse(result["completed"])
        self.assertEqual(len(empty.events), 0)
        with self.assertRaises(ValueError):
            engine.finish(1000)

    def test_all_configurations_optimized_and_full_rows_match(self):
        """26条件の人工結合で同値板省略版と全行版の注文・会計を比較する。

        引数: self(IndependentStateTests)。返り値: None。
        """
        from configs162 import configurations
        from replay162 import run_market
        from signals162 import EXPECTED

        rng = random.Random(162)
        times, bid, ask, valid, observations = [], [], [], [], []
        at, mid, previous_normal_clock = 0., 2000., None
        for index in range(700):
            at += rng.choice([0., 0., 0., 1., 2., 5.])
            mid += rng.choice([-40., -20., 0., 0., 0., 20., 40.])
            mid = max(600., min(3400., mid))
            normal = rng.randrange(20) != 0
            times.append(at)
            bid.append(mid-5)
            ask.append(mid+5 if normal else mid-5)
            valid.append(normal)
            if normal and at != previous_normal_clock:
                observations.append(index)
                previous_normal_clock = at
        ix = np.asarray(observations)
        t = np.asarray(times)
        market = {"time": t, "bid": np.asarray(bid), "ask": np.asarray(ask),
                  "last": (np.asarray(bid)+np.asarray(ask))/2, "line": np.arange(700)+1,
                  "valid": np.asarray(valid), "observations": ix}
        names = ["ret5_pt", "ret15_pt", "ret60_pt", "spread", "ofi5"]
        values = np.asarray([[20*s, 10*s, -60*s, 10, s] for s in (rng.choice([-1, 0, 0, 1]) for _ in ix)])
        features = {"decision_index": ix, "time": t[ix], "phase": np.zeros(len(ix), dtype=int),
                    "feature_names": np.asarray(names), "features": values}
        scene = {"session": "人工_Day", "kind": "Day", "split": "人工",
                 "start": 0, "end": float(t[-1]+300)}
        definitions = configurations()
        self.assertEqual(len(definitions), 26)
        self.assertEqual(len({d["id"] for d in definitions}), 26)
        quick = run_market(scene, market, features, {"selected": EXPECTED}, definitions, True)
        full = run_market(scene, market, features, {"selected": EXPECTED}, definitions, False)
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from aggregate162 import session_row
        self.assertFalse(quick["label_input_used"])
        for left, right in zip(quick["cases"], full["cases"]):
            row = session_row(scene, left)
            self.assertEqual(row["profit"]-row["loss"], row["net"])
            self.assertEqual(row["main_net"]+row["cover_net"], row["net"])
            self.assertEqual(row["net"], sum(event["gross"] for event in left["events"]))
            left.pop("skipped_unchanged_rows")
            right.pop("skipped_unchanged_rows")
            self.assertEqual(left, right)

    def test_locked_test_requires_matching_stage_and_frozen_selection(self):
        """後半の許可は固定3候補・正本指紋・未開封フラグが揃った場合だけ受理する。

        引数: self(IndependentStateTests)。返り値: None。
        """
        from replay162 import require_stage

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            paths = [base/name for name in ("manifest.json", "configs.json", "spec.json")]
            for path in paths:
                path.write_text("{}", encoding="utf-8")
            expected = {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in
                        zip(("manifest_sha256", "configs_sha256", "spec_sha256"), paths)}
            chosen = {**expected, "selected": ["H01", "H03", "H24"], "test_opened": False}
            freeze = base/"freeze.json"
            freeze.write_text(json.dumps(chosen), encoding="utf-8")
            receipt = {**expected, "allowed_stages": ["train_validation"],
                       "freeze_sha256": hashlib.sha256(freeze.read_bytes()).hexdigest()}
            with self.assertRaises(ValueError):
                require_stage(receipt, "locked_test", *paths, freeze)
            receipt["allowed_stages"].append("locked_test")
            require_stage(receipt, "locked_test", *paths, freeze)
            for extra in ({"test_opened": True}, {"selected": ["H01"]*2},
                          {"selected": ["H01", "H02", "H03", "H04"]}, {"selected": ["N00"]}):
                freeze.write_text(json.dumps({**chosen, **extra}), encoding="utf-8")
                receipt["freeze_sha256"] = hashlib.sha256(freeze.read_bytes()).hexdigest()
                with self.assertRaises(ValueError):
                    require_stage(receipt, "locked_test", *paths, freeze)
            freeze.write_text(json.dumps(chosen), encoding="utf-8")
            receipt["freeze_sha256"] = "0"*64
            with self.assertRaises(ValueError):
                require_stage(receipt, "locked_test", *paths, freeze)

    def test_learned_signals_do_not_refit_from_future_rows(self):
        """人工の固定ロジットで後続行だけを変えても過去の信号が変わらない。

        引数: self(IndependentStateTests)。返り値: None。
        """
        from signals162 import make_signals, EXPECTED
        from source161_rules import DIRECTIONAL, UNDIRECTED

        names = list(DIRECTIONAL)+list(UNDIRECTED)+["pos60", "bid_refill15", "ask_refill15"]
        width = len(DIRECTIONAL)+len(UNDIRECTED)+2
        values = np.ones((40, len(names)))
        values[:, names.index("spread")] = 10
        values[:, names.index("ret5_pt")] = np.where(np.arange(40)%3 == 0, 10, -10)
        config = {"preprocess": {"median": [0.]*width, "mean": [0.]*width, "std": [1.]*width},
                  "GL": {"kind": "GL", "coefficient": [0., .1]+[0.]*(2*width-1)}}
        frozen = {"selected": EXPECTED, "models": {"preUS": config, "postUS": config}}
        features = {"feature_names": np.asarray(names), "features": values,
                    "time": np.arange(40), "phase": np.where(np.arange(40) < 20, 1, 2)}
        before = make_signals(features, frozen)
        features["features"][30:, :] = np.nan
        after = make_signals(features, frozen)
        for side in (0, 1):
            np.testing.assert_array_equal(before[side][:30], after[side][:30])


if __name__ == "__main__":
    unittest.main(verbosity=2)
