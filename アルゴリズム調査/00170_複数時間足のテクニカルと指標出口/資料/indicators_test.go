package main

import (
	"math"
	"reflect"
	"testing"
)

// artificialCandle は、単体検証専用の連続した確定1分足を作ります。
// 引数: minute は int 型の分位置、close は float64 型の終値。
// 返り値: Candle 型の人工確定足。
func artificialCandle(minute int, close float64) Candle {
	const minuteNS = int64(60_000_000_000)
	return Candle{StartNS: int64(minute) * minuteNS, EndNS: int64(minute+1) * minuteNS, Open: close - 0.3, High: close + 1, Low: close - 1, Close: close, SourceLine: int64(minute + 2), Samples: 2, Volume: 2, VolumeComplete: true}
}

// requireNear は、既知計算値との誤差を確認します。
// 引数: t は *testing.T 型のテスト、actual と expected と tolerance は float64 型の数値。
// 返り値: なし。
func requireNear(t *testing.T, actual, expected, tolerance float64) {
	t.Helper()
	if math.Abs(actual-expected) > tolerance {
		t.Fatalf("計算値 %.12f、期待値 %.12f", actual, expected)
	}
}

// TestIndicatorKnownVectors は、EMA 初期化・Wilder RSI・標準偏差・MACD・DMI の既知値を確認します。
// 引数: t は *testing.T 型の検証状態。
// 返り値: なし。
func TestIndicatorKnownVectors(t *testing.T) {
	e := emaState{n: 3}
	for i, x := range []float64{1, 2, 3, 4, 5} {
		value, ready := e.push(x)
		if ready != (i >= 2) {
			t.Fatal("EMA が準備本数より前に有効になりました")
		}
		if ready {
			requireNear(t, value, float64(i), 1e-12)
		}
	}
	r := rsiState{n: 3}
	for i, x := range []float64{10, 11, 10, 12, 11} {
		value, ready := r.push(x)
		if ready != (i >= 3) {
			t.Fatal("RSI の差分準備本数が不正です")
		}
		if i == 3 {
			requireNear(t, value, 75, 1e-12)
		}
		if i == 4 {
			requireNear(t, value, 600.0/11, 1e-12)
		}
	}
	sd, ready := sampleSDLast([]float64{1, 2, 3, 4}, 4)
	if !ready {
		t.Fatal("標準偏差が未準備です")
	}
	requireNear(t, sd, math.Sqrt(5.0/3), 1e-12)
	s := newIndicatorSeries()
	var p indicatorPoint
	for i := 0; i < 40; i++ {
		p = s.push(artificialCandle(i, float64(i+10)))
	}
	standard, ok := p.MACD[macdPeriods{12, 26, 9}]
	if !ok {
		t.Fatal("標準MACDが未準備です")
	}
	requireNear(t, standard.MACD, 7, 1e-10)
	requireNear(t, standard.Signal, 7, 1e-10)
	requireNear(t, standard.Hist, 0, 1e-10)
	d, ok := p.DMI[8]
	if !ok || !d.ADXReady {
		t.Fatal("DMIが未準備です")
	}
	requireNear(t, d.Plus, 50, 1e-12)
	requireNear(t, d.Minus, 0, 1e-12)
	requireNear(t, d.ADX, 100, 1e-12)
}

// TestHigherFramePublication は、上位足を終端前に公開せず、欠測・部分足も使わないことを確認します。
// 引数: t は *testing.T 型の検証状態。
// 返り値: なし。
func TestHigherFramePublication(t *testing.T) {
	a := candleAggregator{minutes: 3}
	if a.push(artificialCandle(0, 10)) != nil || a.push(artificialCandle(1, 12)) != nil {
		t.Fatal("未確定3分足が公開されました")
	}
	c := a.push(artificialCandle(2, 11))
	if c == nil {
		t.Fatal("確定3分足がありません")
	}
	requireNear(t, c.Open, 9.7, 1e-12)
	requireNear(t, c.High, 13, 1e-12)
	requireNear(t, c.Low, 9, 1e-12)
	requireNear(t, c.Close, 11, 1e-12)
	if c.StartNS != 0 || c.EndNS != 180_000_000_000 || c.SourceLine != 4 || c.Samples != 6 {
		t.Fatal("足境界または出所が一致しません")
	}
	b := candleAggregator{minutes: 3}
	if b.push(artificialCandle(1, 10)) != nil || b.push(artificialCandle(2, 11)) != nil {
		t.Fatal("場頭の部分足を公開しました")
	}
	if b.push(artificialCandle(3, 12)) != nil || b.push(artificialCandle(5, 14)) != nil {
		t.Fatal("欠測足を補間して公開しました")
	}
	for i := 6; i < 9; i++ {
		got := b.push(artificialCandle(i, float64(i)))
		if (got != nil) != (i == 8) {
			t.Fatal("欠測後の完全足へ復帰できません")
		}
	}
	e := newTechnicalEngine()
	e.push(artificialCandle(0, 10))
	e.push(artificialCandle(1, 11))
	if e.series[3].latest(0) != nil {
		t.Fatal("上位足の前倒し参照です")
	}
	e.push(artificialCandle(2, 12))
	if e.series[3].latest(0) == nil || e.series[5].latest(0) != nil {
		t.Fatal("時間軸の確定境界が不正です")
	}
	if e.push(artificialCandle(2, 999)) {
		t.Fatal("重複足を受理しました")
	}
}

