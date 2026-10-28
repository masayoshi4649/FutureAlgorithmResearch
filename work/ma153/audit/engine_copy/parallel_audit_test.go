package main

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

// TestAuditParallelFailures は読込と保存の失敗を成功として返さず、成功済み口座と分けて報告することを検査します。
//
// 引数: t(*testing.T)。返り値: なし。人工ファイルのみを使います。
func TestAuditParallelFailures(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, "人工.jsonl")
	raw := `{"CurrentPriceTime":"2026-10-27T08:45:00+09:00","Buy1":{"Price":9999},"Sell1":{"Price":10001}}` + "\n"
	if err := os.WriteFile(path, []byte(raw), 0600); err != nil {
		t.Fatal(err)
	}
	start := float64(time.Date(2026, 10, 27, 8, 45, 0, 0, time.FixedZone("JST", 9*3600)).Unix())
	scene := Scene{Session: "人工_Day", Kind: "Day", Start: start, End: start + 1000, ForceClose: start + 900, Partial: true, Books: map[string]string{"NK225": path, "TOPIX": path, "欠測": filepath.Join(directory, "不存在.jsonl")}}
	var lock sync.Mutex
	calls := map[string]int{}
	save := func(s Saved) error {
		lock.Lock()
		calls[s.Symbol]++
		lock.Unlock()
		if s.Symbol == "TOPIX" {
			return errors.New("人工保存失敗")
		}
		return nil
	}
	err := runJobs([]Job{{scene, "NK225"}, {scene, "TOPIX"}, {scene, "欠測"}}, auditConfigs(), 4, save)
	if err == nil || !strings.Contains(err.Error(), "人工保存失敗") || !strings.Contains(err.Error(), "不存在.jsonl") {
		t.Fatalf("失敗消失: %v", err)
	}
	if calls["NK225"] != 1 || calls["TOPIX"] != 1 || calls["欠測"] != 0 {
		t.Fatalf("読込失敗を保存又は重複処理: %v", calls)
	}
	if err = runJobs(nil, auditConfigs(), 0, save); err == nil {
		t.Fatal("0並列を許可")
	}
	if err = runJobs(nil, auditConfigs(), 5, save); err == nil {
		t.Fatal("未固定5並列を許可")
	}
}
