package main

import (
	"futurealgorithm/sessiontrader/internal/strategy"
	"reflect"
	"strings"
	"testing"
)

// testNightR2 は金融原板を含まない夜前半候補を作ります。
//
// 引数: number(int)。返り値: *NightResult164R2。
func testNightR2(number int) *NightResult164R2 {
	return newNight164R2(configsNight164R2()[number-4], Scene{Start: 0, USOpen: 10000, ForceClose: 20000})
}

// signalNightR2 は所有IDを明記した人工元通知を作ります。
//
// 引数: id/action(string)、o(Observation)、side/qty(int)、targets(...LotTarget)。返り値: Signal。
func signalNightR2(id, action string, o strategy.Observation, side, qty int, targets ...strategy.LotTarget) strategy.Signal {
	return strategy.Signal{ID: "前半/" + id, Owner: "前半/core", Campaign: 1, Action: action, Side: side, Quantity: qty, Time: o.Time, SourceIndex: o.Index, Targets: targets}
}

// stepTestNightR2 は人工の通知・判断・約定を通常関数で進めます。
//
// 引数: t(*testing.T)、r(*NightResult164R2)、o(Observation)、short(Short164)、signals(...Signal)。返り値: なし。
func stepTestNightR2(t *testing.T, r *NightResult164R2, o strategy.Observation, short Short164, signals ...strategy.Signal) {
	t.Helper()
	if e := r.stepNight164R2(o, signals, short); e != nil {
		t.Fatal(e)
	}
}

// seedTestNightR2 は元新規判断と次正常板を使って初回実玉を作ります。
//
// 引数: t(*testing.T)、number/side/qty(int)。返り値: *NightResult164R2と実玉ID(string)。
func seedTestNightR2(t *testing.T, number, side, qty int) (*NightResult164R2, string) {
	t.Helper()
	r := testNightR2(number)
	o := quoteNightTest164(0, 100, 990, 1000)
	if side < 0 {
		o = quoteNightTest164(0, 100, 1000, 1010)
	}
	stepTestNightR2(t, r, o, Short164{}, signalNightR2("初回", "new", o, side, qty))
	o.Index = 1
	o.Time = 101
	stepTestNightR2(t, r, o, Short164{})
	return r, r.Actual.Active[0]
}

// TestNightR2FloorGapMirror は10円起動・建値床・次板赤字を買売鏡像で確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestNightR2FloorGapMirror(t *testing.T) {
	for _, side := range []int{1, -1} {
		r, id := seedTestNightR2(t, 4, side, 2)
		quote := func(i int64, at, gain float64) strategy.Observation {
			if side > 0 {
				return quoteNightTest164(i, at, 1000+gain, 1010+gain)
			}
			return quoteNightTest164(i, at, 990-gain, 1000-gain)
		}
		stepTestNightR2(t, r, quote(2, 102, 10), Short164{})
		if !r.Lots[id].Activated || len(r.Actual.Pending) != 0 {
			t.Fatal("10円起動")
		}
		stepTestNightR2(t, r, quote(3, 103, 0), Short164{})
		if len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Reason != "protect_10trail20" {
			t.Fatal("床判断")
		}
		stepTestNightR2(t, r, quote(4, 103, -30), Short164{})
		if r.Actual.Realized != -6000 || len(r.Actual.Active) != 0 {
			t.Fatal("次正常同時計の赤字を隠した")
		}
		if r.Parents["前半/core/1"].Base.SourceQty != 20 {
			t.Fatal("独自保護がSourceへ混入")
		}
	}
}

// TestNightR2PartialActualProfit は実益だけの資格・元部分返済量・後順新玉非継承を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestNightR2PartialActualProfit(t *testing.T) {
	for _, gain := range []float64{30, -20} {
		r, id := seedTestNightR2(t, 5, 1, 5)
		o := quoteNightTest164(2, 102, 1040, 1050)
		close := signalNightR2("部分", "close", o, -1, 2, strategy.LotTarget{ID: "前半/初回-玉", Quantity: 2})
		add := signalNightR2("追加", "new", o, 1, 1)
		stepTestNightR2(t, r, o, Short164{}, close, add)
		stepTestNightR2(t, r, quoteNightTest164(3, 103, 1000+gain, 1010+gain), Short164{})
		if r.Actual.Lots[id].Remaining != 30 {
			t.Fatal("元2/5返済")
		}
		if r.Lots[id].ResidualEligible != (gain > 0) {
			t.Fatal("影の利益や判断価格で資格を与えた")
		}
		for _, l := range r.Actual.Lots {
			if l.Kind == "source_add" && r.Lots[l.ID].ResidualEligible {
				t.Fatal("後順の新玉へ過去資格継承")
			}
		}
	}
}

