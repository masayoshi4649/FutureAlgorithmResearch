package journal

import (
	"encoding/csv"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// TestProjectionRebuild はCSV欠落・上書き後にも正本から重複なく復元することを確認します。
//
// 引数: t *testing.T は試験です。
// 返り値: なし。
func TestProjectionRebuild(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "state.json")
	logs := filepath.Join(dir, "log")
	s, err := Open(path, logs)
	if err != nil {
		t.Fatal(err)
	}
	if err = s.EnsureSession("2026-10-02_Day", true); err != nil {
		t.Fatal(err)
	}
	trade := Trade{ID: "記録1", At: time.Now(), Session: "2026-10-02_Day", Symbol: "TOPIXmini", TradeType: "new", Side: "buy", Quantity: 1, Price: 4000, Reason: "理由,改行\nあり", DryRun: true}
	if err = s.Save(map[string]int{"確認": 1}, []Trade{trade}); err != nil {
		t.Fatal(err)
	}
	csvPath := filepath.Join(logs, "2026-10-02_Day_dryrun.csv")
	if err = os.WriteFile(csvPath, []byte("途中"), 0600); err != nil {
		t.Fatal(err)
	}
	s, err = Open(path, logs)
	if err != nil {
		t.Fatal(err)
	}
	var state map[string]int
	trades, err := s.Load(&state)
	if err != nil || state["確認"] != 1 || len(trades) != 1 {
		t.Fatal("正本の復元失敗")
	}
	f, err := os.Open(csvPath)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	rows, err := csv.NewReader(f).ReadAll()
	if err != nil || len(rows) != 2 || rows[1][9] != trade.Reason {
		t.Fatal("CSVの復元・引用符処理失敗")
	}
	if err = s.EnsureSession("../escape", false); err == nil {
		t.Fatal("不正パスを受け入れました")
	}
}
