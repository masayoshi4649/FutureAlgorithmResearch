package main

import (
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
	"reflect"
	"testing"
)

// bookTest165 は同価格対応を検査する人工十段板を作ります。
//
// 引数: at/bid/ask(float64)。返り値: strategy.Board。
func bookTest165(at, bid, ask float64) strategy.Board {
	b := strategy.Board{Reference: "NK225", Time: at, Received: at, Last: (bid + ask) / 2, Bid: bid, Ask: ask, BidQuantity: 10, AskQuantity: 10}
	for i := 0; i < 10; i++ {
		b.BidLevels[i] = strategy.ResearchLevel{Price: bid - float64(i)*10, Quantity: 10}
		b.AskLevels[i] = strategy.ResearchLevel{Price: ask + float64(i)*10, Quantity: 10}
	}
	return b
}

// TestFeature165SameClockPrefix は同時計の後続板を先取りしないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestFeature165SameClockPrefix(t *testing.T) {
	h := &BookFeatures165{}
	out := []Feature165{}
	for i := 0; i < 10; i++ {
		out = append(out, h.add165(bookTest165(100, 1000+float64(i)*10, 1010+float64(i)*10), int64(i), int64(i+1)))
	}
	if !out[8].Event8.Known || out[8].Event8.BidMove != 80 || out[8].Event8.Elapsed != 0 {
		t.Fatalf("同時計順: %+v", out[8])
	}
	h2 := &BookFeatures165{}
	for i := 0; i <= 8; i++ {
		v := h2.add165(bookTest165(100, 1000+float64(i)*10, 1010+float64(i)*10), int64(i), int64(i+1))
		if !reflect.DeepEqual(v, out[i]) {
			t.Fatal("prefix差")
		}
	}
	h.add165(bookTest165(100, 3000, 3010), 10, 11)
	if out[8].Current.Bid != 1080 {
		t.Fatal("過去の参照を変更")
	}
}

// TestFeature165SeparateWidening は片側板引きと両気配移動を分離します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestFeature165SeparateWidening(t *testing.T) {
	h := &BookFeatures165{}
	for i := 0; i <= 8; i++ {
		h.add165(bookTest165(float64(i), 1000, 1010+float64(i)*10), int64(i), int64(i+1))
	}
	b := h.event165(8)
	if b.BidMove != 0 || b.AskMove != 80 || b.AskOnlyUp != 8 || b.SpreadChange != 80 {
		t.Fatalf("片側:%+v", b)
	}
}

// TestFeature165BreaksUnknown は不正板と長い空白で連続性を切ります。
//
// 引数: t(*testing.T)。返り値: なし。
func TestFeature165BreaksUnknown(t *testing.T) {
	h := &BookFeatures165{}
	for i := 0; i <= 8; i++ {
		h.add165(bookTest165(float64(i), 1000+float64(i)*10, 1010+float64(i)*10), int64(i), int64(i+1))
	}
	h.add165(bookTest165(9, 1100, 1100), 9, 10)
	v := h.add165(bookTest165(10, 1110, 1120), 10, 11)
	if v.Event8.Known || v.InvalidRows != 1 {
		t.Fatal("不正板を接続")
	}
	v = h.add165(bookTest165(71, 1200, 1210), 11, 12)
	if v.Event8.Known || v.LongGaps != 1 {
		t.Fatal("61秒空白を接続")
	}
}

// TestFeature165QuantitiesAndDepth は同価格の数量だけを回復代理に数えます。
//
// 引数: t(*testing.T)。返り値: なし。
func TestFeature165QuantitiesAndDepth(t *testing.T) {
	h := &BookFeatures165{}
	a := bookTest165(100, 1000, 1010)
	h.add165(a, 0, 1)
	b := a
	b.AskQuantity = 30
	b.AskLevels[0].Quantity = 30
	v := h.add165(b, 1, 2)
	if v.Changed || v.Current.PriceEvents != 0 || v.Current.AskRefill != .5 {
		t.Fatal("価格と数量を混同")
	}
	for i := 2; i < 102; i++ {
		h.add165(b, int64(i), int64(i+1))
	}
	if h.Frames[len(h.Frames)-1].QuantityEvents != 1 {
		t.Fatal("同値板で分母が膨張")
	}
	shift := bookTest165(101, 1010, 1020)
	u, d, k := commonDepth165(a.BidLevels, shift.BidLevels)
	if !k || u != 0 || d != 0 {
		t.Fatalf("段ずれを増減と誤認 %v %v %v", u, d, k)
	}
	b = bookTest165(102, 1020, 1030)
	b.BidQuantity = math.Inf(1)
	v = h.add165(b, 102, 103)
	if v.Current.BadQuantity != 1 {
		t.Fatal("無限数量を既知")
	}
}

// TestFeature165ClockEndpoint は過去端を包含し同時計の未来を参照しません。
//
// 引数: t(*testing.T)。返り値: なし。
func TestFeature165ClockEndpoint(t *testing.T) {
	h := &BookFeatures165{}
	h.add165(bookTest165(100, 1000, 1010), 0, 1)
	h.add165(bookTest165(100, 1010, 1020), 1, 2)
	v := h.add165(bookTest165(115, 1030, 1040), 2, 3)
	if !v.Clock15.Known || v.Clock15.StartIndex != 1 || v.Clock15.BidMove != 20 || v.Clock15.Elapsed != 15 {
		t.Fatalf("端点:%+v", v.Clock15)
	}
	v = h.add165(bookTest165(146, 1040, 1050), 3, 4)
	if v.Clock15.Known {
		t.Fatal("過去端16秒遅れ")
	}
}
