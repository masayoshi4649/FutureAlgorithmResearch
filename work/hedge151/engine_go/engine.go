package main

import (
	"errors"
	"fmt"
	"math"
)

// finiteは有限の数値であることを検査します。
//
// 引数: x(float64)。返り値: boolはNaNと無限大を含まない場合です。
func finite(x float64) bool { return !math.IsNaN(x) && !math.IsInf(x, 0) }

// quoteOKは返済にも新規にも用いる正常な両気配を検査します。
//
// 引数: q(Quote)。返り値: boolは有限かつ0<bid<askの場合です。
func quoteOK(q Quote) bool { return finite(q.Bid) && finite(q.Ask) && q.Bid > 0 && q.Ask > q.Bid }

// newResultは条件ごとの独立在庫と予約を作ります。
//
// 引数: scene(Scene)、cfg(Config)。返り値: *Resultは未運転状態です。
func newResult(scene Scene, cfg Config) *Result {
	end := scene.ForceClose
	if cfg.Scope == "pre" {
		end = scene.USOpen - 900
	}
	return &Result{Config: cfg, ScheduledClose: end, LastIndex: -1, LastTime: scene.Start, EquityPeakAt: Snapshot{Time: scene.Start, Index: -1}, LastSnapshotMinute: -1, Lots: []*Lot{}, Pending: []Pending{}, Events: []Event{}, Decisions: []Decision{}, Snapshots: []Snapshot{}}
}

// exposureは実保有と未約定新規を方向ごとに数えます。
//
// 引数: c(*Result)。返り値: long/short(int)は実保有、reservedLong/reservedShort(int)は予約込みです。
// 返済予約中の玉も実際の約定までは保有に残します。
func exposure(c *Result) (long, short, reservedLong, reservedShort int) {
	for _, lot := range c.Lots {
		if lot.Side > 0 {
			long += lot.Quantity
		} else {
			short += lot.Quantity
		}
	}
	reservedLong, reservedShort = long, short
	for _, p := range c.Pending {
		if p.Action == "new" {
			if p.Side > 0 {
				reservedLong += p.Quantity
			} else {
				reservedShort += p.Quantity
			}
		}
	}
	return
}

// liquidationGainは当該玉を現在の返済側気配で返した場合の1枚当たり値幅を返します。
//
// 引数: lot(*Lot)、q(Quote)。返り値: float64は損益ptです。呼出し前に正常気配を確認します。
func liquidationGain(lot *Lot, q Quote) float64 {
	if lot.Side > 0 {
		return q.Bid - lot.Price
	}
	return lot.Price - q.Ask
}

// findLotは当運転の固有IDから玉を取り出します。
//
// 引数: c(*Result)、id(string)。返り値: *Lotは該当玉、見つからなければnilです。
func findLot(c *Result, id string) *Lot {
	for _, lot := range c.Lots {
		if lot.ID == id {
			return lot
		}
	}
	return nil
}

