package main

import (
	"futurealgorithm/sessiontrader/internal/strategy"
	"reflect"
	"testing"
)

// runArtificial1573 は共通の人工通知と原行を順に適用します。
//
// 引数: t(*testing.T)、p(Policy157)。返り値: *PolicyResult157。
func runArtificial1573(t *testing.T, p Policy157) *PolicyResult157 {
	p.ID, p.Control, p.Description = "同値対照", "", ""
	r := newPolicy157(p, Scene{Start: 100, ForceClose: 1000})
	for i, price := range []float64{1000, 1000, 1080, 1010, 900, 1100, 1100, 1050} {
		o := sample157(int64(i), 100+float64(i)*11, price-1, price+1)
		var signals []strategy.Signal
		if i == 0 || i == 4 {
			signals = []strategy.Signal{newSignal157("初回", "core", i+1, 1, 5, o)}
		}
		if i == 2 {
			signals = []strategy.Signal{newSignal157("追加", "core", 1, 1, 1, o)}
		}
		if i == 3 {
			signals = []strategy.Signal{{ID: "部分", Owner: "core", Campaign: 1, Action: "close", Side: -1, Quantity: 2, Targets: []strategy.LotTarget{{ID: "初回-玉", Quantity: 2}}}}
		}
		if i == 6 {
			signals = []strategy.Signal{{ID: "終了", Owner: "core", Campaign: 1, Action: "close", Side: -1, Quantity: 4, Targets: []strategy.LotTarget{{ID: "初回-玉", Quantity: 3}, {ID: "追加-玉", Quantity: 1}}}}
		}
		if err := step157(r, o, signals, supportPair157(.7, .6, 1)); err != nil {
			t.Fatal(err)
		}
	}
	return r
}

// TestO00Unchanged1573 はJ02と全通知・所有・時価が同一であることを人工系列で検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestO00Unchanged1573(t *testing.T) {
	a := runArtificial1573(t, policyBy157("J02"))
	b := runArtificial1573(t, policyBy157("O00"))
	if len(a.Actual.Events) == 0 || !reflect.DeepEqual(a, b) {
		t.Fatal("対照J02とO00の不一致")
	}
	for _, p := range configs157() {
		if !p.OldExit || p.Minimum != 10 || p.Power != 1 || p.Quantum != 1 {
			t.Fatal("旧出口・初回量の共通条件が変化", p)
		}
	}
	h, n := policyBy157("O08"), policyBy157("O05")
	h.ID, h.Control, h.Description, h.Hedge = n.ID, n.Control, n.Description, n.Hedge
	if !reflect.DeepEqual(h, n) {
		t.Fatal("Hが純対照ではない")
	}
	d := policyBy157("O09")
	d.ID, d.Control, d.Description, d.SessionSave = n.ID, n.Control, n.Description, n.SessionSave
	if !reflect.DeepEqual(d, n) {
		t.Fatal("場抑制が純対照ではない")
	}
}

// seedBase1573 は元Source初回を実約定させた人工口座を作ります。
//
// 引数: t(*testing.T)、id(string)、side(int)、s(map[int]Support157)。返り値: *PolicyResult157。
func seedBase1573(t *testing.T, id string, side int, s map[int]Support157) *PolicyResult157 {
	r := newPolicy157(policyBy157(id), Scene{Start: 100, ForceClose: 10000})
	o := sample157(0, 100, 999, 1001)
	if err := step157(r, o, []strategy.Signal{newSignal157("初回", "core", 1, side, 5, o)}, s); err != nil {
		t.Fatal(err)
	}
	if err := step157(r, sample157(1, 101, 999, 1001), nil, s); err != nil {
		t.Fatal(err)
	}
	return r
}

