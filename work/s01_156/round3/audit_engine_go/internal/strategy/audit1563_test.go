package strategy

import (
	"encoding/json"
	"testing"
)

// TestAudit1563ActualEntryBoundaryAndOriginalExclusion は実建値の3幅境界と正ticket非対象を検査します。
//
// 引数: t(*testing.T)。返り値: なし。買売鏡像を同一の返済側価格で確認します。
func TestAudit1563ActualEntryBoundaryAndOriginalExclusion(t *testing.T) {
	for _, side := range []int{-1, 1} {
		for _, width := range []float64{20, 40, 80} {
			p, s := auditReentry1562(side)
			p.Reentry1562.LocalStop = width
			s.Lots = []ResearchLot{{ID: "元玉", Ticket: 0, Price: 1000, Quantity: 1}, {ID: "再参加", Ticket: -1, Price: 1000, Quantity: 1}, {ID: "返済済", Ticket: -2, Price: 1000}}
			before, _ := json.Marshal(s.Source)
			p.applyLocalStop1563(s, auditObservation156(101, 1000-float64(side)*(width-1), side), true)
			if len(s.Goals) != 0 {
				t.Fatal("指定損失幅より手前で発火")
			}
			p.applyLocalStop1563(s, auditObservation156(102, 1000-float64(side)*width, side), true)
			if len(s.Goals) != 1 || s.Goals["再参加"].Reason != 15631 || s.Goals["再参加"].Remaining != 0 {
				t.Fatal("境界又は対象玉の差", s.Goals)
			}
			after, _ := json.Marshal(s.Source)
			if string(before) != string(after) {
				t.Fatal("局所停止で元Sourceを変更")
			}
		}
	}
}

// TestAudit1563WideSpreadCanStopImmediately は値動きがなくても実建値と返済側の差を無視しないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。20pt気配差は20pt局所停止へ等号到達します。
func TestAudit1563WideSpreadCanStopImmediately(t *testing.T) {
	for _, side := range []int{-1, 1} {
		p, s := auditReentry1562(side)
		p.Reentry1562.LocalStop = 20
		s.Lots = []ResearchLot{{ID: "再参加", Ticket: -1, Price: 1010 + float64(side)*10, Quantity: 1}}
		o := auditObservation156(101, 1010-float64(side)*10, side)
		o.Bid, o.Ask = 1000, 1020
		p.applyLocalStop1563(s, o, true)
		if s.Goals["再参加"].Reason != 15631 {
			t.Fatal("気配差を初期損失から除外")
		}
	}
}

// TestAudit1563MixedProfitAndLocalStopDoesNotArm は同時の利益返済と局所停止を利益群へ読み替えません。
//
// 引数: t(*testing.T)。返り値: なし。最後の約定が利益理由でも再参加準備を作りません。
func TestAudit1563MixedProfitAndLocalStopDoesNotArm(t *testing.T) {
	for _, reverse := range []bool{false, true} {
		p, s := auditReentry1562(1)
		delete(p.Reentry1562.Arms, s.Name)
		p.Reentry1562.LocalStop = 20
		s.Lots = []ResearchLot{{ID: "利益玉", Ticket: -1, Price: 900, Quantity: 1}, {ID: "損失玉", Ticket: -2, Price: 1100, Quantity: 1}}
		s.Goals["利益玉"] = ResearchGoal{Remaining: 0, Reason: 15601}
		p.applyLocalStop1563(s, auditObservation156(100, 1000, 1), true)
		if s.Goals["利益玉"].Reason != 15601 || s.Goals["損失玉"].Reason != 15631 {
			t.Fatal("元利益床の上書き又は局所漏れ")
		}
		orders := []Signal{{Action: "close", Quantity: 1, ReasonCode: 15601}, {Action: "close", Quantity: 1, ReasonCode: 15631}}
		p.planReentryBatch1562(s, orders)
		if reverse {
			orders[0], orders[1] = orders[1], orders[0]
		}
		for _, sig := range orders {
			s.Lots = nil
			p.recordReentryFill1562(s, Fill{Time: 101, Quantity: 1}, sig)
		}
		if p.Reentry1562.Arms[s.Name] != nil {
			t.Fatal("局所停止の混合群から再参加")
		}
	}
}

// TestAudit1563ProfitFloorPriorityKeepsOriginalRearm は利益床を先に判断した注文の意味を局所幅で変えません。
//
// 引数: t(*testing.T)。返り値: なし。床から飛んだ実損失も計上し、既存の保護後再参加条件を保ちます。
func TestAudit1563ProfitFloorPriorityKeepsOriginalRearm(t *testing.T) {
	for _, side := range []int{-1, 1} {
		p, s := liveReentry1563(t, side, 20)
		entry := s.Lots[len(s.Lots)-1].Price
		p.updateLot156(s, auditObservation156(101, entry+float64(side)*30, side))
		o := auditObservation156(102, entry-float64(side)*50, side)
		p.updateLot156(s, o)
		p.applyLot156(s, o, true)
		p.applyLocalStop1563(s, o, true)
		out := p.flushResearchGoals(s, o)
		if len(out) != 1 || out[0].ReasonCode != 15601 {
			t.Fatal("同時到達を局所理由へ置換", out)
		}
		price := entry - float64(side)*60
		if err := p.OnFill(Fill{SignalID: out[0].ID, ExecutionID: "保護後飛び", Quantity: out[0].Quantity, Price: price, Time: 103, Closed: out[0].Targets}); err != nil {
			t.Fatal(err)
		}
		p.OnOrderDone(out[0].ID)
		if p.Reentry1562.Arms[s.Name] == nil {
			t.Fatal("利益床理由の再参加条件まで変更")
		}
	}
}
