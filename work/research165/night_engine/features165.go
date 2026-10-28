package main

import (
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
	"sort"
)

type Frame165 struct {
	Index, Line                                              int64
	Time, Bid, Ask                                           float64
	PriceEvents, QuantityEvents, BadQuantity                 int
	Up, Down, BidOnlyUp, AskOnlyDown, AskOnlyUp, BidOnlyDown float64
	BidRefill, AskRefill, BidDeplete, AskDeplete             float64
	CommonBidUp, CommonAskUp, CommonBidDown, CommonAskDown   float64
	CommonDepthEvents                                        int
}

type Band165 struct {
	Known, QuantityKnown                                                       bool
	StartIndex, Index, StartLine, Line                                         int64
	StartTime, Time, Elapsed                                                   float64
	Events, QuantityEvents, BadQuantity, CommonDepthEvents                     int
	BidMove, AskMove, MidMove, Spread, SpreadChange                            float64
	UpFraction, GrossPriceMove, BidOnlyUp, AskOnlyDown, AskOnlyUp, BidOnlyDown float64
	BidRefill, AskRefill, BidDeplete, AskDeplete                               float64
	CommonBidUp, CommonAskUp, CommonBidDown, CommonAskDown                     float64
}

type Feature165 struct {
	Current                       Frame165
	Changed                       bool
	Event8, Event32, Clock15      Band165
	Resets, InvalidRows, LongGaps int
}

type BookFeatures165 struct {
	Frames                        []Frame165
	PricePoints                   []int
	Previous                      strategy.Board
	HasPrevious                   bool
	Resets, InvalidRows, LongGaps int
}

// finite165 は有限数かを返します。
//
// 引数: x(float64)。返り値: bool。NaNや無限大を既知の数量へ変換しません。
func finite165(x float64) bool { return !math.IsNaN(x) && !math.IsInf(x, 0) }

// validBook165 は正常な価格気配かを検査します。
//
// 引数: b(strategy.Board)。返り値: bool。数量欠測とは分離します。
func validBook165(b strategy.Board) bool {
	return finite165(b.Bid) && finite165(b.Ask) && b.Bid > 0 && b.Ask > b.Bid
}

// validQuantity165 は最良両側数量の既知性を検査します。
//
// 引数: b(strategy.Board)。返り値: bool。表示0と欠測を勝手に有効化しません。
func validQuantity165(b strategy.Board) bool {
	return finite165(b.BidQuantity) && finite165(b.AskQuantity) && b.BidQuantity > 0 && b.AskQuantity > 0
}

// commonDepth165 は共通して見える同価格だけの正負数量差を算出します。
//
// 引数: old/current([10]strategy.ResearchLevel)。返り値: 正増分、負増分(float64)、既知(bool)。
// 段外へ出た価格の数量を0にせず、段番号の移動を補充に数えません。
func commonDepth165(old, current [10]strategy.ResearchLevel) (float64, float64, bool) {
	m := map[float64]float64{}
	for _, x := range old {
		if !finite165(x.Price) || !finite165(x.Quantity) || x.Price <= 0 || x.Quantity < 0 {
			return 0, 0, false
		}
		if _, exists := m[x.Price]; exists {
			return 0, 0, false
		}
		m[x.Price] = x.Quantity
	}
	up, down, denom := 0.0, 0.0, 0.0
	seen := map[float64]bool{}
	for _, x := range current {
		if !finite165(x.Price) || !finite165(x.Quantity) || x.Price <= 0 || x.Quantity < 0 || seen[x.Price] {
			return 0, 0, false
		}
		seen[x.Price] = true
		if q, exists := m[x.Price]; exists {
			d := x.Quantity - q
			up += math.Max(0, d)
			down += math.Max(0, -d)
			denom += q + x.Quantity
		}
	}
	if denom <= 0 {
		return 0, 0, false
	}
	return up / denom, down / denom, true
}