// fillPendingは前行以前に発注判断済みの成行を次正常原行で約定します。
//
// 引数: c(*Result)、q(Quote)。返り値: errorは同原行約定・所有ID・数量不整合です。
// 既送信新規は境界後でも約定し、その後の境界判断で返済予約します。
func fillPending(c *Result, q Quote) error {
	if !quoteOK(q) {
		return nil
	}
	for _, p := range c.Pending {
		if q.Index <= p.DecisionIndex || q.Time < p.DecisionTime {
			return errors.New("判断以前の約定")
		}
		price := q.Bid
		if p.Side > 0 {
			price = q.Ask
		}
		gross := 0.
		if p.Action == "new" {
			if findLot(c, p.LotID) != nil {
				return errors.New("建玉IDの重複")
			}
			lot := &Lot{ID: p.LotID, SlotID: p.SlotID, Generation: p.Generation, Source: p.Source, Side: p.Side, Quantity: p.Quantity, OriginalQuantity: p.Quantity, Price: price, Time: q.Time, Index: q.Index, Line: q.Line}
			lot.Worst = liquidationGain(lot, q)
			c.Lots = append(c.Lots, lot)
		} else {
			lot := findLot(c, p.LotID)
			if lot == nil || !lot.Closing || lot.Quantity != p.Quantity || lot.Side != -p.Side {
				return errors.New("返済対象の所有ID又は数量不整合")
			}
			gain := float64(lot.Side) * (price - lot.Price)
			gross = gain * float64(p.Quantity) * 100
			lot.Worst = math.Min(lot.Worst, gain)
			lot.Peak = math.Max(lot.Peak, gain)
			lot.Quantity, lot.Closing = 0, false
			lot.ExitPrice, lot.ExitTime, lot.ExitIndex, lot.Gross = price, q.Time, q.Index, gross
			c.Gross += gross
			if gross > 0 {
				c.Profit += gross
			} else {
				c.Loss -= gross
			}
			if p.Reason == "利益追尾" && p.DecisionGain > 0 && gross < 0 {
				c.PositiveDecisionNegativeFill++
			}
			if c.Config.ReentryDistance > 0 && p.Reason == "利益追尾" && gross > 0 {
				c.Arms = append(c.Arms, ReentryArm{SlotID: lot.SlotID, Generation: lot.Generation + 1, Source: lot.Source, Side: lot.Side, Quantity: p.Quantity, Extreme: q.Last, CreatedIndex: q.Index, CreatedTime: q.Time})
			}
		}
		c.Events = append(c.Events, Event{Order: p, FillIndex: q.Index, FillLine: q.Line, FillTime: q.Time, Price: price, Gross: gross})
	}
	c.Pending = nil
	return nil
}

// queueCloseは指定玉だけを次正常板へ返済予約します。
//
// 引数: c(*Result)、lot(*Lot)、q(Quote)、reason(string)。返り値: なし。
// 予約中はQuantityを減らさず、空き枠の先取りを防ぎます。
func queueClose(c *Result, lot *Lot, q Quote, reason string) {
	if lot.Quantity <= 0 || lot.Closing {
		return
	}
	gain := 0.
	if quoteOK(q) {
		gain = liquidationGain(lot, q)
	}
	lot.Closing = true
	c.Pending = append(c.Pending, Pending{ID: lot.ID + "/返済", Action: "close", LotID: lot.ID, SlotID: lot.SlotID, Generation: lot.Generation, Source: lot.Source, Side: -lot.Side, Quantity: lot.Quantity, DecisionIndex: q.Index, DecisionLine: q.Line, DecisionTime: q.Time, DecisionGain: gain, Reason: reason})
}

// markLotsは玉別の返済可能利益を更新し、利益開始後だけ追尾返済を判断します。
//
// 引数: c(*Result)、q(Quote)、allowTrail(bool)。返り値: なし。
// 利益玉限定条件では判断時利益が0以下の玉を返しません。通常追尾条件では返します。
func markLots(c *Result, q Quote, allowTrail bool) {
	if !quoteOK(q) {
		return
	}
	for _, lot := range c.Lots {
		if lot.Quantity <= 0 {
			continue
		}
		gain := liquidationGain(lot, q)
		lot.Peak, lot.Worst = math.Max(lot.Peak, gain), math.Min(lot.Worst, gain)
		if !lot.Activated && lot.Peak >= c.Config.Activation {
			lot.Activated, lot.ActivationTime = true, q.Time
		}
		if allowTrail && !lot.Closing && lot.Activated && lot.Peak-gain >= c.Config.Trail && (!c.Config.RequirePositive || gain > 0) {
			queueClose(c, lot, q, "利益追尾")
		}
	}
}

