package strategy

import (
	"reflect"
	"testing"
)

// auditS01New155 は独立監査の人工ポートフォリオを作ります。
//
// 引数: t(*testing.T)、side/quantity(int)、fee(float64)。返り値: *Portfolioと初回Signal。
func auditS01New155(t *testing.T, side, quantity int, fee float64) (*Portfolio, Signal) {
	t.Helper()
	params, err := ParametersForMethod("NK225", "Day", "S01")
	if err != nil {
		t.Fatal(err)
	}
	p, err := New(Config{Reference: "NK225", Product: "NK225mini", Cap: 10, CoreQuantity: 5, ExtraMaxQuantity: 5, LargeTick: 10, PointValue: 100, Parameters: params}, Session{ID: "独立人工_Day", Kind: "Day", Start: 0, ForceClose: 20000, End: 21000})
	if err != nil {
		t.Fatal(err)
	}
	o := auditS01Quote155(0, 100, 65000)
	sigs := p.nativeResearch(p.sleeve("episode"), o, []ResearchEvent{{Action: "new", Side: side, Quantity: quantity, Campaign: 0, Ticket: 0}}, true, true)
	if len(sigs) != 1 {
		t.Fatalf("初回通知 %v", sigs)
	}
	if quantity > 0 {
		auditS01Fill155(t, p, sigs[0], "初回玉", quantity, 65000, fee, true)
	}
	return p, sigs[0]
}

// auditS01Quote155 は方向に依存しない正常BBOを作ります。
//
// 引数: index(int64)、at/bid(float64)。返り値: Observation。
func auditS01Quote155(index int64, at, bid float64) Observation {
	return Observation{Reference: "NK225", Index: index, Time: at, Received: at, Bid: bid, Ask: bid + 10, Last: bid, ATR: 100, QuoteOK: true}
}

// auditS01Fill155 は人工の注文へ通常の約定・完了通知を接続します。
//
// 引数: t(*testing.T)、p(*Portfolio)、sig(Signal)、id(string)、qty(int)、price/fee(float64)、done(bool)。返り値: なし。
func auditS01Fill155(t *testing.T, p *Portfolio, sig Signal, id string, qty int, price, fee float64, done bool) {
	t.Helper()
	f := Fill{SignalID: sig.ID, ExecutionID: id + "-約定", HoldID: id, Quantity: qty, Price: price, Time: sig.Time + 1, Fee: fee, Closed: sig.Targets}
	if err := p.OnFill(f); err != nil {
		t.Fatal(err)
	}
	if done {
		if err := p.OnOrderDone(sig.ID); err != nil {
			t.Fatal(err)
		}
	}
}

// TestAuditS01FreshDecisionSurvivesCancel155 は新鮮な床割れ後の未約定取消でも返済意図を回復価格で消しません。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditS01FreshDecisionSurvivesCancel155(t *testing.T) {
	for _, side := range []int{-1, 1} {
		p, _ := auditS01New155(t, side, 2, 0)
		mark := func(gain float64) float64 {
			if side > 0 {
				return 65000 + gain
			}
			return 64990 - gain
		}
		if out, err := p.ObserveWithFreshness(auditS01Quote155(1, 102, mark(100)), false, true); err != nil || len(out) != 0 {
			t.Fatal(out, err)
		}
		out, err := p.ObserveWithFreshness(auditS01Quote155(2, 103, mark(40)), false, true)
		if err != nil || len(out) != 1 || out[0].ReasonCode != 15410 {
			t.Fatal(out, err)
		}
		if err = p.OnOrderDone(out[0].ID); err != nil {
			t.Fatal(err)
		}
		out, err = p.ObserveWithFreshness(auditS01Quote155(3, 104, mark(120)), false, true)
		if err != nil || len(out) != 1 || out[0].Quantity != 2 || out[0].ReasonCode != 15410 {
			t.Fatal("取消後の回復で意図を消去", out, err)
		}
	}
}

// TestAuditS01StaleActivationAndRecovery155 は古い最高値は追跡しても古い床割れを後追い発注しません。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditS01StaleActivationAndRecovery155(t *testing.T) {
	for _, advance := range []bool{false, true} {
		p, _ := auditS01New155(t, 1, 2, 0)
		for i, bid := range []float64{65100, 65030} {
			o := auditS01Quote155(int64(i+1), float64(102+i), bid)
			if advance {
				if err := p.Advance(o); err != nil {
					t.Fatal(err)
				}
			} else {
				out, err := p.ObserveWithFreshness(o, false, false)
				if err != nil || len(out) != 0 {
					t.Fatal(out, err)
				}
			}
		}
		if !p.S01.Guard.Active || p.S01.Guard.Best != 20000 || p.S01.Guard.Floor != 10000 || len(p.sleeve("episode").Goals) != 0 {
			t.Fatal(p.S01.Guard)
		}
		out, err := p.ObserveWithFreshness(auditS01Quote155(3, 104, 65090), false, true)
		if err != nil || len(out) != 0 || p.sleeve("episode").Blocked {
			t.Fatal("過去の古い床割れを発注", out, err)
		}
	}
}

