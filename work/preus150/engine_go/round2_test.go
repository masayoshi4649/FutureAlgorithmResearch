package main

import (
	"futurealgorithm/sessiontrader/internal/strategy"
	"testing"
)

// TestRound2OriginalClocks は特徴保持と準備時計を独立に変更できることを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestRound2OriginalClocks(t *testing.T) {
	s, r := testSetup(t)
	for _, keep := range []bool{false, true} {
		c := StudyConfig{Reset: true, CloseBeforeMinutes: 15, RestartWaitMinutes: 15, KeepFeatures: keep, PostOriginalClocks: true}
		p, from, _, e := newPortfolio(s, c, true, r)
		if e != nil {
			t.Fatal(e)
		}
		if from != s.USOpen+900 {
			t.Fatal("全体最低準備時計を変更")
		}
		for _, sleeve := range p.Research.Sleeves {
			if sleeve.Name == "core" {
				if sleeve.Source.Legacy.Config.Parameters.Night.PostOpenPrepareSeconds != 1320 || sleeve.Source.Session.ExtraAt != s.USOpen+1800 {
					t.Fatal("元の入口時計ではない")
				}
			}
		}
	}
}

// TestRound2FeatureChoice は売買状態を変えず前後の特徴入力だけを選ぶことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestRound2FeatureChoice(t *testing.T) {
	full := strategy.Observation{Time: 100, ATR: 150}
	reset := strategy.Observation{Time: 100, ATR: 30}
	for _, phase := range []string{"前半", "後半", "継続"} {
		for _, keep := range []bool{false, true} {
			c := &Case{Config: StudyConfig{KeepFeatures: keep}, Phase: phase}
			got := selectObservation149(c, full, reset)
			want := 150.
			if phase == "後半" && !keep {
				want = 30
			}
			if got.ATR != want || got.Time != 100 {
				t.Fatal("特徴選択が不正", phase, keep)
			}
		}
	}
}

// TestRound2FourCases は追加条件を固定し、C00/R02の重複再生を含めないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestRound2FourCases(t *testing.T) {
	var configs []StudyConfig
	if e := readJSON("../configs_round2.json", &configs); e != nil {
		t.Fatal(e)
	}
	if len(configs) != 4 {
		t.Fatal("追加4条件ではない")
	}
	for i, c := range configs {
		if c.ID != []string{"S01", "S02", "S03", "S04"}[i] || !c.Reset || c.CloseBeforeMinutes != 15 || c.RestartWaitMinutes != 15 {
			t.Fatal("固定条件が異なる")
		}
	}
}
