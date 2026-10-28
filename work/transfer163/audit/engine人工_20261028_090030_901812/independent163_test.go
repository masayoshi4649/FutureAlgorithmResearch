package main

import (
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
	"testing"
)

// iq163 は外部資料を使わず中値と気配差10円の人工板を作ります。
//
// 引数: i(int64)、at/mid(float64)。返り値: strategy.Observation。
func iq163(i int64, at, mid float64) strategy.Observation {
	return strategy.Observation{Reference: "NK225", Index: i, Time: at, Received: at, Last: mid, Bid: mid - 5, Ask: mid + 5, QuoteOK: true}
}

// ic163 は固定した候補を識別子で選びます。
//
// 引数: id(string)。返り値: Policy163。未定義なら人工不整合として停止します。
func ic163(id string) Policy163 {
	for _, c := range configs163() {
		if c.ID == id {
			return c
		}
	}
	panic("候補がありません")
}

// is163 は単位が円の短期既知値を作ります。
//
// 引数: five/fifteen(float64)。返り値: Short163。
func is163(five, fifteen float64) Short163 {
	return Short163{Own5: ShortWindow163{Known: true, Points: five}, Own15: ShortWindow163{Known: true, Points: fifteen}}
}

// in163 は同じ親に属する元Source新規を作ります。
//
// 引数: o(Observation)、id(string)、side/q(int)。返り値: strategy.Signal。
func in163(o strategy.Observation, id string, side, q int) strategy.Signal {
	return strategy.Signal{ID: id, Owner: "日中/core", Campaign: 1, Action: "new", Side: side, Quantity: q, SourceIndex: o.Index, Time: o.Time}
}

// ix163 は元SourceIDを指定して返済通知を作ります。
//
// 引数: o(Observation)、id/source(string)、side/q(int)。返り値: strategy.Signal。
func ix163(o strategy.Observation, id, source string, side, q int) strategy.Signal {
	return strategy.Signal{ID: id, Owner: "日中/core", Campaign: 1, Action: "close", Side: -side, Quantity: q, SourceIndex: o.Index, Time: o.Time, Targets: []strategy.LotTarget{{ID: source + "-玉", Quantity: q}}}
}

// stepI163 は人工の現在行と元通知を一回だけ渡します。
//
// 引数: t(*testing.T)、r(*TransferResult163)、o(Observation)、short(Short163)、allow(bool)、signals(...Signal)。返り値: なし。
func stepI163(t *testing.T, r *TransferResult163, o strategy.Observation, short Short163, allow bool, signals ...strategy.Signal) {
	t.Helper()
	if err := r.stepTransfer163(o, signals, short, allow); err != nil {
		t.Fatal(err)
	}
}

// parentI163 は人工の親を取得します。
//
// 引数: r(*TransferResult163)。返り値: *TransferParent163。
func parentI163(r *TransferResult163) *TransferParent163 { return r.Parents["日中/core/1"] }

// assertScaleI163 は数量と金額の経路が厳密半分であるか検査します。
//
// 引数: t(*testing.T)、a/b(*TransferResult163)。返り値: なし。
func assertScaleI163(t *testing.T, a, b *TransferResult163) {
	t.Helper()
	x, y := a.Actual, b.Actual
	for key, pair := range map[string][2]float64{
		"確定": {x.Realized, y.Realized}, "含み": {x.Last.Unrealized, y.Last.Unrealized},
		"時価": {x.Last.Equity, y.Last.Equity}, "最低": {x.Risk.Minimum, y.Risk.Minimum},
		"下落": {x.Risk.MaxDD, y.Risk.MaxDD}, "量秒": {x.Risk.GrossSeconds, y.Risk.GrossSeconds},
	} {
		if math.Abs(pair[0]-2*pair[1]) > 1e-8 {
			t.Fatalf("%sの半量不一致:%v", key, pair)
		}
	}
	if x.Last.Long != 2*y.Last.Long || x.Last.Short != 2*y.Last.Short || len(x.Events) != len(y.Events) {
		t.Fatal("数量又は通知数が半量と異なります")
	}
	for i := range x.Events {
		p, q := x.Events[i], y.Events[i]
		if p.FillIndex != q.FillIndex || p.Price != q.Price || p.Order.Quantity != 2*q.Order.Quantity || math.Abs(p.Gross-2*q.Gross) > 1e-8 || len(p.Pieces) != len(q.Pieces) {
			t.Fatalf("約定%dの半量不一致", i)
		}
		for j := range p.Pieces {
			if p.Pieces[j].ID != q.Pieces[j].ID || p.Pieces[j].Quantity != 2*q.Pieces[j].Quantity {
				t.Fatal("同じSourceIDへの返済配賦が変わりました")
			}
		}
	}
}

