package main

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

// TestExportPreservesRawClockAndAllocation は浮動小数の保存時計から原板の精度へ復帰できるか確認します。
//
// 引数: t(*testing.T)。返り値: なし。部分返済の対象・円倍率も検査します。
func TestExportPreservesRawClockAndAllocation(t *testing.T) {
	at, err := time.Parse(time.RFC3339Nano, "2026-10-27T09:00:00.123456789+09:00")
	if err != nil {
		t.Fatal(err)
	}
	first := sourceEvent{FillTime: float64(at.UnixNano()) / 1e9, FillIndex: 0, Price: 65000, HoldID: "所有1"}
	first.Order.ID, first.Order.Side, first.Order.Quantity = "新規1", 1, 10
	second := sourceEvent{FillTime: float64(at.Add(time.Second).UnixNano()) / 1e9, FillIndex: 1, Price: 65020, Gross: 800}
	second.Order.ID, second.Order.Side, second.Order.Quantity = "返済1", -1, 4
	second.Order.Targets = append(second.Order.Targets, []byte(`{}`))
	second.Pieces = []sourcePiece{{ID: "所有1", Quantity: 4, Entry: 65000, Exit: 65020, Gross: 800}}
	path := filepath.Join(t.TempDir(), "book.jsonl")
	raw := "{\"CurrentPriceTime\":null}\n" +
		"{\"CurrentPriceTime\":\"2026-10-27T09:00:00.123456789+09:00\",\"CurrentPrice\":65000,\"Buy1\":{\"Price\":64990},\"Sell1\":{\"Price\":65000}}\n" +
		"{\"CurrentPriceTime\":\"2026-10-27T09:00:01.123456789+09:00\",\"CurrentPrice\":65020,\"Buy1\":{\"Price\":65020},\"Sell1\":{\"Price\":65030}}\n"
	if err = os.WriteFile(path, []byte(raw), 0600); err != nil {
		t.Fatal(err)
	}
	scene := sourceScene{Start: float64(at.Add(-time.Minute).Unix()), End: float64(at.Add(time.Minute).Unix())}
	lines, err := rawLines(path, scene, map[int64][]sourceEvent{0: {first}, 1: {second}})
	if err != nil {
		t.Fatal(err)
	}
	var c sourceCase
	c.Config.ID = "検証用"
	c.Actual.Events, c.Actual.Realized = []sourceEvent{first, second}, 800
	c.Actual.Lots = map[string]sourceLot{"所有1": {Side: 1}}
	rows, err := records(c, lines, 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 2 || rows[0].Timestamp != "2026-10-27T09:00:00.123456789+09:00" || rows[0].SourceLine != 2 || rows[1].Type != "LongR" || rows[1].PositionID != "所有1" || rows[1].Qty != 4 || rows[1].SourceLine != 3 {
		t.Fatalf("原時計・所有配賦が変わりました: %+v", rows)
	}
	c.Actual.Events[1].Pieces[0].Gross = 999
	if _, err = records(c, lines, 10); err == nil {
		t.Fatal("不一致会計を通しました")
	}
}
