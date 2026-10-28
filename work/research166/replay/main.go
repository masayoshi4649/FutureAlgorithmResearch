package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
)

type Scene struct {
	Session, Kind      string
	Start, End, Cutoff float64
	USOpen             float64 `json:"us_open"`
	ForceClose         float64 `json:"force_close"`
	Books              map[string]string
	Candles            map[string]map[string]string
}
type Event struct {
	DecisionIndex, FillIndex int64
	Time, Price, Gross       float64
	Action                   string
	Side, Quantity           int
}
type Result struct {
	Session, Method string
	Cap             int
	Events          []Event
	Gross           float64
	Pending, Held   int
	ExpectedGross   float64
	Differences     []string
	Error           string
}
type Golden struct {
	Cases []struct {
		Config struct{ ID string }
		Actual struct {
			Realized float64
			Events   []struct {
				Order struct {
					DecisionIndex  int64
					Side, Quantity int
					Targets        []json.RawMessage
				}
				FillIndex              int64
				FillTime, Price, Gross float64
			}
		}
	}
}

// session は既存研究の場時計を変更せずアプリへ接続します。
//
// 引数: s(Scene)。返り値: strategy.Session。
func session(s Scene) strategy.Session {
	extra := s.Start + 13500
	if s.Kind == "Night" {
		extra = s.USOpen + 1800
	}
	return strategy.Session{ID: s.Session, Kind: s.Kind, Start: s.Start, End: s.End, ForceClose: s.ForceClose, USOpen: s.USOpen, ExtraAt: extra}
}

// prepare は当時公開された足だけを参照できる共通特徴器を作ります。
//
// 引数: s(Scene)。返り値: *strategy.Featuresとerror。
func prepare(s Scene) (*strategy.Features, error) {
	p := strategy.DefaultParameters("NK225", s.Kind)
	f, err := strategy.NewFeatures(session(s), map[string]float64{"NK225": 10, "TOPIX": .5}, p.Features)
	if err != nil {
		return nil, err
	}
	f.EnableResearch()
	for _, ref := range []string{"TOPIX", "NK225"} {
		for _, iv := range []int{60, 300} {
			bars, err := loadCandles(s.Candles[ref][strconv.Itoa(iv)], iv, s.Start, s.End)
			if err != nil {
				return nil, err
			}
			for _, b := range bars {
				if _, err := f.AddCandles(ref, iv, []strategy.Candle{b}, b.Time+float64(iv)+p.Features.CandleDelay); err != nil {
					return nil, err
				}
			}
		}
	}
	return f, nil
}

// run は原行の次正常気配でのみ仮想約定し、実サービスへ通信しません。
//
// 引数: s(Scene)、cap(int)。返り値: []Resultとerror。
func run(s Scene, cap int) ([]Result, error) {
	rows, _, err := loadBoards(s)
	if err != nil {
		return nil, err
	}
	f, err := prepare(s)
	if err != nil {
		return nil, err
	}
	methods := []string{"D164_15"}
	if s.Kind == "Night" {
		methods = []string{"P164_06", "U165_03"}
	}
	product, pointValue := "NK225micro", 10.0
	if cap == 10 {
		product, pointValue = "NK225mini", 100
	}
	portfolios := map[string]*strategy.Portfolio{}
	pending := map[string][]strategy.Signal{}
	results := map[string]*Result{}
	for _, m := range methods {
		params, err := strategy.ParametersForMethod("NK225", s.Kind, m)
		if err != nil {
			return nil, err
		}
		p, err := strategy.New(strategy.Config{Reference: "NK225", Product: product, Cap: cap, CoreQuantity: 1, ExtraMaxQuantity: 1, LargeTick: 10, PointValue: pointValue, Parameters: params}, session(s))
		if err != nil {
			return nil, err
		}
		portfolios[m] = p
		results[m] = &Result{Session: s.Session, Method: "NK225_" + m, Cap: cap}
	}
	for _, b := range rows {
		o, err := f.OnBoard(b)
		if err != nil {
			return nil, err
		}
		if o.Reference != "NK225" {
			continue
		}
		for _, m := range methods {
			if m == "U165_03" && o.Time < s.USOpen+900 {
				continue
			}
			p := portfolios[m]
			r := results[m]
			if r.Error != "" {
				continue
			}
			waiting := []strategy.Signal{}
			for _, sig := range pending[m] {
				if !o.QuoteOK || o.Index <= sig.SourceIndex {
					waiting = append(waiting, sig)
					continue
				}
				price := o.Bid
				if sig.Side > 0 {
					price = o.Ask
				}
				before := 0.
				for _, pos := range p.Status().Positions {
					before += pos.Realized
				}
				fill := strategy.Fill{SignalID: sig.ID, ExecutionID: sig.ID + "-約定", HoldID: sig.ID + "-玉", Quantity: sig.Quantity, Price: price, Time: o.Time}
				if sig.Action == "close" {
					fill.Closed = sig.Targets
				}
				if err := p.OnFill(fill); err != nil {
					r.Error = fmt.Sprintf("約定 index=%d: %v", o.Index, err)
					break
				}
				if err := p.OnOrderDone(sig.ID); err != nil {
					r.Error = err.Error()
					break
				}
				after := 0.
				for _, pos := range p.Status().Positions {
					after += pos.Realized
				}
				r.Events = append(r.Events, Event{sig.SourceIndex, o.Index, o.Time, price, after - before, sig.Action, sig.Side, sig.Quantity})
			}
			pending[m] = waiting
			if r.Error != "" {
				continue
			}
			signals, err := p.Observe(o, true)
			if err != nil {
				r.Error = fmt.Sprintf("判断 index=%d: %v", o.Index, err)
				continue
			}
			pending[m] = append(pending[m], signals...)
			cancel := map[string]bool{}
			for _, id := range p.SelectedCancellationIDs() {
				cancel[id] = true
			}
			keep := []strategy.Signal{}
			for _, sig := range pending[m] {
				if cancel[sig.ID] {
					if err := p.OnOrderDone(sig.ID); err != nil {
						r.Error = err.Error()
					}
				} else {
					keep = append(keep, sig)
				}
			}
			pending[m] = keep
		}
	}
	var out []Result
	for _, m := range methods {
		r := results[m]
		for _, pos := range portfolios[m].Status().Positions {
			r.Gross += pos.Realized
			r.Held += pos.Quantity
		}
		r.Pending = len(pending[m])
		out = append(out, *r)
	}
	return out, nil
}

