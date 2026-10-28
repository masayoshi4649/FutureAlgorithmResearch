package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"futurealgorithm/sessiontrader/internal/rules"
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
	"sort"
	"strings"
)

// DayConfig164 は日中の一意な手法定義です。対象時間や数字を変える場合は別IDにします。
type DayConfig164 struct {
	ID            string `json:"id"`
	Scope         string `json:"scope"`
	Description   string `json:"description"`
	RuleHash      string `json:"rule_hash"`
	ResidualFloor bool   `json:"residual_floor"`
	Half100       bool   `json:"half_100"`
	FloorAfter100 bool   `json:"floor_after_100"`
	TightAll      bool   `json:"tight_all"`
	Reentry       bool   `json:"reentry"`
	ReentryStop   bool   `json:"reentry_stop"`
	DelayInitial  bool   `json:"delay_initial"`
	ConfirmAdd    bool   `json:"confirm_add"`
	StopAdd       bool   `json:"stop_add"`
	TightReentry  bool   `json:"tight_reentry"`
}

type ShortWindow164 struct {
	Known                                 bool
	Move, Speed, Elapsed, Endpoint, Delay float64
	Reason                                string
}
type Short164 struct {
	Five, Fifteen ShortWindow164
	Time, Mid     float64
}
type DayParent164 struct {
	Deferred            bool
	DeferredAt          float64
	DeferredSource      string
	Cancelled           bool
	WaveArmed, WaveEdge bool
	ExitPrice, Extreme  float64
	Reentries           int
}
type DayLot164 struct{ ResidualEligible, Milestone100, TenActivated bool }
type DayDecision164 struct {
	Parent, Action, Reason, SourceID string
	Index                            int64
	Time                             float64
	Desired, Accepted                int
	Short                            Short164
	Support                          Support157
}
type DayResult164 struct {
	Config    DayConfig164                    `json:"config"`
	Actual    *Ledger157                      `json:"actual"`
	Canonical *Ledger157                      `json:"canonical"`
	Parents   map[string]*AllocationParent157 `json:"parents"`
	States    map[string]*DayParent164        `json:"states"`
	Lots      map[string]*DayLot164           `json:"lot_states"`
	Decisions []DayDecision164                `json:"decisions"`
	Counts    map[string]int                  `json:"counts"`
	Base      *PolicyResult157                `json:"baseline_policy"`
}
type SavedDay164 struct {
	Scene  Scene           `json:"scene"`
	Cases  []*DayResult164 `json:"cases"`
	Source Result          `json:"source"`
	Counts map[string]int  `json:"counts"`
}

// configsDay164 は成績を見る前に固定した12条件を返します。
//
// 引数: なし。返り値: []DayConfig164。規則ハッシュはIDと条件内容のJSONから算出します。
func configsDay164() []DayConfig164 {
	v := []DayConfig164{
		{Description: "00157第二巡J02正本"},
		{Description: "元の利益部分返済後だけ残玉を建値保護", ResidualFloor: true},
		{Description: "元玉が100円順行したら半量利確", Half100: true},
		{Description: "100円半量利確と残り50円床・50円追尾", Half100: true, FloorAfter100: true},
		{Description: "全玉10円順行で建値床・20円追尾", TightAll: true},
		{Description: "早い保護と新しい波への再参加", TightAll: true, Reentry: true, TightReentry: true},
		{Description: "再参加玉だけ50円逆行退出を追加", TightAll: true, Reentry: true, TightReentry: true, ReentryStop: true},
		{Description: "初回失速時だけ最大30秒再加速待ち", DelayInitial: true},
		{Description: "元追加だけ5秒15秒の同方向を確認", ConfirmAdd: true},
		{Description: "元追加玉だけ50円逆行退出", StopAdd: true},
		{Description: "元玉100円保護・残玉保護・入口再確認と再参加", ResidualFloor: true, Half100: true, FloorAfter100: true, DelayInitial: true, ConfirmAdd: true, StopAdd: true, Reentry: true, TightReentry: true},
		{Description: "全玉早期保護・入口再確認と再参加", TightAll: true, DelayInitial: true, ConfirmAdd: true, StopAdd: true, Reentry: true, TightReentry: true},
	}
	for i := range v {
		v[i].ID = fmt.Sprintf("NK225_D164_%02d", i)
		v[i].Scope = "Day"
		b, _ := json.Marshal(v[i])
		h := sha256.Sum256(b)
		v[i].RuleHash = hex.EncodeToString(h[:])
	}
	return v
}

