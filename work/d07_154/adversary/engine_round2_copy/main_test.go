package main

import (
	"encoding/json"
	"fmt"
	"futurealgorithm/sessiontrader/internal/rules"
	"futurealgorithm/sessiontrader/internal/strategy"
	original "futurealgorithm/sessiontrader/internal/strategybase154"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

// Test154Registration は成功フラグと終了コード双方を必須とすることを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test154Registration(t *testing.T) {
	for _, v := range []struct {
		Data string
		OK   bool
	}{{`{"registered":true,"returncode":0}`, true}, {`{"registered":false,"returncode":0}`, false}, {`{"registered":true,"returncode":1}`, false}, {`{"registered":true}`, false}} {
		path := filepath.Join(t.TempDir(), "受領.json")
		if e := os.WriteFile(path, []byte(v.Data), 0600); e != nil {
			t.Fatal(e)
		}
		if (registrationOK(path) == nil) != v.OK {
			t.Fatal(v)
		}
	}
}

// Test154ReadOnlyGuards は未知条件と既存結果上書きを拒否します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test154ReadOnlyGuards(t *testing.T) {
	if validateConfigs([]Variant{{ID: "未登録"}}) == nil || validateConfigs([]Variant{{ID: "D07"}, {ID: "D07"}}) == nil {
		t.Fatal("条件受付")
	}
	path := filepath.Join(t.TempDir(), "結果.json")
	if e := saveResult(path, []int{1}); e != nil {
		t.Fatal(e)
	}
	if saveResult(path, []int{2}) == nil {
		t.Fatal("上書き")
	}
}

// Test154ExpressionScope はC01昼だけの入口拒否とA01通常追撃だけの変更を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test154ExpressionScope(t *testing.T) {
	r, e := rules.Load("NK225_D07.toml")
	if e != nil {
		t.Fatal(e)
	}
	base := r.Expressions()
	for _, id := range []string{"D07", "C01", "X01", "A01"} {
		for _, kind := range []string{"Day", "Night"} {
			got := variantExpressions(base, id, kind)
			changes := []string{}
			for k, v := range got {
				if v != base[k] {
					changes = append(changes, k)
				}
			}
			expected := 0
			if id == "A01" || kind == "Day" && (id == "C01" || id == "X01") {
				expected = 1
			}
			if len(changes) != expected {
				t.Fatal(id, kind, changes)
			}
		}
	}
}

// Test154OriginalSyntheticEquivalence は現Appの無編集コピーと研究基準を同じ人工観測で比較します。
//
// 引数: t(*testing.T)。返り値: なし。将来の実資料や損益結果を使いません。
func Test154OriginalSyntheticEquivalence(t *testing.T) {
	for _, kind := range []string{"Day", "Night"} {
		p, e := strategy.ParametersForMethod("NK225", kind, "D07")
		if e != nil {
			t.Fatal(e)
		}
		cfg := strategy.Config{Reference: "NK225", Product: "NK225mini", Cap: 10, CoreQuantity: 5, ExtraMaxQuantity: 5, LargeTick: 10, PointValue: 100, Parameters: p, Study154: "D07"}
		session := strategy.Session{ID: "人工", Kind: kind, Start: 1, End: 10000, ForceClose: 9900, USOpen: 2000, ExtraAt: 3800}
		updated, e := strategy.New(cfg, session)
		if e != nil {
			t.Fatal(e)
		}
		var bc original.Config
		raw, _ := json.Marshal(cfg)
		json.Unmarshal(raw, &bc)
		var bs original.Session
		raw, _ = json.Marshal(session)
		json.Unmarshal(raw, &bs)
		baseline, e := original.New(bc, bs)
		if e != nil {
			t.Fatal(e)
		}
		var pend []strategy.Signal
		var basePend []original.Signal
		count := 0
		for i := int64(0); i < 1000; i++ {
			at := 4000 + float64(i*5)
			mid := 1000. + float64((i/20)%6)*30
			if (i/120)%2 == 1 {
				mid = 1180 - float64((i/20)%6)*30
			}
			o := strategy.Observation{Reference: "NK225", Time: at, Received: at, Index: i, Last: mid, Bid: mid - 5, Ask: mid + 5, ATR: 80, QuoteOK: i%233 != 0}
			for k := range o.Research.Known {
				o.Research.Known[k] = true
			}
			o.Research.Values[0] = 1100
			o.Research.Values[1] = 900
			o.Research.Values[2] = .1
			o.Research.Values[9] = 80
			o.Research.Values[10] = mid
			o.Research.Values[12] = .2
			o.Research.Values[13] = .2
			o.Research.Values[20] = .1
			o.Research.Values[21] = .1
			o.Research.Values[22] = at - 1
			if (i/120)%2 == 1 {
				o.Research.Values[12] *= -1
				o.Research.Values[13] *= -1
				o.Research.Values[20] *= -1
				o.Research.Values[21] *= -1
				o.Research.Values[15] = -1
			} else {
				o.Research.Values[15] = 1
			}
			o.Research.Band20.Known = true
			o.Research.Band20.Values = [9]float64{1100, 900, 0, 0, 0, 0, 0, 0, at - 60}
			var bo original.Observation
			raw, _ = json.Marshal(o)
			json.Unmarshal(raw, &bo)
			if normal(o) {
				for _, sig := range pend {
					price := o.Ask
					if sig.Side < 0 {
						price = o.Bid
					}
					f := strategy.Fill{SignalID: sig.ID, ExecutionID: sig.ID + "約定", HoldID: sig.ID + "玉", Quantity: sig.Quantity, Price: price, Time: o.Time, Closed: sig.Targets}
					if e = updated.OnFill(f); e != nil {
						t.Fatal(e)
					}
					updated.OnOrderDone(sig.ID)
				}
				for _, sig := range basePend {
					price := bo.Ask
					if sig.Side < 0 {
						price = bo.Bid
					}
					f := original.Fill{SignalID: sig.ID, ExecutionID: sig.ID + "約定", HoldID: sig.ID + "玉", Quantity: sig.Quantity, Price: price, Time: bo.Time, Closed: sig.Targets}
					if e = baseline.OnFill(f); e != nil {
						t.Fatal(e)
					}
					baseline.OnOrderDone(sig.ID)
				}
				pend = nil
				basePend = nil
			}
			sig, e := updated.Observe(o, true)
			if e != nil {
				t.Fatal(e)
			}
			bsig, e := baseline.Observe(bo, true)
			if e != nil {
				t.Fatal(e)
			}
			a, _ := json.Marshal(sig)
			b, _ := json.Marshal(bsig)
			if string(a) != string(b) {
				t.Fatal(kind, i, "通知差", string(a), string(b))
			}
			a, _ = json.Marshal(updated.Status())
			b, _ = json.Marshal(baseline.Status())
			if !reflect.DeepEqual(a, b) {
				t.Fatal(kind, i, "状態差")
			}
			a, _ = json.Marshal(updated.ExitDiagnostics(o))
			b, _ = json.Marshal(baseline.ExitDiagnostics(bo))
			if !reflect.DeepEqual(a, b) {
				t.Fatal(kind, i, "出口差")
			}
			pend = append(pend, sig...)
			count += len(sig)
			basePend = append(basePend, bsig...)
		}
		if count == 0 {
			t.Fatal("基準同値の人工列に実通知がない")
		}
	}
}

