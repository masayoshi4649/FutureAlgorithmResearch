package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
)

type NightConfig164 struct {
	ID             string             `json:"id"`
	Scope          string             `json:"scope"`
	RuleHash       string             `json:"rule_hash"`
	Native         string             `json:"native,omitempty"`
	Protection     string             `json:"protection"`
	Reentry        bool               `json:"reentry"`
	RiskBudget     float64            `json:"risk_budget"`
	Parameters     NightParameters164 `json:"parameters"`
	NativeRuleFile string             `json:"native_rule_file,omitempty"`
	NativeRuleSHA  string             `json:"native_rule_sha256,omitempty"`
}
type NightParameters164 struct {
	WindowsSeconds                                                                                []int `json:"windows_seconds"`
	ShortEndpointDelay, LongEndpointDelay, PathMaximumGap                                         float64
	PreMinimumR, PostMinimumR, RGrid, SpreadMultiplier, RangeDivisor                              float64
	QuantityMaximum, PointValue                                                                   int
	QuantityProgressWeight, QuantityEfficiencyWeight, ProgressR                                   float64
	PreAdverseR, PreReboundR, PostTrendR, MinimumER120, PullbackR, MaximumPullbackR, PostReboundR float64
	AddDistanceR, AddSeconds, ReentrySeconds, ProfitPullbackR, ProfitReboundR                     float64
	BeforeUSCloseSeconds, AfterUSStartSeconds                                                     float64
	EntryRepresentative, PathUnknown, NormalRearm, ProfitFloor, InitialRisk, QuantityFormula      string
}

// nightParameters164 は数値・式・時計の固定正本を返します。
//
// 引数: なし。返り値: NightParameters164。結果を見て変更しません。
func nightParameters164() NightParameters164 {
	return NightParameters164{
		WindowsSeconds: []int{5, 15, 60, 120, 300}, ShortEndpointDelay: 1, LongEndpointDelay: 15, PathMaximumGap: 15,
		PreMinimumR: 40, PostMinimumR: 60, RGrid: 10, SpreadMultiplier: 2, RangeDivisor: 4, QuantityMaximum: 100, PointValue: 10,
		QuantityProgressWeight: .5, QuantityEfficiencyWeight: .5, ProgressR: .5, PreAdverseR: 1, PreReboundR: .5, PostTrendR: 1, MinimumER120: .35, PullbackR: .5, MaximumPullbackR: 1.5, PostReboundR: .25,
		AddDistanceR: .5, AddSeconds: 10, ReentrySeconds: 10, ProfitPullbackR: .5, ProfitReboundR: .25, BeforeUSCloseSeconds: 900, AfterUSStartSeconds: 900,
		EntryRepresentative: "価格時計各時刻の最初正常原行。利益床と損切りは全正常原行", PathUnknown: "経路内不正BBO又は正常時計間隔15秒超でERと範囲は未知。両端価格変化とは分離", NormalRearm: "完済後に既知Own15が方向非正、その後新しいパターン。未知は再armしない", ProfitFloor: "玉別max(0,最高返済側利益-R)、単調、次板約定", InitialRisk: "各注文判断R固定。実建値からR逆行、各玉max(0,-床)*実残量*10＋新規予約R*q*10<=50000", QuantityFormula: "floor(100*clip(0.5*min(1,d*Own15/(0.5R))+0.5*ER15,0,1))。未校正係数"}
}

