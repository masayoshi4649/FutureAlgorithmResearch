package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
	"sort"
	"strings"
)

type NightConfig164R2 struct {
	ID             string         `json:"id"`
	Scope          string         `json:"scope"`
	RuleHash       string         `json:"rule_hash"`
	Native         string         `json:"native"`
	Description    string         `json:"description"`
	TightAll       bool           `json:"tight_all"`
	ResidualFloor  bool           `json:"residual_floor"`
	TightSmall     bool           `json:"tight_small"`
	StopAdd        bool           `json:"stop_add"`
	DelayInitial   bool           `json:"delay_initial"`
	Parameters     map[string]any `json:"parameters"`
	NativeRuleFile string         `json:"native_rule_file"`
	NativeRuleSHA  string         `json:"native_rule_sha256"`
}

type NightParent164R2 struct {
	Base                AllocationParent157
	Deferred, Cancelled bool
	DeferredAt          float64
	DeferredIndex       int64
	DeferredSource      string
	InitialDesired      int
}
type NightLot164R2 struct {
	ResidualEligible, Activated        bool
	ResidualTime, ActivatedTime, Floor float64
	ResidualIndex, ActivatedIndex      int64
}
type NightTrace164R2 struct {
	Parent, Action, Reason, SourceID, ActualID string
	Index                                      int64
	Time                                       float64
	Desired, Accepted                          int
	Gain, Floor                                float64
	Short                                      Short164
}
type NightResult164R2 struct {
	Config         NightConfig164R2             `json:"config"`
	Actual         *Ledger157                   `json:"actual"`
	Parents        map[string]*NightParent164R2 `json:"parents"`
	Lots           map[string]*NightLot164R2    `json:"lot_states"`
	Trace          []NightTrace164R2            `json:"trigger_trace"`
	Counts         map[string]int               `json:"counts"`
	ObservationEnd float64                      `json:"observation_end"`
	Start, End     float64
}

// configsNight164R2 は元入口に局所保護を加える新しい8定義を返します。
//
// 引数: なし。返り値: []NightConfig164R2。第一巡の定義やハッシュは変更しません。
func configsNight164R2() []NightConfig164R2 {
	out := []NightConfig164R2{}
	for _, group := range []struct{ prefix, scope, native string }{{"P", "PreUS", "P05"}, {"U", "PostUS", "D07"}} {
		for number := 4; number <= 7; number++ {
			c := NightConfig164R2{ID: fmt.Sprintf("NK225_%s164_%02d", group.prefix, number), Scope: group.scope, Native: group.native, TightAll: number == 4, ResidualFloor: number >= 5, TightSmall: number >= 6, StopAdd: number >= 6, DelayInitial: number == 7}
			c.Description = map[int]string{4: "元入口と全実玉10円起動20円追尾", 5: "実益の元部分返済後だけ残玉建値保護", 6: "残玉保護・小量初回追尾・同親追加50円停止", 7: "06と初回失速時の最大30秒再加速待機"}[number]
			c.Parameters = map[string]any{
				"利益起動円": 10, "全玉又は小量追尾円": 20, "建値床円": 0, "元追加停止円": 50, "小量初回最大micro": 20,
				"初回最大待機秒": 30, "短期窓秒": []int{5, 15}, "過去端最大遅れ秒": 15, "減速速度比": .5,
				"短期定義": "最後正常板Time<=現在-h、端点遅れ15秒以内、途中不正BBOなし。速度=中値変化/実経過秒。未知時は元入口維持",
				"失速":   "方向15秒速度>0かつ方向5秒速度<=方向15秒速度*0.5", "再加速": "方向5秒速度>0かつ方向15秒速度>=0かつ方向5秒速度>=方向15秒速度",
				"待機数量":       "最初の元通知micro量と当初SourceIDの現在残量の小さい方。初回待機中と取消済みの同親追加は不採用。期限30秒到達は取消優先",
				"残玉資格":       "source_partialの候補Actual返済実約定が正益かつSource親残量>0。その時点の実残玉だけ。過去の利益到達を遡及起動しない",
				"Source部分返済": "SourceIDごとの現在実残量×元target数量/元ID返済前残量、micro1枚切捨て。元ID全返済は全実残量。予約済み返済は重複させない",
				"優先順":        "前行予約の次正常約定、元Source返済、元Source新規、局所保護と停止、待機解除。元返済予約がある親は独自返済と待機解除を見送る",
				"小量判定":       "親の最初の元通知量で固定。initial/delayed_initialだけ対象。source_addは担当名に依存せず別分類",
				"再参加":        "独自再参加なし。元Sourceの次親・後続通知のみ。独自返済はSource保有と内部損益を変えない",
				"片側上限micro":  100, "miniからmicro倍率": 10, "点価円": 10, "手数料円": 0,
				"米国前返済秒": 900, "米国後開始秒": 900, "場末前返済秒": 600,
				"約定": "判断後の次正常原行。利益床の次板赤字をそのまま計上。場末代理清算なし",
			}
			c.NativeRuleFile = "night_rules/NK225_" + c.Native + ".toml"
			sha, e := hashFile164(c.NativeRuleFile)
			if e != nil {
				panic(e)
			}
			c.NativeRuleSHA = sha
			b, _ := json.Marshal(c)
			h := sha256.Sum256(b)
			c.RuleHash = hex.EncodeToString(h[:])
			out = append(out, c)
		}
	}
	return out
}

