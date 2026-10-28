package strategy

import (
	"reflect"
	"testing"
)

// setup154 は当時情報だけを含む人工D07と正常板を用意します。
//
// 引数: t(*testing.T)、id/kind(string)。返り値: *Portfolio、Observation。
func setup154(t *testing.T, id, kind string) (*Portfolio, Observation) {
	t.Helper()
	params, e := ParametersForMethod("NK225", kind, "D07")
	if e != nil {
		t.Fatal(e)
	}
	p, e := New(Config{Reference: "NK225", Product: "NK225mini", Cap: 10, CoreQuantity: 5, ExtraMaxQuantity: 5, LargeTick: 10, PointValue: 100, Parameters: params, Study154: id}, Session{ID: "人工", Kind: kind, Start: 1, End: 50000, ForceClose: 49000, USOpen: 30000, ExtraAt: 32000})
	if e != nil {
		t.Fatal(e)
	}
	o := Observation{Reference: "NK225", Time: 1000, Received: 1000, Index: 1, Last: 1000, Bid: 995, Ask: 1005, ATR: 80, QuoteOK: true}
	for i := range o.Research.Known {
		o.Research.Known[i] = true
	}
	o.Research.Values[9] = 80
	o.Research.Values[12] = .3
	o.Research.Values[13] = .3
	o.Research.Values[20] = .2
	return p, o
}

// fill154 は人工通知を指定した次時点で全量約定させます。
//
// 引数: t(*testing.T)、p(*Portfolio)、s(Signal)、price/at(float64)。返り値: なし。
func fill154(t *testing.T, p *Portfolio, s Signal, price, at float64) {
	t.Helper()
	f := Fill{SignalID: s.ID, ExecutionID: s.ID + "約定", HoldID: s.ID + "玉", Quantity: s.Quantity, Price: price, Time: at, Closed: s.Targets}
	if e := p.OnFill(f); e != nil {
		t.Fatal(e)
	}
	if e := p.OnOrderDone(s.ID); e != nil {
		t.Fatal(e)
	}
}

// Test154JabMapping は影5枚と実1枚を分け、追加と元部分返済の配賦を確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test154JabMapping(t *testing.T) {
	p, o := setup154(t, "C03", "Day")
	s := p.sleeve("core")
	event := ResearchEvent{Action: "new", Side: 1, Quantity: 5, Campaign: 0, Ticket: 0, Risk: 80}
	sig := p.nativeResearch(s, o, []ResearchEvent{event}, true, true)
	if len(sig) != 1 || sig[0].Quantity != 1 || s.Virtual[0] != 5 || s.Requested[0] != 5 {
		t.Fatal("影実分離", sig, s.Virtual, s.Requested)
	}
	fill154(t, p, sig[0], 1005, 1001)
	o.Time = 1030
	o.Index = 2
	o.Bid = 1045
	o.Ask = 1055
	if q := p.addJab154(s, o); len(q) > 0 {
		t.Fatal("30秒未満の追加")
	}
	o.Time = 1031
	added := p.addJab154(s, o)
	if len(added) != 1 || added[0].Quantity != 1 || added[0].Ticket != 0 {
		t.Fatal("追加通知", added)
	}
	if q := p.addJab154(s, o); len(q) > 0 {
		t.Fatal("予約中の再追加")
	}
	fill154(t, p, added[0], 1055, 1032)
	if s.Opened154 != 2 || s.Anchor154 != 1005 || s.Virtual[0] != 5 {
		t.Fatal("初回基準又は影枚数変化")
	}
	o.Time = 1065
	o.Index = 3
	o.Bid = 1100
	o.Ask = 1110
	p.nativeResearch(s, o, []ResearchEvent{{Action: "close", Side: -1, Quantity: 2, Campaign: 0, Ticket: 0, Reason: 7}}, true, true)
	closed := p.flushResearchGoals(s, o)
	if len(closed) != 1 || closed[0].Quantity != 1 {
		t.Fatal("2実枚×2/5の丸め", closed)
	}
	fill154(t, p, closed[0], 1100, 1066)
	if q := p.addJab154(s, o); len(q) > 0 {
		t.Fatal("部分返済後の追加")
	}
	p.nativeResearch(s, o, []ResearchEvent{{Action: "close", Side: -1, Quantity: 3, Campaign: 0, Ticket: 0, Reason: 1}}, true, true)
	closed = p.flushResearchGoals(s, o)
	if len(closed) != 1 || closed[0].Quantity != 1 {
		t.Fatal("影全返済が実残へ届かない", closed)
	}
	fill154(t, p, closed[0], 1090, 1067)
	if s.held() != 0 {
		t.Fatal("残玉")
	}
}