// loadDay164Rules はJ02の元S01規則を同じ固定ファイルから読みます。
//
// 引数: なし。返り値: map[string]string と error。
func loadDay164Rules() (map[string]string, error) {
	s, e := rules.LoadFor("NK225_S01.toml", "s01")
	if e != nil {
		return nil, e
	}
	return s.Expressions(), nil
}

// short164 は既に受信した正常価格端点から円幅と円毎秒を分けて計算します。
//
// 引数: f(*SupportBuilder157)、at(float64)。返り値: Short164。長い空白・異常板をまたぐ窓は未知です。
func short164(f *SupportBuilder157, at float64) Short164 {
	out := Short164{Time: at}
	m := f.Markets["NK225"]
	if m == nil || len(m.Rows) == 0 {
		return out
	}
	i := len(m.Rows) - 1
	cur := m.Rows[i]
	if !cur.Valid || cur.Time != at {
		return out
	}
	out.Mid = cur.Mid
	get := func(h float64) ShortWindow164 {
		w := ShortWindow164{Reason: "過去端不足"}
		j := sort.Search(i+1, func(j int) bool { return m.Rows[j].Time > at-h }) - 1
		for j >= 0 && !m.Rows[j].Valid {
			j--
		}
		if j < 0 {
			return w
		}
		old := m.Rows[j]
		w.Endpoint = old.Time
		w.Delay = at - h - old.Time
		w.Elapsed = at - old.Time
		if w.Delay > 15 || w.Elapsed <= 0 || cur.Bad != old.Bad {
			w.Reason = "窓内欠測又は価格時計空白"
			return w
		}
		w.Move = cur.Mid - old.Mid
		w.Speed = w.Move / w.Elapsed
		w.Known = true
		w.Reason = "既知"
		return w
	}
	out.Five = get(5)
	out.Fifteen = get(15)
	return out
}

// decelDay164 は短期速度が長期速度の半分以下に弱まった順行を判定します。
//
// 引数: s(Short164)、side(int)。返り値: bool。bp幅ではなく実経過秒で割った速度です。
func decelDay164(s Short164, side int) bool {
	return s.Five.Known && s.Fifteen.Known && float64(side)*s.Fifteen.Speed > 0 && float64(side)*s.Five.Speed <= .5*float64(side)*s.Fifteen.Speed
}

// recoverDay164 は初回延期の解除を当時の再加速だけで判定します。
//
// 引数: s(Short164)、side(int)。返り値: bool。
func recoverDay164(s Short164, side int) bool {
	return s.Five.Known && s.Fifteen.Known && float64(side)*s.Five.Speed > 0 && float64(side)*s.Fifteen.Speed >= 0 && float64(side)*s.Five.Speed >= float64(side)*s.Fifteen.Speed
}

// forwardDay164 は追加と再参加の短期方向一致を判定します。
//
// 引数: s(Short164)、side(int)。返り値: bool。未知を成立と扱いません。
func forwardDay164(s Short164, side int) bool {
	return s.Five.Known && s.Fifteen.Known && float64(side)*s.Five.Move > 0 && float64(side)*s.Fifteen.Move > 0
}

// newDay164 は正本J02の数量・純量投影会計を維持して条件を分離します。
//
// 引数: c(DayConfig164)、scene(Scene)。返り値: *DayResult164。
func newDay164(c DayConfig164, scene Scene) *DayResult164 {
	var base Policy157
	for _, v := range configs157() {
		if v.ID == "J02" {
			base = v
			break
		}
	}
	base.ID = c.ID
	r := newPolicy157(base, scene)
	return &DayResult164{Config: c, Base: r, Actual: r.Actual, Canonical: r.Canonical, Parents: r.Parents, Counts: r.Counts, States: map[string]*DayParent164{}, Lots: map[string]*DayLot164{}}
}

// stateDay164 は親の戦術状態を取得し、未作成時は空状態を作ります。
//
// 引数: key(string)。返り値: *DayParent164。
func (r *DayResult164) stateDay164(key string) *DayParent164 {
	p := r.States[key]
	if p == nil {
		p = &DayParent164{}
		r.States[key] = p
	}
	return p
}

// recordDay164 は採否と当時情報を少量の判断証跡へ保存します。
//
// 引数: p(*AllocationParent157)、o(Observation)、a/reason/source(string)、want/got(int)、short(Short164)、s(Support157)。返り値: なし。
func (r *DayResult164) recordDay164(p *AllocationParent157, o strategy.Observation, a, reason, source string, want, got int, short Short164, s Support157) {
	r.Decisions = append(r.Decisions, DayDecision164{p.Key, a, reason, source, o.Index, o.Time, want, got, short, s})
	r.Counts[a+":"+reason]++
}

