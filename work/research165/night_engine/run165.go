package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"futurealgorithm/sessiontrader/internal/strategy"
	"os"
)

type Quote165 struct {
	QuoteNight164
	Line int64
}

type Saved165 struct {
	Scene       Scene                   `json:"scene"`
	Cases       []*Result165            `json:"cases"`
	Sources     []*SourceStateNative164 `json:"sources"`
	Control     *NightResult164         `json:"control"`
	Counts      map[string]int          `json:"counts"`
	Reference   []Quote165              `json:"reference"`
	ExactChecks int                     `json:"exact_checks"`
}

// validateFlat165 は未返済・未約定・待機のいずれも残らないことを要求します。
//
// 引数: r(*Result165)。返り値: error。終端価格を補完して成功へ変換しません。
func validateFlat165(r *Result165) error {
	if len(r.Actual.Active) > 0 || len(r.Actual.Pending) > 0 {
		return fmt.Errorf("場末未完済 %s", r.Config.ID)
	}
	for _, p := range r.Parents {
		if p.Deferred {
			return fmt.Errorf("場末待機未解消 %s", r.Config.ID)
		}
	}
	return nil
}

// sourceLines165 は旧読取と同じ採番に物理行だけを対応付けます。
//
// 引数: scene(Scene)。返り値: []int64とerror。売買判断や未来価格は作りません。
func sourceLines165(scene Scene) ([]int64, error) {
	f, e := os.Open(scene.Books["NK225"])
	if e != nil {
		return nil, e
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 65536), 8*1024*1024)
	lines := []int64{}
	previous := scene.Start
	var line int64
	for sc.Scan() {
		line++
		var b struct {
			CurrentPriceTime *string
			CurrentPrice     float64
		}
		if e = json.Unmarshal(sc.Bytes(), &b); e != nil {
			return nil, e
		}
		if b.CurrentPriceTime == nil {
			continue
		}
		at, err := stamp(*b.CurrentPriceTime)
		if err != nil || at < scene.Start || at > scene.End || (scene.Cutoff > 0 && at >= scene.Cutoff) || at < previous || b.CurrentPrice <= 0 || !finite165(b.CurrentPrice) {
			continue
		}
		previous = at
		lines = append(lines, line)
	}
	return lines, sc.Err()
}

// halfMark165 は同じ原行価格の時価断面を厳密半量へ写します。
//
// 引数: m(*Mark157)。返り値: なし。価格と時計は不変です。
func halfMark165(m *Mark157) {
	m.Realized /= 2
	m.Unrealized /= 2
	m.Equity /= 2
	m.MidEquity /= 2
	m.Long /= 2
	m.Short /= 2
	for k, q := range m.Lots {
		m.Lots[k] = q / 2
	}
}

// finalize165 は12の同一仮想指示を厳密半量へ写し、診断を保存します。
//
// 引数: なし。返り値: error。全量側の余枠・同時親・入口順で実行した証跡を保持します。
func (r *Result165) finalize165() error {
	if r.Config.ID != "NK225_U165_12" {
		return nil
	}
	data, e := json.Marshal(r.Actual)
	if e != nil {
		return e
	}
	r.VirtualControl = &Ledger157{}
	if e = json.Unmarshal(data, r.VirtualControl); e != nil {
		return e
	}
	b := r.Actual
	for _, l := range b.Lots {
		if l.Quantity%2 != 0 || l.Remaining%2 != 0 {
			return fmt.Errorf("半量化できない玉")
		}
		l.Quantity /= 2
		l.Remaining /= 2
		l.Gross /= 2
	}
	for i := range b.Events {
		f := &b.Events[i]
		if f.Order.Quantity%2 != 0 {
			return fmt.Errorf("半量化できない注文")
		}
		f.Order.Quantity /= 2
		for j := range f.Order.Targets {
			if f.Order.Targets[j].Quantity%2 != 0 {
				return fmt.Errorf("半量化できない対象")
			}
			f.Order.Targets[j].Quantity /= 2
		}
		f.Gross /= 2
		f.ComparedQuantity /= 2
		for j := range f.Pieces {
			f.Pieces[j].Quantity /= 2
			f.Pieces[j].Gross /= 2
		}
	}
	if len(b.Pending) != 0 {
		return fmt.Errorf("半量確定時に未約定")
	}
	b.Realized /= 2
	for _, p := range b.Parents {
		p.Realized /= 2
		p.Unrealized /= 2
		p.Equity /= 2
		p.Peak /= 2
		p.Minimum /= 2
		p.Quantity /= 2
		p.Long /= 2
		p.Short /= 2
	}
	risk := &b.Risk
	risk.Peak /= 2
	risk.Minimum /= 2
	risk.MaxDD /= 2
	risk.MinimumRealized /= 2
	risk.MinimumUnrealized /= 2
	risk.MaxLong /= 2
	risk.MaxShort /= 2
	risk.MaxGross /= 2
	risk.MaxNetAbs /= 2
	risk.GrossSeconds /= 2
	risk.NetAbsSeconds /= 2
	risk.NetSignedSeconds /= 2
	for _, m := range []*Mark157{&b.Last, &risk.MinimumAt, &risk.PeakAt, &risk.DDFrom, &risk.DDTo, &risk.MinimumRealizedAt, &risk.MinimumUnrealizedAt} {
		halfMark165(m)
	}
	for i := range r.Trace {
		r.Trace[i].Desired /= 2
		r.Trace[i].Accepted /= 2
	}
	return nil
}