// TestOldBaseNoCommonDefense1573 は旧元玉へ新80pt損切り・40pt追尾・親8万円が漏れないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestOldBaseNoCommonDefense1573(t *testing.T) {
	for _, id := range []string{"O01", "O03", "O05"} {
		for _, side := range []int{1, -1} {
			r := seedBase1573(t, id, side, supportPair157(1, 1, side))
			for i, gain := range []float64{100, 50, -110, -100} {
				mid := 1000 + float64(side)*gain
				if err := step157(r, sample157(int64(i+2), 120+float64(i)*20, mid-1, mid+1), nil, nil); err != nil {
					t.Fatal(err)
				}
				if len(r.Canonical.Pending) > 0 || r.Parents["core/1"].Blocked != "" {
					t.Fatal(id, side, "旧元玉へ新出口を混入", r.Canonical.Pending)
				}
			}
			for _, l := range r.Canonical.Lots {
				if l.Activated || l.Floor != 0 {
					t.Fatal("元玉の新追尾を起動", l)
				}
			}
		}
	}
}

// TestOldExitAllowsFavorableAdd1573 は旧出口を残して支持目標への順行追加だけを許可します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestOldExitAllowsFavorableAdd1573(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, id := range []string{"O00", "O01"} {
			r := seedBase1573(t, id, side, nil)
			mid := 1000 + float64(side)*50
			if err := step157(r, sample157(2, 112, mid-1, mid+1), nil, supportPair157(1, 1, side)); err != nil {
				t.Fatal(err)
			}
			if id == "O00" {
				if len(r.Canonical.Pending) != 0 {
					t.Fatal("対照へ独自追加混入")
				}
			} else if len(r.Canonical.Pending) != 1 || r.Canonical.Pending[0].Kind != "policy_add" || r.Canonical.Pending[0].Quantity != 90 {
				t.Fatal(side, r.Canonical.Pending)
			}
		}
	}
}

// seedCover1573 は初回元玉と反対側の実約定逆玉を所有分離して作ります。
//
// 引数: t(*testing.T)、id(string)、side(int)。返り値: *PolicyResult157と逆玉ID(string)。
func seedCover1573(t *testing.T, id string, side int) (*PolicyResult157, string) {
	r := seedBase1573(t, id, side, nil)
	p := r.Parents["core/1"]
	p.CoverOn = true
	o := sample157(2, 102, 999, 1001)
	r.Canonical.open(p, o, "cover", "cover_add", -side, 20, Support157{})
	r.project157(o)
	if err := step157(r, sample157(3, 103, 999, 1001), nil, nil); err != nil {
		t.Fatal(err)
	}
	for _, id := range r.Canonical.Active {
		if r.Canonical.Lots[id].Kind == "cover" {
			return r, id
		}
	}
	t.Fatal("逆玉が約定していない")
	return nil, ""
}

// coverQuote1573 は逆玉の返済側含み幅に対応した買売対称BBOを作ります。
//
// 引数: side(int)、index(int64)、at/gain(float64)。返り値: strategy.Observation。
func coverQuote1573(side int, index int64, at, gain float64) strategy.Observation {
	if side > 0 {
		return sample157(index, at, 997-gain, 999-gain)
	}
	return sample157(index, at, 1001+gain, 1003+gain)
}

