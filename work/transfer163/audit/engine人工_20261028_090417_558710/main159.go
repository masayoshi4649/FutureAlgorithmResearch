package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"futurealgorithm/sessiontrader/internal/rules"
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"sync"
	"time"
)

type Transition159 struct {
	Phase        string
	At           float64
	Index        int64
	PreviousFlat bool
}
type Saved159 struct {
	Scene       Scene              `json:"scene"`
	Cases       []*PolicyResult157 `json:"cases"`
	Sources     []*SourceState159  `json:"sources"`
	Counts      map[string]int     `json:"counts"`
	Transitions []Transition159    `json:"transitions"`
	ExactChecks int                `json:"exact_checks"`
}

// verifyExact159 は元Sourceの全約定と同額N00の全数量・所有配賦・価格を照合します。
//
// 引数: result(*Saved159)。返り値: errorは源との不一致です。
func verifyExact159(result *Saved159) error {
	expected := []SourceEvent159{}
	gross := 0.0
	for _, s := range result.Sources {
		for _, ev := range s.Events {
			mapped, e := s.policySignal159(ev.Signal)
			if e != nil {
				return e
			}
			ev.Signal = mapped
			expected = append(expected, ev)
		}
		gross += s.Gross
		if !s.flat159() {
			return errors.New("完了場のSource未返済")
		}
	}
	base := result.Cases[0]
	if base.Config.ID != "N00" || len(base.Actual.Events) != len(expected) {
		return errors.New("N00の約定数不一致")
	}
	for i, old := range expected {
		sig := namespace159(old.Signal, old.Phase)
		got := base.Actual.Events[i]
		if got.Order.ID != sig.ID || got.Order.Owner != sig.Owner || got.Order.Side != sig.Side || got.Order.Quantity != sig.Quantity*10 || got.Order.DecisionIndex != sig.SourceIndex || got.Order.DecisionTime != sig.Time || got.FillIndex != old.FillIndex || got.FillTime != old.FillTime || got.Price != old.Price || math.Abs(got.Gross-old.Gross) > 1e-7 {
			return fmt.Errorf("N00約定%d不一致", i)
		}
		if len(got.Order.Targets) != len(sig.Targets) {
			return errors.New("N00配賦数不一致")
		}
		for j, t := range sig.Targets {
			if got.Order.Targets[j].ID != t.ID || got.Order.Targets[j].Quantity != t.Quantity*10 {
				return errors.New("N00所有配賦不一致")
			}
		}
		result.ExactChecks++
	}
	if math.Abs(base.Actual.Realized-gross) > 1e-7 {
		return errors.New("N00元Source収支不一致")
	}
	return nil
}

// run159 は共通指標を継続し、時間枠ごとに新しい元手法と固定数量候補を進めます。
//
// 引数: scene(Scene)、configs([]Policy157)、sets(map[string]map[string]string)。返り値: Saved159とerror。
func run159(scene Scene, configs []Policy157, sets map[string]map[string]string) (Saved159, error) {
	result := Saved159{Scene: scene}
	rows, counts, e := loadBoards(scene)
	if e != nil {
		return result, e
	}
	result.Counts = counts
	f, e := newFeatures(scene, scene.Start)
	if e != nil {
		return result, e
	}
	chosen := configs
	if scene.Kind == "Day" {
		chosen = []Policy157{configs[0], configs[2]}
	}
	for _, c := range chosen {
		result.Cases = append(result.Cases, newPolicy157(c, scene))
	}
	phase, method := "前半", "P05"
	if scene.Kind == "Day" {
		phase, method = "日中", "S01"
	}
	source, e := newSource159(scene, phase, method, sets[method])
	if e != nil {
		return result, e
	}
	result.Sources = append(result.Sources, source)
	result.Transitions = append(result.Transitions, Transition159{Phase: phase, At: scene.Start, Index: -1, PreviousFlat: true})
	support := &SupportBuilder157{}
	for _, board := range rows {
		support.add(board)
		o, e := f.OnBoard(board)
		if e != nil {
			return result, e
		}
		if o.Reference != "NK225" {
			continue
		}
		ss := map[int]Support157{1: support.get(o.Time, 1), -1: support.get(o.Time, -1)}
		signals := []strategy.Signal{}
		// 時間枠は当時観測された時計だけで切り替え、前半の確定を後半Sourceへ引き継ぎません。
		if scene.Kind == "Night" && phase == "前半" && o.Time >= scene.USOpen+900 {
			oldSignals, e := source.step159(o, false, ss)
			if e != nil {
				return result, e
			}
			signals = append(signals, oldSignals...)
			if source.flat159() {
				phase = "後半"
				source, e = newSource159(scene, phase, "D07", sets["D07"])
				if e != nil {
					return result, e
				}
				result.Sources = append(result.Sources, source)
				result.Transitions = append(result.Transitions, Transition159{Phase: phase, At: o.Time, Index: o.Index, PreviousFlat: true})
				next, e := source.step159(o, o.Time < scene.ForceClose, ss)
				if e != nil {
					return result, e
				}
				signals = append(signals, next...)
			}
		} else {
			allow := o.Time < scene.ForceClose
			if scene.Kind == "Night" && phase == "前半" {
				allow = o.Time < scene.USOpen-900
			}
			signals, e = source.step159(o, allow, ss)
			if e != nil {
				return result, e
			}
		}
		for i, r := range result.Cases {
			original := chosen[i]
			r.Config = effective159(original, phase)
			if e = stepPolicy159(r, o, signals, ss); e != nil {
				return result, fmt.Errorf("%s/%s:%w", scene.Session, original.ID, e)
			}
			r.Config = original
		}
	}
	for _, c := range result.Cases {
		if len(c.Actual.Active) > 0 || len(c.Actual.Pending) > 0 {
			return result, fmt.Errorf("%sの場末未返済", c.Config.ID)
		}
	}
	if e = verifyExact159(&result); e != nil {
		return result, e
	}
	return result, nil
}

