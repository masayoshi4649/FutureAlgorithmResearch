package strategy

import "testing"

// artificialRecheck150 は価格段階が完了済みの架空主担当を生成します。
//
// 引数: t(*testing.T)、enabled(bool)、side(int)、efficiency(float64)。
// 返り値: *PortfolioとObservationは人工状態と発注候補行です。
func artificialRecheck150(t *testing.T, enabled bool, side int, efficiency float64) (*Portfolio, Observation) {
	t.Helper()
	session := Session{ID: "架空_Night", Kind: "Night", Start: 1000, USOpen: 20800, ForceClose: 40000, End: 41000}
	cfg := Config{Reference: "NK225", Product: "NK225mini", Cap: 10, CoreQuantity: 5, ExtraMaxQuantity: 5, LargeTick: 10, PointValue: 100, Parameters: DefaultParameters("NK225", "Night")}
	p, e := New(cfg, session)
	if e != nil {
		t.Fatal(e)
	}
	p.Config.Parameters.Night.PostOpenPrepareSeconds = session.Start - session.USOpen
	p.Config.Parameters.Night.Efficiency = .25
	p.StudyCoreEntryEfficiency150 = enabled
	d := float64(side)
	mid := 1000 + d*5
	p.Core.Arm = armState{Side: side, Stage: 2, Level: 1000, Risk: 40, At: 2000, ReturnExtreme: mid - d*10, ProgressIndex: 3, ReturnIndex: 5}
	o := Observation{Reference: "NK225", Time: 2100, Received: 2100, Index: 10, Last: mid, Bid: mid - 5, Ask: mid + 5, ATR: 40, QuoteOK: true}
	o.MidMarket = Market{Known: true, Own30Known: true, Peer30Known: true, Own120Known: true, Peer120Known: true, Own30: d, Peer30: d, Own120: d, Peer120: d}
	o.MidHistory.Known = true
	o.MidHistory.Values[5], o.MidHistory.Values[10], o.MidHistory.Values[11] = efficiency, d*5, d*10
	return p, o
}

// Test150RecheckDeclineBothSides は売買対称に効率低下だけで発注を止め、準備を保持します。
//
// 引数: t(*testing.T)。返り値: なし。元の閾値未再確認版では同じ人工行で発注します。
func Test150RecheckDeclineBothSides(t *testing.T) {
	for _, side := range []int{-1, 1} {
		base, o := artificialRecheck150(t, false, side, .095)
		changed, _ := artificialRecheck150(t, true, side, .095)
		prior := changed.Core.Arm
		var original, rejected []Signal
		base.night(o, true, &original)
		changed.night(o, true, &rejected)
		if len(original) != 1 || len(rejected) != 0 || changed.Core.Arm != prior || changed.Core.Pending != "" || changed.StudyEfficiencyRejected150 != 1 {
			t.Fatal("不足行で発注したか準備を変更", side, original, rejected, changed.Core.Arm)
		}
		// ----------------------------------------
		// 次行で強さが回復すれば、保持した同じ準備から改めて発注できます。
		o.Time++
		o.Received++
		o.Index++
		o.MidHistory.Values[5] = .30
		changed.night(o, true, &rejected)
		if len(rejected) != 1 || rejected[0].Side != side || rejected[0].SourceIndex != o.Index {
			t.Fatal("強さが回復しても準備から発注できない", side, rejected)
		}
	}
}

// Test150RecheckStrongPrefixUnchanged は閾値以上なら元と同じ注文を出すことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。将来の勝ち負けを入力せず当該行だけで判定します。
func Test150RecheckStrongPrefixUnchanged(t *testing.T) {
	for _, side := range []int{-1, 1} {
		for _, efficiency := range []float64{.25, .30, .70} {
			base, o := artificialRecheck150(t, false, side, efficiency)
			changed, _ := artificialRecheck150(t, true, side, efficiency)
			var a, b []Signal
			base.night(o, true, &a)
			changed.night(o, true, &b)
			if len(a) != 1 || len(b) != 1 || a[0].Side != b[0].Side || a[0].Quantity != b[0].Quantity || a[0].SourceIndex != b[0].SourceIndex || a[0].Time != b[0].Time || changed.StudyEfficiencyRejected150 != 0 {
				t.Fatal("閾値以上でも注文が変わる", side, efficiency)
			}
		}
	}
}
