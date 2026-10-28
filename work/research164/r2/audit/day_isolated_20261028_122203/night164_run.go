package main

import (
	"fmt"
	"futurealgorithm/sessiontrader/internal/rules"
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
)

type QuoteNight164 struct {
	Index                int64
	Time, Bid, Ask, Last float64
	Normal               bool
}
type SavedNight164 struct {
	Scene       Scene                   `json:"scene"`
	Cases       []*NightResult164       `json:"cases"`
	Sources     []*SourceStateNative164 `json:"sources"`
	Counts      map[string]int          `json:"counts"`
	References  []QuoteNight164         `json:"reference"`
	ExactChecks int                     `json:"exact_checks"`
}

// loadNight164Rules は基準P05/D07の凍結規則を個別に読みます。
//
// 引数: なし。返り値: map[string]map[string]stringとerror。
func loadNight164Rules() (map[string]map[string]string, error) {
	sets := map[string]map[string]string{}
	for _, v := range []struct{ name, profile string }{{"P05", "p05"}, {"D07", "d07"}} {
		b, e := rules.LoadFor("night_rules/NK225_"+v.name+".toml", v.profile)
		if e != nil {
			return nil, e
		}
		sets[v.name] = b.Expressions()
	}
	return sets, nil
}

// nativeStepNight164 は元通知を数量10倍のmicro台帳へ一対一で写します。
//
// 引数: o(Observation)、signals([]Signal)。返り値: error。元の実数量配賦を変更しません。
func (r *NightResult164) nativeStepNight164(o strategy.Observation, signals []strategy.Signal) error {
	r.ObservationEnd = o.Time
	r.Actual.mark(o)
	if _, e := r.Actual.fill(o); e != nil {
		return e
	}
	r.Actual.mark(o)
	prefix := "前半/"
	if r.Config.Scope == "PostUS" {
		prefix = "後半/"
	}
	for _, sig := range signals {
		if len(sig.Owner) < len(prefix) || sig.Owner[:len(prefix)] != prefix {
			continue
		}
		key := fmt.Sprintf("%s/%d", sig.Owner, sig.Campaign)
		p := r.Parents[key]
		if p == nil {
			p = &NightParent164{Base: AllocationParent157{Key: key, Owner: sig.Owner, Campaign: sig.Campaign, Side: sig.Side}}
			r.Parents[key] = p
		}
		kind := "source_close"
		if sig.Action == "new" {
			kind = "source_add"
			if p.Base.InitialQty == 0 {
				kind = "initial"
				p.Base.InitialQty = sig.Quantity * 10
			}
			p.Base.SourceQty += sig.Quantity * 10
		} else {
			p.Base.SourceQty -= sig.Quantity * 10
		}
		ord := Order157{ID: sig.ID, Parent: key, Owner: sig.Owner, Campaign: sig.Campaign, Side: sig.Side, Quantity: sig.Quantity * 10, Kind: kind, Reason: fmt.Sprintf("source:%d", sig.ReasonCode), SourceID: sig.ID, DecisionIndex: sig.SourceIndex, DecisionTime: sig.Time, DecisionBid: o.Bid, DecisionAsk: o.Ask}
		for _, t := range sig.Targets {
			ord.Targets = append(ord.Targets, Target157{t.ID, t.Quantity * 10})
		}
		r.Actual.Pending = append(r.Actual.Pending, ord)
	}
	return nil
}

// verifyNative164 は基準別に全通知と全約定・所有数量・価格・収支を照合します。
//
// 引数: saved(*SavedNight164)。返り値: error。
func verifyNative164(saved *SavedNight164) error {
	for _, s := range saved.Sources {
		var b *NightResult164
		scope := "PreUS"
		if s.Phase == "後半" {
			scope = "PostUS"
		}
		for _, v := range saved.Cases {
			if v.Config.Scope == scope && v.Config.Native != "" {
				b = v
				break
			}
		}
		if b == nil || !s.flatNative164() || len(b.Actual.Events) != len(s.Events) {
			return fmt.Errorf("基準の完済又は約定数不一致 %s", scope)
		}
		for i, ev := range s.Events {
			sig, e := s.policySignalNative164(ev.Signal)
			if e != nil {
				return e
			}
			sig = namespaceNative164(sig, s.Phase)
			got := b.Actual.Events[i]
			if got.Order.ID != sig.ID || got.Order.Owner != sig.Owner || got.Order.Side != sig.Side || got.Order.Quantity != sig.Quantity*10 || got.Order.DecisionIndex != sig.SourceIndex || got.Order.DecisionTime != sig.Time || got.FillIndex != ev.FillIndex || got.FillTime != ev.FillTime || got.Price != ev.Price || math.Abs(got.Gross-ev.Gross) > 1e-7 || len(got.Order.Targets) != len(sig.Targets) {
				return fmt.Errorf("基準約定不一致 %s/%d", scope, i)
			}
			for j, t := range sig.Targets {
				if got.Order.Targets[j].ID != t.ID || got.Order.Targets[j].Quantity != t.Quantity*10 {
					return fmt.Errorf("基準配賦不一致")
				}
			}
			saved.ExactChecks++
		}
		if math.Abs(b.Actual.Realized-s.Gross) > 1e-7 {
			return fmt.Errorf("基準収支不一致")
		}
	}
	return nil
}

// runNight164 は共通原板を一度読み、前後8手法を別の状態として進めます。
//
// 引数: scene(Scene)、configs([]NightConfig164)、sets(map[string]map[string]string)。返り値: SavedNight164とerror。
func runNight164(scene Scene, configs []NightConfig164, sets map[string]map[string]string) (SavedNight164, error) {
	saved := SavedNight164{Scene: scene}
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
		saved.Cases = append(saved.Cases, newNight164(c, scene))
	}
	source, e := newSourceNative164(scene, "前半", "P05", sets["P05"])
	if e != nil {
		return saved, e
	}
	saved.Sources = append(saved.Sources, source)
	h := &NightHistory164{}
	quotes := []QuoteNight164{}
	firstPost := true
	for _, board := range rows {
		o, e := f.OnBoard(board)
		if e != nil {
			return saved, e
		}
		if o.Reference != "NK225" {
			continue
		}
		nf := h.add(o)
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
		for _, r := range saved.Cases {
			if r.Config.Native != "" {
				if r.Config.Scope == "PostUS" && source.Phase != "後半" {
					continue
				}
				e = r.nativeStepNight164(o, signals)
			} else {
				e = r.stepNight164(o, nf)
			}
			if e != nil {
				return saved, fmt.Errorf("%s/%s:%w", scene.Session, r.Config.ID, e)
			}
		}
		if firstPost && o.Time >= scene.USOpen+900 && normal(o) {
			for _, r := range saved.Cases {
				if r.Config.Scope == "PreUS" && (len(r.Actual.Active) > 0 || len(r.Actual.Pending) > 0) {
					return saved, fmt.Errorf("前半未完済で後半開始不可 %s", r.Config.ID)
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
	if e = verifyNative164(&saved); e != nil {
		return saved, e
	}
	return saved, nil
}