// save159 は新規ファイルだけをUTF-8 JSONとして保存します。
//
// 引数: path(string)、v(any)。返り値: errorは既存又は書込失敗です。
func save159(path string, v any) error {
	b, e := json.Marshal(v)
	if e != nil {
		return e
	}
	f, e := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if e != nil {
		return e
	}
	defer f.Close()
	_, e = f.Write(append(b, '\n'))
	return e
}

// registration159 は登録成功が明示されていない金融再生を拒否します。
//
// 引数: path(string)。返り値: errorは受領不足です。
func registration159(path string) error {
	if path == "" {
		return errors.New("金融再生には登録受領が必要です")
	}
	var v struct {
		Registered bool
		Returncode *int
	}
	if e := readJSON(path, &v); e != nil {
		return e
	}
	if !v.Registered || v.Returncode == nil || *v.Returncode != 0 {
		return errors.New("登録成功を確認できません")
	}
	return nil
}

// execute159 は既存結果を上書きせず、場独立で登録済み候補を再生します。
//
// 引数: scenes([]Scene)、configs([]Policy157)、sets(map[string]map[string]string)、out(string)、workers(int)。返り値: error。
func execute159(scenes []Scene, configs []Policy157, sets map[string]map[string]string, out string, workers int) error {
	if workers < 1 || workers > 8 {
		return errors.New("並列数は1〜8です")
	}
	if e := os.MkdirAll(out, 0700); e != nil {
		return e
	}
	for _, s := range scenes {
		if _, e := os.Stat(filepath.Join(out, s.Session+".json")); !os.IsNotExist(e) {
			return errors.New("保存先に既存結果があります")
		}
	}
	jobs := make(chan Scene)
	errs := make(chan error, len(scenes))
	var wg sync.WaitGroup
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for s := range jobs {
				t := time.Now()
				v, e := run159(s, configs, sets)
				if e == nil {
					e = save159(filepath.Join(out, s.Session+".json"), v)
				}
				if e != nil {
					errs <- fmt.Errorf("%s:%w", s.Session, e)
				} else {
					fmt.Printf("完了 %s %d条件 所要%s\n", s.Session, len(v.Cases), time.Since(t).Round(time.Millisecond))
				}
			}
		}()
	}
	for _, s := range scenes {
		jobs <- s
	}
	close(jobs)
	wg.Wait()
	close(errs)
	for e := range errs {
		return e
	}
	return nil
}

// main は人工検証から分離した登録後の金融再生入口です。
//
// 引数: manifest/configs/registration/out/workersのCLI。返り値: なし。失敗時は終了コード1です。
func legacyMain159() {
	manifest := flag.String("manifest", "../../audit159/inputs159.json", "固定原資料目録")
	cfg := flag.String("configs", "../configs159.json", "固定十二政策")
	receipt := flag.String("registration", "", "登録受領")
	out := flag.String("out", "../results_go", "新規結果保存")
	workers := flag.Int("workers", 4, "場独立並列")
	export := flag.String("export-configs", "", "人工準備用の候補出力")
	flag.Parse()
	fail := func(e error) { fmt.Fprintln(os.Stderr, e); os.Exit(1) }
	if *export != "" {
		if e := save159(*export, configs159()); e != nil {
			fail(e)
		}
		return
	}
	if e := registration159(*receipt); e != nil {
		fail(e)
	}
	var input struct{ Sessions []Scene }
	if e := readJSON(*manifest, &input); e != nil {
		fail(e)
	}
	night, day := 0, 0
	for _, s := range input.Sessions {
		if s.Partial {
			fail(errors.New("途中場は今回の主再生対象外です"))
		}
		if s.Kind == "Night" {
			night++
		} else if s.Kind == "Day" {
			day++
		} else {
			fail(errors.New("種別不明"))
		}
	}
	if night != 26 || day != 1 {
		fail(errors.New("固定26Nightと追加完了1Dayが必要です"))
	}
	var configs []Policy157
	if e := readJSON(*cfg, &configs); e != nil {
		fail(e)
	}
	if !reflect.DeepEqual(configs, configs159()) {
		fail(errors.New("固定候補と設定が不一致です"))
	}
	sets := map[string]map[string]string{}
	for _, method := range []string{"D07", "P05", "S01"} {
		name := map[string]string{"D07": "d07", "P05": "p05", "S01": "s01"}[method]
		set, e := rules.LoadFor("rules/NK225_"+method+".toml", name)
		if e != nil {
			fail(e)
		}
		sets[method] = set.Expressions()
	}
	if e := execute159(input.Sessions, configs, sets, *out, *workers); e != nil {
		fail(e)
	}
}
