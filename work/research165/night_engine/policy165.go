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

type Config165 struct {
	ID                                                                                       string  `json:"id"`
	Scope                                                                                    string  `json:"scope"`
	RuleHash                                                                                 string  `json:"rule_hash"`
	Description                                                                              string  `json:"description"`
	Scale                                                                                    float64 `json:"scale"`
	EntryVeto, Delay, AddGate, ResidualExit, Reduce, Clock, Independent, Supply, ProfitTrail bool
	Parameters                                                                               map[string]any `json:"parameters"`
}
type Parent165 struct {
	Reduced         bool
	FirstFillIndex  int64
	FirstFilled     bool
	StateID, WaveID int
}
type Trace165 struct {
	Parent, Action, Reason, SourceID, ActualID string
	Time, Gain                                 float64
	Index                                      int64
	Desired, Accepted                          int
	State                                      StateView165
}
type Result165 struct {
	Config          Config165                    `json:"config"`
	Actual          *Ledger157                   `json:"actual"`
	VirtualControl  *Ledger157                   `json:"virtual_control,omitempty"`
	Parents         map[string]*NightParent164R2 `json:"parents"`
	States          map[string]*Parent165        `json:"states"`
	LotStates       map[string]*NightLot164R2    `json:"lot_states"`
	Trace           []Trace165                   `json:"trigger_trace"`
	NativeTrace     []NightTrace164R2            `json:"native_trace"`
	Counts          map[string]int               `json:"counts"`
	Base            *NightResult164R2            `json:"-"`
	UsedWaves       map[int]bool                 `json:"used_waves"`
	NextIndependent int
}

// configs165 は旧IDを変更せず14個の米国後定義を返します。
//
// 引数: なし。返り値: []Config165。全閾値を定義ハッシュへ含めます。
func configs165() []Config165 {
	out := []Config165{}
	for i := 1; i <= 14; i++ {
		c := Config165{ID: fmt.Sprintf("NK225_U165_%02d", i), Scope: "PostUS", Scale: 1}
		c.EntryVeto = i == 2 || i == 3 || i == 7 || i == 8 || i == 9
		c.Delay = i == 3
		c.AddGate = i == 4 || i == 7 || i == 8 || i == 9
		c.ResidualExit = i == 5 || i == 8 || i == 9
		c.Reduce = i == 6 || i == 8 || i == 9
		c.Clock = i == 9
		c.Independent = i >= 10
		c.Supply = i == 11 || i == 12 || i == 14
		c.ProfitTrail = i >= 13
		if i == 1 || i == 12 {
			c.Scale = .5
		}
		c.Description = map[int]string{1: "元全通知の半量", 2: "元初回の数量回復後反転拒否", 3: "02の拒否候補を30秒待機", 4: "価格帯維持中だけ元追撃", 5: "黒字部分返済後の残玉を反対価格帯維持で返済", 6: "新しい反対価格帯維持で一回半減し追加も半量", 7: "02と04", 8: "07と05と06", 9: "08の時計15秒窓版", 10: "価格だけの新価格維持と押戻り入口", 11: "10と反対回復価格通過", 12: "11の同じ仮想枠指示を厳密半量", 13: "10の100円利確を30円起動40円追尾へ", 14: "11の100円利確を30円起動40円追尾へ"}[i]
		c.Parameters = map[string]any{"主窓価格更新数": 8, "参考窓価格更新数": 32, "時計対照窓秒": 15, "時計過去端遅れ上限秒": 15, "状態最大価格時計秒": 60, "状態最大価格更新数": 32, "価格帯両側移動円": 20, "方向更新幅比": .625, "数量回復窓平均": .07, "候補後確認価格更新数": 2, "許容一時逆行円": 10, "対向回復価格通過円": 10, "初回待機秒": 30, "独立入口元量micro": 20, "独立仮想片側上限micro": 100, "独立仮想全方向親上限": 5, "独立初期停止円": 50, "独立固定利確円": 100, "独立追尾起動円": 30, "独立追尾建値比床円": 10, "独立追尾幅円": 40, "片側実上限micro": 100, "点価円": 10, "手数料円": 0, "時間割": "US+15分から場末10分前。元Sourceは従来のUS解禁を維持。", "価格時計": "CurrentPriceTime代理、同時計の後続原行も当時までだけ。受信秒と称さない。", "元部分返済": "SourceID現在実残量×今回Source返済量/返済前Source残量、micro切捨て。全返済は残全量。", "半減": "親の自由実残量合計の1/2をmicro切捨てし、ActualID昇順へ順次配賦して返済。以後の同親Source追加も1/2。先行返済予約がある親では独自減枚をしない。", "残玉資格": "候補ActualのSource部分返済が実益、Source残存、当時残玉限定。その後に正益を観測し、資格後に成立した反対価格帯維持で返済。", "初回拒否": "未知は元入口維持。既知の反対維持と先行同価格支持回復だけ拒否。拒否取消親は同親追加でも復活不可。", "独立入口": "新押戻りIDごと一回。元Sourceに非依存。先に確認した新価格帯から逆価格更新が生じ、二価格更新後に帯を回復。数量条件は11/12/14だけ。", "半量12": "20micro/100micro仮想台帳を11と同じに進めて、全実指示を1/2写像。価格・時計・同時親数・新規集合は同じ。", "優先": "次正常約定、元返済、元新規の源残数更新、既存玉の保護/半減、元新規受付、待機解除/独立新規。返済未約定の枠は空けない。"}
		c.Parameters["11数量壁の新規時確認"] = "候補開始時の実同価格増分の価格を固定。確認時に通過済みかつ新規時にも返済側が10円以上越える。数量観測から60秒/32価格event以内。"
		c.Parameters["状態と新波ID"] = "HoldIDは基礎価格帯、RetestIDは新しい逆価格更新後の2更新回復ごと。新規は同じRetestIDを二度使わない。"
		for _, native := range []string{"P05", "D07"} {
			hash, e := hashFile164("night_rules/NK225_" + native + ".toml")
			if e != nil {
				panic(e)
			}
			c.Parameters["元"+native+"規則SHA256"] = hash
		}
		b, e := json.Marshal(c)
		if e != nil {
			panic(e)
		}
		h := sha256.Sum256(b)
		c.RuleHash = hex.EncodeToString(h[:])
		out = append(out, c)
	}
	return out
}

