package main

import (
	"encoding/json"
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
	"reflect"
	"testing"
)

// sample157 は人工時計・正常気配を生成します。
//
// 引数: i(int64)、at/bid/ask(float64)。返り値: strategy.Observation。
func sample157(i int64, at, bid, ask float64) strategy.Observation {
	return strategy.Observation{Reference: "NK225", Index: i, Time: at, Bid: bid, Ask: ask, Last: (bid + ask) / 2, QuoteOK: true}
}

// policyBy157 は固定条件を人工検査で選びます。
//
// 引数: id(string)。返り値: Policy157。不明IDはpanicです。
func policyBy157(id string) Policy157 {
	for _, p := range configs157() {
		if p.ID == id || p.ID == "V_"+id {
			return p
		}
	}
	panic(id)
}

// supportPair157 は数量政策だけを検査する既知支持を生成します。
//
// 引数: m/v(float64)、side(int)。返り値: map[int]Support157。
func supportPair157(m, v float64, side int) map[int]Support157 {
	s := Support157{Known: true, M: m, T: v, Own5: float64(side), Own15: float64(side)}
	return map[int]Support157{side: s, -side: {Known: true, Own5: float64(side), Own15: float64(side), Opp: v}}
}

// newSignal157 は未来の約定情報を持たない人工Source通知を作ります。
//
// 引数: id/owner(string)、campaign/side/q(int)、o(Observation)。返り値: strategy.Signal。
func newSignal157(id, owner string, campaign, side, q int, o strategy.Observation) strategy.Signal {
	return strategy.Signal{ID: id, Owner: owner, Campaign: campaign, Side: side, Quantity: q, Action: "new", Time: o.Time, SourceIndex: o.Index}
}

// TestFixed23AndEndpoint157 は第二巡固定案数と旧価格窓端関数を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestFixed23AndEndpoint157(t *testing.T) {
	v := configs157()
	if len(v) != 40 || validate157(v) != nil {
		t.Fatal("固定40条件")
	}
	v[2].Power++
	if validate157(v) == nil {
		t.Fatal("改変を許可")
	}
	rows := []supportRow157{{Time: 100, Mid: 1000, Valid: true}, {Time: 105, Mid: 1002, Valid: true}}
	r, ok := return157(rows, 1, 5, 2)
	if !ok || math.Abs(r-20) > 1e-8 {
		t.Fatal(r, ok)
	}
	rows[0].Time = 97.99
	if _, ok = return157(rows, 1, 5, 2); ok {
		t.Fatal("2秒超の過去値")
	}
}

// TestExactSourceOrder157 は全通知順・所有対象・同額換算と次原行約定を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestExactSourceOrder157(t *testing.T) {
	r := newPolicy157(policyBy157("C00"), Scene{Start: 100, ForceClose: 10000})
	o := sample157(0, 100, 999, 1001)
	s := newSignal157("a", "core", 1, 1, 5, o)
	if e := step157(r, o, []strategy.Signal{s}, nil); e != nil {
		t.Fatal(e)
	}
	if len(r.Actual.Events) != 0 || r.Actual.Pending[0].Quantity != 50 {
		t.Fatal("同原行約定")
	}
	o = sample157(1, 101, 1009, 1011)
	close := strategy.Signal{ID: "z", Owner: "core", Campaign: 1, Action: "close", Side: -1, Quantity: 2, SourceIndex: 1, Time: 101, Targets: []strategy.LotTarget{{ID: "a-玉", Quantity: 2}}}
	add := newSignal157("b", "core", 1, 1, 1, o)
	if e := step157(r, o, []strategy.Signal{close, add}, nil); e != nil {
		t.Fatal(e)
	}
	if r.Actual.Pending[0].ID != "z" || r.Actual.Pending[1].ID != "b" {
		t.Fatal("元通知順の変更")
	}
	if e := step157(r, sample157(2, 102, 1029, 1031), nil, nil); e != nil {
		t.Fatal(e)
	}
	if r.Actual.Realized != 3600 || r.Actual.Lots["a-玉"].Remaining != 30 || r.Actual.Lots["b-玉"].Remaining != 10 {
		t.Fatal(r.Actual)
	}
	if r.Actual.Risk.GrossSeconds != 50 || r.Actual.Risk.PeakAt.Time < 100 {
		t.Fatal("保有時間/初期時刻")
	}
}

