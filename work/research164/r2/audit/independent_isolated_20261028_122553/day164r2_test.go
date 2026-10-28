package main

import (
	"encoding/json"
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
	"os"
	"reflect"
	"testing"
)

// r2CaseDay164 は第二巡の人工条件を作ります。
//
// 引数: n(int)。返り値: *DayResult164R2。
func r2CaseDay164(n int) *DayResult164R2 {
	return newDay164R2(configsDay164R2()[n], Scene{Kind: "Day", Start: 100, ForceClose: 10000})
}

// stepR2CaseDay164 は前半後半とも原データを使わず数量政策を進めます。
//
// 引数: t(*testing.T)、r(*DayResult164R2)、o(Observation)、signals([]Signal)、short(Short164)、quantity(int)。返り値: なし。
func stepR2CaseDay164(t *testing.T, r *DayResult164R2, o strategy.Observation, signals []strategy.Signal, short Short164, quantity int) {
	t.Helper()
	ss := supportPair157(1, float64(quantity-10)/90, 1)
	if e := stepDay164R2(r, o, signals, ss, short); e != nil {
		t.Fatal(e)
	}
}

// TestDay164R2FixedNewIDs は旧12定義を変えず新12～15だけを返すことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestDay164R2FixedNewIDs(t *testing.T) {
	before, _ := json.Marshal(configsDay164())
	v := configsDay164R2()
	after, _ := json.Marshal(configsDay164())
	if string(before) != string(after) || len(v) != 4 {
		t.Fatal("旧ID変更又は新条件数")
	}
	if v[0].ID != "NK225_D164_12" || v[3].ID != "NK225_D164_15" || !v[0].ResidualFloor || !v[0].StopAdd || v[0].DelayQuantityCap || !v[1].DelayQuantityCap || v[1].ResidualFloor || !v[2].ResidualFloor || !v[2].StopAdd || !v[2].DelayInitial || v[2].ConfirmAdd || !v[3].ConfirmAdd {
		t.Fatal("固定因子差")
	}
	if path := os.Getenv("EXPORT_DAY164R2_CONFIGS"); path != "" {
		raw, e := json.MarshalIndent(v, "", "  ")
		if e != nil {
			t.Fatal(e)
		}
		if e = os.WriteFile(path, append(raw, '\n'), 0600); e != nil {
			t.Fatal(e)
		}
	}
}

// TestDay164R2NoCapUnchanged は12の管理複製が旧01＋09の人工運転と完全一致することを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestDay164R2NoCapUnchanged(t *testing.T) {
	r := r2CaseDay164(0)
	old := newDay164(r.Config.DayConfig164, r.Base.Scene)
	for i := 0; i < 8; i++ {
		o := sample157(int64(i), float64(100+i), 999+float64(i*10), 1001+float64(i*10))
		s := []strategy.Signal{}
		switch i {
		case 0:
			s = []strategy.Signal{newSignal157("a", "core", 1, 1, 5, o)}
		case 2:
			s = []strategy.Signal{newSignal157("b", "core", 1, 1, 1, o)}
		case 4:
			s = []strategy.Signal{closeSignalDay164("p", "a", 2, o)}
		case 6:
			s = []strategy.Signal{closeSignalDay164("e", "a", 3, o), closeSignalDay164("f", "b", 1, o)}
		}
		ss := supportPair157(.8, .5, 1)
		if e := stepDay164(old, o, s, ss, shortCase164(1, 1)); e != nil {
			t.Fatal(e)
		}
		if e := stepDay164R2(r, o, s, ss, shortCase164(1, 1)); e != nil {
			t.Fatal(e)
		}
	}
	if !reflect.DeepEqual(old, r.DayResult164) {
		t.Fatal("上限なし複製差")
	}
}

// TestDay164R2StopsSupportAmplification は25希望が待機後88支持になっても25予約で止まることを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestDay164R2StopsSupportAmplification(t *testing.T) {
	r := r2CaseDay164(1)
	o := sample157(0, 100, 999, 1001)
	stepR2CaseDay164(t, r, o, []strategy.Signal{newSignal157("a", "core", 1, 1, 5, o)}, shortCase164(-2, 2), 25)
	cap := r.Caps["core/1"]
	if cap == nil || cap.OriginalDesired != 25 || cap.NativeInitial != 50 {
		t.Fatal(cap)
	}
	stepR2CaseDay164(t, r, sample157(1, 103, 999, 1001), nil, shortCase164(2, 1.7), 88)
	if len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Quantity != 25 || r.Parents["core/1"].Factor != .5 {
		t.Fatal("待機後の量増幅")
	}
	stepR2CaseDay164(t, r, sample157(2, 104, 999, 1001), nil, shortCase164(2, 1.7), 88)
	o = sample157(3, 105, 1019, 1021)
	stepR2CaseDay164(t, r, o, []strategy.Signal{newSignal157("b", "core", 1, 1, 2, o)}, shortCase164(2, 1.7), 100)
	if len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Quantity != 10 {
		t.Fatal("後続係数上限")
	}
}