// newResult165 は候補の実所有と不変のSource写像を分離します。
//
// 引数: c(Config165)、scene(Scene)。返り値: *Result165。
func newResult165(c Config165, scene Scene) *Result165 {
	b := newNight164R2(NightConfig164R2{ID: c.ID, Scope: "PostUS", Native: "D07", ResidualFloor: c.ResidualExit}, scene)
	return &Result165{Config: c, Actual: b.Actual, Parents: b.Parents, States: map[string]*Parent165{}, LotStates: b.Lots, Counts: map[string]int{}, Base: b, UsedWaves: map[int]bool{}}
}

// trace165 は当時の状態を値として保存します。
//
// 引数: p/act/why/source/lot(string)、o(Observation)、want/got(int)、v(StateView165)。返り値: なし。
func (r *Result165) trace165(p, act, why, source, lot string, o strategy.Observation, want, got int, v StateView165) {
	r.Trace = append(r.Trace, Trace165{Parent: p, Action: act, Reason: why, SourceID: source, ActualID: lot, Time: o.Time, Index: o.Index, Desired: want, Accepted: got, State: v})
	r.Counts[act+":"+why]++
}

// holds165 は方向側と反対側の確認済み状態を返します。
//
// 引数: v(StateView165)、side(int)。返り値: 同方向/反対方向のHold165。
func holds165(v StateView165, side int) (Hold165, Hold165) {
	if side > 0 {
		return v.Buy, v.Sell
	}
	return v.Sell, v.Buy
}

// parentState165 は親の一回限りの減枚権を取得します。
//
// 引数: key(string)。返り値: *Parent165。
func (r *Result165) parentState165(key string) *Parent165 {
	if r.States[key] == nil {
		r.States[key] = &Parent165{}
	}
	return r.States[key]
}

// hasClose165 は元返済と独自返済の未約定を検査します。
//
// 引数: key(string)。返り値: bool。新規予約だけでは既存玉保護を止めません。
func (r *Result165) hasClose165(key string) bool {
	for _, o := range r.Actual.Pending {
		if o.Parent == key && len(o.Targets) > 0 {
			return true
		}
	}
	return false
}

