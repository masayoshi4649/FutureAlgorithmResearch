package main

import (
	"reflect"
	"testing"

	"futurealgorithm/sessiontrader/internal/strategy"
)

// independentObservation154 は実資料に依存しない往復と欠測を含む人工観測を作ります。
//
// 引数: i(int64)は原行番号。返り値: strategy.Observation。
func independentObservation154(i int64) strategy.Observation {
	at := 4000 + float64(i*5)
	mid := 1000. + float64((i/20)%6)*30
	if (i/120)%2 == 1 {
		mid = 1180 - float64((i/20)%6)*30
	}
	o := strategy.Observation{Reference: "NK225", Time: at, Received: at, Index: i, Last: mid, Bid: mid - 5, Ask: mid + 5, ATR: 80, QuoteOK: i%233 != 0}
	for k := range o.Research.Known {
		o.Research.Known[k] = true
	}
	o.Research.Values[0], o.Research.Values[1], o.Research.Values[2] = 1100, 900, .1
	o.Research.Values[9], o.Research.Values[10] = 80, mid
	o.Research.Values[12], o.Research.Values[13] = .2, .2
	o.Research.Values[20], o.Research.Values[21], o.Research.Values[22] = .1, .1, at-1
	o.Research.Values[15] = 1
	if (i/120)%2 == 1 {
		for _, k := range []int{12, 13, 20, 21, 15} {
			o.Research.Values[k] *= -1
		}
	}
	o.Research.Band20.Known = true
	o.Research.Band20.Values = [9]float64{1100, 900, 0, 0, 0, 0, 0, 0, at - 60}
	return o
}

// independentCase154 は人工観測を次原行約定する比較用状態を作ります。
//
// 引数: t(*testing.T)、id/kind(string)。返り値: *CaseState。
func independentCase154(t *testing.T, id, kind string) *CaseState {
	t.Helper()
	params, err := strategy.ParametersForMethod("NK225", kind, "D07")
	if err != nil {
		t.Fatal(err)
	}
	scene := Scene{Session: "人工_" + kind, Kind: kind, Start: 1, End: 10000, ForceClose: 9900, USOpen: 2000, Partial: true}
	cfg := strategy.Config{Reference: "NK225", Product: "NK225mini", Cap: 10, CoreQuantity: 5, ExtraMaxQuantity: 5, LargeTick: 10, PointValue: 100, Parameters: params, Study154: id}
	p, err := strategy.New(cfg, makeSession(scene))
	if err != nil {
		t.Fatal(err)
	}
	return &CaseState{P: p, Result: Result{Scene: scene, Variant: Variant{ID: id}, Entries: map[string]*Entry{}, DecisionEvidence: map[string]strategy.Observation{}}}
}

// TestIndependent154R2NightJUnchanged は変更対象外の夜で全Jの発注と会計を原版へ一致させます。
//
// 引数: t(*testing.T)。返り値: なし。取引のない一致を成功扱いしません。
func TestIndependent154R2NightJUnchanged(t *testing.T) {
	cases := []*CaseState{}
	for _, id := range []string{"D07", "J01", "J02", "J03"} {
		cases = append(cases, independentCase154(t, id, "Night"))
	}
	for i := int64(0); i < 1000; i++ {
		o := independentObservation154(i)
		for _, c := range cases {
			if err := process(c, o); err != nil {
				t.Fatal(err)
			}
		}
	}
	base := cases[0]
	if len(base.Result.Events) == 0 {
		t.Fatal("取引のない同値列")
	}
	for _, c := range cases[1:] {
		if !reflect.DeepEqual(base.Result.Events, c.Result.Events) || !reflect.DeepEqual(base.Result.Signals, c.Result.Signals) || !reflect.DeepEqual(base.Result.Entries, c.Result.Entries) || !reflect.DeepEqual(base.Pending, c.Pending) || base.Result.Gross != c.Result.Gross {
			t.Fatal("対象外夜の変更", c.Result.Variant.ID)
		}
	}
}

// independentDrive154 は候補の順序だけを変えて共通影の読み取り独立性を調べます。
//
// 引数: t(*testing.T)、ids([]string)。返り値: map[string]*CaseState。
func independentDrive154(t *testing.T, ids []string) map[string]*CaseState {
	t.Helper()
	ref := independentCase154(t, "D07", "Day")
	out := map[string]*CaseState{}
	for _, id := range ids {
		out[id] = independentCase154(t, id, "Day")
	}
	for i := int64(0); i < 1000; i++ {
		o := independentObservation154(i)
		if err := process(ref, o); err != nil {
			t.Fatal(err)
		}
		for _, id := range ids {
			out[id].P.SetReference154(ref.P)
			if err := process(out[id], o); err != nil {
				t.Fatal(err)
			}
		}
	}
	if len(ref.Result.Events) == 0 {
		t.Fatal("取引のない影運転")
	}
	out["D07"] = ref
	return out
}

// TestIndependent154R2OrderIndependence は参照を共有した候補を逆順処理しても同じ結果になることを検査します。
//
// 引数: t(*testing.T)。返り値: なし。基準運転も候補により変化しないことを確認します。
func TestIndependent154R2OrderIndependence(t *testing.T) {
	ids := []string{"S00", "S01", "S04", "S02", "S03", "J01", "J02", "J03"}
	reverse := append([]string(nil), ids...)
	for i, j := 0, len(reverse)-1; i < j; i, j = i+1, j-1 {
		reverse[i], reverse[j] = reverse[j], reverse[i]
	}
	a, b := independentDrive154(t, ids), independentDrive154(t, reverse)
	for id, c := range a {
		if !reflect.DeepEqual(c.Result, b[id].Result) || !reflect.DeepEqual(c.Pending, b[id].Pending) || !reflect.DeepEqual(c.P.ReferenceRejected154, b[id].P.ReferenceRejected154) {
			t.Fatal("候補順による変化", id)
		}
	}
}
