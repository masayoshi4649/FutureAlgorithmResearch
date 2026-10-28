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
	"sync"
	"time"
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
type Saved157 struct {
	Scene  Scene              `json:"scene"`
	Cases  []*PolicyResult157 `json:"cases"`
	Source Result             `json:"source"`
	Counts map[string]int     `json:"counts"`
}

// step157 は現在原行で実約定・支持・数量政策を順番に評価します。
//
// 引数: r(*PolicyResult157)、o(Observation)、signals([]Signal)、supports(map[int]Support157)。返り値: error。
func step157(r *PolicyResult157, o strategy.Observation, signals []strategy.Signal, supports map[int]Support157) error {
	r.ObservationEnd = o.Time
	r.Canonical.mark(o)
	if r.Actual != r.Canonical {
		r.Actual.mark(o)
	}
	fills, err := r.Canonical.fill(o)
	if err != nil {
		return err
	}
	r.afterFills157(fills, o)
	if r.Actual != r.Canonical {
		if _, err = r.Actual.fill(o); err != nil {
			return err
		}
	}
	r.Canonical.mark(o)
	if r.Actual != r.Canonical {
		r.Actual.mark(o)
	}
	// ----------------------------------------
	// 新しい判断前に親別の純量一致を確認します。買売の清算時価一致は要求しません。
	if normal(o) && r.Actual != r.Canonical {
		for _, key := range sortedParents157(r.Parents) {
			cl, cs := r.Canonical.position(key, "")
			al, as := r.Actual.position(key, "")
			diff := float64((cl - cs) - (al - as))
			r.ProjectionChecks++
			r.ProjectionMaxDifference = math.Max(r.ProjectionMaxDifference, math.Abs(diff))
			if diff != 0 {
				return fmt.Errorf("親内純量差 %s canonical=%d actual=%d", key, cl-cs, al-as)
			}
		}
	}
	if r.Config.Exact {
		r.source157(o, signals, supports)
	} else {
		closes, news := []strategy.Signal{}, []strategy.Signal{}
		for _, s := range signals {
			if s.Action == "close" {
				closes = append(closes, s)
			} else {
				news = append(news, s)
			}
		}
		r.source157(o, closes, supports)
		r.manage157(o, supports, true)
		r.source157(o, news, supports)
		r.manage157(o, supports, false)
	}
	r.project157(o)
	for _, p := range r.Parents {
		cl, cs := r.Canonical.position(p.Key, "")
		al, as := r.Actual.position(p.Key, "")
		p.Finished = (p.SourceQty == 0 || p.Blocked != "" || p.Rejected != "") && cl+cs+al+as == 0 && !r.Canonical.hasPending(p.Key) && !r.Actual.hasPending(p.Key)
	}
	for _, b := range []*Ledger157{r.Canonical, r.Actual} {
		l, s := b.position("", "")
		for _, p := range b.Pending {
			if len(p.Targets) == 0 {
				if p.Side > 0 {
					l += p.Quantity
				} else {
					s += p.Quantity
				}
			}
		}
		if l > 100 || s > 100 {
			return errors.New("予約込み100micro上限違反")
		}
	}
	return nil
}

// verifyExact157 はC00を同じ原資料で独立運転した旧S01の全約定へ照合します。
//
// 引数: r(*PolicyResult157)、source(*Result)。返り値: error。
func verifyExact157(r *PolicyResult157, source *Result) error {
	if len(r.Actual.Events) != len(source.Events) {
		return errors.New("C00全約定数差")
	}
	for i, e := range r.Actual.Events {
		x := source.Events[i]
		if e.Order.ID != x.Signal.ID || e.Order.Owner != x.Signal.Owner || e.Order.Campaign != x.Signal.Campaign || e.Order.Side != x.Signal.Side || e.Order.Quantity != x.Signal.Quantity*10 || e.FillIndex != x.FillIndex || e.Order.DecisionIndex != x.DecisionIndex || e.Order.DecisionTime != x.Signal.Time || e.FillTime != x.Fill.Time || e.Price != x.Fill.Price || math.Abs(e.Gross-x.Gross) > 1e-7 {
			return fmt.Errorf("C00約定%d差", i)
		}
		if len(e.Order.Targets) != len(x.Signal.Targets) {
			return fmt.Errorf("C00返済所有数%d差", i)
		}
		for j, t := range e.Order.Targets {
			if t.ID != x.Signal.Targets[j].ID || t.Quantity != x.Signal.Targets[j].Quantity*10 {
				return fmt.Errorf("C00返済配賦%d差", i)
			}
		}
	}
	if len(source.Signals) != len(r.Actual.Events)+len(r.Actual.Pending) || len(source.FinalPending) != len(r.Actual.Pending) {
		return errors.New("C00未約定通知差")
	}
	for i, e := range r.Actual.Pending {
		x := source.FinalPending[i]
		if e.ID != x.ID || e.Quantity != x.Quantity*10 || e.Side != x.Side || e.DecisionIndex != x.SourceIndex {
			return errors.New("C00末尾予約差")
		}
	}
	if math.Abs(r.Actual.Realized-source.Gross) > 1e-7 {
		return errors.New("C00同額収支差")
	}
	if math.Abs(r.Actual.Last.Unrealized-source.Unrealized) > 1e-7 {
		return errors.New("C00末尾含み差")
	}
	return nil
}