// TestIndependentExactHalf163 は初回・追加・複数ID部分返済の全経路を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependentExactHalf163(t *testing.T) {
	a, b := newTransfer163(ic163("B00"), Scene{Start: 100}), newTransfer163(ic163("C50"), Scene{Start: 100})
	for i, mid := range []float64{1000, 1000, 1040, 1030, 980, 960, 990, 1080, 1100, 1090} {
		o := iq163(int64(i), 100+float64(i), mid)
		signals := []strategy.Signal{}
		switch i {
		case 0:
			signals = append(signals, in163(o, "S1", 1, 5))
		case 2:
			signals = append(signals, in163(o, "S2", 1, 3))
		case 4:
			signals = append(signals, ix163(o, "C1", "S2", 1, 1))
		case 6:
			signals = append(signals, ix163(o, "C2", "S1", 1, 2))
		case 8:
			x := ix163(o, "C3", "S1", 1, 3)
			x.Quantity += 2
			x.Targets = append(x.Targets, strategy.LotTarget{ID: "S2-玉", Quantity: 2})
			signals = append(signals, x)
		}
		stepI163(t, a, o, Short163{}, true, signals...)
		stepI163(t, b, o, Short163{}, true, signals...)
		assertScaleI163(t, a, b)
	}
	if len(a.Actual.Active) != 0 || !parentI163(a).Ended {
		t.Fatal("全返済後に実玉が残りました")
	}
}

// TestIndependentEndpointUnits163 は円単位・実時間換算・1秒境界・不正板を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependentEndpointUnits163(t *testing.T) {
	b := &ShortBuilder163{}
	for _, row := range []struct{ at, mid float64 }{{0, 1000}, {9, 1090}, {15, 1150}} {
		b.add(iq163(int64(len(b.Rows)), row.at, row.mid))
	}
	s := b.get()
	if !s.Own5.Known || s.Own5.Delay != 1 || s.Own5.RawPoints != 60 || s.Own5.Points != 50 || !s.Own15.Known || s.Own15.Points != 150 {
		t.Fatalf("bp又は不正な時間換算:%+v", s)
	}
	b.add(iq163(3, 15.01, 1150))
	if b.get().Own5.Known {
		t.Fatal("1秒を超えた過去端を認めました")
	}
	bad := iq163(4, 16, 1160)
	bad.QuoteOK = false
	b.add(bad)
	if b.get().Own5.Known || b.get().Own15.Known {
		t.Fatal("異常な現在板を既知としました")
	}
}

// TestIndependentUnknownDoesNotReduce163 は未知を0へ補完しないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependentUnknownDoesNotReduce163(t *testing.T) {
	for _, id := range []string{"D40", "G40"} {
		r := newTransfer163(ic163(id), Scene{Start: 100})
		stepI163(t, r, iq163(0, 100, 1000), Short163{}, true, in163(iq163(0, 100, 1000), "S1", 1, 5))
		stepI163(t, r, iq163(1, 101, 1000), Short163{}, true)
		stepI163(t, r, iq163(2, 102, 950), Short163{}, true)
		if parentI163(r).Reduced != (id == "D40") {
			t.Fatalf("未知の処理不一致:%s", id)
		}
	}
}

// TestIndependentOneReductionRestoration163 は売買鏡像で各一回・次原行・極値を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependentOneReductionRestoration163(t *testing.T) {
	for _, side := range []int{1, -1} {
		r := newTransfer163(ic163("R40"), Scene{Start: 100})
		path := []float64{1000, 1000, 955, 930, 970, 980, 900, 1000}
		for i, p := range path {
			mid := 1000 + float64(side)*(p-1000)
			o := iq163(int64(i), 100+float64(i), mid)
			short := is163(float64(side)*10, float64(side)*30)
			if i <= 3 {
				short = is163(float64(side)*-10, float64(side)*-30)
			}
			signals := []strategy.Signal{}
			if i == 0 {
				signals = append(signals, in163(o, "S1", side, 5))
			}
			stepI163(t, r, o, short, true, signals...)
			if i == 2 && len(r.Actual.Events) != 1 {
				t.Fatal("減量が判断行で約定しました")
			}
		}
		p := parentI163(r)
		if p.AnchorMid != 1000 || p.ReductionOrderIndex != 2 || p.ReductionFillIndex != 3 || p.RestorationOrderIndex != 4 || !p.Reduced || !p.Restored || len(r.Decisions) != 2 {
			t.Fatalf("一回の減量復元又は中値固定に違反:%+v", p)
		}
		held, pending, _ := r.sourceHeld163(p, "S1")
		if held != 50 || pending != 0 || r.Actual.Events[2].FillIndex != 5 {
			t.Fatal("復元時刻/数量不整合")
		}
	}
}

