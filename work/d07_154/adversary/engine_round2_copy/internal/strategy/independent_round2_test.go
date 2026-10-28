package strategy

import (
	"encoding/json"
	"reflect"
	"testing"
)

// TestIndependent154R2CloseInFlight は完済約定と注文終了の間も影占有を維持することを検査します。
//
// 引数: t(*testing.T)。返り値: なし。実資料は使用しません。
func TestIndependent154R2CloseInFlight(t *testing.T) {
	p, o := setup154(t, "S01", "Day")
	r, _ := setup154(t, "D07", "Day")
	s := r.sleeve("episode")
	first := r.nativeResearch(s, o, []ResearchEvent{{Action: "new", Side: 1, Quantity: 2, Campaign: 0, Ticket: 0, Risk: 80}}, true, true)
	fill154(t, r, first[0], 1005, 1001)
	closeAllResearch(s, 1)
	o.Time, o.Index = 1002, 2
	closing := r.flushResearchGoals(s, o)
	if len(closing) != 1 {
		t.Fatal("返済予約なし")
	}
	c := closing[0]
	if err := r.OnFill(Fill{SignalID: c.ID, ExecutionID: c.ID + "約定", Quantity: c.Quantity, Price: 995, Time: 1003, Closed: c.Targets}); err != nil {
		t.Fatal(err)
	}
	if s.held() != 0 {
		t.Fatal("人工の完済失敗")
	}
	p.SetReference154(r)
	if p.referenceAllows154("episode", 1, o) {
		t.Fatal("注文終了前の新親受理")
	}
	if err := r.OnOrderDone(c.ID); err != nil {
		t.Fatal(err)
	}
	p.SetReference154(r)
	if !p.referenceAllows154("episode", 1, o) {
		t.Fatal("照合完了後の恒久拒否")
	}
}

// TestIndependent154R2SameParentStaysBlocked は同親許可が元の停止を解除しないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependent154R2SameParentStaysBlocked(t *testing.T) {
	p, o := setup154(t, "S01", "Day")
	s := p.sleeve("episode")
	p.Reference154 = &ReferenceState154{Campaign: 4, Occupied: true, At: o.Time}
	s.Campaign, s.Side, s.Blocked = 4, 1, true
	s.Accepted[4] = true
	e := ResearchEvent{Action: "new", Side: 1, Quantity: 1, Campaign: 4, Ticket: 1, Risk: 80}
	if got := p.nativeResearch(s, o, []ResearchEvent{e}, true, true); len(got) != 0 || !s.Blocked {
		t.Fatal("同親の停止解除", got)
	}
	before, _ := json.Marshal(p.Reference154)
	p.referenceAllows154("core", 5, o)
	after, _ := json.Marshal(p.Reference154)
	if string(before) != string(after) {
		t.Fatal("照会が基準状態を変更")
	}
}

// TestIndependent154R2JModeFixedAndNextParent は入口後の数量方式を固定し、次親だけ再判定します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependent154R2JModeFixedAndNextParent(t *testing.T) {
	for _, id := range []string{"J01", "J02", "J03"} {
		p, o := setup154(t, id, "Day")
		s, ep := p.sleeve("core"), p.sleeve("episode")
		e := ResearchEvent{Action: "new", Side: 1, Quantity: 5, Campaign: 0, Ticket: 0, Risk: 80}
		first := p.nativeResearch(s, o, []ResearchEvent{e}, true, true)
		if len(first) != 1 || first[0].Quantity != 5 || s.JabMode154 != 0 {
			t.Fatal("元枚数", id, first)
		}
		fill154(t, p, first[0], 1005, 1001)
		ep.Side, ep.FixedR = 1, 80
		ep.Lots = []ResearchLot{{ID: "後から順行した玉", Quantity: 1, Price: 900}}
		o.Time, o.Index, o.Bid, o.Ask = 1035, 2, 1100, 1110
		if p.jab154(s) || len(p.addJab154(s, o)) != 0 || s.JabMode154 != 0 {
			t.Fatal("保有中の方式変更", id)
		}
		closeAllResearch(s, 1)
		for _, sig := range p.flushResearchGoals(s, o) {
			fill154(t, p, sig, 1100, 1036)
		}
		o.Time, o.Index = 1037, 3
		e.Campaign = 1
		next := p.nativeResearch(s, o, []ResearchEvent{e}, true, true)
		if len(next) != 1 || next[0].Quantity != 1 || !p.jab154(s) {
			t.Fatal("次親の再判定なし", id, next)
		}
	}
}

