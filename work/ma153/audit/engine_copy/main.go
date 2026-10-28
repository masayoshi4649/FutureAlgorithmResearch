package main

import (
	"bufio"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

type rawBook struct {
	CurrentPriceTime *string
	Buy1, Sell1      struct{ Price float64 }
}
type Saved struct {
	Scene  Scene          `json:"scene"`
	Symbol string         `json:"symbol"`
	Counts map[string]int `json:"counts"`
	Cases  []*Result      `json:"cases"`
}

type Job struct {
	Scene  Scene
	Symbol string
}

// runJobs は商品と場だけを独立並列化し、各場内の原行順を維持します。
//
// 引数: jobs([]Job)、configs([]Config)、workers(int)、save(func(Saved) error)。
// 返り値: errorは再生又は保存の失敗。保存先ごとの既存検査は呼出前に完了させます。
func runJobs(jobs []Job, configs []Config, workers int, save func(Saved) error) error {
	if workers < 1 || workers > 4 {
		return errors.New("並列数は1〜4です")
	}
	queue := make(chan Job, len(jobs))
	failures := make(chan error, len(jobs))
	var group sync.WaitGroup
	for _, job := range jobs {
		queue <- job
	}
	close(queue)
	for i := 0; i < workers; i++ {
		group.Add(1)
		go func() {
			defer group.Done()
			for job := range queue {
				out, err := runScene(job.Scene, job.Symbol, configs)
				if err == nil {
					err = save(out)
				}
				if err != nil {
					failures <- fmt.Errorf("%s/%s: %w", job.Scene.Session, job.Symbol, err)
				}
			}
		}()
	}
	group.Wait()
	close(failures)
	var all []error
	for err := range failures {
		all = append(all, err)
	}
	return errors.Join(all...)
}

// readJSON は保存設定を読み込みます。
//
// 引数: path(string)、target(any)。返り値: errorは入出力又は構造不正です。
func readJSON(path string, target any) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	return json.Unmarshal(data, target)
}

// validateConfigs は第一巡26条件を固定した構成か検査します。
//
// 引数: configs([]Config)。返り値: errorは未知の条件又は値です。
func validateConfigs(configs []Config) error {
	if len(configs) != 26 {
		return errors.New("第一巡は26条件固定です")
	}
	n := 0
	for _, pair := range [][2]float64{{60, 30}, {180, 30}, {300, 60}, {600, 60}} {
		for _, allocation := range []string{"entry", "dynamic"} {
			for _, exit := range []string{"T", "Z", "D"} {
				n++
				expected := Config{fmt.Sprintf("M%02d", n), pair[0], pair[1], allocation, exit}
				if configs[n-1] != expected {
					return fmt.Errorf("固定条件が異なります: %s", expected.ID)
				}
			}
		}
	}
	for i, size := range []int{1, 10} {
		expected := Config{fmt.Sprintf("F%02d", size), 180, 30, fmt.Sprintf("fixed%d", size), "D"}
		if configs[24+i] != expected {
			return errors.New("固定枚数対照が異なります")
		}
	}
	return nil
}

// runScene は一商品一場を一度読み、26条件を同じ当時特徴で並行再生します。
//
// 引数: scene(Scene)、symbol(string)、configs([]Config)。返り値: Savedとerrorです。
// 1分足、Last、出来高、他商品の未来、研究期待損益は判断へ渡しません。
func runScene(scene Scene, symbol string, configs []Config) (Saved, error) {
	out := Saved{Scene: scene, Symbol: symbol, Counts: map[string]int{}}
	for _, config := range configs {
		out.Cases = append(out.Cases, newResult(scene, symbol, config))
	}
	file, err := os.Open(scene.Books[symbol])
	if err != nil {
		return out, err
	}
	defer file.Close()
	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 65536), 8*1024*1024)
	average := Average{}
	previous := scene.Start
	index := int64(0)
	line := int64(0)
	for scanner.Scan() {
		line++
		out.Counts["原行"]++
		var raw rawBook
		if err = json.Unmarshal(scanner.Bytes(), &raw); err != nil {
			return out, fmt.Errorf("%d行: %w", line, err)
		}
		if raw.CurrentPriceTime == nil {
			out.Counts["時計欠測"]++
			continue
		}
		clock, err := time.Parse(time.RFC3339Nano, *raw.CurrentPriceTime)
		if err != nil {
			out.Counts["時計欠測"]++
			continue
		}
		at := float64(clock.UnixNano()) / 1e9
		if at < scene.Start || at > scene.End || scene.Cutoff > 0 && at >= scene.Cutoff {
			out.Counts["範囲外"]++
			continue
		}
		if at < previous {
			out.Counts["時計逆行"]++
			continue
		}
		previous = at
		q := Quote{index, line, at, raw.Buy1.Price, raw.Sell1.Price}
		index++
		out.Counts["採用"]++
		if !quoteOK(q) {
			out.Counts["異常BBO"]++
		}
		if err = average.Add(q); err != nil {
			return out, err
		}
		features := [4]Feature{average.Get(60, 30), average.Get(180, 30), average.Get(300, 60), average.Get(600, 60)}
		for i, c := range out.Cases {
			f := features[1]
			if i < 24 {
				f = features[i/6]
			}
			if err = step(c, q, f); err != nil {
				return out, fmt.Errorf("%s/%s/%s/%d: %w", scene.Session, symbol, c.Config.ID, q.Index, err)
			}
		}
	}
	if err = scanner.Err(); err != nil {
		return out, err
	}
	for _, c := range out.Cases {
		if err = finish(c); err != nil {
			return out, fmt.Errorf("%s/%s/%s: %w", scene.Session, symbol, c.Config.ID, err)
		}
	}
	return out, nil
}

