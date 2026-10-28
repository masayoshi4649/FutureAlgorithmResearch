package main

import (
	"errors"
	"fmt"
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
)

// step157 は現在原行で実約定・支持・数量政策を順番に評価します。
//
// 引数: r(*PolicyResult157)、o(Observation)、signals([]Signal)、supports(map[int]Support157)。返り値: error。
func stepPolicy159(r *PolicyResult157, o strategy.Observation, signals []strategy.Signal, supports map[int]Support157) error {
	r.ObservationEnd = o.Time
	r.Canonical.mark(o)
	if r.Actual != r.Canonical {
		r.Actual.mark(o)
	}
	fills, err := r.Canonical.fill(o)
	if err != nil {
		return err
	}
	r.afterFills157(fills, o)
	if r.Actual != r.Canonical {
		if _, err = r.Actual.fill(o); err != nil {
			return err
		}
	}
	r.Canonical.mark(o)
	if r.Actual != r.Canonical {
		r.Actual.mark(o)
	}
	// ----------------------------------------
	// 新しい判断前に親別の純量一致を確認します。買売の清算時価一致は要求しません。
	if normal(o) && r.Actual != r.Canonical {
		for _, key := range sortedParents157(r.Parents) {
			cl, cs := r.Canonical.position(key, "")
			al, as := r.Actual.position(key, "")
			diff := float64((cl - cs) - (al - as))
			r.ProjectionChecks++
			r.ProjectionMaxDifference = math.Max(r.ProjectionMaxDifference, math.Abs(diff))
			if diff != 0 {
				return fmt.Errorf("親内純量差 %s canonical=%d actual=%d", key, cl-cs, al-as)
			}
		}
	}
	if r.Config.Exact {
		r.source157(o, signals, supports)
	} else {
		closes, news := []strategy.Signal{}, []strategy.Signal{}
		for _, s := range signals {
			if s.Action == "close" {
				closes = append(closes, s)
			} else {
				news = append(news, s)
			}
		}
		r.source157(o, closes, supports)
		r.manage157(o, supports, true)
		extraRisk159(r, o, supports)
		r.source157(o, news, supports)
		r.manage157(o, supports, false)
	}
	r.project157(o)
	for _, p := range r.Parents {
		cl, cs := r.Canonical.position(p.Key, "")
		al, as := r.Actual.position(p.Key, "")
		p.Finished = (p.SourceQty == 0 || p.Blocked != "" || p.Rejected != "") && cl+cs+al+as == 0 && !r.Canonical.hasPending(p.Key) && !r.Actual.hasPending(p.Key)
	}
	for _, b := range []*Ledger157{r.Canonical, r.Actual} {
		l, s := b.position("", "")
		for _, p := range b.Pending {
			if len(p.Targets) == 0 {
				if p.Side > 0 {
					l += p.Quantity
				} else {
					s += p.Quantity
				}
			}
		}
		if l > 100 || s > 100 {
			return errors.New("予約込み100micro上限違反")
		}
	}
	return nil
}
