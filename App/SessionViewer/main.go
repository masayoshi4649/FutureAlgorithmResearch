// 保存済みの原板と約定・損益を、売買を行わずWebで表示します。
package main

import (
	"bufio"
	"context"
	"embed"
	"errors"
	"fmt"
	"io/fs"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"runtime"
	"syscall"
	"time"
)

//go:embed web/*
var webFiles embed.FS

// applicationBase は実行ファイルの隣の設定を優先し、go runでは作業フォルダへ補完します。
//
// 引数: なし。返り値: 設定の基準フォルダ(string)とerror。
// go runと実行ファイルの起動を、引数なしの同じ設定方式で扱います。
func applicationBase() (string, error) {
	executable, err := os.Executable()
	if err != nil {
		return "", err
	}
	base := filepath.Dir(executable)
	if info, e := os.Stat(filepath.Join(base, "conf", "viewer.toml")); e == nil && !info.IsDir() {
		return base, nil
	}
	current, err := os.Getwd()
	if err == nil {
		if info, e := os.Stat(filepath.Join(current, "conf", "viewer.toml")); e == nil && !info.IsDir() {
			return current, nil
		}
	}
	return base, nil
}

// run は設定を読み、埋込画面と読み取り用APIを同じポートで公開します。
//
// 引数: なし。返り値: errorは起動又は稼働失敗です。
func run() error {
	base, err := applicationBase()
	if err != nil {
		return err
	}
	cfg, err := LoadConfig(filepath.Join(base, "conf", "viewer.toml"), base)
	if err != nil {
		return fmt.Errorf("設定を読めません: %w", err)
	}
	api, err := NewServer(cfg)
	if err != nil {
		return err
	}
	assets, err := fs.Sub(webFiles, "web")
	if err != nil {
		return err
	}
	mux := http.NewServeMux()
	mux.Handle("/api/", api.Handler())
	mux.Handle("/", http.FileServer(http.FS(assets)))
	server := &http.Server{Addr: cfg.Server.Listen, Handler: mux, ReadHeaderTimeout: 5 * time.Second, IdleTimeout: 60 * time.Second}
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt, syscall.SIGTERM)
	defer signal.Stop(stop)
	go func() {
		<-stop
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = server.Shutdown(ctx)
	}()
	fmt.Printf("セッション可視化: http://localhost%s/\n", displayPort(cfg.Server.Listen))
	fmt.Printf("待受: %s / 原板: %s\n", cfg.Server.Listen, cfg.Paths.DataRoot)
	fmt.Println("リンク列挙ファイルを選ぶと、価格・売保有・買保有・確定損益・含み損益を表示します。")
	if err = server.ListenAndServe(); errors.Is(err, http.ErrServerClosed) {
		return nil
	}
	return err
}

// displayPort は案内用URLのポート部分を取り出します。
//
// 引数: listen(string)は待受先。返り値: stringはコロン付きポート又は元の文字列です。
func displayPort(listen string) string {
	for i := len(listen) - 1; i >= 0; i-- {
		if listen[i] == ':' {
			return listen[i:]
		}
	}
	return ":" + listen
}

// main はエラーを表示し、Windowsの対話コンソールでは確認まで画面を残します。
//
// 引数: なし。返り値: なし。失敗時は終了コード1です。
func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "起動できません:", err)
		if runtime.GOOS == "windows" {
			if info, e := os.Stdin.Stat(); e == nil && info.Mode()&os.ModeCharDevice != 0 {
				fmt.Fprintln(os.Stderr, "Enterキーで閉じます。")
				_, _ = bufio.NewReader(os.Stdin).ReadString('\n')
			}
		}
		os.Exit(1)
	}
}