// source165 は源残数の更新と候補の新規採否を分けます。
//
// 引数: o(Observation)、signals([]Signal)、v(StateView165)。返り値: 源新規通知([]Signal)、error。
func (r *Result165) source165(o strategy.Observation, signals []strategy.Signal, v StateView165) ([]strategy.Signal, error) {
	closes, news := []strategy.Signal{}, []strategy.Signal{}
	for _, s := range signals {
		if !strings.HasPrefix(s.Owner, "後半/") {
			continue
		}
		if s.Action == "close" {
			closes = append(closes, s)
		} else if s.Action == "new" {
			news = append(news, s)
		}
	}
	if e := r.Base.sourceNight164R2(o, closes, Short164{}); e != nil {
		return nil, e
	}
	for _, s := range news {
		key := fmt.Sprintf("%s/%d", s.Owner, s.Campaign)
		p := r.Parents[key]
		if p == nil {
			p = &NightParent164R2{Base: AllocationParent157{Key: key, Owner: s.Owner, Campaign: s.Campaign, Side: s.Side, Started: o.Time, SourceHolds: map[string]int{}}}
			r.Parents[key] = p
		}
		if p.Base.Side != s.Side {
			return nil, fmt.Errorf("同親方向が変化:%s", key)
		}
		if _, ok := p.Base.SourceHolds[s.ID+"-玉"]; ok {
			return nil, fmt.Errorf("元ID重複")
		}
		q := s.Quantity * 10
		initial := p.Base.OldInitial == 0
		p.Base.SourceHolds[s.ID+"-玉"] = q
		p.Base.SourceQty += q
		p.Base.SourcePeak = max(p.Base.SourcePeak, p.Base.SourceQty)
		if initial {
			p.Base.OldInitial = q
			p.Base.InitialQty = q
			p.InitialDesired = q
			p.DeferredSource = s.ID
			r.Counts["元初回親数"]++
			_, opposite := holds165(v, s.Side)
			if r.Config.EntryVeto && v.Known && opposite.Active && opposite.QuantitySupport {
				if r.Config.Delay {
					p.Deferred = true
					p.DeferredAt = o.Time
					p.DeferredIndex = o.Index
					r.trace165(key, "初回待機", "反対価格帯と数量回復", s.ID, "", o, q, 0, v)
				} else {
					p.Cancelled = true
					r.trace165(key, "初回拒否", "反対価格帯と数量回復", s.ID, "", o, q, 0, v)
				}
			} else if r.Config.EntryVeto && !v.Known {
				r.Counts["初回未知で元通知維持"]++
			}
		}
	}
	return news, nil
}

// acceptNews165 は源の新規を当時の政策量で予約します。
//
// 引数: o(Observation)、news([]Signal)、v(StateView165)。返り値: なし。
func (r *Result165) acceptNews165(o strategy.Observation, news []strategy.Signal, v StateView165) {
	for _, s := range news {
		key := fmt.Sprintf("%s/%d", s.Owner, s.Campaign)
		p := r.Parents[key]
		initial := s.ID == p.DeferredSource
		kind := "source_add"
		if initial {
			kind = "initial"
		}
		q := s.Quantity * 10
		if p.Deferred || p.Cancelled || o.Time >= r.Base.End {
			r.trace165(key, "新規不採用", "初回待機取消又は時間枠終了", s.ID, "", o, q, 0, v)
			continue
		}
		hold, _ := holds165(v, s.Side)
		if !initial && r.Config.AddGate && (!v.Known || !hold.Active) {
			reason := "同方向価格帯維持なし"
			if !v.Known {
				reason = "価格帯未知"
			}
			r.trace165(key, "追加拒否", reason, s.ID, "", o, q, 0, v)
			continue
		}
		if r.Config.Scale == .5 {
			q /= 2
		}
		if r.parentState165(key).Reduced {
			q /= 2
		}
		got := r.Base.openNight164R2(p, o, s.ID, kind, q, Short164{})
		r.trace165(key, "新規受付", kind, s.ID, "", o, q, got, v)
	}
}