// Test154TerminalMark は最終返済する気配も逆行極値へ含むことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test154TerminalMark(t *testing.T) {
	lot := &Entry{Side: 1, Price: 1000, Remaining: 1}
	o := strategy.Observation{Time: 20, Bid: 900, Ask: 910}
	markEntry(lot, o)
	lot.Remaining = 0
	if lot.WorstPoints != -100 || lot.WorstTime != 20 {
		t.Fatal(lot)
	}
}

// Test154SerialParallel は人工原板の独立2場で直列と4並列の保存結果を照合します。
//
// 引数: t(*testing.T)。返り値: なし。金融原資料を読みません。
func Test154SerialParallel(t *testing.T) {
	root := t.TempDir()
	scenes := []Scene{}
	for n := 0; n < 2; n++ {
		s := Scene{Session: fmt.Sprintf("人工%d_Day", n), Kind: "Day", Start: 1700000000, End: 1700006000, ForceClose: 1700005400, Cutoff: 1700000200, Partial: true, Books: map[string]string{}, Candles: map[string]map[string]string{}}
		for _, ref := range []string{"NK225", "TOPIX"} {
			path := filepath.Join(root, s.Session+ref+".jsonl")
			raw := "{\"CurrentPriceTime\":\"2023-11-14T22:13:21Z\",\"CurrentPrice\":1000,\"Buy1\":{\"Price\":995,\"Qty\":1},\"Sell1\":{\"Price\":1005,\"Qty\":1}}\n"
			if e := os.WriteFile(path, []byte(raw), 0600); e != nil {
				t.Fatal(e)
			}
			s.Books[ref] = path
			s.Candles[ref] = map[string]string{}
			for _, interval := range []string{"60", "300"} {
				p := filepath.Join(root, s.Session+ref+interval+".json")
				if e := os.WriteFile(p, []byte(`{"data":[]}`), 0600); e != nil {
					t.Fatal(e)
				}
				s.Candles[ref][interval] = p
			}
		}
		scenes = append(scenes, s)
	}
	ruleset, e := rules.Load("NK225_D07.toml")
	if e != nil {
		t.Fatal(e)
	}
	configs := []Variant{{ID: "D07"}, {ID: "G01"}, {ID: "C03"}}
	a, b := filepath.Join(root, "直列"), filepath.Join(root, "並列")
	if e := executeJobs(scenes, "D07", a, configs, ruleset.Expressions(), 1); e != nil {
		t.Fatal(e)
	}
	if e := executeJobs(scenes, "D07", b, configs, ruleset.Expressions(), 4); e != nil {
		t.Fatal(e)
	}
	for _, s := range scenes {
		var first, second Saved
		if e := readJSON(filepath.Join(a, s.Session+"_D07.json"), &first); e != nil {
			t.Fatal(e)
		}
		if e := readJSON(filepath.Join(b, s.Session+"_D07.json"), &second); e != nil {
			t.Fatal(e)
		}
		if !reflect.DeepEqual(first, second) {
			t.Fatal("直列並列の結果差")
		}
	}
}
