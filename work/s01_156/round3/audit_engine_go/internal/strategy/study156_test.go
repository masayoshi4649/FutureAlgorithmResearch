package strategy

import (
	"testing"
)

// studyTest156 はAPIに接続しない研究用S01を生成します。
//
// 引数: t(*testing.T)、width/activation(float64)、gate(bool)、entry(int)。返り値: *Portfolio。
func studyTest156(t *testing.T, width, activation float64, gate bool, entry int) *Portfolio {
	t.Helper()
	par, err := ParametersForMethod("NK225", "Day", "S01")
	if err != nil {
		t.Fatal(err)
	}
	p, err := New(Config{Reference: "NK225", Product: "NK225mini", CoreQuantity: 5, ExtraMaxQuantity: 5, Cap: 10, LargeTick: 10, PointValue: 100, Parameters: par}, Session{ID: "人工", Kind: "Day", Start: 0, ForceClose: 9000, End: 10000})
	if err != nil {
		t.Fatal(err)
	}
	if err = p.Configure156(width, activation, gate, entry); err != nil {
		t.Fatal(err)
	}
	return p
}

// obs156 は指定中値の人工正常板を作ります。
//
// 引数: index(int64)、at/mid(float64)。返り値: Observation。
func obs156(index int64, at, mid float64) Observation {
	return Observation{Reference: "NK225", Index: index, Time: at, Received: at, Last: mid, Bid: mid - 5, Ask: mid + 5, ATR: 80, QuoteOK: true}
}

// hold156 は所有玉を通常の新規予約・実約定経路で作ります。
//
// 引数: t(*testing.T)、p(*Portfolio)、owner(string)、side/quantity(int)。返り値: *ResearchSleeve。
func hold156(t *testing.T, p *Portfolio, owner string, side, quantity int) *ResearchSleeve {
	t.Helper()
	s := p.sleeve(owner)
	out := p.nativeResearch(s, obs156(0, 1, 1000), []ResearchEvent{{Action: "new", Side: side, Quantity: quantity, Campaign: 0, Ticket: 0, Risk: 80}}, true, true)
	if len(out) != 1 {
		t.Fatal(out)
	}
	f := Fill{SignalID: out[0].ID, ExecutionID: "初約定", HoldID: "玉A", Quantity: quantity, Price: 1000, Time: 2}
	if err := p.OnFill(f); err != nil {
		t.Fatal(err)
	}
	if err := p.OnOrderDone(out[0].ID); err != nil {
		t.Fatal(err)
	}
	return s
}

// Test156LotFloorSymmetric は全担当・買売で玉別建値床と最高値追尾を確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test156LotFloorSymmetric(t *testing.T) {
	for _, owner := range []string{"core", "addon", "episode"} {
		for _, side := range []int{-1, 1} {
			p := studyTest156(t, 20, 0, false, 0)
			s := hold156(t, p, owner, side, 2)
			o := obs156(1, 3, 1000+float64(side)*15)
			p.updateLot156(s, o)
			g := p.Study156.Lots["玉A"]
			if !g.Active || g.FloorPrice != 1000 {
				t.Fatal(owner, side, g)
			}
			o = obs156(2, 4, 1000+float64(side)*55)
			p.updateLot156(s, o)
			if g.FloorPrice != 1000+float64(side)*30 {
				t.Fatal(g)
			}
			o = obs156(3, 5, 1000+float64(side)*25)
			p.updateLot156(s, o)
			p.applyLot156(s, o, true)
			if s.Goals["玉A"].Remaining != 0 || s.Goals["玉A"].Reason != 15601 || !closing156(s) {
				t.Fatal(s.Goals)
			}
		}
	}
}

// Test156ActivationAndUnknown は0超と20pt起動の境界・異常板を区別します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test156ActivationAndUnknown(t *testing.T) {
	for _, threshold := range []float64{0, 20} {
		p := studyTest156(t, 40, threshold, false, 0)
		s := hold156(t, p, "addon", 1, 2)
		p.updateLot156(s, obs156(1, 3, 1005))
		if p.Study156.Lots["玉A"].Active {
			t.Fatal("0利益で起動")
		}
		o := obs156(2, 4, 1030)
		o.QuoteOK = false
		p.updateLot156(s, o)
		if p.Study156.Lots["玉A"].Active {
			t.Fatal("異常気配起動")
		}
		p.updateLot156(s, obs156(3, 5, 1024))
		if p.Study156.Lots["玉A"].Active != (threshold == 0) {
			t.Fatal("20未満起動の差")
		}
		p.updateLot156(s, obs156(4, 6, 1025))
		if !p.Study156.Lots["玉A"].Active {
			t.Fatal("境界起動漏れ")
		}
	}
}

