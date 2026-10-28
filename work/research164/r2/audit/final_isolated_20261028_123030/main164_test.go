package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

// writeGateTest164 は金融入力を含まない段階許可の人工JSONを保存します。
//
// 引数: t(*testing.T)、path(string)、v(any)。返り値: stringはSHAです。
func writeGateTest164(t *testing.T, path string, v any) string {
	t.Helper()
	b, e := json.Marshal(v)
	if e != nil {
		t.Fatal(e)
	}
	if e = os.WriteFile(path, b, 0600); e != nil {
		t.Fatal(e)
	}
	h, e := hashFile164(path)
	if e != nil {
		t.Fatal(e)
	}
	return h
}

// TestMain164StageGate は受領・段階・凍結・実装指紋の欠落と変更を拒否します。
//
// 引数: t(*testing.T)。返り値: なし。原板は読みません。
func TestMain164StageGate(t *testing.T) {
	dir := t.TempDir()
	manifest, spec, configs := filepath.Join(dir, "inputs.json"), filepath.Join(dir, "spec.json"), filepath.Join(dir, "configs.json")
	mh := writeGateTest164(t, manifest, map[string]int{"人工": 1})
	sh := writeGateTest164(t, spec, map[string]int{"人工": 2})
	ch := writeGateTest164(t, configs, allConfigs164())
	receipt, permission, freeze := filepath.Join(dir, "receipt.json"), filepath.Join(dir, "permission.json"), filepath.Join(dir, "freeze.json")
	rh := writeGateTest164(t, receipt, map[string]any{"registered": true, "returncode": 0, "sources": []Fingerprint164{{spec, sh}}})
	a := map[string]any{"registered": true, "returncode": 0, "allowed_stages": []string{"train_validation"}, "manifest_sha256": mh, "spec_sha256": sh, "configs_sha256": ch, "registration": Fingerprint164{receipt, rh}}
	writeGateTest164(t, permission, a)
	if _, _, e := gate164("train_validation", permission, manifest, spec, configs, ""); e != nil {
		t.Fatal(e)
	}
	if _, _, e := gate164("confirmation", permission, manifest, spec, configs, freeze); e == nil {
		t.Fatal("後段階の無許可通過")
	}
	a["allowed_stages"] = []string{"confirmation"}
	fr := map[string]any{"selected": map[string]string{"Day": "NK225_D164_00", "PreUS": "NK225_P164_00", "PostUS": "NK225_U164_00"}, "test_opened": false, "selection_sessions": 40, "manifest_sha256": mh, "spec_sha256": sh, "configs_sha256": ch}
	a["freeze_sha256"] = writeGateTest164(t, freeze, fr)
	writeGateTest164(t, permission, a)
	if _, _, e := gate164("confirmation", permission, manifest, spec, configs, freeze); e != nil {
		t.Fatal(e)
	}
	fr["test_opened"] = true
	a["freeze_sha256"] = writeGateTest164(t, freeze, fr)
	writeGateTest164(t, permission, a)
	if _, _, e := gate164("confirmation", permission, manifest, spec, configs, freeze); e == nil {
		t.Fatal("既開封凍結の通過")
	}
	a["returncode"] = 1
	writeGateTest164(t, permission, a)
	if _, _, e := gate164("confirmation", permission, manifest, spec, configs, freeze); e == nil {
		t.Fatal("失敗受領の通過")
	}
	if e := validateAllConfigs164(configs); e != nil {
		t.Fatal(e)
	}
	writeGateTest164(t, configs, []any{})
	if e := validateAllConfigs164(configs); e == nil {
		t.Fatal("候補改変の通過")
	}
}

// TestMain164ProofSchema は制御器が必要とする小文字キーを保存します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestMain164ProofSchema(t *testing.T) {
	b, e := json.Marshal(Proof164{Completed: true, Sessions: 40, Cases: 400, Returncode: 0, SourcesUnchanged: true})
	if e != nil {
		t.Fatal(e)
	}
	var v map[string]any
	if e = json.Unmarshal(b, &v); e != nil {
		t.Fatal(e)
	}
	for _, key := range []string{"completed", "returncode", "sessions", "cases", "sources_unchanged", "stage", "sources", "results"} {
		if _, ok := v[key]; !ok {
			t.Fatal(key)
		}
	}
}

// TestNight164BoundaryNextRow は境界を跨いだ予約を実約定後の次板で返済します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestNight164BoundaryNextRow(t *testing.T) {
	r, p := seedNightTest164(t, 2, 1, 10, 40)
	r.End = 103
	o := quoteNightTest164(2, 103, 1010, 1020)
	if e := r.stepNight164(o, featuresNightTest164(o)); e != nil {
		t.Fatal(e)
	}
	if len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Reason != "時間枠終了" {
		t.Fatal("境界返済")
	}
	if p.Closed {
		t.Fatal("予約を完済にした")
	}
	o = quoteNightTest164(3, 103, 980, 990)
	f := featuresNightTest164(o)
	f.FirstNormal = false
	if e := r.stepNight164(o, f); e != nil {
		t.Fatal(e)
	}
	if len(r.Actual.Active) > 0 || len(r.Actual.Pending) > 0 || r.Actual.Realized != -2000 {
		t.Fatal("同時計次原行境界約定")
	}
	if r.Sides[1].ProfitSeed {
		t.Fatal("境界後再参加")
	}
}
