package main

import "math"

// bbPoint は、標本標準偏差を用いたボリンジャーバンドです。
type bbPoint struct{ Mid, SD, Upper, Lower, Width float64 }

// dmiPoint は、単純合計による方向性指数と単純平均 ADX です。
type dmiPoint struct {
	Plus, Minus, ADX, TRMean float64
	ADXReady                 bool
}

// macdPeriods は、短期 EMA・長期 EMA・シグナル EMA の本数です。
type macdPeriods struct{ Fast, Slow, Signal int }

// macdPoint は、EMA 差・シグナル・ヒストグラムです。
type macdPoint struct{ MACD, Signal, Hist float64 }

// indicatorPoint は、確定足だけから得た同時点の指標を保持します。
// map に存在しない期間の指標は準備不足であり、売買へ使用しません。
type indicatorPoint struct {
	Bar           Candle
	SMA, EMA, RSI map[int]float64
	BB            map[int]bbPoint
	DMI           map[int]dmiPoint
	MACD          map[macdPeriods]macdPoint
}

// indicatorSeries は、単一時間軸の因果的な指標計算と確定履歴を管理します。
type indicatorSeries struct {
	points                 []indicatorPoint
	closes                 []float64
	bars                   []Candle
	emas                   map[int]*emaState
	rsis                   map[int]*rsiState
	macds                  map[macdPeriods]*macdState
	trs, plusDMs, minusDMs []float64
	dxs                    map[int][]float64
}

// emaState は、n 本の単純平均を初期値とする指数平滑移動平均です。
type emaState struct {
	n, count   int
	sum, value float64
}

// rsiState は、n 差分の単純平均で初期化する Wilder 型 RSI です。
type rsiState struct {
	n, count             int
	previous, gain, loss float64
	hasPrevious          bool
}

// macdState は、独立した二つの EMA と差の EMA を保持します。
type macdState struct{ fast, slow, signal emaState }

// newIndicatorSeries は、足系列ごとの未準備状態を生成します。
// 引数: なし。
// 返り値: *indicatorSeries 型の新規計算器。
func newIndicatorSeries() *indicatorSeries {
	s := &indicatorSeries{emas: map[int]*emaState{}, rsis: map[int]*rsiState{}, macds: map[macdPeriods]*macdState{}, dxs: map[int][]float64{}}
	s.emas[8] = &emaState{n: 8}
	for _, n := range []int{4, 6, 9, 10, 14} {
		s.rsis[n] = &rsiState{n: n}
	}
	for _, p := range []macdPeriods{{4, 8, 3}, {5, 10, 3}, {3, 6, 2}, {6, 13, 5}, {12, 26, 9}} {
		s.macds[p] = &macdState{fast: emaState{n: p.Fast}, slow: emaState{n: p.Slow}, signal: emaState{n: p.Signal}}
	}
	return s
}

// push は、確定した値を指数平均へ追加します。
// 引数: value は float64 型の確定観測値。
// 返り値: float64 型の EMA と bool 型の準備完了状態。
func (e *emaState) push(value float64) (float64, bool) {
	e.count++
	if e.count <= e.n {
		e.sum += value
		if e.count == e.n {
			e.value = e.sum / float64(e.n)
		}
		return e.value, e.count == e.n
	}
	e.value += 2 / float64(e.n+1) * (value - e.value)
	return e.value, true
}

// push は、確定終値を Wilder 型 RSI へ追加します。
// 引数: close は float64 型の確定終値。
// 返り値: float64 型の RSI と bool 型の準備完了状態。
func (r *rsiState) push(close float64) (float64, bool) {
	if !r.hasPrevious {
		r.previous = close
		r.hasPrevious = true
		return 0, false
	}
	difference := close - r.previous
	r.previous = close
	gain, loss := math.Max(difference, 0), math.Max(-difference, 0)
	r.count++
	if r.count <= r.n {
		r.gain += gain
		r.loss += loss
		if r.count < r.n {
			return 0, false
		}
		r.gain /= float64(r.n)
		r.loss /= float64(r.n)
	} else {
		r.gain = (r.gain*float64(r.n-1) + gain) / float64(r.n)
		r.loss = (r.loss*float64(r.n-1) + loss) / float64(r.n)
	}
	if r.gain == 0 && r.loss == 0 {
		return 50, true
	}
	if r.loss == 0 {
		return 100, true
	}
	return 100 - 100/(1+r.gain/r.loss), true
}

