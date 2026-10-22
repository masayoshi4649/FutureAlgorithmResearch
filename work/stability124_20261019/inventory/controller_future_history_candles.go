package main

import (
	"math"
	"time"
)

// futureHistoryQuote は、受信した先物情報のうち分足に必要な値だけを保持します。
// nil は未提供の値を表し、価格と累積出来高の時刻を個別に扱います。
type futureHistoryQuote struct {
	Symbol            string   `json:"Symbol"`
	CurrentPrice      *float64 `json:"CurrentPrice"`
	CurrentPriceTime  string   `json:"CurrentPriceTime"`
	TradingVolume     *float64 `json:"TradingVolume"`
	TradingVolumeTime string   `json:"TradingVolumeTime"`
}

// futureHistoryCandle は、実際に観測した価格と出来高差分から形成した足です。
// VolumeComplete は、その足の出来高基準が取得済みで途中のリセットがないことを示します。
type futureHistoryCandle struct {
	Time           time.Time `json:"time"`
	Open           float64   `json:"open"`
	High           float64   `json:"high"`
	Low            float64   `json:"low"`
	Close          float64   `json:"close"`
	Volume         float64   `json:"volume"`
	VolumeComplete bool      `json:"volumeComplete"`
	Closed         bool      `json:"closed"`
}

// futureHistoryCandleUpdate は、公開する足の間隔、連番、更新後の値です。
// Index は足を実際に形成した順のゼロ始まりで、空の分には割り当てません。
type futureHistoryCandleUpdate struct {
	Interval int
	Index    int
	Candle   futureHistoryCandle
}

// futureHistoryCandles は、単一の書き込み処理から操作する立会内の集計状態です。
// 全履歴を読み直さず、現在の一分足と五分足に属する最大五本だけを保持します。
type futureHistoryCandles struct {
	startsAt  time.Time
	endsAt    time.Time
	advanced  time.Time
	priceAt   time.Time
	volumeAt  time.Time
	volume    float64
	hasVolume bool

	minute          futureHistoryCandle
	minuteExists    bool
	minuteIndex     int
	minuteVolume    float64
	minuteComplete  bool
	minuteHasVolume bool

	five        futureHistoryCandle
	fiveIndex   int
	fiveMinutes [5]futureHistoryCandle
	fivePresent [5]bool
}

// newFutureHistoryCandles は、指定した立会の分足集計器を作成します。
//
// 引数:
//   - startsAt time.Time: 価格を集計し始める立会開始日時。
//   - endsAt time.Time: 最終足を確定する立会終了日時。
//
// 返り値:
//   - *futureHistoryCandles: 履歴を持たない初期状態の集計器。
func newFutureHistoryCandles(startsAt, endsAt time.Time) *futureHistoryCandles {
	return &futureHistoryCandles{startsAt: startsAt, endsAt: endsAt, minuteIndex: -1, fiveIndex: -1}
}

// Apply は、今回の受信値だけを使って該当する一分足と五分足を更新します。
// 同じ秒の価格変化を取り込み、前立会の価格と確定済みの分への遅着は無視します。
//
// 引数:
//   - quote futureHistoryQuote: 受信した価格と累積出来高。
//   - receivedAt time.Time: アプリが受信した日時。
//
// 返り値:
//   - []futureHistoryCandleUpdate: 確定または更新された足。生データの保存は行いません。
func (c *futureHistoryCandles) Apply(quote futureHistoryQuote, receivedAt time.Time) []futureHistoryCandleUpdate {
	advanceAt := receivedAt
	if receivedAt.Equal(c.endsAt) {
		advanceAt = receivedAt.Add(-time.Nanosecond)
	}
	updates := c.Advance(advanceAt)
	if receivedAt.Before(c.startsAt) {
		c.applyVolume(quote, receivedAt, time.Time{})
		return updates
	}
	if receivedAt.After(c.endsAt) || !c.prepareMinute(receivedAt) {
		return updates
	}

	// ----------------------------------------
	// 出来高は価格と別に処理し、同値の板更新による重複計上を防ぎます。
	volumeChanged := c.applyVolume(quote, receivedAt, c.minute.Time)
	priceAt, err := time.Parse(time.RFC3339Nano, quote.CurrentPriceTime)
	priceChanged := err == nil && quote.CurrentPrice != nil && futureHistoryFinite(*quote.CurrentPrice) &&
		*quote.CurrentPrice > 0 && !priceAt.After(receivedAt) && !priceAt.Before(c.priceAt) &&
		c.bucketAt(priceAt).Equal(c.minute.Time)
	if priceChanged {
		price := *quote.CurrentPrice
		if !c.minuteExists {
			c.minuteExists = true
			c.minuteIndex++
			c.minute.Open, c.minute.High, c.minute.Low = price, price, price
		}
		c.minute.High = math.Max(c.minute.High, price)
		c.minute.Low = math.Min(c.minute.Low, price)
		c.minute.Close = price
		c.priceAt = priceAt
	}
	if c.minuteExists && (priceChanged || volumeChanged) {
		c.minute.Volume = c.minuteVolume
		c.minute.VolumeComplete = c.minuteHasVolume && c.minuteComplete
		updates = append(updates, c.minuteUpdate(), c.updateFive(receivedAt))
	}
	if receivedAt.Equal(c.endsAt) {
		updates = append(updates, c.Advance(receivedAt)...)
	}
	return updates
}