// TestCoverOnlyTrailAndRefill1573 は逆玉だけの床・次板飛び損失・10秒後補充を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestCoverOnlyTrailAndRefill1573(t *testing.T) {
	for _, side := range []int{1, -1} {
		r, id := seedCover1573(t, "O03", side)
		for i, gain := range []float64{39, 40, 60, 20} {
			if err := step157(r, coverQuote1573(side, int64(4+i), 110+float64(i)*10, gain), nil, nil); err != nil {
				t.Fatal(err)
			}
			if i == 0 && r.Canonical.Lots[id].Activated {
				t.Fatal("40pt未満で起動")
			}
		}
		if len(r.Canonical.Pending) != 1 || r.Canonical.Pending[0].Reason != "cover_trail" || r.Canonical.Pending[0].Targets[0].ID != id {
			t.Fatal("逆玉だけを返していない", r.Canonical.Pending)
		}
		if err := step157(r, coverQuote1573(side, 8, 141, -10), nil, nil); err != nil {
			t.Fatal(err)
		}
		if r.Canonical.Lots[id].Gross != -2000 || !r.Parents["core/1"].CoverOn {
			t.Fatal("次板飛び/支持状態の改変", r.Canonical.Lots[id])
		}
		for _, l := range r.Canonical.Lots {
			if l.Kind != "cover" && (l.Activated || l.Floor != 0 || l.Remaining == 0) {
				t.Fatal("元玉を追尾/返済した", l)
			}
		}
		s := map[int]Support157{side: {Known: true, M: 1, Opp: .8, Own5: -float64(side), Own15: -float64(side)}}
		if err := step157(r, coverQuote1573(side, 9, 150, -10), nil, s); err != nil {
			t.Fatal(err)
		}
		if len(r.Canonical.Pending) != 0 {
			t.Fatal("10秒前の再補充")
		}
		if err := step157(r, coverQuote1573(side, 10, 151, -10), nil, s); err != nil {
			t.Fatal(err)
		}
		if len(r.Canonical.Pending) != 1 || r.Canonical.Pending[0].Kind != "cover" || r.Canonical.Pending[0].Quantity != 80 {
			t.Fatal("既存支持ループの補充不成立", r.Canonical.Pending)
		}
	}
}

// TestCoverSourceExitPriority1573 は元Sourceの部分予約と完済を逆玉トレールより先に適用します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestCoverSourceExitPriority1573(t *testing.T) {
	r, id := seedCover1573(t, "O03", 1)
	if err := step157(r, coverQuote1573(1, 4, 110, 60), nil, nil); err != nil {
		t.Fatal(err)
	}
	c := strategy.Signal{ID: "部分", Owner: "core", Campaign: 1, Action: "close", Side: -1, Quantity: 2, Targets: []strategy.LotTarget{{ID: "初回-玉", Quantity: 2}}}
	if err := step157(r, coverQuote1573(1, 5, 120, 20), []strategy.Signal{c}, nil); err != nil {
		t.Fatal(err)
	}
	for _, o := range r.Canonical.Pending {
		if o.Reason != "source_partial" {
			t.Fatal("元部分返済に追尾を重ねた", o)
		}
	}
	if r.Canonical.reservedClose(id) != 8 {
		t.Fatal("逆玉のSource部分比率")
	}
	c.ID, c.Quantity = "元完済", 3
	c.Targets[0].Quantity = 3
	if err := step157(r, coverQuote1573(1, 6, 121, 20), []strategy.Signal{c}, nil); err != nil {
		t.Fatal(err)
	}
	for _, o := range r.Canonical.Pending {
		if o.Reason != "source_end" {
			t.Fatal("元完済より別出口が先行", o)
		}
	}
	if err := step157(r, coverQuote1573(1, 7, 122, 20), nil, nil); err != nil {
		t.Fatal(err)
	}
	if len(r.Canonical.Active) != 0 || len(r.Canonical.Pending) != 0 || !r.Parents["core/1"].Finished {
		t.Fatal("元玉完済後に逆玉/予約が残る")
	}
}

// TestSeparateCollapse1573 は支持崩壊だけを指定2案へ適用し、未知で連続時計を解除します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestSeparateCollapse1573(t *testing.T) {
	for _, id := range []string{"O03", "O05", "O10", "O11"} {
		r := seedBase1573(t, id, 1, nil)
		s := map[int]Support157{1: {Known: true, M: .09, Opp: .5, Own5: -1, Own15: -1}}
		for i, at := range []float64{110, 120, 130, 140, 145} {
			used := s
			if i == 1 {
				used = nil
			}
			if err := step157(r, sample157(int64(i+2), at, 999, 1001), nil, used); err != nil {
				t.Fatal(err)
			}
			blocked := r.Parents["core/1"].Blocked
			if i < 4 && blocked != "" {
				t.Fatal("未知区間を15秒へ加算", blocked)
			}
		}
		blocked := r.Parents["core/1"].Blocked
		if (id == "O10" || id == "O11") != (blocked == "長短支持崩壊") {
			t.Fatal(id, blocked)
		}
	}
}
