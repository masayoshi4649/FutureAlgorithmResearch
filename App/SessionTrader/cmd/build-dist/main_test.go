package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"futurealgorithm/sessiontrader/internal/config"
)

const sampleConfiguration = `
[startup]
# 実行動作の説明。
action = "run"
[controller]
# 接続先の説明。
base_url = "http://127.0.0.1:8080"
[trading]
# 仮想実行の説明。実設定は上書きしません。
dryrun = true
# 運転IDの説明。
instance_id = "topix-mini"
[schedule]
# 場内返済時刻の説明。
force_close_before_seconds = 600
# 日中追加時刻の説明。日本時間。
day_extra_jst = "12:30"
# 米国開始時刻の説明。冬の日本時間。
us_open_jst = "23:30"
# 米国開始後待機の説明。
us_extra_delay_minutes = 30
# 欧州引け時刻の説明。冬の日本時間。
london_extra_jst = "01:30"
# 一つの商品だけを売買する設定の説明。
[market]
# 発注商品の説明。
product = "TOPIXmini"
# 片方向上限の説明。
max_per_side = 10
[methods]
# 日中手法の説明。
day = "T06"
# 夜間手法の説明。TOPIXはT04、日経の新規配布はTG04。
night = "T04"
`

// fixture は実在の設定を読まずに一時的な配布元を構成します。
//
// 引数: t *testing.T は試験です。
// 返り値: string は一時ルートです。
func fixture(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	write(t, filepath.Join(root, "go.mod"), "module futurealgorithm/sessiontrader\n")
	write(t, filepath.Join(root, "conf", "setting.toml.sample"), sampleConfiguration)
	write(t, filepath.Join(root, "conf", "setting.toml"), "実設定は配布元にしない")
	write(t, filepath.Join(root, "docs", "仕様.md"), "# 仕様\n")
	return root
}

// TestSingleProductConfigurations は全五商品の配布分離と再配布時の設定保持を確認します。
//
// 引数: t *testing.T。返り値: なし。
func TestSingleProductConfigurations(t *testing.T) {
	root := fixture(t)
	if err := buildDistribution(root, fakeBuild); err != nil {
		t.Fatal(err)
	}
	for _, target := range []string{"windows-amd64", "linux-amd64"} {
		for _, example := range []struct {
			folder, product, id, day, night string
			cap                             int
			tick, pointValue                float64
		}{
			{"TOPIX", "TOPIX", "topix", "T06", "T04", 2, .5, 10000},
			{"TOPIXmini", "TOPIXmini", "topix-mini", "T06", "T04", 10, .25, 1000},
			{"NK225", "NK225", "nk225", "TG04", "TG04", 2, 10, 1000},
			{"NK225mini", "NK225mini", "nk225mini", "TG04", "TG04", 10, 5, 100},
			{"NK225micro", "NK225micro", "nk-micro", "TG04", "TG04", 20, 5, 10},
		} {
			path := filepath.Join(root, "dist", target, example.folder)
			cfg, err := config.Load(filepath.Join(path, "conf"))
			if err != nil {
				t.Fatal(err)
			}
			_, market := cfg.Selected()
			if len(cfg.Markets) != 1 || market.Product != example.product || market.MaxPerSide != example.cap || cfg.InstanceID() != example.id || !cfg.Trading.DryRun {
				t.Fatalf("単一商品の設定例が不正です: %+v", cfg)
			}
			if cfg.MethodID("Day") != example.day || cfg.MethodID("Night") != example.night ||
				cfg.Products[example.product].Tick != example.tick || cfg.Products[example.product].PointValue != example.pointValue {
				t.Fatalf("商品の手法または呼値・円換算規格が不正です: %s %+v", example.product, cfg)
			}
			if cfg.Root != path || cfg.Path("data") != filepath.Join(path, "data") {
				t.Fatal("商品フォルダの外に保存先が設定されました")
			}
			binary, platform := "sessiontrader.exe", "windows"
			if target == "linux-amd64" {
				binary, platform = "sessiontrader", "linux"
			}
			for relative, expected := range map[string]string{binary: "模擬実行ファイル:" + platform, "docs/仕様.md": "# 仕様\n", "README.md": string(distributionReadme)} {
				content, err := os.ReadFile(filepath.Join(path, relative))
				if err != nil || string(content) != expected {
					t.Fatalf("フォルダ単独で必要な配布物が揃いません: %s %v", relative, err)
				}
			}
			write(t, filepath.Join(path, "conf", "settings.toml"), "利用者設定を保持")
			write(t, filepath.Join(path, "data", "state.sqlite"), "独立した正本")
			write(t, filepath.Join(path, "log", "history.csv"), "独立した約定")
		}
	}
	if err := buildDistribution(root, fakeBuild); err != nil {
		t.Fatal(err)
	}
	for _, target := range []string{"windows-amd64", "linux-amd64"} {
		for _, folder := range []string{"TOPIX", "TOPIXmini", "NK225", "NK225mini", "NK225micro"} {
			for relative, expected := range map[string]string{"conf/settings.toml": "利用者設定を保持", "data/state.sqlite": "独立した正本", "log/history.csv": "独立した約定"} {
				data, err := os.ReadFile(filepath.Join(root, "dist", target, folder, relative))
				if err != nil || string(data) != expected {
					t.Fatal("再配布で設定・データ・ログを書き換えました", relative)
				}
			}
		}
	}
}

