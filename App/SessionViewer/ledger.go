package main

import "fmt"

type position struct {
	Side, Qty int
	Average   float64
}
type displayLedger struct {
	Positions  map[string]*position
	Realized   float64
	PointValue float64
	Net        bool
}

// newDisplayLedger は表示用の空台帳を作ります。
//
// 引数: r(ResourceMeta)。返り値: *displayLedger。注文・売買判断は行いません。
func newDisplayLedger(r ResourceMeta) *displayLedger {
	return &displayLedger{Positions: map[string]*position{}, PointValue: r.PointValue, Net: r.PNLBasis == "net"}
}

// apply は明示position_idへ約定片を配賦します。
//
// 引数: t(Trade)。返り値: 当片の確定増減(float64)、error。FIFO推測はしません。
func (l *displayLedger) apply(t Trade) (float64, error) {
	if t.Type == "Detach" {
		p := l.Positions[t.PositionID]
		if p == nil || t.Qty < 1 || p.Qty < t.Qty || t.Price != 0 || t.FeeYen != 0 {
			return 0, fmt.Errorf("不存在・過剰又は価格付きの管理外移管: %s", t.PositionID)
		}
		p.Qty -= t.Qty
		return 0, nil
	}
	side := 1
	if t.Type == "ShortN" || t.Type == "ShortR" {
		side = -1
	}
	p := l.Positions[t.PositionID]
	delta := 0.0
	if t.Type == "LongN" || t.Type == "ShortN" {
		if p == nil {
			p = &position{Side: side}
			l.Positions[t.PositionID] = p
		}
		if p.Side != side && p.Qty > 0 {
			return 0, fmt.Errorf("position_idの売買方向が異なります: %s", t.PositionID)
		}
		p.Side = side
		p.Average = (p.Average*float64(p.Qty) + t.Price*float64(t.Qty)) / float64(p.Qty+t.Qty)
		p.Qty += t.Qty
	} else {
		if p == nil || p.Side != side || p.Qty < t.Qty {
			return 0, fmt.Errorf("不存在又は過剰返済: %s", t.PositionID)
		}
		delta = float64(side) * (t.Price - p.Average) * float64(t.Qty) * l.PointValue
		p.Qty -= t.Qty
	}
	if l.Net {
		delta -= t.FeeYen
	}
	l.Realized += delta
	if !finite(l.Realized) {
		return 0, fmt.Errorf("損益が有限範囲を超えました")
	}
	return delta, nil
}

// mark は現在正常BBOで全所有玉を評価し、不明な含みをnullへ分離します。
//
// 引数: q(*marketQuote)は同期可能な板又はnil。返り値: DataSummary。
func (l *displayLedger) mark(q *marketQuote) DataSummary {
	long, short := 0, 0
	unreal := 0.0
	valid := q != nil && q.Bid != nil && q.Ask != nil && *q.Ask > *q.Bid
	for _, p := range l.Positions {
		if p.Side == 1 {
			long += p.Qty
		} else {
			short += p.Qty
		}
		if p.Qty == 0 || !valid {
			continue
		}
		price := *q.Bid
		if p.Side == -1 {
			price = *q.Ask
		}
		unreal += float64(p.Side) * (price - p.Average) * float64(p.Qty) * l.PointValue
	}
	realized := l.Realized
	s := DataSummary{LongQty: &long, ShortQty: &short, Realized: &realized}
	if long+short == 0 || valid {
		if finite(unreal) {
			s.Unrealized = &unreal
		}
	}
	return s
}
