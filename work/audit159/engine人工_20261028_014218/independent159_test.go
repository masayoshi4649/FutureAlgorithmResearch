package main

import (
	"futurealgorithm/sessiontrader/internal/rules"
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
	"reflect"
	"testing"
)

// independentQuote159 は実資料を参照しない人工気配を返します。
//
// 引数: i(int64)、at/bid/ask(float64)。返り値: strategy.Observationです。
func independentQuote159(i int64, at, bid, ask float64) strategy.Observation {
	return strategy.Observation{Reference: "NK225", Index: i, Time: at, Received: at, Last: (bid + ask) / 2, Bid: bid, Ask: ask, QuoteOK: true}
}

// independentConfig159 は固定候補をIDで参照します。
//
// 引数: id(string)。返り値: Policy157です。不存在は人工試験の不整合です。
func independentConfig159(id string) Policy157 {
	for _, c := range configs159() {
		if c.ID == id {
			return c
		}
	}
	panic("人工検査の候補がありません")
}

// independentSource159 は外部式を使用した人工Sourceを作ります。
//
// 引数: t(*testing.T)、kind/method/phase(string)。返り値: *SourceState159です。
func independentSource159(t *testing.T, kind, method, phase string) *SourceState159 {
	t.Helper()
	profile := map[string]string{"P05": "p05", "D07": "d07", "S01": "s01"}[method]
	set, err := rules.LoadFor("rules/NK225_"+method+".toml", profile)
	if err != nil {
		t.Fatal(err)
	}
	s, err := newSource159(Scene{Session: "人工_" + kind, Kind: kind, Start: 1000, USOpen: 20000, ForceClose: 47000, End: 48000}, phase, method, set.Expressions())
	if err != nil {
		t.Fatal(err)
	}
	return s
}

// TestIndependentRiskHedge159 は利確が増えても全玉含み損を加えた時価で悪化を残すか確認します。
//
// 引数: t(*testing.T)。返り値: なし。両建てを相殺した中値損益で置換しません。
func TestIndependentRiskHedge159(t *testing.T) {
	b := newLedger157("独立", 100)
	p1 := &AllocationParent157{Key: "買", Owner: "core", Side: 1}
	p2 := &AllocationParent157{Key: "売", Owner: "episode", Side: -1}
	o := independentQuote159(0, 100, 999, 1001)
	b.open(p1, o, "initial", "人工", 1, 10, Support157{})
	b.open(p2, o, "initial", "人工", -1, 10, Support157{})
	o = independentQuote159(1, 101, 999, 1001)
	b.mark(o)
	if _, err := b.fill(o); err != nil {
		t.Fatal(err)
	}
	if b.Last.Equity != -400 || b.Risk.Minimum != -400 || b.Risk.MaxGross != 20 {
		t.Fatalf("両側初期差 %+v", b.Last)
	}
	o = independentQuote159(2, 110, 1099, 1101)
	b.mark(o)
	b.closeQuantity(p1, o, "", "人工利確", 10, Support157{})
	o = independentQuote159(3, 111, 1099, 1101)
	b.mark(o)
	if _, err := b.fill(o); err != nil {
		t.Fatal(err)
	}
	if b.Realized != 9800 || b.Last.Unrealized != -10200 || b.Last.Equity != -400 {
		t.Fatalf("利確のみを利益にした %+v", b.Last)
	}
	b.mark(independentQuote159(4, 120, 1199, 1201))
	if b.Last.Equity != -10400 || b.Risk.MaxDD != 10400 || b.Risk.Minimum != -10400 || b.Risk.MinimumRealized != 0 {
		t.Fatalf("時価悪化を隠した %+v", b.Risk)
	}
	if b.Risk.GrossSeconds != 290 || b.Risk.HeldSeconds != 19 || b.Risk.HedgedSeconds != 10 {
		t.Fatalf("保有積分 %+v", b.Risk)
	}
}

