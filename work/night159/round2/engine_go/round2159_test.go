package main

import (
	"futurealgorithm/sessiontrader/internal/strategy"
	"testing"
)

// seedRound2159 はSource50micro相当から支持で実80microとなる人工親を作ります。
//
// 引数: t(*testing.T)、id(string)。返り値: *PolicyResult157です。
func seedRound2159(t *testing.T, id string) *PolicyResult157 {
	t.Helper()
	var cfg Policy157
	for _, c := range configsRound2159() {
		if c.ID == id {
			cfg = c
		}
	}
	r := newPolicy157(cfg, Scene{Start: 100, ForceClose: 10000, End: 10100, Kind: "Night"})
	ss := map[int]Support157{1: {Known: true, M: 1, T: 7.0 / 9, Own5: 1, Own15: 1}}
	sig := strategy.Signal{ID: "後半/seed", Owner: "後半/core", Campaign: 1, Action: "new", Side: 1, Quantity: 5, Time: 100, SourceIndex: 0}
	if e := stepPolicy159(r, quote159(0, 100, 999, 1001), []strategy.Signal{sig}, ss); e != nil {
		t.Fatal(e)
	}
	if e := stepPolicy159(r, quote159(1, 101, 999, 1001), nil, ss); e != nil {
		t.Fatal(e)
	}
	if a, _ := r.Actual.position("", ""); a != 80 {
		t.Fatalf("人工初回%d", a)
	}
	return r
}

// TestUnknownUsesSourceQuantityRound2159 は未知と低支持を区別し、未知初回だけ元量へ戻します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestUnknownUsesSourceQuantityRound2159(t *testing.T) {
	for _, known := range []bool{false, true} {
		r := newPolicy157(configsRound2159()[0], Scene{Start: 100, ForceClose: 10000})
		ss := map[int]Support157{1: {Known: known}}
		sig := strategy.Signal{ID: "後半/new", Owner: "後半/core", Campaign: 1, Action: "new", Side: 1, Quantity: 5, Time: 100, SourceIndex: 0}
		if e := stepPolicy159(r, quote159(0, 100, 999, 1001), []strategy.Signal{sig}, ss); e != nil {
			t.Fatal(e)
		}
		want := 50
		if known {
			want = 10
		}
		if r.Canonical.Pending[0].Quantity != want {
			t.Fatalf("未知%vの量%d", !known, r.Canonical.Pending[0].Quantity)
		}
	}
}

// TestExcessPartialAndSourcePartialRound2159 は超過30を閉じた後の元2/5返済が20となることを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestExcessPartialAndSourcePartialRound2159(t *testing.T) {
	r := seedRound2159(t, "R01")
	ss := support159()
	for i, price := range []float64{1101, 1061, 1051} {
		if e := stepPolicy159(r, quote159(int64(i+2), 102+float64(i), price, price+2), nil, ss); e != nil {
			t.Fatal(e)
		}
	}
	if a, _ := r.Actual.position("", ""); a != 50 || len(r.ExcessExits) != 1 || r.ExcessExits[0].Closed != 30 {
		t.Fatal("超過のみを閉じていない")
	}
	close := strategy.Signal{ID: "後半/source-close", Owner: "後半/core", Campaign: 1, Action: "close", Side: -1, Quantity: 2, Time: 105, SourceIndex: 5, Targets: []strategy.LotTarget{{ID: "後半/seed-玉", Quantity: 2}}}
	if e := stepPolicy159(r, quote159(5, 105, 1051, 1053), []strategy.Signal{close}, ss); e != nil {
		t.Fatal(e)
	}
	if len(r.Canonical.Pending) != 1 || r.Canonical.Pending[0].Quantity != 20 {
		t.Fatal("Source部分返済が旧初回係数へ戻った")
	}
	if e := stepPolicy159(r, quote159(6, 106, 1051, 1053), nil, ss); e != nil {
		t.Fatal(e)
	}
	if a, _ := r.Actual.position("", ""); a != 30 || r.Parents["後半/core/1"].SourceQty != 30 {
		t.Fatal("残30の基準と不一致")
	}
}

