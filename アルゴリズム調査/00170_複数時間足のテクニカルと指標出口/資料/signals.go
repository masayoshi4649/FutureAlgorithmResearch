package main

import (
	"fmt"
	"math"
)

// CandidateConfig は、事前固定された独立候補の定義です。
type CandidateConfig struct {
	ID                                string `json:"id"`
	Family                            int    `json:"family"`
	Variant                           string `json:"variant"`
	MediumMinutes                     int    `json:"medium_minutes"`
	LongMinutes                       int    `json:"long_minutes"`
	MediumFast, MediumSlow            int
	LongFast, LongSlow, LongSlopeBack int
	MediumPeriod, MediumLookback      int
	MediumMACD                        macdPeriods
	Quantity                          int     `json:"quantity"`
	IndicatorExit                     bool    `json:"indicator_exit"`
	ExitMode                          string  `json:"exit_mode"`
	HardStopRatio                     float64 `json:"hard_stop_ratio"`
	TrailActivationRatio              float64 `json:"trail_activation_ratio"`
	TrailDistanceRatio                float64 `json:"trail_distance_ratio"`
	FloorActivationRatio              float64 `json:"floor_activation_ratio"`
	FloorRatio                        float64 `json:"floor_ratio"`
}

// CandidateConfigs は、12 仮説×2 時間軸×3 出口の72候補を返します。
// 引数: なし。
// 返り値: []CandidateConfig 型の固定候補。I は指標出口併用、T はトレール単独対照、F は I と早期利益床。
func CandidateConfigs() []CandidateConfig {
	result := make([]CandidateConfig, 0, 72)
	for family := 1; family <= 12; family++ {
		for _, variant := range []string{"A", "B"} {
			c := CandidateConfig{Family: family, Variant: variant, Quantity: 10, HardStopRatio: 0.003, TrailActivationRatio: 0.001, TrailDistanceRatio: 0.0005}
			if variant == "A" {
				c.MediumMinutes = 3
				c.LongMinutes = 5
				c.MediumFast = 5
				c.MediumSlow = 10
				c.LongFast = 6
				c.LongSlow = 12
				c.LongSlopeBack = 3
				c.MediumPeriod = 10
				c.MediumLookback = 5
				c.MediumMACD = macdPeriods{5, 10, 3}
			} else {
				c.MediumMinutes = 5
				c.LongMinutes = 15
				c.MediumFast = 3
				c.MediumSlow = 6
				c.LongFast = 2
				c.LongSlow = 4
				c.LongSlopeBack = 1
				c.MediumPeriod = 6
				c.MediumLookback = 3
				c.MediumMACD = macdPeriods{3, 6, 2}
			}
			for _, exitMode := range []string{"I", "T", "F"} {
				c.ExitMode = exitMode
				c.IndicatorExit = exitMode != "T"
				c.FloorActivationRatio, c.FloorRatio = 0, 0
				if exitMode == "F" {
					c.FloorActivationRatio, c.FloorRatio = 0.0004, 0.0001
				}
				c.ID = fmt.Sprintf("F%02d%s_%s", family, variant, exitMode)
				result = append(result, c)
			}
		}
	}
	return result
}

// TechnicalStrategy は、場内だけの指標状態と固定候補を管理します。
type TechnicalStrategy struct {
	Config       CandidateConfig
	engine       *technicalEngine
	sessionOpen  float64
	lastBarEndNS int64
}

// NewTechnicalStrategy は、未準備の候補状態を生成します。
// 引数: config は CandidateConfig 型の固定定義、sessionOpen は float64 型の場内始値。
// 返り値: *TechnicalStrategy 型の新しい戦略。sessionOpen が0なら最初の確定足始値で設定します。
func NewTechnicalStrategy(config CandidateConfig, sessionOpen float64) *TechnicalStrategy {
	return &TechnicalStrategy{Config: config, engine: newTechnicalEngine(), sessionOpen: sessionOpen}
}