// TestRejectedParentAndFactor157 は初回拒否固定と係数による後続Source数量を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestRejectedParentAndFactor157(t *testing.T) {
	for _, id := range []string{"B01", "Q01"} {
		r := newPolicy157(policyBy157(id), Scene{Start: 100, ForceClose: 10000})
		o := sample157(0, 100, 999, 1001)
		if e := step157(r, o, []strategy.Signal{newSignal157("拒否", "episode", 2, 1, 2, o)}, nil); e != nil {
			t.Fatal(e)
		}
		o = sample157(1, 101, 999, 1001)
		if e := step157(r, o, []strategy.Signal{newSignal157("遅れ", "episode", 2, 1, 1, o), newSignal157("初回", "core", 1, 1, 5, o)}, supportPair157(.8, .5, 1)); e != nil {
			t.Fatal(e)
		}
		if r.Parents["episode/2"].Rejected != "指標未知" || r.Parents["core/1"].InitialQty != 40 {
			t.Fatal(r.Parents)
		}
		o = sample157(2, 102, 999, 1001)
		if e := step157(r, o, []strategy.Signal{newSignal157("追加", "core", 1, 1, 1, o)}, supportPair157(.8, .5, 1)); e != nil {
			t.Fatal(e)
		}
		if len(r.Canonical.Pending) != 1 || r.Canonical.Pending[0].Quantity != 8 || r.Canonical.Pending[0].Kind != "source_add" {
			t.Fatal(r.Canonical.Pending)
		}
	}
}

// TestAdverseBottomAndStopPriority157 は低支持中の極値と当行防御優先を売買対称で検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAdverseBottomAndStopPriority157(t *testing.T) {
	for _, side := range []int{1, -1} {
		r := newPolicy157(policyBy157("Q08"), Scene{Start: 100, ForceClose: 10000})
		quote := func(i int64, at, gain float64) strategy.Observation {
			if side == 1 {
				return sample157(i, at, 1001+gain, 1003+gain)
			}
			return sample157(i, at, 999-gain, 1001-gain)
		}
		o := sample157(0, 100, 999, 1001)
		if e := step157(r, o, []strategy.Signal{newSignal157("初回", "core", 1, side, 5, o)}, supportPair157(.5, .5, side)); e != nil {
			t.Fatal(e)
		}
		if e := step157(r, sample157(1, 101, 999, 1001), nil, supportPair157(.5, .5, side)); e != nil {
			t.Fatal(e)
		}
		if e := step157(r, quote(2, 105, -50), nil, nil); e != nil {
			t.Fatal(e)
		}
		if e := step157(r, quote(3, 112, -30), nil, supportPair157(1, 1, side)); e != nil {
			t.Fatal(e)
		}
		if len(r.Canonical.Pending) != 1 || r.Canonical.Pending[0].Kind != "adverse" || r.Canonical.Pending[0].Quantity != 25 {
			t.Fatal(side, r.Canonical.Pending)
		}
		if e := step157(r, quote(4, 113, -30), nil, supportPair157(1, 1, side)); e != nil {
			t.Fatal(e)
		}
		p := r.Parents["core/1"]
		if p.AdverseUsed != 25 {
			t.Fatal(p)
		}
		o = quote(5, 114, -90)
		if e := step157(r, o, []strategy.Signal{newSignal157("停止時追加", "core", 1, side, 1, o)}, supportPair157(1, 1, side)); e != nil {
			t.Fatal(e)
		}
		for _, ord := range r.Canonical.Pending {
			if len(ord.Targets) == 0 {
				t.Fatal("停止と新規が同時", ord)
			}
		}
		if len(r.Canonical.Pending) == 0 {
			t.Fatal("停止なし")
		}
	}
}