// TestCandidateDefinitionsAndWarmup は、72個の固定IDと入口ごとの準備不足抑制を確認します。
// 引数: t は *testing.T 型の検証状態。
// 返り値: なし。
func TestCandidateDefinitionsAndWarmup(t *testing.T) {
	configs := CandidateConfigs()
	ids := map[string]bool{}
	if len(configs) != 72 {
		t.Fatalf("候補数 %d", len(configs))
	}
	for _, c := range configs {
		if ids[c.ID] {
			t.Fatalf("ID重複 %s", c.ID)
		}
		ids[c.ID] = true
		if c.Quantity != 10 || c.IndicatorExit != (c.ExitMode != "T") {
			t.Fatal("固定定義が不正です")
		}
		s := NewTechnicalStrategy(c, 10000)
		for i := 0; i < 30; i++ {
			if s.OnBar(artificialCandle(i, 10000+30*math.Sin(float64(i))), Position{}) != nil {
				t.Fatalf("%s が未準備で新規判断しました", c.ID)
			}
		}
	}
	if !ids["F01A_I"] || !ids["F12B_F"] {
		t.Fatal("固定ID境界がありません")
	}
}

// TestSignalsAreCausalAndSymmetric は、未来足変更による過去指示の変化と上下非対称を検出します。
// 引数: t は *testing.T 型の検証状態。
// 返り値: なし。
func TestSignalsAreCausalAndSymmetric(t *testing.T) {
	signaled := 0
	for _, c := range CandidateConfigs() {
		a, b, mirror := NewTechnicalStrategy(c, 10000), NewTechnicalStrategy(c, 10000), NewTechnicalStrategy(c, 10000)
		var saved *indicatorPoint
		var snapshot [4]float64
		for i := 0; i < 240; i++ {
			price := 10000 + 0.15*float64(i) + 40*math.Sin(float64(i)*0.14) + 12*math.Sin(float64(i)*0.8)
			ca := artificialCandle(i, price)
			cb := ca
			if i >= 180 {
				cb.Open += 800
				cb.High += 800
				cb.Low += 800
				cb.Close += 800
			}
			sa, sb := a.OnBar(ca, Position{}), b.OnBar(cb, Position{})
			if i < 180 && !reflect.DeepEqual(sa, sb) {
				t.Fatalf("%s の過去指示が未来変更で変化しました", c.ID)
			}
			cm := ca
			cm.Open = -ca.Open
			cm.High = -ca.Low
			cm.Low = -ca.High
			cm.Close = -ca.Close
			sm := mirror.OnBar(cm, Position{})
			if (sa == nil) != (sm == nil) {
				t.Fatalf("%s の鏡映シグナル有無が非対称です", c.ID)
			}
			if sa != nil {
				signaled++
				if sa.Target != -sm.Target {
					t.Fatalf("%s の売買方向が非対称です", c.ID)
				}
			}
			if i == 100 {
				saved = a.engine.series[1].latest(0)
				snapshot = [4]float64{saved.Bar.Close, saved.EMA[8], saved.RSI[9], saved.BB[12].SD}
			}
		}
		if snapshot != [4]float64{saved.Bar.Close, saved.EMA[8], saved.RSI[9], saved.BB[12].SD} {
			t.Fatal("後続足で確定済みスナップショットを書き換えました")
		}
	}
	if signaled == 0 {
		t.Fatal("人工系列に売買指示がなく因果性検証が空です")
	}
}

