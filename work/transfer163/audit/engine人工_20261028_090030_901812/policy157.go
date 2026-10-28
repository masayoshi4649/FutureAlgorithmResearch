package main

import (
	"fmt"
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
	"sort"
)

// newPolicy157 は指示判断と実保有を別台帳で初期化します。
//
// 引数: config(Policy157)、scene(Scene)。返り値: *PolicyResult157。
func newPolicy157(config Policy157, scene Scene) *PolicyResult157 {
	r := &PolicyResult157{Config: config, Scene: scene, Parents: map[string]*AllocationParent157{}, Counts: map[string]int{}, Actual: newLedger157(config.ID+"-実", scene.Start), Canonical: newLedger157(config.ID+"-判断", scene.Start)}
	if config.Exact || config.Hedge {
		r.Actual = r.Canonical
	}
	return r
}

// record157 は当時の採否・数量希望を親IDと原行で保存します。
//
// 引数: p(*AllocationParent157)、o(Observation)、action/reason(string)、q(int)、support(Support157)。返り値: なし。
func (r *PolicyResult157) record157(p *AllocationParent157, o strategy.Observation, action, reason string, q int, support Support157) {
	r.Decisions = append(r.Decisions, Decision157{Parent: p.Key, Action: action, Reason: reason, Quantity: q, Index: o.Index, Time: o.Time, Support: support})
	r.Counts[action+":"+reason]++
}

// scale157 は場開始からの赤字に応じた希望量係数だけを返します。
//
// 引数: なし。返り値: float64。通常政策は場の停止・縮小をしません。
func (r *PolicyResult157) scale157() float64 {
	if !r.Config.SessionSave {
		return 1
	}
	return math.Max(0, math.Min(1, (160000+r.Canonical.Last.Equity)/80000))
}

// quantize157 は連続希望量を指定micro粒度へ切り捨てます。
//
// 引数: q(float64)、unit(int)。返り値: int。
func quantize157(q float64, unit int) int { return max(0, int(math.Floor(q/float64(unit)+1e-10))*unit) }

// desired157 は初回と政策追加で共通の数量式を適用します。
//
// 引数: support(Support157)。返り値: int。
func (r *PolicyResult157) desired157(support Support157) int {
	if r.Config.InitialFixed > 0 {
		return quantize157(float64(r.Config.InitialFixed)*r.scale157(), r.Config.Quantum)
	}
	v := support.M * support.T
	if !support.Known {
		v = 0
	}
	if r.Config.InverseSupport && support.Known {
		v = 1 - v
	}
	if r.Config.Power == 2 {
		v *= v
	}
	return quantize157((float64(r.Config.Minimum)+float64(100-r.Config.Minimum)*v)*r.scale157(), r.Config.Quantum)
}

// filter157 は未知、低支持、速度反対を混同せず初回不採用理由を返します。
//
// 引数: s(Support157)、side(int)。返り値: stringは採用時空文字です。
func filter157(s Support157, side int) string {
	if !s.Known {
		return "指標未知"
	}
	if s.M < .25 || s.T < .25 {
		return "支持閾値"
	}
	if float64(side)*s.Own15 <= 0 || float64(side)*s.Own5 < 0 {
		return "速度符号"
	}
	return ""
}