// acceptNoticeは独立した仮想D07の入口通知を、その時点の実在庫上限へ写します。
//
// 引数: c(*Result)、q(Quote)、n(EntryNotice)。返り値: errorは時刻・添字・通知値の不整合です。
// 拒否した通知は後から復活させません。枠の再利用は次の新しい通知からです。
func acceptNotice(c *Result, q Quote, n EntryNotice) error {
	if n.Index != q.Index || n.Time != q.Time || (n.Side != 1 && n.Side != -1) || n.Quantity <= 0 {
		return errors.New("入口通知と原行が不一致")
	}
	if c.Config.Scope == "pre" && n.Phase != "前半" {
		return nil
	}
	_, _, long, short := exposure(c)
	d := Decision{Notice: n, Rejected: n.Quantity, LongReserved: long, ShortReserved: short}
	available, opposite := 10-long, short
	if n.Side < 0 {
		available, opposite = 10-short, long
	}
	switch {
	case q.Time >= c.ScheduledClose:
		d.Reason = "新規終了時刻"
	case !quoteOK(q):
		d.Reason = "異常気配"
	case c.Config.NoOpposite && opposite > 0:
		d.Reason = "反対側の保有又は新規予約あり"
	case available <= 0:
		d.Reason = "片側上限"
	default:
		quantity := min(n.Quantity, available)
		if c.Config.QuantityLimit > 0 {
			quantity = min(quantity, c.Config.QuantityLimit)
		}
		d.Accepted, d.Rejected, d.Reason = quantity, n.Quantity-quantity, "新規予約"
		id := c.Config.ID + "/" + n.Phase + "/" + n.ID
		if findLot(c, id) != nil {
			return errors.New("同じ入口通知の再利用")
		}
		for _, p := range c.Pending {
			if p.LotID == id {
				return errors.New("同じ入口通知の重複予約")
			}
		}
		c.Pending = append(c.Pending, Pending{ID: id + "/新規", Action: "new", LotID: id, SlotID: id, Source: n, Side: n.Side, Quantity: quantity, DecisionIndex: q.Index, DecisionLine: q.Line, DecisionTime: q.Time, Reason: "仮想D07入口"})
	}
	c.Decisions = append(c.Decisions, d)
	return nil
}

// reenterは利益返済後の固定枠を、現在までのLast極値からの反発・反落で再使用します。
//
// 引数: c(*Result)、q(Quote)。返り値: なし。正常気配の後続原行だけを使います。
// 枠待機中は未発注です。元の枚数を全て確保できなければ待機を残し、返済予定枠を先取りしません。
func reenter(c *Result, q Quote) {
	if !quoteOK(q) || q.Time >= c.ScheduledClose {
		return
	}
	remaining := []ReentryArm{}
	for _, arm := range c.Arms {
		if q.Index <= arm.CreatedIndex {
			remaining = append(remaining, arm)
			continue
		}
		if arm.Side > 0 {
			arm.Extreme = math.Min(arm.Extreme, q.Last)
		} else {
			arm.Extreme = math.Max(arm.Extreme, q.Last)
		}
		trigger := float64(arm.Side)*(q.Last-arm.Extreme) >= c.Config.ReentryDistance
		_, _, long, short := exposure(c)
		available, opposite := 10-long, short
		if arm.Side < 0 {
			available, opposite = 10-short, long
		}
		if !trigger || available < arm.Quantity || (c.Config.NoOpposite && opposite > 0) {
			if trigger && available < arm.Quantity {
				c.ReentryCapWaitRows++
			}
			remaining = append(remaining, arm)
			continue
		}
		id := fmt.Sprintf("%s/再%06d", arm.SlotID, arm.Generation)
		c.Pending = append(c.Pending, Pending{ID: id + "/新規", Action: "new", LotID: id, SlotID: arm.SlotID, Generation: arm.Generation, Source: arm.Source, Side: arm.Side, Quantity: arm.Quantity, DecisionIndex: q.Index, DecisionLine: q.Line, DecisionTime: q.Time, Reason: "利益返済後の追尾再新規"})
		c.ReentryNewCount++
	}
	c.Arms = remaining
}