// totals は同じ原行・方向の分割返済を集約し、約定粒度だけの差を除きます。
//
// 引数: events([]Event)。返り値: map[string][2]float64。
func totals(events []Event) map[string][2]float64 {
	out := map[string][2]float64{}
	for _, e := range events {
		k := fmt.Sprintf("%d/%d/%s/%d/%.6f", e.DecisionIndex, e.FillIndex, e.Action, e.Side, e.Price)
		v := out[k]
		v[0] += float64(e.Quantity)
		v[1] += e.Gross
		out[k] = v
	}
	return out
}

// compare は保存済み同手法の全約定と数量・粗益を照合します。
//
// 引数: r(*Result)、root(string)。返り値: error。
func compare(r *Result, root string) error {
	base := "work/research164/r2/results"
	if r.Method == "NK225_U165_03" {
		base = "work/research165/results"
	}
	var golden Golden
	found := false
	for _, stage := range []string{"train_validation", "confirmation"} {
		path := filepath.Join(root, base, stage, r.Session+".json")
		if _, err := os.Stat(path); err == nil {
			if err := readJSON(path, &golden); err != nil {
				return err
			}
			found = true
			break
		}
	}
	if !found {
		return fmt.Errorf("既存結果がありません: %s", r.Session)
	}
	for _, c := range golden.Cases {
		if c.Config.ID != r.Method {
			continue
		}
		r.ExpectedGross = c.Actual.Realized
		var expected []Event
		for _, e := range c.Actual.Events {
			action := "new"
			if len(e.Order.Targets) > 0 {
				action = "close"
			}
			expected = append(expected, Event{e.Order.DecisionIndex, e.FillIndex, e.FillTime, e.Price, e.Gross, action, e.Order.Side, e.Order.Quantity})
		}
		a, b := totals(r.Events), totals(expected)
		keys := map[string]bool{}
		for k := range a {
			keys[k] = true
		}
		for k := range b {
			keys[k] = true
		}
		for k := range keys {
			if a[k] != b[k] {
				r.Differences = append(r.Differences, fmt.Sprintf("%s 実装%v 正本%v", k, a[k], b[k]))
			}
		}
		sort.Strings(r.Differences)
		return nil
	}
	return fmt.Errorf("既存結果に手法がありません: %s", r.Method)
}

// main は事前登録を確認し、選定三手法の移植同値だけを検査します。
//
// 引数: CLI。返り値: なし。不一致又は未完済は終了コード1です。
func main() {
	root := flag.String("root", "../../..", "根ディレクトリ")
	only := flag.String("session", "", "場の部分一致")
	cap := flag.Int("cap", 100, "実商品枚数上限")
	out := flag.String("out", "../results", "新しい保存先")
	workers := flag.Int("workers", 3, "並列数")
	flag.Parse()
	if _, err := os.Stat(filepath.Join(*root, "work/research166/登録受領166.json")); err != nil {
		panic("事前登録の受領がありません")
	}
	var manifest struct{ Sessions []Scene }
	if err := readJSON(filepath.Join(*root, "work/research164/r2/inputs164r2.json"), &manifest); err != nil {
		panic(err)
	}
	if err := os.MkdirAll(*out, 0755); err != nil {
		panic(err)
	}
	jobs := make(chan Scene)
	var wg sync.WaitGroup
	var mu sync.Mutex
	failed := false
	for i := 0; i < *workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for s := range jobs {
				results, err := run(s, *cap)
				if err == nil {
					for i := range results {
						if *cap == 100 {
							if e := compare(&results[i], *root); e != nil {
								err = e
								break
							}
						}
					}
				}
				bad := err != nil
				for _, r := range results {
					bad = bad || r.Error != "" || r.Held != 0 || r.Pending != 0 || len(r.Differences) > 0 || (*cap == 100 && math.Abs(r.Gross-r.ExpectedGross) > .001)
				}
				data, _ := json.MarshalIndent(struct {
					Results []Result
					Error   string
				}{results, fmt.Sprint(err)}, "", "  ")
				path := filepath.Join(*out, s.Session+".json")
				f, e := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0644)
				if e != nil {
					err = e
					bad = true
				} else {
					_, e = f.Write(data)
					f.Close()
					if e != nil {
						err = e
						bad = true
					}
				}
				mu.Lock()
				failed = failed || bad
				fmt.Printf("%s 不一致=%t 異常=%v\n", s.Session, bad, err)
				for _, r := range results {
					fmt.Printf("  %s 約定%d 収支%.0f 正本%.0f 差%d %s\n", r.Method, len(r.Events), r.Gross, r.ExpectedGross, len(r.Differences), r.Error)
				}
				mu.Unlock()
			}
		}()
	}
	for _, s := range manifest.Sessions {
		if strings.Contains(s.Session, *only) {
			jobs <- s
		}
	}
	close(jobs)
	wg.Wait()
	if failed {
		os.Exit(1)
	}
}
