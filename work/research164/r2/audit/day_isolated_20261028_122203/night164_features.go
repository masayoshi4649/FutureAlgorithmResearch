package main

import (
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
	"sort"
)

type NightPoint164 struct {
	Time, Mid, Path float64
	Invalid, Gaps   int
	Good            bool
}
type NightFeatures164 struct {
	Time, Mid, Spread                                             float64
	Own5, Own15, Own60, Own120, Own300                            float64
	Elapsed5, Elapsed15                                           float64
	ER15, ER120, High60, Low60, Range300                          float64
	Known5, Known15, Known60, Known120, Known300, Path15, Path120 bool
	Invalid300, Gaps300                                           int
	Invalid15, Gaps15, Invalid60, Gaps60, Invalid120, Gaps120     int
	FirstNormal                                                   bool
}
type NightHistory164 struct {
	Rows                                     []NightPoint164
	LastNormalTime, LastMid, LastObservation float64
	HasNormal, HasObservation                bool
	Path                                     float64
	Invalid, Gaps                            int
}

// add は現在原行までのラージ正常中値だけを経路へ加えます。
//
// 引数: o(strategy.Observation)。返り値: NightFeatures164。受信時計を生成しません。
func (h *NightHistory164) add(o strategy.Observation) NightFeatures164 {
	f := NightFeatures164{Time: o.Time}
	good := normal(o)
	if !good {
		h.Invalid++
	} else {
		if h.HasNormal {
			h.Path += math.Abs((o.Bid+o.Ask)/2 - h.LastMid)
			if o.Time-h.LastNormalTime > 15 {
				h.Gaps++
			}
		}
		h.LastMid = (o.Bid + o.Ask) / 2
		h.LastNormalTime = o.Time
		h.HasNormal = true
		f.FirstNormal = !h.HasObservation || o.Time != h.LastObservation
		if f.FirstNormal {
			h.LastObservation = o.Time
			h.HasObservation = true
		}
	}
	h.Rows = append(h.Rows, NightPoint164{o.Time, h.LastMid, h.Path, h.Invalid, h.Gaps, good})
	if !good || !f.FirstNormal {
		return f
	}
	f.Mid = h.LastMid
	f.Spread = o.Ask - o.Bid
	// ----------------------------------------
	// 同時計の後続板は現在判断へ遡らず、次の時計から既知の過去として参照します。
	for _, span := range []float64{5, 15, 60, 120, 300} {
		tolerance := 15.
		if span < 60 {
			tolerance = 1
		}
		k := sort.Search(len(h.Rows), func(i int) bool { return h.Rows[i].Time > o.Time-span }) - 1
		for k >= 0 && !h.Rows[k].Good && o.Time-span-h.Rows[k].Time <= tolerance {
			k--
		}
		if k < 0 || !h.Rows[k].Good || o.Time-span-h.Rows[k].Time > tolerance {
			continue
		}
		r := h.Rows[k]
		elapsed := o.Time - r.Time
		delta := f.Mid - r.Mid
		invalid, gaps := h.Invalid-r.Invalid, h.Gaps-r.Gaps
		// 取得済み正常標本の効率です。欠測中の未観測経路を補間しません。
		pathKnown := true
		er := 0.
		if h.Path > r.Path {
			er = math.Abs(delta) / (h.Path - r.Path)
		}
		switch span {
		case 5:
			f.Own5 = delta * 5 / elapsed
			f.Elapsed5 = elapsed
			f.Known5 = true
		case 15:
			f.Invalid15, f.Gaps15 = invalid, gaps
			f.Own15 = delta * 15 / elapsed
			f.Elapsed15 = elapsed
			f.Known15 = true
			f.Path15 = pathKnown
			f.ER15 = er
		case 60:
			f.Invalid60, f.Gaps60 = invalid, gaps
			f.Known60 = pathKnown
			f.Own60 = delta
			f.High60 = f.Mid
			f.Low60 = f.Mid
			for _, v := range h.Rows[k:] {
				if v.Good {
					f.High60 = math.Max(f.High60, v.Mid)
					f.Low60 = math.Min(f.Low60, v.Mid)
				}
			}
		case 120:
			f.Invalid120, f.Gaps120 = invalid, gaps
			f.Own120 = delta
			f.Known120 = true
			f.Path120 = pathKnown
			f.ER120 = er
		case 300:
			f.Own300 = delta
			f.Known300 = pathKnown
			f.Invalid300 = invalid
			f.Gaps300 = gaps
			high, low := f.Mid, f.Mid
			for _, v := range h.Rows[k:] {
				if v.Good {
					high = math.Max(high, v.Mid)
					low = math.Min(low, v.Mid)
				}
			}
			f.Range300 = high - low
		}
	}
	return f
}

// riskNight164 は現在までの300秒範囲から新注文の固定危険幅を返します。
//
// 引数: f(NightFeatures164)、scope(string)。返り値: float64、bool。未知を最小幅へ代用しません。
func riskNight164(f NightFeatures164, scope string) (float64, bool) {
	if !f.Known300 {
		return 0, false
	}
	minimum := 40.
	if scope == "PostUS" {
		minimum = 60
	}
	return math.Ceil(math.Max(minimum, math.Max(2*f.Spread, f.Range300/4))/10) * 10, true
}

// shortNight164 は方向と速度差を別々に確認します。
//
// 引数: f(NightFeatures164)、side(int)。返り値: bool。
func shortNight164(f NightFeatures164, side int) bool {
	return f.Known5 && f.Known15 && f.Path15 && float64(side)*f.Own5 > 0 && float64(side)*f.Own15 > 0 && float64(side)*(f.Own5/5-f.Own15/15) >= 0
}

// quantityNight164 は未校正の進行と効率を初回希望量へ写します。
//
// 引数: f(NightFeatures164)、side(int)、risk(float64)。返り値: intはmicro数です。
func quantityNight164(f NightFeatures164, side int, risk float64) int {
	if risk <= 0 || !f.Known15 || !f.Path15 {
		return 0
	}
	score := .5*math.Min(1, float64(side)*f.Own15/(.5*risk)) + .5*f.ER15
	return int(math.Floor(100 * math.Max(0, math.Min(1, score))))
}
