package main

import (
	"errors"
	"math"
	"sort"
)

type interval struct{ End, Area, Known float64 }
type Average struct {
	Start, Time, Value float64
	Good, Started      bool
	Intervals          []interval
}

// quoteOK は価格だけで正常な返済可能気配を判定します。
//
// 引数: q(Quote)。返り値: bool。約定出来高やLastの更新時刻を気配品質へ代用しません。
func quoteOK(q Quote) bool { return finite(q.Bid) && finite(q.Ask) && q.Bid > 0 && q.Ask > q.Bid }

// finite は有限な数値を判定します。
//
// 引数: x(float64)。返り値: bool。
func finite(x float64) bool { return !math.IsNaN(x) && !math.IsInf(x, 0) }

// appendInterval は過去値を最大120秒保持し、未知区間の面積を作りません。
//
// 引数: end(float64)、good(bool)。返り値: なし。同時刻更新の経過重みは0です。
func (a *Average) appendInterval(end float64, good bool) {
	start, area, known := a.Start, 0., 0.
	if n := len(a.Intervals); n > 0 {
		last := a.Intervals[n-1]
		start, area, known = last.End, last.Area, last.Known
	}
	if end <= start {
		return
	}
	if good {
		area += (end - start) * a.Value
		known += end - start
	}
	a.Intervals = append(a.Intervals, interval{end, area, known})
}

// Add はその行以前の時間積分を確定し、現在板を次区間の保持値へ設定します。
//
// 引数: q(Quote)。返り値: errorは時計巻戻り。将来の次板を現在計算へ用いません。
func (a *Average) Add(q Quote) error {
	if !finite(q.Time) || a.Started && q.Time < a.Time {
		return errors.New("移動平均の時計が逆行しました")
	}
	if !a.Started {
		a.Start = q.Time
		a.Time = q.Time
		a.Started = true
	}
	if q.Time > a.Time {
		if a.Good {
			a.appendInterval(math.Min(q.Time, a.Time+120), true)
		}
		a.appendInterval(q.Time, false)
	}
	a.Time = q.Time
	a.Good = quoteOK(q)
	if a.Good {
		a.Value = (q.Bid + q.Ask) / 2
	}
	return nil
}

// integral は記録済みの任意の過去時刻の価格面積と既知秒数を返します。
//
// 引数: at(float64)。返り値: float64二つは累積価格面積と既知秒数、boolは範囲内です。
func (a *Average) integral(at float64) (float64, float64, bool) {
	if !a.Started || at < a.Start || at > a.Time {
		return 0, 0, false
	}
	if at == a.Start {
		return 0, 0, true
	}
	i := sort.Search(len(a.Intervals), func(i int) bool { return a.Intervals[i].End >= at })
	if i == len(a.Intervals) {
		return 0, 0, false
	}
	end := a.Intervals[i]
	start, area, known := a.Start, 0., 0.
	if i > 0 {
		prior := a.Intervals[i-1]
		start, area, known = prior.End, prior.Area, prior.Known
	}
	fraction := (at - start) / (end.End - start)
	return area + (end.Area-area)*fraction, known + (end.Known-known)*fraction, true
}

// mean は完全な既知窓に限り時間加重平均を返します。
//
// 引数: at/window(float64)。返り値: float64は平均、boolは全秒既知です。
func (a *Average) mean(at, window float64) (float64, bool) {
	x, k, good := a.integral(at)
	y, j, prior := a.integral(at - window)
	if !good || !prior || math.Abs(k-j-window) > 1e-6 {
		return 0, false
	}
	return (x - y) / window, true
}

// Get は移動平均の過去差を価格比のbp/分へ変換します。
//
// 引数: window/lag(float64)。返り値: Featureは確定済みの連続時間窓だけの傾きです。
func (a *Average) Get(window, lag float64) Feature {
	now, good := a.mean(a.Time, window)
	prior, old := a.mean(a.Time-lag, window)
	if !good || !old || prior <= 0 || !a.Good {
		return Feature{}
	}
	return Feature{true, now, prior, 10000 * (now/prior - 1) * 60 / lag}
}