// TestDay164R2CurrentWeakerCanReduce は当時支持が弱くなればQ0以下へ減量できることを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestDay164R2CurrentWeakerCanReduce(t *testing.T) {
	r := r2CaseDay164(1)
	o := sample157(0, 100, 999, 1001)
	stepR2CaseDay164(t, r, o, []strategy.Signal{newSignal157("a", "core", 1, 1, 5, o)}, shortCase164(.2, 2), 60)
	stepR2CaseDay164(t, r, sample157(1, 110, 999, 1001), nil, shortCase164(3, 2), 25)
	if r.Actual.Pending[0].Quantity != 25 || r.Parents["core/1"].Factor != .5 {
		t.Fatal("減量禁止又は係数膨張")
	}
}

// TestDay164R2PartialAndWaitingAddition は待機中の元減量/追加とQ0係数上限を同時に検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestDay164R2PartialAndWaitingAddition(t *testing.T) {
	for _, add := range []bool{false, true} {
		r := r2CaseDay164(1)
		o := sample157(0, 100, 999, 1001)
		stepR2CaseDay164(t, r, o, []strategy.Signal{newSignal157("a", "core", 1, 1, 5, o)}, shortCase164(-2, 2), 25)
		o = sample157(1, 105, 989, 991)
		s := []strategy.Signal{closeSignalDay164("p", "a", 2, o)}
		if add {
			s = append(s, newSignal157("b", "core", 1, 1, 1, o))
		}
		stepR2CaseDay164(t, r, o, s, shortCase164(-2, 2), 88)
		stepR2CaseDay164(t, r, sample157(2, 130, 999, 1001), nil, shortCase164(3, 2), 88)
		sum := 0
		for _, ord := range r.Actual.Pending {
			sum += ord.Quantity
		}
		want := 15
		if add {
			want = 20
		}
		p := r.Parents["core/1"]
		if sum != want || sum > 25*p.SourceQty/50 || p.Factor > .5+1e-10 {
			t.Fatal("残量/peakと元係数上限", sum, want, p)
		}
	}
}

// TestDay164R2ZeroAndThirtyBoundary は0希望の復活禁止と30秒超/Source終了を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestDay164R2ZeroAndThirtyBoundary(t *testing.T) {
	for _, mode := range []string{"zero", "timeout", "end"} {
		r := r2CaseDay164(1)
		o := sample157(0, 100, 999, 1001)
		stepR2CaseDay164(t, r, o, []strategy.Signal{newSignal157("a", "core", 1, 1, 5, o)}, shortCase164(-2, 2), 25)
		at := 130.
		signals := []strategy.Signal{}
		switch mode {
		case "zero":
			r.Caps["core/1"].OriginalDesired = 0
		case "timeout":
			at = 130.001
		case "end":
			signals = []strategy.Signal{closeSignalDay164("e", "a", 5, sample157(1, 130, 999, 1001))}
		}
		stepR2CaseDay164(t, r, sample157(1, at, 999, 1001), signals, shortCase164(3, 2), 100)
		if len(r.Actual.Pending) > 0 {
			t.Fatal("禁止条件で新規", mode)
		}
	}
}

// TestDay164R2SameRowAddReleaseCapacity は解除原行の追加を源残量に足し既予約込み上限を守ります。
//
// 引数: t(*testing.T)。返り値: なし。
func TestDay164R2SameRowAddReleaseCapacity(t *testing.T) {
	r := r2CaseDay164(1)
	o := sample157(0, 100, 999, 1001)
	stepR2CaseDay164(t, r, o, []strategy.Signal{newSignal157("a", "core", 1, 1, 5, o)}, shortCase164(-2, 2), 25)
	o = sample157(1, 105, 999, 1001)
	stepR2CaseDay164(t, r, o, []strategy.Signal{newSignal157("b", "core", 1, 1, 1, o), newSignal157("c", "episode", 2, 1, 5, o)}, shortCase164(3, 2), 88)
	sum := 0
	for _, ord := range r.Actual.Pending {
		sum += ord.Quantity
	}
	if sum > 100 {
		t.Fatal("片側枠")
	}
	p := r.Parents["core/1"]
	if p.SourceQty != 60 || p.Factor > 25./50.+1e-10 || p.InitialQty > 25 {
		t.Fatal("同原行源追加", p)
	}
	if math.Abs(float64(p.InitialQty)-12) > 1e-9 {
		t.Fatal("通常初回88を優先した残枠12", p.InitialQty)
	}
}

// TestDay164R2SellMirror は売りの再加速でも初回希望量以上へ増やさないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestDay164R2SellMirror(t *testing.T) {
	r := r2CaseDay164(1)
	o := sample157(0, 100, 999, 1001)
	ss := supportPair157(1, 15./90., -1)
	if e := stepDay164R2(r, o, []strategy.Signal{newSignal157("a", "core", 1, -1, 5, o)}, ss, shortCase164(-.5, -2)); e != nil {
		t.Fatal(e)
	}
	ss = supportPair157(1, 78./90., -1)
	if e := stepDay164R2(r, sample157(1, 103, 999, 1001), nil, ss, shortCase164(-3, -2)); e != nil {
		t.Fatal(e)
	}
	if r.Actual.Pending[0].Side != -1 || r.Actual.Pending[0].Quantity != 25 || r.Parents["core/1"].Factor != .5 {
		t.Fatal("売りで数量式差")
	}
}
