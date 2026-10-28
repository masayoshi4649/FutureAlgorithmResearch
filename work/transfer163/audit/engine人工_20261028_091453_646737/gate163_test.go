package main

import (
	"os"
	"path/filepath"
	"testing"
)

// TestStagePermission163 は登録・段階・指紋・後半事前凍結が揃わない実行を拒否します。
//
// 引数: t(*testing.T)。返り値: なし。小さな人工定義だけを作り金融処理は呼びません。
func TestStagePermission163(t *testing.T) {
	dir := t.TempDir()
	paths := map[string]string{}
	for _, name := range []string{"manifest", "spec", "configs", "source"} {
		p := filepath.Join(dir, name)
		if e := os.WriteFile(p, []byte(name), 0600); e != nil {
			t.Fatal(e)
		}
		paths[name] = p
	}
	sha := func(path string) string {
		t.Helper()
		h, e := hash163(path)
		if e != nil {
			t.Fatal(e)
		}
		return h
	}
	receipt := filepath.Join(dir, "receipt.json")
	if e := save159(receipt, map[string]any{"registered": true, "returncode": 0, "sources": []Fingerprint163{{Path: "source", SHA: sha(paths["source"])}}}); e != nil {
		t.Fatal(e)
	}
	permit := map[string]any{"registered": true, "returncode": 0, "allowed_stages": []string{"train_validation"}, "manifest_sha256": sha(paths["manifest"]), "spec_sha256": sha(paths["spec"]), "configs_sha256": sha(paths["configs"]), "registration": Fingerprint163{Path: "receipt.json", SHA: sha(receipt)}}
	p := filepath.Join(dir, "permit.json")
	if e := save159(p, permit); e != nil {
		t.Fatal(e)
	}
	check := func(path, stage, freeze string) error {
		_, _, e := requireStage163(dir, path, paths["manifest"], paths["spec"], paths["configs"], stage, freeze)
		return e
	}
	if check(p, "train_validation", "") != nil || check(p, "locked_test", "") == nil || check("", "train_validation", "") == nil {
		t.Fatal("段階許可差")
	}
	freeze := filepath.Join(dir, "freeze.json")
	if e := save159(freeze, map[string]any{"test_opened": false, "selection_sessions": 40, "selected": map[string]string{"Day": "G40", "Night": "R80"}, "manifest_sha256": permit["manifest_sha256"], "spec_sha256": permit["spec_sha256"], "configs_sha256": permit["configs_sha256"]}); e != nil {
		t.Fatal(e)
	}
	permit["allowed_stages"] = []string{"locked_test"}
	permit["freeze_sha256"] = sha(freeze)
	q := filepath.Join(dir, "testpermit.json")
	if e := save159(q, permit); e != nil {
		t.Fatal(e)
	}
	if check(q, "locked_test", freeze) != nil {
		t.Fatal("正しい後半許可を拒否")
	}
	if e := os.WriteFile(paths["source"], []byte("変更"), 0600); e != nil {
		t.Fatal(e)
	}
	if check(q, "locked_test", freeze) == nil {
		t.Fatal("源変更を許可")
	}
}

// TestRawFingerprints163 は六資料の集合と内容変更の両方を検出します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestRawFingerprints163(t *testing.T) {
	s := artificialScene163(t, "Day")
	for _, p := range s.Books {
		h, e := hash163(p)
		if e != nil {
			t.Fatal(e)
		}
		s.Fingerprints = append(s.Fingerprints, Fingerprint163{Path: p, SHA: h})
	}
	for _, paths := range s.Candles {
		for _, p := range paths {
			h, e := hash163(p)
			if e != nil {
				t.Fatal(e)
			}
			s.Fingerprints = append(s.Fingerprints, Fingerprint163{Path: p, SHA: h})
		}
	}
	if e := rawHashes163(s); e != nil {
		t.Fatal(e)
	}
	if e := os.WriteFile(s.Candles["NK225"]["60"], []byte("変更"), 0600); e != nil {
		t.Fatal(e)
	}
	if rawHashes163(s) == nil {
		t.Fatal("原資料変更を検出しない")
	}
}
