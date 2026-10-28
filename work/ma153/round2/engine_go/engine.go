package main

import (
	"errors"
	"math"
)

// proportional は当時の保有方向への速度を1〜10枚へ連続的に割り当てます。
//
// 引数: speed(float64)はbp/分。返り値: intは小数切捨ての目標枚数です。
func proportional(speed float64) int {
	return 1 + int(math.Floor(9*math.Max(0, math.Min(1, (speed-.25)/2.25))))
}

// newResult は当場だけの独立口座を準備します。
//
// 引数: scene(Scene)、symbol(string)、config(Config)。返り値: *Resultです。
func newResult(scene Scene, symbol string, config Config) *Result {
	multiplier := 100.
	if symbol == "TOPIX" {
		multiplier = 1000
	}
	return &Result{Config: config, Session: scene.Session, Kind: scene.Kind, Symbol: symbol, Partial: scene.Partial, PointValue: multiplier, Start: scene.Start, ForceClose: scene.ForceClose, End: scene.End, LastIndex: -1, LastTime: scene.Start, LastMinute: -1, Armed: map[int]bool{-1: true, 1: true}, ArmResetIndex: map[int]int64{-1: -1, 1: -1}, Rejections: map[string]int{}}
}

// queue は同時に一つだけの成行依頼を作り、判断時点の特徴を固定します。
//
// 引数: c(*Result)、q(Quote)、f(Feature)、action/reason(string)、side/quantity(int)。返り値: なし。
func queue(c *Result, q Quote, f Feature, action, reason string, side, quantity int) {
	if c.Pending != nil || quantity <= 0 {
		return
	}
	c.Sequence++
	parentID := len(c.Parents) + 1
	if c.Current != nil {
		parentID = c.Current.ID
	}
	o := &Order{ID: c.Sequence, ParentID: parentID, Action: action, Reason: reason, Side: side, Quantity: quantity, DecisionIndex: q.Index, DecisionLine: q.Line, DecisionTime: q.Time, DecisionBid: q.Bid, DecisionAsk: q.Ask, Feature: f, ShortFeature: c.ShortCurrent, LastNewPrice: c.LastNewPrice}
	if c.Current != nil {
		o.EntrySlope = c.Current.EntrySlope
		o.PeakSlope = c.Current.PeakSlope
		o.PeakGain = c.Current.PeakGain
	}
	c.Pending = o
	if action == "new" {
		if c.Quantity == 0 {
			c.NewOrders++
			if reentryRequired(c.Config.ID) {
				c.Armed[side] = false
			}
		} else {
			c.AddOrders++
		}
	} else if reason == "比例枚数へ縮小" {
		c.ReduceOrders++
	} else {
		c.CloseOrders++
	}
}

