// 155はS01のApp移植を凍結研究の全通知・約定へ照合します。通信・実注文は行いません。
package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"sync"

	"futurealgorithm/sessiontrader/internal/rules"
	"futurealgorithm/sessiontrader/internal/strategy"
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

type ExpectedEvent struct {
	Signal        strategy.Signal `json:"signal"`
	Fill          strategy.Fill   `json:"fill"`
	DecisionIndex int64           `json:"decision_index"`
	FillIndex     int64           `json:"fill_index"`
	Gross         float64         `json:"gross"`
}
type ExpectedCase struct {
	Config struct {
		ID string `json:"id"`
	} `json:"config"`
	Scene             Scene             `json:"scene"`
	Events            []ExpectedEvent   `json:"events"`
	Signals           []strategy.Signal `json:"signals"`
	FinalPending      []strategy.Signal `json:"final_pending"`
	Gross, Unrealized float64
}
type ActualLot struct {
	Quantity, Side int
	Price          float64
}
type Case struct {
	ID            string
	Portfolio     *strategy.Portfolio
	Expected      ExpectedCase
	Pending       []strategy.Signal
	Signals       int
	Events        []ExpectedEvent
	HoldMapping   map[string]string
	SignalMapping map[string]string
	Lots          map[string]ActualLot
	Gross         float64
	Last          strategy.Observation
}
type CaseReport struct {
	Method     string          `json:"method"`
	Signals    int             `json:"signals"`
	Fills      int             `json:"fills"`
	Gross      float64         `json:"gross"`
	Unrealized float64         `json:"unrealized"`
	Remaining  int             `json:"remaining"`
	Pending    int             `json:"pending"`
	Events     []ExpectedEvent `json:"events"`
	Equal      bool            `json:"equal"`
}
type Report struct {
	Scene  Scene          `json:"scene"`
	Counts map[string]int `json:"counts"`
	Cases  []CaseReport   `json:"cases"`
}

// session155 は元研究の場内時計をそのままAppへ渡します。
//
// 引数: scene(Scene)。返り値: strategy.Session。
func session155(scene Scene) strategy.Session {
	extra := scene.Start + 13500
	if scene.Kind == "Night" {
		extra = scene.USOpen + 1800
	}
	return strategy.Session{ID: scene.Session, Kind: scene.Kind, Start: scene.Start, End: scene.End, ForceClose: scene.ForceClose, USOpen: scene.USOpen, ExtraAt: extra}
}

// prepare155 は公開遅延付きの確定足と共通特徴を元研究と同じ順序で準備します。
//
// 引数: scene(Scene)。返り値: *strategy.Featuresとerror。
func prepare155(scene Scene) (*strategy.Features, error) {
	p, err := strategy.ParametersForMethod("NK225", scene.Kind, "D07")
	if err != nil {
		return nil, err
	}
	f, err := strategy.NewFeatures(session155(scene), map[string]float64{"NK225": 10, "TOPIX": .5}, p.Features)
	if err != nil {
		return nil, err
	}
	f.EnableResearch()
	end := scene.End
	if scene.Cutoff > 0 && scene.Cutoff < end {
		end = scene.Cutoff
	}
	for _, ref := range []string{"TOPIX", "NK225"} {
		for _, interval := range []int{60, 300} {
			bars, err := loadCandles(scene.Candles[ref][strconv.Itoa(interval)], interval, scene.Start, end)
			if err != nil {
				return nil, err
			}
			for _, b := range bars {
				if _, err = f.AddCandles(ref, interval, []strategy.Candle{b}, b.Time+float64(interval)+p.Features.CandleDelay); err != nil {
					return nil, err
				}
			}
		}
	}
	return f, nil
}

// expected155 は保存済み研究の指定条件だけを読取り、成績による選別を行いません。
//
// 引数: dir/scene/id(string)。返り値: ExpectedCaseとerror。
func expected155(dir, scene, id string) (ExpectedCase, error) {
	var saved struct {
		Cases []ExpectedCase `json:"cases"`
	}
	if err := readJSON(filepath.Join(dir, scene+"_D07.json"), &saved); err != nil {
		return ExpectedCase{}, err
	}
	for _, c := range saved.Cases {
		if c.Config.ID == id {
			return c, nil
		}
	}
	return ExpectedCase{}, fmt.Errorf("保存対照がない: %s/%s", scene, id)
}

// close155 は浮動小数の比較を固定許容誤差で判定します。
//
// 引数: a/b(float64)。返り値: bool。
func close155(a, b float64) bool { return math.Abs(a-b) < 1e-7 }

