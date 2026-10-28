package main

import (
	"fmt"
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
	"sort"
	"strings"
)

type Policy163 struct {
	ID          string  `json:"id"`
	Description string  `json:"description"`
	Control     string  `json:"control"`
	Half        bool    `json:"half"`
	Adverse     float64 `json:"adverse"`
	Gate        bool    `json:"gate"`
	Restore     string  `json:"restore"`
}

type ShortWindow163 struct {
	Known                                                    bool
	CurrentAt, EndpointAt, Elapsed, Delay, RawPoints, Points float64
}
type Short163 struct{ Own5, Own15 ShortWindow163 }
type shortRow163 struct {
	At, Mid float64
	Valid   bool
}
type ShortBuilder163 struct{ Rows []shortRow163 }

// add はラージの当時原行だけを新しい短期価格履歴へ加えます。
//
// 引数: o(strategy.Observation)。返り値: なし。異常板は正常価格へ置換しません。
func (b *ShortBuilder163) add(o strategy.Observation) {
	b.Rows = append(b.Rows, shortRow163{At: o.Time, Mid: (o.Bid + o.Ask) / 2, Valid: normal(o)})
}

// window は遅れ1秒以内の正常過去端から円単位の時間換算幅を計算します。
//
// 引数: h(float64)は5又は15秒。返り値: ShortWindow163。現在の不正と不足は未知です。
func (b *ShortBuilder163) window(h float64) ShortWindow163 {
	w := ShortWindow163{}
	if len(b.Rows) == 0 {
		return w
	}
	r := b.Rows[len(b.Rows)-1]
	w.CurrentAt = r.At
	if !r.Valid {
		return w
	}
	bound := r.At - h
	j := sort.Search(len(b.Rows), func(i int) bool { return b.Rows[i].At > bound }) - 1
	for j >= 0 && !b.Rows[j].Valid {
		j--
	}
	if j < 0 {
		return w
	}
	p := b.Rows[j]
	w.EndpointAt = p.At
	w.Elapsed = r.At - p.At
	w.Delay = bound - p.At
	if w.Delay > 1 || w.Elapsed <= 0 {
		return w
	}
	w.RawPoints = r.Mid - p.Mid
	w.Points = w.RawPoints * h / w.Elapsed
	w.Known = !math.IsNaN(w.Points) && !math.IsInf(w.Points, 0)
	return w
}

// get は同じ原行から5秒と15秒換算の円幅を返します。
//
// 引数: なし。返り値: Short163。既存bp支持値を代入しません。
func (b *ShortBuilder163) get() Short163 { return Short163{Own5: b.window(5), Own15: b.window(15)} }

type TransferParent163 struct {
	Diagnostics                                                    map[string]int
	FirstShortUnknown                                              *Decision163
	Base                                                           *AllocationParent157
	Phase                                                          string
	SourceMini                                                     map[string]int
	InitialSource                                                  string
	AnchorMid                                                      float64
	AnchorIndex                                                    int64
	Reduced, Restored, Ended                                       bool
	ReductionOrderIndex, ReductionFillIndex, RestorationOrderIndex int64
	ReductionFillTime, ExtremeMid                                  float64
}
type Decision163 struct {
	Parent, Action, Reason                  string
	Index                                   int64
	Time, AnchorMid, CurrentMid, ExtremeMid float64
	Quantity                                int
	SourceMini                              map[string]int
	Short                                   Short163
}
type TransferResult163 struct {
	Config           Policy163                     `json:"config"`
	Actual           *Ledger157                    `json:"actual"`
	Parents          map[string]*TransferParent163 `json:"parents"`
	Decisions        []Decision163                 `json:"decisions"`
	Counts           map[string]int                `json:"counts"`
	MaxReservedLong  int                           `json:"max_reserved_long"`
	MaxReservedShort int                           `json:"max_reserved_short"`
	ObservationEnd   float64                       `json:"observation_end"`
}

// configs163 は事前固定した二基準と八つの局所変更を返します。
//
// 引数: なし。返り値: []Policy163。追加探索は行いません。
func configs163() []Policy163 {
	return []Policy163{
		{ID: "B00", Description: "元S01/P05/D07の全数量と出口", Control: "Source"},
		{ID: "C50", Description: "元の全通知数量を厳密1/2", Control: "B00", Half: true},
		{ID: "D40", Description: "初回中値から40円逆行で一度半量", Control: "B00", Adverse: 40},
		{ID: "D80", Description: "初回中値から80円逆行で一度半量", Control: "B00", Adverse: 80},
		{ID: "G40", Description: "40円逆行と短期逆進行で一度半量", Control: "D40", Adverse: 40, Gate: true},
		{ID: "G80", Description: "80円逆行と短期逆進行で一度半量", Control: "D80", Adverse: 80, Gate: true},
		{ID: "R40", Description: "G40後の不利極値から40円回復で一度復元", Control: "G40", Adverse: 40, Gate: true, Restore: "extreme"},
		{ID: "R80", Description: "G80後の不利極値から40円回復で一度復元", Control: "G80", Adverse: 80, Gate: true, Restore: "extreme"},
		{ID: "E40", Description: "G40後に初回中値を回復して一度復元", Control: "G40", Adverse: 40, Gate: true, Restore: "entry"},
		{ID: "E80", Description: "G80後に初回中値を回復して一度復元", Control: "G80", Adverse: 80, Gate: true, Restore: "entry"},
	}
}

