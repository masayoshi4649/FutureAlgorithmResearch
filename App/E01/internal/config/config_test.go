package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestLoad は実設定の読込と枚数・未対応キーの拒否を検証します。
//
// 引数: t *testing.T。返り値: なし。
func TestLoad(t *testing.T) {
	c, err := Load("../../conf")
	if err != nil {
		t.Fatal(err)
	}
	if !c.Trading.DryRun || c.Trading.MaxPositionPerSide != 10 || c.Trading.InitialQuantity != 5 {
		t.Fatalf("枚数・モードが不正: %+v", c.Trading)
	}
	for _, code := range []string{"NK225", "NK225mini", "NK225micro", "TOPIX", "TOPIXmini"} {
		v := c
		v.Trading.Symbol = code
		if err := v.Validate(); err != nil {
			t.Fatalf("%s: %v", code, err)
		}
	}
	dir := t.TempDir()
	names, err := filepath.Glob("../../conf/*.toml")
	if err != nil {
		t.Fatal(err)
	}
	for _, name := range names {
		b, err := os.ReadFile(name)
		if err != nil {
			t.Fatal(err)
		}
		if err = os.WriteFile(filepath.Join(dir, filepath.Base(name)), b, 0600); err != nil {
			t.Fatal(err)
		}
	}
	if err = os.WriteFile(filepath.Join(dir, "zzz.toml"), []byte("[MISTAKE]\nTypo = 1\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err = Load(dir); err == nil || !strings.Contains(err.Error(), "未対応") {
		t.Fatalf("未知設定を受理しました: %v", err)
	}
}

// TestInvalidAndFingerprint は上限超過や設定変更の混在を防ぐことを検証します。
//
// 引数: t *testing.T。返り値: なし。
func TestInvalidAndFingerprint(t *testing.T) {
	c, err := Load("../../conf")
	if err != nil {
		t.Fatal(err)
	}
	v := c
	v.Trading.InitialQuantity = 11
	if v.Validate() == nil {
		t.Fatal("上限超過を受理しました")
	}
	v = c
	v.Trading.MaxPositionPerSide = 1
	v.Trading.InitialQuantity = 0
	if err = v.Validate(); err != nil || v.Trading.InitialQuantity != 1 {
		t.Fatal("1枚上限に対応していません")
	}
	v = c
	v.Runtime.LogDirectory = "別の記録"
	if v.Fingerprint() != c.Fingerprint() {
		t.Fatal("保存先だけで指紋が変わります")
	}
	v = c
	v.E01.StopATR = 1
	if v.Fingerprint() == c.Fingerprint() {
		t.Fatal("戦略差を識別できません")
	}
}
