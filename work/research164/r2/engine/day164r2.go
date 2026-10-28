package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
)

// DayConfig164R2 は第一巡定義を上書きしない第二巡の日中定義です。
type DayConfig164R2 struct {
	DayConfig164
	DelayQuantityCap bool     `json:"delay_quantity_cap"`
	BaseDefinitions  []string `json:"base_definitions"`
}
type DayQuantityCap164R2 struct {
	Known                          bool
	OriginalDesired, NativeInitial int
	CapturedAt                     float64
	CapturedIndex                  int64
}
type DayResult164R2 struct {
	*DayResult164
	Config DayConfig164R2                  `json:"config"`
	Caps   map[string]*DayQuantityCap164R2 `json:"delay_quantity_caps"`
}
type SavedDay164R2 struct {
	Scene  Scene             `json:"scene"`
	Cases  []*DayResult164R2 `json:"cases"`
	Source Result            `json:"source"`
	Counts map[string]int    `json:"counts"`
}

// configsDay164R2 は第一巡の保存会計と比較する新しい四定義だけを返します。
//
// 引数: なし。返り値: []DayConfig164R2。旧12条件のID・定義を変更しません。
func configsDay164R2() []DayConfig164R2 {
	old := configsDay164()
	v := []DayConfig164R2{
		{DayConfig164: old[1], BaseDefinitions: []string{"NK225_D164_01", "NK225_D164_09"}},
		{DayConfig164: old[7], DelayQuantityCap: true, BaseDefinitions: []string{"NK225_D164_07"}},
		{DayConfig164: old[1], DelayQuantityCap: true, BaseDefinitions: []string{"NK225_D164_01", "NK225_D164_09", "NK225_D164_13"}},
		{DayConfig164: old[1], DelayQuantityCap: true, BaseDefinitions: []string{"NK225_D164_14", "NK225_D164_08"}},
	}
	for i := range v {
		v[i].ID = fmt.Sprintf("NK225_D164_%02d", 12+i)
		v[i].RuleHash = ""
		v[i].Parameters = map[string]float64{}
		for k, n := range old[0].Parameters {
			v[i].Parameters[k] = n
		}
		switch i {
		case 0:
			v[i].StopAdd = true
			v[i].Description = "元部分利確後の残玉保護と追加50円損切り"
		case 1:
			v[i].Description = "失速待機の解除量と後続係数を最初の希望以下に固定"
		case 2:
			v[i].DelayInitial = true
			v[i].StopAdd = true
			v[i].Description = "残玉保護・追加50円損切り・数量上限付き失速待機"
		case 3:
			v[i].DelayInitial = true
			v[i].StopAdd = true
			v[i].ConfirmAdd = true
			v[i].Description = "14に元追加時の短期方向確認を追加"
		}
		if v[i].DelayQuantityCap {
			v[i].Parameters["待機後希望上限倍率"] = 1
			v[i].Parameters["元追加係数上限倍率"] = 1
		}
		raw, _ := json.Marshal(v[i])
		h := sha256.Sum256(raw)
		v[i].RuleHash = hex.EncodeToString(h[:])
	}
	return v
}

// newDay164R2 は旧会計を保持したまま第二巡の独立状態を作ります。
//
// 引数: c(DayConfig164R2)、scene(Scene)。返り値: *DayResult164R2。
func newDay164R2(c DayConfig164R2, scene Scene) *DayResult164R2 {
	return &DayResult164R2{DayResult164: newDay164(c.DayConfig164, scene), Config: c, Caps: map[string]*DayQuantityCap164R2{}}
}

// captureCaps164R2 は最初に延期した原行の希望量と元初回量だけを固定します。
//
// 引数: o(Observation)、start(int)。返り値: なし。後の支持や結果で記録を書き換えません。
func (r *DayResult164R2) captureCaps164R2(o strategy.Observation, start int) {
	if !r.Config.DelayQuantityCap {
		return
	}
	for _, d := range r.Decisions[start:] {
		if d.Action != "初回延期" {
			continue
		}
		if r.Caps[d.Parent] != nil {
			panic("初回数量上限の再記録")
		}
		p := r.Parents[d.Parent]
		r.Caps[d.Parent] = &DayQuantityCap164R2{Known: true, OriginalDesired: d.Desired, NativeInitial: p.OldInitial, CapturedAt: o.Time, CapturedIndex: o.Index}
	}
}