// TestSourceReservationAndExcessRound2159 は同原行のSource32予約と更新基準30を引き18だけを保護します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestSourceReservationAndExcessRound2159(t *testing.T) {
	r := seedRound2159(t, "R01")
	if e := stepPolicy159(r, quote159(2, 102, 1101, 1103), nil, support159()); e != nil {
		t.Fatal(e)
	}
	close := strategy.Signal{ID: "後半/source-close", Owner: "後半/core", Campaign: 1, Action: "close", Side: -1, Quantity: 2, Time: 103, SourceIndex: 3, Targets: []strategy.LotTarget{{ID: "後半/seed-玉", Quantity: 2}}}
	if e := stepPolicy159(r, quote159(3, 103, 1061, 1063), []strategy.Signal{close}, support159()); e != nil {
		t.Fatal(e)
	}
	if len(r.Canonical.Pending) != 2 || r.Canonical.Pending[0].Quantity != 32 || r.Canonical.Pending[1].Quantity != 18 {
		t.Fatalf("Source優先と超過18の予約 %+v", r.Canonical.Pending)
	}
	if r.ExcessExits[0].SourceRemaining != 30 || r.ExcessExits[0].FreeRemaining != 48 {
		t.Fatal("超過計算の証跡不正")
	}
}

// TestNewestAllocationAndReservationRound2159 は追加玉優先・既予約・再保護の上限を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestNewestAllocationAndReservationRound2159(t *testing.T) {
	r := seedRound2159(t, "R01")
	p := r.Parents["後半/core/1"]
	id := r.Canonical.Active[0]
	r.Canonical.closeLot(p, quote159(2, 102, 1050, 1052), id, "人工予約", 15, support159()[1])
	slices, free, excess := excessSlices159(r.Canonical, p)
	if free != 65 || excess != 15 || len(slices) != 1 || slices[0].Quantity != 15 {
		t.Fatal("予約控除不正")
	}
	r.Canonical.Pending = nil
	add := strategy.Signal{ID: "後半/add", Owner: "後半/core", Campaign: 1, Action: "new", Side: 1, Quantity: 1, Time: 102, SourceIndex: 2}
	if e := stepPolicy159(r, quote159(2, 102, 999, 1001), []strategy.Signal{add}, support159()); e != nil {
		t.Fatal(e)
	}
	if e := stepPolicy159(r, quote159(3, 103, 999, 1001), nil, support159()); e != nil {
		t.Fatal(e)
	}
	slices, free, excess = excessSlices159(r.Canonical, p)
	if free != 96 || excess != 36 || len(slices) != 2 || slices[0].Quantity != 16 || slices[1].Quantity != 20 {
		t.Fatalf("新玉優先配賦 %+v %d %d", slices, free, excess)
	}
	for _, slice := range slices {
		r.Canonical.closeLot(p, quote159(4, 104, 1050, 1052), slice.ID, "人工超過返済", slice.Quantity, support159()[1])
	}
	if e := stepPolicy159(r, quote159(5, 105, 1050, 1052), nil, support159()); e != nil {
		t.Fatal(e)
	}
	close := strategy.Signal{ID: "後半/source-close", Owner: "後半/core", Campaign: 1, Action: "close", Side: -1, Quantity: 2, Time: 106, SourceIndex: 6, Targets: []strategy.LotTarget{{ID: "後半/seed-玉", Quantity: 2}}}
	if e := stepPolicy159(r, quote159(6, 106, 1050, 1052), []strategy.Signal{close}, support159()); e != nil {
		t.Fatal(e)
	}
	if e := stepPolicy159(r, quote159(7, 107, 1050, 1052), nil, support159()); e != nil {
		t.Fatal(e)
	}
	a, _ := r.Actual.position("", "")
	if a != 36 || p.SourceQty != 40 {
		t.Fatalf("既存Source部分退出の限界を隠した %d/%d", a, p.SourceQty)
	}
}

// TestExcessStopAndGapRound2159 は後半の反対支持継続時も80逆行玉の超過30だけを返済します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestExcessStopAndGapRound2159(t *testing.T) {
	r := seedRound2159(t, "R03")
	ss := map[int]Support157{1: {Known: true, Opp: .8, Own5: -1, Own15: -1}}
	for i, at := range []float64{102, 104, 106, 107} {
		if e := stepPolicy159(r, quote159(int64(i+2), at, 900, 902), nil, ss); e != nil {
			t.Fatal(e)
		}
	}
	if len(r.Canonical.Pending) != 1 || r.Canonical.Pending[0].Quantity != 30 {
		t.Fatal("逆行防御が基準分まで閉じた")
	}
	if e := stepPolicy159(r, quote159(6, 108, 880, 882), nil, ss); e != nil {
		t.Fatal(e)
	}
	if a, _ := r.Actual.position("", ""); a != 50 || r.Actual.Realized != -36300 {
		t.Fatal("次板の悪化又は基準50を隠した")
	}
}
