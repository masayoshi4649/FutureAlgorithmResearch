package main

import (
	"os"
	"path/filepath"
	"testing"

	"ose-future/e01/internal/config"
)

// TestConfigurationDelivery は、初回設定の生成と再配布時の利用者設定保持を検証します。
//
// 引数: t *testing.T。テストの実行状態。
// 返り値: なし。実設定の漏出・上書きやサンプルの誤読込があれば失敗します。
func TestConfigurationDelivery(t *testing.T) {
	source := filepath.Join(t.TempDir(), "source")
	destination := filepath.Join(t.TempDir(), "conf")
	if err := copyConfiguration("../../conf", source); err != nil {
		t.Fatal(err)
	}
	// 配布元の実設定は、変更されていてもサンプルに混入させません。
	userTrade := []byte("[TRADE]\nSymbol = \"NK225micro\"\nMaxPositionPerSide = 20\nDryRun = false\n")
	if err := os.WriteFile(filepath.Join(source, "trade.toml"), userTrade, 0600); err != nil {
		t.Fatal(err)
	}
	if err := copyConfiguration(source, destination); err != nil {
		t.Fatal(err)
	}
	cfg, err := config.Load(destination)
	if err != nil {
		t.Fatal(err)
	}
	if !cfg.Trading.DryRun || cfg.Trading.Symbol != "TOPIXmini" || cfg.Trading.MaxPositionPerSide != 10 {
		t.Fatalf("配布元の実設定が混入しました: %+v", cfg.Trading)
	}
	if cfg.Path("log") != filepath.Join(filepath.Dir(destination), "log") {
		t.Fatal("保存先が配布フォルダ内になりません")
	}

	// ----------------------------------------

	if err = os.WriteFile(filepath.Join(destination, "trade.toml"), userTrade, 0600); err != nil {
		t.Fatal(err)
	}
	samplePath := filepath.Join(source, "trade.toml.sample")
	sample, err := os.ReadFile(samplePath)
	if err != nil {
		t.Fatal(err)
	}
	sample = append(sample, []byte("\n# サンプル更新の確認\n")...)
	if err = os.WriteFile(samplePath, sample, 0644); err != nil {
		t.Fatal(err)
	}
	if err = copyConfiguration(source, destination); err != nil {
		t.Fatal(err)
	}
	actual, err := os.ReadFile(filepath.Join(destination, "trade.toml"))
	if err != nil || string(actual) != string(userTrade) {
		t.Fatalf("利用者の実設定が変更されました: %v", err)
	}
	updated, err := os.ReadFile(filepath.Join(destination, "trade.toml.sample"))
	if err != nil || string(updated) != string(sample) {
		t.Fatalf("サンプルが更新されていません: %v", err)
	}
	// 誤って読み込むと確実にエラーになる雛形を置き、読み分けを確認します。
	if err = os.WriteFile(filepath.Join(destination, "invalid.toml.sample"), []byte("不正なTOML ["), 0644); err != nil {
		t.Fatal(err)
	}
	cfg, err = config.Load(destination)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Trading.DryRun || cfg.Trading.Symbol != "NK225micro" || cfg.Trading.InitialQuantity != 10 {
		t.Fatal("再配布後の利用者設定が反映されません")
	}
}
