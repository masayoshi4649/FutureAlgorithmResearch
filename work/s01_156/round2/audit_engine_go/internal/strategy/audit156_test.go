package strategy

import (
	"encoding/json"
	"reflect"
	"testing"
)

// auditPortfolio156 は独立した人工状態を作り、観測・実玉・担当を固定します。
//
// 引数: rule(int)、width/activation(float64)。返り値: *Portfolio、*ResearchSleeve。
func auditPortfolio156(rule int, width, activation float64) (*Portfolio, *ResearchSleeve) {
	s := &ResearchSleeve{Name: "core", Capacity: 5, Campaign: 1, Side: 1, Accepted: map[int]bool{}, Virtual: map[int]int{}, Requested: map[int]int{}, Opened: map[int]int{}, CloseReason: map[int]int{}, Goals: map[string]ResearchGoal{}, FixedR: 80, FailureSince: -1}
	p := &Portfolio{Session: Session{ID: "人工", Kind: "Day", Start: 0, ForceClose: 10000, End: 11000}, Config: Config{Reference: "NK225", Product: "NK225mini", Cap: 10, LargeTick: 10, PointValue: 100}, Research: &ResearchPortfolio{Sleeves: []*ResearchSleeve{s}}, Orders: map[string]*orderState{}, Executions: map[string]Fill{}, Study156: &StudyState156{EntryRule: rule, Width: width, Activation: activation, Lots: map[string]*LotGuard156{}, Reference: map[string]Reference156{}}}
	return p, s
}

// auditObservation156 は実板を読まない正常ラージ観測を作ります。
//
// 引数: at/mark(float64)、side(int)。返り値: Observationは返済側価格をmarkとした板です。
func auditObservation156(at, mark float64, side int) Observation {
	o := Observation{Reference: "NK225", Time: at, Received: at, Index: int64(at), Last: mark, QuoteOK: true, ATR: 80}
	if side > 0 {
		o.Bid, o.Ask = mark, mark+10
	} else {
		o.Bid, o.Ask = mark-10, mark
	}
	return o
}

// auditMinutes156 は指定した確定終値だけを時系列に入れ、最後に未知の当分を開始します。
//
// 引数: p(*Portfolio)、closes([]float64)。返り値: Observationは最後の確定分の翌分です。
func auditMinutes156(p *Portfolio, closes []float64) Observation {
	for i, v := range closes {
		p.updateMinutes156(auditObservation156(float64(i*60+59), v, 1))
	}
	o := auditObservation156(float64(len(closes)*60), 100000, 1)
	p.updateMinutes156(o)
	return o
}

// TestAudit156MinuteCurrentNeverLeaks は現在足の任意の上書きが確定足の採否を変えないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit156MinuteCurrentNeverLeaks(t *testing.T) {
	for _, side := range []int{1, -1} {
		p, _ := auditPortfolio156(1, 0, 0)
		closes := []float64{1000, 1000 + float64(side)*10, 1000 + float64(side)*20}
		o := auditMinutes156(p, closes)
		before, _ := json.Marshal(p.Study156.Minutes)
		for _, last := range []float64{1, 1000000} {
			o.Time, o.Last = 181, last
			p.updateMinutes156(o)
			if !p.entryMinuteAllowed156(o, 1, side, "core") {
				t.Fatal("当分の値で確定済み方向を拒否")
			}
			after, _ := json.Marshal(p.Study156.Minutes)
			if string(before) != string(after) {
				t.Fatal("確定足へ当分値が混入")
			}
		}
	}
}

// TestAudit156MinuteGapsUnknown は連続足と直前分の欠測をゼロ補完しないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit156MinuteGapsUnknown(t *testing.T) {
	for _, times := range [][]float64{{59, 179, 239, 240}, {59, 119, 179, 300}} {
		p, _ := auditPortfolio156(1, 0, 0)
		var o Observation
		for i, at := range times {
			o = auditObservation156(at, 1000+float64(i)*10, 1)
			p.updateMinutes156(o)
		}
		if p.entryMinuteAllowed156(o, 1, 1, "core") {
			t.Fatal("欠測足を許可")
		}
		if !p.Study156.EntryRejected[0].Unknown {
			t.Fatal("欠測を方向不成立と誤分類")
		}
	}
}

