package main

import (
	"errors"
	"fmt"
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
)

type Saved163 struct {
	Scene           Scene                `json:"scene"`
	Cases           []*TransferResult163 `json:"cases"`
	Sources         []*SourceState159    `json:"sources"`
	Counts          map[string]int       `json:"counts"`
	Transitions     []Transition159      `json:"transitions"`
	ExactChecks     int                  `json:"exact_checks"`
	HalfChecks      int                  `json:"half_checks"`
	RawFilesChecked int                  `json:"raw_files_checked"`
}

// rawHashes163 は目録の原資料集合と読取前後の内容指紋を照合します。
//
// 引数: scene(Scene)。返り値: error。人工系列では空指紋を許し、正式CLIは六資料を必須とします。
func rawHashes163(scene Scene) error {
	if len(scene.Fingerprints) == 0 {
		return nil
	}
	expected := map[string]bool{}
	for _, p := range scene.Books {
		expected[p] = true
	}
	for _, paths := range scene.Candles {
		for _, p := range paths {
			expected[p] = true
		}
	}
	if len(expected) != 6 || len(scene.Fingerprints) != 6 {
		return errors.New("原資料六件の集合不整合")
	}
	seen := map[string]bool{}
	for _, f := range scene.Fingerprints {
		if !expected[f.Path] || seen[f.Path] {
			return errors.New("原資料指紋のパス集合差")
		}
		seen[f.Path] = true
		h, e := hash163(f.Path)
		if e != nil {
			return e
		}
		if h != f.SHA {
			return fmt.Errorf("原資料の内容指紋差:%s", f.Path)
		}
	}
	return nil
}

// verify163 は全元通知を同額B00と照合し、C50の全実約定が厳密半量か検査します。
//
// 引数: result(*Saved163)。返り値: error。同一原行内の返済優先順を除き未来の値で補正しません。
func verify163(result *Saved163) error {
	if len(result.Cases) != 10 || result.Cases[0].Config.ID != "B00" || result.Cases[1].Config.ID != "C50" {
		return errors.New("対照配置不正")
	}
	base, half := result.Cases[0].Actual, result.Cases[1].Actual
	expected := map[string]SourceEvent159{}
	total := 0.0
	for _, s := range result.Sources {
		if !s.flat159() {
			return errors.New("完了場のSource未解消")
		}
		total += s.Gross
		for _, ev := range s.Events {
			sig, e := s.policySignal159(ev.Signal)
			if e != nil {
				return e
			}
			ev.Signal = namespace159(sig, ev.Phase)
			if _, ok := expected[ev.Signal.ID]; ok {
				return errors.New("元通知ID重複")
			}
			expected[ev.Signal.ID] = ev
		}
	}
	if len(base.Events) != len(expected) || len(half.Events) != len(base.Events) {
		return errors.New("対照約定数不一致")
	}
	for i, got := range base.Events {
		old, ok := expected[got.Order.ID]
		if !ok {
			return errors.New("B00に元にない通知")
		}
		sig := old.Signal
		if got.Order.Owner != sig.Owner || got.Order.Side != sig.Side || got.Order.Quantity != sig.Quantity*10 || got.Order.DecisionIndex != sig.SourceIndex || got.Order.DecisionTime != sig.Time || got.FillIndex != old.FillIndex || got.FillTime != old.FillTime || got.Price != old.Price || math.Abs(got.Gross-old.Gross) > 1e-7 {
			return fmt.Errorf("B00元約定不一致:%s", got.Order.ID)
		}
		if len(got.Order.Targets) != len(sig.Targets) {
			return errors.New("B00配賦数差")
		}
		targets := map[string]int{}
		for _, t := range sig.Targets {
			targets[t.ID] += t.Quantity * 10
		}
		for _, t := range got.Order.Targets {
			if targets[t.ID] != t.Quantity {
				return errors.New("B00配賦量差")
			}
		}
		h := half.Events[i]
		if h.Order.ID != got.Order.ID || h.Order.Side != got.Order.Side || h.Order.Owner != got.Order.Owner || h.Order.Quantity*2 != got.Order.Quantity || h.Order.DecisionIndex != got.Order.DecisionIndex || h.Order.DecisionTime != got.Order.DecisionTime || h.FillIndex != got.FillIndex || h.FillTime != got.FillTime || h.Price != got.Price || h.Gross*2 != got.Gross || len(h.Pieces) != len(got.Pieces) || len(h.Order.Targets) != len(got.Order.Targets) {
			return errors.New("C50全約定半量差")
		}
		for j, t := range got.Order.Targets {
			ht := h.Order.Targets[j]
			if ht.ID != t.ID || ht.Quantity*2 != t.Quantity {
				return errors.New("C50配賦半量差")
			}
		}
		for j, p := range got.Pieces {
			hp := h.Pieces[j]
			if hp.ID != p.ID || hp.Quantity*2 != p.Quantity || hp.Entry != p.Entry || hp.Exit != p.Exit || hp.Gross*2 != p.Gross {
				return errors.New("C50実現配賦差")
			}
		}
		result.ExactChecks++
		result.HalfChecks++
	}
	if math.Abs(base.Realized-total) > 1e-7 || half.Realized*2 != base.Realized || half.Risk.Minimum*2 != base.Risk.Minimum || half.Risk.MaxDD*2 != base.Risk.MaxDD {
		return errors.New("元収支又は半量時価の差")
	}
	return nil
}