// Test156PartialOriginalPriority は元部分利確の理由を維持し、残数へ同じ床を再適用します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test156PartialOriginalPriority(t *testing.T) {
	p := studyTest156(t, 20, 0, false, 0)
	s := hold156(t, p, "addon", 1, 2)
	p.updateLot156(s, obs156(1, 3, 1055))
	s.setGoal("玉A", 1, 14510)
	o := obs156(2, 4, 1025)
	p.applyLot156(s, o, true)
	if s.Goals["玉A"].Reason != 14510 || s.Goals["玉A"].Remaining != 1 {
		t.Fatal("元部分返済を上書き")
	}
	signals := p.flushResearchGoals(s, o)
	if len(signals) != 1 {
		t.Fatal(signals)
	}
	if err := p.OnFill(Fill{SignalID: signals[0].ID, ExecutionID: "部分利益", Quantity: 1, Price: 1020, Time: 5, Closed: signals[0].Targets}); err != nil {
		t.Fatal(err)
	}
	p.OnOrderDone(signals[0].ID)
	s.Budget = 100000 // 旧親に大きな利益予算があっても玉別床を下げない。
	p.applyLot156(s, obs156(3, 6, 1025), true)
	if s.Goals["玉A"].Remaining != 0 || p.Study156.Lots["玉A"].FloorPrice != 1030 || s.Cash != 2000 {
		t.Fatal(s.Goals, p.Study156.Lots["玉A"], s.Cash)
	}
}

// Test156NewLotAndStale は追加玉の床が独立し、古い観測から新規返済目標を作らないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test156NewLotAndStale(t *testing.T) {
	p := studyTest156(t, 20, 0, false, 0)
	s := hold156(t, p, "addon", 1, 2)
	p.updateLot156(s, obs156(1, 3, 1055))
	s.Lots = append(s.Lots, ResearchLot{ID: "追加玉", Quantity: 1, Price: 1050, At: 3, EntryID: "追加", Ticket: 1})
	o := obs156(2, 4, 1045)
	p.updateLot156(s, o)
	p.applyLot156(s, o, false)
	if len(s.Goals) > 0 || p.Study156.Lots["追加玉"].Active || p.Study156.Lots["玉A"].FloorPrice != 1030 {
		t.Fatal(s.Goals)
	}
	o = obs156(3, 5, 1025)
	p.updateLot156(s, o)
	p.applyLot156(s, o, true)
	if s.Goals["玉A"].Remaining != 0 {
		t.Fatal(s.Goals)
	}
	if _, ok := s.Goals["追加玉"]; ok {
		t.Fatal("未保護追加玉への架空床")
	}
}

// Test156ReferenceGate は担当別の旧親予約・同親・完済・拒否固定を確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test156ReferenceGate(t *testing.T) {
	p := studyTest156(t, 20, 0, true, 0)
	s := p.sleeve("core")
	p.Study156.Reference["core"] = Reference156{Campaign: 7, Occupied: true, Time: 100}
	o := obs156(0, 100, 1000)
	if p.entryAllowed156(s, o, 8, 1) || !p.entryAllowed156(s, o, 7, 1) {
		t.Fatal("旧親と同親の区別")
	}
	ev := ResearchEvent{Action: "new", Side: 1, Quantity: 5, Campaign: 8, Ticket: 0}
	if out := p.nativeResearch(s, o, []ResearchEvent{ev}, true, true); len(out) > 0 {
		t.Fatal(out)
	}
	p.Study156.Reference["core"] = Reference156{Campaign: 7, Occupied: false, Time: 101}
	if out := p.nativeResearch(s, obs156(1, 101, 1000), []ResearchEvent{ev}, true, true); len(out) > 0 {
		t.Fatal("拒否済親を後追い採用")
	}
	if p.entryAllowed156(p.sleeve("addon"), obs156(2, 102, 1000), 9, 1) {
		t.Fatal("未知の参照を占有なし扱い")
	}
}