// TestNightR2ResidualNoRetroactive は資格前の順行を遡及起動せず、部分返済後の新しい正益を待ちます。
//
// 引数: t(*testing.T)。返り値: なし。
func TestNightR2ResidualNoRetroactive(t *testing.T) {
	r, id := seedTestNightR2(t, 5, 1, 5)
	stepTestNightR2(t, r, quoteNightTest164(2, 102, 1100, 1110), Short164{})
	o := quoteNightTest164(3, 103, 1005, 1015)
	stepTestNightR2(t, r, o, Short164{}, signalNightR2("部分", "close", o, -1, 2, strategy.LotTarget{ID: "前半/初回-玉", Quantity: 2}))
	stepTestNightR2(t, r, quoteNightTest164(4, 104, 1005, 1015), Short164{})
	if !r.Lots[id].ResidualEligible || r.Lots[id].Activated {
		t.Fatal("過去100円順行を再利用した")
	}
	stepTestNightR2(t, r, quoteNightTest164(5, 105, 1010, 1020), Short164{})
	stepTestNightR2(t, r, quoteNightTest164(6, 106, 1000, 1010), Short164{})
	if len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Reason != "protect_residual_floor" || r.Actual.Pending[0].Quantity != 30 {
		t.Fatal("資格後の建値床")
	}
}

// TestNightR2SmallAndSourceAdd は小量を元初回量で固定し、担当名によらず追加だけ停止します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestNightR2SmallAndSourceAdd(t *testing.T) {
	for _, q := range []int{2, 3} {
		r, id := seedTestNightR2(t, 6, 1, q)
		stepTestNightR2(t, r, quoteNightTest164(2, 102, 1010, 1020), Short164{})
		if r.Lots[id].Activated != (q == 2) {
			t.Fatal("小量初回の分類")
		}
	}
	r, id := seedTestNightR2(t, 6, 1, 5)
	o := quoteNightTest164(2, 102, 1050, 1060)
	stepTestNightR2(t, r, o, Short164{}, signalNightR2("追加", "new", o, 1, 2))
	stepTestNightR2(t, r, quoteNightTest164(3, 103, 1050, 1060), Short164{})
	stepTestNightR2(t, r, quoteNightTest164(4, 104, 1010, 1020), Short164{})
	if len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Reason != "source_add_stop50" || r.Actual.Pending[0].Targets[0].ID == id {
		t.Fatal("core初回へ追加停止が漏れた")
	}
}

// TestNightR2SourceClosesPriority は元返済を優先し独自返済済みSourceIDを二重返済しません。
//
// 引数: t(*testing.T)。返り値: なし。
func TestNightR2SourceClosesPriority(t *testing.T) {
	r, id := seedTestNightR2(t, 4, 1, 5)
	stepTestNightR2(t, r, quoteNightTest164(2, 102, 1030, 1040), Short164{})
	o := quoteNightTest164(3, 103, 1000, 1010)
	stepTestNightR2(t, r, o, Short164{}, signalNightR2("部分", "close", o, -1, 2, strategy.LotTarget{ID: "前半/初回-玉", Quantity: 2}))
	if len(r.Actual.Pending) != 1 || !strings.HasPrefix(r.Actual.Pending[0].Reason, "source_partial/") {
		t.Fatal("元返済優先")
	}
	stepTestNightR2(t, r, quoteNightTest164(4, 104, 1000, 1010), Short164{})
	if len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Quantity != 30 {
		t.Fatal("部分返済後残量だけ保護")
	}
	stepTestNightR2(t, r, quoteNightTest164(5, 105, 1000, 1010), Short164{})
	if r.Actual.Lots[id].Remaining != 0 {
		t.Fatal("全返済")
	}
	o = quoteNightTest164(6, 106, 900, 910)
	stepTestNightR2(t, r, o, Short164{}, signalNightR2("終了", "close", o, -1, 3, strategy.LotTarget{ID: "前半/初回-玉", Quantity: 3}))
	if len(r.Actual.Pending) > 0 || r.Parents["前半/core/1"].Base.SourceQty != 0 {
		t.Fatal("既返済玉を二重返済")
	}
}

// shortTestNightR2 は失速又は再加速の既知速度を作ります。
//
// 引数: recovery(bool)。返り値: Short164。
func shortTestNightR2(recovery bool) Short164 {
	s := Short164{Five: ShortWindow164{Known: true, Speed: .25}, Fifteen: ShortWindow164{Known: true, Speed: 1}}
	if recovery {
		s.Five.Speed = 2
	}
	return s
}