// Reset は、場の切替時に全指標履歴と利益保護尺度を初期化します。
// 引数: sessionOpen は float64 型の新しい場の始値。
// 返り値: なし。
func (t *TechnicalStrategy) Reset(sessionOpen float64) {
	t.engine = newTechnicalEngine()
	t.sessionOpen = sessionOpen
	t.lastBarEndNS = 0
}

// OnBar は、確定足から入口と指標による支持失効を判断します。
// 引数: c は Candle 型の確定1分足、p は Position 型の約定済み建玉。
// 返り値: *Signal 型の目標枚数。条件なし・準備不足なら nil。
func (t *TechnicalStrategy) OnBar(c Candle, p Position) *Signal {
	if !t.engine.push(c) {
		return nil
	}
	return t.OnPreparedBar(c, p)
}

// OnPreparedBar は、同じ確定足まで更新済みの指標器を読み取り、売買を判断します。
// 引数: c は Candle 型の確定1分足、p は Position 型の約定済み建玉。
// 返り値: *Signal 型の目標枚数。足不一致・未来状態・重複判断・条件なしの場合は nil。
func (t *TechnicalStrategy) OnPreparedBar(c Candle, p Position) *Signal {
	latest := t.engine.series[1].latest(0)
	if latest == nil || latest.Bar != c || c.EndNS <= t.lastBarEndNS {
		return nil
	}
	if t.sessionOpen <= 0 {
		t.sessionOpen = c.Open
	}
	t.lastBarEndNS = c.EndNS
	buy, buyExit := t.evaluate(1)
	sell, sellExit := t.evaluate(-1)
	if p.Qty > 0 && p.Side != 0 {
		if !t.Config.IndicatorExit {
			return nil
		}
		if p.Side > 0 && sell && !buy {
			return &Signal{Target: -t.Config.Quantity, Reason: "反対指標の新規支持"}
		}
		if p.Side < 0 && buy && !sell {
			return &Signal{Target: t.Config.Quantity, Reason: "反対指標の新規支持"}
		}
		exit := p.Side > 0 && buyExit || p.Side < 0 && sellExit
		if exit {
			return &Signal{Target: 0, Reason: "指標支持失効"}
		}
		return nil
	}
	if buy && !sell {
		return &Signal{Target: t.Config.Quantity, Reason: fmt.Sprintf("H%02d買い支持", t.Config.Family)}
	}
	if sell && !buy {
		return &Signal{Target: -t.Config.Quantity, Reason: fmt.Sprintf("H%02d売り支持", t.Config.Family)}
	}
	return nil
}

// OnQuote は、実行可能気配の含み益を使い、保険損切りと利益トレールを判断します。
// 引数: q は Quote 型の現原行、p は Position 型の約定済み建玉。
// 返り値: *Signal 型の全返済指示。正常気配・建玉・条件がない場合は nil。
func (t *TechnicalStrategy) OnQuote(q Quote, p Position) *Signal {
	if p.Qty <= 0 || p.Side == 0 || q.Bid <= 0 || q.Ask <= q.Bid || p.Entry <= 0 {
		return nil
	}
	profit := q.Bid - p.Entry
	if p.Side < 0 {
		profit = p.Entry - q.Ask
	}
	threshold := -p.Entry * t.Config.HardStopRatio
	reason := "固定比率の保険損切り"
	if t.Config.FloorActivationRatio > 0 && p.PeakPoints >= p.Entry*t.Config.FloorActivationRatio {
		threshold, reason = p.Entry*t.Config.FloorRatio, "早期利益床"
	}
	if p.PeakPoints >= p.Entry*t.Config.TrailActivationRatio {
		trail := p.PeakPoints - p.Entry*t.Config.TrailDistanceRatio
		if trail > threshold {
			threshold, reason = trail, "利益トレール"
		}
	}
	if profit <= threshold {
		return &Signal{Target: 0, Reason: reason}
	}
	return nil
}

// directionalView は、売り側を鏡映して買い側と同じ不等式で判定する参照です。
type directionalView struct {
	p    *indicatorPoint
	side int
}