// write は親ディレクトリ込みで試験用の通常ファイルを書きます。
//
// 引数: t *testing.T は試験、path/content string は対象と内容です。
// 返り値: なし。
func write(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0644); err != nil {
		t.Fatal(err)
	}
}

// fakeBuild は実コンパイルなしで配置対象を生成します。
//
// 引数: root/goos/output string はビルド契約です。
// 返り値: error はファイル作成エラーです。
func fakeBuild(root, goos, output string) error {
	return os.WriteFile(output, []byte("模擬実行ファイル:"+goos), 0755)
}

// TestUpdatePreservesActualConfigDataLog は再配布で利用者データを保持します。
//
// 引数: t *testing.T は試験です。
// 返り値: なし。
func TestUpdatePreservesActualConfigDataLog(t *testing.T) {
	root := fixture(t)
	retained := map[string]string{
		"conf/setting.toml":        "利用者の実設定",
		"conf/custom.toml":         "追加した実設定",
		"conf/setting.toml.sample": "旧構成のサンプル",
		"docs/仕様.md":               "旧構成の説明書",
		"conf-topix/settings.toml": "旧TOPIX設定",
		"conf-nk/settings.toml":    "旧日経設定",
		"data/state.sqlite":        "運用の正本",
		"log/history.csv":          "運用の約定",
		"独自メモ.txt":                 "未知ファイルを維持",
	}
	for _, target := range []string{"windows-amd64", "linux-amd64"} {
		dest := filepath.Join(root, "dist", target)
		for relative, content := range retained {
			write(t, filepath.Join(dest, relative), content)
		}
		binary := "sessiontrader.exe"
		if target == "linux-amd64" {
			binary = "sessiontrader"
		}
		write(t, filepath.Join(dest, binary), "旧構成の実行ファイル")
	}
	if err := buildDistribution(root, fakeBuild); err != nil {
		t.Fatal(err)
	}
	for _, target := range []string{"windows-amd64", "linux-amd64"} {
		dest := filepath.Join(root, "dist", target)
		for path, expected := range retained {
			data, err := os.ReadFile(filepath.Join(dest, filepath.FromSlash(path)))
			if err != nil || string(data) != expected {
				t.Fatalf("保持または配置が不正です: %s %s %v", target, path, err)
			}
		}
		binary := "sessiontrader.exe"
		if target == "linux-amd64" {
			binary = "sessiontrader"
		}
		data, err := os.ReadFile(filepath.Join(dest, binary))
		if err != nil || string(data) != "旧構成の実行ファイル" {
			t.Fatal("利用者の旧実行ファイルを自動で変更しました", err)
		}
	}
	stages, _ := filepath.Glob(filepath.Join(root, "dist", ".build-*"))
	if len(stages) != 0 {
		t.Fatal("専用一時領域を片付けていません")
	}
}