// TestNightR2DelayQuantityAndDeadSource は待機中の部分減少・追加不採用・元ID終了を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestNightR2DelayQuantityAndDeadSource(t *testing.T) {
	for _, closed := range []int{2, 5} {
		r := testNightR2(7)
		o := quoteNightTest164(0, 100, 990, 1000)
		stepTestNightR2(t, r, o, shortTestNightR2(false), signalNightR2("初回", "new", o, 1, 5))
		if len(r.Actual.Pending) > 0 {
			t.Fatal("待機しない")
		}
		o = quoteNightTest164(1, 101, 995, 1005)
		stepTestNightR2(t, r, o, shortTestNightR2(false), signalNightR2("部分", "close", o, -1, closed, strategy.LotTarget{ID: "前半/初回-玉", Quantity: closed}), signalNightR2("追加", "new", o, 1, 1))
		stepTestNightR2(t, r, quoteNightTest164(2, 102, 1000, 1010), shortTestNightR2(true))
		if closed == 2 {
			if len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Quantity != 30 || r.Actual.Pending[0].SourceID != "前半/初回" {
				t.Fatal("当初生存ID残量を超えて解除")
			}
		} else if len(r.Actual.Pending) > 0 {
			t.Fatal("元ID終了後の復活")
		}
	}
}

// TestNightR2UnknownAndExpiry は未知の元入口維持と30秒超の取消優先を固定します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestNightR2UnknownAndExpiry(t *testing.T) {
	r := testNightR2(7)
	o := quoteNightTest164(0, 100, 990, 1000)
	stepTestNightR2(t, r, o, Short164{}, signalNightR2("初回", "new", o, 1, 5))
	if len(r.Actual.Pending) != 1 || r.Counts["初回短期未知で元通知維持"] != 1 {
		t.Fatal("未知を失速扱い")
	}
	r = testNightR2(7)
	stepTestNightR2(t, r, o, shortTestNightR2(false), signalNightR2("初回", "new", o, 1, 5))
	stepTestNightR2(t, r, quoteNightTest164(1, 130.001, 1000, 1010), shortTestNightR2(true))
	if len(r.Actual.Pending) > 0 || !r.Parents["前半/core/1"].Cancelled {
		t.Fatal("30秒超取消優先")
	}
}

// TestNightR2NativeQuantityAndSameParent は政策無効の源配賦とP05同親後続新規を確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestNightR2NativeQuantityAndSameParent(t *testing.T) {
	r := testNightR2(5)
	r.Config.ResidualFloor = false
	c := newNight164(configsNight164()[0], Scene{Start: 0, USOpen: 10000, ForceClose: 20000})
	for i := int64(0); i <= 8; i++ {
		o := quoteNightTest164(i, 100+float64(i), 990+float64(i)*10, 1000+float64(i)*10)
		sigs := []strategy.Signal{}
		switch i {
		case 0:
			sigs = append(sigs, signalNightR2("初回", "new", o, 1, 5))
		case 2:
			sigs = append(sigs, signalNightR2("部分", "close", o, -1, 2, strategy.LotTarget{ID: "前半/初回-玉", Quantity: 2}))
		case 4:
			sigs = append(sigs, signalNightR2("終了", "close", o, -1, 3, strategy.LotTarget{ID: "前半/初回-玉", Quantity: 3}))
		case 6:
			sigs = append(sigs, signalNightR2("同親後続", "new", o, 1, 1))
		case 7:
			sigs = append(sigs, signalNightR2("後続終了", "close", o, -1, 1, strategy.LotTarget{ID: "前半/同親後続-玉", Quantity: 1}))
		}
		stepTestNightR2(t, r, o, Short164{}, sigs...)
		if e := c.nativeStepNight164(o, sigs); e != nil {
			t.Fatal(e)
		}
	}
	if r.Actual.Realized != c.Actual.Realized || len(r.Actual.Events) != len(c.Actual.Events) {
		t.Fatal("基準会計不一致")
	}
	for i, e := range c.Actual.Events {
		got := r.Actual.Events[i]
		if got.Order.Quantity != e.Order.Quantity || got.Order.Side != e.Order.Side || got.Order.DecisionIndex != e.Order.DecisionIndex || got.FillIndex != e.FillIndex || got.Price != e.Price || got.Gross != e.Gross {
			t.Fatal("基準約定不一致")
		}
	}
	if r.Actual.Events[3].Order.Kind != "source_add" || r.Parents["前半/core/1"].Base.OldInitial != 50 {
		t.Fatal("同親後続を初回へ変更")
	}
}