// newNight164R2 は時間枠別に実所有・源残数・待機を初期化します。
//
// 引数: c(NightConfig164R2)、scene(Scene)。返り値: *NightResult164R2。
func newNight164R2(c NightConfig164R2, scene Scene) *NightResult164R2 {
	start, end := scene.Start, scene.USOpen-900
	if c.Scope == "PostUS" {
		start, end = scene.USOpen+900, scene.ForceClose
	}
	return &NightResult164R2{Config: c, Actual: newLedger157(c.ID, start), Parents: map[string]*NightParent164R2{}, Lots: map[string]*NightLot164R2{}, Counts: map[string]int{}, Start: start, End: end}
}

// recordNight164R2 は当時の原行と実玉に結び付いた判断を残します。
//
// 引数: p(*NightParent164R2)、o(Observation)、action/reason/source/id(string)、desired/accepted(int)、short(Short164)。返り値: なし。
func (r *NightResult164R2) recordNight164R2(p *NightParent164R2, o strategy.Observation, action, reason, source, id string, desired, accepted int, short Short164) {
	r.Trace = append(r.Trace, NightTrace164R2{Parent: p.Base.Key, Action: action, Reason: reason, SourceID: source, ActualID: id, Index: o.Index, Time: o.Time, Desired: desired, Accepted: accepted, Short: short})
	r.Counts[action+":"+reason]++
}

// stateLotNight164R2 は実約定IDごとの保護状態を返します。
//
// 引数: id(string)。返り値: *NightLot164R2。新玉は旧玉の床を継承しません。
func (r *NightResult164R2) stateLotNight164R2(id string) *NightLot164R2 {
	if r.Lots[id] == nil {
		r.Lots[id] = &NightLot164R2{}
	}
	return r.Lots[id]
}

