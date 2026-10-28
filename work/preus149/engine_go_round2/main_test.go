package main

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"futurealgorithm/sessiontrader/internal/rules"
	"futurealgorithm/sessiontrader/internal/strategy"
)

// testSetup は架空の場と外部既定ルールを生成します。
//
// 引数: t(*testing.T)。返り値: Sceneとmap[string]stringです。
func testSetup(t *testing.T) (Scene, map[string]string) {
	t.Helper()
	r, e := rules.Load("NK225_D07.toml")
	if e != nil {
		t.Fatal(e)
	}
	return Scene{Session: "架空_Night", Start: 1000, USOpen: 20800, ForceClose: 47200, End: 47800}, r.Expressions()
}

// TestBaselineClone149 は無変更設定がコピー元D07生成と同じ状態になることを確かめます。
//
// 引数: t(*testing.T)。返り値: なし。
func TestBaselineClone149(t *testing.T) {
	s, r := testSetup(t)
	p, _, _, e := newPortfolio(s, StudyConfig{}, false, r)
	if e != nil {
		t.Fatal(e)
	}
	params, _ := strategy.ParametersForMethod("NK225", "Night", "D07")
	plain, e := strategy.New(strategy.Config{Reference: "NK225", Product: "NK225mini", CoreQuantity: 5, ExtraMaxQuantity: 5, Cap: 10, LargeTick: 10, PointValue: 100, Parameters: params, RuleExpressions: r}, makeSession(s, s.Start, s.ForceClose))
	if e != nil {
		t.Fatal(e)
	}
	a, e := json.Marshal(p)
	if e != nil {
		t.Fatal(e)
	}
	b, e := json.Marshal(plain)
	if e != nil {
		t.Fatal(e)
	}
	if !bytes.Equal(a, b) {
		t.Fatal("C00が元D07生成と異なる")
	}
}

// TestClockOnly149 は入口時計を除く数量・価格条件が不変であることを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestClockOnly149(t *testing.T) {
	s, r := testSetup(t)
	p, _, _, e := newPortfolio(s, StudyConfig{CoreHour: 17, ExtraHour: 17}, false, r)
	if e != nil {
		t.Fatal(e)
	}
	for _, x := range p.Research.Sleeves {
		if x.Name != "core" {
			continue
		}
		n := x.Source.Legacy.Config.Parameters.Night
		expected := strategy.DefaultParameters("NK225", "Night").Night
		expected.PostOpenPrepareSeconds = s.Start - s.USOpen
		if n != expected {
			t.Fatal("時計以外も変更")
		}
		if x.Source.Session.ExtraAt != s.Start || p.Session.USOpen != s.USOpen {
			t.Fatal("補完時計又はUS時刻")
		}
	}
}

// TestSingleOwnerCapacity149 は担当削除で残りへ枚数を再配分しないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestSingleOwnerCapacity149(t *testing.T) {
	s, r := testSetup(t)
	for name, want := range map[string]int{"core": 5, "addon": 3, "episode": 2} {
		p, _, _, e := newPortfolio(s, StudyConfig{Owners: []string{name}}, false, r)
		if e != nil {
			t.Fatal(e)
		}
		if len(p.Research.Sleeves) != 1 || p.Research.Sleeves[0].Capacity != want {
			t.Fatal(name, "配分不一致")
		}
	}
}

// TestResetNewState149 は後半に損益予算・初回状態・前半担当制限を渡さないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestResetNewState149(t *testing.T) {
	s, r := testSetup(t)
	cfg := StudyConfig{Reset: true, CoreHour: 17, ExtraHour: 17, Owners: []string{"core"}, CloseBeforeMinutes: 15, RestartWaitMinutes: 5}
	p, from, end, e := newPortfolio(s, cfg, true, r)
	if e != nil {
		t.Fatal(e)
	}
	if p.Session.Start != s.USOpen || from != s.USOpen+300 || end != s.ForceClose || len(p.Research.Sleeves) != 3 {
		t.Fatal("後半開始又は配分")
	}
	for _, x := range p.Research.Sleeves {
		if x.Cash != 0 || x.Budget != 0 || len(x.Lots) != 0 || x.Source.LastIndex != -1 {
			t.Fatal("前半状態の混入")
		}
	}
}

// TestQuoteValidity149 は中値や異常気配で約定しないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestQuoteValidity149(t *testing.T) {
	for _, o := range []strategy.Observation{{QuoteOK: true, Bid: 100, Ask: 100}, {QuoteOK: true, Bid: 101, Ask: 100}, {QuoteOK: false, Bid: 100, Ask: 110}, {QuoteOK: true, Bid: 0, Ask: 110}} {
		if quoteOK(o) {
			t.Fatal("異常気配を採用")
		}
	}
	if !quoteOK(strategy.Observation{QuoteOK: true, Bid: 100, Ask: 110}) {
		t.Fatal("正常気配を拒否")
	}
}