// TestAuditS01AddedLotKeepsInitialBasis155 は追加後も初回1枚の基準と親全体の最高益を保持します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditS01AddedLotKeepsInitialBasis155(t *testing.T) {
	p, _ := auditS01New155(t, 1, 1, 999)
	s := p.sleeve("episode")
	p.manageS01Guard(s, auditS01Quote155(1, 102, 65100), true)
	if p.S01.Guard.Best != 10000 {
		t.Fatal("費用を保護額へ混入")
	}
	out := p.nativeResearch(s, auditS01Quote155(2, 103, 65100), []ResearchEvent{{Action: "new", Side: 1, Quantity: 1, Campaign: 0, Ticket: 1}}, true, true)
	if len(out) != 1 {
		t.Fatal(out)
	}
	auditS01Fill155(t, p, out[0], "追加玉", 1, 65110, 888, true)
	if p.S01.Guard.InitialQuantity != 1 || p.S01.Guard.Risk != 100 || p.S01.Guard.Best != 10000 {
		t.Fatal("追加で親基準変更", p.S01.Guard)
	}
	p.manageS01Guard(s, auditS01Quote155(3, 105, 65090), true)
	if s.Blocked {
		t.Fatal("親粗含み7000で床5000の上にいる")
	}
	p.manageS01Guard(s, auditS01Quote155(4, 106, 65080), true)
	if !s.Blocked || s.ForceReason != 15410 {
		t.Fatal("親粗含み5000で床へ到達")
	}
}

// TestAuditS01GrossPartialAndRestore155 は部分返済・費用差・復元後も親の粗時価が同じことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditS01GrossPartialAndRestore155(t *testing.T) {
	for _, fee := range []float64{0, 1000} {
		p, _ := auditS01New155(t, 1, 2, fee)
		s := p.sleeve("episode")
		sig := p.emitResearch(s, auditS01Quote155(1, 102, 65100), ResearchEvent{Action: "close", Side: -1, Quantity: 1, Campaign: 0, Ticket: 0}, []LotTarget{{ID: "初回玉", Quantity: 1}})
		auditS01Fill155(t, p, sig, "部分返済", 1, 65100, fee, true)
		p.manageS01Guard(s, auditS01Quote155(2, 104, 65040), true)
		if p.S01.Guard.Best != 14000 || p.S01.Guard.Floor != 7000 || p.S01.Guard.InitialQuantity != 2 {
			t.Fatal(p.S01.Guard)
		}
		raw, err := p.Dump()
		if err != nil {
			t.Fatal(err)
		}
		q, err := Restore(raw)
		if err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(q.S01.Guard, p.S01.Guard) {
			t.Fatal("復元時の親変化")
		}
		for _, candidate := range []*Portfolio{p, q} {
			candidate.manageS01Guard(candidate.sleeve("episode"), auditS01Quote155(3, 105, 64960), true)
			if candidate.sleeve("episode").ForceReason != 15410 {
				t.Fatal("確定1万と含み-4000の床割れを見落とし")
			}
		}
	}
}

// TestAuditS01NewStartIsEmpty155 は新規運転が実玉・仮想玉・保護・予算を引き継がないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditS01NewStartIsEmpty155(t *testing.T) {
	p, _ := auditS01New155(t, 1, 2, 0)
	p.manageS01Guard(p.sleeve("episode"), auditS01Quote155(1, 102, 65100), true)
	q, err := New(p.Config, p.Session)
	if err != nil {
		t.Fatal(err)
	}
	if q.S01.Guard != nil || len(q.Orders) != 0 || len(q.S01.ShadowPending) != 0 {
		t.Fatal("旧親を新運転へ継承")
	}
	for _, candidate := range []*Portfolio{q, q.S01.Shadow} {
		for _, s := range candidate.Research.Sleeves {
			if s.held() != 0 || s.Cash != 0 || s.Budget != 0 {
				t.Fatal("旧玉・旧予算継承")
			}
		}
	}
}
