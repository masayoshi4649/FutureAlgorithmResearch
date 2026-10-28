package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"os"
	"strconv"

	"futurealgorithm/sessiontrader/internal/strategy"
)

type Entry struct {
	ID, Owner                                                        string
	Campaign, Side, Quantity, Remaining                              int
	Price, Time, Gross, BestPoints, WorstPoints, BestTime, WorstTime float64
}
type Event struct {
	Signal        strategy.Signal `json:"signal"`
	Fill          strategy.Fill   `json:"fill"`
	DecisionIndex int64           `json:"decision_index"`
	FillIndex     int64           `json:"fill_index"`
	Gross         float64         `json:"gross"`
	Pieces        []Piece156      `json:"pieces,omitempty"`
}
type Snapshot struct {
	Time, Bid, Ask float64
	Index          int64
	Diagnostics    []map[string]any
}
type Result struct {
	Parents           map[string]*ParentMark156       `json:"parents"`
	Variant           Variant                         `json:"config"`
	Scene             Scene                           `json:"scene"`
	Method            string                          `json:"method"`
	Counts            map[string]int                  `json:"counts"`
	Events            []Event                         `json:"events"`
	Signals           []strategy.Signal               `json:"signals"`
	Entries           map[string]*Entry               `json:"entries"`
	Snapshots         []Snapshot                      `json:"snapshots"`
	DecisionEvidence  map[string]strategy.Observation `json:"decision_evidence"`
	FinalPending      []strategy.Signal               `json:"final_pending"`
	Gross, Unrealized float64
	LastQuote         strategy.Observation       `json:"last_quote"`
	Reentry1562       *strategy.ReentryState1562 `json:"reentry1562,omitempty"`
	Protection156     *strategy.StudyState156    `json:"protection156,omitempty"`
}

// makeSession は指定した昼夜の通常場内時計を接続します。
//
// 引数: scene(Scene)。返り値: strategy.Session。途中終端を場末へ変更しません。
func makeSession(scene Scene) strategy.Session {
	extra := scene.Start + 13500
	if scene.Kind == "Night" {
		extra = scene.USOpen + 1800
	}
	return strategy.Session{ID: scene.Session, Kind: scene.Kind, Start: scene.Start, End: scene.End, ForceClose: scene.ForceClose, USOpen: scene.USOpen, ExtraAt: extra}
}

// prepare は確定足に名目公開遅延を付け、当時までの特徴だけを利用可能にします。
//
// 引数: scene(Scene)、method(string)。返り値: *strategy.Features、strategy.Parameters、error。
func prepare(scene Scene, method string) (*strategy.Features, strategy.Parameters, error) {
	params, e := strategy.ParametersForMethod("NK225", scene.Kind, method)
	if e != nil {
		return nil, params, e
	}
	f, e := strategy.NewFeatures(makeSession(scene), map[string]float64{"NK225": 10, "TOPIX": .5}, params.Features)
	if e != nil {
		return nil, params, e
	}
	f.EnableResearch()
	end := scene.End
	if scene.Cutoff > 0 && scene.Cutoff < end {
		end = scene.Cutoff
	}
	for _, ref := range []string{"TOPIX", "NK225"} {
		for _, interval := range []int{60, 300} {
			bars, e := loadCandles(scene.Candles[ref][strconv.Itoa(interval)], interval, scene.Start, end)
			if e != nil {
				return nil, params, e
			}
			for _, b := range bars {
				if _, e = f.AddCandles(ref, interval, []strategy.Candle{b}, b.Time+float64(interval)+params.Features.CandleDelay); e != nil {
					return nil, params, e
				}
			}
		}
	}
	return f, params, nil
}

// normal は実行の約定と含み評価に使う正常なラージ気配を検査します。
//
// 引数: o(strategy.Observation)。返り値: boolは既知の正で順序のあるBBOです。
func normal(o strategy.Observation) bool {
	return o.QuoteOK && o.Bid > 0 && o.Ask > o.Bid && !math.IsInf(o.Ask, 0) && !math.IsNaN(o.Bid)
}

