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
	Components                                             *Components1572 `json:"components,omitempty"`
}

type Return1572 struct {
	Known                                                   bool
	Reason                                                  string
	CurrentAt, EndpointAt, Elapsed, Delay, RawReturn, Value float64
	IntermediateBad                                         int64
}
type Components1572 struct {
	OwnKnown, PeerKnown, OFIKnown    bool
	OwnReason, PeerReason, OFIReason string
	Windows                          map[string]Return1572
}

// clip157 は符号を維持した観測を有限区間へ制限します。
//
// 引数: x(float64)。返り値: float64は−1～1です。
func clip157(x float64) float64 { return math.Max(-1, math.Min(1, x)) }

// add は原板から実経過時間を確認できる短期速度用履歴を追加します。
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

// elapsedReturn1572 は現在と許容内の最後の正常過去端から速度又は価格比を計算します。
//
// 引数: rows([]supportRow157)、i(int)、seconds(float64)、normalize(bool)。
// 返り値: Return1572。途中の異常価格は採らず、異常の存在だけで両端比を無効にしません。
func elapsedReturn1572(rows []supportRow157, i int, seconds float64, normalize bool) Return1572 {
	w := Return1572{Reason: "現在値不明"}
	if i < 0 || i >= len(rows) {
		return w
	}
	r := rows[i]
	w.CurrentAt = r.Time
	if !r.Valid || !(r.Mid > 0) || math.IsInf(r.Mid, 0) || math.IsNaN(r.Mid) {
		return w
	}
	bound := r.Time - seconds
	j := sort.Search(i+1, func(j int) bool { return rows[j].Time > bound }) - 1
	for j >= 0 && !rows[j].Valid {
		j--
	}
	if j < 0 {
		w.Reason = "過去端履歴不足"
		return w
	}
	w.EndpointAt = rows[j].Time
	w.Elapsed = r.Time - rows[j].Time
	w.Delay = bound - rows[j].Time
	w.IntermediateBad = r.Bad - rows[j].Bad
	if w.Delay > 15 || w.Elapsed <= 0 {
		w.Reason = "正常過去端が許容15秒より古い"
		return w
	}
	if !(rows[j].Mid > 0) || math.IsNaN(rows[j].Mid) || math.IsInf(rows[j].Mid, 0) {
		w.Reason = "過去端価格非有限"
		return w
	}
	w.RawReturn = 10000 * (r.Mid/rows[j].Mid - 1)
	if math.IsNaN(w.RawReturn) || math.IsInf(w.RawReturn, 0) {
		w.RawReturn = 0
		w.Reason = "価格比非有限"
		return w
	}
	w.Value = w.RawReturn
	if normalize {
		w.Value *= seconds / w.Elapsed
	}
	w.Known = true
	w.Reason = ""
	return w
}

// get は自己価格を必須、相手価格とOFIを個別補助として未校正支持を返します。
//
// 引数: at(float64)、side(int)。返り値: Support157。補助未知は0寄与で重みを再正規化しません。
func (f *SupportBuilder157) get(at float64, side int) Support157 {
	c := &Components1572{OwnReason: "自己履歴不足", PeerReason: "相手履歴不足", OFIReason: "OFI履歴不足", Windows: map[string]Return1572{}}
	o := Support157{Reason: "自己価格未知", Components: c}
	own, peer := f.Markets["NK225"], f.Markets["TOPIX"]
	if own == nil || len(own.Rows) == 0 {
		return o
	}
	i := len(own.Rows) - 1
	r := own.Rows[i]
	o.OwnAt = r.Time
	if r.Time != at || !r.Valid {
		c.OwnReason = "自己現在時計又は気配が不正"
		return o
	}
	// ----------------------------------------
	// 価格窓は正常な両端を使い、短期5/15だけ実経過時間で速度へ換算します。
	c.OwnKnown = true
	c.OwnReason = ""
	for _, x := range []struct {
		name    string
		seconds float64
		target  *float64
	}{{"own5", 5, &o.Own5}, {"own15", 15, &o.Own15}, {"own120", 120, &o.Own120}, {"own300", 300, &o.Own300}} {
		w := elapsedReturn1572(own.Rows, i, x.seconds, x.seconds <= 15)
		c.Windows[x.name] = w
		if w.Known {
			*x.target = w.Value
		} else {
			c.OwnKnown = false
			if c.OwnReason == "" {
				c.OwnReason = x.name + ":" + w.Reason
			}
		}
	}
	if peer != nil {
		j := sort.Search(len(peer.Rows), func(j int) bool { return peer.Rows[j].Time >= at }) - 1
		if j >= 0 {
			o.PeerAt = peer.Rows[j].Time
			if at-o.PeerAt <= 15 {
				w := elapsedReturn1572(peer.Rows, j, 120, false)
				c.Windows["peer120"] = w
				c.PeerKnown = w.Known
				c.PeerReason = w.Reason
				if w.Known {
					o.Peer120 = w.Value
				}
			} else {
				c.PeerReason = "相手現在値が15秒より古い"
			}
		}
	}
	k := sort.Search(len(own.Rows), func(k int) bool { return own.Rows[k].Time >= at-30 }) - 1
	if !r.OFIValid {
		c.OFIReason = "現在OFI差分不成立"
	} else if k < 0 {
		c.OFIReason = "OFI30秒履歴不足"
	} else if r.Bad != own.Rows[k].Bad {
		c.OFIReason = "OFI窓内異常又は空白"
	} else if r.OFICount-own.Rows[k].OFICount < 2 {
		c.OFIReason = "OFI差分2件未満"
	} else {
		v := (r.OFISum - own.Rows[k].OFISum) / float64(r.OFICount-own.Rows[k].OFICount)
		if !math.IsNaN(v) && !math.IsInf(v, 0) {
			o.OFI30 = v
			c.OFIKnown = true
			c.OFIReason = ""
		} else {
			c.OFIReason = "OFI非有限"
		}
	}
	if !c.OwnKnown {
		return o
	}
	d := float64(side)
	o.M = math.Max(0, .45*clip157(d*o.Own120/8)+.35*clip157(d*o.Own300/16)+.20*clip157(d*o.Peer120/8))
	z := .45*clip157(d*o.Own15/3) + .35*clip157(d*o.Own5/1.5) + .20*clip157(d*o.OFI30/.05)
	o.T = math.Max(0, z)
	o.Opp = math.Max(0, -z)
	o.Known = true
	o.Reason = ""
	return o
}