// manage165 は元退出を優先し、価格帯の反転後だけ局所介入します。
//
// 引数: o(Observation)、v(StateView165)。返り値: なし。
func (r *Result165) manage165(o strategy.Observation, v StateView165) {
	if !normal(o) {
		return
	}
	keys := []string{}
	for k := range r.Parents {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, key := range keys {
		p := r.Parents[key]
		ps := r.parentState165(key)
		_, opposite := holds165(v, p.Base.Side)
		if o.Time >= r.Base.End {
			p.Deferred = false
			p.Cancelled = true
			r.Actual.closeQuantity(&p.Base, o, "", "時間枠終了", 10000, Support157{})
			continue
		}
		if r.hasClose165(key) {
			continue
		}
		for _, id := range r.Actual.Active {
			l := r.Actual.Lots[id]
			if l.Parent != key {
				continue
			}
			ls := r.Base.stateLotNight164R2(id)
			mark := o.Bid
			if l.Side < 0 {
				mark = o.Ask
			}
			gain := float64(l.Side) * (mark - l.Entry)
			if ls.ResidualEligible && gain > 0 && !ls.Activated {
				ls.Activated = true
				ls.ActivatedTime = o.Time
				ls.ActivatedIndex = o.Index
			}
			if r.Config.ResidualExit && ls.ResidualEligible && ls.Activated && opposite.Active && opposite.Index > ls.ResidualIndex {
				q := r.Actual.closeLot(&p.Base, o, id, "qualified_residual_repricing", l.Remaining, Support157{})
				r.trace165(key, "独自返済", "資格後正益と反対価格帯", l.SourceID, id, o, l.Remaining, q, v)
				r.Trace[len(r.Trace)-1].Gain = gain
			}
			if r.Config.Independent {
				why := ""
				if gain <= -50 {
					why = "independent_stop50"
				} else if !r.Config.ProfitTrail && gain >= 100 {
					why = "independent_take100"
				} else if r.Config.ProfitTrail && l.Best >= 30 && gain <= math.Max(10, l.Best-40) {
					why = "independent_trail30_40_floor10"
				} else if opposite.Active && opposite.Index > l.EntryIndex {
					why = "independent_opposite_band"
				}
				if why != "" {
					q := r.Actual.closeLot(&p.Base, o, id, why, l.Remaining, Support157{})
					r.trace165(key, "独自返済", why, l.SourceID, id, o, l.Remaining, q, v)
					r.Trace[len(r.Trace)-1].Gain = gain
				}
			}
		}
		if r.Config.Reduce && !ps.Reduced && ps.FirstFilled && opposite.Active && opposite.Index > ps.FirstFillIndex && !r.hasClose165(key) {
			ids := []string{}
			freeTotal := 0
			for _, id := range r.Actual.Active {
				l := r.Actual.Lots[id]
				if l.Parent != key {
					continue
				}
				ids = append(ids, id)
				freeTotal += l.Remaining - r.Actual.reservedClose(id)
			}
			sort.Strings(ids)
			wanted := freeTotal / 2
			total := 0
			for _, id := range ids {
				l := r.Actual.Lots[id]
				q := min(wanted-total, l.Remaining-r.Actual.reservedClose(id))
				if q > 0 {
					total += r.Actual.closeLot(&p.Base, o, id, "confirmed_opposite_half", q, Support157{})
				}
			}
			if total > 0 {
				ps.Reduced = true
				r.trace165(key, "半減", "反対価格帯維持", "", "", o, total, total, v)
			}
		}
	}
}

// release165 は同親の生存源量以内で一度だけ待機を解除します。
//
// 引数: o(Observation)、v(StateView165)。返り値: なし。
func (r *Result165) release165(o strategy.Observation, v StateView165) {
	keys := []string{}
	for key := range r.Parents {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		p := r.Parents[key]
		if !p.Deferred {
			continue
		}
		q := min(p.InitialDesired, p.Base.SourceHolds[p.DeferredSource+"-玉"])
		if o.Time-p.DeferredAt > 30 || q <= 0 || o.Time >= r.Base.End {
			p.Deferred = false
			p.Cancelled = true
			r.trace165(key, "待機取消", "期限又はSource終了", p.DeferredSource, "", o, q, 0, v)
			continue
		}
		hold, _ := holds165(v, p.Base.Side)
		if o.Index <= p.DeferredIndex || !v.Known || !hold.Active || hold.Index <= p.DeferredIndex || r.Actual.hasPending(key) {
			continue
		}
		got := r.Base.openNight164R2(p, o, p.DeferredSource, "delayed_initial", q, Short164{})
		p.Deferred = false
		if got == 0 {
			p.Cancelled = true
		}
		r.trace165(key, "待機解除", "新しい同方向価格帯", p.DeferredSource, "", o, q, got, v)
	}
}

// independent165 は現在までに完成した新しい押戻りIDだけを採用します。
//
// 引数: o(Observation)、v(StateView165)。返り値: なし。半量12も20micro仮想枠で運転します。
func (r *Result165) independent165(o strategy.Observation, v StateView165) {
	if !normal(o) || o.Time < r.Base.Start || o.Time >= r.Base.End || v.RetestID == 0 || r.UsedWaves[v.RetestID] {
		return
	}
	r.UsedWaves[v.RetestID] = true
	hold, _ := holds165(v, v.RetestSide)
	mark := o.Bid
	if v.RetestSide < 0 {
		mark = o.Ask
	}
	currentPassed := hold.SupplyPassed && aliveBarrier165(hold.Barrier, o.Time, v.PriceEvent) && float64(v.RetestSide)*(mark-hold.Barrier.Price) >= 10
	if !hold.Active || (r.Config.Supply && !currentPassed) {
		r.Counts["独立入口の数量条件不成立"]++
		return
	}
	activeParents := map[string]bool{}
	for _, id := range r.Actual.Active {
		activeParents[r.Actual.Lots[id].Parent] = true
	}
	for _, ord := range r.Actual.Pending {
		if len(ord.Targets) == 0 {
			activeParents[ord.Parent] = true
		}
	}
	if len(activeParents) >= 5 {
		r.Counts["独立入口の仮想親数上限"]++
		return
	}
	if r.Actual.capacity(v.RetestSide) < 20 {
		r.Counts["独立入口の仮想枠不足"]++
		return
	}
	r.NextIndependent++
	key := fmt.Sprintf("independent/%d", r.NextIndependent)
	p := &NightParent164R2{Base: AllocationParent157{Key: key, Owner: "independent", Campaign: r.NextIndependent, Side: v.RetestSide, Started: o.Time, InitialQty: 20, OldInitial: 20, SourceHolds: map[string]int{}}}
	r.Parents[key] = p
	ps := r.parentState165(key)
	ps.StateID = hold.ID
	ps.WaveID = v.RetestID
	q := r.Actual.open(&p.Base, o, "initial", "independent_retest", p.Base.Side, 20, Support157{})
	r.trace165(key, "独立新規", "新押戻りの価格帯回復", "", "", o, 20, q, v)
}

// step165Policy は実約定と元通知を進め、最後に新規を予約します。
//
// 引数: o(Observation)、signals([]Signal)、v(StateView165)。返り値: error。
func (r *Result165) step165Policy(o strategy.Observation, signals []strategy.Signal, v StateView165) error {
	before := len(r.Actual.Events)
	if e := r.Base.fillNight164R2(o, Short164{}); e != nil {
		return e
	}
	for _, f := range r.Actual.Events[before:] {
		if len(f.Order.Targets) == 0 {
			ps := r.parentState165(f.Order.Parent)
			if !ps.FirstFilled {
				ps.FirstFilled = true
				ps.FirstFillIndex = f.FillIndex
			}
		}
	}
	news := []strategy.Signal{}
	var e error
	if !r.Config.Independent {
		news, e = r.source165(o, signals, v)
		if e != nil {
			return e
		}
	}
	r.manage165(o, v)
	if r.Config.Independent {
		r.independent165(o, v)
	} else {
		r.acceptNews165(o, news, v)
		r.release165(o, v)
	}
	long, short := r.Actual.position("", "")
	for _, q := range r.Actual.Pending {
		if len(q.Targets) == 0 {
			if q.Side > 0 {
				long += q.Quantity
			} else {
				short += q.Quantity
			}
		}
	}
	if long > 100 || short > 100 {
		return fmt.Errorf("片側予約上限違反 %s", r.Config.ID)
	}
	r.NativeTrace = r.Base.Trace
	return nil
}
