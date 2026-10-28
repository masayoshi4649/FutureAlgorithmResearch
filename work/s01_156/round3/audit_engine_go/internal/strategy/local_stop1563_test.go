package strategy

import "testing"

// liveReentry1563 は元玉の保護完済から新しい再参加実玉まで人工注文を通します。
//
// 引数: t(*testing.T)、side(int)、width(float64)。返り値: *Portfolio、*ResearchSleeve。
func liveReentry1563(t *testing.T, side int, width float64) (*Portfolio, *ResearchSleeve) {
	t.Helper()
	p, s := readyReentry1562(t, side, 5)
	if err := p.ConfigureLocalStop1563(width); err != nil {
		t.Fatal(err)
	}
	sig := fireReentry1562(t, p, s)
	if err := p.OnFill(Fill{SignalID: sig.ID, ExecutionID: "再参加", HoldID: "再参加玉", Quantity: 5, Price: 1000 + float64(side)*5, Time: 8}); err != nil {
		t.Fatal(err)
	}
	if err := p.OnOrderDone(sig.ID); err != nil {
		t.Fatal(err)
	}
	return p, s
}

// Test1563LossSymmetryGapAndNoArm は買売鏡像・3幅・次板飛び損失と損切り後停止を検査します。
//
// 引数: t(*testing.T)。返り値: なし。新規の旧床を継承せず、元Sourceを変更しません。
func Test1563LossSymmetryGapAndNoArm(t *testing.T) {
	for _, side := range []int{-1, 1} {
		for _, width := range []float64{20, 40, 80} {
			p, s := liveReentry1563(t, side, width)
			d := float64(side)
			entry := 1000 + d*5
			o := obs156(7, 9, entry)
			p.updateLot156(s, o)
			if g := p.Study156.Lots["再参加玉"]; g == nil || g.Active || g.Entry != entry {
				t.Fatal("旧床を継承", g)
			}
			o = obs156(8, 10, entry-d*(width-5))
			p.applyLocalStop1563(s, o, false)
			if _, exists := s.Goals["再参加玉"]; exists {
				t.Fatal("非新鮮な行で発火")
			}
			p.applyLot156(s, o, true)
			p.applyLocalStop1563(s, o, true)
			out := p.flushResearchGoals(s, o)
			if len(out) != 1 || out[0].ReasonCode != 15631 || out[0].Quantity != 5 {
				t.Fatal("幅の境界", out, s.Goals)
			}
			if len(p.flushResearchGoals(s, o)) != 0 {
				t.Fatal("同注文を重複予約")
			}
			before := p.researchCash(s)
			price := entry - d*(width+30)
			if err := p.OnFill(Fill{SignalID: out[0].ID, ExecutionID: "板飛び", Quantity: 5, Price: price, Time: 11, Closed: out[0].Targets}); err != nil {
				t.Fatal(err)
			}
			p.OnOrderDone(out[0].ID)
			if p.researchCash(s)-before != -5*(width+30)*100 {
				t.Fatal("停止価格の仮想約定", p.researchCash(s), before)
			}
			if s.held() != 0 || p.Reentry1562.Arms[s.Name] != nil || originalQuantity1562(s) != 5 || !sourceContinues1562(s) {
				t.Fatal("元源変更又は損切り後arm")
			}
			if out := p.manageReentry1562(s, obs156(10, 12, entry+d*200), nil, true, true); len(out) != 0 {
				t.Fatal("損切り後の独自再参加", out)
			}
		}
	}
}

// Test1563OriginalFloorAndPartialPriority は元玉非対象・利益床・部分目標・未確定予約を検査します。
//
// 引数: t(*testing.T)。返り値: なし。元の返済を局所理由へ置き換えません。
func Test1563OriginalFloorAndPartialPriority(t *testing.T) {
	for _, side := range []int{-1, 1} {
		p := studyTest156(t, 20, 0, false, 0)
		if err := p.ConfigureReentry1562(20); err != nil {
			t.Fatal(err)
		}
		if err := p.ConfigureLocalStop1563(20); err != nil {
			t.Fatal(err)
		}
		s := hold156(t, p, "core", side, 5)
		p.applyLocalStop1563(s, obs156(1, 3, 1000-float64(side)*200), true)
		if len(s.Goals) != 0 {
			t.Fatal("元初回玉へ局所stop")
		}
		// ----------------------------------------
		// 一度正になった玉は、同時に局所stopも越えていても元利益床が優先です。
		p, s = liveReentry1563(t, side, 20)
		d := float64(side)
		entry := 1000 + d*5
		p.updateLot156(s, obs156(7, 9, entry+d*35))
		o := obs156(8, 10, entry-d*40)
		p.updateLot156(s, o)
		p.applyLot156(s, o, true)
		p.applyLocalStop1563(s, o, true)
		if s.Goals["再参加玉"].Reason != 15601 {
			t.Fatal("利益床の理由上書き", s.Goals)
		}
		// ----------------------------------------
		// 元の部分目標がある間は触らず、約定終了後の実残数だけを判断します。
		p, s = liveReentry1563(t, side, 20)
		s.setGoal("再参加玉", 3, 30)
		o = obs156(8, 10, entry-d*40)
		p.applyLocalStop1563(s, o, true)
		if s.Goals["再参加玉"].Reason != 30 || s.Goals["再参加玉"].Remaining != 3 {
			t.Fatal("元部分を上書き")
		}
		out := p.flushResearchGoals(s, o)
		if len(out) != 1 || out[0].Quantity != 2 {
			t.Fatal(out)
		}
		p.applyLocalStop1563(s, o, true)
		if s.Goals["再参加玉"].Remaining != 3 {
			t.Fatal("未確定返済と重複")
		}
		if err := p.OnFill(Fill{SignalID: out[0].ID, ExecutionID: "部分", Quantity: 2, Price: entry - d*40, Time: 11, Closed: out[0].Targets}); err != nil {
			t.Fatal(err)
		}
		p.OnOrderDone(out[0].ID)
		p.applyLocalStop1563(s, obs156(9, 12, entry-d*40), true)
		out = p.flushResearchGoals(s, obs156(9, 12, entry-d*40))
		if len(out) != 1 || out[0].ReasonCode != 15631 || out[0].Quantity != 3 {
			t.Fatal("残数以外を返済", out)
		}
	}
}

// Test1563ConfigureAndInvalid は未登録幅と異常気配の新規停止を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test1563ConfigureAndInvalid(t *testing.T) {
	p := studyTest156(t, 20, 0, false, 0)
	if p.ConfigureLocalStop1563(20) == nil {
		t.Fatal("再参加なしに局所stop")
	}
	p.ConfigureReentry1562(20)
	if p.ConfigureLocalStop1563(30) == nil {
		t.Fatal("未登録幅")
	}
	if err := p.ConfigureLocalStop1563(20); err != nil {
		t.Fatal(err)
	}
	if p.ConfigureLocalStop1563(40) == nil {
		t.Fatal("幅を途中変更")
	}
	p, s := liveReentry1563(t, 1, 20)
	o := obs156(7, 9, 900)
	o.QuoteOK = false
	p.applyLocalStop1563(s, o, true)
	if _, exists := s.Goals["再参加玉"]; exists {
		t.Fatal("異常板で発火")
	}
}
