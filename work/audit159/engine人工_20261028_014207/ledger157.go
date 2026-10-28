package main

import (
	"errors"
	"fmt"
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
	"sort"
)

type Target157 struct {
	ID       string
	Quantity int
}
type Order157 struct {
	ID, Parent, Owner, Kind, Reason, SourceID string
	Campaign, Side, Quantity                  int
	DecisionIndex                             int64
	DecisionTime, DecisionBid, DecisionAsk    float64
	Targets                                   []Target157
	Support                                   Support157
	CanonicalKinds, CanonicalOrderIDs         []string
}
type Piece157 struct {
	ID, Kind                        string
	Quantity                        int
	Entry, Exit, Gross, Best, Worst float64
}
type Event157 struct {
	Order                                           Order157
	FillIndex                                       int64
	FillTime, Price, Bid, Ask, Gross                float64
	Pieces                                          []Piece157
	HoldID                                          string
	ComparedQuantity                                int
	PreviousAverage, NewAverage, AverageImprovement float64
}
type Lot157 struct {
	ID, Parent, Owner, Kind, SourceID              string
	Campaign, Side, Quantity, Remaining            int
	Entry, At, Gross, Best, Worst, BestAt, WorstAt float64
	EntryIndex                                     int64
	Activated                                      bool
	Floor                                          float64
}
type ParentValue157 struct {
	Realized, Unrealized, Equity, Peak, Minimum float64
	Quantity, Long, Short                       int
}
type Mark157 struct {
	Time, Bid, Ask, Realized, Unrealized, Equity, MidEquity float64
	Index                                                   int64
	Long, Short                                             int
	Lots                                                    map[string]int
}
type Risk157 struct {
	Peak, Minimum, MaxDD                                                      float64
	MinimumAt, PeakAt, DDFrom, DDTo                                           Mark157
	MinimumRealized, MinimumUnrealized                                        float64
	MinimumRealizedAt, MinimumUnrealizedAt                                    Mark157
	MaxLong, MaxShort, MaxGross                                               int
	MaxNetAbs                                                                 int
	HeldSeconds, GrossSeconds, NetAbsSeconds, NetSignedSeconds, HedgedSeconds float64
}
type Ledger157 struct {
	Prefix   string
	Sequence int
	Lots     map[string]*Lot157
	Active   []string
	Pending  []Order157
	Events   []Event157
	Realized float64
	Parents  map[string]*ParentValue157
	Risk     Risk157
	Last     Mark157
	LastTime float64
}

// newLedger157 は実又はCanonicalの独立所有台帳を作ります。
//
// 引数: prefix(string)、at(float64)。返り値: *Ledger157。
func newLedger157(prefix string, at float64) *Ledger157 {
	m := Mark157{Time: at, Index: -1}
	return &Ledger157{Prefix: prefix, Lots: map[string]*Lot157{}, Parents: map[string]*ParentValue157{}, LastTime: at, Last: m, Risk: Risk157{PeakAt: m, MinimumAt: m, DDFrom: m, DDTo: m, MinimumRealizedAt: m, MinimumUnrealizedAt: m}}
}

// position は親と役割の現在の実約定残数を返します。
//
// 引数: parent/kind(string)。返り値: long,short(int)。kind空は全役割です。
func (b *Ledger157) position(parent, kind string) (int, int) {
	l, s := 0, 0
	for _, id := range b.Active {
		x := b.Lots[id]
		if (parent == "" || x.Parent == parent) && (kind == "" || (kind == "cover") == (x.Kind == "cover")) {
			if x.Side > 0 {
				l += x.Remaining
			} else {
				s += x.Remaining
			}
		}
	}
	return l, s
}

// hasPending は同じ親に未確定注文があるか調べます。
//
// 引数: parent(string)。返り値: bool。
func (b *Ledger157) hasPending(parent string) bool {
	for _, o := range b.Pending {
		if o.Parent == parent {
			return true
		}
	}
	return false
}

// capacity は返済予定を空き枠と見なさず、新規予約を含めて余枠を返します。
//
// 引数: side(int)。返り値: intは片側100との差です。
func (b *Ledger157) capacity(side int) int {
	l, s := b.position("", "")
	n := l
	if side < 0 {
		n = s
	}
	for _, o := range b.Pending {
		if len(o.Targets) == 0 && o.Side == side {
			n += o.Quantity
		}
	}
	return max(0, 100-n)
}

