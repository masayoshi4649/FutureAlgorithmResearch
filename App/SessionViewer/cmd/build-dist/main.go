// 表示アプリをCGOなしでWindows・Linux向けに配布します。
package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// copyFile は配布文書をコピーし、設定ファイルは既存値を保持します。
//
// 引数: source/target(string)、preserve(bool)。返り値: error。
func copyFile(source, target string, preserve bool) error {
	if preserve {
		if _, err := os.Stat(target); err == nil {
			return nil
		}
	}
	data, err := os.ReadFile(source)
	if err != nil {
		return err
	}
	if err = os.MkdirAll(filepath.Dir(target), 0755); err != nil {
		return err
	}
	return os.WriteFile(target, data, 0644)
}

// build は同一ソースから2環境のバイナリ・設定・仕様を生成します。
//
// 引数: なし。返り値: error。App/SessionViewerで実行し、原板をコピーしません。
func build() error {
	for _, platform := range []string{"windows", "linux"} {
		base := filepath.Join("dist", platform+"-amd64", "SessionViewer")
		if err := os.MkdirAll(base, 0755); err != nil {
			return err
		}
		name := "session-viewer"
		if platform == "windows" {
			name += ".exe"
		}
		command := exec.Command("go", "build", "-trimpath", "-ldflags=-s -w", "-o", filepath.Join(base, name), ".")
		for _, value := range os.Environ() {
			key := strings.ToUpper(strings.SplitN(value, "=", 2)[0])
			if key != "GOOS" && key != "GOARCH" && key != "CGO_ENABLED" {
				command.Env = append(command.Env, value)
			}
		}
		command.Env = append(command.Env, "GOOS="+platform, "GOARCH=amd64", "CGO_ENABLED=0")
		command.Stdout, command.Stderr = os.Stdout, os.Stderr
		if err := command.Run(); err != nil {
			return err
		}
		for _, doc := range []string{"conf/viewer.toml", "README.md", "docs/データ仕様.md", "docs/画像API.md"} {
			if err := copyFile(doc, filepath.Join(base, filepath.FromSlash(doc)), doc == "conf/viewer.toml"); err != nil {
				return err
			}
		}
		if err := copyFile("conf/viewer.toml", filepath.Join(base, "conf", "viewer.toml.sample"), false); err != nil {
			return err
		}
		fmt.Println("配布先:", base)
	}
	return nil
}

// main は配布生成の失敗を終了コードに反映します。
//
// 引数: なし。返り値: なし。表示アプリ本体の起動ではありません。
func main() {
	if err := build(); err != nil {
		fmt.Fprintln(os.Stderr, "配布生成失敗:", err)
		os.Exit(1)
	}
}