// source157 は元S01の判断通知を同じ原行で受付し、将来の実約定を参照しません。
//
// 引数: o(Observation)、signals([]strategy.Signal)、support(map[int]Support157)。返り値: なし。
func (r *PolicyResult157) source157(o strategy.Observation, signals []strategy.Signal, support map[int]Support157) {
	if r.Config.Exact {
		r.sourceExact157(o, signals)
		return
	}
	type request struct {
		p       *AllocationParent157
		sig     strategy.Signal
		q       int
		initial bool
	}
	requests := []request{}
	for _, sig := range signals {
		key := fmt.Sprintf("%s/%d", sig.Owner, sig.Campaign)
		p := r.Parents[key]
		if p == nil {
			p = &AllocationParent157{Key: key, Owner: sig.Owner, Campaign: sig.Campaign, Side: sig.Side, Started: o.Time, SourceHolds: map[string]int{}}
			r.Parents[key] = p
		}
		if sig.Action == "close" {
			before := p.SourceQty
			closed := sig.Quantity * 10
			p.SourceQty = max(0, p.SourceQty-closed)
			if r.Config.Exact {
				ord := Order157{ID: sig.ID, Parent: key, Owner: sig.Owner, Campaign: sig.Campaign, Side: sig.Side, Quantity: closed, Kind: "source_close", Reason: fmt.Sprintf("source:%d", sig.ReasonCode), SourceID: sig.ID, DecisionIndex: o.Index, DecisionTime: o.Time, DecisionBid: o.Bid, DecisionAsk: o.Ask}
				for _, t := range sig.Targets {
					ord.Targets = append(ord.Targets, Target157{t.ID, t.Quantity * 10})
				}
				r.Canonical.Pending = append(r.Canonical.Pending, ord)
			} else if p.Rejected == "" {
				if p.SourceQty == 0 {
					r.Canonical.closeQuantity(p, o, "", "source_end", 1000, p.LastSupport)
				} else {
					for _, id := range r.Canonical.Active {
						l := r.Canonical.Lots[id]
						if l.Parent != key {
							continue
						}
						ratio := float64(closed) / float64(max(1, before))
						if l.SourceID != "" {
							ratio = 0
							for _, t := range sig.Targets {
								if l.SourceID+"-玉" == t.ID {
									ratio = float64(t.Quantity*10) / float64(max(1, p.SourceHolds[t.ID]))
									break
								}
							}
						}
						q := quantize157(float64(l.Remaining)*math.Min(1, ratio), r.Config.Quantum)
						r.Canonical.closeLot(p, o, id, "source_partial", q, p.LastSupport)
					}
				}
			}
			for _, t := range sig.Targets {
				p.SourceHolds[t.ID] = max(0, p.SourceHolds[t.ID]-t.Quantity*10)
			}
			continue
		}
		initial := p.OldInitial == 0
		p.SourceQty += sig.Quantity * 10
		p.SourcePeak = max(p.SourcePeak, p.SourceQty)
		p.SourceHolds[sig.ID+"-玉"] += sig.Quantity * 10
		if initial {
			p.OldInitial = sig.Quantity * 10
			r.Counts["source_initial"]++
			p.LastSupport = support[p.Side]
			if r.Stopped {
				p.Rejected = "場停止"
			} else if r.Config.Filter {
				p.Rejected = filter157(p.LastSupport, p.Side)
			}
			if p.Rejected != "" {
				r.record157(p, o, "初回拒否", p.Rejected, 0, p.LastSupport)
				r.Requests = append(r.Requests, Request159{SourceID: sig.ID, Parent: p.Key, Reason: p.Rejected, Initial: true, SourceQuantity: sig.Quantity * 10, Time: o.Time, Index: o.Index, Support: p.LastSupport})
				continue
			}
			q := p.OldInitial
			if !r.Config.Fixed {
				q = r.desired157(p.LastSupport)
				if r.Config.SaveDeceleration && decelerated159(p.LastSupport, p.Side) {
					q = r.Config.Minimum
				}
			} else {
				q = quantize157(float64(q)*r.scale157(), r.Config.Quantum)
			}
			if q == 0 {
				p.Rejected = "丸め0"
				r.record157(p, o, "初回拒否", p.Rejected, 0, p.LastSupport)
				continue
			}
			requests = append(requests, request{p, sig, q, true})
		} else {
			if p.Rejected != "" || p.Blocked != "" || r.Stopped {
				r.Counts["source_add拒否"]++
				r.Requests = append(r.Requests, Request159{SourceID: sig.ID, Parent: p.Key, Reason: "親拒否又は停止:" + p.Rejected + p.Blocked, SourceQuantity: sig.Quantity * 10, Time: o.Time, Index: o.Index, Support: support[p.Side]})
				continue
			}
			q := quantize157(float64(sig.Quantity*10)*p.Factor*r.scale157(), r.Config.Quantum)
			if r.Config.ReselectAdd {
				cl, cs := r.Canonical.position(p.Key, "")
				prior := q
				q = min(q, max(0, r.desired157(support[p.Side])-cl-cs))
				r.record157(p, o, "追加量再評価", fmt.Sprintf("元希望%d→現在希望%d", prior, q), q, support[p.Side])
			}
			requests = append(requests, request{p, sig, q, false})
		}
	}
	// ----------------------------------------
	// 同じ原行の新規希望へ比例配分し、既存玉・予約分の枠を優先します。
	for _, side := range []int{-1, 1} {
		indexes := []int{}
		sum := 0
		for i, x := range requests {
			if x.p.Side == side {
				indexes = append(indexes, i)
				sum += x.q
			}
		}
		available := r.Canonical.capacity(side)
		allocated := map[int]int{}
		left := available
		for _, i := range indexes {
			q := requests[i].q
			if sum > available {
				q = quantize157(float64(q*available)/float64(sum), r.Config.Quantum)
			}
			allocated[i] = q
			left -= q
		}
		if sum > available {
			sort.SliceStable(indexes, func(i, j int) bool {
				a, b := requests[indexes[i]], requests[indexes[j]]
				ra := float64(a.q*available)/float64(sum) - float64(allocated[indexes[i]])
				rb := float64(b.q*available)/float64(sum) - float64(allocated[indexes[j]])
				if ra == rb {
					if a.p.Started != b.p.Started {
						return a.p.Started < b.p.Started
					}
					return a.p.Key < b.p.Key
				}
				return ra > rb
			})
			for _, i := range indexes {
				if left < r.Config.Quantum {
					break
				}
				allocated[i] += r.Config.Quantum
				left -= r.Config.Quantum
			}
		}
		for _, i := range indexes {
			x := requests[i]
			p := x.p
			q := allocated[i]
			requestRecord := Request159{SourceID: x.sig.ID, Parent: p.Key, Initial: x.initial, SourceQuantity: x.sig.Quantity * 10, Requested: x.q, Accepted: q, Time: o.Time, Index: o.Index, Support: support[p.Side]}
			if q <= 0 {
				requestRecord.Reason = "共有枠不足"
				if x.q == 0 {
					requestRecord.Reason = "希望量0"
					if r.Config.ReselectAdd && !x.initial {
						requestRecord.Reason = "現在支持目標を超えるため追加0"
					}
				}
				r.Requests = append(r.Requests, requestRecord)
				if x.initial {
					p.Rejected = "枠不足"
					r.record157(p, o, "初回拒否", p.Rejected, 0, p.LastSupport)
				} else {
					if x.q == 0 {
						r.Counts["source_add丸め0"]++
						r.record157(p, o, "追加見送り", "希望量0", 0, support[p.Side])
					} else {
						r.Counts["source_add枠不足"]++
						r.record157(p, o, "追加見送り", "共有枠不足", 0, support[p.Side])
					}
				}
				continue
			}
			if x.initial {
				p.InitialQty = q
				p.Factor = float64(q) / float64(p.OldInitial)
			}
			kind := "source_add"
			if x.initial {
				kind = "initial"
			}
			if r.Config.Exact {
				ord := Order157{ID: x.sig.ID, Parent: p.Key, Owner: p.Owner, Campaign: p.Campaign, Side: p.Side, Quantity: q, Kind: kind, Reason: fmt.Sprintf("source:%d", x.sig.ReasonCode), SourceID: x.sig.ID, DecisionIndex: o.Index, DecisionTime: o.Time, DecisionBid: o.Bid, DecisionAsk: o.Ask}
				r.Canonical.Pending = append(r.Canonical.Pending, ord)
			} else {
				if r.Canonical.hasPending(p.Key) {
					r.Counts["source_add予約競合"]++
					requestRecord.Accepted = 0
					requestRecord.Reason = "同親の未確定注文"
					r.Requests = append(r.Requests, requestRecord)
					continue
				}
				r.Canonical.open(p, o, kind, kind, p.Side, q, p.LastSupport)
				r.Canonical.Pending[len(r.Canonical.Pending)-1].SourceID = x.sig.ID
			}
			requestRecord.Reason = "採用"
			if q < x.q {
				requestRecord.Reason = "共有枠で減量採用"
			}
			r.Requests = append(r.Requests, requestRecord)
			r.record157(p, o, "新規判断", kind, q, p.LastSupport)
		}
	}
}