// makeOrder は観測時点の注文情報を固定します。
//
// 引数: parent(*AllocationParent157)、o(Observation)、kind/reason(string)、side/q(int)、support(Support157)。返り値: Order157。
func (b *Ledger157) makeOrder(parent *AllocationParent157, o strategy.Observation, kind, reason string, side, q int, support Support157) Order157 {
	b.Sequence++
	return Order157{ID: fmt.Sprintf("%s-%06d", b.Prefix, b.Sequence), Parent: parent.Key, Owner: parent.Owner, Campaign: parent.Campaign, Kind: kind, Reason: reason, Side: side, Quantity: q, DecisionIndex: o.Index, DecisionTime: o.Time, DecisionBid: o.Bid, DecisionAsk: o.Ask, Support: support}
}

// open は実玉を増やさず次正常原行の新規だけを予約します。
//
// 引数: p(*AllocationParent157)、o(Observation)、kind/reason(string)、side/q(int)、support(Support157)。返り値: intは予約数量です。
func (b *Ledger157) open(p *AllocationParent157, o strategy.Observation, kind, reason string, side, q int, support Support157) int {
	q = min(q, b.capacity(side))
	if q <= 0 {
		return 0
	}
	b.Pending = append(b.Pending, b.makeOrder(p, o, kind, reason, side, q, support))
	return q
}

// reservedClose は実玉IDに予約済みの返済数を返します。
//
// 引数: id(string)。返り値: int。
func (b *Ledger157) reservedClose(id string) int {
	n := 0
	for _, o := range b.Pending {
		for _, t := range o.Targets {
			if t.ID == id {
				n += t.Quantity
			}
		}
	}
	return n
}

// closeLot は未返済残数だけを所有ID指定で予約します。
//
// 引数: p(*AllocationParent157)、o(Observation)、id/reason(string)、q(int)、support(Support157)。返り値: int。
func (b *Ledger157) closeLot(p *AllocationParent157, o strategy.Observation, id, reason string, q int, support Support157) int {
	l := b.Lots[id]
	if l == nil {
		return 0
	}
	q = min(q, l.Remaining-b.reservedClose(id))
	if q <= 0 {
		return 0
	}
	e := b.makeOrder(p, o, l.Kind, reason, -l.Side, q, support)
	e.Targets = []Target157{{id, q}}
	b.Pending = append(b.Pending, e)
	return q
}

// closeQuantity は同じ親の指定役割を最古玉から部分返済します。
//
// 引数: p(*AllocationParent157)、o(Observation)、kind/reason(string)、q(int)、support(Support157)。返り値: なし。
func (b *Ledger157) closeQuantity(p *AllocationParent157, o strategy.Observation, kind, reason string, q int, support Support157) {
	for _, id := range b.Active {
		l := b.Lots[id]
		if l.Parent != p.Key || (kind != "" && (kind == "cover") != (l.Kind == "cover")) {
			continue
		}
		q -= b.closeLot(p, o, id, reason, q, support)
		if q <= 0 {
			return
		}
	}
}