// Test154OneLotPartial は元の部分返済割合の丸めを1枚条件で確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test154OneLotPartial(t *testing.T) {
	for _, closeQty := range []int{2, 3} {
		p, o := setup154(t, "C02", "Day")
		s := p.sleeve("core")
		sig := p.nativeResearch(s, o, []ResearchEvent{{Action: "new", Side: 1, Quantity: 5, Campaign: 0, Ticket: 0, Risk: 80}}, true, true)
		fill154(t, p, sig[0], 1005, 1001)
		o.Index++
		o.Time = 1100
		o.Bid = 1100
		o.Ask = 1110
		p.nativeResearch(s, o, []ResearchEvent{{Action: "close", Side: -1, Quantity: closeQty, Campaign: 0, Ticket: 0, Reason: 7}}, true, true)
		got := p.flushResearchGoals(s, o)
		n := 0
		for _, v := range got {
			n += v.Quantity
		}
		want := 0
		if closeQty == 3 {
			want = 1
		}
		if n != want {
			t.Fatal(closeQty, n, want)
		}
	}
}

// Test154JabExitPriority は新規追加より元返済・場末・不明特徴を優先します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test154JabExitPriority(t *testing.T) {
	for _, reason := range []string{"返済目標", "反証", "場末", "未知", "逆行", "間隔"} {
		p, o := setup154(t, "C03", "Day")
		s := p.sleeve("core")
		sig := p.nativeResearch(s, o, []ResearchEvent{{Action: "new", Side: 1, Quantity: 5, Campaign: 0, Ticket: 0, Risk: 80}}, true, true)
		fill154(t, p, sig[0], 1005, 1001)
		o.Time = 1100
		o.Bid = 1100
		o.Ask = 1110
		switch reason {
		case "返済目標":
			s.setGoal(s.Lots[0].ID, 0, 1)
		case "反証":
			closeAllResearch(s, 14312)
		case "場末":
			o.Time = p.Session.ForceClose
		case "未知":
			o.Research.Known[20] = false
		case "逆行":
			o.Research.Values[13] = -.1
		case "間隔":
			o.Time = 1002
		}
		if x := p.addJab154(s, o); len(x) != 0 {
			t.Fatal(reason, x)
		}
	}
}

// Test154ResidualVariants は残玉化拒否・予算縮小・固定床・幅上限の差を確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test154ResidualVariants(t *testing.T) {
	for _, id := range []string{"D07", "E01", "E02", "E03", "E04", "E05"} {
		p, o := setup154(t, id, "Day")
		s := p.sleeve("episode")
		sig := p.nativeResearch(s, o, []ResearchEvent{{Action: "new", Side: 1, Quantity: 2, Campaign: 0, Ticket: 0, Risk: 80}}, true, true)
		fill154(t, p, sig[0], 1000, 1001)
		o.Time = 1100
		o.Index++
		o.Bid = 1100
		o.Ask = 1110
		kept := p.retainResearch(s, o, []ResearchEvent{{Action: "close", Side: -1, Quantity: 2, Campaign: 0, Ticket: 0, Reason: 70}})
		if kept != (id != "E01") {
			t.Fatal(id, kept)
		}
		if !kept {
			continue
		}
		req := p.flushResearchGoals(s, o)
		if len(req) != 1 || req[0].Quantity != 1 {
			t.Fatal(id, req)
		}
		fill154(t, p, req[0], 1100, 1101)
		p.researchManage(s, o)
		want := 10000.
		if id == "E02" {
			want = 5000
		}
		if s.Stage != 2 || s.Budget != want {
			t.Fatal(id, s.Stage, s.Budget)
		}
		width, _ := p.researchResidualWidth(s)
		wantWidth := 240.
		if id == "E03" {
			wantWidth = 160
		}
		if id == "E04" {
			wantWidth = 80
		}
		if width != wantWidth {
			t.Fatal(id, width)
		}
		if id == "E05" {
			if s.ResidualFloor154 != 50 {
				t.Fatal(s.ResidualFloor154)
			}
			o.Bid = 1200
			o.Ask = 1210
			p.researchManage(s, o)
			if s.ResidualFloor154 != 50 {
				t.Fatal("固定床が最高益へ追随")
			}
			o.Bid = 1040
			o.Ask = 1050
			p.researchManage(s, o)
			if s.ForceReason == 0 {
				t.Fatal("利益50床を無視")
			}
		}
	}
}

