package main

import (
	"encoding/json"
	"fmt"
	"futurealgorithm/sessiontrader/internal/strategy"
	"reflect"
	"sync"
	"testing"
)

// audit154Case は実原板を読まず、当時値を直接与える独立候補を作ります。
//
// 引数: id(string)。返り値: *CaseStateと生成時のerrorです。
func audit154Case(id string) (*CaseState, error) {
	params, err := strategy.ParametersForMethod("NK225", "Day", "D07")
	if err != nil {
		return nil, err
	}
	scene := Scene{Session: "人工_Day", Kind: "Day", Start: 1, End: 10000, ForceClose: 9900, USOpen: 2000, Partial: true}
	session := makeSession(scene)
	session.ExtraAt = 3800
	p, err := strategy.New(strategy.Config{Reference: "NK225", Product: "NK225mini", Cap: 10, CoreQuantity: 5, ExtraMaxQuantity: 5, LargeTick: 10, PointValue: 100, Parameters: params, Study154: id}, session)
	if err != nil {
		return nil, err
	}
	return &CaseState{P: p, Result: Result{Scene: scene, Variant: Variant{ID: id}, Entries: map[string]*Entry{}, DecisionEvidence: map[string]strategy.Observation{}}}, nil
}

// audit154Sequence は往復する人工板で約定を伴う状態列を作ります。
//
// 引数: id(string)。返り値: Resultと不整合errorです。実市場の再生ではありません。
func audit154Sequence(id string) (Result, error) {
	c, err := audit154Case(id)
	if err != nil {
		return Result{}, err
	}
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
			for _, k := range []int{12, 13, 20, 21} {
				o.Research.Values[k] *= -1
			}
			o.Research.Values[15] = -1
		} else {
			o.Research.Values[15] = 1
		}
		o.Research.Band20.Known = true
		o.Research.Band20.Values = [9]float64{1100, 900, 0, 0, 0, 0, 0, 0, at - 60}
		if err = process(c, o); err != nil {
			return Result{}, err
		}
	}
	if len(c.Result.Events) == 0 {
		return Result{}, fmt.Errorf("人工列に約定がありません %s", id)
	}
	return c.Result, nil
}

// TestAudit154ConcurrentActiveCases は約定する4候補を直列・並列で比較します。
//
// 引数: t(*testing.T)。返り値: なし。原板・ネットワーク・実注文は使用しません。
func TestAudit154ConcurrentActiveCases(t *testing.T) {
	ids := []string{"D07", "E03", "C03", "G01"}
	serial := make([]Result, len(ids))
	parallel := make([]Result, len(ids))
	errs := make([]error, len(ids))
	for i, id := range ids {
		var err error
		serial[i], err = audit154Sequence(id)
		if err != nil {
			t.Fatal(err)
		}
	}
	var wg sync.WaitGroup
	for i, id := range ids {
		wg.Add(1)
		go func(i int, id string) { defer wg.Done(); parallel[i], errs[i] = audit154Sequence(id) }(i, id)
	}
	wg.Wait()
	for i, id := range ids {
		if errs[i] != nil {
			t.Fatal(errs[i])
		}
		a, err := json.Marshal(serial[i])
		if err != nil {
			t.Fatal(err)
		}
		b, err := json.Marshal(parallel[i])
		if err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(a, b) {
			t.Fatal("候補状態の直列並列差", id)
		}
	}
}

// TestAudit154RejectSameOrPastRow は判断と同じ又は前原行への約定を拒否することを確認します。
//
// 引数: t(*testing.T)。返り値: なし。この検査は実際の入力を読みません。
func TestAudit154RejectSameOrPastRow(t *testing.T) {
	s := strategy.Signal{SourceIndex: 3}
	for _, index := range []int64{3, 2} {
		c, err := audit154Case("D07")
		if err != nil {
			t.Fatal(err)
		}
		if err = applyFill(&c.Result, c.P, s, strategy.Observation{Index: index, Time: 10, Bid: 100, Ask: 110}); err == nil {
			t.Fatal("同一又は前原行を受理", index)
		}
	}
}
