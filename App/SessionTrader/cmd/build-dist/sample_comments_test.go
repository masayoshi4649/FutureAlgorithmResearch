package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"futurealgorithm/sessiontrader/internal/config"
	"github.com/BurntSushi/toml"
)

// TestProductSamplesKeepExplanations は各商品・各OSに最小設定とすべての説明が届くことを確認します。
//
// 引数: t(*testing.T) は試験です。返り値: なし。
// 配布物のビルドは模擬し、設定の説明と有効・無効の意味だけを検査します。
func TestProductSamplesKeepExplanations(t *testing.T) {
	root := fixture(t)
	if err := buildDistribution(root, fakeBuild); err != nil {
		t.Fatal(err)
	}
	for _, platform := range []string{"windows-amd64", "linux-amd64"} {
		for _, product := range []string{"TOPIX", "TOPIXmini", "NK225", "NK225mini", "NK225micro"} {
			directory := filepath.Join(root, "dist", platform, product, "conf")
			data, err := os.ReadFile(filepath.Join(directory, "settings.toml.sample"))
			if err != nil {
				t.Fatal(err)
			}
			for _, line := range strings.Split(sampleConfiguration, "\n") {
				if strings.HasPrefix(strings.TrimSpace(line), "#") && !strings.Contains(string(data), line) {
					t.Errorf("%s/%sで説明が失われました: %s", platform, product, line)
				}
			}
			var decoded map[string]any
			if _, err := toml.Decode(string(data), &decoded); err != nil {
				t.Fatal(err)
			}
			count := 0
			for _, value := range decoded {
				table, ok := value.(map[string]any)
				if !ok {
					t.Fatal("最小設定のテーブル構成が変わりました")
				}
				count += len(table)
			}
			if len(decoded) != 6 || count != 13 {
				t.Fatalf("最小設定へ不要な既定値が出力されました: %dテーブル/%d項目", len(decoded), count)
			}
			night := "T04"
			if strings.HasPrefix(product, "NK225") {
				night = "U06"
			}
			cfg, err := config.Load(directory)
			if err != nil || cfg.MethodID("Day") != "T06" || cfg.MethodID("Night") != night {
				t.Fatalf("商品別の昼夜手法が違います: %+v %v", cfg.Methods, err)
			}
		}
	}
}

// TestCommentRefreshPreservesUserValues は説明の再配布で利用者の設定値を上書きしないことを確認します。
//
// 引数: t(*testing.T) は試験です。返り値: なし。
func TestCommentRefreshPreservesUserValues(t *testing.T) {
	root := fixture(t)
	if err := buildDistribution(root, fakeBuild); err != nil {
		t.Fatal(err)
	}
	directory := filepath.Join(root, "dist", "windows-amd64", "TOPIXmini", "conf")
	path := filepath.Join(directory, "settings.toml")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	custom := strings.Replace(string(data), "dryrun = true", "dryrun = false", 1)
	custom = strings.Replace(custom, "max_per_side = 10", "max_per_side = 6", 1)
	write(t, path, custom)
	updated := strings.Replace(sampleConfiguration, "# 片方向上限の説明。", "# 片方向上限の説明を更新。返済後は再新規できます。", 1)
	write(t, filepath.Join(root, "conf", "setting.toml.sample"), updated)
	if err = buildDistribution(root, fakeBuild); err != nil {
		t.Fatal(err)
	}
	retained, err := os.ReadFile(path)
	if err != nil || string(retained) != custom {
		t.Fatal("既存の実設定を変更しました", err)
	}
	cfg, err := config.Load(directory)
	_, selected := cfg.Selected()
	if err != nil || cfg.Trading.DryRun || selected.MaxPerSide != 6 {
		t.Fatalf("利用者が設定した有効値を保持していません: %+v %v", cfg, err)
	}
	sample, err := os.ReadFile(filepath.Join(directory, "settings.toml.sample"))
	if err != nil || !strings.Contains(string(sample), "# 片方向上限の説明を更新。返済後は再新規できます。") {
		t.Fatal("新しい説明をsampleへ配布していません", err)
	}
}

// TestUndocumentedKeyStopsBeforeBuild は無説明の追加キーを配布前に検出します。
//
// 引数: t(*testing.T) は試験です。返り値: なし。
func TestUndocumentedKeyStopsBeforeBuild(t *testing.T) {
	root := fixture(t)
	without := strings.Replace(sampleConfiguration, "# 仮想実行の説明。実設定は上書きしません。\n", "", 1)
	write(t, filepath.Join(root, "conf", "setting.toml.sample"), without)
	calls := 0
	err := buildDistribution(root, func(string, string, string) error {
		calls++
		return nil
	})
	if err == nil || !strings.Contains(err.Error(), "trading.dryrun") || calls != 0 {
		t.Fatalf("説明欠落をビルド前に検出できません: %d %v", calls, err)
	}
}