// fill は前原行までに予約した注文を現在正常BBOで全量約定します。
//
// 引数: o(Observation)。返り値: []Event157とerror。停止線価格への置換はしません。
func (b *Ledger157) fill(o strategy.Observation) ([]Event157, error) {
	if !normal(o) {
		return nil, nil
	}
	out := []Event157{}
	for _, ord := range b.Pending {
		if o.Index <= ord.DecisionIndex {
			return nil, errors.New("同じ又は前原行での約定")
		}
		price := o.Bid
		if ord.Side > 0 {
			price = o.Ask
		}
		e := Event157{Order: ord, FillIndex: o.Index, FillTime: o.Time, Price: price, Bid: o.Bid, Ask: o.Ask}
		if len(ord.Targets) == 0 {
			if ord.Kind != "cover" {
				sum := 0.
				for _, id := range b.Active {
					old := b.Lots[id]
					if old.Parent == ord.Parent && old.Side == ord.Side && old.Kind != "cover" {
						e.ComparedQuantity += old.Remaining
						sum += old.Entry * float64(old.Remaining)
					}
				}
				if e.ComparedQuantity > 0 {
					e.PreviousAverage = sum / float64(e.ComparedQuantity)
					e.NewAverage = (sum + price*float64(ord.Quantity)) / float64(e.ComparedQuantity+ord.Quantity)
					e.AverageImprovement = float64(ord.Side) * (e.PreviousAverage - e.NewAverage)
				}
			}
			id := ord.ID + "-玉"
			if b.Lots[id] != nil {
				return nil, errors.New("所有ID重複")
			}
			l := &Lot157{ID: id, Parent: ord.Parent, Owner: ord.Owner, Campaign: ord.Campaign, Kind: ord.Kind, SourceID: ord.SourceID, Side: ord.Side, Quantity: ord.Quantity, Remaining: ord.Quantity, Entry: price, At: o.Time, EntryIndex: o.Index, BestAt: o.Time, WorstAt: o.Time}
			b.Lots[id] = l
			b.Active = append(b.Active, id)
			e.HoldID = id
		} else {
			n := 0
			for _, t := range ord.Targets {
				l := b.Lots[t.ID]
				if l == nil || l.Parent != ord.Parent || l.Remaining < t.Quantity || l.Side != -ord.Side {
					return nil, errors.New("所有返済不整合")
				}
				gain := float64(l.Side) * (price - l.Entry)
				gross := gain * float64(t.Quantity) * 10
				l.Remaining -= t.Quantity
				l.Gross += gross
				e.Gross += gross
				n += t.Quantity
				e.Pieces = append(e.Pieces, Piece157{ID: l.ID, Kind: l.Kind, Quantity: t.Quantity, Entry: l.Entry, Exit: price, Gross: gross, Best: l.Best, Worst: l.Worst})
			}
			if n != ord.Quantity {
				return nil, errors.New("返済配賦数量差")
			}
		}
		pv := b.Parents[ord.Parent]
		if pv == nil {
			pv = &ParentValue157{}
			b.Parents[ord.Parent] = pv
		}
		pv.Realized += e.Gross
		b.Realized += e.Gross
		b.Events = append(b.Events, e)
		out = append(out, e)
		b.mark(o)
	}
	b.Pending = nil
	active := b.Active[:0]
	for _, id := range b.Active {
		if b.Lots[id].Remaining > 0 {
			active = append(active, id)
		}
	}
	b.Active = active
	return out, nil
}