// Test156MinuteCausalityAndRules は連続足・現分除外・鏡像・失速条件を確かめます。
//
// 引数: t(*testing.T)。返り値: なし。
func Test156MinuteCausalityAndRules(t *testing.T) {
	for _, side := range []int{-1, 1} {
		for rule := 1; rule <= 3; rule++ {
			p := studyTest156(t, 0, 0, false, rule)
			values := []float64{0, 60, 80, 110, 100, 110}
			for i, v := range values {
				p.updateMinutes156(obs156(int64(i), float64(i*60+59), 1000+float64(side)*v))
			}
			if len(p.Study156.Minutes) != 5 {
				t.Fatal("現分closeを確定列へ混入")
			}
			if rule == 3 && p.entryMinuteAllowed156(obs156(6, 359, 9000), 1, side, "core") {
				t.Fatal("6本必要な条件を5本で受付")
			}
			p.updateMinutes156(obs156(7, 360, 9000)) // 当分の極端な値は完了列へ入れない。
			if p.entryMinuteAllowed156(obs156(7, 360, 9000), 1, side, "core") {
				t.Fatal("既知失速を通過", side, rule, p.Study156.Minutes)
			}
			if len(p.Study156.Minutes) != 6 || p.Study156.Minutes[5].Close != 1000+float64(side)*110 {
				t.Fatal("未来close混入")
			}
		}
	}
	p := studyTest156(t, 0, 0, false, 1)
	for _, minute := range []int{0, 2, 3} {
		p.updateMinutes156(obs156(int64(minute), float64(minute*60+59), 1000+float64(minute*10)))
	}
	p.updateMinutes156(obs156(4, 240, 1050))
	if p.entryMinuteAllowed156(obs156(4, 240, 1050), 1, 1, "core") {
		t.Fatal("欠測の分を補間")
	}
	for rule := 1; rule <= 3; rule++ {
		p := studyTest156(t, 0, 0, false, rule)
		for i := 0; i < 7; i++ {
			p.updateMinutes156(obs156(int64(i), float64(i*60), 1000+float64(i*40)))
		}
		if !p.entryMinuteAllowed156(obs156(7, 421, 1280), 1, 1, "core") {
			t.Fatal("順行の正例を拒否", rule)
		}
		if !p.entryAllowed156(p.sleeve("addon"), obs156(7, 421, 1280), 1, -1) {
			t.Fatal("core以外へ入口veto")
		}
	}
}

// Test156CompletedForceReleasesParent は強制返済済みの担当が次親を永久拒否しないことを確かめます。
//
// 引数: t(*testing.T)。返り値: なし。返済予約がある間は新規を受付しません。
func Test156CompletedForceReleasesParent(t *testing.T) {
	p := studyTest156(t, 20, 0, false, 0)
	s := hold156(t, p, "addon", 1, 2)
	closeAllResearch(s, 2)
	if !closing156(s) {
		t.Fatal("残玉がある強制返済を見落とし")
	}
	o := obs156(1, 10, 1050)
	out := p.flushResearchGoals(s, o)
	if len(out) != 1 {
		t.Fatal(out)
	}
	if err := p.OnFill(Fill{SignalID: out[0].ID, ExecutionID: "返済", Quantity: 2, Price: 1045, Time: 11, Closed: out[0].Targets}); err != nil {
		t.Fatal(err)
	}
	if err := p.OnOrderDone(out[0].ID); err != nil {
		t.Fatal(err)
	}
	if closing156(s) {
		t.Fatal("完済後も旧ForceReasonで永久停止")
	}
	o = obs156(3, 12, 1000)
	out = p.nativeResearch(s, o, []ResearchEvent{{Action: "new", Side: -1, Quantity: 2, Campaign: 1, Ticket: 0, Risk: 80}}, true, true)
	if len(out) != 1 || out[0].Campaign != 1 {
		t.Fatal("完済後の新親を拒否", out)
	}
}

// Test156ProtectedCloseGapAndCancel は取消後も床を保ち、発注判断後の板飛び損失を計上します。
//
// 引数: t(*testing.T)。返り値: なし。利益床は約定価格保証ではありません。
func Test156ProtectedCloseGapAndCancel(t *testing.T) {
	for _, side := range []int{-1, 1} {
		p := studyTest156(t, 20, 0, false, 0)
		s := hold156(t, p, "addon", side, 2)
		p.updateLot156(s, obs156(1, 3, 1000+float64(side)*55))
		o := obs156(2, 4, 1000+float64(side)*25)
		p.updateLot156(s, o)
		p.applyLot156(s, o, true)
		out := p.flushResearchGoals(s, o)
		if len(out) != 1 {
			t.Fatal(out)
		}
		if err := p.OnOrderDone(out[0].ID); err != nil {
			t.Fatal(err)
		}
		out = p.flushResearchGoals(s, obs156(3, 5, 1100))
		if len(out) != 1 || out[0].Targets[0].ID != "玉A" {
			t.Fatal("取消済返済目標を喪失", out)
		}
		price := 1000 - float64(side)*30
		if err := p.OnFill(Fill{SignalID: out[0].ID, ExecutionID: "飛び約定", Quantity: 2, Price: price, Time: 6, Closed: out[0].Targets}); err != nil {
			t.Fatal(err)
		}
		if p.researchCash(s) != -6000 || p.Study156.Lots["玉A"].FloorPrice != 1000+float64(side)*30 {
			t.Fatal("飛び損失または床", p.researchCash(s))
		}
	}
}
