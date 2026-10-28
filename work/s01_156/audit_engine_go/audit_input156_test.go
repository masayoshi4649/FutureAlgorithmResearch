package main

import (
	"encoding/json"
	"math"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"futurealgorithm/sessiontrader/internal/strategy"
)

// TestAudit156FixedCartesianConditions は固定26条件の要因と順番を独立に検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit156FixedCartesianConditions(t *testing.T) {
	var variants []Variant
	if err := readJSON("../configs156.json", &variants); err != nil {
		t.Fatal(err)
	}
	if err := validateConfigs(variants); err != nil {
		t.Fatal(err)
	}
	for i := range variants {
		for _, change := range []func(*Variant){func(v *Variant) { v.Width++ }, func(v *Variant) { v.Activation++ }, func(v *Variant) { v.Gate = !v.Gate }, func(v *Variant) { v.EntryRule++ }} {
			copyV := append([]Variant(nil), variants...)
			change(&copyV[i])
			if validateConfigs(copyV) == nil {
				t.Fatalf("条件%dの書換えを受理", i)
			}
		}
	}
}

// TestAudit156RawOrderAndClock は同秒を保持し原順を壊さず、時計欠測と逆行だけを除外する人工読取です。
//
// 引数: t(*testing.T)。返り値: なし。外部原板は読みません。
func TestAudit156RawOrderAndClock(t *testing.T) {
	dir := t.TempDir()
	start, _ := stamp("2026-10-27T08:45:00+09:00")
	books := map[string]string{}
	for _, ref := range []string{"TOPIX", "NK225"} {
		rows := []map[string]any{}
		for _, r := range []struct {
			clock any
			last  float64
		}{{"2026-10-27T08:45:00+09:00", 1000}, {"2026-10-27T08:45:01+09:00", 1010}, {"2026-10-27T08:45:01+09:00", 1020}, {nil, 1030}, {"2026-10-27T08:45:00+09:00", 1040}} {
			rows = append(rows, map[string]any{"CurrentPriceTime": r.clock, "CurrentPrice": r.last, "Buy1": map[string]any{"Price": r.last, "Qty": 1}, "Sell1": map[string]any{"Price": r.last + 10, "Qty": 1}})
		}
		lines := []string{}
		for _, r := range rows {
			b, _ := json.Marshal(r)
			lines = append(lines, string(b))
		}
		books[ref] = filepath.Join(dir, ref+".jsonl")
		if err := os.WriteFile(books[ref], []byte(strings.Join(lines, "\n")), 0600); err != nil {
			t.Fatal(err)
		}
	}
	rows, counts, err := loadBoards(Scene{Start: start, End: start + 60, Books: books})
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 6 || counts["NK225_逆行"] != 1 || counts["NK225_時計欠測"] != 1 {
		t.Fatalf("読取数不整合 %v", counts)
	}
	nk := []float64{}
	for _, r := range rows {
		if r.Reference == "NK225" {
			nk = append(nk, r.Last)
		}
	}
	if len(nk) != 3 || nk[0] != 1000 || nk[1] != 1010 || nk[2] != 1020 {
		t.Fatal("同秒原順が消失", nk)
	}
}

// TestAudit156ExecutionNeedsLaterNormalRow は同一原行や異常気配を約定価格に使わない境界を確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit156ExecutionNeedsLaterNormalRow(t *testing.T) {
	o := strategy.Observation{Index: 1, Time: 100, Bid: 1000, Ask: 1010, QuoteOK: true}
	if !normal(o) {
		t.Fatal("正常板を拒否")
	}
	if applyFill(nil, nil, strategy.Signal{SourceIndex: 1}, o) == nil {
		t.Fatal("同原行約定を受理")
	}
	for _, bad := range []strategy.Observation{{QuoteOK: false, Bid: 1000, Ask: 1010}, {QuoteOK: true, Bid: 1010, Ask: 1000}, {QuoteOK: true, Bid: 1000, Ask: math.Inf(1)}, {QuoteOK: true, Bid: math.NaN(), Ask: 1010}} {
		if normal(bad) {
			t.Fatal("異常気配を正常約定へ使用")
		}
	}
}

// TestAudit156UnregisteredCannotReplay は登録失敗と未指定を金融再生許可へ読み替えないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit156UnregisteredCannotReplay(t *testing.T) {
	if registrationOK("") == nil {
		t.Fatal("登録未指定を受理")
	}
	for _, body := range []string{`{}`, `{"registered":true}`, `{"registered":true,"returncode":1}`, `{"registered":false,"returncode":0}`} {
		path := filepath.Join(t.TempDir(), "受領.json")
		if err := os.WriteFile(path, []byte(body), 0600); err != nil {
			t.Fatal(err)
		}
		if registrationOK(path) == nil {
			t.Fatal("未完了登録を受理", body)
		}
	}
}
