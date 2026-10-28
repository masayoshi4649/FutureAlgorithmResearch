// 156はS01の全担当へ玉別利益床を追加する隔離研究です。通信・実注文機能はありません。
package main

import (
	"errors"
	"flag"
	"fmt"
	"os"

	"futurealgorithm/sessiontrader/internal/rules"
)

type Scene struct {
	Session    string                       `json:"session"`
	Kind       string                       `json:"kind"`
	Start      float64                      `json:"start"`
	USOpen     float64                      `json:"us_open"`
	ForceClose float64                      `json:"force_close"`
	End        float64                      `json:"end"`
	Cutoff     float64                      `json:"cutoff"`
	Partial    bool                         `json:"partial"`
	Books      map[string]string            `json:"books"`
	Candles    map[string]map[string]string `json:"candles"`
}

// main は受領後に固定27日中場・18条件を再生し、既存結果への上書きを拒否します。
//
// 引数: manifest/configs/registration/out/workersは実行引数。返り値: なし。失敗は終了コード1です。
func main() {
	manifest := flag.String("manifest", "../../inputs156.json", "固定入力")
	configsPath := flag.String("configs", "../configs1562.json", "固定18条件")
	receipt := flag.String("registration", "", "登録受領")
	output := flag.String("out", "../results_go", "新規出力先")
	workers := flag.Int("workers", 8, "独立場の並列1～8")
	flag.Parse()
	fail := func(err error) { fmt.Fprintln(os.Stderr, err); os.Exit(1) }
	if err := registrationOK(*receipt); err != nil {
		fail(err)
	}
	var manifestData struct {
		Sessions []Scene `json:"sessions"`
	}
	if err := readJSON(*manifest, &manifestData); err != nil {
		fail(err)
	}
	complete, partial := 0, 0
	for _, s := range manifestData.Sessions {
		if s.Kind != "Day" {
			fail(errors.New("156は日中のみです"))
		}
		if s.Partial {
			partial++
		} else {
			complete++
		}
	}
	if complete != 26 || partial != 1 {
		fail(errors.New("固定26完了場と途中1場が必要です"))
	}
	var configs []Variant
	if err := readJSON(*configsPath, &configs); err != nil {
		fail(err)
	}
	if err := validateConfigs(configs); err != nil {
		fail(err)
	}
	ruleset, err := rules.LoadFor("NK225_S01.toml", "s01")
	if err != nil {
		fail(err)
	}
	if err = executeJobs(manifestData.Sessions, "S01", *output, configs, ruleset.Expressions(), *workers); err != nil {
		fail(err)
	}
}
