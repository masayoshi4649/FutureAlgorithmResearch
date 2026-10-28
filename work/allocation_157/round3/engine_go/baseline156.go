package main

import (
	"encoding/json"
	"fmt"
	"math"
	"path/filepath"
)

// baseline156 は3対照を第2巡保存結果へ全通知・所有玉・会計まで照合します。
//
// 引数: scene(Scene)、r(Result)。返り値: errorは対照の不一致です。
// 途中の15:20保存対照も同じ入力なので対象です。保存結果を取引判断へ渡しません。
func baseline156(scene Scene, r Result) error {
	var expected Saved
	path := filepath.Join("..", "..", "round2", "results_go", scene.Session+"_S01.json")
	if err := readJSON(path, &expected); err != nil {
		return err
	}
	for _, c := range expected.Cases {
		if c.Variant.ID != r.Variant.ID {
			continue
		}
		if len(c.Events) != len(r.Events) || len(c.Signals) != len(r.Signals) || math.Abs(c.Gross-r.Gross) > 1e-7 || math.Abs(c.Unrealized-r.Unrealized) > 1e-7 {
			return fmt.Errorf("%s/%s 第2巡との会計差", scene.Session, r.Variant.ID)
		}
		for i, want := range c.Events {
			got := r.Events[i]
			got.Signal.Evidence = nil
			want.Signal.Evidence = nil
			a, _ := json.Marshal(got)
			b, _ := json.Marshal(want)
			if string(a) != string(b) {
				return fmt.Errorf("%s/%s 約定%d差", scene.Session, r.Variant.ID, i)
			}
		}
		for i, want := range c.Signals {
			got := r.Signals[i]
			got.Evidence = nil
			want.Evidence = nil
			a, _ := json.Marshal(got)
			b, _ := json.Marshal(want)
			if string(a) != string(b) {
				return fmt.Errorf("%s/%s 通知%d差", scene.Session, r.Variant.ID, i)
			}
		}
		for _, pair := range [][2]any{{c.Entries, r.Entries}, {c.Parents, r.Parents}, {c.FinalPending, r.FinalPending}} {
			a, _ := json.Marshal(pair[0])
			b, _ := json.Marshal(pair[1])
			if string(a) != string(b) {
				return fmt.Errorf("%s/%s 最終玉又は親差", scene.Session, r.Variant.ID)
			}
		}
		return nil
	}
	return fmt.Errorf("%s/%s 第2巡対照なし", scene.Session, r.Variant.ID)
}