// sourceExact157 は元S01の全通知順・所有ID・数量配賦を厳密10倍で保存します。
//
// 引数: o(Observation)、signals([]strategy.Signal)。返り値: なし。現在の支持を採否に使いません。
func (r *PolicyResult157) sourceExact157(o strategy.Observation, signals []strategy.Signal) {
	for _, sig := range signals {
		key := fmt.Sprintf("%s/%d", sig.Owner, sig.Campaign)
		p := r.Parents[key]
		if p == nil {
			p = &AllocationParent157{Key: key, Owner: sig.Owner, Campaign: sig.Campaign, Side: sig.Side, Started: o.Time, SourceHolds: map[string]int{}}
			r.Parents[key] = p
		}
		kind := "source_close"
		if sig.Action == "new" {
			kind = "source_add"
			if p.OldInitial == 0 {
				kind = "initial"
				p.OldInitial = sig.Quantity * 10
				p.InitialQty = p.OldInitial
				p.Factor = 1
				r.Counts["source_initial"]++
			}
			p.SourceQty += sig.Quantity * 10
			p.SourcePeak = max(p.SourcePeak, p.SourceQty)
		} else {
			p.SourceQty -= sig.Quantity * 10
		}
		ord := Order157{ID: sig.ID, Parent: key, Owner: sig.Owner, Campaign: sig.Campaign, Side: sig.Side, Quantity: sig.Quantity * 10, Kind: kind, Reason: fmt.Sprintf("source:%d", sig.ReasonCode), SourceID: sig.ID, DecisionIndex: o.Index, DecisionTime: o.Time, DecisionBid: o.Bid, DecisionAsk: o.Ask}
		for _, t := range sig.Targets {
			ord.Targets = append(ord.Targets, Target157{t.ID, t.Quantity * 10})
		}
		r.Canonical.Pending = append(r.Canonical.Pending, ord)
	}
}

