package main

import (
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
	"reflect"
	"testing"
)

// TestElapsedEndpoint1572 は実経過換算・正常過去端・未来端除外・15秒境界を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestElapsedEndpoint1572(t *testing.T) {
	rows := []supportRow157{{Time: 100, Mid: 1000, Valid: true}, {Time: 110, Valid: false, Bad: 1}, {Time: 115, Valid: false, Bad: 2}, {Time: 119, Mid: 1019, Valid: true, Bad: 2}, {Time: 120, Mid: 1020, Valid: true, Bad: 2}}
	w := elapsedReturn1572(rows, 4, 5, true)
	if !w.Known || w.EndpointAt != 100 || w.Elapsed != 20 || w.Delay != 15 || math.Abs(w.Value-50) > 1e-7 || w.IntermediateBad != 2 {
		t.Fatal(w)
	}
	rows[4].Time = 120.001
	if elapsedReturn1572(rows, 4, 5, true).Known {
		t.Fatal("15秒超を採用")
	}
	long := elapsedReturn1572([]supportRow157{{Time: 100, Mid: 1000, Valid: true}, {Time: 235, Mid: 1020, Valid: true}}, 1, 120, false)
	if !long.Known || long.Elapsed != 135 || math.Abs(long.Value-200) > 1e-7 {
		t.Fatal("長期を速度に変えた", long)
	}
}

// syntheticSupport1572 は実原板を使わない秒時計の人工支持系列を作ります。
//
// 引数: peer/quantity(bool)、side(int)。返り値: *SupportBuilder157。
func syntheticSupport1572(peer, quantity bool, side int) *SupportBuilder157 {
	f := &SupportBuilder157{}
	for at := 0; at <= 340; at++ {
		mid := 10000 + float64(side*at)*10
		q := 0.
		if quantity {
			q = 10
		}
		if peer {
			f.add(strategy.Board{Reference: "TOPIX", Time: float64(at), Bid: mid - 1, Ask: mid + 1, BidQuantity: q, AskQuantity: q})
		}
		f.add(strategy.Board{Reference: "NK225", Time: float64(at), Bid: mid - 1, Ask: mid + 1, BidQuantity: q, AskQuantity: q})
	}
	return f
}

// TestOptionalComponents1572 は補助欠測が0寄与であり再正規化しないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestOptionalComponents1572(t *testing.T) {
	for _, side := range []int{1, -1} {
		a := syntheticSupport1572(false, false, side).get(340, side)
		if !a.Known || !a.Components.OwnKnown || a.Components.PeerKnown || a.Components.OFIKnown || math.Abs(a.M-.8) > 1e-8 || math.Abs(a.T-.8) > 1e-8 {
			t.Fatal(a)
		}
		b := syntheticSupport1572(true, false, side).get(340, side)
		if !b.Known || !b.Components.PeerKnown || b.Components.OFIKnown || math.Abs(b.M-1) > 1e-8 || math.Abs(b.T-.8) > 1e-8 {
			t.Fatal(b)
		}
		if b.PeerAt != 339 {
			t.Fatal("相手の同時計を採用", b.PeerAt)
		}
	}
}

// TestOwnUnknownAndFuture1572 は必須自己窓の不足と現在以後を使わないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestOwnUnknownAndFuture1572(t *testing.T) {
	f := syntheticSupport1572(true, true, 1)
	want := f.get(340, 1)
	f.add(strategy.Board{Reference: "TOPIX", Time: 341, Bid: 90000, Ask: 90010, BidQuantity: 10, AskQuantity: 10})
	if got := f.get(340, 1); !reflect.DeepEqual(want, got) {
		t.Fatal("未来相手が過去へ混入")
	}
	f.add(strategy.Board{Reference: "NK225", Time: 400, Bid: 14000, Ask: 14002, BidQuantity: 10, AskQuantity: 10})
	got := f.get(400, 1)
	if got.Known || got.Components.OwnKnown || got.Components.OwnReason == "" {
		t.Fatal(got)
	}
	f.add(strategy.Board{Reference: "NK225", Time: 401, Bid: 14000, Ask: 14000, BidQuantity: 10, AskQuantity: 10})
	if f.get(401, 1).Known {
		t.Fatal("現在不正板を採用")
	}
}

