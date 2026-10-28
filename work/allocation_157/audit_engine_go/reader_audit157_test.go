package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"
)

// auditScene157 は一時ディレクトリへ人工原板だけを書きます。
//
// 引数: t(*testing.T)、name(string)。返り値: Scene。
func auditScene157(t *testing.T, name string) Scene {
	dir := t.TempDir()
	start := 1700000000.0
	s := Scene{Session: name, Kind: "Day", Start: start, End: start + 10000, ForceClose: start + 9900, Cutoff: start + 30, Partial: true, Books: map[string]string{}, Candles: map[string]map[string]string{}}
	for _, ref := range []string{"NK225", "TOPIX"} {
		rows := []map[string]any{}
		for i := 0; i < 35; i++ {
			rows = append(rows, map[string]any{"CurrentPriceTime": time.Unix(int64(start)+int64(i), 0).Format(time.RFC3339Nano), "CurrentPrice": 64005 + i, "Buy1": map[string]any{"Price": 64000 + i, "Qty": 10}, "Sell1": map[string]any{"Price": 64010 + i, "Qty": 10}, "TradingVolumeTime": nil})
		}
		raw := []byte{}
		for _, row := range rows {
			line, err := json.Marshal(row)
			if err != nil {
				t.Fatal(err)
			}
			raw = append(raw, line...)
			raw = append(raw, '\n')
		}
		path := filepath.Join(dir, ref+".jsonl")
		if err := os.WriteFile(path, raw, 0600); err != nil {
			t.Fatal(err)
		}
		s.Books[ref] = path
		s.Candles[ref] = map[string]string{}
		for _, interval := range []string{"60", "300"} {
			path := filepath.Join(dir, ref+interval+".json")
			if err := os.WriteFile(path, []byte(`{"data":[]}`), 0600); err != nil {
				t.Fatal(err)
			}
			s.Candles[ref][interval] = path
		}
	}
	return s
}

// TestAuditReaderCutoffAndNullVolume157 は末尾の非精算・null約定時計を確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditReaderCutoffAndNullVolume157(t *testing.T) {
	s := auditScene157(t, "入力人工_Day")
	rows, counts, err := loadBoards(s)
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 60 || counts["NK225_採用"] != 30 || counts["TOPIX_採用"] != 30 || rows[len(rows)-1].Time >= s.Cutoff {
		t.Fatalf("null約定時計又はcutoff境界: %v %v", len(rows), counts)
	}
	for i := 0; i < len(rows); i += 2 {
		if rows[i].Reference != "TOPIX" || rows[i+1].Reference != "NK225" || rows[i].Time != rows[i+1].Time {
			t.Fatal("市場結合の原順が変化")
		}
	}
	value, err := run157(s, configs157(), nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(value.Cases) != 23 {
		t.Fatal("人工全条件数")
	}
	for _, c := range value.Cases {
		if c.ObservationEnd != s.Cutoff-1 || len(c.Actual.Events) != 0 {
			t.Fatal("準備未完了人工列の売買又は時刻不整合")
		}
	}
}

// TestAuditSceneParallelIsolation157 は独立場の実行順で保存結果が変わらないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditSceneParallelIsolation157(t *testing.T) {
	scenes := []Scene{auditScene157(t, "並列人工0_Day"), auditScene157(t, "並列人工1_Day")}
	one, many := filepath.Join(t.TempDir(), "直列"), filepath.Join(t.TempDir(), "並列")
	if err := execute157(scenes, configs157(), nil, one, 1); err != nil {
		t.Fatal(err)
	}
	if err := execute157(scenes, configs157(), nil, many, 8); err != nil {
		t.Fatal(err)
	}
	for _, s := range scenes {
		a, err := os.ReadFile(filepath.Join(one, s.Session+"_S01.json"))
		if err != nil {
			t.Fatal(err)
		}
		b, err := os.ReadFile(filepath.Join(many, s.Session+"_S01.json"))
		if err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(a, b) {
			t.Fatal("並列共有状態で出力が変化")
		}
	}
}