// close は、方向をそろえた終値を取得します。
// 引数: なし。
// 返り値: float64 型の終値。参照がない場合は NaN。
func (v directionalView) close() float64 {
	if v.p == nil {
		return math.NaN()
	}
	return float64(v.side) * v.p.Bar.Close
}

// low は、方向をそろえた安値を取得します。
// 引数: なし。
// 返り値: float64 型の安値。参照がない場合は NaN。
func (v directionalView) low() float64 {
	if v.p == nil {
		return math.NaN()
	}
	if v.side > 0 {
		return v.p.Bar.Low
	}
	return -v.p.Bar.High
}

// sma は、方向をそろえた単純移動平均を取得します。
// 引数: n は int 型の期間。
// 返り値: float64 型の平均と bool 型の準備完了状態。
func (v directionalView) sma(n int) (float64, bool) {
	if v.p == nil {
		return 0, false
	}
	value, ok := v.p.SMA[n]
	return float64(v.side) * value, ok
}

// ema は、方向をそろえた指数移動平均を取得します。
// 引数: n は int 型の期間。
// 返り値: float64 型の平均と bool 型の準備完了状態。
func (v directionalView) ema(n int) (float64, bool) {
	if v.p == nil {
		return 0, false
	}
	value, ok := v.p.EMA[n]
	return float64(v.side) * value, ok
}

// rsi は、方向をそろえた RSI を取得します。
// 引数: n は int 型の期間。
// 返り値: float64 型の RSI と bool 型の準備完了状態。
func (v directionalView) rsi(n int) (float64, bool) {
	if v.p == nil {
		return 0, false
	}
	value, ok := v.p.RSI[n]
	return 50 + float64(v.side)*(value-50), ok
}

// bb は、方向をそろえたボリンジャーバンドを取得します。
// 引数: n は int 型の期間。
// 返り値: bbPoint 型のバンドと bool 型の準備完了状態。
func (v directionalView) bb(n int) (bbPoint, bool) {
	if v.p == nil {
		return bbPoint{}, false
	}
	value, ok := v.p.BB[n]
	if v.side < 0 {
		value.Mid = -value.Mid
		upper := value.Upper
		value.Upper = -value.Lower
		value.Lower = -upper
	}
	return value, ok
}

// dmi は、方向をそろえた DMI を取得します。
// 引数: n は int 型の期間。
// 返り値: dmiPoint 型の DMI と bool 型の ADX 準備完了状態。
func (v directionalView) dmi(n int) (dmiPoint, bool) {
	if v.p == nil {
		return dmiPoint{}, false
	}
	value, ok := v.p.DMI[n]
	if v.side < 0 {
		value.Plus, value.Minus = value.Minus, value.Plus
	}
	return value, ok && value.ADXReady
}

// macd は、方向をそろえた MACD を取得します。
// 引数: periods は macdPeriods 型の EMA 期間組。
// 返り値: macdPoint 型の MACD と bool 型の準備完了状態。
func (v directionalView) macd(periods macdPeriods) (macdPoint, bool) {
	if v.p == nil {
		return macdPoint{}, false
	}
	value, ok := v.p.MACD[periods]
	value.MACD *= float64(v.side)
	value.Signal *= float64(v.side)
	value.Hist *= float64(v.side)
	return value, ok
}

// view は、指定した確定足を方向付きで参照します。
// 引数: minutes は int 型の時間軸、back は int 型の遡及本数、side は int 型の売買方向。
// 返り値: directionalView 型の指標参照。
func (t *TechnicalStrategy) view(minutes, back, side int) directionalView {
	return directionalView{p: t.engine.series[minutes].latest(back), side: side}
}