// TestQuotedAlgorithmOverrideKeepsValueAndExamples は引用符付きの実キーと無効化例を区別します。
//
// 引数: t(*testing.T) は試験です。返り値: なし。
func TestQuotedAlgorithmOverrideKeepsValueAndExamples(t *testing.T) {
	root := fixture(t)
	sample := sampleConfiguration + "\n[algorithm]\n# 共通上書きとして有効な損失幅の説明。\n\"day.risk_floor\" = 0.8\n# 幅の意味を説明した無効化例。\n# \"night.trail_width_r\" = 0.75\n"
	write(t, filepath.Join(root, "conf", "setting.toml.sample"), sample)
	if err := buildDistribution(root, fakeBuild); err != nil {
		t.Fatal(err)
	}
	directory := filepath.Join(root, "dist", "linux-amd64", "NK225micro", "conf")
	cfg, err := config.Load(directory)
	if err != nil || len(cfg.Algorithm) != 1 || cfg.Algorithm["day.risk_floor"] != .8 {
		t.Fatalf("有効な上書き値を変更しました: %+v %v", cfg.Algorithm, err)
	}
	data, err := os.ReadFile(filepath.Join(directory, "settings.toml.sample"))
	if err != nil || !strings.Contains(string(data), "# \"night.trail_width_r\" = 0.75") ||
		!strings.Contains(string(data), "# 共通上書きとして有効な損失幅の説明。") {
		t.Fatal("上書きの説明または無効化例が失われました", err)
	}
}

// TestRepositorySamplesCoverGeneratedKeys は実際に配布するサンプルの全実キーを検査します。
//
// 引数: t(*testing.T) は試験です。返り値: なし。
// 利用者の*.tomlは読まず、版管理対象の*.toml.sampleだけを一時領域へコピーします。
func TestRepositorySamplesCoverGeneratedKeys(t *testing.T) {
	stage := t.TempDir()
	if err := copyConfiguration(filepath.Join("..", "..", "conf"), filepath.Join(stage, "conf")); err != nil {
		t.Fatal(err)
	}
	cfg, err := config.Load(filepath.Join(stage, "conf"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err = prepareSingleConfigurations(stage, cfg); err != nil {
		t.Fatal(err)
	}
}

// TestScalarReplacementKeepsLiteralAndInlineComment は文字列と行末説明を混同しないことを確認します。
//
// 引数: t(*testing.T) は試験です。返り値: なし。
func TestScalarReplacementKeepsLiteralAndInlineComment(t *testing.T) {
	template := []byte("[market]\n# 発注商品の説明。\nproduct = 'TOPIX#mini' # 商品の行末説明。\n# 上限の説明。\nmax_per_side = 10\n")
	value := "引用符\"と改行\nを含む#文字列"
	data, err := replaceSampleScalars(template, []sampleReplacement{{"market", "product", value}})
	if err != nil {
		t.Fatal(err)
	}
	var decoded map[string]any
	if _, err := toml.Decode(string(data), &decoded); err != nil {
		t.Fatal(err)
	}
	market := decoded["market"].(map[string]any)
	if len(market) != 2 || market["product"] != value || market["max_per_side"] != int64(10) ||
		!strings.Contains(string(data), "# 商品の行末説明。") {
		t.Fatal("文字列の内容、別項目または行末説明が変わりました")
	}
	if _, err := replaceSampleScalars(template, []sampleReplacement{{"market", "unknown", 20}}); err == nil {
		t.Fatal("存在しない項目を差替えで追加しました")
	}
}

// TestUnknownMethodStopsBeforeBuild は未知の手法IDを含む配布元を出荷しないことを確認します。
//
// 引数: t(*testing.T) は試験です。返り値: なし。
func TestUnknownMethodStopsBeforeBuild(t *testing.T) {
	root := fixture(t)
	write(t, filepath.Join(root, "conf", "setting.toml.sample"), strings.Replace(sampleConfiguration, `day = "T06"`, `day = "T99"`, 1))
	calls := 0
	err := buildDistribution(root, func(string, string, string) error {
		calls++
		return nil
	})
	if err == nil || calls != 0 || !strings.Contains(err.Error(), "T99") {
		t.Fatalf("未知の手法IDをビルド前に拒否できません: %d %v", calls, err)
	}
}