// newTransfer163 は元Sourceと分離した実数量台帳を初期化します。
//
// 引数: config(Policy163)、scene(Scene)。返り値: *TransferResult163。
func newTransfer163(config Policy163, scene Scene) *TransferResult163 {
	return &TransferResult163{Config: config, Actual: newLedger157(config.ID, scene.Start), Parents: map[string]*TransferParent163{}, Counts: map[string]int{}}
}

// multiplier163 は現在状態のSource1mini当たり実micro数を返します。
//
// 引数: p(*TransferParent163)。返り値: intは5又は10です。
func (r *TransferResult163) multiplier163(p *TransferParent163) int {
	if r.Config.Half || (p.Reduced && !p.Restored) {
		return 5
	}
	return 10
}

// record163 は数量判断時の基準と短期入力を独立コピーで保存します。
//
// 引数: p(*TransferParent163)、o(Observation)、short(Short163)、action/reason(string)、q(int)。返り値: なし。
func (r *TransferResult163) record163(p *TransferParent163, o strategy.Observation, short Short163, action, reason string, q int) {
	holds := map[string]int{}
	for id, n := range p.SourceMini {
		holds[id] = n
	}
	r.Decisions = append(r.Decisions, Decision163{Parent: p.Base.Key, Action: action, Reason: reason, Index: o.Index, Time: o.Time, AnchorMid: p.AnchorMid, CurrentMid: (o.Bid + o.Ask) / 2, ExtremeMid: p.ExtremeMid, Quantity: q, SourceMini: holds, Short: short})
	r.Counts[action+":"+reason]++
}