// run163 は独立Sourceと十数量台帳へ同じ原行を渡し、元の時間枠・退出を維持します。
//
// 引数: scene(Scene)、configs([]Policy163)、sets(map[string]map[string]string)。返り値: Saved163とerror。
func run163(scene Scene, configs []Policy163, sets map[string]map[string]string) (Saved163, error) {
	result := Saved163{Scene: scene}
	if e := rawHashes163(scene); e != nil {
		return result, e
	}
	rows, counts, e := loadBoards(scene)
	if e != nil {
		return result, e
	}
	result.Counts = counts
	f, e := newFeatures(scene, scene.Start)
	if e != nil {
		return result, e
	}
	for _, c := range configs {
		result.Cases = append(result.Cases, newTransfer163(c, scene))
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
	short := &ShortBuilder163{}
	for _, board := range rows {
		support.add(board)
		o, e := f.OnBoard(board)
		if e != nil {
			return result, e
		}
		if o.Reference != "NK225" {
			continue
		}
		short.add(o)
		ss := map[int]Support157{1: support.get(o.Time, 1), -1: support.get(o.Time, -1)}
		signals := []strategy.Signal{}
		if scene.Kind == "Night" && phase == "前半" && o.Time >= scene.USOpen+900 {
			old, e := source.step159(o, false, ss)
			if e != nil {
				return result, e
			}
			signals = append(signals, old...)
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
		allowRestore := o.Time < scene.ForceClose
		if scene.Kind == "Night" && o.Time >= scene.USOpen-900 && o.Time < scene.USOpen+900 {
			allowRestore = false
		}
		shortNow := short.get()
		for _, r := range result.Cases {
			if e = r.stepTransfer163(o, signals, shortNow, allowRestore); e != nil {
				return result, fmt.Errorf("%s/%s:%w", scene.Session, r.Config.ID, e)
			}
		}
	}
	for _, r := range result.Cases {
		if len(r.Actual.Active) > 0 || len(r.Actual.Pending) > 0 {
			return result, fmt.Errorf("%sの場末未解消", r.Config.ID)
		}
	}
	if e = verify163(&result); e != nil {
		return result, e
	}
	if e = rawHashes163(scene); e != nil {
		return result, e
	}
	result.RawFilesChecked = len(scene.Fingerprints)
	return result, nil
}