// TestMinimumAndFixedAmount1572 は未知・弱支持・強支持と数量式の境界を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestMinimumAndFixedAmount1572(t *testing.T) {
	for _, x := range []struct {
		id                  string
		unknown, half, full int
	}{{"J01", 5, 28, 100}, {"J02", 10, 32, 100}, {"J03", 20, 40, 100}, {"J15", 10, 15, 100}, {"K01", 10, 10, 10}, {"K02", 10, 10, 10}} {
		r := newPolicy157(policyBy157(x.id), Scene{Start: 100, ForceClose: 10000})
		if q := r.desired157(Support157{M: 1, T: 1}); q != x.unknown {
			t.Fatal(x.id, q)
		}
		if q := r.desired157(Support157{Known: true, M: .5, T: .5}); q != x.half {
			t.Fatal(x.id, q)
		}
		if q := r.desired157(Support157{Known: true, M: 1, T: 1}); q != x.full {
			t.Fatal(x.id, q)
		}
		o := sample157(0, 100, 999, 1001)
		if e := step157(r, o, []strategy.Signal{newSignal157("初回", "core", 1, 1, 5, o)}, nil); e != nil {
			t.Fatal(e)
		}
		if r.Parents["core/1"].InitialQty != x.unknown || r.Parents["core/1"].Rejected != "" {
			t.Fatal("未知初回の最低量", r.Parents)
		}
	}
}

// TestDScalesWholeMinimum1572 は最低量も場内抑制の対象となることを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestDScalesWholeMinimum1572(t *testing.T) {
	r := newPolicy157(policyBy157("J13"), Scene{Start: 100, ForceClose: 10000})
	r.Canonical.Last.Equity = -120000
	if r.desired157(Support157{}) != 5 || r.desired157(Support157{Known: true, M: .5, T: .5}) != 16 {
		t.Fatal("最低量を抑制しなかった")
	}
	r.Canonical.Last.Equity = -160000
	if r.desired157(Support157{}) != 0 {
		t.Fatal("場停止で最低量を強制")
	}
}

// TestMinimumDoesNotReleasePolicyUnknown1572 は未知初回の許可を独自追加やカバーへ拡張しません。
//
// 引数: t(*testing.T)。返り値: なし。
func TestMinimumDoesNotReleasePolicyUnknown1572(t *testing.T) {
	r := newPolicy157(policyBy157("J10"), Scene{Start: 100, ForceClose: 10000})
	o := sample157(0, 100, 999, 1001)
	if e := step157(r, o, []strategy.Signal{newSignal157("初回", "core", 1, 1, 5, o)}, nil); e != nil {
		t.Fatal(e)
	}
	if e := step157(r, sample157(1, 101, 999, 1001), nil, nil); e != nil {
		t.Fatal(e)
	}
	// ----------------------------------------
	// 支持未知のまま40pt以上動いても独自追加せず、元Source追加だけは係数写像します。
	if e := step157(r, sample157(2, 112, 1051, 1053), nil, nil); e != nil {
		t.Fatal(e)
	}
	if len(r.Canonical.Pending) != 0 {
		t.Fatal(r.Canonical.Pending)
	}
	o = sample157(3, 113, 1051, 1053)
	if e := step157(r, o, []strategy.Signal{newSignal157("源追加", "core", 1, 1, 1, o)}, nil); e != nil {
		t.Fatal(e)
	}
	if len(r.Canonical.Pending) != 1 || r.Canonical.Pending[0].Kind != "source_add" || r.Canonical.Pending[0].Quantity != 2 {
		t.Fatal(r.Canonical.Pending)
	}
}

// TestSourceExactUnaffected1572 は新しい補助情報をC00へ混ぜないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestSourceExactUnaffected1572(t *testing.T) {
	a := newPolicy157(policyBy157("C00"), Scene{Start: 100, ForceClose: 10000})
	b := newPolicy157(policyBy157("C00"), Scene{Start: 100, ForceClose: 10000})
	f := syntheticSupport1572(true, true, 1)
	for i := int64(0); i < 3; i++ {
		o := sample157(i, 100+float64(i), 999, 1001)
		var sig []strategy.Signal
		if i == 0 {
			sig = []strategy.Signal{newSignal157("初回", "core", 1, 1, 5, o)}
		}
		if e := step157(a, o, sig, nil); e != nil {
			t.Fatal(e)
		}
		if e := step157(b, o, sig, map[int]Support157{1: f.get(340, 1)}); e != nil {
			t.Fatal(e)
		}
	}
	if !reflect.DeepEqual(a, b) {
		t.Fatal("C00の経路が支持で変化")
	}
}