// applyFill は予約を実約定へ反映し、所有玉別に全損失を計上します。
//
// 引数: r(*Result)、p(*strategy.Portfolio)、sig(strategy.Signal)、o(strategy.Observation)。返り値: error。
func applyFill(r *Result, p *strategy.Portfolio, sig strategy.Signal, o strategy.Observation) error {
	if o.Index <= sig.SourceIndex {
		return errors.New("判断と同じ又は前原行への約定")
	}
	price := o.Bid
	if sig.Side > 0 {
		price = o.Ask
	}
	id := sig.ID + "-玉"
	fill := strategy.Fill{SignalID: sig.ID, ExecutionID: sig.ID + "-約定", HoldID: id, Quantity: sig.Quantity, Price: price, Time: o.Time, Fee: 0}
	gross := 0.
	pieces := []Piece156{}
	if sig.Action == "new" {
		if _, exists := r.Entries[id]; exists {
			return errors.New("新規ID重複")
		}
		r.Entries[id] = &Entry{ID: id, Owner: sig.Owner, Campaign: sig.Campaign, Side: sig.Side, Quantity: sig.Quantity, Remaining: sig.Quantity, Price: price, Time: o.Time, BestTime: o.Time, WorstTime: o.Time}
	} else {
		fill.Closed = append([]strategy.LotTarget(nil), sig.Targets...)
		n := 0
		for _, t := range sig.Targets {
			lot := r.Entries[t.ID]
			if lot == nil || lot.Remaining < t.Quantity || lot.Side != -sig.Side {
				return fmt.Errorf("所有返済不整合 %s", t.ID)
			}
			pnl := float64(lot.Side*t.Quantity) * (price - lot.Price) * 100
			piece := Piece156{ID: t.ID, Owner: lot.Owner, Campaign: lot.Campaign, Side: lot.Side, Quantity: t.Quantity, Entry: lot.Price, Exit: price, Gross: pnl, BestGain: lot.BestPoints, WorstGain: lot.WorstPoints, Reason: sig.ReasonCode, PositiveThenLoss: lot.BestPoints > 0 && pnl < 0}
			if p.Study156 != nil {
				if g := p.Study156.Lots[t.ID]; g != nil {
					piece.Protected = g.Active
					piece.Floor = g.FloorPrice
					piece.ProtectionAt = g.ActivatedAt
				}
			}
			pieces = append(pieces, piece)
			lot.Remaining -= t.Quantity
			lot.Gross += pnl
			gross += pnl
			n += t.Quantity
		}
		if n != sig.Quantity {
			return errors.New("返済配賦数量不一致")
		}
	}
	if e := p.OnFill(fill); e != nil {
		return e
	}
	if e := p.OnOrderDone(sig.ID); e != nil {
		return e
	}
	r.Gross += gross
	r.Events = append(r.Events, Event{Signal: sig, Fill: fill, DecisionIndex: sig.SourceIndex, FillIndex: o.Index, Gross: gross, Pieces: pieces})
	return nil
}

type Variant struct {
	ReentryWidth float64 `json:"reentry_width"`
	Control      string  `json:"control,omitempty"`
	ID           string  `json:"id"`
	Description  string  `json:"description"`
	Width        float64 `json:"width"`
	Activation   float64 `json:"activation"`
	Gate         bool    `json:"gate"`
	EntryRule    int     `json:"entry_rule"`
}

// validateConfigs は第1巡対照6案と固定再参加12案の変更を拒否します。
//
// 引数: configs([]Variant)。返り値: errorは条件不整合です。
func validateConfigs(configs []Variant) error {
	if len(configs) != 18 {
		return errors.New("第二巡は固定18条件です")
	}
	controls := []Variant{{ID: "S01"}, {ID: "F05", Width: 20}, {ID: "F09", Width: 40}, {ID: "E07", EntryRule: 3}, {ID: "E08", EntryRule: 3, Width: 20}, {ID: "E09", EntryRule: 3, Width: 40}}
	for i, want := range controls {
		got := configs[i]
		if got.ID != want.ID || got.Width != want.Width || got.EntryRule != want.EntryRule || got.Activation != 0 || got.Gate || got.ReentryWidth != 0 {
			return fmt.Errorf("対照%dの改変", i)
		}
	}
	i := 6
	for _, entry := range []int{0, 3} {
		for _, width := range []float64{20, 40} {
			for _, reentry := range []float64{20, 40, 80} {
				v := configs[i]
				if v.ID != fmt.Sprintf("R%02d", i-5) || v.Width != width || v.EntryRule != entry || v.Activation != 0 || v.Gate || v.ReentryWidth != reentry {
					return fmt.Errorf("第二巡条件%dの改変", i)
				}
				i++
			}
		}
	}
	return nil
}