// sourceNewsDay164 は入口の延期・追加拒否だけを行い、元の論理残量は全通知を受け入れます。
//
// 引数: o(Observation)、news([]Signal)、supports(map[int]Support157)、short(Short164)。返り値: なし。
func (r *DayResult164) sourceNewsDay164(o strategy.Observation, news []strategy.Signal, supports map[int]Support157, short Short164) {
	accepted := []strategy.Signal{}
	seen := map[string]bool{}
	lateRejected := []strategy.Signal{}
	for _, sig := range news {
		key := fmt.Sprintf("%s/%d", sig.Owner, sig.Campaign)
		p := r.Parents[key]
		initial := (p == nil || p.OldInitial == 0) && !seen[key]
		seen[key] = true
		st := r.stateDay164(key)
		deferNow := initial && r.Config.DelayInitial && decelDay164(short, sig.Side)
		rejectAdd := !initial && (st.Deferred || st.Cancelled || (r.Config.ConfirmAdd && !forwardDay164(short, sig.Side)))
		if !deferNow && !rejectAdd {
			accepted = append(accepted, sig)
			continue
		}
		if p == nil && !initial {
			lateRejected = append(lateRejected, sig)
			continue
		}
		if p == nil {
			p = &AllocationParent157{Key: key, Owner: sig.Owner, Campaign: sig.Campaign, Side: sig.Side, Started: o.Time, SourceHolds: map[string]int{}}
			r.Parents[key] = p
		}
		p.SourceQty += sig.Quantity * 10
		p.SourcePeak = max(p.SourcePeak, p.SourceQty)
		p.SourceHolds[sig.ID+"-玉"] += sig.Quantity * 10
		p.LastSupport = supports[p.Side]
		if initial {
			p.OldInitial = sig.Quantity * 10
			r.Counts["source_initial"]++
			st.Deferred = true
			st.DeferredAt = o.Time
			st.DeferredSource = sig.ID
			r.recordDay164(p, o, "初回延期", "短期失速", sig.ID, r.Base.desired157(p.LastSupport), 0, short, p.LastSupport)
		} else {
			reason := "追加短期不一致"
			if st.Deferred {
				reason = "初回待機中の源追加"
			}
			if st.Cancelled {
				reason = "初回待機取消済み"
			}
			r.recordDay164(p, o, "追加不採用", reason, sig.ID, 0, 0, short, p.LastSupport)
		}
	}
	r.Base.source157(o, accepted, supports)
	for _, sig := range lateRejected {
		key := fmt.Sprintf("%s/%d", sig.Owner, sig.Campaign)
		p := r.Parents[key]
		if p == nil {
			panic("同原行初回の論理親なし")
		}
		p.SourceQty += sig.Quantity * 10
		p.SourcePeak = max(p.SourcePeak, p.SourceQty)
		p.SourceHolds[sig.ID+"-玉"] += sig.Quantity * 10
		r.recordDay164(p, o, "追加不採用", "追加短期不一致", sig.ID, 0, 0, short, supports[p.Side])
	}
}

// openLinkedDay164 は当時の源残量へ新数量を比例配賦し、死んだSourceIDを復活させません。
//
// 引数: p(*AllocationParent157)、o(Observation)、kind(string)、wanted(int)、s(Support157)。返り値: intは実予約数です。
func (r *DayResult164) openLinkedDay164(p *AllocationParent157, o strategy.Observation, kind string, wanted int, s Support157) int {
	q := min(wanted, r.Canonical.capacity(p.Side))
	if q <= 0 || p.SourceQty <= 0 || r.Canonical.hasPending(p.Key) {
		return 0
	}
	keys := []string{}
	total := 0
	for id, n := range p.SourceHolds {
		if n > 0 {
			keys = append(keys, id)
			total += n
		}
	}
	sort.Strings(keys)
	if total == 0 {
		return 0
	}
	alloc := map[string]int{}
	left := q
	for _, id := range keys {
		alloc[id] = q * p.SourceHolds[id] / total
		left -= alloc[id]
	}
	sort.SliceStable(keys, func(i, j int) bool {
		a, b := keys[i], keys[j]
		ra := q * p.SourceHolds[a] % total
		rb := q * p.SourceHolds[b] % total
		if ra == rb {
			return a < b
		}
		return ra > rb
	})
	for _, id := range keys {
		if left == 0 {
			break
		}
		alloc[id]++
		left--
	}
	sort.Strings(keys)
	out := 0
	for _, id := range keys {
		n := alloc[id]
		if n <= 0 {
			continue
		}
		n = r.Canonical.open(p, o, kind, kind, p.Side, n, s)
		if n > 0 {
			r.Canonical.Pending[len(r.Canonical.Pending)-1].SourceID = strings.TrimSuffix(id, "-玉")
			out += n
		}
	}
	return out
}