// Advance は、受信が途切れた場合も時刻境界で形成済みの足を確定します。
// 空の時間帯に足を補完せず、確定済みの足は変更しません。
//
// 引数:
//   - now time.Time: 確定判定に使う現在日時。
//
// 返り値:
//   - []futureHistoryCandleUpdate: 新たに確定した足と対応する五分足。
func (c *futureHistoryCandles) Advance(now time.Time) []futureHistoryCandleUpdate {
	if now.After(c.advanced) {
		c.advanced = now
	}
	var updates []futureHistoryCandleUpdate
	if c.minuteExists && !c.minute.Closed && !now.Before(c.intervalEnd(c.minute.Time, time.Minute)) {
		c.minute.Closed = true
		updates = append(updates, c.minuteUpdate(), c.updateFive(now))
	}
	if c.fiveIndex >= 0 && !c.five.Closed && !now.Before(c.intervalEnd(c.five.Time, 5*time.Minute)) {
		c.five.Closed = true
		updates = append(updates, futureHistoryCandleUpdate{Interval: 5, Index: c.fiveIndex, Candle: c.five})
	}
	return updates
}

// prepareMinute は、受信時刻に対応する未確定の一分足の作業領域を用意します。
//
// 引数:
//   - receivedAt time.Time: アプリの受信日時。
//
// 返り値:
//   - bool: 今回の分が未確定で更新できる場合は真。
func (c *futureHistoryCandles) prepareMinute(receivedAt time.Time) bool {
	bucket := c.bucketAt(receivedAt)
	if bucket.IsZero() || bucket.Before(c.minute.Time) || !c.advanced.Before(c.intervalEnd(bucket, time.Minute)) {
		return false
	}
	if !bucket.Equal(c.minute.Time) {
		c.minute = futureHistoryCandle{Time: bucket}
		c.minuteExists = false
		c.minuteVolume = 0
		c.minuteComplete = true
		c.minuteHasVolume = false
	}
	return !c.minute.Closed
}

// applyVolume は、累積出来高の差分を現在の分だけに加算します。
// 遅着分の差分は捨てて基準だけ進め、初回値と減少時は基準を取り直します。
//
// 引数:
//   - quote futureHistoryQuote: 累積出来高とその観測日時。
//   - receivedAt time.Time: アプリの受信日時。
//   - minute time.Time: 加算する分。ゼロ値は開始前の基準取得だけを表します。
//
// 返り値:
//   - bool: 現在の分の出来高または完全性を更新した場合は真。
func (c *futureHistoryCandles) applyVolume(quote futureHistoryQuote, receivedAt, minute time.Time) bool {
	if quote.TradingVolume == nil || !futureHistoryFinite(*quote.TradingVolume) || *quote.TradingVolume < 0 {
		return false
	}
	volumeAt, err := time.Parse(time.RFC3339Nano, quote.TradingVolumeTime)
	if err != nil || volumeAt.After(receivedAt) || volumeAt.Before(c.volumeAt) || volumeAt.After(c.endsAt) {
		return false
	}
	volume := *quote.TradingVolume
	delta, complete := 0.0, c.hasVolume && volume >= c.volume
	if complete {
		delta = volume - c.volume
	}
	c.hasVolume, c.volume, c.volumeAt = true, volume, volumeAt
	if minute.IsZero() || !c.bucketAt(volumeAt).Equal(minute) {
		return false
	}
	c.minuteVolume += delta
	c.minuteHasVolume = true
	c.minuteComplete = c.minuteComplete && complete
	return true
}