// TestIndependentEveryFillMark159 は同原行の各新規直後の時価と同秒でも原行順の約定を確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependentEveryFillMark159(t *testing.T) {
	b := newLedger157("逐次", 100)
	p := &AllocationParent157{Key: "親", Side: 1}
	b.open(p, independentQuote159(0, 100, 99, 101), "initial", "人工", 1, 20, Support157{})
	b.open(p, independentQuote159(0, 100, 99, 101), "source_add", "人工", 1, 30, Support157{})
	if _, e := b.fill(independentQuote159(0, 100, 99, 101)); e == nil {
		t.Fatal("同一行約定を認めた")
	}
	if _, e := b.fill(independentQuote159(1, 100, 99, 101)); e != nil {
		t.Fatal(e)
	}
	if b.Risk.Minimum != -1000 || b.Risk.MinimumAt.Long != 50 || b.Risk.MaxDD != 1000 || b.Risk.GrossSeconds != 0 {
		t.Fatalf("同秒逐次時価 %+v", b.Risk)
	}
	if b.capacity(1) != 50 {
		t.Fatal("所有上限")
	}
	b.open(p, independentQuote159(1, 100, 99, 101), "source_add", "人工", 1, 80, Support157{})
	if b.capacity(1) != 0 || b.Pending[0].Quantity != 50 {
		t.Fatal("予約上限")
	}
}

// TestIndependentP05ParentMapping159 はP05返済が正しい親に届き元通知を変更しないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependentP05ParentMapping159(t *testing.T) {
	s := &SourceState159{Lots: map[string]*SourceLot159{"a": {Owner: "core", Campaign: 7}, "b": {Owner: "core", Campaign: 8}}}
	raw := strategy.Signal{Owner: "core", Campaign: 0, Action: "close", Targets: []strategy.LotTarget{{ID: "a", Quantity: 2}}}
	mapped, e := s.policySignal159(raw)
	if e != nil || mapped.Campaign != 7 || raw.Campaign != 0 {
		t.Fatal("親補完", e)
	}
	raw.Targets = append(raw.Targets, strategy.LotTarget{ID: "b", Quantity: 1})
	if _, e = s.policySignal159(raw); e == nil {
		t.Fatal("異親跨ぎを黙認した")
	}
	raw.Targets = []strategy.LotTarget{{ID: "不明", Quantity: 1}}
	if _, e = s.policySignal159(raw); e == nil {
		t.Fatal("所有不明を黙認した")
	}
}

// TestIndependentBoundaryPending159 はP05境界返済の異常板待機と次正常約定を検査します。
//
// 引数: t(*testing.T)。返り値: なし。未来の正常板まで状態を先行初期化しません。
func TestIndependentBoundaryPending159(t *testing.T) {
	s := independentSource159(t, "Night", "P05", "前半")
	s.P.P05.Lots = []strategy.P05Lot{{ID: "実約定", HoldID: "保有", Owner: "core", Side: 1, Quantity: 2, InitialQuantity: 2, Price: 1000, At: 1100}}
	s.Lots["保有"] = &SourceLot159{ID: "保有", Owner: "core", Campaign: 9, Side: 1, Quantity: 2, Remaining: 2, Entry: 1000, At: 1100}
	bad := independentQuote159(1, 19100, 0, 0)
	bad.QuoteOK = false
	ss, e := s.step159(bad, false, nil)
	if e != nil || len(ss) != 1 || ss[0].Campaign != 9 || s.flat159() {
		t.Fatal("境界予約", ss, e)
	}
	bad.Index = 2
	bad.Time = 20900
	if _, e = s.step159(bad, false, nil); e != nil || s.flat159() {
		t.Fatal("異常板で前半を消した", e)
	}
	if _, e = s.step159(independentQuote159(3, 20901, 900, 910), false, nil); e != nil {
		t.Fatal(e)
	}
	if !s.flat159() || s.Gross != -20000 || s.Events[0].FillTime != 20901 {
		t.Fatalf("遅延境界返済 %+v", s.Events)
	}
	post := independentSource159(t, "Night", "D07", "後半")
	if post.P.Session.Start != 1000 || post.P.P05 != nil || len(post.P.Orders) != 0 {
		t.Fatal("後半の初期状態")
	}
}

