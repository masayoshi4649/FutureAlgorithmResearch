package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// auditConfigs は固定26条件を人工検査にだけ構成します。
//
// 引数: なし。返り値: []Configです。
func auditConfigs() []Config {
	var cs []Config
	ids := []string{"M01", "M02", "M03", "M04", "M05", "M06", "M07", "M08", "M09", "M10", "M11", "M12", "M13", "M14", "M15", "M16", "M17", "M18", "M19", "M20", "M21", "M22", "M23", "M24"}
	for _, p := range [][2]float64{{60, 30}, {180, 30}, {300, 60}, {600, 60}} {
		for _, a := range []string{"entry", "dynamic"} {
			for _, e := range []string{"T", "Z", "D"} {
				cs = append(cs, Config{ids[len(cs)], p[0], p[1], a, e})
			}
		}
	}
	return append(cs, Config{"F01", 180, 30, "fixed1", "D"}, Config{"F10", 180, 30, "fixed10", "D"})
}

// TestAuditReaderPreservesInvalidAndEqualClock は時計欠測・巻戻り・同時刻を別扱いとし、不正板を消して約定しないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。実保存データは読みません。
func TestAuditReaderPreservesInvalidAndEqualClock(t *testing.T) {
	base := time.Date(2026, 10, 27, 8, 45, 0, 0, time.FixedZone("JST", 9*3600))
	at := float64(base.Unix())
	path := filepath.Join(t.TempDir(), "人工.jsonl")
	rows := []map[string]any{}
	add := func(sec int, bid, ask float64) {
		rows = append(rows, map[string]any{"CurrentPriceTime": base.Add(time.Duration(sec) * time.Second).Format(time.RFC3339Nano), "Buy1": map[string]any{"Price": bid}, "Sell1": map[string]any{"Price": ask}})
	}
	add(0, 9999, 10001)
	rows = append(rows, map[string]any{"CurrentPriceTime": nil, "Buy1": map[string]any{"Price": 99999}})
	add(30, 10009, 10011)
	add(60, 10019, 10021)
	add(90, 10029, 10031)
	add(95, 10040, 10039)
	add(94, 10039, 10041)
	add(96, 10039, 10041)
	add(96, 10039, 10041)
	add(200, 20000, 20002)
	data := []byte{}
	for _, row := range rows {
		b, err := json.Marshal(row)
		if err != nil {
			t.Fatal(err)
		}
		data = append(data, b...)
		data = append(data, '\n')
	}
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
	scene := Scene{Session: "人工_Day", Kind: "Day", Start: at, End: at + 300, ForceClose: at + 250, Cutoff: at + 200, Partial: true, Books: map[string]string{"NK225": path}}
	result, err := runScene(scene, "NK225", auditConfigs())
	if err != nil {
		t.Fatal(err)
	}
	if result.Counts["原行"] != 10 || result.Counts["時計欠測"] != 1 || result.Counts["時計逆行"] != 1 || result.Counts["異常BBO"] != 1 || result.Counts["範囲外"] != 1 || result.Counts["採用"] != 7 {
		t.Fatalf("行分類%v", result.Counts)
	}
	c := result.Cases[0]
	if len(c.Events) == 0 {
		t.Fatal("人工傾きの新規なし")
	}
	e := c.Events[0]
	if e.Order.DecisionTime != at+90 || e.Order.DecisionLine != 5 || e.Order.DecisionIndex != 3 || e.FillTime != at+96 || e.FillLine != 8 || e.FillIndex != 5 {
		t.Fatalf("原順/正常板約定%+v", e)
	}
	if !c.Partial || c.Quantity == 0 || c.FlatAt != 0 {
		t.Fatal("部分末尾を勝手に清算")
	}
}

// TestAuditFixedConfigurationRejectsMutations は窓・数量・出口の自由な追加を防ぐことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditFixedConfigurationRejectsMutations(t *testing.T) {
	cs := auditConfigs()
	if err := validateConfigs(cs); err != nil {
		t.Fatal(err)
	}
	cs[8].Window = 181
	if err := validateConfigs(cs); err == nil {
		t.Fatal("未登録の窓変更を許可")
	}
	cs = auditConfigs()
	cs[24].Allocation = "fixed2"
	if err := validateConfigs(cs); err == nil {
		t.Fatal("未登録固定2枚を許可")
	}
}
