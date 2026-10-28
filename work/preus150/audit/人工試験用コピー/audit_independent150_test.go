package main

import (
	"bytes"
	"testing"

	"futurealgorithm/sessiontrader/internal/strategy"
)

// TestAudit150CoreExactDifferences は各条件の主担当差分を、入力マップのコピーではなく固定期待値で検査します。
//
// 引数: t(*testing.T)は試験環境です。返り値: なし。原資料や金融再生は使用しません。
func TestAudit150CoreExactDifferences(t *testing.T) {
	s, r := testSetup(t)
	configs := configsFor150(t)
	for i, c := range configs {
		p, _, _, err := newPortfolio(s, c, false, r)
		if err != nil {
			t.Fatal(err)
		}
		want := strategy.DefaultParameters("NK225", "Night").Night
		want.PostOpenPrepareSeconds = s.Start - s.USOpen
		switch i {
		case 1:
			want.Efficiency = .25
		case 2:
			want.ConfirmSeconds = 20
		case 3:
			want.RetestProgressR = .5
		case 4:
			want.RetestReturnR = .4
		case 5:
			want.BounceR = .125
		case 15, 16:
			want.Efficiency, want.ConfirmSeconds = .25, 20
			want.RetestProgressR, want.BounceR = .5, .125
		}
		if got := p.Research.Sleeves[0].Source.Legacy.Config.Parameters.Night; got != want {
			t.Fatalf("%sの主担当に登録外の差分: %+v / %+v", c.ID, got, want)
		}
	}
}

// TestAudit150PostObservationIdentity は人工板を消費しても全条件の後半が同じ状態と通知を保つことを確認します。
//
// 引数: t(*testing.T)は試験環境です。返り値: なし。既知相場・損益結果を使用しません。
func TestAudit150PostObservationIdentity(t *testing.T) {
	s, r := testSetup(t)
	configs := configsFor150(t)
	portfolios := make([]*strategy.Portfolio, len(configs))
	for i, c := range configs {
		// 前半の生成によって共有式が変更されないことも含めます。
		if _, _, _, err := newPortfolio(s, c, false, r); err != nil {
			t.Fatal(err)
		}
		p, _, _, err := newPortfolio(s, c, true, r)
		if err != nil {
			t.Fatal(err)
		}
		portfolios[i] = p
	}
	for step := 0; step < 90; step++ {
		at := s.USOpen + 600 + float64(step*30)
		mid := 1050. + float64((step%20)-10)*5
		o := strategy.Observation{Reference: "NK225", Index: int64(step), Time: at, Received: at, Last: mid, Bid: mid - 5, Ask: mid + 5, ATR: 40, QuoteOK: true}
		o.MidHistory.Known = true
		o.MidHistory.Values[3], o.MidHistory.Values[4], o.MidHistory.Values[5] = 1070, 970, .4
		o.MidHistory.Values[10], o.MidHistory.Values[11] = 1, 1
		o.MidMarket = strategy.Market{Known: true, Own30Known: true, Peer30Known: true, Own120Known: true, Peer120Known: true, Own30: 1, Peer30: 1, Own120: 1, Peer120: 1}
		for j := 0; j < 24; j++ {
			o.Research.Known[j] = true
		}
		o.Research.Values[0], o.Research.Values[1], o.Research.Values[2] = 1080, 980, .4
		o.Research.Values[9], o.Research.Values[10] = 100, mid
		o.Research.Values[12], o.Research.Values[15], o.Research.Values[20] = 1, 1, 1
		var baseState, baseSignals []byte
		for i, p := range portfolios {
			signals, err := p.Observe(o, at >= s.USOpen+900)
			if err != nil {
				t.Fatal(configs[i].ID, err)
			}
			state, emitted := jsonFor150(t, p), jsonFor150(t, signals)
			if i == 0 {
				baseState, baseSignals = state, emitted
			} else if !bytes.Equal(state, baseState) || !bytes.Equal(emitted, baseSignals) {
				t.Fatalf("後半で前半設定が漏洩: %s / 人工行%d", configs[i].ID, step)
			}
		}
	}
}

// TestAudit150ZeroAndNarrowRange はA10の高安同値と狭い範囲における買売対称性を確認します。
//
// 引数: t(*testing.T)は試験環境です。返り値: なし。
func TestAudit150ZeroAndNarrowRange(t *testing.T) {
	s, r := testSetup(t)
	p, _, _, err := newPortfolio(s, configsFor150(t)[10], false, r)
	if err != nil {
		t.Fatal(err)
	}
	for _, width := range []float64{0, .1, 10, 100} {
		for _, fraction := range []float64{-.1, 0, .25, .5, .75, 1, 1.1} {
			mid := 1000 + fraction*width
			env := map[string]any{"efficiency": .1, "risk": 200., "low": 1000., "high": 1000. + width, "mid": mid}
			a := p.Rules.Number("addon.entry.range_side", env)
			env["mid"] = 2000 + width - mid
			b := p.Rules.Number("addon.entry.range_side", env)
			if a != -b || (width == 0 && a != 0) {
				t.Fatalf("高安幅%g・比率%gで非対称: %g/%g", width, fraction, a, b)
			}
		}
	}
}