// normal155 は凍結研究と同じ正常気配の条件を確認します。
//
// 引数: o(strategy.Observation)。返り値: boolは次約定へ使用できる場合trueです。
func normal155(o strategy.Observation) bool {
	return o.QuoteOK && o.Bid > 0 && o.Ask > o.Bid && !math.IsInf(o.Ask, 0) && !math.IsNaN(o.Bid)
}

// reason155 は売買条件を変えない表示用の理由番号だけを明示的に対応させます。
//
// 引数: value(int)。返り値: int。現在は番号変換なしです。
func reason155(value int) int { return value }

// signal155 は全発注の判断原行・方向・数量・退出対象と判断根拠を照合します。
//
// 引数: c(*Case)、actual(strategy.Signal)。返り値: errorは最初の不一致です。
func signal155(c *Case, actual strategy.Signal) error {
	if c.Signals >= len(c.Expected.Signals) {
		return fmt.Errorf("余分な通知 %s/%+v", c.ID, actual)
	}
	e := c.Expected.Signals[c.Signals]
	if actual.Owner != e.Owner || actual.Action != e.Action || actual.Side != e.Side || actual.Quantity != e.Quantity || actual.Campaign != e.Campaign || actual.Ticket != e.Ticket || actual.SourceIndex != e.SourceIndex || !close155(actual.Time, e.Time) || !close155(actual.Risk, e.Risk) || !close155(actual.Boundary, e.Boundary) || reason155(actual.ReasonCode) != reason155(e.ReasonCode) {
		return fmt.Errorf("通知差 %s/%d\n実:%+v\n元:%+v", c.ID, c.Signals, actual, e)
	}
	if len(actual.Targets) != len(e.Targets) {
		return fmt.Errorf("返済対象数の差 %s/%d", c.ID, c.Signals)
	}
	for i, t := range e.Targets {
		if actual.Targets[i].ID != c.HoldMapping[t.ID] || actual.Targets[i].Quantity != t.Quantity {
			return fmt.Errorf("返済対象の差 %s/%d", c.ID, c.Signals)
		}
	}
	var oldEvidence, newEvidence map[string]any
	if err := json.Unmarshal(e.Evidence, &oldEvidence); err != nil {
		return fmt.Errorf("保存根拠JSONの破損: %w", err)
	}
	if err := json.Unmarshal(actual.Evidence, &newEvidence); err != nil {
		return fmt.Errorf("移植根拠JSONの破損: %w", err)
	}
	for _, key := range []string{"fixed_r", "fixed_ma20", "ma_known", "profit_budget", "strategy_cash", "residual_stage", "observation"} {
		// 追加診断・method表示・内部IDは除外し、同じ当時観測と固定水準を要求します。
		old, oldOK := oldEvidence[key]
		now, newOK := newEvidence[key]
		if oldOK != newOK {
			return fmt.Errorf("判断根拠の有無 %s/%d/%s", c.ID, c.Signals, key)
		}
		if oldOK {
			a, _ := json.Marshal(old)
			b, _ := json.Marshal(now)
			if string(a) != string(b) {
				return fmt.Errorf("判断根拠差 %s/%d/%s", c.ID, c.Signals, key)
			}
		}
	}
	c.SignalMapping[e.ID] = actual.ID
	c.Signals++
	return nil
}