type CaseState struct {
	Result        Result
	P             *strategy.Portfolio
	Pending       []strategy.Signal
	LastSample    float64
	PreviousStage string
}

// process は一件の当時観測を独立した候補へ送ります。
//
// 引数: c(*CaseState)、o(strategy.Observation)。返り値: errorは状態・会計・数量の矛盾です。
func process(c *CaseState, o strategy.Observation) error {
	filled := false
	peak := false
	if normal(o) {
		for _, lot := range c.Result.Entries {
			if lot.Remaining > 0 {
				peak = markEntry(lot, o) || peak
			}
		}
		markParents156(&c.Result, o)
		for _, sig := range c.Pending {
			if e := applyFill(&c.Result, c.P, sig, o); e != nil {
				return e
			}
			filled = true
		}
		c.Pending = nil
		c.Result.LastQuote = o
		for _, l := range c.Result.Entries {
			if l.Remaining <= 0 {
				continue
			}
			peak = markEntry(l, o) || peak
		}
	}
	if normal(o) {
		markParents156(&c.Result, o)
	}
	sigs, e := c.P.Observe(o, o.Time < c.Result.Scene.ForceClose)
	if e != nil {
		return e
	}
	c.Pending = append(c.Pending, sigs...)
	c.Result.Signals = append(c.Result.Signals, sigs...)
	for _, sig := range sigs {
		c.Result.DecisionEvidence[sig.ID] = o
	}
	// ----------------------------------------
	// 入口の数量・所有IDと、利益保護開始などの状態遷移を監査用に記録します。
	stage := ""
	long, short := 0, 0
	for _, s := range c.P.Research.Sleeves {
		stage += fmt.Sprintf("%s:%d:%v:%d;", s.Name, s.Stage, s.PartialProtection != nil, s.ForceReason)
		held := 0
		for _, l := range s.Lots {
			held += l.Quantity
		}
		if held > s.Capacity {
			return errors.New("担当上限違反")
		}
	}
	for _, l := range c.Result.Entries {
		if l.Side > 0 {
			long += l.Remaining
		} else {
			short += l.Remaining
		}
	}
	for _, sig := range c.Pending {
		if sig.Action == "new" {
			if sig.Side > 0 {
				long += sig.Quantity
			} else {
				short += sig.Quantity
			}
		}
	}
	if long > 10 || short > 10 {
		return errors.New("予約込み片側上限違反")
	}
	if filled || len(sigs) > 0 || stage != c.PreviousStage || (c.Result.Scene.Partial && (peak || o.Time-c.LastSample >= 5)) {
		c.Result.Snapshots = append(c.Result.Snapshots, Snapshot{Time: o.Time, Bid: o.Bid, Ask: o.Ask, Index: o.Index, Diagnostics: c.P.ExitDiagnostics(o)})
		c.LastSample = o.Time
		c.PreviousStage = stage
	}
	return nil
}

// markEntry は返済される原行も含めて建玉の順行・逆行極値を更新します。
//
// 引数: l(*Entry)、o(strategy.Observation)。返り値: boolは極値更新の有無です。
func markEntry(l *Entry, o strategy.Observation) bool {
	mark := o.Bid
	if l.Side < 0 {
		mark = o.Ask
	}
	gain := float64(l.Side) * (mark - l.Price)
	changed := false
	if gain > l.BestPoints {
		l.BestPoints = gain
		l.BestTime = o.Time
		changed = true
	}
	if gain < l.WorstPoints {
		l.WorstPoints = gain
		l.WorstTime = o.Time
		changed = true
	}
	return changed
}