// TestAudit156MinuteRulesMirrorAndBoundary は三入口の境界と売買鏡像を独立の算術期待値で確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit156MinuteRulesMirrorAndBoundary(t *testing.T) {
	cases := []struct {
		rule    int
		deltas  []float64
		allowed bool
	}{
		{1, []float64{0, 20, 0}, false}, {1, []float64{0, -10, 1}, true},
		{2, []float64{0, 0, 20}, false}, {2, []float64{0, 10, 20}, true},
		{3, []float64{0, 20, 40, 60, 70, 80}, false}, {3, []float64{0, 20, 40, 59, 70, 79}, true},
		{3, []float64{0, 20, 40, 60, 70, 81}, true},
	}
	for _, c := range cases {
		for _, side := range []int{1, -1} {
			p, _ := auditPortfolio156(c.rule, 0, 0)
			prices := make([]float64, len(c.deltas))
			for i, d := range c.deltas {
				prices[i] = 1000 + float64(side)*d
			}
			o := auditMinutes156(p, prices)
			if got := p.entryMinuteAllowed156(o, 1, side, "core"); got != c.allowed {
				t.Fatalf("入口%d 方向%d: %v != %v", c.rule, side, got, c.allowed)
			}
		}
	}
}

// TestAudit156EntryRejectedParentStaysRejected はcoreの拒否が同親後追いを許さず、他担当へ波及しないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit156EntryRejectedParentStaysRejected(t *testing.T) {
	p, s := auditPortfolio156(1, 0, 0)
	o := auditMinutes156(p, []float64{1000, 1000, 1000})
	e := []ResearchEvent{{Action: "new", Side: 1, Quantity: 5, Campaign: 7, Ticket: 0}}
	if len(p.nativeResearch(s, o, e, true, true)) != 0 || s.Accepted[7] {
		t.Fatal("不成立親を受付")
	}
	p.Study156.Minutes[2].Close = 1010
	if len(p.nativeResearch(s, o, e, true, true)) != 0 || s.Accepted[7] {
		t.Fatal("同親を後追いで受付")
	}
	for _, owner := range []string{"addon", "episode"} {
		s.Name = owner
		if !p.entryAllowed156(s, o, 8, 1) {
			t.Fatal("入口がcore以外へ波及")
		}
	}
}

// TestAudit156LotsIndependentMirror は有利な旧玉の床を損失中の新玉へ流用しないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit156LotsIndependentMirror(t *testing.T) {
	for _, side := range []int{1, -1} {
		p, s := auditPortfolio156(0, 20, 20)
		s.Side = side
		s.Lots = []ResearchLot{{ID: "旧玉", Price: 1000, Quantity: 1}, {ID: "新玉", Price: 1000 + float64(side)*50, Quantity: 2}}
		o := auditObservation156(100, 1000+float64(side)*40, side)
		p.updateLot156(s, o)
		if !p.Study156.Lots["旧玉"].Active || p.Study156.Lots["新玉"].Active {
			t.Fatal("玉別起動が混線")
		}
		o = auditObservation156(101, 1000+float64(side)*20, side)
		p.updateLot156(s, o)
		p.applyLot156(s, o, true)
		if _, ok := s.Goals["旧玉"]; !ok {
			t.Fatal("旧玉床未発火")
		}
		if _, ok := s.Goals["新玉"]; ok {
			t.Fatal("新玉へ旧玉床転用")
		}
	}
}

// TestAudit156PartialGoalThenResidual は元の部分返済を先行し、その実約定後に残玉へ同じ床を再適用します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit156PartialGoalThenResidual(t *testing.T) {
	p, s := auditPortfolio156(0, 20, 0)
	s.Lots = []ResearchLot{{ID: "玉", Price: 1000, Quantity: 3}}
	p.updateLot156(s, auditObservation156(100, 1050, 1))
	s.setGoal("玉", 1, 70)
	o := auditObservation156(101, 1020, 1)
	p.updateLot156(s, o)
	p.applyLot156(s, o, true)
	if s.Goals["玉"].Remaining != 1 || s.Goals["玉"].Reason != 70 {
		t.Fatal("元部分返済を上書き")
	}
	s.Lots[0].Quantity = 1
	p.applyLot156(s, auditObservation156(102, 1020, 1), true)
	if s.Goals["玉"].Remaining != 0 || s.Goals["玉"].Reason != 15601 {
		t.Fatal("残玉保護が抜ける")
	}
}

