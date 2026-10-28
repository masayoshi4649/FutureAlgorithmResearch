package main

import (
	"encoding/json"
	"futurealgorithm/sessiontrader/internal/strategy"
	original "futurealgorithm/sessiontrader/internal/strategybase155"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

// Test156RegistrationAndFixedConditions は未登録・条件改変・既存出力上書きを拒否します。
//
// 引数: t(*testing.T)。返り値: なし。原資料と金融再生器は呼びません。
func Test156RegistrationAndFixedConditions(t *testing.T) {
	var configs []Variant
	if err := readJSON("../configs156.json", &configs); err != nil {
		t.Fatal(err)
	}
	if err := validateConfigs(configs); err != nil {
		t.Fatal(err)
	}
	configs[1].Width = 15
	if validateConfigs(configs) == nil {
		t.Fatal("未登録条件を許可")
	}
	path := filepath.Join(t.TempDir(), "受領.json")
	for _, raw := range []string{`{"registered":true}`, `{"registered":false,"returncode":0}`, `{"registered":true,"returncode":1}`} {
		if err := os.WriteFile(path, []byte(raw), 0600); err != nil {
			t.Fatal(err)
		}
		if registrationOK(path) == nil {
			t.Fatal("不完全受領を許可", raw)
		}
	}
	if err := os.WriteFile(path, []byte(`{"registered":true,"returncode":0}`), 0600); err != nil {
		t.Fatal(err)
	}
	if err := registrationOK(path); err != nil {
		t.Fatal(err)
	}
	if err := saveResult(path, map[string]int{"置換": 1}); err == nil {
		t.Fatal("既存出力を上書き")
	}
}

// Test156ParentAndPieceMetrics は親の確定・含み合計と玉別利益返しを混同しないことを確かめます。
//
// 引数: t(*testing.T)。返り値: なし。
func Test156ParentAndPieceMetrics(t *testing.T) {
	r := Result{Entries: map[string]*Entry{
		"A": {ID: "A", Owner: "core", Campaign: 1, Side: 1, Quantity: 2, Remaining: 1, Price: 1000, Gross: 5000},
		"B": {ID: "B", Owner: "core", Campaign: 1, Side: 1, Quantity: 1, Remaining: 1, Price: 1060},
	}}
	markParents156(&r, strategy.Observation{Time: 1, Bid: 1070, Ask: 1080})
	p := r.Parents["core/1"]
	if p.Equity != 13000 || p.Peak != 13000 || p.Remaining != 2 {
		t.Fatal(p)
	}
	markParents156(&r, strategy.Observation{Time: 2, Bid: 980, Ask: 990})
	if p.Equity != -5000 || p.Minimum != -5000 || p.PositiveThenLoss {
		t.Fatal(p)
	}
	r.Entries["A"].Gross = 3000
	r.Entries["A"].Remaining = 0
	r.Entries["B"].Gross = -8000
	r.Entries["B"].Remaining = 0
	markParents156(&r, strategy.Observation{Time: 3, Bid: 980, Ask: 990})
	if p.Realized != -5000 || p.Unrealized != 0 || !p.PositiveThenLoss || p.Peak != 13000 {
		t.Fatal(p)
	}
}

// Test156OriginalSyntheticEquivalence は未改変155版と全通知・状態を人工板で照合します。
//
// 引数: t(*testing.T)。返り値: なし。金融原資料は読みません。
func Test156OriginalSyntheticEquivalence(t *testing.T) {
	for _, kind := range []string{"Day"} {
		p, e := strategy.ParametersForMethod("NK225", kind, "S01")
		if e != nil {
			t.Fatal(e)
		}
		cfg := strategy.Config{Reference: "NK225", Product: "NK225mini", Cap: 10, CoreQuantity: 5, ExtraMaxQuantity: 5, LargeTick: 10, PointValue: 100, Parameters: p}
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
