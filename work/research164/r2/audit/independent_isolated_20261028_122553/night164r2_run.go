package main

import (
	"fmt"
	"futurealgorithm/sessiontrader/internal/strategy"
)

type SavedNight164R2 struct {
	Scene       Scene                   `json:"scene"`
	Cases       []*NightResult164R2     `json:"cases"`
	Sources     []*SourceStateNative164 `json:"sources"`
	Counts      map[string]int          `json:"counts"`
	References  []QuoteNight164         `json:"reference"`
	ExactChecks int                     `json:"exact_checks"`
}

// runNight164R2 は元P05/D07を一度だけ駆動し、新8条件を独立した実台帳へ写します。
//
// 引数: scene(Scene)、configs([]NightConfig164R2)、sets(map[string]map[string]string)。返り値: SavedNight164R2とerror。
func runNight164R2(scene Scene, configs []NightConfig164R2, sets map[string]map[string]string) (SavedNight164R2, error) {
	saved := SavedNight164R2{Scene: scene}
	rows, counts, e := loadBoards(scene)
	if e != nil {
		return saved, e
	}
	saved.Counts = counts
	f, _, e := prepare(scene, "D07")
	if e != nil {
		return saved, e
	}
	for _, c := range configs {
		saved.Cases = append(saved.Cases, newNight164R2(c, scene))
	}
	source, e := newSourceNative164(scene, "前半", "P05", sets["P05"])
	if e != nil {
		return saved, e
	}
	saved.Sources = append(saved.Sources, source)
	// ----------------------------------------
	// 元通知の10倍写像だけを内部検算します。保存済み基準の新たな効能試験ではありません。
	control := SavedNight164{Scene: scene}
	for _, c := range configsNight164() {
		if c.Native != "" {
			control.Cases = append(control.Cases, newNight164(c, scene))
		}
	}
	features := &SupportBuilder157{Markets: map[string]*supportMarket157{}}
	quotes := []QuoteNight164{}
	firstPost := true
	for _, board := range rows {
		features.add(board)
		o, err := f.OnBoard(board)
		if err != nil {
			return saved, err
		}
		if o.Reference != "NK225" {
			continue
		}
		short := short164(features, o.Time)
		quotes = append(quotes, QuoteNight164{o.Index, o.Time, o.Bid, o.Ask, o.Last, normal(o)})
		signals := []strategy.Signal{}
		if source.Phase == "前半" && o.Time >= scene.USOpen+900 {
			signals, e = source.stepNative164(o, false, nil)
			if e != nil {
				return saved, e
			}
			if source.flatNative164() {
				source, e = newSourceNative164(scene, "後半", "D07", sets["D07"])
				if e != nil {
					return saved, e
				}
				saved.Sources = append(saved.Sources, source)
				next, err := source.stepNative164(o, o.Time < scene.ForceClose, nil)
				if err != nil {
					return saved, err
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
				return saved, e
			}
		}
		for _, r := range control.Cases {
			if r.Config.Scope == "PostUS" && source.Phase != "後半" {
				continue
			}
			if e = r.nativeStepNight164(o, signals); e != nil {
				return saved, e
			}
		}
		for _, r := range saved.Cases {
			if r.Config.Scope == "PostUS" && source.Phase != "後半" {
				continue
			}
			if e = r.stepNight164R2(o, signals, short); e != nil {
				return saved, fmt.Errorf("%s/%s:%w", scene.Session, r.Config.ID, e)
			}
		}
		if firstPost && o.Time >= scene.USOpen+900 && normal(o) {
			for _, r := range saved.Cases {
				if r.Config.Scope == "PreUS" && (len(r.Actual.Active) > 0 || len(r.Actual.Pending) > 0) {
					return saved, fmt.Errorf("前半未完済 %s", r.Config.ID)
				}
			}
			firstPost = false
		}
	}
	wanted := map[int64]bool{}
	for _, r := range saved.Cases {
		if len(r.Actual.Active) > 0 || len(r.Actual.Pending) > 0 {
			return saved, fmt.Errorf("場末未完済 %s", r.Config.ID)
		}
		for _, p := range r.Parents {
			if p.Deferred {
				return saved, fmt.Errorf("場末待機未解消 %s", r.Config.ID)
			}
		}
		for _, ev := range r.Actual.Events {
			wanted[ev.Order.DecisionIndex] = true
			wanted[ev.FillIndex] = true
		}
		for _, tr := range r.Trace {
			wanted[tr.Index] = true
		}
		for _, m := range []Mark157{r.Actual.Risk.MinimumAt, r.Actual.Risk.PeakAt, r.Actual.Risk.DDFrom, r.Actual.Risk.DDTo, r.Actual.Risk.MinimumRealizedAt, r.Actual.Risk.MinimumUnrealizedAt} {
			wanted[m.Index] = true
		}
	}
	for _, q := range quotes {
		if wanted[q.Index] {
			saved.References = append(saved.References, q)
		}
	}
	control.Sources = saved.Sources
	if e = verifyNative164(&control); e != nil {
		return saved, e
	}
	saved.ExactChecks = control.ExactChecks
	return saved, nil
}