// registrationOK は事前照合登録の両成功条件を必須にします。
//
// 引数: path(string)。返り値: errorは未登録又は不成功です。
func registrationOK(path string) error {
	if path == "" {
		return errors.New("金融再生には登録受領が必要です")
	}
	var receipt struct {
		Registered bool
		Returncode *int
	}
	if err := readJSON(path, &receipt); err != nil {
		return err
	}
	if !receipt.Registered || receipt.Returncode == nil || *receipt.Returncode != 0 {
		return errors.New("登録成功が確認できません")
	}
	return nil
}

// main は登録後の保存52場・二商品の固定条件だけを一度再生します。
//
// 引数: OS引数。返り値: なし。金融再生前に設定・目録・既存出力を検査します。
func main() {
	registration := flag.String("registration", "", "登録受領JSON")
	manifest := flag.String("manifest", "../data/入力目録153.json", "固定入力目録")
	configPath := flag.String("configs", "../configs153.json", "固定26条件")
	output := flag.String("out", "../results_go", "未作成の結果フォルダ")
	workers := flag.Int("workers", 4, "独立商品・場の並列数（1〜4）")
	flag.Parse()
	if err := registrationOK(*registration); err != nil {
		panic(err)
	}
	var inputs struct{ Sessions []Scene }
	if err := readJSON(*manifest, &inputs); err != nil {
		panic(err)
	}
	if len(inputs.Sessions) != 52 {
		panic("固定目録は51完了場と既知途中1場です")
	}
	var configs []Config
	if err := readJSON(*configPath, &configs); err != nil {
		panic(err)
	}
	if err := validateConfigs(configs); err != nil {
		panic(err)
	}
	var jobs []Job
	for i := range inputs.Sessions {
		scene := &inputs.Sessions[i]
		if scene.Kind == "" {
			if strings.HasSuffix(scene.Session, "_Day") {
				scene.Kind = "Day"
			} else {
				scene.Kind = "Night"
			}
		}
		if (scene.Kind != "Day" && scene.Kind != "Night") || scene.Start >= scene.ForceClose || scene.ForceClose != scene.End-600 || !finite(scene.Start) || !finite(scene.End) {
			panic("固定セッション時刻が不正です: " + scene.Session)
		}
		for _, symbol := range []string{"NK225", "TOPIX"} {
			jobs = append(jobs, Job{*scene, symbol})
			path := filepath.Join(*output, scene.Session+"_"+symbol+".json")
			if _, err := os.Stat(path); !os.IsNotExist(err) {
				panic("結果は上書きしません: " + path)
			}
		}
	}
	if err := os.MkdirAll(*output, 0755); err != nil {
		panic(err)
	}
	if err := runJobs(jobs, configs, *workers, func(out Saved) error {
		data, err := json.MarshalIndent(out, "", "  ")
		if err != nil {
			return err
		}
		path := filepath.Join(*output, out.Scene.Session+"_"+out.Symbol+".json")
		if err = os.WriteFile(path, data, 0644); err != nil {
			return err
		}
		fmt.Printf("%s %s: 原行%d、26条件完了\n", out.Scene.Session, out.Symbol, out.Counts["採用"])
		return nil
	}); err != nil {
		panic(err)
	}
}