// add165 は現在の物理原行だけから価格イベントと同価格数量を更新します。
//
// 引数: b(strategy.Board)、index/line(int64)。返り値: Feature165。
// 同時計の価格更新を処理し、不正板又は60秒超の時計空白では接続を切ります。
func (h *BookFeatures165) add165(b strategy.Board, index, line int64) Feature165 {
	if !validBook165(b) {
		h.InvalidRows++
		h.Resets++
		h.HasPrevious = false
		h.Frames = nil
		h.PricePoints = nil
		return Feature165{Resets: h.Resets, InvalidRows: h.InvalidRows, LongGaps: h.LongGaps}
	}
	if h.HasPrevious && (b.Time < h.Previous.Time || b.Time-h.Previous.Time > 60) {
		h.LongGaps++
		h.Resets++
		h.HasPrevious = false
		h.Frames = nil
		h.PricePoints = nil
	}
	f := Frame165{Index: index, Line: line, Time: b.Time, Bid: b.Bid, Ask: b.Ask}
	changed := false
	if h.HasPrevious {
		f = h.Frames[len(h.Frames)-1]
		f.Index = index
		f.Line = line
		f.Time = b.Time
		f.Bid = b.Bid
		f.Ask = b.Ask
		p := h.Previous
		db, da := b.Bid-p.Bid, b.Ask-p.Ask
		changed = db != 0 || da != 0
		if changed {
			f.PriceEvents++
			f.Up += math.Max(db, 0) + math.Max(da, 0)
			f.Down += math.Max(-db, 0) + math.Max(-da, 0)
		}
		if db > 0 && da <= 0 {
			f.BidOnlyUp++
		}
		if da < 0 && db >= 0 {
			f.AskOnlyDown++
		}
		if da > 0 && db <= 0 {
			f.AskOnlyUp++
		}
		if db < 0 && da >= 0 {
			f.BidOnlyDown++
		}
		if validQuantity165(b) && validQuantity165(p) {
			if b.Bid != p.Bid || b.Ask != p.Ask || b.BidQuantity != p.BidQuantity || b.AskQuantity != p.AskQuantity {
				f.QuantityEvents++
				if b.Bid == p.Bid {
					d := (b.BidQuantity - p.BidQuantity) / (b.BidQuantity + p.BidQuantity)
					f.BidRefill += math.Max(d, 0)
					f.BidDeplete += math.Max(-d, 0)
				}
				if b.Ask == p.Ask {
					d := (b.AskQuantity - p.AskQuantity) / (b.AskQuantity + p.AskQuantity)
					f.AskRefill += math.Max(d, 0)
					f.AskDeplete += math.Max(-d, 0)
				}
			}
		} else {
			f.BadQuantity++
		}
		if p.BidLevels != b.BidLevels || p.AskLevels != b.AskLevels {
			bu, bd, bk := commonDepth165(p.BidLevels, b.BidLevels)
			au, ad, ak := commonDepth165(p.AskLevels, b.AskLevels)
			if bk && ak && (bu+bd+au+ad > 0) {
				f.CommonDepthEvents++
				f.CommonBidUp += bu
				f.CommonBidDown += bd
				f.CommonAskUp += au
				f.CommonAskDown += ad
			}
		}
	}
	h.Frames = append(h.Frames, f)
	if !h.HasPrevious || changed {
		h.PricePoints = append(h.PricePoints, len(h.Frames)-1)
	}
	h.Previous = b
	h.HasPrevious = true
	return Feature165{Current: f, Changed: changed, Event8: h.event165(8), Event32: h.event165(32), Clock15: h.clock165(15), Resets: h.Resets, InvalidRows: h.InvalidRows, LongGaps: h.LongGaps}
}

// between165 は既知の二原行の差から窓内の価格応答を返します。
//
// 引数: a/z(Frame165)。返り値: Band165。量の平均は最良価格又は数量が変化した有効更新を分母にします。
func between165(a, z Frame165) Band165 {
	b := Band165{Known: true, StartIndex: a.Index, Index: z.Index, StartLine: a.Line, Line: z.Line, StartTime: a.Time, Time: z.Time, Elapsed: z.Time - a.Time,
		Events: z.PriceEvents - a.PriceEvents, QuantityEvents: z.QuantityEvents - a.QuantityEvents, BadQuantity: z.BadQuantity - a.BadQuantity, CommonDepthEvents: z.CommonDepthEvents - a.CommonDepthEvents,
		BidMove: z.Bid - a.Bid, AskMove: z.Ask - a.Ask, MidMove: (z.Bid + z.Ask - a.Bid - a.Ask) / 2, Spread: z.Ask - z.Bid, SpreadChange: z.Ask - z.Bid - a.Ask + a.Bid,
		GrossPriceMove: z.Up + z.Down - a.Up - a.Down, BidOnlyUp: z.BidOnlyUp - a.BidOnlyUp, AskOnlyDown: z.AskOnlyDown - a.AskOnlyDown, AskOnlyUp: z.AskOnlyUp - a.AskOnlyUp, BidOnlyDown: z.BidOnlyDown - a.BidOnlyDown}
	if b.GrossPriceMove > 0 {
		b.UpFraction = (z.Up - a.Up) / b.GrossPriceMove
	}
	b.QuantityKnown = b.BadQuantity == 0
	if b.QuantityEvents > 0 {
		n := float64(b.QuantityEvents)
		b.BidRefill = (z.BidRefill - a.BidRefill) / n
		b.AskRefill = (z.AskRefill - a.AskRefill) / n
		b.BidDeplete = (z.BidDeplete - a.BidDeplete) / n
		b.AskDeplete = (z.AskDeplete - a.AskDeplete) / n
	}
	if b.CommonDepthEvents > 0 {
		n := float64(b.CommonDepthEvents)
		b.CommonBidUp = (z.CommonBidUp - a.CommonBidUp) / n
		b.CommonAskUp = (z.CommonAskUp - a.CommonAskUp) / n
		b.CommonBidDown = (z.CommonBidDown - a.CommonBidDown) / n
		b.CommonAskDown = (z.CommonAskDown - a.CommonAskDown) / n
	}
	return b
}

// event165 は現在までの指定価格遷移数を持つ窓を返します。
//
// 引数: n(int)。返り値: Band165。60秒を越えた古い窓は未知です。
func (h *BookFeatures165) event165(n int) Band165 {
	if len(h.PricePoints) <= n || len(h.Frames) == 0 {
		return Band165{}
	}
	z := h.Frames[len(h.Frames)-1]
	a := h.Frames[h.PricePoints[len(h.PricePoints)-n-1]]
	if z.Time-a.Time > 60 {
		return Band165{}
	}
	return between165(a, z)
}

// clock165 は目標時計以前の最後正常行を過去端とします。
//
// 引数: seconds(float64)。返り値: Band165。過去端の15秒超遅れは未知です。
func (h *BookFeatures165) clock165(seconds float64) Band165 {
	if len(h.Frames) == 0 {
		return Band165{}
	}
	z := h.Frames[len(h.Frames)-1]
	target := z.Time - seconds
	i := sort.Search(len(h.Frames), func(i int) bool { return h.Frames[i].Time > target }) - 1
	if i < 0 || target-h.Frames[i].Time > 15 {
		return Band165{}
	}
	return between165(h.Frames[i], z)
}