// fillPending は判断行より後の正常気配で全数量を約定させます。
//
// 引数: c(*Result)、q(Quote)。返り値: boolは約定有無、errorは方向・枚数不整合です。
func fillPending(c *Result, q Quote) (bool, error) {
	o := c.Pending
	if o == nil || !quoteOK(q) || q.Index <= o.DecisionIndex {
		return false, nil
	}
	price := q.Ask
	if o.Side < 0 {
		price = q.Bid
	}
	event := Event{Order: *o, FillIndex: q.Index, FillLine: q.Line, FillTime: q.Time, Price: price, FillBid: q.Bid, FillAsk: q.Ask}
	if o.Action == "new" {
		if c.Quantity+o.Quantity > 10 || c.Quantity > 0 && c.Side != o.Side {
			return false, errors.New("新規約定が方向又は10枚上限へ違反しました")
		}
		if c.Quantity == 0 {
			c.Current = &Parent{ID: o.ParentID, Side: o.Side, EntryQuantity: o.Quantity, EntryTime: q.Time, Anchor: price, EntrySlope: math.Abs(o.Feature.Slope), PeakSlope: math.Abs(o.Feature.Slope)}
			c.Side = o.Side
			if c.FirstEntry == 0 {
				c.FirstEntry = q.Time
			}
		}
		c.Lots = append(c.Lots, Lot{ID: len(c.Lots) + 1, ParentID: c.Current.ID, Side: o.Side, Initial: o.Quantity, Quantity: o.Quantity, Price: price, At: q.Time})
		c.Quantity += o.Quantity
		c.LastEntry = q.Time
		c.LastNewPrice, c.LastNewTime = price, q.Time
	} else {
		if c.Current == nil || o.Side != -c.Side || o.Quantity > c.Quantity {
			return false, errors.New("返済方向又は残数が一致しません")
		}
		remaining := o.Quantity
		for i := c.OpenStart; i < len(c.Lots) && remaining > 0; i++ {
			lot := &c.Lots[i]
			amount := min(lot.Quantity, remaining)
			if amount == 0 {
				continue
			}
			gain := float64(lot.Side*amount) * (price - lot.Price) * c.PointValue
			lot.Quantity -= amount
			lot.Realized += gain
			remaining -= amount
			event.Gross += gain
			event.Closed = append(event.Closed, Allocation{lot.ID, amount, lot.Price, price, gain})
			if gain > 0 {
				c.Profit += gain
			} else {
				c.Loss -= gain
			}
		}
		if remaining != 0 {
			return false, errors.New("FIFO返済対象が不足しています")
		}
		c.Quantity -= o.Quantity
		c.Gross += event.Gross
		c.Current.Realized += event.Gross
		for c.OpenStart < len(c.Lots) && c.Lots[c.OpenStart].Quantity == 0 {
			c.OpenStart++
		}
		if c.Quantity == 0 {
			if reentryRequired(c.Config.ID) {
				c.Armed[c.Side] = false
				c.ArmResetIndex[c.Side] = q.Index
			}
			c.Current.CloseTime = q.Time
			c.Current.ExitReason = o.Reason
			c.Parents = append(c.Parents, *c.Current)
			c.Current = nil
			c.Side = 0
			c.ReadyAfter = q.Time + 10
		}
	}
	c.Events = append(c.Events, event)
	c.Pending = nil
	c.LastRebalance = q.Time
	return true, nil
}

// evaluate は価格の防御・追尾と傾き条件を順に評価し、全返済を数量変更より優先します。
//
// 引数: c(*Result)、q(Quote)、f(Feature)。返り値: なし。
func evaluate(c *Result, q Quote, f Feature) {
	if q.Time >= c.ForceClose {
		if c.CloseDecisionAt == 0 {
			c.CloseDecisionAt = q.Time
		}
		if c.Quantity > 0 && c.Pending == nil {
			queue(c, q, f, "close", "場内全返済", -c.Side, c.Quantity)
		}
		return
	}
	if c.Quantity > 0 {
		p := c.Current
		updateParent(c, q, f)
		reason := ""
		if quoteOK(q) {
			mark := q.Bid
			if c.Side < 0 {
				mark = q.Ask
			}
			gain := float64(c.Side) * (mark - p.Anchor)
			if p.PeakGain >= c.OpeningMid*.0006 {
				p.Activated = true
			}
			if gain <= -c.OpeningMid*.0012 {
				reason = "初期逆行12bp"
			} else if p.Activated && p.PeakGain-gain >= c.OpeningMid*.0003 {
				reason = "利益開始後3bp戻り"
			}
		}
		if reason == "" && f.Known && c.Config.Exit != "T" {
			signed := float64(c.Side) * f.Slope
			if signed <= 0 {
				reason = "傾きの方向反転"
			} else if c.Config.Exit == "D" && p.Strengthened && signed <= p.PeakSlope*.5 {
				reason = "2倍へ増勢後に傾き半減"
			}
		}
		if reason != "" {
			if c.Pending == nil {
				queue(c, q, f, "close", reason, -c.Side, c.Quantity)
			}
			return
		}
		if c.Pending != nil || !quoteOK(q) || !f.Known || c.Config.Allocation != "dynamic" || q.Time-c.LastRebalance < 10 {
			return
		}
		target := proportional(float64(c.Side) * f.Slope)
		if guardedAllocation(c.Config.ID) && !allocationAllowed(c, q, target) {
			return
		}
		if target > c.Quantity {
			queue(c, q, f, "new", "比例枚数へ追加", c.Side, target-c.Quantity)
		} else if target < c.Quantity {
			queue(c, q, f, "close", "比例枚数へ縮小", -c.Side, c.Quantity-target)
		}
		return
	}
	if c.Pending != nil || q.Time < c.ReadyAfter || !quoteOK(q) || !f.Known || math.Abs(f.Slope) < .25 {
		return
	}
	side := 1
	if f.Slope < 0 {
		side = -1
	}
	if reentryRequired(c.Config.ID) && !c.Armed[side] {
		c.Rejections["同方向の冷却待ち"]++
		return
	}
	if alignmentRequired(c.Config.ID) && !entryAligned(c, q, f, side) {
		return
	}
	quantity := proportional(math.Abs(f.Slope))
	if c.Config.Allocation == "fixed1" {
		quantity = 1
	} else if c.Config.Allocation == "fixed10" {
		quantity = 10
	}
	queue(c, q, f, "new", "平均傾きの方向へ新規", side, quantity)
}