// TestExitModesKeepTheirMeaning は、同じ入口の I/F 指標出口と T の保有継続を照合します。
// 引数: t は *testing.T 型の検証状態。
// 返り値: なし。
func TestExitModesKeepTheirMeaning(t *testing.T) {
	configs := CandidateConfigs()
	exits := 0
	for index := 0; index < len(configs); index += 3 {
		i, trail, floor := NewTechnicalStrategy(configs[index], 10000), NewTechnicalStrategy(configs[index+1], 10000), NewTechnicalStrategy(configs[index+2], 10000)
		for minute := 0; minute < 180; minute++ {
			c := artificialCandle(minute, 10000+30*math.Sin(float64(minute)*0.13))
			p := Position{Side: 1, Qty: 10, Entry: 10000}
			si, st, sf := i.OnBar(c, p), trail.OnBar(c, p), floor.OnBar(c, p)
			if st != nil {
				t.Fatalf("%s が保有中に指標で返済・反転しました", trail.Config.ID)
			}
			if !reflect.DeepEqual(si, sf) {
				t.Fatalf("%s の指標出口と F が異なります", i.Config.ID)
			}
			if si != nil {
				exits++
			}
		}
	}
	if exits == 0 {
		t.Fatal("指標出口を発生させる人工経路がありません")
	}
}

// TestSharedPreparedEngineMatchesIndependent は、共有指標器と独立指標器の全候補指示を照合します。
// 引数: t は *testing.T 型の検証状態。
// 返り値: なし。
func TestSharedPreparedEngineMatchesIndependent(t *testing.T) {
	configs := CandidateConfigs()
	shared := newTechnicalEngine()
	independent := make([]*TechnicalStrategy, len(configs))
	prepared := make([]*TechnicalStrategy, len(configs))
	for index, config := range configs {
		independent[index] = NewTechnicalStrategy(config, 10000)
		prepared[index] = NewTechnicalStrategy(config, 10000)
		prepared[index].engine = shared
	}
	for minute := 0; minute < 240; minute++ {
		c := artificialCandle(minute, 10000+0.1*float64(minute)+40*math.Sin(float64(minute)*0.14)+12*math.Sin(float64(minute)*0.8))
		p := Position{}
		if minute%90 >= 30 && minute%90 < 60 {
			p = Position{Side: 1, Qty: 10, Entry: 10000}
		} else if minute%90 >= 60 {
			p = Position{Side: -1, Qty: 10, Entry: 10000}
		}
		for _, strategy := range prepared {
			if strategy.OnPreparedBar(c, p) != nil {
				t.Fatal("未準備足で指示を出しました")
			}
		}
		if !shared.push(c) {
			t.Fatal("共有指標器が連続足を受理しませんでした")
		}
		for index, strategy := range prepared {
			expected := independent[index].OnBar(c, p)
			actual := strategy.OnPreparedBar(c, p)
			if !reflect.DeepEqual(actual, expected) {
				t.Fatalf("%s 分%d の共有/独立指示が異なります: 共有%v 独立%v", strategy.Config.ID, minute, actual, expected)
			}
			if strategy.OnPreparedBar(c, p) != nil {
				t.Fatal("同候補が同じ確定足を重複判断しました")
			}
			if minute > 0 && strategy.OnPreparedBar(artificialCandle(minute-1, 9999), p) != nil {
				t.Fatal("更新済み未来状態から過去足を判断しました")
			}
		}
	}
}

// TestSessionResetAndProtection は、場内初期化と建値比の保険・トレール・早期利益床を確認します。
// 引数: t は *testing.T 型の検証状態。
// 返り値: なし。
func TestSessionResetAndProtection(t *testing.T) {
	configs := CandidateConfigs()
	s := NewTechnicalStrategy(configs[0], 9000)
	for i := 0; i < 100; i++ {
		s.OnBar(artificialCandle(i, 10000+float64(i)), Position{})
	}
	s.Reset(11000)
	for _, tf := range []int{1, 3, 5, 15} {
		if s.engine.series[tf].latest(0) != nil {
			t.Fatal("前場の指標が残っています")
		}
	}
	if s.OnBar(artificialCandle(0, 11000), Position{}) != nil {
		t.Fatal("場初期化後に準備不足指示を出しました")
	}
	for _, c := range configs[:3] {
		strategy := NewTechnicalStrategy(c, 1)
		for _, side := range []int{1, -1} {
			p := Position{Side: side, Qty: 10, Entry: 10000, PeakPoints: 0}
			check := func(profit, peak float64, want bool) {
				p.PeakPoints = peak
				q := Quote{Bid: 10000 + profit, Ask: 10001 + profit}
				if side < 0 {
					q.Ask = 10000 - profit
					q.Bid = q.Ask - 1
				}
				got := strategy.OnQuote(q, p)
				if (got != nil) != want {
					t.Fatalf("%s 方向%d 利益%.3f 最大%.3f 指示=%v", c.ID, side, profit, peak, got)
				}
			}
			check(-29, 0, false)
			check(-30, 0, true)
			check(6, 9, false)
			check(7, 12, true)
			check(8, 12, false)
			check(0.5, 4, c.ExitMode == "F")
			check(1.5, 4, false)
		}
	}
}