// afterFills157 は実約定だけから間隔基準・逆行追加使用数・完済の扱いを更新します。
//
// 引数: fills([]Event157)、o(Observation)。返り値: なし。
func (r *PolicyResult157) afterFills157(fills []Event157, o strategy.Observation) {
	for _, e := range fills {
		p := r.Parents[e.Order.Parent]
		if p == nil {
			continue
		}
		p.LastFill = o.Time
		if len(e.Order.Targets) == 0 && e.Order.Kind != "cover" {
			p.LastBasePrice = e.Price
			p.Extreme = e.Price
			p.HasExtreme = true
			p.AdverseReady = false
			if e.Order.Kind == "adverse" {
				p.AdverseUsed += e.Order.Quantity
			}
		}
		if len(e.Order.Targets) > 0 && e.Order.Kind != "cover" {
			if e.Order.Reason == "lot_trail" {
				p.LastBasePrice = e.Price
				p.Extreme = e.Price
				p.HasExtreme = true
				p.AdverseReady = false
				p.RecoveryAllowed = true
			}
			l, s := r.Canonical.position(p.Key, "base")
			if l+s == 0 && e.Order.Reason == "lot_stop" {
				p.Blocked = "価格損失後の同親停止"
			}
		}
	}
}

// elapsed157 は連続成立の開始時計を管理し、未知や欠測を継続時間へ足しません。
//
// 引数: since(*float64)、condition(bool)、at/duration(float64)。返り値: bool。
func elapsed157(since *float64, condition bool, at, duration float64) bool {
	if !condition {
		*since = 0
		return false
	}
	if *since == 0 {
		*since = at
	}
	return at-*since >= duration
}

