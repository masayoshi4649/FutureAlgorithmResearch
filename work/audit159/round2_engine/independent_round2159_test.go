package main

import (
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
	"testing"
)

// auditQuoteR2159 は実建値1000を中心に方向付き含み幅を持つ人工気配を返します。
//
// 引数: side(int)、index(int64)、at/gain(float64)。返り値: strategy.Observationです。
func auditQuoteR2159(side int, index int64, at, gain float64) strategy.Observation {
	mark := 1000 + float64(side)*gain
	if side > 0 {
		return quote159(index, at, mark, mark+10)
	}
	return quote159(index, at, mark-10, mark)
}

// auditSeedR2159 はSource初回5miniと政策80microの実約定を作ります。
//
// 引数: t(*testing.T)、id/phase(string)、side(int)、known(bool)。返り値: *PolicyResult157と親です。
func auditSeedR2159(t *testing.T, id, phase string, side int, known bool) (*PolicyResult157, *AllocationParent157) {
	t.Helper()
	var config Policy157
	for _, c := range configsRound2159() {
		if c.ID == id {
			config = effective159(c, phase)
		}
	}
	if config.ID == "" {
		t.Fatal("候補不明")
	}
	r := newPolicy157(config, Scene{Kind: "Night", Start: 900, ForceClose: 10000, End: 10100})
	s := Support157{Known: known, M: 1, T: 7.0 / 9, Own5: float64(side), Own15: float64(side)}
	ss := map[int]Support157{side: s}
	sig := strategy.Signal{ID: phase + "/seed", Owner: phase + "/core", Campaign: 1, Side: side,
		Action: "new", Quantity: 5, SourceIndex: 0, Time: 1000}
	for i := int64(0); i < 2; i++ {
		var signals []strategy.Signal
		if i == 0 {
			signals = []strategy.Signal{sig}
		}
		if e := stepPolicy159(r, auditQuoteR2159(side, i, 1000+float64(i), -10), signals, ss); e != nil {
			t.Fatal(e)
		}
	}
	return r, r.Parents[phase+"/core/1"]
}

// auditSourceCloseR2159 は元Sourceの所有IDへ指定枚数の返済判断を作ります。
//
// 引数: p(*AllocationParent157)、q(int)、index(int64)、at(float64)。返り値: strategy.Signalです。
func auditSourceCloseR2159(p *AllocationParent157, q int, index int64, at float64) strategy.Signal {
	return strategy.Signal{ID: "source-close", Owner: p.Owner, Campaign: p.Campaign, Action: "close", Side: -p.Side,
		Quantity: q, SourceIndex: index, Time: at, Targets: []strategy.LotTarget{{ID: "後半/seed-玉", Quantity: q}}}
}

// auditPendingR2159 は親の返済予約数を集計します。
//
// 引数: b(*Ledger157)、parent(string)。返り値: intは現在保有とは別の予約です。
func auditPendingR2159(b *Ledger157, parent string) int {
	n := 0
	for _, order := range b.Pending {
		if order.Parent == parent && len(order.Targets) > 0 {
			n += order.Quantity
		}
	}
	return n
}

// TestAuditR2UnknownAndBefore159 は未知初回の元量と前半基準量を上下両側で確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditR2UnknownAndBefore159(t *testing.T) {
	for _, side := range []int{-1, 1} {
		for _, c := range configsRound2159() {
			for _, phase := range []string{"前半", "後半"} {
				r, p := auditSeedR2159(t, c.ID, phase, side, false)
				l, s := r.Actual.position(p.Key, "")
				if l+s != 50 || p.InitialQty != 50 {
					t.Fatal("未知又は前半を勝手に減量", c.ID, phase, l, s, p.InitialQty)
				}
			}
		}
	}
}