// TestIndependentPartialThenRestore163 は現在Source残数だけを復元するか検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependentPartialThenRestore163(t *testing.T) {
	r := newTransfer163(ic163("R40"), Scene{Start: 100})
	for i, mid := range []float64{1000, 1000, 950, 920, 930, 940, 970, 980} {
		o := iq163(int64(i), 100+float64(i), mid)
		ss := []strategy.Signal{}
		if i == 0 {
			ss = append(ss, in163(o, "S1", 1, 5))
		}
		if i == 4 {
			ss = append(ss, ix163(o, "C1", "S1", 1, 2))
		}
		short := is163(-10, -30)
		if i >= 4 {
			short = is163(10, 30)
		}
		stepI163(t, r, o, short, true, ss...)
	}
	p := parentI163(r)
	held, _, _ := r.sourceHeld163(p, "S1")
	if held != 30 || p.SourceMini["S1"] != 3 || !p.Restored {
		t.Fatalf("終了分を復元:%d %+v", held, p)
	}
	if len(r.Decisions) != 2 || r.Decisions[1].Quantity != 15 {
		t.Fatal("復元は15microだけです")
	}
}

// TestIndependentClosePriority163 は全返済・静観中に復元が出ないか検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependentClosePriority163(t *testing.T) {
	for _, closeAll := range []bool{false, true} {
		r := newTransfer163(ic163("R40"), Scene{Start: 100})
		for i, mid := range []float64{1000, 1000, 950, 920, 1000, 1010} {
			o := iq163(int64(i), 100+float64(i), mid)
			ss := []strategy.Signal{}
			if i == 0 {
				ss = append(ss, in163(o, "S1", 1, 5))
			}
			if i == 4 && closeAll {
				ss = append(ss, ix163(o, "C1", "S1", 1, 5))
			}
			short := is163(-10, -30)
			if i >= 4 {
				short = is163(10, 30)
			}
			stepI163(t, r, o, short, closeAll, ss...)
		}
		if parentI163(r).Restored || len(r.Decisions) != 1 {
			t.Fatal("静観又は元全返済より復元を優先しました")
		}
	}
}

// TestIndependentLaterSourceSameParent163 は実玉ゼロ後の同親新SourceIDを検査します。
//
// 引数: t(*testing.T)。返り値: なし。同親の基準は維持し、終了済みIDを復活させません。
func TestIndependentLaterSourceSameParent163(t *testing.T) {
	r := newTransfer163(ic163("D40"), Scene{Start: 100})
	for i, mid := range []float64{1000, 1000, 1030, 1030, 950, 950, 940} {
		o := iq163(int64(i), 100+float64(i), mid)
		ss := []strategy.Signal{}
		if i == 0 {
			ss = append(ss, in163(o, "S1", 1, 5))
		}
		if i == 2 {
			ss = append(ss, ix163(o, "C1", "S1", 1, 5))
		}
		if i == 4 {
			ss = append(ss, in163(o, "S2", 1, 2))
		}
		stepI163(t, r, o, Short163{}, true, ss...)
	}
	p := parentI163(r)
	old, _, _ := r.sourceHeld163(p, "S1")
	current, _, _ := r.sourceHeld163(p, "S2")
	if p.Ended || !p.Reduced || old != 0 || current != 10 || p.AnchorMid != 1000 {
		t.Fatalf("同親の新しい源玉を永久停止しました:%+v q=%d", p, current)
	}
}