// run157 は二市場特徴と旧S01源を一度だけ進め、固定政策へ同じ通知を渡します。
//
// 引数: scene(Scene)、configs([]Policy157)、expressions(map[string]string)。返り値: Saved157とerror。
func run157(scene Scene, configs []Policy157, expressions map[string]string) (Saved157, error) {
	result := Saved157{Scene: scene}
	rows, counts, e := loadBoards(scene)
	if e != nil {
		return result, e
	}
	result.Counts = counts
	f, params, e := prepare(scene, "S01")
	if e != nil {
		return result, e
	}
	p, e := strategy.New(strategy.Config{Reference: "NK225", Product: "NK225mini", Cap: 10, CoreQuantity: 5, ExtraMaxQuantity: 5, LargeTick: 10, PointValue: 100, Parameters: params, RuleExpressions: expressions}, makeSession(scene))
	if e != nil {
		return result, e
	}
	source := &CaseState{P: p, Result: Result{Scene: scene, Method: "S01", Variant: Variant{ID: "S01"}, Counts: counts, Entries: map[string]*Entry{}, DecisionEvidence: map[string]strategy.Observation{}}}
	for _, c := range configs {
		result.Cases = append(result.Cases, newPolicy157(c, scene))
	}
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
		before := len(source.Result.Signals)
		if e = process(source, o); e != nil {
			return result, e
		}
		signals := source.Result.Signals[before:]
		ss := map[int]Support157{1: support.get(o.Time, 1), -1: support.get(o.Time, -1)}
		for _, c := range result.Cases {
			if e = step157(c, o, signals, ss); e != nil {
				return result, fmt.Errorf("%s/%s: %w", scene.Session, c.Config.ID, e)
			}
		}
	}
	source.Result.FinalPending = source.Pending
	source.Result.Unrealized = 0
	for _, l := range source.Result.Entries {
		if l.Remaining > 0 {
			mark := source.Result.LastQuote.Bid
			if l.Side < 0 {
				mark = source.Result.LastQuote.Ask
			}
			source.Result.Unrealized += float64(l.Side*l.Remaining) * (mark - l.Price) * 100
		}
	}
	result.Source = source.Result
	for _, c := range result.Cases {
		if c.Config.Exact {
			if e = verifyExact157(c, &source.Result); e != nil {
				return result, e
			}
		}
		if !scene.Partial && (len(c.Actual.Active) > 0 || len(c.Actual.Pending) > 0 || len(c.Canonical.Active) > 0 || len(c.Canonical.Pending) > 0) {
			return result, fmt.Errorf("%s完了場に未解消", c.Config.ID)
		}
	}
	return result, nil
}

// execute157 は場独立8並列まで実行し、既存結果の上書きを拒否します。
//
// 引数: scenes([]Scene)、configs([]Policy157)、expressions(map[string]string)、out(string)、workers(int)。返り値: error。
func execute157(scenes []Scene, configs []Policy157, expressions map[string]string, out string, workers int) error {
	if workers < 1 || workers > 8 {
		return errors.New("並列数1～8")
	}
	for _, s := range scenes {
		if _, e := os.Stat(filepath.Join(out, s.Session+"_S01.json")); !os.IsNotExist(e) {
			return errors.New("結果既存又は保存先不正")
		}
	}
	if e := os.MkdirAll(out, 0700); e != nil {
		return e
	}
	jobs := make(chan Scene)
	failures := make(chan error, len(scenes))
	var wg sync.WaitGroup
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for s := range jobs {
				t := time.Now()
				v, e := run157(s, configs, expressions)
				if e == nil {
					e = saveResult(filepath.Join(out, s.Session+"_S01.json"), v)
				}
				if e != nil {
					failures <- fmt.Errorf("%s: %w", s.Session, e)
				} else {
					fmt.Printf("完了 %s 条件%d 所要%s\n", s.Session, len(configs), time.Since(t).Round(time.Millisecond))
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

// main は人工作業から独立した登録後の研究実行入口です。
//
// 引数: CLIでmanifest/configs/registration/out/workers。返り値: なし。未登録は終了コード1です。
func main() {
	manifest := flag.String("manifest", "../../../s01_156/inputs156.json", "固定27日中入力")
	cfg := flag.String("configs", "../configs1573.json", "固定12政策")
	receipt := flag.String("registration", "", "登録受領")
	out := flag.String("out", "../results_go", "結果新規保存")
	workers := flag.Int("workers", 8, "場独立並列")
	export := flag.String("export-configs", "", "人工準備用の固定政策出力")
	flag.Parse()
	fail := func(e error) { fmt.Fprintln(os.Stderr, e); os.Exit(1) }
	if *export != "" {
		raw, e := json.MarshalIndent(configs157(), "", "  ")
		if e != nil {
			fail(e)
		}
		if e = os.WriteFile(*export, append(raw, '\n'), 0600); e != nil {
			fail(e)
		}
		return
	}
	if e := registrationOK(*receipt); e != nil {
		fail(e)
	}
	var input struct {
		Sessions []Scene `json:"sessions"`
	}
	if e := readJSON(*manifest, &input); e != nil {
		fail(e)
	}
	complete, partial := 0, 0
	for _, s := range input.Sessions {
		if s.Kind != "Day" {
			fail(errors.New("日中だけ"))
		}
		if s.Partial {
			partial++
		} else {
			complete++
		}
	}
	if complete != 26 || partial != 1 {
		fail(errors.New("固定26完了＋途中1場"))
	}
	var configs []Policy157
	if e := readJSON(*cfg, &configs); e != nil {
		fail(e)
	}
	if e := validate157(configs); e != nil {
		fail(e)
	}
	r, e := rules.LoadFor("NK225_S01.toml", "s01")
	if e != nil {
		fail(e)
	}
	if e = execute157(input.Sessions, configs, r.Expressions(), *out, *workers); e != nil {
		fail(e)
	}
}