type NightGuard164 struct {
	R, Floor      float64
	Active        bool
	DecisionIndex int64
	DecisionTime  float64
}
type NightSetup164 struct {
	Stage                  int
	At, Favorable, Adverse float64
	Index                  int64
	ProfitRoute            bool
}
type NightParent164 struct {
	Base                       AllocationParent157
	LastEntry, LastR, LastFill float64
	LastIndex                  int64
	Closed                     bool
	ExitReason                 string
	InitialKind                string
	NonTrailExit               bool
}
type NightSide164 struct {
	Parent     string
	Ready      bool
	FlatTime   float64
	FlatIndex  int64
	Setup      NightSetup164
	ProfitSeed bool
}
type NightTrace164 struct {
	Kind, Reason, Parent, OrderID  string
	Side, Quantity                 int
	Time, R, RiskBefore, RiskAfter float64
	Index                          int64
	Features                       NightFeatures164
}
type NightResult164 struct {
	Config         NightConfig164             `json:"config"`
	Actual         *Ledger157                 `json:"actual"`
	Parents        map[string]*NightParent164 `json:"parents"`
	Guards         map[string]*NightGuard164  `json:"guards"`
	PendingRisk    map[string]NightGuard164   `json:"pending_risk"`
	Trace          []NightTrace164            `json:"trigger_trace"`
	Counts         map[string]int             `json:"counts"`
	ObservationEnd float64                    `json:"observation_end"`
	Start, End     float64
	Sides          map[int]*NightSide164 `json:"-"`
	Sequence       int                   `json:"-"`
}

// configsNight164 は米国前後の不変8手法を返します。
//
// 引数: なし。返り値: []NightConfig164。時間割と手法IDを分離します。
func configsNight164() []NightConfig164 {
	out := []NightConfig164{}
	for _, group := range []struct{ prefix, scope, native string }{{"P", "PreUS", "P05"}, {"U", "PostUS", "D07"}} {
		for i := 0; i < 4; i++ {
			c := NightConfig164{ID: fmt.Sprintf("NK225_%s164_%02d", group.prefix, i), Scope: group.scope, RiskBudget: 50000, Protection: "R利益開始", Parameters: nightParameters164()}
			if i == 0 {
				c.Native = group.native
				c.Protection = "元手法"
				c.RiskBudget = 0
				c.NativeRuleFile = "night_rules/NK225_" + c.Native + ".toml"
				sha, e := hashFile164(c.NativeRuleFile)
				if e != nil {
					panic(e)
				}
				c.NativeRuleSHA = sha
			}
			if i >= 2 {
				c.Protection = "正利益開始"
			}
			c.Reentry = i == 3
			b, _ := json.Marshal(c)
			hash := sha256.Sum256(b)
			c.RuleHash = hex.EncodeToString(hash[:])
			out = append(out, c)
		}
	}
	return out
}

// newNight164 は時間帯単位の独立所有と入口状態を初期化します。
//
// 引数: c(NightConfig164)、scene(Scene)。返り値: *NightResult164。
func newNight164(c NightConfig164, scene Scene) *NightResult164 {
	start, end := scene.Start, scene.USOpen-900
	if c.Scope == "PostUS" {
		start = scene.USOpen + 900
		end = scene.ForceClose
	}
	return &NightResult164{Config: c, Actual: newLedger157(c.ID, start), Parents: map[string]*NightParent164{}, Guards: map[string]*NightGuard164{}, PendingRisk: map[string]NightGuard164{}, Counts: map[string]int{}, Start: start, End: end, Sides: map[int]*NightSide164{1: {Ready: true, FlatIndex: -1}, -1: {Ready: true, FlatIndex: -1}}}
}

// trace は状態遷移と発注時の当時特徴だけを保存します。
//
// 引数: o(Observation)、f(NightFeatures164)、kind/reason/parent/order(string)、side/q(int)、risk(float64)。返り値: なし。
func (r *NightResult164) trace(o strategy.Observation, f NightFeatures164, kind, reason, parent, order string, side, q int, risk float64) {
	r.Counts[kind+"_"+reason]++
	r.Trace = append(r.Trace, NightTrace164{Kind: kind, Reason: reason, Parent: parent, OrderID: order, Side: side, Quantity: q, Time: o.Time, Index: o.Index, R: risk, Features: f})
}