// fillNight164R2 は次正常約定後の実益だけで、その時点の残玉へ資格を付けます。
//
// 引数: o(Observation)、short(Short164)。返り値: error。影の利益は参照しません。
func (r *NightResult164R2) fillNight164R2(o strategy.Observation, short Short164) error {
	r.Actual.mark(o)
	remainingAtFill := map[string]int{}
	for _, id := range r.Actual.Active {
		remainingAtFill[id] = r.Actual.Lots[id].Remaining
	}
	fills, e := r.Actual.fill(o)
	if e != nil {
		return e
	}
	r.Actual.mark(o)
	for _, f := range fills {
		if len(f.Order.Targets) == 0 {
			r.stateLotNight164R2(f.HoldID)
			remainingAtFill[f.HoldID] = f.Order.Quantity
			continue
		}
		for _, piece := range f.Pieces {
			remainingAtFill[piece.ID] -= piece.Quantity
		}
		p := r.Parents[f.Order.Parent]
		if p == nil {
			return fmt.Errorf("実約定親がありません %s", f.Order.Parent)
		}
		if r.Config.ResidualFloor && strings.HasPrefix(f.Order.Reason, "source_partial/") && f.Gross > 0 && p.Base.SourceQty > 0 {
			ids := []string{}
			for id, quantity := range remainingAtFill {
				if quantity > 0 { ids = append(ids, id) }
			}
			sort.Strings(ids)
			for _, id := range ids {
				l := r.Actual.Lots[id]
				if l.Parent != p.Base.Key {
					continue
				}
				ls := r.stateLotNight164R2(id)
				if !ls.ResidualEligible {
					ls.ResidualEligible = true
					ls.ResidualTime = o.Time
					ls.ResidualIndex = o.Index
					r.recordNight164R2(p, o, "残玉資格", "Source部分返済の実益", l.SourceID, id, 0, 0, short)
				}
			}
		}
	}
	return nil
}

// openNight164R2 は生存SourceIDの通知量以内で新規を予約します。
//
// 引数: p(*NightParent164R2)、o(Observation)、source/kind(string)、wanted(int)、short(Short164)。返り値: int。
func (r *NightResult164R2) openNight164R2(p *NightParent164R2, o strategy.Observation, source, kind string, wanted int, short Short164) int {
	wanted = min(wanted, p.Base.SourceHolds[source+"-玉"])
	q := r.Actual.open(&p.Base, o, kind, kind, p.Base.Side, wanted, Support157{})
	if q > 0 {
		r.Actual.Pending[len(r.Actual.Pending)-1].SourceID = source
	}
	r.recordNight164R2(p, o, "新規受付", kind, source, "", wanted, q, short)
	if q < wanted {
		r.Counts["片側枠による縮小又は拒否"]++
	}
	return q
}

