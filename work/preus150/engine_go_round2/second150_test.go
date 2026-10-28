package main

import (
	"bytes"
	"testing"

	"futurealgorithm/sessiontrader/internal/strategy"
)

// secondConfigs150 は第二巡の6固定条件を読取・検証します。
//
// 引数: t(*testing.T)。返り値: []StudyConfigは金融原板を含まない条件です。
func secondConfigs150(t *testing.T) []StudyConfig {
	t.Helper()
	var configs []StudyConfig
	if e := readJSON("../configs_round2_150.json", &configs); e != nil {
		t.Fatal(e)
	}
	if e := validateConfigs150(configs); e != nil {
		t.Fatal(e)
	}
	if len(configs) != 6 {
		t.Fatal("第二巡6条件ではありません")
	}
	return configs
}

// Test150SecondExplicitParameters は6条件の実際の主担当源へ独立した期待値を照合します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test150SecondExplicitParameters(t *testing.T) {
	s, rules := testSetup(t)
	wants := []struct {
		Efficiency, Return, Bounce float64
		Recheck                    bool
	}{
		{.20, .25, .25, false}, {.30, .25, .25, false},
		{.25, .40, .25, false}, {.25, .40, .125, false},
		{.25, .25, .25, true}, {.25, .40, .25, true},
	}
	base, _, _, _ := newPortfolio(s, configsFor150(t)[0], false, rules)
	for i, c := range secondConfigs150(t) {
		p, _, _, e := newPortfolio(s, c, false, rules)
		if e != nil {
			t.Fatal(e)
		}
		legacy := p.Research.Sleeves[0].Source.Legacy
		n := legacy.Config.Parameters.Night
		w := wants[i]
		if n.Efficiency != w.Efficiency || n.RetestReturnR != w.Return || n.BounceR != w.Bounce || n.RetestProgressR != .75 || n.ConfirmSeconds != 60 || legacy.StudyCoreEntryEfficiency150 != w.Recheck {
			t.Fatal(c.ID, "源の確定パラメータ不一致", n, w)
		}
		for _, k := range []int{1, 2} {
			if !bytes.Equal(jsonFor150(t, p.Research.Sleeves[k]), jsonFor150(t, base.Research.Sleeves[k])) {
				t.Fatal(c.ID, "追加又は独立担当も変更")
			}
		}
	}
}

// Test150SecondPostUnchanged は実入口再検査も後半に漏れず、人工観測後までS04と同じであることを確かめます。
//
// 引数: t(*testing.T)。返り値: なし。
func Test150SecondPostUnchanged(t *testing.T) {
	s, rules := testSetup(t)
	for _, c := range secondConfigs150(t) {
		p, from, end, e := newPortfolio(s, c, true, rules)
		if e != nil {
			t.Fatal(e)
		}
		base, _, _, _ := newPortfolio(s, configsFor150(t)[0], true, rules)
		if from != s.USOpen+900 || end != s.ForceClose || !bytes.Equal(jsonFor150(t, p), jsonFor150(t, base)) {
			t.Fatal(c.ID, "後半生成状態が異なる")
		}
		for i := int64(0); i < 4; i++ {
			at := s.USOpen + 1500 + float64(i)
			o := strategy.Observation{Reference: "NK225", Time: at, Received: at, Index: i, Last: 65000, Bid: 65000, Ask: 65010, ATR: 80, QuoteOK: true}
			a, ae := p.Observe(o, true)
			b, be := base.Observe(o, true)
			if ae != nil || be != nil || !bytes.Equal(jsonFor150(t, a), jsonFor150(t, b)) || !bytes.Equal(jsonFor150(t, p), jsonFor150(t, base)) {
				t.Fatal(c.ID, "人工観測後の後半が異なる", ae, be)
			}
		}
	}
}