// recordStateは全玉の清算時価と最大保有数、約定時及び1分ごとの状態を記録します。
//
// 引数: c(*Result)、q(Quote)、eventChanged(bool)。返り値: errorは上限・会計不整合です。
func recordState(c *Result, q Quote, eventChanged bool) error {
	long, short, lr, sr := exposure(c)
	if long > 10 || short > 10 || lr > 10 || sr > 10 {
		return errors.New("保有と未約定新規の片側10枚超過")
	}
	slots := map[string]bool{}
	for _, lot := range c.Lots {
		if lot.Quantity > 0 {
			if slots[lot.SlotID] {
				return errors.New("枠に実玉が重複")
			}
			slots[lot.SlotID] = true
		}
	}
	for _, p := range c.Pending {
		if p.Action == "new" {
			if slots[p.SlotID] {
				return errors.New("枠に新規予約が重複")
			}
			slots[p.SlotID] = true
		}
	}
	for _, arm := range c.Arms {
		if slots[arm.SlotID] {
			return errors.New("枠に再新規待機が重複")
		}
		slots[arm.SlotID] = true
	}
	c.MaxLong, c.MaxShort = max(c.MaxLong, long), max(c.MaxShort, short)
	c.MaxLongReserved, c.MaxShortReserved = max(c.MaxLongReserved, lr), max(c.MaxShortReserved, sr)
	if quoteOK(q) {
		c.LastQuote = q
	}
	unrealized := 0.
	if quoteOK(c.LastQuote) {
		for _, lot := range c.Lots {
			unrealized += liquidationGain(lot, c.LastQuote) * float64(lot.Quantity) * 100
		}
	}
	c.Unrealized = unrealized
	equity := c.Gross + unrealized
	snapshot := Snapshot{Time: q.Time, Index: q.Index, Line: q.Line, Bid: c.LastQuote.Bid, Ask: c.LastQuote.Ask, Long: long, Short: short, Realized: c.Gross, Unrealized: unrealized, Equity: equity}
	if equity < c.MinimumEquity {
		c.MinimumEquity, c.MinimumEquityAt = equity, snapshot
	}
	if unrealized < c.MinimumUnrealized {
		c.MinimumUnrealized, c.MinimumUnrealizedAt = unrealized, snapshot
	}
	if equity > c.EquityPeak {
		c.EquityPeak, c.EquityPeakAt = equity, snapshot
	}
	if c.EquityPeak-equity > c.MaximumDrawdown {
		c.MaximumDrawdown, c.MaximumDrawdownAt, c.MaximumDrawdownFrom = c.EquityPeak-equity, snapshot, c.EquityPeakAt
	}
	minute := int64(q.Time) / 60
	if quoteOK(q) && (eventChanged || minute != c.LastSnapshotMinute) {
		c.Snapshots = append(c.Snapshots, snapshot)
		c.LastSnapshotMinute = minute
	}
	if math.Abs(c.Gross-(c.Profit-c.Loss)) > 1e-7 {
		return errors.New("確定会計の不一致")
	}
	c.PreviousLong, c.PreviousShort = long, short
	if q.Time >= c.ScheduledClose && long+short == 0 && len(c.Pending) == 0 && c.FlatAt == 0 {
		c.FlatAt = q.Time
	}
	return nil
}