// TestBoundaryCloseNextQuote149 は境界返済が同原行や無効板で約定しないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestBoundaryCloseNextQuote149(t *testing.T) {
	s, r := testSetup(t)
	cfg := StudyConfig{Reset: true, CloseBeforeMinutes: 15, RestartWaitMinutes: 15, Owners: []string{"core"}}
	p, from, end, e := newPortfolio(s, cfg, false, r)
	if e != nil {
		t.Fatal(e)
	}
	x := p.Research.Sleeves[0]
	x.Side = 1
	x.Campaign = 1
	x.FixedR = 100
	x.Lots = []strategy.ResearchLot{{ID: "seed", EntryID: "seed-entry", Ticket: 0, Quantity: 5, Price: 65000}}
	x.Opened[0] = 5
	x.Requested[0] = 5
	c := &Case{Config: cfg, P: p, Phase: "前半", EntryFrom: from, End: end, Positions: map[string]Lot{"seed": {Side: 1, Quantity: 5, Price: 65000, Owner: "core", Parent: "seed-parent"}}, Parents: map[string]float64{}, Diagnostics: map[string]map[string]int{}, FirstFeatureKnown: map[string]float64{}}
	o := strategy.Observation{Reference: "NK225", Time: end, Received: end, Index: 0, Bid: 65100, Ask: 65110, Last: 65100, QuoteOK: true, ATR: 100}
	if e = process(c, o); e != nil {
		t.Fatal(e)
	}
	if len(c.Events) != 0 || len(c.Pending) != 1 {
		t.Fatal("境界判断同時に約定又は返済欠落")
	}
	o.Time++
	o.Received++
	o.Index++
	o.QuoteOK = false
	if e = process(c, o); e != nil {
		t.Fatal(e)
	}
	if len(c.Events) != 0 || flat(c.P) {
		t.Fatal("異常気配で約定")
	}
	o.Time++
	o.Received++
	o.Index++
	o.QuoteOK = true
	o.Bid = 65080
	o.Ask = 65090
	if e = process(c, o); e != nil {
		t.Fatal(e)
	}
	if len(c.Events) != 1 || c.Events[0].Fill.Price != 65080 || c.Gross != 40000 || !flat(c.P) {
		t.Fatal("次正常売り気配又は所有玉会計", c.Events, c.Gross)
	}
}

// TestResetCandles149 はUS開始前と跨ぎ足を後半指標へ入れないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestResetCandles149(t *testing.T) {
	path := filepath.Join(t.TempDir(), "足.csv")
	raw := "time,open,high,low,close,closed\n2026-10-26T22:29:00+09:00,1,2,1,2,true\n2026-10-26T22:30:00+09:00,3,4,3,4,true\n2026-10-26T22:31:00+09:00,4,5,4,5,false\n"
	if e := os.WriteFile(path, []byte(raw), 0644); e != nil {
		t.Fatal(e)
	}
	start, _ := stamp("2026-10-26T22:30:00+09:00")
	bars, e := loadCandles(path, 60, start, start+600)
	if e != nil {
		t.Fatal(e)
	}
	if len(bars) != 1 || bars[0].Open != 3 || bars[0].Time < start {
		t.Fatal("US前の足又は未確定足を混入")
	}
}

// TestRawNoExecutionClock149 は約定時刻nullの正常板を残し、逆行だけを除くことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestRawNoExecutionClock149(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "板.jsonl")
	raw := "{\"CurrentPriceTime\":\"2026-10-26T17:00:01+09:00\",\"TradingVolumeTime\":null,\"CurrentPrice\":65000,\"Buy1\":{\"Price\":65000,\"Qty\":1},\"Sell1\":{\"Price\":65010,\"Qty\":1}}\n"
	if e := os.WriteFile(path, []byte(raw), 0644); e != nil {
		t.Fatal(e)
	}
	start, _ := stamp("2026-10-26T17:00:00+09:00")
	s := Scene{Start: start, End: start + 10, Cutoff: start + 10, Books: map[string]string{"NK225": path, "TOPIX": path}}
	rows, counts, e := loadBoards(s)
	if e != nil {
		t.Fatal(e)
	}
	if len(rows) != 2 || counts["NK225_採用"] != 1 || rows[0].Reference != "TOPIX" {
		t.Fatal("null約定時計の板が欠落又は同時刻順変更")
	}
}

// TestFixedSixteen149 は事前固定条件数と識別子重複を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestFixedSixteen149(t *testing.T) {
	var configs []StudyConfig
	if e := readJSON("../configs149.json", &configs); e != nil {
		t.Fatal(e)
	}
	if len(configs) != 16 {
		t.Fatal("16条件ではない")
	}
	seen := map[string]bool{}
	for _, c := range configs {
		if seen[c.ID] {
			t.Fatal("ID重複")
		}
		seen[c.ID] = true
	}
}
