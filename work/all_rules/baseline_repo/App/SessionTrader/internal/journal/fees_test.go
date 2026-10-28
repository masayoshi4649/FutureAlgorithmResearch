package journal

import (
	"bytes"
	"encoding/csv"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"futurealgorithm/sessiontrader/internal/controller"
)

// TestFeeLotsAndLegacyJournal は旧形式を改変せず、新しい手数料・返済内訳を復元します。
//
// 引数: t(*testing.T)は試験です。
// 返り値: なし。SQLite正本とCSV/JSONLの追加列を照合します。
func TestFeeLotsAndLegacyJournal(t *testing.T) {
	s, path, logs := testStore(t)
	old := testTrade("old")
	before, err := json.Marshal(old)
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(before, []byte(`"fee"`)) || bytes.Contains(before, []byte(`"closed"`)) {
		t.Fatal("旧形式に新項目を強制追加しました")
	}
	if err = s.Save(map[string]int{"state": 1}, []Trade{old}); err != nil {
		t.Fatal(err)
	}
	current := testTrade("new-close")
	current.TradeType, current.Side, current.Fee = "close", "sell", 83
	current.Quantity = 2
	current.Closed = []controller.ClosePosition{{HoldID: "old", Quantity: 2}}
	current.ClosedBasis = "口座残数照合による配賦"
	if err = s.Save(map[string]int{"state": 2}, []Trade{old, current}); err != nil {
		t.Fatal(err)
	}
	if err = s.Close(); err != nil {
		t.Fatal(err)
	}
	restored, err := Open(path, logs)
	if err != nil {
		t.Fatal(err)
	}
	defer restored.Close()
	var state map[string]int
	trades, err := restored.Load(&state)
	if err != nil || len(trades) != 2 || trades[0].Fee != 0 || trades[0].Closed != nil {
		t.Fatal("旧形式または費用/玉指定の復元失敗", trades, err)
	}
	currentBefore, _ := json.Marshal(current)
	currentAfter, _ := json.Marshal(trades[1])
	if !bytes.Equal(currentBefore, currentAfter) {
		t.Fatal("返済約定の再保存内容が不一致")
	}
	oldAfter, _ := json.Marshal(trades[0])
	if !bytes.Equal(before, oldAfter) {
		t.Fatal("過去約定の会計を書き換えました")
	}
	if err = restored.Save(state, trades); err != nil {
		t.Fatal("復元後の同一保存を拒否しました", err)
	}
	raw, err := os.ReadFile(filepath.Join(logs, "2026-10-21_Day_dryrun.csv"))
	if err != nil {
		t.Fatal(err)
	}
	rows, err := csv.NewReader(bytes.NewReader(raw)).ReadAll()
	if err != nil || len(rows) != 3 || len(rows[0]) != 22 || rows[0][18] != "標準手数料円" || rows[2][18] != "83" || rows[2][21] != current.ClosedBasis {
		t.Fatal("CSV追加列が不一致", rows, err)
	}
	var targets []controller.ClosePosition
	if err = json.Unmarshal([]byte(rows[2][20]), &targets); err != nil || !reflect.DeepEqual(targets, current.Closed) {
		t.Fatal("CSVの返済玉内訳が不一致", targets, err)
	}
}