// TestFirstConfigAndFailedBuild は初回配置と両 OS 完成前の更新禁止を確認します。
//
// 引数: t *testing.T は試験です。
// 返り値: なし。
func TestFirstConfigAndFailedBuild(t *testing.T) {
	root := fixture(t)
	existing := map[string]string{}
	for _, target := range []string{"windows-amd64", "linux-amd64"} {
		binary := "sessiontrader.exe"
		if target == "linux-amd64" {
			binary = "sessiontrader"
		}
		for _, product := range []string{"TOPIX", "TOPIXmini", "NK225", "NK225mini", "NK225micro"} {
			bundle := filepath.Join(root, "dist", target, product)
			for relative, value := range map[string]string{binary: "旧実行ファイル", "conf/settings.toml.sample": "旧サンプル", "docs/仕様.md": "旧説明書", "data/state.sqlite": "旧状態"} {
				path := filepath.Join(bundle, relative)
				existing[path] = value
				write(t, path, value)
			}
		}
	}
	calls := 0
	if err := buildDistribution(root, func(root, goos, path string) error {
		calls++
		if goos == "linux" {
			return fmt.Errorf("模擬失敗")
		}
		return fakeBuild(root, goos, path)
	}); err == nil || calls != 2 {
		t.Fatal("二番目のビルド失敗を検出できません")
	}
	for path, expected := range existing {
		data, err := os.ReadFile(path)
		if err != nil || string(data) != expected {
			t.Fatal("両 OS 成功前に既存配布物を変更しました", path, err)
		}
	}
	if err := buildDistribution(root, fakeBuild); err != nil {
		t.Fatal(err)
	}
	directory := filepath.Join(root, "dist", "linux-amd64", "NK225mini", "conf")
	data, err := os.ReadFile(filepath.Join(directory, "settings.toml"))
	sample, sampleErr := os.ReadFile(filepath.Join(directory, "settings.toml.sample"))
	if err != nil || sampleErr != nil || string(data) != string(sample) {
		t.Fatal("初回にサンプルから実設定を配置できません")
	}
}

// TestFreshRootHasOnlyProductBundles はOS直下へ共通実行ファイル・設定を再生成しないことを確認します。
//
// 引数: t(*testing.T) は試験です。返り値: なし。
func TestFreshRootHasOnlyProductBundles(t *testing.T) {
	root := fixture(t)
	if err := buildDistribution(root, fakeBuild); err != nil {
		t.Fatal(err)
	}
	for _, target := range []string{"windows-amd64", "linux-amd64"} {
		directory := filepath.Join(root, "dist", target)
		entries, err := os.ReadDir(directory)
		if err != nil {
			t.Fatal(err)
		}
		expected := map[string]bool{"README.md": false, "TOPIX": true, "TOPIXmini": true, "NK225": true, "NK225mini": true, "NK225micro": true}
		if len(entries) != len(expected) {
			t.Fatalf("OS直下がREADMEと五商品だけになっていません: %s %v", target, entries)
		}
		for _, entry := range entries {
			directory, exists := expected[entry.Name()]
			if !exists || entry.IsDir() != directory {
				t.Fatalf("OS直下に想定外の配布物があります: %s/%s", target, entry.Name())
			}
		}
		data, err := os.ReadFile(filepath.Join(directory, "README.md"))
		if err != nil || string(data) != string(distributionRootReadme) {
			t.Fatal("OS直下に商品一覧用READMEを配置していません", err)
		}
	}
}

// TestUnsafeSampleRejected は配布既定が実注文へ変わることを防ぎます。
//
// 引数: t *testing.T は試験です。
// 返り値: なし。
func TestUnsafeSampleRejected(t *testing.T) {
	root := fixture(t)
	write(t, filepath.Join(root, "conf", "setting.toml.sample"), strings.Replace(sampleConfiguration, "dryrun = true", "dryrun = false", 1))
	calls := 0
	err := buildDistribution(root, func(string, string, string) error {
		calls++
		return nil
	})
	if err == nil || calls != 0 {
		t.Fatal("実注文指定のサンプルを配布しました")
	}
}

// TestCrossBuildEnvironment はホスト設定に関係なく CGO を無効化します。
//
// 引数: t *testing.T は試験です。
// 返り値: なし。
func TestCrossBuildEnvironment(t *testing.T) {
	t.Setenv("GOOS", "windows")
	t.Setenv("GOARCH", "arm64")
	t.Setenv("CGO_ENABLED", "1")
	values := map[string]string{}
	for _, field := range buildEnvironment("linux") {
		key, value, _ := strings.Cut(field, "=")
		if key == "GOOS" || key == "GOARCH" || key == "CGO_ENABLED" {
			if _, exists := values[key]; exists {
				t.Fatal("対象環境が二重定義です")
			}
			values[key] = value
		}
	}
	if values["GOOS"] != "linux" || values["GOARCH"] != "amd64" || values["CGO_ENABLED"] != "0" {
		t.Fatal("クロスビルド設定が不正です")
	}
}