// TestAuditR2ReservedSourceExit159 は更新済基準残30と元返済予約32を二重に返さないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditR2ReservedSourceExit159(t *testing.T) {
	for _, side := range []int{-1, 1} {
		r, p := auditSeedR2159(t, "R02", "後半", side, true)
		lot := r.Actual.Lots[r.Actual.Active[0]]
		if lot.Remaining != 80 {
			t.Fatal("初回80でない", lot.Remaining)
		}
		lot.Best = 80
		q := auditQuoteR2159(side, 2, 1002, 40)
		if e := stepPolicy159(r, q, []strategy.Signal{auditSourceCloseR2159(p, 2, 2, 1002)}, nil); e != nil {
			t.Fatal(e)
		}
		if p.SourceQty != 30 || auditPendingR2159(r.Actual, p.Key) != 50 || len(r.ExcessExits) != 1 || r.ExcessExits[0].Closed != 18 {
			t.Fatalf("基準/予約/追加保護不整合: %+v pending=%d exits=%+v", p, auditPendingR2159(r.Actual, p.Key), r.ExcessExits)
		}
		if e := stepPolicy159(r, auditQuoteR2159(side, 3, 1003, 30), nil, nil); e != nil {
			t.Fatal(e)
		}
		l, s := r.Actual.position(p.Key, "")
		if l+s != 30 {
			t.Fatal("基準残量未満まで返済", l, s)
		}
	}
}

// TestAuditR2ProtectionThenSourcePartial159 は超過利確後に旧初回比率の数量を戻さないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditR2ProtectionThenSourcePartial159(t *testing.T) {
	for _, side := range []int{-1, 1} {
		r, p := auditSeedR2159(t, "R01", "後半", side, true)
		if e := stepPolicy159(r, auditQuoteR2159(side, 2, 1002, 80), nil, nil); e != nil {
			t.Fatal(e)
		}
		if e := stepPolicy159(r, auditQuoteR2159(side, 3, 1003, 40), nil, nil); e != nil {
			t.Fatal(e)
		}
		if auditPendingR2159(r.Actual, p.Key) != 30 {
			t.Fatal("超過30だけでない")
		}
		if e := stepPolicy159(r, auditQuoteR2159(side, 4, 1004, 35), []strategy.Signal{auditSourceCloseR2159(p, 2, 4, 1004)}, nil); e != nil {
			t.Fatal(e)
		}
		if auditPendingR2159(r.Actual, p.Key) != 20 {
			t.Fatal("元部分退出が現残50の2/5でない", r.Actual.Pending)
		}
		if e := stepPolicy159(r, auditQuoteR2159(side, 5, 1005, 30), nil, nil); e != nil {
			t.Fatal(e)
		}
		l, s := r.Actual.position(p.Key, "")
		if l+s != 30 {
			t.Fatal("元残30と異なる")
		}
		if e := stepPolicy159(r, auditQuoteR2159(side, 6, 1006, 25), []strategy.Signal{auditSourceCloseR2159(p, 3, 6, 1006)}, nil); e != nil {
			t.Fatal(e)
		}
		if e := stepPolicy159(r, auditQuoteR2159(side, 7, 1007, 20), nil, nil); e != nil {
			t.Fatal(e)
		}
		if !p.Finished || len(r.Actual.Active) != 0 || len(r.Actual.Pending) != 0 {
			t.Fatal("元完済後の残玉")
		}
	}
}

// TestAuditR2FreeBudgetAndNewest159 は既予約と別親を除外し新玉から超過を割り当てます。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditR2FreeBudgetAndNewest159(t *testing.T) {
	b := newLedger157("audit", 100)
	p := &AllocationParent157{Key: "後半/core/1", SourceQty: 50}
	b.Active = []string{"old", "new", "foreign"}
	b.Lots["old"] = &Lot157{ID: "old", Parent: p.Key, Remaining: 50, EntryIndex: 1}
	b.Lots["new"] = &Lot157{ID: "new", Parent: p.Key, Remaining: 30, EntryIndex: 2}
	b.Lots["foreign"] = &Lot157{ID: "foreign", Parent: "後半/addon/1", Remaining: 20, EntryIndex: 3}
	b.Pending = []Order157{{Targets: []Target157{{ID: "new", Quantity: 15}}}}
	slices, free, extra := excessSlices159(b, p)
	if free != 65 || extra != 15 || len(slices) != 1 || slices[0].ID != "new" || slices[0].Quantity != 15 {
		t.Fatal("予約か別親を超過へ混入", slices, free, extra)
	}
}