// Test154NightCoreUnchanged は日中限定の小口化が夜の主担当へ混ざらないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test154NightCoreUnchanged(t *testing.T) {
	var want []Signal
	for _, id := range []string{"D07", "C02", "C03"} {
		p, o := setup154(t, id, "Night")
		sig := p.nativeResearch(p.sleeve("core"), o, []ResearchEvent{{Action: "new", Side: 1, Quantity: 5, Campaign: 0, Ticket: 0, Risk: 80}}, true, true)
		if id == "D07" {
			want = sig
		} else if !reflect.DeepEqual(want, sig) {
			t.Fatal(id, "夜の源通知が変化")
		}
	}
}

// Test154ParentValueGuard は利益床を部分利確・残玉・新規追加で初期化しないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test154ParentValueGuard(t *testing.T) {
	for _, id := range []string{"G01", "G02"} {
		p, o := setup154(t, id, "Day")
		s := p.sleeve("episode")
		sig := p.nativeResearch(s, o, []ResearchEvent{{Action: "new", Side: 1, Quantity: 2, Campaign: 0, Ticket: 0, Risk: 80}}, true, true)
		fill154(t, p, sig[0], 1000, 1001)
		o.Time = 1100
		o.Bid = 1040
		o.Ask = 1050
		p.manageGuard154(s, o)
		if s.GuardActive154 != (id == "G01") {
			t.Fatal(id, "開始倍率")
		}
		o.Bid = 1080
		o.Ask = 1090
		p.manageGuard154(s, o)
		if !s.GuardActive154 || s.GuardFloor154 != 8000 || s.GuardQ154 != 2 {
			t.Fatal(id, s.GuardFloor154)
		}
		s.Stage = 2
		s.Cash = 8000
		s.Lots[0].Quantity = 1
		o.Bid = 1080
		p.manageGuard154(s, o)
		if s.GuardFloor154 != 8000 {
			t.Fatal("部分利確で床変更")
		}
		o.Bid = 995
		o.Ask = 1005
		p.manageGuard154(s, o)
		if !s.Blocked || s.ForceReason != 15410 {
			t.Fatal("全親の利益床を無視")
		}
		blocked := p.nativeResearch(s, o, []ResearchEvent{{Action: "new", Side: 1, Quantity: 1, Campaign: 0, Ticket: 1, Risk: 80}}, true, true)
		if len(blocked) > 0 {
			t.Fatal("同親追加")
		}
		closed := p.flushResearchGoals(s, o)
		if len(closed) != 1 {
			t.Fatal(closed)
		}
		fill154(t, p, closed[0], 995, 1101)
		if !p.guardEntryAllowed154(s, false) {
			t.Fatal("完済後も次親入口が禁止")
		}
		s.Stage = 0
		o.Time = 1200
		o.Index++
		next := p.nativeResearch(s, o, []ResearchEvent{{Action: "new", Side: 1, Quantity: 2, Campaign: 1, Ticket: 0, Risk: 80}}, true, true)
		if len(next) != 1 || s.Blocked || s.GuardActive154 || s.GuardQ154 != 0 {
			t.Fatal("新親が解除されない", next)
		}
	}
}

// Test154GuardKeepsOriginalExit は利益床と元退出が同時でも元の理由を保持します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test154GuardKeepsOriginalExit(t *testing.T) {
	p, o := setup154(t, "G01", "Day")
	s := p.sleeve("episode")
	s.Side = 1
	s.FixedR = 80
	s.GuardQ154 = 2
	s.GuardActive154 = true
	s.GuardBest154 = 20000
	s.GuardFloor154 = 10000
	s.Lots = []ResearchLot{{ID: "a", Quantity: 2, Price: 1000}}
	s.setGoal("a", 0, 1436)
	o.Bid = 1010
	o.Ask = 1020
	p.manageGuard154(s, o)
	if s.ForceReason != 0 || s.Goals["a"].Reason != 1436 {
		t.Fatal("元退出を上書き")
	}
}