// runScene は二市場の特徴を一度だけ計算し、条件別の独立状態へ同じ原行を送ります。
//
// 引数: scene(Scene)、method(string)、configs([]Variant)、expressions(map[string]string)。返り値: []Resultとerror。
// 途中終端の強制清算は行いません。未来の約定・成績で条件を選びません。
func runScene(scene Scene, method string, configs []Variant, expressions map[string]string) ([]Result, error) {
	rows, counts, e := loadBoards(scene)
	if e != nil {
		return nil, e
	}
	f, params, e := prepare(scene, method)
	if e != nil {
		return nil, e
	}
	cases := []*CaseState{}
	for _, v := range configs {
		p, e := strategy.New(strategy.Config{Reference: "NK225", Product: "NK225mini", Cap: 10, CoreQuantity: 5, ExtraMaxQuantity: 5, LargeTick: 10, PointValue: 100, Parameters: params, RuleExpressions: expressions}, makeSession(scene))
		if e != nil {
			return nil, e
		}
		if v.ID != "S01" {
			if e = p.Configure156(v.Width, v.Activation, v.Gate, v.EntryRule); e != nil {
				return nil, e
			}
		}
		if v.ReentryWidth > 0 {
			if e = p.ConfigureReentry1562(v.ReentryWidth); e != nil {
				return nil, e
			}
		}
		cases = append(cases, &CaseState{P: p, Result: Result{Scene: scene, Method: method, Variant: v, Counts: counts, Entries: map[string]*Entry{}, DecisionEvidence: map[string]strategy.Observation{}}})
	}
	for _, board := range rows {
		o, e := f.OnBoard(board)
		if e != nil {
			return nil, e
		}
		if o.Reference != "NK225" {
			continue
		}
		for i, c := range cases {
			if i > 0 {
				c.P.SetReference156(cases[0].P)
			}
			if e = process(c, o); e != nil {
				return nil, fmt.Errorf("%s/%s: %w", scene.Session, c.Result.Variant.ID, e)
			}
		}
	}
	out := []Result{}
	for _, c := range cases {
		r := &c.Result
		r.FinalPending = append([]strategy.Signal(nil), c.Pending...)
		for _, l := range r.Entries {
			if l.Remaining <= 0 {
				continue
			}
			mark := r.LastQuote.Bid
			if l.Side < 0 {
				mark = r.LastQuote.Ask
			}
			r.Unrealized += float64(l.Side*l.Remaining) * (mark - l.Price) * 100
			if !scene.Partial {
				return nil, fmt.Errorf("%s/%s 完全場に残建玉", scene.Session, r.Variant.ID)
			}
		}
		if !scene.Partial && len(c.Pending) > 0 {
			return nil, errors.New("完全場に未約定")
		}
		if r.Variant.ReentryWidth == 0 {
			if e = baseline156(scene, *r); e != nil {
				return nil, e
			}
		}
		r.Protection156 = c.P.Study156
		r.Reentry1562 = c.P.Reentry1562
		out = append(out, *r)
	}
	return out, nil
}

// registrationOK は受領の二条件を満たさない金融再生を拒否します。
//
// 引数: path(string)。返り値: errorは未登録・不正受領です。
func registrationOK(path string) error {
	var receipt struct {
		Registered bool `json:"registered"`
		Returncode *int `json:"returncode"`
	}
	if path == "" {
		return errors.New("事前登録受領が必要です")
	}
	if e := readJSON(path, &receipt); e != nil {
		return e
	}
	if !receipt.Registered || receipt.Returncode == nil || *receipt.Returncode != 0 {
		return errors.New("事前登録が正常完了していません")
	}
	return nil
}

// saveResult は新規ファイルだけを作り、既存結果を上書きしません。
//
// 引数: path(string)、r(Result)。返り値: errorは保存又は既存ファイルの競合です。
func saveResult(path string, r any) error {
	f, e := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if e != nil {
		return e
	}
	defer f.Close()
	return json.NewEncoder(f).Encode(r)
}