// TestAuditR2ThresholdAndGap159 は開始40/80の差と次原行での負約定を確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditR2ThresholdAndGap159(t *testing.T) {
	for _, side := range []int{-1, 1} {
		for _, id := range []string{"R00", "R01", "R02"} {
			r, p := auditSeedR2159(t, id, "後半", side, true)
			if e := stepPolicy159(r, auditQuoteR2159(side, 2, 1002, 40), nil, nil); e != nil {
				t.Fatal(e)
			}
			if e := stepPolicy159(r, auditQuoteR2159(side, 3, 1003, 0), nil, nil); e != nil {
				t.Fatal(e)
			}
			want := 0
			if id == "R01" {
				want = 30
			}
			if got := auditPendingR2159(r.Actual, p.Key); got != want {
				t.Fatal(id, got, want)
			}
			if e := stepPolicy159(r, auditQuoteR2159(side, 4, 1004, -100), nil, nil); e != nil {
				t.Fatal(e)
			}
			if id == "R01" && math.Abs(r.Actual.Realized+30000) > 1e-8 {
				t.Fatal("床約定を保証した", r.Actual.Realized)
			}
		}
	}
}

// TestAuditR2OppositeClock159 は逆行だけで基準玉を返さず未知や観測空白で時計を解除します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditR2OppositeClock159(t *testing.T) {
	for _, side := range []int{-1, 1} {
		r, p := auditSeedR2159(t, "R03", "後半", side, true)
		ss := map[int]Support157{side: {Known: true, Opp: .5, Own15: -float64(side), Own5: -float64(side)}}
		for i := int64(2); i <= 6; i++ {
			if e := stepPolicy159(r, auditQuoteR2159(side, i, 1000+float64(i), -80), nil, ss); e != nil {
				t.Fatal(e)
			}
		}
		if auditPendingR2159(r.Actual, p.Key) != 0 {
			t.Fatal("5秒未満で防御")
		}
		if e := stepPolicy159(r, auditQuoteR2159(side, 7, 1007, -80), nil, nil); e != nil {
			t.Fatal(e)
		}
		if e := stepPolicy159(r, auditQuoteR2159(side, 8, 1008, -80), nil, ss); e != nil {
			t.Fatal(e)
		}
		if e := stepPolicy159(r, auditQuoteR2159(side, 9, 1020, -80), nil, ss); e != nil {
			t.Fatal(e)
		}
		if auditPendingR2159(r.Actual, p.Key) != 0 {
			t.Fatal("欠測区間を継続にした")
		}
		for i := int64(10); i <= 14; i++ {
			if e := stepPolicy159(r, auditQuoteR2159(side, i, 1020+float64(i-9), -80), nil, ss); e != nil {
				t.Fatal(e)
			}
		}
		if auditPendingR2159(r.Actual, p.Key) != 30 || len(r.ExcessExits) != 1 {
			t.Fatal("超過30防御でない", r.Actual.Pending)
		}
		if e := stepPolicy159(r, auditQuoteR2159(side, 15, 1026, -110), nil, ss); e != nil {
			t.Fatal(e)
		}
		l, s := r.Actual.position(p.Key, "")
		if l+s != 50 || r.Actual.Realized != -33000 {
			t.Fatal("基準量又は飛び損失不一致", l, s, r.Actual.Realized)
		}
	}
}