// riskUsed は返済予約を控除せず、各玉と新規予約の非負危険を合計します。
//
// 引数: なし。返り値: float64は停止線までの潜在円損失で、約定損失保証ではありません。
func (r *NightResult164) riskUsed() float64 {
	sum := 0.
	for _, id := range r.Actual.Active {
		g := r.Guards[id]
		if g == nil {
			continue
		}
		floor := -g.R
		if g.Active {
			floor = math.Max(floor, g.Floor)
		}
		sum += math.Max(0, -floor) * float64(r.Actual.Lots[id].Remaining) * 10
	}
	for _, o := range r.Actual.Pending {
		if len(o.Targets) == 0 {
			g, ok := r.PendingRisk[o.ID]
			if ok {
				sum += g.R * float64(o.Quantity) * 10
			}
		}
	}
	return sum
}

// reserveNight164 は価格危険枠と方向枠の両方で数量を制限し次板新規を予約します。
//
// 引数: p(*NightParent164)、o(Observation)、f(NightFeatures164)、kind(string)、want(int)、risk(float64)。返り値: int。
func (r *NightResult164) reserveNight164(p *NightParent164, o strategy.Observation, f NightFeatures164, kind string, want int, risk float64) int {
	before := r.riskUsed()
	q := min(want, r.Actual.capacity(p.Base.Side))
	q = min(q, int(math.Floor(math.Max(0, r.Config.RiskBudget-before)/(risk*10))))
	if q <= 0 {
		r.Counts["新規_危険又は方向枠不足"]++
		return 0
	}
	n := r.Actual.open(&p.Base, o, kind, kind, p.Base.Side, q, Support157{})
	order := r.Actual.Pending[len(r.Actual.Pending)-1].ID
	r.PendingRisk[order] = NightGuard164{R: risk, Floor: -risk, DecisionIndex: o.Index, DecisionTime: o.Time}
	r.trace(o, f, "新規", kind, p.Base.Key, order, p.Base.Side, n, risk)
	t := &r.Trace[len(r.Trace)-1]
	t.RiskBefore = before
	t.RiskAfter = r.riskUsed()
	return n
}

// fillNight164 は次正常原行約定を受け、新玉の危険と完済後の準備を更新します。
//
// 引数: o(Observation)。返り値: error。
func (r *NightResult164) fillNight164(o strategy.Observation) error {
	r.Actual.mark(o)
	events, e := r.Actual.fill(o)
	if e != nil {
		return e
	}
	r.Actual.mark(o)
	for _, v := range events {
		p := r.Parents[v.Order.Parent]
		if p == nil {
			return fmt.Errorf("夜親なし %s", v.Order.Parent)
		}
		if len(v.Order.Targets) == 0 {
			g, ok := r.PendingRisk[v.Order.ID]
			if !ok {
				return fmt.Errorf("夜新規Rなし")
			}
			r.Guards[v.HoldID] = &g
			delete(r.PendingRisk, v.Order.ID)
			p.LastEntry = v.Price
			p.LastR = g.R
			p.LastFill = v.FillTime
			p.LastIndex = v.FillIndex
		} else {
			p.ExitReason = v.Order.Reason
			p.NonTrailExit = p.NonTrailExit || v.Order.Reason != "利益床"
		}
	}
	for _, v := range events {
		if len(v.Order.Targets) == 0 {
			continue
		}
		p := r.Parents[v.Order.Parent]
		if p.Closed {
			continue
		}
		l, s := r.Actual.position(p.Base.Key, "")
		if l+s == 0 && !r.Actual.hasPending(p.Base.Key) {
			p.Closed = true
			side := r.Sides[p.Base.Side]
			side.Parent = ""
			side.Ready = false
			side.FlatTime = o.Time
			side.FlatIndex = o.Index
			side.Setup = NightSetup164{}
			pv := r.Actual.Parents[p.Base.Key]
			side.ProfitSeed = r.Config.Reentry && !p.NonTrailExit && p.ExitReason == "利益床" && pv != nil && pv.Realized > 0
			r.Counts["完済"]++
		}
	}
	return nil
}