// fill155 は元研究と同じ次正常BBOで実Appの約定反映を呼び、全返済会計を照合します。
//
// 引数: c(*Case)、s(strategy.Signal)、o(strategy.Observation)。返り値: error。
func fill155(c *Case, s strategy.Signal, o strategy.Observation) error {
	if !normal155(o) {
		return errors.New("非正常気配での約定は禁止")
	}
	if o.Index <= s.SourceIndex {
		return errors.New("同原行約定は禁止")
	}
	n := len(c.Events)
	if n >= len(c.Expected.Events) {
		return errors.New("余分な約定")
	}
	e := c.Expected.Events[n]
	price := o.Bid
	if s.Side > 0 {
		price = o.Ask
	}
	f := strategy.Fill{SignalID: s.ID, ExecutionID: s.ID + "-約定", HoldID: s.ID + "-玉", Quantity: s.Quantity, Price: price, Time: o.Time, Closed: s.Targets}
	if c.SignalMapping[e.Signal.ID] != s.ID || o.Index != e.FillIndex || s.SourceIndex != e.DecisionIndex || f.Quantity != e.Fill.Quantity || !close155(f.Price, e.Fill.Price) || !close155(f.Time, e.Fill.Time) {
		return fmt.Errorf("約定差 %s/%d", c.ID, n)
	}
	gross := 0.
	if s.Action == "new" {
		if _, ok := c.Lots[f.HoldID]; ok {
			return errors.New("新規所有ID重複")
		}
		c.Lots[f.HoldID] = ActualLot{Quantity: s.Quantity, Side: s.Side, Price: price}
		c.HoldMapping[e.Fill.HoldID] = f.HoldID
	} else {
		total := 0
		for _, target := range s.Targets {
			lot, ok := c.Lots[target.ID]
			if !ok || lot.Quantity < target.Quantity || lot.Side != -s.Side {
				return errors.New("所有返済不整合")
			}
			gross += float64(lot.Side*target.Quantity) * (price - lot.Price) * 100
			lot.Quantity -= target.Quantity
			c.Lots[target.ID] = lot
			total += target.Quantity
		}
		if total != s.Quantity {
			return errors.New("返済数量と対象配賦の不一致")
		}
	}
	if !close155(gross, e.Gross) {
		return fmt.Errorf("返済額差 %s/%d: %v/%v", c.ID, n, gross, e.Gross)
	}
	if err := c.Portfolio.OnFill(f); err != nil {
		return err
	}
	if err := c.Portfolio.OnOrderDone(s.ID); err != nil {
		return err
	}
	c.Gross += gross
	c.Events = append(c.Events, ExpectedEvent{Signal: s, Fill: f, DecisionIndex: s.SourceIndex, FillIndex: o.Index, Gross: gross})
	return nil
}

// process155 は一原行の既発注約定と現在判断を順に進めます。
//
// 引数: c(*Case)、o(strategy.Observation)。返り値: error。
func process155(c *Case, o strategy.Observation) error {
	if normal155(o) {
		for _, s := range c.Pending {
			if err := fill155(c, s, o); err != nil {
				return err
			}
		}
		c.Pending = nil
		c.Last = o
	}
	signals, err := c.Portfolio.Observe(o, o.Time < c.Expected.Scene.ForceClose)
	if err != nil {
		return err
	}
	for _, s := range signals {
		if err = signal155(c, s); err != nil {
			return err
		}
	}
	c.Pending = append(c.Pending, signals...)
	for _, side := range []int{-1, 1} {
		quantity := 0
		for _, lot := range c.Lots {
			if lot.Side == side {
				quantity += lot.Quantity
			}
		}
		for _, pending := range c.Pending {
			if pending.Action == "new" && pending.Side == side {
				quantity += pending.Quantity
			}
		}
		if quantity > 10 {
			return errors.New("予約込み片方向10枚上限違反")
		}
	}
	return nil
}

// run155 は一場を一度読み、D07と昼S01を独立に照合します。
//
// 引数: scene(Scene)、first/second(string)、expressions(map[string]map[string]string)。返り値: Reportとerror。
func run155(scene Scene, first, second string, expressions map[string]map[string]string) (Report, error) {
	report := Report{Scene: scene}
	rows, counts, err := loadBoards(scene)
	if err != nil {
		return report, err
	}
	report.Counts = counts
	features, err := prepare155(scene)
	if err != nil {
		return report, err
	}
	ids := []string{"D07"}
	if scene.Kind == "Day" {
		ids = append(ids, "S01")
	}
	cases := []*Case{}
	for _, id := range ids {
		dir := first
		if id == "S01" {
			dir = second
		}
		expected, err := expected155(dir, scene.Session, id)
		if err != nil {
			return report, err
		}
		if !reflect.DeepEqual(scene, expected.Scene) {
			return report, fmt.Errorf("場定義差 %s", scene.Session)
		}
		params, err := strategy.ParametersForMethod("NK225", scene.Kind, id)
		if err != nil {
			return report, err
		}
		p, err := strategy.New(strategy.Config{Reference: "NK225", Product: "NK225mini", Cap: 10, CoreQuantity: 5, ExtraMaxQuantity: 5, LargeTick: 10, PointValue: 100, Parameters: params, RuleExpressions: expressions[id]}, session155(scene))
		if err != nil {
			return report, err
		}
		cases = append(cases, &Case{ID: id, Portfolio: p, Expected: expected, HoldMapping: map[string]string{}, SignalMapping: map[string]string{}, Lots: map[string]ActualLot{}})
	}
	for _, board := range rows {
		o, err := features.OnBoard(board)
		if err != nil {
			return report, err
		}
		if o.Reference != "NK225" {
			continue
		}
		for _, c := range cases {
			if err = process155(c, o); err != nil {
				return report, fmt.Errorf("%s: %w", scene.Session, err)
			}
		}
	}
	for _, c := range cases {
		unrealized, remaining := 0., 0
		for _, l := range c.Lots {
			mark := c.Last.Bid
			if l.Side < 0 {
				mark = c.Last.Ask
			}
			unrealized += float64(l.Side*l.Quantity) * (mark - l.Price) * 100
			remaining += l.Quantity
		}
		if c.Signals != len(c.Expected.Signals) || len(c.Events) != len(c.Expected.Events) || len(c.Pending) != len(c.Expected.FinalPending) || !close155(c.Gross, c.Expected.Gross) || !close155(unrealized, c.Expected.Unrealized) {
			return report, fmt.Errorf("終端差 %s/%s", scene.Session, c.ID)
		}
		for i, pending := range c.Pending {
			if c.SignalMapping[c.Expected.FinalPending[i].ID] != pending.ID {
				return report, errors.New("終端未約定ID又は順序の差")
			}
		}
		if !scene.Partial && (remaining != 0 || len(c.Pending) != 0) {
			return report, errors.New("完了場に残玉・予約")
		}
		report.Cases = append(report.Cases, CaseReport{Method: c.ID, Signals: c.Signals, Fills: len(c.Events), Gross: c.Gross, Unrealized: unrealized, Remaining: remaining, Pending: len(c.Pending), Events: c.Events, Equal: true})
	}
	return report, nil
}

