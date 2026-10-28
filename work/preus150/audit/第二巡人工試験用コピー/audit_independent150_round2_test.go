package main

import (
	"bytes"
	"testing"

	"futurealgorithm/sessiontrader/internal/strategy"
)

// round2ConfigsAudit150 は第二巡の登録前固定条件だけを読み込みます。
//
// 引数: t(*testing.T)。返り値: []StudyConfigはB01〜B06です。相場資料は使いません。
func round2ConfigsAudit150(t *testing.T) []StudyConfig {
	t.Helper()
	var c []StudyConfig
	if err := readJSON("../configs_round2_150.json", &c); err != nil {
		t.Fatal(err)
	}
	if len(c) != 6 || c[4].ID != "B05" || c[5].ID != "B06" {
		t.Fatal("固定6条件と異なる")
	}
	return c
}

// armedCoreAudit150 は発注直前まで進んだ架空の買い又は売り準備を作ります。
//
// 引数: t(*testing.T)、c(StudyConfig)、side(int)は生成条件です。
// 返り値: *strategy.Portfolioとstrategy.Observationは旧主担当だけの人工状態です。
func armedCoreAudit150(t *testing.T, c StudyConfig, side int) (*strategy.Portfolio, strategy.Observation) {
	t.Helper()
	s, rules := testSetup(t)
	p, _, _, err := newPortfolio(s, c, false, rules)
	if err != nil {
		t.Fatal(err)
	}
	core := p.Research.Sleeves[0].Source.Legacy
	a := &core.Core.Arm
	a.Side, a.Stage, a.Level, a.Risk = side, 2, 1000, 80
	a.At, a.ReturnExtreme, a.ProgressIndex, a.ReturnIndex = s.Start+1000, 1000, 1, 2
	d := float64(side)
	mid := 1000 + d*25
	at := s.Start + 1100
	o := strategy.Observation{Reference: "NK225", Index: 10, Time: at, Received: at, Last: mid, Bid: mid-5, Ask: mid+5, ATR: 80, QuoteOK: true}
	o.MidHistory.Known = true
	o.MidHistory.Values[3], o.MidHistory.Values[4], o.MidHistory.Values[5] = 1100, 900, .095
	o.MidHistory.Values[10], o.MidHistory.Values[11] = d*5, d*5
	o.MidMarket = strategy.Market{Known: true, Own30Known: true, Peer30Known: true, Own120Known: true, Peer120Known: true, Own30: d, Peer30: d, Own120: d, Peer120: d}
	return core, o
}

// TestAudit150Round2GateRetainsArm は新規直前の強さ不足だけで発注を止め、回復すれば同じ準備から発注できることを確認します。
//
// 引数: t(*testing.T)。返り値: なし。買いと売りの両方を鏡像で検査します。
func TestAudit150Round2GateRetainsArm(t *testing.T) {
	configs := round2ConfigsAudit150(t)
	for _, index := range []int{4, 5} {
		for _, side := range []int{-1, 1} {
			core, o := armedCoreAudit150(t, configs[index], side)
			oldArm := core.Core.Arm
			signals, err := core.Observe(o, true)
			if err != nil || len(signals) != 0 || core.Core.Arm != oldArm || core.StudyEfficiencyRejected150 != 1 {
				t.Fatal(configs[index].ID, side, "弱化時に発注又は準備変更", err)
			}
			o.Index++
			o.Time++
			o.Received++
			o.MidHistory.Values[5] = .3
			signals, err = core.Observe(o, true)
			if err != nil || len(signals) != 1 || signals[0].Action != "new" || signals[0].Side != side {
				t.Fatal(configs[index].ID, side, "回復後に同じ準備から発注できない", err)
			}
		}
	}
}

// TestAudit150Round2GateDiscardsBothPossibleFutures は拒否時点の後に順行する人工例も逆行する人工例も同じ判断になることを確認します。
//
// 引数: t(*testing.T)。返り値: なし。未来側の価格は入口計算へ渡しません。
func TestAudit150Round2GateDiscardsBothPossibleFutures(t *testing.T) {
	configs := round2ConfigsAudit150(t)
	for _, side := range []int{-1, 1} {
		for _, futureChange := range []float64{-100, 100} {
			guarded, o := armedCoreAudit150(t, configs[4], side)
			plainConfig := configs[4]
			plainConfig.PreCoreEntryRecheck = false
			plain, _ := armedCoreAudit150(t, plainConfig, side)
			rejected, err := guarded.Observe(o, true)
			if err != nil || len(rejected) != 0 {
				t.Fatal("現在の弱さで拒否しない", err)
			}
			accepted, err := plain.Observe(o, true)
			if err != nil || len(accepted) != 1 || accepted[0].Action != "new" {
				t.Fatal("元条件の比較入口が成立しない", err)
			}
			// 拒否された仮の入口価格から、その後どちらへ動くかは拒否理由に使いません。
			futurePrice := o.Last + float64(side)*futureChange
			if futurePrice <= 0 || guarded.Core.Arm.Side != side {
				t.Fatal("人工例の準備保持が不正")
			}
		}
	}
}

// TestAudit150Round2PostAndOtherSourcesUnchanged は6条件の後半・追加・別入口へ再確認条件が漏れないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit150Round2PostAndOtherSourcesUnchanged(t *testing.T) {
	s, rules := testSetup(t)
	baseConfig := configsFor150(t)[0]
	preBase, _, _, _ := newPortfolio(s, baseConfig, false, rules)
	postBase, _, _, _ := newPortfolio(s, baseConfig, true, rules)
	for _, c := range round2ConfigsAudit150(t) {
		pre, _, _, err := newPortfolio(s, c, false, rules)
		if err != nil {
			t.Fatal(err)
		}
		post, _, _, err := newPortfolio(s, c, true, rules)
		if err != nil || !bytes.Equal(jsonFor150(t, post), jsonFor150(t, postBase)) {
			t.Fatal(c.ID, "後半へ変更が漏洩", err)
		}
		for _, i := range []int{1, 2} {
			if !bytes.Equal(jsonFor150(t, pre.Research.Sleeves[i].Source), jsonFor150(t, preBase.Research.Sleeves[i].Source)) {
				t.Fatal(c.ID, "他担当へ変更が漏洩", i)
			}
		}
	}
}