// TestIndependentPeerClock159 は同秒又は未来の相手板を現在判断へ混ぜないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependentPeerClock159(t *testing.T) {
	f := &SupportBuilder157{}
	for at := 0.; at <= 320; at++ {
		for _, ref := range []string{"TOPIX", "NK225"} {
			if ref == "TOPIX" && at == 320 {
				continue
			}
			price := 10000 + at
			f.add(strategy.Board{Reference: ref, Time: at, Bid: price - 1, Ask: price + 1, BidQuantity: 100, AskQuantity: 100})
		}
	}
	a := f.get(320, 1)
	f.add(strategy.Board{Reference: "TOPIX", Time: 320, Bid: 20000, Ask: 20002, BidQuantity: 5000, AskQuantity: 1})
	b := f.get(320, 1)
	if !a.Known || a.PeerAt != 319 || !reflect.DeepEqual(a, b) {
		t.Fatal("同秒の相手を先読みした", a, b)
	}
	if decelerated159(Support157{Known: true, Own5: 2, Own15: 6}, 1) || decelerated159(Support157{Known: true, Own5: -2, Own15: -6}, -1) {
		t.Fatal("一定速度を失速扱い")
	}
}

// TestIndependentReselectAndReserve159 は支持低下と予約による追加拒否を区別し、元数量を消さないか検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependentReselectAndReserve159(t *testing.T) {
	r := newPolicy157(independentConfig159("N07"), Scene{Start: 100, ForceClose: 10000})
	support := map[int]Support157{1: {Known: true, M: .5, T: 1}}
	sig := strategy.Signal{ID: "前半/a", Owner: "前半/core", Campaign: 5, Action: "new", Side: 1, Quantity: 5, Time: 100, SourceIndex: 0}
	if e := stepPolicy159(r, independentQuote159(0, 100, 999, 1001), []strategy.Signal{sig}, support); e != nil {
		t.Fatal(e)
	}
	if e := stepPolicy159(r, independentQuote159(1, 101, 999, 1001), nil, support); e != nil {
		t.Fatal(e)
	}
	sig.ID = "前半/b"
	sig.Quantity = 3
	sig.Time = 102
	sig.SourceIndex = 2
	if e := stepPolicy159(r, independentQuote159(2, 102, 999, 1001), []strategy.Signal{sig}, map[int]Support157{}); e != nil {
		t.Fatal(e)
	}
	l, _ := r.Actual.position("", "")
	if l != 55 || len(r.Actual.Pending) != 0 || r.Parents["前半/core/5"].SourceQty != 80 {
		t.Fatal("支持低下の追加抑制又は元数量")
	}
	sig.ID = "前半/c"
	sig.Quantity = 2
	sig.Time = 103
	sig.SourceIndex = 3
	if e := stepPolicy159(r, independentQuote159(3, 103, 999, 1001), []strategy.Signal{sig}, map[int]Support157{1: {Known: true, M: 1, T: 1}}); e != nil {
		t.Fatal(e)
	}
	if len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Quantity != 22 {
		t.Fatal("源追加係数を無視した", r.Actual.Pending)
	}
}

// TestIndependentSignedProtection159 は売りの利益床が単調で、次板飛び越しを赤字計上するか検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependentSignedProtection159(t *testing.T) {
	r := newPolicy157(independentConfig159("N09"), Scene{Start: 100, ForceClose: 10000})
	sig := strategy.Signal{ID: "後半/s", Owner: "後半/core", Campaign: 1, Action: "new", Side: -1, Quantity: 5, Time: 100, SourceIndex: 0}
	ss := map[int]Support157{-1: {Known: true, M: 0, T: 0}}
	rows := [][2]float64{{999, 1001}, {999, 1001}, {940, 942}, {920, 922}, {962, 964}, {1010, 1012}}
	for i, v := range rows {
		sigs := []strategy.Signal{}
		if i == 0 {
			sigs = []strategy.Signal{sig}
		}
		if e := stepPolicy159(r, independentQuote159(int64(i), 100+float64(i), v[0], v[1]), sigs, ss); e != nil {
			t.Fatal(e)
		}
	}
	if len(r.Actual.Events) != 2 || math.Abs(r.Actual.Realized-(-1300)) > 1e-8 {
		t.Fatalf("売り追尾の約定又は損失 %+v", r.Actual.Events)
	}
}