// manageDay164R2 は元の返済を優先した後で各玉の利益保護と限定損切りを判断します。
//
// 引数: o(Observation)、supports(map[int]Support157)、short(Short164)、allowEntry(bool)。返り値: なし。
func (r *DayResult164R2) manageDay164R2(o strategy.Observation, supports map[int]Support157, short Short164, allowEntry bool) {
	if !normal(o) {
		return
	}
	b := r.Actual
	for _, key := range sortedParents157(r.Parents) {
		p := r.Parents[key]
		st := r.stateDay164(key)
		s := supports[p.Side]
		p.LastSupport = s
		if p.SourceQty == 0 || o.Time >= r.Base.Scene.ForceClose {
			if st.Deferred {
				st.Cancelled = true
			}
			st.Deferred = false
			st.WaveArmed = false
			st.WaveEdge = false
			continue
		}
		for _, id := range b.Active {
			l := b.Lots[id]
			if l.Parent != key || b.reservedClose(id) > 0 {
				continue
			}
			ls := r.Lots[id]
			if ls == nil {
				ls = &DayLot164{}
				r.Lots[id] = ls
			}
			mark := o.Bid
			if l.Side < 0 {
				mark = o.Ask
			}
			gain := float64(l.Side) * (mark - l.Entry)
			original := l.Kind == "initial" || l.Kind == "source_add" || l.Kind == "delayed_initial"
			if r.Config.Half100 && original && !ls.Milestone100 && gain >= 100 {
				ls.Milestone100 = true
				ls.MilestoneAt = o.Time
				ls.MilestoneIndex = o.Index
				n := l.Remaining / 2
				if n > 0 {
					r.protectDay164(p, o, id, "protect_half100", n, s)
				}
				r.recordDay164(p, o, "100円節目", "半量利確", l.SourceID, n, n, short, s)
				r.Decisions[len(r.Decisions)-1].ActualID = id
			}
			floor := -math.MaxFloat64
			reason := ""
			if r.Config.FloorAfter100 && ls.Milestone100 {
				floor = math.Max(50, l.Best-50)
				reason = "protect_100floor"
			}
			tight := r.Config.TightAll || (r.Config.TightReentry && l.Kind == "reentry")
			if (tight || (r.Config.ResidualFloor && ls.ResidualEligible)) && gain >= 10 && !ls.TenActivated {
				ls.TenActivated = true
				ls.ActivatedAt = o.Time
				ls.ActivatedIndex = o.Index
				r.recordDay164(p, o, "保護起動", "Actual実建値から10円", l.SourceID, 0, 0, short, s)
				r.Decisions[len(r.Decisions)-1].ActualID = id
			}
			if ls.TenActivated {
				f := 0.
				why := "protect_residual_floor"
				if tight {
					f = math.Max(0, l.Best-20)
					why = "protect_10trail20"
				}
				if f > floor {
					floor = f
					reason = why
				}
			}
			if floor != -math.MaxFloat64 && gain <= floor {
				r.protectDay164(p, o, id, reason, l.Remaining, s)
				continue
			}
			if gain <= -50 && ((r.Config.StopAdd && l.Kind == "source_add") || (r.Config.ReentryStop && l.Kind == "reentry")) {
				r.protectDay164(p, o, id, "tactical_stop50", l.Remaining, s)
			}
		}
		waveEdge := false
		if st.WaveArmed {
			mark := o.Bid
			if p.Side < 0 {
				mark = o.Ask
			}
			d := float64(p.Side)
			if d*(mark-st.Extreme) < 0 {
				st.Extreme = mark
			}
			if allowEntry {
				wave := (d*(st.Extreme-st.ExitPrice) <= -20 && d*(mark-st.Extreme) >= 20) || d*(mark-st.ExitPrice) >= 40
				condition := wave && forwardDay164(short, p.Side)
				waveEdge = condition && !st.WaveEdge
				st.WaveEdge = condition
			}
		}
		if !allowEntry || b.hasPending(key) || r.Canonical.hasPending(key) || p.Rejected != "" {
			continue
		}
		if st.Deferred {
			if o.Time-st.DeferredAt > 30 {
				st.Deferred = false
				st.Cancelled = true
				p.Rejected = "初回再加速待機30秒超"
				r.recordDay164(p, o, "初回取消", p.Rejected, st.DeferredSource, 0, 0, short, s)
				continue
			}
			if recoverDay164(short, p.Side) {
				desired := r.Base.desired157(s)
				if r.Config.DelayQuantityCap {
					cap := r.Caps[p.Key]
					if cap == nil || !cap.Known {
						panic("延期上限の初回記録なし")
					}
					desired = min(desired, cap.OriginalDesired)
				}
				want := quantize157(float64(desired)*math.Min(1, float64(p.SourceQty)/float64(max(1, p.SourcePeak))), 1)
				n := r.openLinkedDay164(p, o, "delayed_initial", want, s)
				r.recordDay164(p, o, "延期解除", "30秒以内再加速", st.DeferredSource, want, n, short, s)
				if n > 0 {
					p.InitialQty = n
					p.Factor = float64(n) / float64(p.SourceQty)
					if r.Config.DelayQuantityCap {
						cap := r.Caps[p.Key]
						p.Factor = math.Min(p.Factor, float64(cap.OriginalDesired)/float64(max(1, cap.NativeInitial)))
					}
					st.Deferred = false
				}
			}
			continue
		}
		if st.WaveArmed && r.Config.Reentry {
			if !waveEdge {
				continue
			}
			a, z := b.position(key, "")
			want := quantize157(float64(r.Base.desired157(s))*math.Min(1, float64(p.SourceQty)/float64(max(1, p.SourcePeak))), 1) - (a + z)
			want = max(0, want)
			n := r.openLinkedDay164(p, o, "reentry", want, s)
			r.recordDay164(p, o, "再参加判断", "保護後の新しい波", "", want, n, short, s)
			if n > 0 {
				st.WaveArmed = false
				st.Reentries++
			}
		}
	}
}