// updateParent は返済実約定の原行も含めて、親の有利幅・不利幅と傾きを記録します。
//
// 引数: c(*Result)、q(Quote)、f(Feature)。返り値: なし。追加でも初回建値は変えません。
func updateParent(c *Result, q Quote, f Feature) {
	if c.Current == nil {
		return
	}
	p := c.Current
	if f.Known {
		p.LastSlope = f.Slope
		p.LastSlopeTime = q.Time
		p.PeakSlope = math.Max(p.PeakSlope, float64(c.Side)*f.Slope)
		if p.PeakSlope >= 2*p.EntrySlope {
			p.Strengthened = true
		}
	}
	if quoteOK(q) {
		mark := q.Bid
		if c.Side < 0 {
			mark = q.Ask
		}
		gain := float64(c.Side) * (mark - p.Anchor)
		if gain > p.PeakGain {
			p.PeakGain = gain
			p.PeakGainTime = q.Time
		}
		if gain < p.WorstGain {
			p.WorstGain = gain
			p.WorstGainTime = q.Time
		}
	}
}

// mark は全残玉の清算含み・全会計・最大保有と時価下落を記録します。
//
// 引数: c(*Result)、q(Quote)、changed(bool)は当行約定有無。返り値: errorは会計又は上限違反です。
func mark(c *Result, q Quote, changed bool) error {
	if quoteOK(q) {
		c.LastQuote = q
		c.ClosingMid = (q.Bid + q.Ask) / 2
	}
	reserved := c.Quantity
	if c.Pending != nil && c.Pending.Action == "new" {
		reserved += c.Pending.Quantity
	}
	if c.Quantity < 0 || reserved > 10 {
		return errors.New("保有と新規予約が10枚を超えました")
	}
	c.MaxQuantity = max(c.MaxQuantity, c.Quantity)
	c.MaxReserved = max(c.MaxReserved, reserved)
	unrealized := 0.
	if quoteOK(c.LastQuote) {
		for i := c.OpenStart; i < len(c.Lots); i++ {
			l := c.Lots[i]
			price := c.LastQuote.Bid
			if l.Side < 0 {
				price = c.LastQuote.Ask
			}
			unrealized += float64(l.Side*l.Quantity) * (price - l.Price) * c.PointValue
		}
	}
	c.Unrealized = unrealized
	equity := c.Gross + unrealized
	s := Snapshot{q.Time, q.Index, c.LastQuote.Bid, c.LastQuote.Ask, c.Side, c.Quantity, c.Gross, unrealized, equity}
	if c.PeakSnapshot.Time == 0 {
		c.PeakSnapshot = s
		c.PeakSnapshot.Realized = 0
		c.PeakSnapshot.Unrealized = 0
		c.PeakSnapshot.Equity = 0
	}
	if equity < c.MinimumEquity {
		c.MinimumEquity = equity
		c.MinimumEquityAt = s
	}
	if unrealized < c.MinimumUnrealized {
		c.MinimumUnrealized = unrealized
		c.MinimumUnrealizedAt = s
	}
	if equity > c.PeakEquity {
		c.PeakEquity = equity
		c.PeakSnapshot = s
	}
	if c.PeakEquity-equity > c.MaximumDrawdown {
		c.MaximumDrawdown = c.PeakEquity - equity
		c.MaximumDrawdownAt = s
		c.MaximumDrawdownFrom = c.PeakSnapshot
	}
	minute := int64(q.Time) / 60
	if quoteOK(q) && (changed || minute != c.LastMinute) {
		c.Snapshots = append(c.Snapshots, s)
		c.LastMinute = minute
	}
	if math.Abs(c.Gross-c.Profit+c.Loss) > 1e-6 {
		return errors.New("確定損益会計が一致しません")
	}
	if q.Time >= c.ForceClose && c.Quantity == 0 && c.Pending == nil && c.FlatAt == 0 {
		c.FlatAt = q.Time
	}
	return nil
}