// afterDayFills164 は実約定された利益返済だけから残玉保護・新波待ちを始めます。
//
// 引数: fills([]Event157)、o(Observation)。返り値: なし。
func (r *DayResult164) afterDayFills164(fills []Event157, o strategy.Observation) {
	for _, e := range fills {
		if len(e.Order.Targets) == 0 {
			continue
		}
		p := r.Parents[e.Order.Parent]
		if p == nil {
			continue
		}
		st := r.stateDay164(p.Key)
		nativePartial := strings.Contains(e.Order.Reason, "source_partial/")
		if r.Config.ResidualFloor && nativePartial && e.Gross > 0 && p.SourceQty > 0 {
			for _, id := range r.Actual.Active {
				l := r.Actual.Lots[id]
				if l.Parent == p.Key {
					ls := r.Lots[id]
					if ls == nil {
						ls = &DayLot164{}
						r.Lots[id] = ls
					}
					ls.ResidualEligible = true
				}
			}
			r.Counts["実益部分返済後の残玉資格"]++
		}
		protection := strings.Contains(e.Order.Reason, "protect_")
		if r.Config.Reentry && protection && p.SourceQty > 0 {
			st.WaveArmed = true
			st.WaveEdge = false
			st.ExitPrice = e.Price
			st.Extreme = e.Price
			r.Counts["利益保護後の新波待ち"]++
		}
	}
}

