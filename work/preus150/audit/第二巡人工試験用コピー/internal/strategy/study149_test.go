package strategy

import "testing"

// TestEarlyFallbackQuiet149 は早期化した補完だけ実US静観の返済を行うことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestEarlyFallbackQuiet149(t *testing.T) {
	session := Session{ID: "人工_Night", Kind: "Night", Start: 1000, USOpen: 10000, ForceClose: 30000, End: 31000, ExtraAt: 11800}
	params, err := ParametersForMethod("NK225", "Night", "D07")
	if err != nil {
		t.Fatal(err)
	}
	p, err := New(Config{Reference: "NK225", Product: "NK225mini", Cap: 10, CoreQuantity: 5, ExtraMaxQuantity: 5, LargeTick: 10, PointValue: 100, Parameters: params}, session)
	if err != nil {
		t.Fatal(err)
	}
	p.StudyConfigure149(1000, 1000, []string{"core"})
	source := p.Research.Sleeves[0].Source
	source.Supplement.Extra.Position = Position{Side: 1, Quantity: 3, Average: 65000, Risk: 100}
	source.Supplement.Extra.CloseTarget = -1
	var signals []Signal
	source.z04(Observation{Time: 9100, Index: 1, Bid: 65050, Ask: 65060, QuoteOK: true}, true, &signals)
	if source.Supplement.Extra.CloseTarget != 0 || source.Supplement.Extra.CloseReason != 94 || len(signals) != 0 {
		t.Fatal("早期補完の静観返済がない")
	}
}

// TestQuietOverride149 は全経路で指定境界が半開区間になることを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestQuietOverride149(t *testing.T) {
	s := Session{USOpen: 10000, StudyQuietOverride: true, StudyQuietBefore: 300, StudyQuietAfter: 900}
	for _, x := range []struct {
		at   float64
		want bool
	}{{9699, false}, {9700, true}, {10000, true}, {10899, true}, {10900, false}} {
		if studyQuiet149(s, x.at, 900, 900) != x.want {
			t.Fatal(x)
		}
	}
	s.StudyQuietOverride = false
	if !studyQuiet149(s, 9200, 900, 900) {
		t.Fatal("既定静観が変化")
	}
}

// TestFeaturePrefix149 は後半に未来板を追加しても過去特徴を変えないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestFeaturePrefix149(t *testing.T) {
	session := Session{ID: "人工_Night", Kind: "Night", Start: 1000, USOpen: 1000, ForceClose: 10000, End: 11000}
	params := DefaultParameters("NK225", "Night")
	makeF := func() *Features {
		f, e := NewFeatures(session, map[string]float64{"NK225": 10, "TOPIX": .5}, params.Features)
		if e != nil {
			t.Fatal(e)
		}
		f.EnableResearch()
		return f
	}
	a, b := makeF(), makeF()
	for i := 0; i < 120; i++ {
		for _, name := range []string{"TOPIX", "NK225"} {
			row := Board{Reference: name, Time: 1000 + float64(i*30), Received: 1000 + float64(i*30), Last: 65000 + float64(i*10), Bid: 65000 + float64(i*10), Ask: 65010 + float64(i*10), BidQuantity: 1, AskQuantity: 1}
			x, e := a.OnBoard(row)
			if e != nil {
				t.Fatal(e)
			}
			y, e := b.OnBoard(row)
			if e != nil {
				t.Fatal(e)
			}
			if x.Research != y.Research {
				t.Fatal("同接頭辞が不一致")
			}
		}
	}
	old := a.OpeningLast["NK225"]
	_, e := a.OnBoard(Board{Reference: "NK225", Time: 5000, Received: 5000, Last: 99000, Bid: 99000, Ask: 99010})
	if e != nil {
		t.Fatal(e)
	}
	if a.OpeningLast["NK225"] != old || a.OpeningLast["NK225"] != 65000 {
		t.Fatal("後続板が開始値を変更")
	}
}