// sourceNight164R2 は元通知だけで源残数を更新し、実残量へ返済を比例配賦します。
//
// 引数: o(Observation)、signals([]Signal)、short(Short164)。返り値: error。未来の約定は参照しません。
func (r *NightResult164R2) sourceNight164R2(o strategy.Observation, signals []strategy.Signal, short Short164) error {
	prefix := "前半/"
	if r.Config.Scope == "PostUS" {
		prefix = "後半/"
	}
	// ----------------------------------------
	// 元の返済を新規・独自保護より先に所有IDへ予約します。
	for _, sig := range signals {
		if !strings.HasPrefix(sig.Owner, prefix) || sig.Action != "close" {
			continue
		}
		key := fmt.Sprintf("%s/%d", sig.Owner, sig.Campaign)
		p := r.Parents[key]
		if p == nil {
			return fmt.Errorf("元返済親なし %s", key)
		}
		before := p.Base.SourceQty
		closed := sig.Quantity * 10
		if closed > before {
			return fmt.Errorf("元親返済過大 %s", key)
		}
		p.Base.SourceQty -= closed
		why := fmt.Sprintf("source_partial/%d", sig.ReasonCode)
		if p.Base.SourceQty == 0 {
			why = fmt.Sprintf("source_end/%d", sig.ReasonCode)
		}
		ord := r.Actual.makeOrder(&p.Base, o, "source_close", why, sig.Side, 0, Support157{})
		ord.SourceID = sig.ID
		total := 0
		for _, target := range sig.Targets {
			old := p.Base.SourceHolds[target.ID]
			n := target.Quantity * 10
			if old <= 0 || n > old {
				return fmt.Errorf("元ID返済過大 %s", target.ID)
			}
			total += n
			for _, id := range r.Actual.Active {
				l := r.Actual.Lots[id]
				if l.Parent != key || l.SourceID+"-玉" != target.ID {
					continue
				}
				q := l.Remaining * n / old
				if n == old {
					q = l.Remaining
				}
				q = min(q, l.Remaining-r.Actual.reservedClose(id))
				if q <= 0 {
					continue
				}
				ord.Targets = append(ord.Targets, Target157{id, q})
				ord.Quantity += q
			}
			p.Base.SourceHolds[target.ID] = old - n
		}
		if total != closed {
			return fmt.Errorf("元Target量不一致")
		}
		if ord.Quantity > 0 {
			r.Actual.Pending = append(r.Actual.Pending, ord)
		}
		r.recordNight164R2(p, o, "元返済", why, sig.ID, "", closed, ord.Quantity, short)
		if p.Deferred && p.Base.SourceHolds[p.DeferredSource+"-玉"] == 0 {
			p.Deferred = false
			p.Cancelled = true
			r.recordNight164R2(p, o, "初回取消", "元ID終了", p.DeferredSource, "", p.InitialDesired, 0, short)
		}
	}
	// ----------------------------------------
	// Source追加は初回と別種別です。早期返済した旧玉を勝手に買い戻しません。
	for _, sig := range signals {
		if !strings.HasPrefix(sig.Owner, prefix) || sig.Action != "new" {
			continue
		}
		key := fmt.Sprintf("%s/%d", sig.Owner, sig.Campaign)
		p := r.Parents[key]
		if p == nil {
			p = &NightParent164R2{Base: AllocationParent157{Key: key, Owner: sig.Owner, Campaign: sig.Campaign, Side: sig.Side, Started: o.Time, SourceHolds: map[string]int{}}}
			r.Parents[key] = p
		}
		if p.Base.Side != sig.Side {
			return fmt.Errorf("同親の方向変更 %s", key)
		}
		initial := p.Base.OldInitial == 0
		q := sig.Quantity * 10
		if _, exists := p.Base.SourceHolds[sig.ID+"-玉"]; exists {
			return fmt.Errorf("元新規ID重複")
		}
		p.Base.SourceQty += q
		p.Base.SourcePeak = max(p.Base.SourcePeak, p.Base.SourceQty)
		p.Base.SourceHolds[sig.ID+"-玉"] = q
		kind := "source_add"
		if initial {
			kind = "initial"
			p.Base.OldInitial = q
			p.Base.InitialQty = q
			p.InitialDesired = q
			r.Counts["元初回親数"]++
		}
		if initial && r.Config.DelayInitial && decelDay164(short, sig.Side) && o.Time < r.End {
			p.Deferred = true
			p.DeferredAt = o.Time
			p.DeferredIndex = o.Index
			p.DeferredSource = sig.ID
			r.recordNight164R2(p, o, "初回延期", "既知短期失速", sig.ID, "", q, 0, short)
			continue
		}
		if p.Deferred || p.Cancelled {
			r.recordNight164R2(p, o, "追加不採用", "初回待機又は取消済み", sig.ID, "", q, 0, short)
			continue
		}
		if o.Time >= r.End {
			r.recordNight164R2(p, o, "新規不採用", "時間枠終了", sig.ID, "", q, 0, short)
			continue
		}
		if initial && r.Config.DelayInitial && (!short.Five.Known || !short.Fifteen.Known) {
			r.Counts["初回短期未知で元通知維持"]++
		}
		r.openNight164R2(p, o, sig.ID, kind, q, short)
	}
	return nil
}

