package main

import (
	"futurealgorithm/sessiontrader/internal/strategy"
	"testing"
)

// TestIndependentFlatExtremeCorrected163 は空玉区間の安値/高値を後続同親へ保つか確認します。
//
// 引数: t(*testing.T)。返り値: なし。終了IDを復活させず、新IDの元残数だけを復元します。
func TestIndependentFlatExtremeCorrected163(t *testing.T) {
	for _, side := range []int{1, -1} {
		r := newTransfer163(ic163("R40"), Scene{Start: 100})
		for i, value := range []float64{1000, 1000, 950, 920, 920, 900, 800, 850, 850, 850, 850} {
			mid := 1000 + float64(side)*(value-1000)
			o := iq163(int64(i), 100+float64(i), mid)
			short := is163(float64(side)*-10, float64(side)*-30)
			if i >= 7 {
				short = is163(float64(side)*10, float64(side)*30)
			}
			ss := []strategy.Signal{}
			if i == 0 {
				ss = append(ss, in163(o, "S1", side, 5))
			}
			if i == 4 {
				ss = append(ss, ix163(o, "C1", "S1", side, 5))
			}
			if i == 8 {
				ss = append(ss, in163(o, "S2", side, 2))
			}
			stepI163(t, r, o, short, true, ss...)
			p := parentI163(r)
			if i == 6 && (p.ExtremeMid != 1000-float64(side)*200 || !p.Ended) {
				t.Fatal("空玉中に極値の追跡が止まりました")
			}
			if i == 7 && (p.Restored || len(r.Actual.Pending) != 0 || len(r.Actual.Active) != 0) {
				t.Fatal("元玉がないのに復元しました")
			}
			if i == 8 && (p.Restored || len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Quantity != 10) {
				t.Fatal("後続新IDの半量又は予約優先が変わりました")
			}
		}
		p := parentI163(r)
		old, _, _ := r.sourceHeld163(p, "S1")
		current, _, _ := r.sourceHeld163(p, "S2")
		if p.AnchorMid != 1000 || p.ReductionOrderIndex != 2 || p.RestorationOrderIndex != 9 || old != 0 || current != 20 || len(r.Decisions) != 2 {
			t.Fatalf("同親の基準/権利又は現在SourceID残数を破りました:%+v old=%d current=%d", p, old, current)
		}
	}
}