// TestAudit156FloorMonotoneAndFresh は絶対床を緩めず、古い観測では新返済を作らず、既存目標を回復で消さないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit156FloorMonotoneAndFresh(t *testing.T) {
	for _, side := range []int{1, -1} {
		p, s := auditPortfolio156(0, 20, 0)
		s.Side = side
		s.Lots = []ResearchLot{{ID: "玉", Price: 1000, Quantity: 2}}
		p.updateLot156(s, auditObservation156(100, 1000+float64(side)*50, side))
		floor := p.Study156.Lots["玉"].FloorPrice
		s.Lots[0].Price = 1000 - float64(side)*50
		o := auditObservation156(101, 1000+float64(side)*20, side)
		p.updateLot156(s, o)
		p.applyLot156(s, o, false)
		if p.Study156.Lots["玉"].FloorPrice != floor || len(s.Goals) != 0 {
			t.Fatal("床緩和又は古い観測の発注")
		}
		p.applyLot156(s, o, true)
		goal := s.Goals["玉"]
		p.updateLot156(s, auditObservation156(102, 1000+float64(side)*100, side))
		p.applyLot156(s, auditObservation156(102, 1000+float64(side)*100, side), true)
		if !reflect.DeepEqual(goal, s.Goals["玉"]) {
			t.Fatal("成立済み返済を回復で解除")
		}
	}
}

// TestAudit156CompletedForceReasonUnlock は旧親完済後の残る理由を新親の永続禁止へ使わないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit156CompletedForceReasonUnlock(t *testing.T) {
	_, s := auditPortfolio156(0, 20, 0)
	s.ForceReason = 14312
	s.Blocked = true
	s.Lots = []ResearchLot{{ID: "完済玉", Quantity: 0}}
	if closing156(s) {
		t.Fatal("完済旧親が新親を永続禁止")
	}
	s.Lots[0].Quantity = 1
	if !closing156(s) {
		t.Fatal("未返済旧親の新規禁止が解除")
	}
}

// TestAudit156ReferenceSameRowOwnerAndCopy は同担当の当時占有だけを値コピーし、将来変更や別担当へ引きずられないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit156ReferenceSameRowOwnerAndCopy(t *testing.T) {
	p, s := auditPortfolio156(0, 20, 0)
	p.Study156.Gate = true
	base, bs := auditPortfolio156(0, 0, 0)
	base.LastTime = 100
	bs.Campaign = 2
	bs.Lots = []ResearchLot{{ID: "基準玉", Quantity: 1}}
	p.SetReference156(base)
	bs.Campaign = 3
	bs.Lots[0].Quantity = 0
	o := auditObservation156(100, 1000, 1)
	if p.entryAllowed156(s, o, 3, 1) || !p.entryAllowed156(s, o, 2, 1) {
		t.Fatal("同親/異親の採否又は値コピー不正")
	}
	o.Time = 101
	if p.entryAllowed156(s, o, 2, 1) {
		t.Fatal("過去時刻の参照で受付")
	}
	if p.Study156.Reference["core"].Campaign != 2 || !p.Study156.Reference["core"].Occupied {
		t.Fatal("基準の将来変更が参照へ混入")
	}
}

// TestAudit156BreakevenDecisionMayFillAtLoss は建値床の判断が次気配の赤字約定を隠さないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。人工の次原行だけを使い、実板は読みません。
func TestAudit156BreakevenDecisionMayFillAtLoss(t *testing.T) {
	for _, side := range []int{1, -1} {
		p, s := auditPortfolio156(0, 20, 0)
		s.Side = side
		s.Lots = []ResearchLot{{ID: "既玉", EntryID: "既注文", Ticket: 0, Quantity: 2, Price: 1000}}
		p.updateLot156(s, auditObservation156(100, 1000+float64(side)*10, side))
		o := auditObservation156(101, 1000, side)
		p.applyLot156(s, o, true)
		signals := p.flushResearchGoals(s, o)
		if len(signals) != 1 || signals[0].ReasonCode != 15602 {
			t.Fatal("建値床で予約されない")
		}
		sig := signals[0]
		if len(sig.Targets) != 1 || sig.Targets[0].ID != "既玉" || sig.Targets[0].Quantity != 2 {
			t.Fatal("返済対象の混線")
		}
		if err := p.OnFill(Fill{SignalID: sig.ID, ExecutionID: "次行実約定", Time: 102, Quantity: 2, Price: 1000 - float64(side)*30, Closed: sig.Targets}); err != nil {
			t.Fatal(err)
		}
		if s.Cash != -6000 || s.held() != 0 {
			t.Fatalf("次気配損失を建値で捏造: %v", s.Cash)
		}
	}
}
