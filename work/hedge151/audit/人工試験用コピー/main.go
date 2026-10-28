package main

import (
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"time"
)

// validateReceiptは登録済みの旗と登録コマンド成功の両方を要求します。
//
// 引数: receipt(map[string]any)。返り値: errorは未登録又は登録失敗です。
func validateReceipt(receipt map[string]any) error {
	if receipt["returncode"] != float64(0) || receipt["registered"] != true {
		return errors.New("登録完了を確認できません")
	}
	return nil
}

// validateConfigsは登録した条件以外が混ざることを拒否します。
//
// 引数: configs([]Config)。返り値: errorは固定条件と異なる場合です。
func validateConfigs(configs []Config) error {
	expected := fixedConfigs()
	if len(configs) != len(expected) {
		return fmt.Errorf("条件数が%dではありません", len(expected))
	}
	for i, cfg := range configs {
		cfg.Description = expected[i].Description
		if !reflect.DeepEqual(cfg, expected[i]) {
			return fmt.Errorf("固定条件と相違: %s", cfg.ID)
		}
	}
	return nil
}

// prepareInputは保存結果から入口の判断項目と会計専用の後半を分離して保存します。
//
// 引数: scene(Scene)、source/postSource/target(string)。返り値: errorは保存資料の不整合です。
// 原板による新たな金融再生は行いません。
func prepareInput(scene Scene, source, postSource, target string) error {
	raw, err := os.ReadFile(source)
	if err != nil {
		return err
	}
	notices, err := extractNotices(raw, scene)
	if err != nil {
		return err
	}
	post, err := loadPost(postSource)
	if err != nil {
		return err
	}
	return writeJSON(target, Input{Scene: scene, Source: source, Notices: notices, Post: post})
}

// mainは入力分離又は登録済み金融再生を実行します。
//
// 引数: CLIのmanifest/configs/inputs/source/post-source/registration/out/scene/prepare。
// 返り値: なし。金融再生には成功した登録受領が必須です。実注文の機能はありません。
func main() {
	manifest := flag.String("manifest", "../../preus149/data/原資料一覧149.json", "原資料一覧")
	configPath := flag.String("configs", "../configs151.json", "固定条件")
	inputs := flag.String("inputs", "../inputs", "分離済み入力")
	source := flag.String("source", "../../preus150/results_round2", "B04保存会計")
	postSource := flag.String("post-source", "../../preus149/results_round2", "S04保存会計")
	registration := flag.String("registration", "", "登録受領")
	output := flag.String("out", "../results_go", "結果先")
	only := flag.String("scene", "", "一場限定")
	prepare := flag.Bool("prepare", false, "保存会計から入力分離のみ")
	flag.Parse()
	var manifestValue struct {
		Sessions []Scene `json:"sessions"`
	}
	if err := readJSON(*manifest, &manifestValue); err != nil {
		panic(err)
	}
	if *prepare {
		if err := os.MkdirAll(*inputs, 0755); err != nil {
			panic(err)
		}
		for _, scene := range manifestValue.Sessions {
			if *only != "" && scene.Session != *only {
				continue
			}
			name := scene.Session + ".json"
			if err := prepareInput(scene, filepath.Join(*source, name), filepath.Join(*postSource, name), filepath.Join(*inputs, name)); err != nil {
				panic(err)
			}
			fmt.Println(scene.Session, "保存通知分離")
		}
		return
	}
	// ----------------------------------------
	// 金融再生は登録受領を検査してから原板を読みます。
	var receipt map[string]any
	if *registration == "" {
		panic("金融再生には登録受領が必要です")
	}
	if err := readJSON(*registration, &receipt); err != nil {
		panic(err)
	}
	if err := validateReceipt(receipt); err != nil {
		panic(err)
	}
	var configs []Config
	if err := readJSON(*configPath, &configs); err != nil {
		panic(err)
	}
	if err := validateConfigs(configs); err != nil {
		panic(err)
	}
	if err := os.MkdirAll(*output, 0755); err != nil {
		panic(err)
	}
	for _, scene := range manifestValue.Sessions {
		if *only != "" && scene.Session != *only {
			continue
		}
		started := time.Now()
		var input Input
		if err := readJSON(filepath.Join(*inputs, scene.Session+".json"), &input); err != nil {
			panic(err)
		}
		if !reflect.DeepEqual(input.Scene, scene) {
			panic("分離入力と原資料一覧の場定義不一致")
		}
		quotes, counts, err := loadQuotes(scene)
		if err != nil {
			panic(err)
		}
		cases, err := replay(input, quotes, configs)
		if err != nil {
			panic(err)
		}
		value := map[string]any{"scene": scene, "cases": cases, "counts": counts, "source_notices": input.Notices, "fees": 0, "real_orders": 0, "price": "判断後の次正常ラージBBO代理", "elapsed_seconds": time.Since(started).Seconds()}
		if err := writeJSON(filepath.Join(*output, scene.Session+".json"), value); err != nil {
			panic(err)
		}
		fmt.Println(scene.Session, "完了", time.Since(started))
	}
}