// manageDay164 は元の返済を優先した後で各玉の利益保護と限定損切りを判断します。
//
// 引数: o(Observation)、supports(map[int]Support157)、short(Short164)、allowEntry(bool)。返り値: なし。
func (r *DayResult164) manageDay164(o strategy.Observation, supports map[int]Support157, short Short164, allowEntry bool) {
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
				n := l.Remaining / 2
				if n > 0 {
					r.protectDay164(p, o, id, "protect_half100", n, s)
				}
				r.recordDay164(p, o, "100円節目", "半量利確", l.SourceID, n, n, short, s)
			}
			floor := -math.MaxFloat64
			reason := ""
			if r.Config.FloorAfter100 && ls.Milestone100 {
				floor = math.Max(50, l.Best-50)
				reason = "protect_100floor"
			}
			tight := r.Config.TightAll || (r.Config.TightReentry && l.Kind == "reentry")
			if (tight || (r.Config.ResidualFloor && ls.ResidualEligible)) && gain >= 10 {
				ls.TenActivated = true
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
				want := quantize157(float64(r.Base.desired157(s))*math.Min(1, float64(p.SourceQty)/float64(max(1, p.SourcePeak))), 1)
				n := r.openLinkedDay164(p, o, "delayed_initial", want, s)
				r.recordDay164(p, o, "延期解除", "30秒以内再加速", st.DeferredSource, want, n, short, s)
				if n > 0 {
					p.InitialQty = n
					p.Factor = float64(n) / float64(p.SourceQty)
					st.Deferred = false
				}
			}
			continue
		}
		if st.WaveArmed && r.Config.Reentry {
			mark := o.Bid
			if p.Side < 0 {
				mark = o.Ask
			}
			d := float64(p.Side)
			if d*(mark-st.Extreme) < 0 {
				st.Extreme = mark
			}
			wave := (d*(st.Extreme-st.ExitPrice) <= -20 && d*(mark-st.Extreme) >= 20) || d*(mark-st.ExitPrice) >= 40
			condition := wave && forwardDay164(short, p.Side)
			edge := condition && !st.WaveEdge
			st.WaveEdge = condition
			if !edge {
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

// protectDay164 はActual所有IDの返済を予約し、Canonicalの同量を同期して再投影を防ぎます。
//
// 引数: p(*AllocationParent157)、o(Observation)、id/reason(string)、quantity(int)、s(Support157)。返り値: intは予約数量です。
// 同じSourceID・役割のCanonicalを先に減らし、不足分は同親最古順です。独自保護の判断はActualだけです。
func (r *DayResult164) protectDay164(p *AllocationParent157, o strategy.Observation, id, reason string, quantity int, s Support157) int {
	l := r.Actual.Lots[id]
	if l == nil {
		return 0
	}
	q := min(quantity, l.Remaining-r.Actual.reservedClose(id))
	if q <= 0 {
		return 0
	}
	ids := []string{}
	for _, cid := range r.Canonical.Active {
		c := r.Canonical.Lots[cid]
		if c.Parent == p.Key && c.Side == l.Side {
			ids = append(ids, cid)
		}
	}
	sort.SliceStable(ids, func(i, j int) bool {
		a, b := r.Canonical.Lots[ids[i]], r.Canonical.Lots[ids[j]]
		am := a.SourceID == l.SourceID && a.Kind == l.Kind
		bm := b.SourceID == l.SourceID && b.Kind == l.Kind
		return am && !bm
	})
	available := 0
	for _, cid := range ids {
		c := r.Canonical.Lots[cid]
		available += c.Remaining - r.Canonical.reservedClose(cid)
	}
	q = min(q, available)
	if q <= 0 {
		return 0
	}
	got := r.Actual.closeLot(p, o, id, reason, q, s)
	left := got
	orders := []string{}
	for _, cid := range ids {
		n := r.Canonical.closeLot(p, o, cid, reason, left, s)
		if n > 0 {
			orders = append(orders, r.Canonical.Pending[len(r.Canonical.Pending)-1].ID)
			left -= n
		}
		if left == 0 {
			break
		}
	}
	if left != 0 {
		panic("Actual保護とCanonical同期の数量不足")
	}
	actual := &r.Actual.Pending[len(r.Actual.Pending)-1]
	actual.CanonicalOrderIDs = orders
	actual.CanonicalKinds = []string{l.Kind}
	return got
}

// projectNewDay164 は新規だけをActualへ役割・SourceID付きで写します。
//
// 引数: o(Observation)。返り値: error。元Source返済は先行する旧FIFO投影、独自返済は所有ID指定済みです。
func (r *DayResult164) projectNewDay164(o strategy.Observation) error {
	for _, key := range sortedParents157(r.Parents) {
		p := r.Parents[key]
		cl, cs := r.Canonical.position(key, "")
		al, as := r.Actual.position(key, "")
		target := cl - cs
		have := al - as
		for _, ord := range r.Canonical.Pending {
			if ord.Parent == key {
				target += ord.Side * ord.Quantity
			}
		}
		for _, ord := range r.Actual.Pending {
			if ord.Parent == key {
				have += ord.Side * ord.Quantity
			}
		}
		delta := target - have
		if delta == 0 {
			continue
		}
		if delta*p.Side <= 0 {
			return fmt.Errorf("独自同期後に未投影返済 %s %d", key, delta)
		}
		left := delta * p.Side
		for _, ord := range r.Canonical.Pending {
			if ord.Parent != key || len(ord.Targets) > 0 {
				continue
			}
			q := min(left, ord.Quantity)
			if q <= 0 {
				continue
			}
			n := r.Actual.open(p, o, ord.Kind, ord.Reason, ord.Side, q, ord.Support)
			if n > 0 {
				a := &r.Actual.Pending[len(r.Actual.Pending)-1]
				a.SourceID = ord.SourceID
				a.CanonicalKinds = []string{ord.Kind}
				a.CanonicalOrderIDs = []string{ord.ID}
				left -= n
			}
			if left == 0 {
				break
			}
		}
		if left != 0 {
			return fmt.Errorf("新規投影の数量不足 %s %d", key, left)
		}
	}
	return nil
}

// stepDay164 は元源・保護・再参加を原行順で動かし、00は正本を直接実行します。
//
// 引数: r(*DayResult164)、o(Observation)、signals([]Signal)、supports(map[int]Support157)、short(Short164)。返り値: error。
func stepDay164(r *DayResult164, o strategy.Observation, signals []strategy.Signal, supports map[int]Support157, short Short164) error {
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
	r.manageDay164(o, supports, short, false)
	r.sourceNewsDay164(o, news, supports, short)
	r.manageDay164(o, supports, short, true)
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

// runDay164 はJ02の元S01を一度逐次運転し、独立した12日中条件へ通知します。
//
// 引数: scene(Scene)、configs([]DayConfig164)、expressions(map[string]string)。返り値: SavedDay164 と error。
func runDay164(scene Scene, configs []DayConfig164, expressions map[string]string) (SavedDay164, error) {
	result := SavedDay164{Scene: scene}
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
		result.Cases = append(result.Cases, newDay164(c, scene))
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
			if e = stepDay164(c, o, signals, ss, short); e != nil {
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
		if !scene.Partial && (len(c.Actual.Active) > 0 || len(c.Actual.Pending) > 0 || len(c.Canonical.Active) > 0 || len(c.Canonical.Pending) > 0) {
			return result, fmt.Errorf("%s完了場未解消", c.Config.ID)
		}
	}
	return result, nil
}