// manage157 は源退出の後に共通防御・数量増減を判断します。
//
// 引数: o(Observation)、supports(map[int]Support157)、riskOnly(bool)。返り値: なし。
func (r *PolicyResult157) manage157(o strategy.Observation, supports map[int]Support157, riskOnly bool) {
	if r.Config.Exact || !normal(o) {
		return
	}
	b := r.Canonical
	if r.Config.SessionSave && b.Last.Equity <= -160000 {
		r.Stopped = true
	}
	for _, key := range sortedParents157(r.Parents) {
		p := r.Parents[key]
		s := supports[p.Side]
		p.LastSupport = s
		if o.Time-p.LastObservation > 15 || !s.Known {
			p.CoverSince = 0
			p.UncoverSince = 0
			p.CollapseSince = 0
		}
		p.LastObservation = o.Time
		long, short := b.position(key, "base")
		held := long + short
		// ----------------------------------------
		// 極値は支持の強弱や10秒待機と独立に、その玉の実約定以降を全観測で追います。
		if held > 0 && p.HasExtreme {
			mark := o.Bid
			if p.Side < 0 {
				mark = o.Ask
			}
			d := float64(p.Side)
			if d*(mark-p.Extreme) < 0 {
				p.Extreme = mark
			}
			if r.Config.AdverseGap > 0 && d*(mark-p.LastBasePrice) <= -r.Config.AdverseGap {
				p.AdverseReady = true
			}
		}
		if p.Rejected != "" {
			continue
		}
		if o.Time >= r.Scene.ForceClose || p.SourceQty == 0 || r.Stopped {
			b.closeQuantity(p, o, "", "boundary", 1000, s)
			continue
		}
		if !r.Config.OldExit {
			pv := b.Parents[key]
			if pv != nil && pv.Equity <= -80000 {
				p.Blocked = "親時価8万円"
			}
		}
		// ----------------------------------------
		// 旧元玉出口を維持しつつ、支持崩壊だけを指定した対照へ独立に加えます。
		if !r.Config.OldExit || r.Config.SeparateCollapse {
			if s.Known && elapsed157(&p.CollapseSince, s.M < .10 && s.Opp >= .50, o.Time, 15) {
				p.Blocked = "長短支持崩壊"
			}
			if p.Blocked != "" {
				b.closeQuantity(p, o, "", p.Blocked, 1000, s)
				continue
			}
		}
		// ----------------------------------------
		// CoverTrail単独では逆玉だけを40pt起動/40pt追尾し、元玉へ新出口を混ぜません。
		if !r.Config.OldExit || r.Config.CoverTrail {
			for _, id := range b.Active {
				l := b.Lots[id]
				if l.Parent != key || b.reservedClose(id) > 0 || (r.Config.OldExit && l.Kind != "cover") {
					continue
				}
				mark := o.Bid
				if l.Side < 0 {
					mark = o.Ask
				}
				gain := float64(l.Side) * (mark - l.Entry)
				if gain >= 40 {
					l.Activated = true
				}
				if l.Activated {
					floor := l.Entry + float64(l.Side)*math.Max(0, l.Best-40)
					if l.Floor == 0 || float64(l.Side)*(floor-l.Floor) > 0 {
						l.Floor = floor
					}
					if float64(l.Side)*(mark-l.Floor) <= 0 {
						reason := "lot_trail"
						if r.Config.OldExit {
							reason = "cover_trail"
						}
						b.closeLot(p, o, id, reason, l.Remaining, s)
						continue
					}
				}
				if !r.Config.OldExit && gain <= -80 {
					b.closeLot(p, o, id, "lot_stop", l.Remaining, s)
				}
			}
		}
		if held == 0 {
			b.closeQuantity(p, o, "cover", "base_flat", 1000, s)
			p.CoverOn = false
		}
		if riskOnly || (r.Config.OldExit && !r.Config.ManagementEnabled) || p.Blocked != "" || b.hasPending(key) || !s.Known {
			continue
		}
		if r.Config.Cover && held > 0 {
			enter := s.Opp >= .50 && float64(p.Side)*s.Own15 < 0 && float64(p.Side)*s.Own5 <= 0
			leave := s.Opp <= .20 || s.T >= .50
			if elapsed157(&p.CoverSince, enter, o.Time, 5) {
				p.CoverOn = true
			}
			if elapsed157(&p.UncoverSince, leave, o.Time, 5) {
				p.CoverOn = false
			}
		}
		if o.Time-p.LastFill < 10 {
			continue
		}
		threshold := max(5, r.Config.Quantum)
		// ----------------------------------------
		// 源の通常追加が予約済みならここまで来ず、政策独自追加と二重にしません。
		if r.Config.GoodGap > 0 && filter157(s, p.Side) == "" {
			target := r.desired157(s)
			target = quantize157(float64(target)*math.Min(1, float64(p.SourceQty)/float64(max(1, p.SourcePeak))), r.Config.Quantum)
			mark := o.Bid
			if p.Side < 0 {
				mark = o.Ask
			}
			d := float64(p.Side)
			kind := ""
			q := target - held
			if held > 0 && p.AdverseReady && r.Config.AdverseMax > p.AdverseUsed && s.M >= .5 && s.T >= .5 && s.Opp <= .2 && d*(mark-p.Extreme) >= 20 {
				kind = "adverse"
				q = min(q, r.Config.AdverseMax-p.AdverseUsed)
			} else if p.HasExtreme && d*(mark-p.LastBasePrice) >= r.Config.GoodGap && (held > 0 || p.RecoveryAllowed) {
				kind = "policy_add"
				if held == 0 {
					kind = "recover"
				}
			}
			q = quantize157(float64(min(q, b.capacity(p.Side))), r.Config.Quantum)
			if kind != "" && q >= threshold {
				n := b.open(p, o, kind, kind, p.Side, q, s)
				if n > 0 {
					r.record157(p, o, "新規判断", kind, n, s)
					continue
				}
			}
		}
		if r.Config.Cover && held > 0 {
			desired := 0
			if p.CoverOn {
				desired = quantize157(100*s.M*s.Opp*r.scale157(), r.Config.Quantum)
			}
			a, z := b.position(key, "cover")
			have := a + z
			diff := desired - have
			if diff >= threshold {
				q := quantize157(float64(min(diff, b.capacity(-p.Side))), r.Config.Quantum)
				if q < threshold {
					continue
				}
				n := b.open(p, o, "cover", "cover_add", -p.Side, q, s)
				if n > 0 {
					r.record157(p, o, "新規判断", "cover", n, s)
				}
			} else if -diff >= threshold || desired == 0 && have > 0 {
				b.closeQuantity(p, o, "cover", "cover_release", -diff, s)
			}
		}
	}
}