// bucketAt は、立会内の観測時刻を一分足の開始日時へ変換します。
// 立会終了ちょうどの観測は最終の一分へ含めます。
//
// 引数:
//   - at time.Time: 分類する観測日時。
//
// 返り値:
//   - time.Time: 対応する分の開始日時。立会外はゼロ値。
func (c *futureHistoryCandles) bucketAt(at time.Time) time.Time {
	if at.Before(c.startsAt) || at.After(c.endsAt) {
		return time.Time{}
	}
	if at.Equal(c.endsAt) {
		at = at.Add(-time.Nanosecond)
	}
	return c.startsAt.Add(at.Sub(c.startsAt) / time.Minute * time.Minute)
}

// intervalEnd は、足の終了を立会終了日時で打ち切って返します。
//
// 引数:
//   - start time.Time: 足の開始日時。
//   - interval time.Duration: 足の時間幅。
//
// 返り値:
//   - time.Time: 足を確定する日時。
func (c *futureHistoryCandles) intervalEnd(start time.Time, interval time.Duration) time.Time {
	end := start.Add(interval)
	if end.After(c.endsAt) {
		return c.endsAt
	}
	return end
}

// minuteUpdate は、現在の一分足を値として複製して公開用の更新にします。
//
// 引数:
//   - なし。
//
// 返り値:
//   - futureHistoryCandleUpdate: 一分足の連番と値。
func (c *futureHistoryCandles) minuteUpdate() futureHistoryCandleUpdate {
	return futureHistoryCandleUpdate{Interval: 1, Index: c.minuteIndex, Candle: c.minute}
}

// updateFive は、今回の一分足が属する最大五本だけから五分足を再集計します。
//
// 引数:
//   - now time.Time: 五分足の確定判定に使う日時。
//
// 返り値:
//   - futureHistoryCandleUpdate: 五分足の連番と値。
func (c *futureHistoryCandles) updateFive(now time.Time) futureHistoryCandleUpdate {
	start := c.startsAt.Add(c.minute.Time.Sub(c.startsAt) / (5 * time.Minute) * (5 * time.Minute))
	if !start.Equal(c.five.Time) {
		c.fiveIndex++
		c.fiveMinutes = [5]futureHistoryCandle{}
		c.fivePresent = [5]bool{}
	}
	slot := int(c.minute.Time.Sub(start) / time.Minute)
	c.fiveMinutes[slot], c.fivePresent[slot] = c.minute, true
	candle := futureHistoryCandle{Time: start, VolumeComplete: true, Closed: !now.Before(c.intervalEnd(start, 5*time.Minute))}
	first := true
	for index, minute := range c.fiveMinutes {
		if !c.fivePresent[index] {
			continue
		}
		if first {
			candle.Open, candle.High, candle.Low = minute.Open, minute.High, minute.Low
			first = false
		}
		candle.High = math.Max(candle.High, minute.High)
		candle.Low = math.Min(candle.Low, minute.Low)
		candle.Close = minute.Close
		candle.Volume += minute.Volume
		candle.VolumeComplete = candle.VolumeComplete && minute.VolumeComplete
	}
	c.five = candle
	return futureHistoryCandleUpdate{Interval: 5, Index: c.fiveIndex, Candle: c.five}
}

// futureHistoryFinite は、足へ保存できる有限数かを確認します。
//
// 引数:
//   - value float64: 検証する数値。
//
// 返り値:
//   - bool: 非数および無限大でない場合は真。
func futureHistoryFinite(value float64) bool {
	return !math.IsNaN(value) && !math.IsInf(value, 0)
}