// protectNight164 は全正常板で玉別の停止線と単調な利益床を判断します。
//
// 引数: o(Observation)、f(NightFeatures164)。返り値: boolは返済の予約があることです。
func (r *NightResult164) protectNight164(o strategy.Observation, f NightFeatures164) bool {
	for _, id := range r.Actual.Active {
		l := r.Actual.Lots[id]
		g := r.Guards[id]
		p := r.Parents[l.Parent]
		if g == nil || p == nil {
			continue
		}
		price := o.Bid
		if l.Side < 0 {
			price = o.Ask
		}
		gain := float64(l.Side) * (price - l.Entry)
		if !g.Active && ((r.Config.Protection == "正利益開始" && gain > 0) || (r.Config.Protection == "R利益開始" && l.Best >= g.R)) {
			g.Active = true
			g.Floor = math.Max(0, l.Best-g.R)
			r.trace(o, f, "保護起動", r.Config.Protection, p.Base.Key, id, l.Side, l.Remaining, g.R)
		}
		if g.Active {
			g.Floor = math.Max(g.Floor, math.Max(0, l.Best-g.R))
		}
		reason := ""
		if o.Time >= r.End {
			reason = "時間枠終了"
		} else if g.Active && gain <= g.Floor {
			reason = "利益床"
		} else if gain <= -g.R {
			reason = "玉別損切"
		}
		if reason != "" {
			q := r.Actual.closeLot(&p.Base, o, id, reason, l.Remaining, Support157{})
			if q > 0 {
				r.trace(o, f, "返済", reason, p.Base.Key, id, l.Side, q, g.R)
			}
		}
	}
	return len(r.Actual.Pending) > 0
}

// patternNight164 は準備後に観測された極値だけから次の新規候補を返します。
//
// 引数: side(int)、o(Observation)、f(NightFeatures164)、risk(float64)。返り値: boolと入口種別string。
func (r *NightResult164) patternNight164(side int, o strategy.Observation, f NightFeatures164, risk float64) (bool, string) {
	s := r.Sides[side]
	a := &s.Setup
	d := float64(side)
	x := d * f.Mid
	if a.Stage == 0 {
		if s.ProfitSeed && o.Index > s.FlatIndex {
			a.Stage = 1
			a.ProfitRoute = true
			a.Favorable = x
			a.Adverse = x
			a.At = o.Time
			a.Index = o.Index
			s.ProfitSeed = false
			r.trace(o, f, "準備", "利益後新極値", "", "", side, 0, risk)
			return false, ""
		}
		if !s.Ready {
			return false, ""
		}
		if r.Config.Scope == "PreUS" {
			if !f.Known60 {
				return false, ""
			}
			adverse := f.High60 - f.Mid
			if side < 0 {
				adverse = f.Mid - f.Low60
			}
			if adverse < risk {
				return false, ""
			}
			a.Stage = 2
			a.Adverse = x
		} else {
			if !f.Known120 || !f.Path120 || d*f.Own120 < risk || f.ER120 < .35 {
				return false, ""
			}
			a.Stage = 1
			a.Favorable = x
			a.Adverse = x
		}
		a.At = o.Time
		a.Index = o.Index
		r.trace(o, f, "準備", "通常入口", "", "", side, 0, risk)
		return false, ""
	}
	if o.Index <= a.Index {
		return false, ""
	}
	if r.Config.Scope == "PostUS" && !a.ProfitRoute {
		if !f.Known120 || !f.Path120 {
			return false, ""
		}
		if d*f.Own120 < risk || f.ER120 < .35 {
			*a = NightSetup164{}
			r.Counts["準備_中期条件解消"]++
			return false, ""
		}
	}
	if a.Stage == 1 {
		a.Favorable = math.Max(a.Favorable, x)
		pull := a.Favorable - x
		if !a.ProfitRoute && pull > 1.5*risk {
			*a = NightSetup164{}
			r.Counts["準備_押戻り超過"]++
			return false, ""
		}
		if pull >= .5*risk {
			a.Stage = 2
			a.Adverse = x
			a.Index = o.Index
		}
		return false, ""
	}
	a.Adverse = math.Min(a.Adverse, x)
	if r.Config.Scope == "PostUS" && !a.ProfitRoute && a.Favorable-a.Adverse > 1.5*risk {
		*a = NightSetup164{}
		r.Counts["準備_押戻り超過"]++
		return false, ""
	}
	rebound := .5 * risk
	if r.Config.Scope == "PostUS" || a.ProfitRoute {
		rebound = .25 * risk
	}
	if x-a.Adverse >= rebound && shortNight164(f, side) {
		kind := "初回"
		if a.ProfitRoute {
			kind = "利益後再参加"
		}
		return true, kind
	}
	return false, ""
}

