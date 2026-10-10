// 配布用の実行ファイルと設定サンプルを作成します。
package main

import (
	_ "embed"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"ose-future/e01/internal/config"
)

//go:embed README.dist.md
var distributionReadme []byte

// main は、App/E01 を起点に Windows / Linux の配布物を作ります。
//
// 引数: なし。作業ディレクトリと Go の実行環境を使用します。
// 返り値: なし。失敗時は終了コード1を返します。
func main() {
	root, err := os.Getwd()
	if err == nil {
		err = buildDistribution(root)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "配布物の作成に失敗しました:", err)
		os.Exit(1)
	}
	fmt.Println("dist に Windows / Linux の実行ファイルと設定サンプルを作成しました。既存の実設定・記録・状態は保持しています。")
}

// ----------------------------------------

// buildDistribution は、両環境のビルド成功後に配布ファイルを配置します。
//
// 引数: root string。App/E01 の絶対パス。
// 返り値: error。ビルド・設定検証・配置が失敗した場合の原因です。
func buildDistribution(root string) error {
	module, err := os.ReadFile(filepath.Join(root, "go.mod"))
	if err != nil || !strings.Contains(string(module), "module ose-future/e01") {
		return fmt.Errorf("App/E01 フォルダから go run ./cmd/build-dist を実行してください")
	}
	destination := filepath.Join(root, "dist")
	if err = os.MkdirAll(destination, 0755); err != nil {
		return err
	}
	stage, err := os.MkdirTemp(destination, ".build-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(stage)
	if err = copyConfiguration(filepath.Join(root, "conf"), filepath.Join(stage, "conf")); err != nil {
		return err
	}
	cfg, err := config.Load(filepath.Join(stage, "conf"))
	if err != nil {
		return fmt.Errorf("設定サンプルの検証: %w", err)
	}
	if !cfg.Trading.DryRun {
		return fmt.Errorf("配布用 trade.toml.sample の DryRun は true にしてください")
	}

	// ----------------------------------------

	targets := []struct{ goos, name string }{
		{"windows", "e01.exe"},
		{"linux", "e01-linux-amd64"},
	}
	for _, target := range targets {
		fmt.Printf("%s / amd64 をビルドします。\n", target.goos)
		command := exec.Command("go", "build", "-trimpath", "-o", filepath.Join(stage, target.name), ".")
		command.Dir = root
		command.Env = buildEnvironment(target.goos)
		command.Stdout, command.Stderr = os.Stdout, os.Stderr
		if err = command.Run(); err != nil {
			return fmt.Errorf("%s のビルド: %w", target.goos, err)
		}
	}
	if err = copyConfiguration(filepath.Join(root, "conf"), filepath.Join(destination, "conf")); err != nil {
		return err
	}
	if err = os.WriteFile(filepath.Join(destination, "README.md"), distributionReadme, 0644); err != nil {
		return err
	}
	for _, target := range targets {
		if err = os.Rename(filepath.Join(stage, target.name), filepath.Join(destination, target.name)); err != nil {
			return fmt.Errorf("%s を更新できません。実行中のプログラムは停止していません: %w", target.name, err)
		}
	}
	return nil
}

// buildEnvironment は、他の環境変数を保持してクロスビルド条件を設定します。
//
// 引数: goos string。windows または linux。
// 返り値: []string。amd64・CGO無効の子プロセス用環境変数です。
func buildEnvironment(goos string) []string {
	environment := []string{}
	for _, value := range os.Environ() {
		key, _, _ := strings.Cut(value, "=")
		switch strings.ToUpper(key) {
		case "GOOS", "GOARCH", "CGO_ENABLED":
			continue
		}
		environment = append(environment, value)
	}
	return append(environment, "GOOS="+goos, "GOARCH=amd64", "CGO_ENABLED=0")
}

// ----------------------------------------

// copyConfiguration は、独立したサンプルだけを配布し、未作成の実設定を補います。
//
// 引数: source string はサンプル元、destination string は配置先の設定フォルダ。
// 返り値: error。読み書きに失敗した場合の原因。既存の実設定は上書きしません。
func copyConfiguration(source, destination string) error {
	names, err := filepath.Glob(filepath.Join(source, "*.toml.sample"))
	if err != nil {
		return err
	}
	if len(names) == 0 {
		return fmt.Errorf("%s に設定サンプルがありません", source)
	}
	if err = os.MkdirAll(destination, 0755); err != nil {
		return err
	}
	for _, name := range names {
		data, err := os.ReadFile(name)
		if err != nil {
			return err
		}
		base := filepath.Base(name)
		if err = os.WriteFile(filepath.Join(destination, base), data, 0644); err != nil {
			return err
		}
		actual := filepath.Join(destination, strings.TrimSuffix(base, ".sample"))
		file, err := os.OpenFile(actual, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if os.IsExist(err) {
			continue
		}
		if err != nil {
			return err
		}
		_, writeErr := file.Write(data)
		closeErr := file.Close()
		if writeErr != nil {
			return writeErr
		}
		if closeErr != nil {
			return closeErr
		}
	}
	return nil
}
