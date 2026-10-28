package main

import "futurealgorithm/sessiontrader/internal/strategy"

type Barrier165 struct {
	Known        bool
	Price, Time  float64
	Index, Event int64
}
type Candidate165 struct {
	Active          bool
	Side            int
	Bid, Ask, Time  float64
	Index, Event    int64
	QuantitySupport bool
	Barrier         Barrier165
	Support         Barrier165
}
type Hold165 struct {
	Active, QuantitySupport, SupplyPassed, Pressured bool
	ID, Side                                         int
	Bid, Ask, Time                                   float64
	Index, Event, PressureEvent, PressureIndex       int64
	Barrier                                          Barrier165
	Support                                          Barrier165
}
type StateView165 struct {
	Known                                             bool
	Window                                            string
	Band                                              Band165
	PriceEvent                                        int64
	Buy, Sell                                         Hold165
	ConfirmedSide, RetestSide, RetestID, RetestHoldID int
	Invalid                                           bool
}
type Repricing165 struct {
	Clock                    bool
	Sequence, WaveSequence   int
	PriceEvent               int64
	Candidates               [2]Candidate165
	Holds                    [2]Hold165
	BidRecovery, AskRecovery Barrier165
	Previous                 strategy.Board
	HasPrevious              bool
}

// directionSlot165 は符号方向を配列位置へ変換します。
//
// 引数: side(int)。返り値: int。買いは0、売りは1です。
func directionSlot165(side int) int {
	if side > 0 {
		return 0
	}
	return 1
}

// aliveBarrier165 は過去の数量回復の観測範囲を検査します。
//
// 引数: b(Barrier165)、at(float64)、event(int64)。返り値: bool。
func aliveBarrier165(b Barrier165, at float64, event int64) bool {
	return b.Known && at >= b.Time && at-b.Time <= 60 && event >= b.Event && event-b.Event <= 32
}

// clear165 は未知区間をまたいだ価格帯と補充代理を破棄します。
//
// 引数: なし。返り値: なし。ID採番は後戻りさせません。
func (s *Repricing165) clear165() {
	s.Candidates = [2]Candidate165{}
	s.Holds = [2]Hold165{}
	s.BidRecovery = Barrier165{}
	s.AskRecovery = Barrier165{}
	s.HasPrevious = false
}

// step165 は価格移動と後続二更新の維持を因果的に確認します。
//
// 引数: f(Feature165)、b(strategy.Board)。返り値: StateView165。
// 数量圧力だけで既存価格帯を壊さず、数量を使う旗と価格だけの押戻りを分離します。
func (s *Repricing165) step165(f Feature165, b strategy.Board) StateView165 {
	window := f.Event8
	name := "E08"
	if s.Clock {
		window = f.Clock15
		name = "T15"
	}
	v := StateView165{Window: name, Band: window, Known: window.Known, PriceEvent: s.PriceEvent}
	if !validBook165(b) {
		s.clear165()
		v.Invalid = true
		return v
	}
	if s.HasPrevious && (b.Time < s.Previous.Time || b.Time-s.Previous.Time > 60) {
		s.clear165()
	}
	if f.Changed {
		s.PriceEvent++
	}
	v.PriceEvent = s.PriceEvent
	// ----------------------------------------
	// 同価格の回復が実際に当原行であり、直近窓の平均も閾値を満たす時だけ旗を作ります。
	if s.HasPrevious && window.Known && window.QuantityKnown && validQuantity165(b) && validQuantity165(s.Previous) {
		if b.Bid == s.Previous.Bid && b.BidQuantity > s.Previous.BidQuantity && window.BidRefill >= .07 {
			s.BidRecovery = Barrier165{true, b.Bid, b.Time, f.Current.Index, s.PriceEvent}
		}
		if b.Ask == s.Previous.Ask && b.AskQuantity > s.Previous.AskQuantity && window.AskRefill >= .07 {
			s.AskRecovery = Barrier165{true, b.Ask, b.Time, f.Current.Index, s.PriceEvent}
		}
	}
	for slot, side := range []int{1, -1} {
		d := float64(side)
		hold := &s.Holds[slot]
		candidate := &s.Candidates[slot]
		if hold.Active && (b.Time-hold.Time > 60 || s.PriceEvent-hold.Event > 32) {
			hold.Active = false
		}
		if candidate.Active && (b.Time-candidate.Time > 60 || s.PriceEvent-candidate.Event > 32) {
			candidate.Active = false
		}
		if !f.Changed {
			continue
		}
		// ----------------------------------------
		// 反対数量のみでは解除しません。両気配が元帯を越えて逆行すれば維持は消えます。
		if hold.Active && d*(b.Bid-hold.Bid) < -10 && d*(b.Ask-hold.Ask) < -10 {
			hold.Active = false
			hold.Pressured = false
		}
		if hold.Active && s.HasPrevious {
			midMove := d * (b.Bid + b.Ask - s.Previous.Bid - s.Previous.Ask) / 2
			if midMove < 0 {
				hold.Pressured = true
				hold.PressureEvent = s.PriceEvent
				hold.PressureIndex = f.Current.Index
			}
			if hold.Pressured && s.PriceEvent-hold.PressureEvent >= 2 && d*(b.Bid-hold.Bid) >= 0 && d*(b.Ask-hold.Ask) >= 0 && midMove > 0 {
				s.WaveSequence++
				v.RetestSide = side
				v.RetestID = s.WaveSequence
				v.RetestHoldID = hold.ID
				hold.Pressured = false
			}
		}
		if candidate.Active {
			if d*(b.Bid-candidate.Bid) < -10 || d*(b.Ask-candidate.Ask) < -10 {
				candidate.Active = false
			} else if s.PriceEvent-candidate.Event >= 2 && d*(b.Bid-candidate.Bid) >= 0 && d*(b.Ask-candidate.Ask) >= 0 {
				s.Sequence++
				price := b.Bid
				if side < 0 {
					price = b.Ask
				}
				*hold = Hold165{Active: true, ID: s.Sequence, Side: side, Bid: candidate.Bid, Ask: candidate.Ask, Time: b.Time, Index: f.Current.Index, Event: s.PriceEvent, QuantitySupport: candidate.QuantitySupport, Barrier: candidate.Barrier, Support: candidate.Support, SupplyPassed: aliveBarrier165(candidate.Barrier, b.Time, s.PriceEvent) && d*(price-candidate.Barrier.Price) >= 10}
				candidate.Active = false
				s.Holds[1-slot].Active = false
				s.Candidates[1-slot].Active = false
				v.ConfirmedSide = side
			}
		}
		if !hold.Active && !candidate.Active && window.Known && window.GrossPriceMove > 0 {
			fraction := window.UpFraction
			if side < 0 {
				fraction = 1 - fraction
			}
			if d*window.BidMove >= 20 && d*window.AskMove >= 20 && fraction >= .625 {
				own, opp := s.BidRecovery, s.AskRecovery
				if side < 0 {
					own, opp = opp, own
				}
				*candidate = Candidate165{Active: true, Side: side, Bid: b.Bid, Ask: b.Ask, Time: b.Time, Index: f.Current.Index, Event: s.PriceEvent, QuantitySupport: aliveBarrier165(own, b.Time, s.PriceEvent), Barrier: opp, Support: own}
			}
		}
	}
	s.Previous = b
	s.HasPrevious = true
	v.Buy = s.Holds[0]
	v.Sell = s.Holds[1]
	return v
}
