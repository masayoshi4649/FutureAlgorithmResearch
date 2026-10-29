package main

import (
	"fmt"
	"math"
	"strconv"
	"time"
)

type displayMode struct {
	Interval string
	Price    string
	Minutes  int
}

type timeBar struct {
	Start, End             float64
	Open, High, Low, Close *float64
	State                  []any
}

type barCollector struct {
	Bars                      []timeBar
	Start, End, Aligned, Span float64
	Price                     string
	PriceInput, StateInput    int64
}

// parseDisplayMode は表示時間幅と価格列を検証します。
//
// 引数: interval/price(string)。返り値: displayModeとerror。省略はraw/lastです。
func parseDisplayMode(interval, price string) (displayMode, error) {
	if interval == "" {
		interval = "raw"
	}
	if price == "" {
		price = "last"
	}
	m := displayMode{Interval: interval, Price: price}
	if interval != "raw" {
		if interval != "1" && interval != "5" && interval != "15" {
			return m, fmt.Errorf("intervalはraw/1/5/15です")
		}
		m.Minutes, _ = strconv.Atoi(interval)
	}
	if price != "last" && price != "mid" && price != "bid" && price != "ask" {
		return m, fmt.Errorf("priceはlast/mid/bid/askです")
	}
	return m, nil
}

// newBarCollector は場固定の時計分へ整列した小さな集計器を作ります。
//
// 引数: start/end(float64、ミリ秒)、mode(displayMode)。返り値: *barCollector。
func newBarCollector(start, end float64, mode displayMode) *barCollector {
	span := float64(mode.Minutes) * 60000
	aligned := math.Floor(start/span) * span
	b := &barCollector{Start: start, End: end, Aligned: aligned, Span: span, Price: mode.Price}
	for left := aligned; left < end; left += span {
		b.Bars = append(b.Bars, timeBar{Start: math.Max(left, start), End: math.Min(left+span, end)})
	}
	return b
}

// index は境界上の原行を右の区間へ、場終端だけを最後の区間へ割り当てます。
//
// 引数: at(float64、ミリ秒)。返り値: int。不正又は場外は-1です。
func (b *barCollector) index(at float64) int {
	if !finite(at) || at < b.Start || at > b.End {
		return -1
	}
	i := int(math.Floor((at - b.Aligned) / b.Span))
	if at == b.End {
		i = len(b.Bars) - 1
	}
	if i < 0 || i >= len(b.Bars) {
		return -1
	}
	return i
}

// indexTime は原時計のナノ秒を保ち、丸めで分境界を跨がない添字を返します。
//
// 引数: at(time.Time)。返り値: int。原時計がない補助行はindexで扱います。
func (b *barCollector) indexTime(at time.Time) int {
	n := at.UnixNano()
	start, end := int64(b.Start)*int64(time.Millisecond), int64(b.End)*int64(time.Millisecond)
	if n < start || n > end {
		return -1
	}
	if n == end {
		return len(b.Bars) - 1
	}
	return int((n - int64(b.Aligned)*int64(time.Millisecond)) / int64(b.Span*float64(time.Millisecond)))
}

// addQuote は縮約前の原板から選択価格のOHLCを更新します。
//
// 引数: q(marketQuote)。返り値: なし。欠測を価格0へ変換しません。
func (b *barCollector) addQuote(q marketQuote) {
	b.PriceInput++
	i := b.indexTime(q.At)
	if i < 0 {
		return
	}
	value := q.Last
	switch b.Price {
	case "bid":
		value = q.Bid
	case "ask":
		value = q.Ask
	case "mid":
		value = nil
		if q.Bid != nil && q.Ask != nil && *q.Bid < *q.Ask {
			v := (*q.Bid + *q.Ask) / 2
			value = &v
		}
	}
	if value == nil {
		return
	}
	v := *value
	bar := &b.Bars[i]
	if bar.Open == nil {
		open, high, low := v, v, v
		bar.Open, bar.High, bar.Low = &open, &high, &low
	}
	if v > *bar.High {
		high := v
		bar.High = &high
	}
	if v < *bar.Low {
		low := v
		bar.Low = &low
	}
	bar.Close = &v
}

// addState は同時計の原行順を変えず、区間の最後の会計状態だけを保持します。
//
// 引数: row([]any、既存state_columns順)。返り値: なし。nullの最終状態も保持します。
func (b *barCollector) addState(row []any) {
	b.addStateAt(row, time.Time{})
}

// addStateAt は原時計がある状態を正しい分境界へ割り当てます。
//
// 引数: row([]any)、at(time.Time、0値は表示用ミリ秒を使用)。返り値: なし。
func (b *barCollector) addStateAt(row []any, at time.Time) {
	b.StateInput++
	stamp, _ := numeric(row[0])
	i := b.index(stamp)
	if !at.IsZero() {
		i = b.indexTime(at)
	}
	if i >= 0 {
		b.Bars[i].State = row
	}
}

// result は表示と重なる完全区間のOHLCと、その区間末の状態を返します。
//
// 引数: from/to(float64、ミリ秒)、includeStates(bool)。
// 返り値: candles/states([][]any)。約定由来の既知会計は持越し、明示nullは補完しません。
func (b *barCollector) result(from, to float64, includeStates bool) ([][]any, [][]any) {
	candles, states := [][]any{}, [][]any{}
	var previous []any
	var preceding []any
	for _, bar := range b.Bars {
		if bar.State != nil {
			previous = bar.State
		}
		var row []any
		if includeStates {
			row = []any{bar.End, int64(0), nil, nil, nil, nil, nil}
			if previous != nil {
				copy(row, previous)
				row[0] = bar.End
			}
		}
		if bar.End <= from {
			preceding = row
			continue
		}
		if bar.Start >= to {
			break
		}
		if len(candles) == 0 && preceding != nil {
			states = append(states, preceding)
		}
		candles = append(candles, []any{bar.Start, bar.End, floatValue(bar.Open), floatValue(bar.High), floatValue(bar.Low), floatValue(bar.Close)})
		if row != nil {
			states = append(states, row)
		}
	}
	return candles, states
}
