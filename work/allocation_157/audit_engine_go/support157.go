package main

import (
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
	"sort"
)

type supportRow157 struct {
	Time, Mid, OFISum float64
	Bad, OFICount     int64
	Valid             bool
	OFIValid          bool
}
type supportMarket157 struct {
	Rows          []supportRow157
	Last          strategy.Board
	Seen          bool
	Bad, OFICount int64
	OFISum        float64
}
type SupportBuilder157 struct{ Markets map[string]*supportMarket157 }
type Support157 struct {
	Known                                                  bool
	Reason                                                 string
	Own5, Own15, Own120, Own300, Peer120, OFI30, M, T, Opp float64
	OwnAt, PeerAt                                          float64
}

// clip157 は符号を維持した観測を有限区間へ制限します。
//
// 引数: x(float64)。返り値: float64は−1～1です。
func clip157(x float64) float64 { return math.Max(-1, math.Min(1, x)) }

// add は原板から真の5/15秒窓用履歴を追加します。
//
// 引数: b(strategy.Board)。返り値: なし。同時計は順番だけを維持し未来相手へ使用しません。
func (f *SupportBuilder157) add(b strategy.Board) {
	if f.Markets == nil {
		f.Markets = map[string]*supportMarket157{}
	}
	s := f.Markets[b.Reference]
	if s == nil {
		s = &supportMarket157{}
		f.Markets[b.Reference] = s
	}
	valid := b.Bid > 0 && b.Ask > b.Bid && !math.IsInf(b.Ask, 0) && !math.IsNaN(b.Bid)
	if !valid || (s.Seen && b.Time-s.Last.Time > 15) {
		s.Bad++
	}
	finiteQty := func(x float64) bool { return x > 0 && !math.IsNaN(x) && !math.IsInf(x, 0) }
	qty := valid && finiteQty(b.BidQuantity) && finiteQty(b.AskQuantity)
	p := s.Last
	ofiValid := false
	if qty && s.Seen && p.Bid > 0 && p.Ask > p.Bid && finiteQty(p.BidQuantity) && finiteQty(p.AskQuantity) && b.Time-p.Time <= 15 {
		x := 0.
		if b.Bid >= p.Bid {
			x += b.BidQuantity
		}
		if b.Bid <= p.Bid {
			x -= p.BidQuantity
		}
		if b.Ask <= p.Ask {
			x -= b.AskQuantity
		}
		if b.Ask >= p.Ask {
			x += p.AskQuantity
		}
		den := b.BidQuantity + p.BidQuantity + b.AskQuantity + p.AskQuantity
		v := x / den
		if !math.IsInf(x, 0) && !math.IsInf(den, 0) && !math.IsNaN(v) && !math.IsInf(v, 0) && !math.IsInf(s.OFISum+v, 0) {
			s.OFISum += v
			s.OFICount++
			ofiValid = true
		}
	}
	r := supportRow157{Time: b.Time, Bad: s.Bad, Valid: valid, OFIValid: ofiValid, OFISum: s.OFISum, OFICount: s.OFICount}
	if valid {
		r.Mid = b.Bid + (b.Ask-b.Bid)/2
	}
	s.Rows = append(s.Rows, r)
	s.Last = b
	s.Seen = true
	keep := sort.Search(len(s.Rows), func(i int) bool { return s.Rows[i].Time >= b.Time-340 })
	if keep > 0 {
		s.Rows = s.Rows[keep:]
	}
}

// return157 は厳密過去の窓端だけから価格比を計算します。
//
// 引数: rows([]supportRow157)、i(int)、seconds/tolerance(float64)。返り値: bp変化(float64)、既知(bool)。
func return157(rows []supportRow157, i int, seconds, tolerance float64) (float64, bool) {
	if i < 0 || !rows[i].Valid {
		return 0, false
	}
	r := rows[i]
	bound := r.Time - seconds
	j := sort.Search(i+1, func(j int) bool { return rows[j].Time > bound }) - 1
	if j < 0 || !rows[j].Valid || bound-rows[j].Time > tolerance || r.Bad != rows[j].Bad {
		return 0, false
	}
	v := 10000 * (r.Mid/rows[j].Mid - 1)
	return v, !math.IsNaN(v) && !math.IsInf(v, 0)
}

// get は長期と短期の未校正支持を同じ当時情報で返します。
//
// 引数: at(float64)、side(int)。返り値: Support157。未知を0支持と混同しません。
func (f *SupportBuilder157) get(at float64, side int) Support157 {
	o := Support157{Reason: "指標未知"}
	own, peer := f.Markets["NK225"], f.Markets["TOPIX"]
	if own == nil || peer == nil || len(own.Rows) == 0 {
		return o
	}
	i := len(own.Rows) - 1
	r := own.Rows[i]
	o.OwnAt = r.Time
	if r.Time != at || !r.Valid || !r.OFIValid || own.Last.BidQuantity <= 0 || own.Last.AskQuantity <= 0 || math.IsNaN(own.Last.BidQuantity) || math.IsNaN(own.Last.AskQuantity) || math.IsInf(own.Last.BidQuantity, 0) || math.IsInf(own.Last.AskQuantity, 0) {
		return o
	}
	j := sort.Search(len(peer.Rows), func(j int) bool { return peer.Rows[j].Time >= at }) - 1
	if j < 0 || at-peer.Rows[j].Time > 15 {
		return o
	}
	o.PeerAt = peer.Rows[j].Time
	var ok bool
	if o.Own5, ok = return157(own.Rows, i, 5, 2); !ok {
		return o
	}
	if o.Own15, ok = return157(own.Rows, i, 15, 2); !ok {
		return o
	}
	if o.Own120, ok = return157(own.Rows, i, 120, 15); !ok {
		return o
	}
	if o.Own300, ok = return157(own.Rows, i, 300, 15); !ok {
		return o
	}
	if o.Peer120, ok = return157(peer.Rows, j, 120, 15); !ok {
		return o
	}
	k := sort.Search(len(own.Rows), func(k int) bool { return own.Rows[k].Time >= at-30 }) - 1
	if k < 0 || r.Bad != own.Rows[k].Bad || r.OFICount-own.Rows[k].OFICount < 2 {
		return o
	}
	o.OFI30 = (r.OFISum - own.Rows[k].OFISum) / float64(r.OFICount-own.Rows[k].OFICount)
	d := float64(side)
	o.M = math.Max(0, .45*clip157(d*o.Own120/8)+.35*clip157(d*o.Own300/16)+.20*clip157(d*o.Peer120/8))
	t := .45*clip157(d*o.Own15/3) + .35*clip157(d*o.Own5/1.5) + .20*clip157(d*o.OFI30/.05)
	o.T = math.Max(0, t)
	o.Opp = math.Max(0, -t)
	for _, v := range []float64{o.M, o.T, o.Opp, o.OFI30} {
		if math.IsNaN(v) || math.IsInf(v, 0) {
			return Support157{Reason: "指標非有限", OwnAt: o.OwnAt, PeerAt: o.PeerAt}
		}
	}
	o.Known = true
	o.Reason = ""
	return o
}
