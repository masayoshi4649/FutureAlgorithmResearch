package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	"ose-future/e01/internal/config"
	"ose-future/e01/internal/runner"
)

// main はOS共通の入口でE01を開始します。
//
// 引数: コマンドライン引数をflagで読み込みます。
// 返り値: なし。運転失敗時は終了コード1です。
func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "E01を停止しました:", err)
		os.Exit(1)
	}
}

// run は設定を読み、停止信号を連続運転へ渡します。
//
// 引数: なし。返り値: error。設定または運転エラー。
func run() error {
	conf := flag.String("conf", "conf", "conf/*.tomlを読むフォルダ")
	duration := flag.Duration("duration", 0, "試運転時間。例180s、0で連続運転")
	dryrun := flag.Bool("dryrun", false, "設定にかかわらず実注文を禁止する")
	logDir := flag.String("log-dir", "", "取引記録の保存先を変更する")
	stateDir := flag.String("state-dir", "", "復旧状態の保存先を変更する")
	check := flag.Bool("check", false, "設定の検査だけで終了する")
	flag.Parse()
	if flag.NArg() > 0 {
		return fmt.Errorf("未対応の引数です: %v", flag.Args())
	}
	if *duration < 0 {
		return fmt.Errorf("試運転時間に負数は指定できません")
	}
	cfg, err := config.Load(*conf)
	if err != nil {
		return err
	}
	if *dryrun {
		cfg.Trading.DryRun = true
	}
	if *logDir != "" {
		cfg.Runtime.LogDirectory = *logDir
	}
	if *stateDir != "" {
		cfg.Runtime.StateDirectory = *stateDir
	}
	if err = cfg.Validate(); err != nil {
		return err
	}
	if *check {
		fmt.Printf("設定正常: %s / 初回%d枚 / 片方向最大%d枚 / dryrun=%t\n", cfg.Trading.Symbol, cfg.Trading.InitialQuantity, cfg.Trading.MaxPositionPerSide, cfg.Trading.DryRun)
		return nil
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	return runner.Run(ctx, cfg, runner.Options{Duration: time.Duration(*duration), Output: os.Stdout})
}