// TestSourcePartialAndCompletion157 は参加前の返済を遡及せず玉別比率と親完結を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestSourcePartialAndCompletion157(t *testing.T) {
	r := newPolicy157(policyBy157("B01"), Scene{Start: 100, ForceClose: 10000})
	o := sample157(0, 100, 999, 1001)
	if e := step157(r, o, []strategy.Signal{newSignal157("初回", "core", 1, 1, 5, o)}, supportPair157(.8, .5, 1)); e != nil {
		t.Fatal(e)
	}
	o = sample157(1, 101, 999, 1001)
	if e := step157(r, o, []strategy.Signal{newSignal157("追加", "core", 1, 1, 1, o)}, supportPair157(.8, .5, 1)); e != nil {
		t.Fatal(e)
	}
	o = sample157(2, 102, 1009, 1011)
	c := strategy.Signal{ID: "部分", Owner: "core", Campaign: 1, Action: "close", Side: -1, Quantity: 2, Targets: []strategy.LotTarget{{ID: "初回-玉", Quantity: 2}}}
	if e := step157(r, o, []strategy.Signal{c}, supportPair157(.8, .5, 1)); e != nil {
		t.Fatal(e)
	}
	if len(r.Canonical.Pending) != 1 || r.Canonical.Pending[0].Quantity != 16 {
		t.Fatal(r.Canonical.Pending)
	}
	if e := step157(r, sample157(3, 103, 1009, 1011), nil, supportPair157(.8, .5, 1)); e != nil {
		t.Fatal(e)
	}
	if r.Parents["core/1"].Finished {
		t.Fatal("部分を完結")
	}
	c.ID = "終了"
	c.Quantity = 4
	c.Targets = []strategy.LotTarget{{ID: "初回-玉", Quantity: 3}, {ID: "追加-玉", Quantity: 1}}
	if e := step157(r, sample157(4, 104, 1009, 1011), []strategy.Signal{c}, supportPair157(.8, .5, 1)); e != nil {
		t.Fatal(e)
	}
	if e := step157(r, sample157(5, 105, 1009, 1011), nil, supportPair157(.8, .5, 1)); e != nil {
		t.Fatal(e)
	}
	if !r.Parents["core/1"].Finished || len(r.Canonical.Active) != 0 || len(r.Actual.Active) != 0 {
		t.Fatal("親が終わらない")
	}
}

// TestCanonicalNetIsolation157 はH/Nで政策会計を共有し実側の気配差だけを分けます。
//
// 引数: t(*testing.T)。返り値: なし。
func TestCanonicalNetIsolation157(t *testing.T) {
	var results []*PolicyResult157
	for _, id := range []string{"Q05", "H05"} {
		r := newPolicy157(policyBy157(id), Scene{Start: 100, ForceClose: 10000})
		p := &AllocationParent157{Key: "core/1", Owner: "core", Campaign: 1, Side: 1, SourceQty: 50, SourcePeak: 50, OldInitial: 50, SourceHolds: map[string]int{}}
		r.Parents[p.Key] = p
		o := sample157(0, 100, 999, 1001)
		r.Canonical.open(p, o, "initial", "initial", 1, 50, Support157{})
		r.project157(o)
		if e := step157(r, sample157(1, 101, 999, 1001), nil, nil); e != nil {
			t.Fatal(e)
		}
		o = sample157(2, 102, 999, 1001)
		r.Canonical.open(p, o, "cover", "cover_add", -1, 20, Support157{})
		r.project157(o)
		if e := step157(r, sample157(3, 103, 999, 1001), nil, nil); e != nil {
			t.Fatal(e)
		}
		if r.Parents[p.Key].Finished {
			t.Fatal("純玉の有無だけで親終了")
		}
		results = append(results, r)
	}
	n, h := results[0], results[1]
	if n.Canonical.Realized != h.Canonical.Realized || n.Canonical.Last.Equity != h.Canonical.Last.Equity {
		t.Fatal("実側が政策へ混入")
	}
	if n.Actual.Last.MidEquity != h.Actual.Last.MidEquity || math.Abs((n.Actual.Last.Equity-h.Actual.Last.Equity)-400) > 1e-9 {
		t.Fatal(n.Actual.Last, h.Actual.Last)
	}
	if n.Actual.Events[1].Order.Kind != "projection" || len(n.Actual.Events[1].Order.CanonicalKinds) != 1 {
		t.Fatal("混合役割の誤帰属")
	}
}

// TestPrefixAndCandidateIsolation157 は将来観測と候補順が過去判断へ影響しないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestPrefixAndCandidateIsolation157(t *testing.T) {
	run := func(ids []string) map[string][]byte {
		out := map[string][]byte{}
		for _, id := range ids {
			r := newPolicy157(policyBy157(id), Scene{Start: 100, ForceClose: 10000})
			for i := int64(0); i < 7; i++ {
				o := sample157(i, 100+float64(i)*11, 999+float64(i)*2, 1001+float64(i)*2)
				var sig []strategy.Signal
				if i == 0 {
					sig = []strategy.Signal{newSignal157("初回", "core", 1, 1, 5, o)}
				}
				if e := step157(r, o, sig, supportPair157(.6, .7, 1)); e != nil {
					t.Fatal(e)
				}
			}
			out[id], _ = json.Marshal(r)
		}
		return out
	}
	a := run([]string{"C00", "Q01", "Q05", "H05"})
	b := run([]string{"H05", "Q05", "Q01", "C00"})
	if !reflect.DeepEqual(a, b) {
		t.Fatal("候補順で変化")
	}
}
