package main

import (
	"reflect"
	"testing"
	"time"
)

// TestViewerBarsUseFullRawAndPeriodLast は縮約前の極値と区間最終の部分返済を検査します。
//
// 引数: t(*testing.T)。返り値: なし。表示範囲を途中で切っても同じ足・状態を要求します。
func TestViewerBarsUseFullRawAndPeriodLast(t *testing.T) {
	books := []map[string]any{
		adversaryBook(0, 100, 100, 110), adversaryBook(10, 1000, 1000, 1010),
		adversaryBook(20, 5, 5, 15), adversaryBook(50, 110, 110, 120),
		adversaryBook(60, 200, 200, 210), adversaryBook(100, 220, 220, 230),
		adversaryBook(300, 500, 500, 510),
	}
	trades := []map[string]any{
		adversaryTrade("初回", "LongN", "買玉", 0, 3, 1, 100, 0),
		adversaryTrade("部分返済", "LongR", "買玉", 50, 1, 4, 110, 0),
		adversaryTrade("逆玉", "ShortN", "売玉", 60, 1, 5, 200, 0),
	}
	cfg, resource, path := adversaryFixture(t, books, trades, "trades")
	full, err := loadDataMode(cfg, resource, path, 0, 0, 1, "1", "last")
	if err != nil {
		t.Fatal(err)
	}
	start := millis(adversaryTime(0))
	want := []any{start, start + 60000, float64(100), float64(1000), float64(5), float64(110)}
	if !reflect.DeepEqual(full.Candles[0], want) {
		t.Fatalf("縮約前OHLCの不一致: %+v", full.Candles[0])
	}
	rows := adversaryStates(t, full)
	adversaryNumber(t, rows[0], "long_qty", 2)
	adversaryNumber(t, rows[0], "short_qty", 0)
	adversaryNumber(t, rows[0], "realized_pnl_yen", 100)
	adversaryNumber(t, rows[0], "unrealized_pnl_yen", 200)
	adversaryNumber(t, rows[1], "long_qty", 2)
	adversaryNumber(t, rows[1], "short_qty", 1)
	adversaryNumber(t, rows[1], "unrealized_pnl_yen", 2100)
	partial, err := loadDataMode(cfg, resource, path, start+5000, start+30000, 1, "1", "last")
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(partial.Candles[0], full.Candles[0]) || !reflect.DeepEqual(partial.States[0], full.States[0]) {
		t.Fatalf("viewportで足又は末値が変わりました: %+v/%+v", partial.Candles, partial.States)
	}
	if full.Candles[2][2] != nil || full.Candles[2][5] != nil {
		t.Fatalf("空区間価格を補完しました: %+v", full.Candles[2])
	}
}

// TestBarCollectorEndAndMidnight は分境界・夜間跨日・場終端を別区間へ誤配分しないか検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestBarCollectorEndAndMidnight(t *testing.T) {
	start, end, err := sessionBounds("2026-10-27_Night")
	if err != nil {
		t.Fatal(err)
	}
	mode, _ := parseDisplayMode("15", "mid")
	b := newBarCollector(millis(start), millis(end), mode)
	midnight := time.Date(2026, 10, 28, 0, 0, 0, 0, japan)
	quote := func(at time.Time, bid, ask float64) { b.addQuote(marketQuote{At: at, Bid: &bid, Ask: &ask}) }
	quote(midnight.Add(-time.Nanosecond), 100, 110)
	quote(midnight, 200, 210)
	quote(end, 300, 310)
	left := b.index(millis(midnight.Add(-time.Millisecond)))
	right := b.index(millis(midnight))
	if left == right || b.Bars[left].Close == nil || *b.Bars[left].Close != 105 || b.Bars[right].Open == nil || *b.Bars[right].Open != 205 {
		t.Fatalf("跨日の所属が不正: left=%+v right=%+v", b.Bars[left], b.Bars[right])
	}
	last := b.Bars[len(b.Bars)-1]
	if last.Close == nil || *last.Close != 305 || last.End != millis(end) {
		t.Fatalf("場終端を除外しました: %+v", last)
	}
}