// stepは一つの原行を時間順に処理します。
//
// 引数: c(*Result)、q(Quote)、notices([]EntryNotice)は当該原行の入口通知だけです。
// 返り値: errorは因果順序・会計・所有IDの不整合です。未来の約定情報を受け取りません。
func step(c *Result, q Quote, notices []EntryNotice) error {
	if q.Index <= c.LastIndex || q.Time < c.LastTime {
		return errors.New("原行の巻戻り")
	}
	dt := q.Time - c.LastTime
	if c.PreviousLong+c.PreviousShort > 0 {
		c.HeldSeconds += dt
	}
	if c.PreviousLong > 0 && c.PreviousShort > 0 {
		c.HedgedSeconds += dt
	}
	if c.PreviousLong == 10 {
		c.LongCapSeconds += dt
	}
	if c.PreviousShort == 10 {
		c.ShortCapSeconds += dt
	}
	beforeEvents := len(c.Events)
	if err := fillPending(c, q); err != nil {
		return err
	}
	// ----------------------------------------
	// 境界は価格方向より優先し、返済側価格が不正でも時刻で予約できます。
	ended := q.Time >= c.ScheduledClose
	markLots(c, q, !ended)
	if ended {
		if c.CloseDecisionAt == 0 {
			c.CloseDecisionAt = q.Time
		}
		c.ReentryArmsCancelled += len(c.Arms)
		c.Arms = nil
		for _, lot := range c.Lots {
			queueClose(c, lot, q, "境界全返済")
		}
	}
	for _, notice := range notices {
		if err := acceptNotice(c, q, notice); err != nil {
			return err
		}
	}
	// 同じ原行の競合では元B04通知を先に受け、再新規待機は作成順に判定します。
	reenter(c, q)
	if err := recordState(c, q, beforeEvents != len(c.Events)); err != nil {
		return err
	}
	c.LastIndex, c.LastTime = q.Index, q.Time
	return nil
}

// finishは途中観測と完了夜を区別し、保存後半会計を安全に合算します。
//
// 引数: scene(Scene)、c(*Result)、post(ReusedPost)。返り値: errorは未完済の合算又は会計不一致です。
// 後半の未来損益を入口判断へ返さず、再生完了後にだけ合算します。
func finish(scene Scene, c *Result, post ReusedPost) error {
	long, short, _, _ := exposure(c)
	if !scene.Partial && (long+short > 0 || len(c.Pending) > 0 || c.FlatAt == 0) {
		return errors.New("完了夜に残玉又は予約があります")
	}
	if c.Config.Scope == "pre" {
		if post.FirstNewTime > 0 && (c.FlatAt == 0 || c.FlatAt >= post.FirstNewTime) {
			return errors.New("前半完済が保存後半の初回新規より前ではありません")
		}
		c.Post = post
	}
	c.CombinedGross, c.CombinedProfit, c.CombinedLoss = c.Gross+c.Post.Gross, c.Profit+c.Post.Profit, c.Loss+c.Post.Loss
	lotGross := 0.
	for _, lot := range c.Lots {
		lotGross += lot.Gross
	}
	if math.Abs(lotGross-c.Gross) > 1e-7 {
		return errors.New("玉別と現金の確定損益が不一致")
	}
	return nil
}

// replayは固定済み入口通知を原行番号で供給し、条件ごとに独立した実在庫を再生します。
//
// 引数: input(Input)、quotes([]Quote)、configs([]Config)。返り値: []*Resultと不整合errorです。
func replay(input Input, quotes []Quote, configs []Config) ([]*Result, error) {
	byIndex := map[int64][]EntryNotice{}
	for _, n := range input.Notices {
		byIndex[n.Index] = append(byIndex[n.Index], n)
	}
	results := []*Result{}
	for _, cfg := range configs {
		results = append(results, newResult(input.Scene, cfg))
	}
	seen := 0
	for _, q := range quotes {
		ns := byIndex[q.Index]
		seen += len(ns)
		for _, c := range results {
			if err := step(c, q, ns); err != nil {
				return nil, fmt.Errorf("%s/%s/%d: %w", input.Scene.Session, c.Config.ID, q.Index, err)
			}
		}
	}
	if seen != len(input.Notices) {
		return nil, errors.New("入口通知に対応する原行がありません")
	}
	for _, c := range results {
		if err := finish(input.Scene, c, input.Post); err != nil {
			return nil, fmt.Errorf("%s/%s: %w", input.Scene.Session, c.Config.ID, err)
		}
	}
	return results, nil
}