// trend は、長期足の価格位置・移動平均順序・15分傾きを判定します。
// 引数: side は int 型の判定方向。
// 返り値: bool 型のトレンド支持と bool 型の必要指標準備完了状態。
func (t *TechnicalStrategy) trend(side int) (bool, bool) {
	c := t.Config
	l, past := t.view(c.LongMinutes, 0, side), t.view(c.LongMinutes, c.LongSlopeBack, side)
	fast, fr := l.sma(c.LongFast)
	slow, sr := l.sma(c.LongSlow)
	previous, pr := past.sma(c.LongFast)
	ready := fr && sr && pr
	return ready && l.close() >= slow && fast > slow && fast > previous, ready
}

// evaluate は、独立した一つの仮説について入口と指標出口を判定します。
// 引数: side は int 型の売買方向であり、買いは1、売りは-1。
// 返り値: bool 型の新規支持と bool 型の指標出口条件。
func (t *TechnicalStrategy) evaluate(side int) (bool, bool) {
	c := t.Config
	s, sp, spp := t.view(1, 0, side), t.view(1, 1, side), t.view(1, 2, side)
	m, mp := t.view(c.MediumMinutes, 0, side), t.view(c.MediumMinutes, 1, side)
	l, lp := t.view(c.LongMinutes, 0, side), t.view(c.LongMinutes, c.LongSlopeBack, side)
	midFresh := m.p != nil && m.p.Bar.EndNS == t.lastBarEndNS
	tr, trReady := t.trend(side)
	opposite, oppositeReady := t.trend(-side)
	neutral := trReady && oppositeReady && !tr && !opposite
	e, er := s.ema(8)
	pe, per := sp.ema(8)
	r, rr := s.rsi(9)
	pr, prr := sp.rsi(9)
	mf, mfr := m.sma(c.MediumFast)
	ms, msr := m.sma(c.MediumSlow)
	pmf, pmfr := mp.sma(c.MediumFast)
	pms, pmsr := mp.sma(c.MediumSlow)
	lf, lfr := l.sma(c.LongFast)
	plf, plfr := lp.sma(c.LongFast)
	md, mdr := m.dmi(c.MediumPeriod)
	pmd, pmdr := mp.dmi(c.MediumPeriod)
	sm, smr := s.macd(macdPeriods{4, 8, 3})
	psm, psmr := sp.macd(macdPeriods{4, 8, 3})
	ppsm, ppsmr := spp.macd(macdPeriods{4, 8, 3})
	mm, mmr := m.macd(c.MediumMACD)
	pmm, pmmr := mp.macd(c.MediumMACD)
	sb, sbr := s.bb(12)
	psb, psbr := sp.bb(12)
	mb, mbr := m.bb(c.MediumPeriod)
	pmb, pmbr := mp.bb(c.MediumPeriod)
	switch c.Family {
	case 1:
		pullback := false
		for back := 1; back <= 3; back++ {
			v := t.view(1, back, side)
			average, ok := v.ema(8)
			if ok && v.close() <= average {
				pullback = true
			}
		}
		entry := tr && msr && m.close() >= ms && er && per && s.close() > e && sp.close() <= pe && pullback && rr && r > 45
		exit := er && rr && s.close() < e && r < 50 || msr && m.close() < ms
		return entry, exit
	case 2:
		entry := lfr && plfr && l.close() > lf && lf >= plf && mfr && msr && pmfr && pmsr && midFresh && mf > ms && pmf <= pms && er && rr && s.close() > e && r > 50
		exit := mfr && msr && mf < ms || er && rr && s.close() < e && r < 45
		return entry, exit
	case 3:
		entry := neutral && mdr && pmdr && md.ADX < 20 && md.ADX <= pmd.ADX && rr && prr && r > 30 && pr <= 30 && s.close() > sp.close()
		exit := rr && (r >= 55 || r < 30) || mdr && md.Minus > md.Plus && md.ADX >= 25
		return entry, exit
	case 4:
		oversold := false
		for back := 1; back <= 3; back++ {
			value, ok := t.view(1, back, side).rsi(9)
			if ok && value <= 40 {
				oversold = true
			}
		}
		entry := tr && msr && m.close() > ms && rr && prr && r > 50 && pr <= 50 && oversold && er && s.close() > e
		exit := rr && r < 45 || msr && m.close() < ms
		return entry, exit
	case 5:
		entry := tr && mmr && mm.MACD > 0 && mm.Hist > 0 && smr && psmr && ppsmr && sm.Hist > psm.Hist && psm.Hist <= ppsm.Hist && er && s.close() > e
		exit := smr && sm.Hist < 0 || mmr && mm.Hist < 0
		return entry, exit
	case 6:
		entry := lfr && plfr && l.close() > lf && lf >= plf && mmr && pmmr && midFresh && mm.MACD > 0 && pmm.MACD <= 0 && mm.Hist > 0 && er && s.close() > e
		exit := mmr && mm.MACD < 0 || smr && er && sm.Hist < 0 && s.close() < e
		return entry, exit
	case 7:
		squeeze := pmbr
		for back := 2; back <= c.MediumLookback+1; back++ {
			old, ok := t.view(c.MediumMinutes, back, side).bb(c.MediumPeriod)
			if !ok || pmb.Width > old.Width {
				squeeze = false
			}
		}
		entry := oppositeReady && !opposite && midFresh && squeeze && mbr && mb.Width > pmb.Width && m.close() > mb.Upper && rr && r > 55
		exit := mbr && m.close() < mb.Mid+mb.SD || er && smr && s.close() < e && sm.Hist < 0
		return entry, exit
	case 8:
		walk := true
		for back := 1; back <= 3; back++ {
			v := t.view(1, back, side)
			old, ok := v.bb(12)
			if !ok || v.close() <= old.Mid {
				walk = false
			}
		}
		entry := tr && mbr && pmbr && m.close() >= mb.Mid+mb.SD && mb.Width >= pmb.Width && sbr && psbr && s.close() > sb.Mid+sb.SD && sp.close() <= psb.Mid+psb.SD && walk
		exit := mbr && m.close() < mb.Mid+mb.SD || sbr && s.close() < sb.Mid
		return entry, exit
	case 9:
		entry := neutral && mdr && md.ADX < 20 && psbr && sbr && sp.close() < psb.Lower && s.close() >= sb.Lower && s.close() > sp.close()
		exit := sbr && (s.close() >= sb.Mid || s.close() < sb.Lower) || mdr && md.Minus > md.Plus && md.ADX >= 25
		return entry, exit
	case 10:
		entry := oppositeReady && !opposite && mdr && pmdr && midFresh && md.Plus > md.Minus && pmd.Plus <= pmd.Minus && md.ADX >= 20 && md.ADX > pmd.ADX && er && s.close() > e
		exit := mdr && md.Plus < md.Minus || mdr && pmdr && er && md.ADX < pmd.ADX && s.close() < e
		return entry, exit
	case 11:
		entry := tr && mdr && pmdr && md.Plus-md.Minus >= 10 && pmd.Plus-pmd.Minus >= 10 && md.ADX >= 20 && er && per && s.close() > e && sp.close() <= pe
		exit := mdr && md.Plus <= md.Minus || er && rr && s.close() < e && r < 45
		return entry, exit
	case 12:
		lowest := math.Inf(1)
		oldRSI := 0.0
		historyReady := true
		for back := c.MediumLookback; back >= 1; back-- {
			old := t.view(c.MediumMinutes, back, side)
			value, ok := old.rsi(c.MediumPeriod)
			if !ok {
				historyReady = false
			}
			if old.low() <= lowest {
				lowest = old.low()
				oldRSI = value
			}
		}
		mr, mrr := m.rsi(c.MediumPeriod)
		entry := oppositeReady && !opposite && midFresh && historyReady && mrr && m.low() < lowest && mr >= oldRSI+5 && m.close() > mp.close() && er && rr && s.close() > e && r > 50
		exit := rr && r >= 65 || er && rr && s.close() < e && r < 45 || mbr && mdr && pmdr && m.close() < mb.Lower && md.ADX > pmd.ADX && md.Minus > md.Plus
		return entry, exit
	}
	return false, false
}