// stepDay164R2 は元源・保護・再参加を原行順で動かし、00は正本を直接実行します。
//
// 引数: r(*DayResult164R2)、o(Observation)、signals([]Signal)、supports(map[int]Support157)、short(Short164)。返り値: error。
func stepDay164R2(r *DayResult164R2, o strategy.Observation, signals []strategy.Signal, supports map[int]Support157, short Short164) error {
	if r.Config.ID == "NK225_D164_00" {
		return step157(r.Base, o, signals, supports)
	}
	p := r.Base
	p.ObservationEnd = o.Time
	p.Canonical.mark(o)
	p.Actual.mark(o)
	fills, e := p.Canonical.fill(o)
	if e != nil {
		return e
	}
	p.afterFills157(fills, o)
	actual, e := p.Actual.fill(o)
	if e != nil {
		return e
	}
	p.Canonical.mark(o)
	p.Actual.mark(o)
	r.afterDayFills164(actual, o)
	if normal(o) {
		for _, key := range sortedParents157(p.Parents) {
			cl, cs := p.Canonical.position(key, "")
			al, as := p.Actual.position(key, "")
			diff := cl - cs - al + as
			p.ProjectionChecks++
			p.ProjectionMaxDifference = math.Max(p.ProjectionMaxDifference, math.Abs(float64(diff)))
			if diff != 0 {
				return errors.New("日中親内純量差")
			}
		}
	}
	closes, news := []strategy.Signal{}, []strategy.Signal{}
	for _, sig := range signals {
		if sig.Action == "close" {
			closes = append(closes, sig)
		} else {
			news = append(news, sig)
		}
	}
	p.source157(o, closes, supports)
	for _, parent := range p.Parents {
		if parent.SourceQty == 0 || o.Time >= p.Scene.ForceClose {
			p.Canonical.closeQuantity(parent, o, "", "boundary", 1000, supports[parent.Side])
		}
	}
	p.project157(o)
	r.manageDay164R2(o, supports, short, false)
	beforeDecisions := len(r.Decisions)
	r.sourceNewsDay164(o, news, supports, short)
	r.captureCaps164R2(o, beforeDecisions)
	r.manageDay164R2(o, supports, short, true)
	if e = r.projectNewDay164(o); e != nil {
		return e
	}
	for _, x := range p.Parents {
		cl, cs := p.Canonical.position(x.Key, "")
		al, as := p.Actual.position(x.Key, "")
		x.Finished = (x.SourceQty == 0 || x.Rejected != "") && cl+cs+al+as == 0 && !p.Canonical.hasPending(x.Key) && !p.Actual.hasPending(x.Key)
	}
	for _, b := range []*Ledger157{p.Canonical, p.Actual} {
		a, z := b.position("", "")
		for _, ord := range b.Pending {
			if len(ord.Targets) == 0 {
				if ord.Side > 0 {
					a += ord.Quantity
				} else {
					z += ord.Quantity
				}
			}
		}
		if a > 100 || z > 100 {
			return errors.New("日中片側100micro上限")
		}
	}
	return nil
}

// runDay164R2 はJ02の元S01を一度逐次運転し、独立した12日中条件へ通知します。
//
// 引数: scene(Scene)、configs([]DayConfig164R2)、expressions(map[string]string)。返り値: SavedDay164R2 と error。
func runDay164R2(scene Scene, configs []DayConfig164R2, expressions map[string]string) (SavedDay164R2, error) {
	result := SavedDay164R2{Scene: scene}
	if scene.Kind != "Day" {
		return result, errors.New("Day専用手法への別時間枠入力")
	}
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
		result.Cases = append(result.Cases, newDay164R2(c, scene))
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
		short := short164(support, o.Time)
		for _, c := range result.Cases {
			if e = stepDay164R2(c, o, signals, ss, short); e != nil {
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
		c.SourceDecisions = c.Base.Decisions
		c.ProjectionChecks = c.Base.ProjectionChecks
		c.ProjectionMaxDifference = c.Base.ProjectionMaxDifference
		if !scene.Partial && (len(c.Actual.Active) > 0 || len(c.Actual.Pending) > 0 || len(c.Canonical.Active) > 0 || len(c.Canonical.Pending) > 0) {
			return result, fmt.Errorf("%s完了場未解消", c.Config.ID)
		}
	}
	return result, nil
}