// stepNight164 は返済を新規より先に処理し、新しい価格時計だけで入口を判断します。
//
// 引数: o(Observation)、f(NightFeatures164)。返り値: error。
func (r *NightResult164) stepNight164(o strategy.Observation, f NightFeatures164) error {
	if o.Time < r.Start {
		return nil
	}
	r.ObservationEnd = o.Time
	if e := r.fillNight164(o); e != nil {
		return e
	}
	if !normal(o) {
		r.Counts["現在気配異常"]++
		return nil
	}
	closing := r.protectNight164(o, f)
	if o.Time >= r.End || !f.FirstNormal {
		return nil
	}
	r.Counts["入口観測"]++
	for _, side := range []int{1, -1} {
		s := r.Sides[side]
		if s.Parent == "" && !s.Ready && o.Index > s.FlatIndex && f.Known15 && f.Path15 && float64(side)*f.Own15 <= 0 {
			s.Ready = true
			s.Setup = NightSetup164{}
			r.Counts["通常再準備解禁"]++
		}
	}
	risk, known := riskNight164(f, r.Config.Scope)
	if !known || !f.Known5 || !f.Known15 || !f.Path15 {
		r.Counts["入口_特徴未知"]++
	}
	// 短期が未知でも既に観測した極値を捨てず、発注可否だけを止めます。
	if !known {
		for side, s := range r.Sides {
			x := float64(side) * (o.Bid + o.Ask) / 2
			if s.Setup.Stage == 1 {
				s.Setup.Favorable = math.Max(s.Setup.Favorable, x)
			}
			if s.Setup.Stage == 2 {
				s.Setup.Adverse = math.Min(s.Setup.Adverse, x)
			}
		}
		return nil
	}
	if closing {
		return nil
	}
	for _, side := range []int{1, -1} {
		s := r.Sides[side]
		if s.Parent != "" {
			p := r.Parents[s.Parent]
			l, v := r.Actual.position(p.Base.Key, "")
			qty := l + v
			price := o.Bid
			if side < 0 {
				price = o.Ask
			}
			if o.Time-p.LastFill >= 10 && o.Index > p.LastIndex && float64(side)*(price-p.LastEntry) >= .5*p.LastR && shortNight164(f, side) && !r.Actual.hasPending(p.Base.Key) {
				want := quantityNight164(f, side, risk) - qty
				if want > 0 {
					r.reserveNight164(p, o, f, "順行追加", want, risk)
				}
			}
			continue
		}
		if o.Time-s.FlatTime < 10 || o.Index <= s.FlatIndex {
			continue
		}
		fire, kind := r.patternNight164(side, o, f, risk)
		if !fire {
			r.Counts["入口_準備又は価格条件未達"]++
			continue
		}
		want := quantityNight164(f, side, risk)
		if want <= 0 {
			r.Counts["入口_希望量ゼロ"]++
			continue
		}
		r.Sequence++
		key := fmt.Sprintf("%s/親%d", r.Config.ID, r.Sequence)
		p := &NightParent164{Base: AllocationParent157{Key: key, Owner: r.Config.Scope, Campaign: r.Sequence, Side: side}, InitialKind: kind}
		r.Parents[key] = p
		if r.reserveNight164(p, o, f, kind, want, risk) > 0 {
			s.Parent = key
			s.Ready = false
			s.Setup = NightSetup164{}
		} else {
			delete(r.Parents, key)
		}
	}
	return nil
}