// push は、確定値を MACD 計算器へ追加します。
// 引数: close は float64 型の確定終値。
// 返り値: macdPoint 型の MACD と bool 型の準備完了状態。
func (m *macdState) push(close float64) (macdPoint, bool) {
	fast, fr := m.fast.push(close)
	slow, sr := m.slow.push(close)
	if !fr || !sr {
		return macdPoint{}, false
	}
	value := fast - slow
	signal, ready := m.signal.push(value)
	return macdPoint{MACD: value, Signal: signal, Hist: value - signal}, ready
}

// meanLast は、末尾 n 個の単純平均を計算します。
// 引数: values は []float64 型の観測列、n は int 型の期間。
// 返り値: float64 型の単純平均と bool 型の準備完了状態。
func meanLast(values []float64, n int) (float64, bool) {
	if n <= 0 || len(values) < n {
		return 0, false
	}
	sum := 0.0
	for _, v := range values[len(values)-n:] {
		sum += v
	}
	return sum / float64(n), true
}

// sampleSDLast は、末尾 n 個の標本標準偏差を二段階計算で求めます。
// 引数: values は []float64 型の観測列、n は int 型の期間。
// 返り値: float64 型の標本標準偏差と bool 型の準備完了状態。
func sampleSDLast(values []float64, n int) (float64, bool) {
	mean, ready := meanLast(values, n)
	if !ready || n < 2 {
		return 0, false
	}
	sum := 0.0
	for _, v := range values[len(values)-n:] {
		d := v - mean
		sum += d * d
	}
	return math.Sqrt(sum / float64(n-1)), true
}

// push は、確定足を追加し、その時点で計算できる指標だけを返します。
// 引数: c は Candle 型の確定足。
// 返り値: indicatorPoint 型の因果的な指標スナップショット。
func (s *indicatorSeries) push(c Candle) indicatorPoint {
	p := indicatorPoint{Bar: c, SMA: map[int]float64{}, EMA: map[int]float64{}, RSI: map[int]float64{}, BB: map[int]bbPoint{}, DMI: map[int]dmiPoint{}, MACD: map[macdPeriods]macdPoint{}}
	s.closes = append(s.closes, c.Close)
	for _, n := range []int{2, 3, 4, 5, 6, 8, 10, 12} {
		if value, ready := meanLast(s.closes, n); ready {
			p.SMA[n] = value
		}
	}
	for n, state := range s.emas {
		if value, ready := state.push(c.Close); ready {
			p.EMA[n] = value
		}
	}
	for n, state := range s.rsis {
		if value, ready := state.push(c.Close); ready {
			p.RSI[n] = value
		}
	}
	for periods, state := range s.macds {
		if value, ready := state.push(c.Close); ready {
			p.MACD[periods] = value
		}
	}

	// ----------------------------------------
	for _, n := range []int{6, 10, 12} {
		mean, ready := meanLast(s.closes, n)
		if !ready {
			continue
		}
		sd, _ := sampleSDLast(s.closes, n)
		p.BB[n] = bbPoint{Mid: mean, SD: sd, Upper: mean + 2*sd, Lower: mean - 2*sd, Width: 4 * sd}
	}
	if len(s.bars) > 0 {
		previous := s.bars[len(s.bars)-1]
		tr := math.Max(c.High-c.Low, math.Max(math.Abs(c.High-previous.Close), math.Abs(c.Low-previous.Close)))
		up, down := c.High-previous.High, previous.Low-c.Low
		plus, minus := 0.0, 0.0
		if up > 0 && up > down {
			plus = up
		}
		if down > 0 && down > up {
			minus = down
		}
		s.trs = append(s.trs, tr)
		s.plusDMs = append(s.plusDMs, plus)
		s.minusDMs = append(s.minusDMs, minus)
		for _, n := range []int{6, 8, 10} {
			trMean, ready := meanLast(s.trs, n)
			if !ready {
				continue
			}
			plusMean, _ := meanLast(s.plusDMs, n)
			minusMean, _ := meanLast(s.minusDMs, n)
			d := dmiPoint{TRMean: trMean}
			if trMean > 0 {
				d.Plus = 100 * plusMean / trMean
				d.Minus = 100 * minusMean / trMean
			}
			dx := 0.0
			if d.Plus+d.Minus > 0 {
				dx = 100 * math.Abs(d.Plus-d.Minus) / (d.Plus + d.Minus)
			}
			s.dxs[n] = append(s.dxs[n], dx)
			d.ADX, d.ADXReady = meanLast(s.dxs[n], n)
			p.DMI[n] = d
		}
	}
	s.bars = append(s.bars, c)
	s.points = append(s.points, p)
	return p
}

