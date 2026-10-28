package main

import (
	"fmt"
	"futurealgorithm/sessiontrader/internal/strategy"
)

// Piece156 は各返済配賦の利益返しを、親収支から独立して記録します。
type Piece156 struct {
	ID, Owner                                                    string
	Campaign, Side, Quantity, Reason                             int
	Entry, Exit, Gross, BestGain, WorstGain, Floor, ProtectionAt float64
	Protected, PositiveThenLoss                                  bool
}
type ParentMark156 struct {
	Owner                                                          string
	Campaign                                                       int
	Realized, Unrealized, Equity, Peak, Minimum, PeakAt, MinimumAt float64
	Remaining                                                      int
	PositiveThenLoss                                               bool
}

// markParents156 は全案に同じ原板で親時価を測定し、黒字経験後の赤字確定を区別します。
//
// 引数: r(*Result)、o(strategy.Observation)。返り値: なし。判断への入力には使いません。
func markParents156(r *Result, o strategy.Observation) {
	if r.Parents == nil {
		r.Parents = map[string]*ParentMark156{}
	}
	for _, p := range r.Parents {
		p.Realized = 0
		p.Unrealized = 0
		p.Remaining = 0
	}
	for _, l := range r.Entries {
		key := fmt.Sprintf("%s/%d", l.Owner, l.Campaign)
		p := r.Parents[key]
		if p == nil {
			p = &ParentMark156{Owner: l.Owner, Campaign: l.Campaign}
			r.Parents[key] = p
		}
		p.Realized += l.Gross
		p.Remaining += l.Remaining
		mark := o.Bid
		if l.Side < 0 {
			mark = o.Ask
		}
		p.Unrealized += float64(l.Side*l.Remaining) * (mark - l.Price) * 100
	}
	for _, p := range r.Parents {
		p.Equity = p.Realized + p.Unrealized
		if p.Equity > p.Peak {
			p.Peak = p.Equity
			p.PeakAt = o.Time
		}
		if p.Equity < p.Minimum {
			p.Minimum = p.Equity
			p.MinimumAt = o.Time
		}
		p.PositiveThenLoss = p.Remaining == 0 && p.Peak > 0 && p.Realized < 0
	}
}