// TestNightR2BoundaryAndDefinitions は時間枠返済と旧定義非変更・新8IDを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestNightR2BoundaryAndDefinitions(t *testing.T) {
	before := configsNight164()
	configs := configsNight164R2()
	if len(configs) != 8 || !reflect.DeepEqual(before, configsNight164()) {
		t.Fatal("旧定義変更")
	}
	r, _ := seedTestNightR2(t, 5, 1, 5)
	r.End = 102
	stepTestNightR2(t, r, quoteNightTest164(2, 102, 900, 910), Short164{})
	if len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Reason != "時間枠終了" {
		t.Fatal("時間枠返済")
	}
	stepTestNightR2(t, r, quoteNightTest164(3, 102, 890, 900), Short164{})
	if len(r.Actual.Active) > 0 || r.Actual.Realized != -55000 {
		t.Fatal("時間枠を次板実価格で清算しない")
	}
}

// TestNightR2ExactThirtyAndNextParent は30秒境界・取消後の親分離・予約込み上限を確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestNightR2ExactThirtyAndNextParent(t *testing.T) {
	r := testNightR2(7)
	o := quoteNightTest164(0, 100, 990, 1000)
	stepTestNightR2(t, r, o, shortTestNightR2(false), signalNightR2("初回", "new", o, 1, 5))
	stepTestNightR2(t, r, quoteNightTest164(1, 130, 1000, 1010), shortTestNightR2(true))
	if len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Quantity != 50 {
		t.Fatal("30秒ちょうどの再加速拒否")
	}
	r = testNightR2(7)
	stepTestNightR2(t, r, o, shortTestNightR2(false), signalNightR2("初回", "new", o, 1, 5))
	stepTestNightR2(t, r, quoteNightTest164(1, 131, 1000, 1010), shortTestNightR2(true))
	o = quoteNightTest164(2, 132, 1000, 1010)
	add := signalNightR2("取消後追加", "new", o, 1, 1)
	next := signalNightR2("次親", "new", o, 1, 5)
	next.Campaign = 2
	stepTestNightR2(t, r, o, Short164{}, add, next)
	if len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Campaign != 2 {
		t.Fatal("取消後の同親復活又は新親拒否")
	}
	// ----------------------------------------
	// 未約定の新規50枚を控除し、別親60枚を50枚へ制限します。
	next = signalNightR2("別親", "new", o, 1, 6)
	next.Campaign = 3
	if e := r.sourceNight164R2(o, []strategy.Signal{next}, Short164{}); e != nil {
		t.Fatal(e)
	}
	if len(r.Actual.Pending) != 2 || r.Actual.Pending[1].Quantity != 50 || r.Actual.capacity(1) != 0 {
		t.Fatal("新規予約の枠を無視")
	}
}

// TestNightR2PendingNewDoesNotDelayOldFloor は元追加予約が既存玉の同原行保護を遅らせないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。新規予約で将来返済分の枠を空けません。
func TestNightR2PendingNewDoesNotDelayOldFloor(t *testing.T) {
	r, id := seedTestNightR2(t, 4, 1, 5)
	stepTestNightR2(t, r, quoteNightTest164(2, 102, 1030, 1040), Short164{})
	o := quoteNightTest164(3, 103, 1010, 1020)
	stepTestNightR2(t, r, o, Short164{}, signalNightR2("追加", "new", o, 1, 5))
	if len(r.Actual.Pending) != 2 || r.Actual.Pending[0].Kind != "source_add" || r.Actual.Pending[1].Reason != "protect_10trail20" || r.Actual.Pending[1].Targets[0].ID != id {
		t.Fatal("元追加予約が旧玉の利益床を遅らせた")
	}
	if r.Actual.capacity(1) != 0 {
		t.Fatal("返済予定で先に新規枠が空いた")
	}
	stepTestNightR2(t, r, quoteNightTest164(4, 103, 990, 1000), Short164{})
	if r.Actual.Lots[id].Remaining != 0 || r.Actual.Realized != -5000 || len(r.Actual.Active) != 1 || r.Actual.Lots[r.Actual.Active[0]].Kind != "source_add" {
		t.Fatal("同原行新規と旧玉返済の所有又は次板赤字不一致")
	}
	if r.Lots[r.Actual.Active[0]].Activated {
		t.Fatal("旧玉の床を新しい追加へ継承")
	}
}