// latest は、確定済み指標の末尾から指定した位置を参照します。
// 引数: back は int 型の遡及本数であり、0 が最新。
// 返り値: *indicatorPoint 型の参照。確定足が不足する場合は nil。
func (s *indicatorSeries) latest(back int) *indicatorPoint {
	i := len(s.points) - 1 - back
	if i < 0 || i >= len(s.points) {
		return nil
	}
	return &s.points[i]
}

// candleAggregator は、欠測を埋めずに確定した連続分足だけを上位足へ集計します。
type candleAggregator struct {
	minutes int
	current Candle
	count   int
	active  bool
}

// push は、全構成分足が確定したときだけ上位足を公開します。
// 引数: c は Candle 型の確定1分足。
// 返り値: *Candle 型の確定上位足。構成不足・未確定の場合は nil。
func (a *candleAggregator) push(c Candle) *Candle {
	const minuteNS = int64(60_000_000_000)
	width := int64(a.minutes) * minuteNS
	start := c.StartNS / width * width
	if !a.active || a.current.StartNS != start {
		a.current = Candle{StartNS: start, EndNS: start + width, Open: c.Open, High: c.High, Low: c.Low, Close: c.Close, VolumeComplete: true}
		a.count = 0
		a.active = true
	}
	if c.StartNS != start+int64(a.count)*minuteNS || c.EndNS != c.StartNS+minuteNS {
		a.active = false
		return nil
	}
	if a.count > 0 {
		a.current.High = math.Max(a.current.High, c.High)
		a.current.Low = math.Min(a.current.Low, c.Low)
	}
	a.current.Close = c.Close
	a.current.Volume += c.Volume
	a.current.VolumeComplete = a.current.VolumeComplete && c.VolumeComplete
	a.current.SourceLine = c.SourceLine
	a.current.Samples += c.Samples
	a.count++
	if a.count == a.minutes {
		out := a.current
		a.active = false
		return &out
	}
	return nil
}

// technicalEngine は、同一場内の1分足と3分・5分・15分確定足を管理します。
type technicalEngine struct {
	series      map[int]*indicatorSeries
	aggregators map[int]*candleAggregator
	lastStartNS int64
	hasLast     bool
}

// newTechnicalEngine は、前セッションの履歴を持たない指標器を作成します。
// 引数: なし。
// 返り値: *technicalEngine 型の新しい指標器。
func newTechnicalEngine() *technicalEngine {
	e := &technicalEngine{series: map[int]*indicatorSeries{}, aggregators: map[int]*candleAggregator{}}
	for _, tf := range []int{1, 3, 5, 15} {
		e.series[tf] = newIndicatorSeries()
		if tf > 1 {
			e.aggregators[tf] = &candleAggregator{minutes: tf}
		}
	}
	return e
}

// push は、確定1分足と同時点までに確定した上位足の状態を更新します。
// 引数: c は Candle 型の確定1分足。時刻は昇順である必要があります。
// 返り値: bool 型の受付結果。重複足・逆行足は false で無視します。
func (e *technicalEngine) push(c Candle) bool {
	if e.hasLast && c.StartNS <= e.lastStartNS {
		return false
	}
	e.series[1].push(c)
	for _, tf := range []int{3, 5, 15} {
		if complete := e.aggregators[tf].push(c); complete != nil {
			e.series[tf].push(*complete)
		}
	}
	e.lastStartNS = c.StartNS
	e.hasLast = true
	return true
}
