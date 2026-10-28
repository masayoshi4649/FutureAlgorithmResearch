package main

import (
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
	"sort"
	"strings"
)

type ExcessSlice159 struct {
	ID       string
	Quantity int
}
type ExcessExit159 struct {
	Parent, LotID, Reason                          string
	Time                                           float64
	Index                                          int64
	SourceRemaining, FreeRemaining, Excess, Closed int
	Gain, Peak, Floor                              float64
	Support                                        Support157
}

// excessSlices159 は既存返済予約を除いた親残量から基準残量を引き、新しい玉へ超過分を割り当てます。
//
// 引数: b(*Ledger157)、p(*AllocationParent157)。返り値: []ExcessSlice159、intは自由残量、intは総超過量です。
func excessSlices159(b *Ledger157, p *AllocationParent157) ([]ExcessSlice159, int, int) {
	ids := []string{}
	free := 0
	for _, id := range b.Active {
		l := b.Lots[id]
		if l.Parent != p.Key {
			continue
		}
		q := l.Remaining - b.reservedClose(id)
		if q > 0 {
			ids = append(ids, id)
			free += q
		}
	}
	excess := max(0, free-p.SourceQty)
	sort.Slice(ids, func(i, j int) bool {
		a, z := b.Lots[ids[i]], b.Lots[ids[j]]
		if a.EntryIndex != z.EntryIndex {
			return a.EntryIndex > z.EntryIndex
		}
		return a.ID > z.ID
	})
	left := excess
	slices := []ExcessSlice159{}
	for _, id := range ids {
		q := min(left, b.Lots[id].Remaining-b.reservedClose(id))
		if q > 0 {
			slices = append(slices, ExcessSlice159{id, q})
			left -= q
		}
		if left == 0 {
			break
		}
	}
	return slices, free, excess
}

// excessRisk159 は後半の基準超過分だけに利益追尾と指定した逆行防御を付けます。
//
// 引数: r(*PolicyResult157)、o(Observation)、supports(map[int]Support157)。返り値: なし。元Source返済予約を先に控除します。
func excessRisk159(r *PolicyResult157, o strategy.Observation, supports map[int]Support157) {
	if !normal(o) {
		for _, p := range r.Parents {
			p.GuardSince159 = 0
			p.GuardLastObservation159 = 0
		}
		return
	}
	b := r.Canonical
	for _, key := range sortedParents157(r.Parents) {
		p := r.Parents[key]
		if !strings.HasPrefix(p.Owner, "後半/") {
			continue
		}
		s := supports[p.Side]
		if !s.Known || p.GuardLastObservation159 == 0 || o.Time-p.GuardLastObservation159 > 5 {
			p.GuardSince159 = 0
		}
		p.GuardLastObservation159 = o.Time
		opposite := s.Known && s.Opp >= .5 && float64(p.Side)*s.Own15 < 0 && float64(p.Side)*s.Own5 <= 0
		opposed := elapsed157(&p.GuardSince159, opposite, o.Time, 5)
		slices, free, excess := excessSlices159(b, p)
		for _, slice := range slices {
			l := b.Lots[slice.ID]
			mark := o.Bid
			if l.Side < 0 {
				mark = o.Ask
			}
			gain := float64(l.Side) * (mark - l.Entry)
			// 追尾開始はこの玉が超過分に割り当てられた時点での既知最高順行幅から決めます。
			if l.Best >= r.Config.ProtectionStart {
				l.Activated = true
			}
			reason := ""
			if l.Activated {
				floor := l.Entry + float64(l.Side)*math.Max(0, l.Best-r.Config.ProtectionTrail)
				if l.Floor == 0 || float64(l.Side)*(floor-l.Floor) > 0 {
					l.Floor = floor
				}
				if float64(l.Side)*(mark-l.Floor) <= 0 {
					reason = "後半超過分の固定利益追尾"
				}
			}
			if reason == "" && r.Config.ExcessLossGuard && gain <= -80 && opposed {
				reason = "後半超過分80pt逆行と逆支持5秒"
			}
			if reason != "" {
				q := b.closeLot(p, o, l.ID, reason, slice.Quantity, s)
				if q > 0 {
					r.ExcessExits = append(r.ExcessExits, ExcessExit159{Parent: key, LotID: l.ID, Reason: reason, Time: o.Time, Index: o.Index, SourceRemaining: p.SourceQty, FreeRemaining: free, Excess: excess, Closed: q, Gain: gain, Peak: l.Best, Floor: l.Floor, Support: s})
				}
			}
		}
	}
}