// TestIndependentReducedNewSource163 は縮小中の追加とID別返済を確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependentReducedNewSource163(t *testing.T) {
	r := newTransfer163(ic163("D40"), Scene{Start: 100})
	for i, mid := range []float64{1000, 1000, 950, 940, 970, 980, 1010, 1020} {
		o := iq163(int64(i), 100+float64(i), mid)
		ss := []strategy.Signal{}
		if i == 0 {
			ss = append(ss, in163(o, "S1", 1, 5))
		}
		if i == 4 {
			ss = append(ss, in163(o, "S2", 1, 3))
		}
		if i == 6 {
			ss = append(ss, ix163(o, "C1", "S1", 1, 5))
		}
		stepI163(t, r, o, Short163{}, true, ss...)
	}
	p := parentI163(r)
	a, _, _ := r.sourceHeld163(p, "S1")
	b, _, _ := r.sourceHeld163(p, "S2")
	if a != 0 || b != 15 || p.AnchorMid != 1000 || len(r.Decisions) != 1 {
		t.Fatalf("縮小中の追加又はID返済不一致:%d/%d", a, b)
	}
}

// TestIndependentEntryRestore163 は初回中値回復と極値回復を区別します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependentEntryRestore163(t *testing.T) {
	r := newTransfer163(ic163("E40"), Scene{Start: 100})
	for i, mid := range []float64{1000, 1000, 950, 920, 970, 999, 1000, 1010} {
		o := iq163(int64(i), 100+float64(i), mid)
		ss := []strategy.Signal{}
		if i == 0 {
			ss = append(ss, in163(o, "S1", 1, 5))
		}
		short := is163(-10, -30)
		if i >= 4 {
			short = is163(10, 30)
		}
		stepI163(t, r, o, short, true, ss...)
		if i < 6 && parentI163(r).Restored {
			t.Fatal("初回中値前にEが復元しました")
		}
	}
	if parentI163(r).RestorationOrderIndex != 6 || r.Actual.Events[len(r.Actual.Events)-1].FillIndex != 7 {
		t.Fatal("中値接触又は次原行約定の不一致")
	}
}

// TestIndependentBothSideCapacity163 は反対側を独立に許し、返済予約を余枠にしないか確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependentBothSideCapacity163(t *testing.T) {
	r := newTransfer163(ic163("B00"), Scene{Start: 100})
	o := iq163(0, 100, 1000)
	a, b := in163(o, "買", 1, 10), in163(o, "売", -1, 10)
	b.Owner, b.Campaign = "日中/episode", 2
	stepI163(t, r, o, Short163{}, true, a, b)
	if len(r.Actual.Pending) != 2 || r.Actual.capacity(1) != 0 || r.Actual.capacity(-1) != 0 {
		t.Fatal("反対側の100枚を受け付けませんでした")
	}
	stepI163(t, r, iq163(1, 101, 1000), Short163{}, true)
	if r.Actual.Last.Long != 100 || r.Actual.Last.Short != 100 || r.Actual.Last.Equity != -20000 {
		t.Fatal("両側全玉のBBO評価が不正です")
	}
	o = iq163(2, 102, 1000)
	stepI163(t, r, o, Short163{}, true, ix163(o, "返済", "買", 1, 5))
	if r.Actual.capacity(1) != 0 {
		t.Fatal("返済予約だけで空き枠を得ました")
	}
	stepI163(t, r, iq163(3, 103, 1000), Short163{}, true)
	if r.Actual.capacity(1) != 50 {
		t.Fatal("返済実約定後の余枠が不正です")
	}
}

// TestIndependentBadQuoteAndSameClock163 は同秒後続と異常板飛越しを区別します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependentBadQuoteAndSameClock163(t *testing.T) {
	r := newTransfer163(ic163("B00"), Scene{Start: 100})
	o := iq163(0, 100, 1000)
	stepI163(t, r, o, Short163{}, true, in163(o, "S1", 1, 5))
	bad := iq163(1, 100, 9999)
	bad.QuoteOK = false
	stepI163(t, r, bad, Short163{}, true)
	if len(r.Actual.Events) != 0 || len(r.Actual.Pending) != 1 {
		t.Fatal("異常板で約定しました")
	}
	stepI163(t, r, iq163(2, 100, 1020), Short163{}, true)
	if len(r.Actual.Events) != 1 || r.Actual.Events[0].Price != 1025 || r.Actual.Events[0].FillIndex != 2 {
		t.Fatal("同秒後続の次正常板へ約定を進めませんでした")
	}
}