// step は未来を渡さず一つの原板を処理します。
//
// 引数: c(*Result)、q(Quote)、f(Feature)、short(...Feature)は60秒・差30秒の傾きです。
// 返り値: errorは順序・会計不整合です。短期特徴省略は人工基準対照だけで使用します。
func step(c *Result, q Quote, f Feature, short ...Feature) error {
	if q.Index <= c.LastIndex || q.Time < c.LastTime {
		return errors.New("原板の時計又は連番が逆行しました")
	}
	dt := q.Time - c.LastTime
	if c.PreviousHeld {
		c.HeldSeconds += dt
	}
	if c.PreviousKnown {
		c.KnownSeconds += math.Min(dt, 120)
	}
	if c.OpeningMid == 0 && quoteOK(q) {
		c.OpeningMid = (q.Bid + q.Ask) / 2
	}
	if f.Known && c.FirstKnownAt == 0 {
		c.FirstKnownAt = q.Time
	}
	c.ShortCurrent = Feature{}
	if len(short) > 0 {
		c.ShortCurrent = short[0]
	}
	updateParent(c, q, f)
	changed, err := fillPending(c, q)
	if err != nil {
		return err
	}
	refreshArms(c, q, f)
	evaluate(c, q, f)
	if err = mark(c, q, changed); err != nil {
		return err
	}
	c.LastIndex, c.LastTime = q.Index, q.Time
	c.ObservationEnd = q.Time
	c.EligibleSeconds = q.Time - c.Start
	c.PreviousHeld = c.Quantity > 0
	c.PreviousKnown = f.Known
	return nil
}

// finish は途中観測を勝手に清算せず、全保有と完結会計を検算します。
//
// 引数: c(*Result)。返り値: errorは完了場の残玉又は会計差です。
func finish(c *Result) error {
	if !c.Partial && (c.Quantity != 0 || c.Pending != nil || c.FlatAt == 0) {
		return errors.New("完了場に未返済・未約定又は終端観測不足があります")
	}
	if !c.Partial {
		c.EligibleSeconds = c.End - c.Start
	}
	sum := 0.
	for _, l := range c.Lots {
		sum += l.Realized
	}
	if math.Abs(sum-c.Gross) > 1e-6 {
		return errors.New("玉別確定会計が一致しません")
	}
	sum = 0
	for _, p := range c.Parents {
		sum += p.Realized
	}
	if c.Current != nil {
		sum += c.Current.Realized
	}
	if math.Abs(sum-c.Gross) > 1e-6 {
		return errors.New("方向親会計が一致しません")
	}
	return nil
}