// TestIndependent154R2JUsesRemainingValue は確定益や未約定を同方向の実含みへ混ぜないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependent154R2JUsesRemainingValue(t *testing.T) {
	p, o := setup154(t, "J02", "Day")
	s, ep := p.sleeve("core"), p.sleeve("episode")
	ep.Side, ep.FixedR, ep.Cash = 1, 80, 1000000
	ep.Lots = []ResearchLot{{ID: "残玉", Quantity: 1, Price: 1000}}
	if p.chooseJab154(s, o, 1) != 0 {
		t.Fatal("確定利益を含みに混入")
	}
	ep.Lots = nil
	p.emitResearch(ep, o, ResearchEvent{Action: "new", Side: 1, Quantity: 2, Campaign: 0, Ticket: 0, Risk: 80}, nil)
	if p.chooseJab154(s, o, 1) != 0 {
		t.Fatal("未約定を実玉に混入")
	}
	ep.Lots = []ResearchLot{{ID: "実玉", Quantity: 1, Price: 900}}
	ep.setGoal("実玉", 0, 1)
	if p.chooseJab154(s, o, 1) != 3 {
		t.Fatal("未約定返済を先取り")
	}
}

// TestIndependent154R2ScopeNoOtherOwnerChange は別入口限定保護が他担当の原出口を変えないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependent154R2ScopeNoOtherOwnerChange(t *testing.T) {
	for _, owner := range []string{"core", "addon"} {
		for _, id := range []string{"S00", "S01", "S04", "S02"} {
			base, o := setup154(t, "D07", "Day")
			p, _ := setup154(t, id, "Day")
			var signals [][]Signal
			for _, x := range []*Portfolio{base, p} {
				s := x.sleeve(owner)
				s.Campaign, s.Side, s.FixedR, s.GuardQ154 = 0, 1, 80, 1
				s.Lots = []ResearchLot{{ID: "比較玉", Quantity: 1, Price: 900}}
				x.manageGuard154(s, o)
				o2 := o
				o2.Time += 1
				o2.Index++
				o2.Bid, o2.Ask = 940, 950
				x.manageGuard154(s, o2)
				signals = append(signals, x.flushResearchGoals(s, o2))
			}
			if !reflect.DeepEqual(signals[0], signals[1]) || len(signals[1]) != 0 {
				t.Fatal(owner, id, signals)
			}
		}
	}
}

// TestIndependent154R2ReferenceCopiesState は参照先の後の変化が当時の拒否記録を書き換えないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependent154R2ReferenceCopiesState(t *testing.T) {
	p, o := setup154(t, "S02", "Day")
	r, _ := setup154(t, "D07", "Day")
	s := r.sleeve("episode")
	s.Campaign = 7
	s.Lots = []ResearchLot{{ID: "影玉", Quantity: 1, Price: 1000}}
	r.LastTime = o.Time
	p.SetReference154(r)
	if p.referenceAllows154("episode", 8, o) {
		t.Fatal("新親を拒否できない")
	}
	s.Campaign = 9
	s.Lots = nil
	r.LastTime++
	p.SetReference154(r)
	old := p.ReferenceRejected154[0]
	if old.Reference.Campaign != 7 || !old.Reference.Occupied || old.Reference.At != o.Time {
		t.Fatal("過去の拒否が変質", old)
	}
}