// registration155 は登録成功前の原資料再生を拒否します。
//
// 引数: path(string)。返り値: error。
func registration155(path string) error {
	var r struct {
		Registered bool `json:"registered"`
		Returncode *int `json:"returncode"`
	}
	if path == "" {
		return errors.New("登録受領が必要です")
	}
	if err := readJSON(path, &r); err != nil {
		return err
	}
	if !r.Registered || r.Returncode == nil || *r.Returncode != 0 {
		return errors.New("登録未完了")
	}
	return nil
}

// main は事前登録済みの移植照合だけを最大4場並列で実行します。
//
// 引数: コマンド引数。返り値: なし。不一致又は保存失敗は終了コード1。
func main() {
	manifest := flag.String("manifest", "../inputs155.json", "固定入力目録")
	receipt := flag.String("registration", "", "登録受領JSON")
	first := flag.String("expected-first", "../../d07_154/results_go", "初巡対照")
	second := flag.String("expected-second", "../../d07_154/results_round2", "第二巡対照")
	output := flag.String("out", "../results", "新規出力先")
	workers := flag.Int("workers", 4, "独立場の並列数1～4")
	flag.Parse()
	fail := func(err error) { fmt.Fprintln(os.Stderr, err); os.Exit(1) }
	if err := registration155(*receipt); err != nil {
		fail(err)
	}
	if *workers < 1 || *workers > 4 {
		fail(errors.New("並列数の範囲外"))
	}
	var m struct {
		Sessions []Scene `json:"sessions"`
	}
	if err := readJSON(*manifest, &m); err != nil {
		fail(err)
	}
	if len(m.Sessions) != 52 {
		fail(errors.New("固定52場と不一致"))
	}
	expressions := map[string]map[string]string{}
	for _, id := range []string{"D07", "S01"} {
		r, err := rules.LoadFor("NK225_"+id+".toml", strings.ToLower(id))
		if err != nil {
			fail(err)
		}
		expressions[id] = r.Expressions()
	}
	if err := os.MkdirAll(*output, 0700); err != nil {
		fail(err)
	}
	jobs := make(chan Scene, len(m.Sessions))
	results := make(chan error, len(m.Sessions))
	var wg sync.WaitGroup
	for i := 0; i < *workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for scene := range jobs {
				out, err := run155(scene, *first, *second, expressions)
				if err == nil {
					var f *os.File
					f, err = os.OpenFile(filepath.Join(*output, scene.Session+".json"), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
					if err == nil {
						err = json.NewEncoder(f).Encode(out)
						closeErr := f.Close()
						if err == nil {
							err = closeErr
						}
					}
				}
				if err == nil {
					fmt.Println(scene.Session, "一致", len(out.Cases), "条件")
				}
				results <- err
			}
		}()
	}
	for _, s := range m.Sessions {
		jobs <- s
	}
	close(jobs)
	wg.Wait()
	close(results)
	for err := range results {
		if err != nil {
			fail(err)
		}
	}
}