// mark は全正常気配で極値と清算時価を更新し、持越した含みを隠しません。
//
// 引数: o(Observation)。返り値: Mark157。保有時間は異常板の時計でも積算します。
func (b *Ledger157) mark(o strategy.Observation) Mark157 {
	l, s := b.position("", "")
	dt := math.Max(0, o.Time-b.LastTime)
	if l+s > 0 {
		b.Risk.HeldSeconds += dt
	}
	b.Risk.GrossSeconds += dt * float64(l+s)
	b.Risk.NetAbsSeconds += dt * math.Abs(float64(l-s))
	b.Risk.NetSignedSeconds += dt * float64(l-s)
	if l > 0 && s > 0 {
		b.Risk.HedgedSeconds += dt
	}
	b.LastTime = o.Time
	if !normal(o) {
		return b.Last
	}
	m := Mark157{Time: o.Time, Index: o.Index, Bid: o.Bid, Ask: o.Ask, Realized: b.Realized, Long: l, Short: s}
	for _, p := range b.Parents {
		p.Unrealized = 0
		p.Quantity = 0
		p.Long = 0
		p.Short = 0
	}
	for _, id := range b.Active {
		x := b.Lots[id]
		mark := o.Bid
		if x.Side < 0 {
			mark = o.Ask
		}
		gain := float64(x.Side) * (mark - x.Entry)
		if gain > x.Best {
			x.Best = gain
			x.BestAt = o.Time
		}
		if gain < x.Worst {
			x.Worst = gain
			x.WorstAt = o.Time
		}
		u := gain * float64(x.Remaining) * 10
		m.Unrealized += u
		m.MidEquity += float64(x.Side*x.Remaining) * ((o.Bid+o.Ask)/2 - x.Entry) * 10
		p := b.Parents[x.Parent]
		if p == nil {
			p = &ParentValue157{}
			b.Parents[x.Parent] = p
		}
		p.Unrealized += u
		p.Quantity += x.Remaining
		if x.Side > 0 {
			p.Long += x.Remaining
		} else {
			p.Short += x.Remaining
		}
	}
	m.Equity = m.Realized + m.Unrealized
	m.MidEquity += m.Realized
	for _, p := range b.Parents {
		p.Equity = p.Realized + p.Unrealized
		p.Peak = math.Max(p.Peak, p.Equity)
		p.Minimum = math.Min(p.Minimum, p.Equity)
	}
	copyMark := func() Mark157 {
		r := m
		r.Lots = map[string]int{}
		for _, id := range b.Active {
			r.Lots[id] = b.Lots[id].Remaining
		}
		return r
	}
	if m.Equity > b.Risk.Peak {
		b.Risk.Peak = m.Equity
		b.Risk.PeakAt = copyMark()
	}
	if m.Equity < b.Risk.Minimum {
		b.Risk.Minimum = m.Equity
		b.Risk.MinimumAt = copyMark()
	}
	if m.Realized < b.Risk.MinimumRealized {
		b.Risk.MinimumRealized = m.Realized
		b.Risk.MinimumRealizedAt = copyMark()
	}
	if m.Unrealized < b.Risk.MinimumUnrealized {
		b.Risk.MinimumUnrealized = m.Unrealized
		b.Risk.MinimumUnrealizedAt = copyMark()
	}
	if d := b.Risk.Peak - m.Equity; d > b.Risk.MaxDD {
		b.Risk.MaxDD = d
		b.Risk.DDFrom = b.Risk.PeakAt
		b.Risk.DDTo = copyMark()
	}
	b.Risk.MaxLong = max(b.Risk.MaxLong, l)
	b.Risk.MaxShort = max(b.Risk.MaxShort, s)
	b.Risk.MaxGross = max(b.Risk.MaxGross, l+s)
	b.Risk.MaxNetAbs = max(b.Risk.MaxNetAbs, int(math.Abs(float64(l-s))))
	b.Last = m
	return m
}

// sortedParents157 は同じ時計の操作順を親キーで再現可能にします。
//
// 引数: parents(map[string]*AllocationParent157)。返り値: []string。
func sortedParents157(parents map[string]*AllocationParent157) []string {
	keys := []string{}
	for k := range parents {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

type AllocationParent157 struct {
	GuardSince159, GuardLastObservation159                                     float64
	Key, Owner, Rejected, Blocked                                              string
	Campaign, Side, OldInitial, SourceQty, SourcePeak, InitialQty, AdverseUsed int
	Factor, Started, LastFill, LastBasePrice, Extreme                          float64
	HasExtreme, AdverseReady                                                   bool
	CoverOn                                                                    bool
	CoverSince, UncoverSince, CollapseSince, LastObservation                   float64
	SourceAddRequested                                                         int
	LastSupport                                                                Support157
	SourceHolds                                                                map[string]int
	RecoveryAllowed                                                            bool
	Finished                                                                   bool
}
type Decision157 struct {
	Parent, Action, Reason string
	Index                  int64
	Time                   float64
	Quantity               int
	Support                Support157
}
type Request159 struct {
	SourceID, Parent, Reason            string
	Initial                             bool
	SourceQuantity, Requested, Accepted int
	Time                                float64
	Index                               int64
	Support                             Support157
}
type PolicyResult157 struct {
	Requests                []Request159                    `json:"requests"`
	Config                  Policy157                       `json:"config"`
	Scene                   Scene                           `json:"scene"`
	Actual                  *Ledger157                      `json:"actual"`
	Canonical               *Ledger157                      `json:"canonical"`
	Parents                 map[string]*AllocationParent157 `json:"parents"`
	Decisions               []Decision157                   `json:"decisions"`
	Counts                  map[string]int                  `json:"counts"`
	Stopped                 bool                            `json:"stopped"`
	ObservationEnd          float64                         `json:"observation_end"`
	ProjectionChecks        int                             `json:"projection_checks"`
	ProjectionMaxDifference float64                         `json:"projection_max_difference"`
}