// sourceIDs163 は元玉IDを固定順で返し、同時処理の非決定性を防ぎます。
//
// 引数: p(*TransferParent163)。返り値: []string。
func sourceIDs163(p *TransferParent163) []string {
	ids := []string{}
	for id := range p.SourceMini {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	return ids
}

// sourceHeld163 は同じSourceIDへ結び付く実玉と新規・返済予約を数えます。
//
// 引数: p(*TransferParent163)、source(string)。返り値: held,newPending,closePending(int)。
func (r *TransferResult163) sourceHeld163(p *TransferParent163, source string) (int, int, int) {
	held, news, closes := 0, 0, 0
	for _, id := range r.Actual.Active {
		l := r.Actual.Lots[id]
		if l.Parent == p.Base.Key && l.SourceID == source {
			held += l.Remaining
			closes += r.Actual.reservedClose(id)
		}
	}
	for _, o := range r.Actual.Pending {
		if o.Parent == p.Base.Key && o.SourceID == source && len(o.Targets) == 0 {
			news += o.Quantity
		}
	}
	return held, news, closes
}

// closeSource163 はSourceID単位の残量上限まで、古い実玉から返済対象を作ります。
//
// 引数: p(*TransferParent163)、source(string)、target(int)。返り値: []Target157。返済予約は重複させません。
func (r *TransferResult163) closeSource163(p *TransferParent163, source string, target int) []Target157 {
	held, _, pending := r.sourceHeld163(p, source)
	needed := max(0, held-pending-target)
	out := []Target157{}
	for _, id := range r.Actual.Active {
		l := r.Actual.Lots[id]
		if l.Parent != p.Base.Key || l.SourceID != source {
			continue
		}
		q := min(needed, l.Remaining-r.Actual.reservedClose(id))
		if q > 0 {
			out = append(out, Target157{ID: id, Quantity: q})
			needed -= q
		}
	}
	return out
}

// sourceSignals163 は元の通知順とSourceID所有を保ち、元返済を先に写します。
//
// 引数: o(Observation)、signals([]Signal)。返り値: error。Source自身の数量や損益は変更しません。
func (r *TransferResult163) sourceSignals163(o strategy.Observation, signals []strategy.Signal) error {
	for _, sig := range signals {
		key := fmt.Sprintf("%s/%d", sig.Owner, sig.Campaign)
		p := r.Parents[key]
		if p == nil {
			p = &TransferParent163{Base: &AllocationParent157{Key: key, Owner: sig.Owner, Campaign: sig.Campaign, Side: sig.Side, Started: o.Time}, Phase: strings.SplitN(sig.Owner, "/", 2)[0], SourceMini: map[string]int{}, Diagnostics: map[string]int{}, AnchorIndex: -1, ReductionOrderIndex: -1, ReductionFillIndex: -1, RestorationOrderIndex: -1}
			r.Parents[key] = p
		}
		ord := Order157{ID: sig.ID, Parent: key, Owner: sig.Owner, Campaign: sig.Campaign, Side: sig.Side, DecisionIndex: o.Index, DecisionTime: o.Time, DecisionBid: o.Bid, DecisionAsk: o.Ask, SourceID: sig.ID, Reason: fmt.Sprintf("source:%d", sig.ReasonCode)}
		if sig.Action == "new" {
			if p.InitialSource != "" && p.Base.Side != sig.Side {
				return fmt.Errorf("同親の元新規方向が変更:%s", key)
			}
			ord.Kind = "source_add"
			if p.InitialSource == "" {
				p.InitialSource = sig.ID
				p.Base.Side = sig.Side
				ord.Kind = "initial"
			}
			p.SourceMini[sig.ID] += sig.Quantity
			p.Ended = false
			ord.Quantity = sig.Quantity * r.multiplier163(p)
			if ord.Quantity > r.Actual.capacity(sig.Side) {
				return fmt.Errorf("元Source数量以内の新規が共有枠を超過:%s", key)
			}
			r.Actual.Pending = append(r.Actual.Pending, ord)
			r.Counts[ord.Kind]++
		} else {
			ord.Kind = "source_close"
			for _, t := range sig.Targets {
				if !strings.HasSuffix(t.ID, "-玉") {
					return fmt.Errorf("元返済ID不正:%s", t.ID)
				}
				source := t.ID[:len(t.ID)-len("-玉")]
				before, ok := p.SourceMini[source]
				if !ok || before < t.Quantity {
					return fmt.Errorf("元玉残数不足:%s", source)
				}
				p.SourceMini[source] -= t.Quantity
				ord.Targets = append(ord.Targets, r.closeSource163(p, source, p.SourceMini[source]*r.multiplier163(p))...)
			}
			remaining := 0
			for _, n := range p.SourceMini {
				remaining += n
			}
			p.Ended = remaining == 0
			for _, t := range ord.Targets {
				ord.Quantity += t.Quantity
			}
			if ord.Quantity > 0 {
				r.Actual.Pending = append(r.Actual.Pending, ord)
			}
		}
	}
	return nil
}

// afterFills163 は初回中値と減枚完了後の不利極値を実約定の当行で固定します。
//
// 引数: fills([]Event157)、o(Observation)。返り値: なし。
func (r *TransferResult163) afterFills163(fills []Event157, o strategy.Observation) {
	for _, ev := range fills {
		p := r.Parents[ev.Order.Parent]
		if p.AnchorIndex < 0 && ev.Order.Kind == "initial" && len(ev.Order.Targets) == 0 {
			p.AnchorMid = (o.Bid + o.Ask) / 2
			p.AnchorIndex = o.Index
		}
		if ev.Order.Reason == "reduce163" {
			p.ReductionFillIndex = o.Index
			p.ReductionFillTime = o.Time
			p.ExtremeMid = (o.Bid + o.Ask) / 2
		}
	}
}

// manage163 は元通知後に一回の減枚と、生きているSource玉だけの一回復元を判断します。
//
// 引数: o(Observation)、short(Short163)、allowRestore(bool)。返り値: error。
func (r *TransferResult163) manage163(o strategy.Observation, short Short163, allowRestore bool) error {
	if r.Config.Adverse == 0 || !normal(o) {
		return nil
	}
	keys := []string{}
	for key := range r.Parents {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		p := r.Parents[key]
		if p.AnchorIndex < 0 {
			continue
		}
		d := float64(p.Base.Side)
		mid := (o.Bid + o.Ask) / 2
		if p.Reduced && !p.Restored && p.ReductionFillIndex >= 0 && d*(mid-p.ExtremeMid) < 0 {
			p.ExtremeMid = mid
		}
		if p.Ended {
			continue
		}
		if r.Actual.hasPending(key) {
			p.Diagnostics["未約定優先の原行数"]++
			continue
		}
		if !p.Reduced {
			if d*(mid-p.AnchorMid) > -r.Config.Adverse {
				p.Diagnostics["逆行幅未達の原行数"]++
				continue
			}
			p.Diagnostics["逆行幅到達の原行数"]++
			if r.Config.Gate && (!short.Own5.Known || !short.Own15.Known) {
				r.Counts["減枚の短期未知"]++
				p.Diagnostics["減枚の短期未知原行数"]++
				if !short.Own5.Known {
					p.Diagnostics["減枚の5秒端未知原行数"]++
				}
				if !short.Own15.Known {
					p.Diagnostics["減枚の15秒端未知原行数"]++
				}
				if p.FirstShortUnknown == nil {
					p.FirstShortUnknown = &Decision163{Parent: key, Action: "見送り", Reason: "減枚短期未知", Index: o.Index, Time: o.Time, AnchorMid: p.AnchorMid, CurrentMid: mid, Short: short}
				}
				continue
			}
			if r.Config.Gate && (d*short.Own15.Points > -20 || d*short.Own5.Points > 0) {
				p.Diagnostics["減枚の短期既知かつ閾値不一致原行数"]++
				continue
			}
			q := 0
			for _, source := range sourceIDs163(p) {
				for _, t := range r.closeSource163(p, source, p.SourceMini[source]*5) {
					q += r.Actual.closeLot(p.Base, o, t.ID, "reduce163", t.Quantity, Support157{})
				}
			}
			if q > 0 {
				p.Reduced = true
				p.ReductionOrderIndex = o.Index
				r.record163(p, o, short, "減枚", "逆行と指定確認", q)
			}
			continue
		}
		if p.Restored || r.Config.Restore == "" || !allowRestore || p.ReductionFillIndex < 0 || o.Index <= p.ReductionFillIndex {
			continue
		}
		if !short.Own5.Known || !short.Own15.Known {
			r.Counts["復元の短期未知"]++
			p.Diagnostics["復元の短期未知原行数"]++
			continue
		}
		if d*short.Own5.Points <= 0 || d*short.Own15.Points <= 0 {
			p.Diagnostics["復元の短期既知かつ非順行原行数"]++
			continue
		}
		if r.Config.Restore == "extreme" && d*(mid-p.ExtremeMid) < 40 {
			p.Diagnostics["極値から回復幅未達の原行数"]++
			continue
		}
		if r.Config.Restore == "entry" && d*(mid-p.AnchorMid) < 0 {
			p.Diagnostics["初回中値未回復の原行数"]++
			continue
		}
		q := 0
		for _, source := range sourceIDs163(p) {
			held, news, _ := r.sourceHeld163(p, source)
			wanted := max(0, p.SourceMini[source]*10-held-news)
			if wanted == 0 {
				continue
			}
			if wanted > r.Actual.capacity(p.Base.Side) {
				return fmt.Errorf("復元上限と共有枠の不整合:%s", key)
			}
			opened := r.Actual.open(p.Base, o, "restore163", "restore163", p.Base.Side, wanted, Support157{})
			if opened > 0 {
				r.Actual.Pending[len(r.Actual.Pending)-1].SourceID = source
				q += opened
			}
		}
		if q > 0 {
			p.Restored = true
			p.RestorationOrderIndex = o.Index
			r.record163(p, o, short, "復元", r.Config.Restore, q)
		}
	}
	return nil
}

// stepTransfer163 は前原行予約を約定し、元返済・元新規・政策変更の順を守ります。
//
// 引数: o(Observation)、signals([]Signal)、short(Short163)、allowRestore(bool)。返り値: error。
func (r *TransferResult163) stepTransfer163(o strategy.Observation, signals []strategy.Signal, short Short163, allowRestore bool) error {
	r.ObservationEnd = o.Time
	r.Actual.mark(o)
	fills, e := r.Actual.fill(o)
	if e != nil {
		return e
	}
	r.afterFills163(fills, o)
	r.Actual.mark(o)
	closes, news := []strategy.Signal{}, []strategy.Signal{}
	for _, s := range signals {
		if s.Action == "close" {
			closes = append(closes, s)
		} else {
			news = append(news, s)
		}
	}
	if e = r.sourceSignals163(o, closes); e != nil {
		return e
	}
	if e = r.sourceSignals163(o, news); e != nil {
		return e
	}
	if e = r.manage163(o, short, allowRestore); e != nil {
		return e
	}
	long, shortQuantity := r.Actual.position("", "")
	for _, ord := range r.Actual.Pending {
		if len(ord.Targets) == 0 {
			if ord.Side > 0 {
				long += ord.Quantity
			} else {
				shortQuantity += ord.Quantity
			}
		}
	}
	r.MaxReservedLong = max(r.MaxReservedLong, long)
	r.MaxReservedShort = max(r.MaxReservedShort, shortQuantity)
	if long > 100 || shortQuantity > 100 {
		return fmt.Errorf("予約込み片側上限違反:%d/%d", long, shortQuantity)
	}
	return nil
}
