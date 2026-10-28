package main

import (
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"
)

type Saved struct {
	Scene Scene    `json:"scene"`
	Cases []Result `json:"cases"`
}

// executeJobs は場ごとの独立状態を最大4並列で再生し、各結果を一度だけ保存します。
//
// 引数: scenes([]Scene)、method/output(string)、configs([]Variant)、expressions(map[string]string)、workers(int)。
// 返り値: errorは一件以上の再生・保存失敗です。場内の原行順と条件順を変えません。
func executeJobs(scenes []Scene, method, output string, configs []Variant, expressions map[string]string, workers int) error {
	if workers < 1 || workers > 4 {
		return fmt.Errorf("並列数は1～4です")
	}
	for _, s := range scenes {
		if s.Kind != "Day" && s.Kind != "Night" {
			return fmt.Errorf("昼夜区分不正 %s", s.Session)
		}
		if _, e := os.Stat(filepath.Join(output, s.Session+"_"+method+".json")); !os.IsNotExist(e) {
			return fmt.Errorf("既存結果又は保存先不正 %s", s.Session)
		}
	}
	if e := os.MkdirAll(output, 0700); e != nil {
		return e
	}
	jobs := make(chan Scene)
	failures := make(chan error, len(scenes))
	var wg sync.WaitGroup
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for scene := range jobs {
				began := time.Now()
				result, e := runScene(scene, method, configs, expressions)
				if e == nil {
					e = saveResult(filepath.Join(output, scene.Session+"_"+method+".json"), Saved{Scene: scene, Cases: result})
				}
				if e != nil {
					failures <- fmt.Errorf("%s: %w", scene.Session, e)
				} else {
					fmt.Printf("完了 %s 条件%d 所要%s\n", scene.Session, len(result), time.Since(began).Round(time.Millisecond))
				}
			}
		}()
	}
	for _, s := range scenes {
		jobs <- s
	}
	close(jobs)
	wg.Wait()
	close(failures)
	for e := range failures {
		return e
	}
	return nil
}