// manageNight164R2 は元返済を優先し、実玉の利益床・追加停止・待機解除を判断します。
//
// 引数: o(Observation)、short(Short164)。返り値: なし。すべて次正常原行の予約です。
func (r *NightResult164R2) manageNight164R2(o strategy.Observation, short Short164) {
	if !normal(o) {
		return
	}
	keys := []string{}
	for key := range r.Parents {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		p := r.Parents[key]
		if o.Time >= r.End {
			if p.Deferred {
				p.Deferred = false
				p.Cancelled = true
				r.recordNight164R2(p, o, "初回取消", "時間枠終了", p.DeferredSource, "", p.InitialDesired, 0, short)
			}
			r.Actual.closeQuantity(&p.Base, o, "", "時間枠終了", 1000, Support157{})
			continue
		}
		if r.Actual.hasPending(key) {
			continue
		}
		for _, id := range r.Actual.Active {
			l := r.Actual.Lots[id]
			if l.Parent != key {
				continue
			}
			ls := r.stateLotNight164R2(id)
			mark := o.Bid
			if l.Side < 0 {
				mark = o.Ask
			}
			gain := float64(l.Side) * (mark - l.Entry)
			tight := r.Config.TightAll || (r.Config.TightSmall && p.Base.OldInitial <= 20 && (l.Kind == "initial" || l.Kind == "delayed_initial"))
			if (tight || (r.Config.ResidualFloor && ls.ResidualEligible)) && gain >= 10 && !ls.Activated {
				ls.Activated = true
				ls.ActivatedTime = o.Time
				ls.ActivatedIndex = o.Index
				r.recordNight164R2(p, o, "保護起動", "実玉10円順行", l.SourceID, id, 0, 0, short)
			}
			reason := ""
			if ls.Activated {
				floor := 0.
				reason = "protect_residual_floor"
				if tight {
					floor = math.Max(0, l.Best-20)
					reason = "protect_10trail20"
				}
				ls.Floor = math.Max(ls.Floor, floor)
				if gain > ls.Floor {
					reason = ""
				}
			}
			if reason == "" && r.Config.StopAdd && l.Kind == "source_add" && gain <= -50 {
				reason = "source_add_stop50"
			}
			if reason != "" {
				q := r.Actual.closeLot(&p.Base, o, id, reason, l.Remaining, Support157{})
				r.recordNight164R2(p, o, "独自返済", reason, l.SourceID, id, l.Remaining, q, short)
				tr := &r.Trace[len(r.Trace)-1]
				tr.Gain = gain
				tr.Floor = ls.Floor
			}
		}
		if !p.Deferred {
			continue
		}
		if o.Time-p.DeferredAt >= 30 || p.Base.SourceHolds[p.DeferredSource+"-玉"] <= 0 {
			p.Deferred = false
			p.Cancelled = true
			r.recordNight164R2(p, o, "初回取消", "期限又は元ID終了", p.DeferredSource, "", p.InitialDesired, 0, short)
			continue
		}
		if o.Index <= p.DeferredIndex || r.Actual.hasPending(key) || !recoverDay164(short, p.Base.Side) {
			continue
		}
		q := min(p.InitialDesired, p.Base.SourceHolds[p.DeferredSource+"-玉"])
		accepted := r.openNight164R2(p, o, p.DeferredSource, "delayed_initial", q, short)
		p.Deferred = false
		if accepted == 0 {
			p.Cancelled = true
		}
	}
}

// stepNight164R2 は実約定・元通知・局所判断を原行順で進めます。
//
// 引数: o(Observation)、signals([]Signal)、short(Short164)。返り値: error。
func (r *NightResult164R2) stepNight164R2(o strategy.Observation, signals []strategy.Signal, short Short164) error {
	r.ObservationEnd = o.Time
	if e := r.fillNight164R2(o, short); e != nil {
		return e
	}
	if e := r.sourceNight164R2(o, signals, short); e != nil {
		return e
	}
	r.manageNight164R2(o, short)
	long, shortQ := r.Actual.position("", "")
	for _, ord := range r.Actual.Pending {
		if len(ord.Targets) == 0 {
			if ord.Side > 0 {
				long += ord.Quantity
			} else {
				shortQ += ord.Quantity
			}
		}
	}
	if long > 100 || shortQ > 100 {
		return fmt.Errorf("新規予約込み片側100超過")
	}
	return nil
}
