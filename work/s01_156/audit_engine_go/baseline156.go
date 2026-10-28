package main

import (
	"encoding/json"
	"fmt"
	"math"
	"path/filepath"
)

// baseline156 は完了場基準を保存155S01へ照合し、同じ元入口を比較していることを確認します。
//
// 引数: scene(Scene)、r(Result)。返り値: errorは通知・約定・会計の差です。
// 延長した当日15:20資料には同じ終点の対照がないので、この検査だけ対象外です。
func baseline156(scene Scene, r Result) error {
	if scene.Partial {
		return nil
	}
	var report struct {
		Cases []struct {
			Method     string  `json:"method"`
			Events     []Event `json:"events"`
			Gross      float64 `json:"gross"`
			Unrealized float64 `json:"unrealized"`
			Signals    int     `json:"signals"`
		} `json:"cases"`
	}
	path := filepath.Join("..", "..", "s01_155", "results", scene.Session+".json")
	if err := readJSON(path, &report); err != nil {
		return err
	}
	for _, expected := range report.Cases {
		if expected.Method != "S01" {
			continue
		}
		if len(r.Events) != len(expected.Events) || len(r.Signals) != expected.Signals || math.Abs(r.Gross-expected.Gross) > 1e-7 || math.Abs(r.Unrealized-expected.Unrealized) > 1e-7 {
			return fmt.Errorf("%s 基準の会計又は通知数差", scene.Session)
		}
		for i, event := range expected.Events {
			actual := r.Events[i]
			// Evidenceは当時の観測と判断を保持するが、追加診断キーの有無は経済条件の同値と区別する。
			actual.Pieces = nil
			event.Pieces = nil
			actual.Signal.Evidence = nil
			event.Signal.Evidence = nil
			a, _ := json.Marshal(actual)
			b, _ := json.Marshal(event)
			if string(a) != string(b) {
				return fmt.Errorf("%s 基準約定%d差", scene.Session, i)
			}
		}
		return nil
	}
	return fmt.Errorf("%s 保存S01基準がありません", scene.Session)
}