// project157 は同じCanonical親ごとの純数量を実側へ写し、全口座相殺はしません。
//
// 引数: o(Observation)。返り値: なし。元・カバーの相殺往復を実際には省きます。
func (r *PolicyResult157) project157(o strategy.Observation) {
	if r.Actual == r.Canonical {
		return
	}
	a, b := r.Actual, r.Canonical
	for _, key := range sortedParents157(r.Parents) {
		p := r.Parents[key]
		if a.hasPending(key) {
			continue
		}
		cl, cs := b.position(key, "")
		target := cl - cs
		reasons := ""
		kinds, ids := []string{}, []string{}
		for _, ord := range b.Pending {
			if ord.Parent == key {
				target += ord.Side * ord.Quantity
				reasons += ord.Reason + "/"
				kinds = append(kinds, ord.Kind)
				ids = append(ids, ord.ID)
			}
		}
		al, as := a.position(key, "")
		net := al - as
		delta := target - net
		if delta == 0 {
			continue
		}
		side := 1
		if delta < 0 {
			side = -1
		}
		q := int(math.Abs(float64(delta)))
		for _, id := range a.Active {
			l := a.Lots[id]
			if l.Parent == key && l.Side == -side {
				q -= a.closeLot(p, o, id, "net:"+reasons, min(q, l.Remaining), p.LastSupport)
				if q == 0 {
					break
				}
			}
		}
		if q > 0 {
			a.open(p, o, "projection", "net:"+reasons, side, q, p.LastSupport)
		}
		for i := range a.Pending {
			if a.Pending[i].Parent == key {
				a.Pending[i].CanonicalKinds = append([]string(nil), kinds...)
				a.Pending[i].CanonicalOrderIDs = append([]string(nil), ids...)
			}
		}
	}
}