// run165 は不変の元Sourceを一回だけ進め、新14案へ当時通知を渡します。
//
// 引数: scene(Scene)、configs([]Config165)、sets(map[string]map[string]string)。返り値: Saved165とerror。
func run165(scene Scene, configs []Config165, sets map[string]map[string]string) (Saved165, error) {
	s := Saved165{Scene: scene}
	rows, counts, e := loadBoards(scene)
	if e != nil {
		return s, e
	}
	s.Counts = counts
	lines, e := sourceLines165(scene)
	if e != nil {
		return s, e
	}
	f, _, e := prepare(scene, "D07")
	if e != nil {
		return s, e
	}
	for _, c := range configs {
		s.Cases = append(s.Cases, newResult165(c, scene))
	}
	control := SavedNight164{Scene: scene}
	for _, c := range configsNight164() {
		if c.Native != "" {
			control.Cases = append(control.Cases, newNight164(c, scene))
		}
	}
	source, e := newSourceNative164(scene, "前半", "P05", sets["P05"])
	if e != nil {
		return s, e
	}
	s.Sources = append(s.Sources, source)
	h := &BookFeatures165{}
	eventState, clockState := &Repricing165{}, &Repricing165{Clock: true}
	quotes := []Quote165{}
	var nkIndex int64
	for _, board := range rows {
		o, err := f.OnBoard(board)
		if err != nil {
			return s, err
		}
		if o.Reference != "NK225" {
			continue
		}
		if o.Index != nkIndex {
			return s, fmt.Errorf("NK原行採番不一致 %d/%d", o.Index, nkIndex)
		}
		nkIndex++
		if o.Index < 0 || int(o.Index) >= len(lines) {
			return s, fmt.Errorf("物理行対応の不足")
		}
		features := h.add165(board, o.Index, lines[o.Index])
		v, w := eventState.step165(features, board), clockState.step165(features, board)
		quotes = append(quotes, Quote165{QuoteNight164{o.Index, o.Time, o.Bid, o.Ask, o.Last, normal(o)}, lines[o.Index]})
		signals := []strategy.Signal{}
		if source.Phase == "前半" && o.Time >= scene.USOpen+900 {
			signals, e = source.stepNative164(o, false, nil)
			if e != nil {
				return s, e
			}
			if source.flatNative164() {
				source, e = newSourceNative164(scene, "後半", "D07", sets["D07"])
				if e != nil {
					return s, e
				}
				s.Sources = append(s.Sources, source)
				next, err := source.stepNative164(o, o.Time < scene.ForceClose, nil)
				if err != nil {
					return s, err
				}
				signals = append(signals, next...)
			}
		} else {
			allow := o.Time < scene.ForceClose
			if source.Phase == "前半" {
				allow = o.Time < scene.USOpen-900
			}
			signals, e = source.stepNative164(o, allow, nil)
			if e != nil {
				return s, e
			}
		}
		for _, r := range control.Cases {
			if r.Config.Scope == "PostUS" && source.Phase != "後半" {
				continue
			}
			if e = r.nativeStepNight164(o, signals); e != nil {
				return s, e
			}
		}
		if source.Phase != "後半" {
			continue
		}
		for _, r := range s.Cases {
			state := v
			if r.Config.Clock {
				state = w
			}
			if e = r.step165Policy(o, signals, state); e != nil {
				return s, fmt.Errorf("%s/%s:%w", scene.Session, r.Config.ID, e)
			}
		}
	}
	control.Sources = s.Sources
	if e = verifyNative164(&control); e != nil {
		return s, e
	}
	s.ExactChecks = control.ExactChecks
	for _, r := range control.Cases {
		if r.Config.Scope == "PostUS" {
			s.Control = r
		}
	}
	wanted := map[int64]bool{}
	for _, r := range s.Cases {
		if e = validateFlat165(r); e != nil {
			return s, e
		}
		if e = r.finalize165(); e != nil {
			return s, e
		}
		for _, ev := range r.Actual.Events {
			wanted[ev.Order.DecisionIndex] = true
			wanted[ev.FillIndex] = true
		}
		for _, tr := range r.Trace {
			wanted[tr.Index] = true
			wanted[tr.State.Band.StartIndex] = true
			wanted[tr.State.Buy.Barrier.Index] = true
			wanted[tr.State.Sell.Barrier.Index] = true
		}
		for _, m := range []Mark157{r.Actual.Risk.MinimumAt, r.Actual.Risk.DDFrom, r.Actual.Risk.DDTo, r.Actual.Risk.PeakAt, r.Actual.Risk.MinimumRealizedAt, r.Actual.Risk.MinimumUnrealizedAt} {
			wanted[m.Index] = true
		}
	}
	for _, q := range quotes {
		if wanted[q.Index] {
			s.Reference = append(s.Reference, q)
		}
	}
	return s, nil
}
