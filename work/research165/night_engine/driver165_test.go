package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

// TestGate165RequiresSuccessfulStage は未登録・欠測受領を拒否します。
//
// 引数: t(*testing.T)。返り値: なし。原資料や保存金融結果は読みません。
func TestGate165RequiresSuccessfulStage(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "許可.json")
	for _, raw := range []string{`{}`, `{"registered":true}`, `{"registered":true,"returncode":1}`, `{"registered":true,"returncode":0,"allowed_stages":["confirmation"]}`} {
		if e := os.WriteFile(p, []byte(raw), 0644); e != nil {
			t.Fatal(e)
		}
		if _, _, e := gate165("train_validation", p, "なし", "なし", "なし", ""); e == nil {
			t.Fatal("不正許可を通過")
		}
	}
}

// TestValidateFlat165RejectsUnresolved は未約定と待機がある状態を完了にしません。
//
// 引数: t(*testing.T)。返り値: なし。
func TestValidateFlat165RejectsUnresolved(t *testing.T) {
	r := newResult165(configs165()[0], Scene{USOpen: 0, ForceClose: 2000})
	if e := validateFlat165(r); e != nil {
		t.Fatal(e)
	}
	r.Actual.Pending = append(r.Actual.Pending, Order157{ID: "未約定", Quantity: 10})
	if e := validateFlat165(r); e == nil {
		t.Fatal("未約定を完了")
	}
	r.Actual.Pending = nil
	r.Parents["待機"] = &NightParent164R2{Deferred: true}
	if e := validateFlat165(r); e == nil {
		t.Fatal("未完待機を完了")
	}
}

// TestConfigs165FullDefinition は14IDと数値定義がJSON単独で復元できることを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestConfigs165FullDefinition(t *testing.T) {
	c := configs165()
	if len(c) != 14 {
		t.Fatal("条件数")
	}
	seen := map[string]bool{}
	for _, x := range c {
		if x.Scope != "PostUS" || len(x.RuleHash) != 64 || seen[x.ID] {
			t.Fatal("ID/区分/指紋")
		}
		seen[x.ID] = true
		if x.Parameters["独立仮想全方向親上限"] != 5 {
			t.Fatal("全方向枠")
		}
	}
	b, e := json.Marshal(c)
	if e != nil {
		t.Fatal(e)
	}
	p := filepath.Join(t.TempDir(), "定義.json")
	if e = os.WriteFile(p, b, 0644); e != nil {
		t.Fatal(e)
	}
	if e = validateConfigs165(p); e != nil {
		t.Fatal(e)
	}
}
