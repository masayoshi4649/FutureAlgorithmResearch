package main

import (
	"encoding/json"
	"futurealgorithm/sessiontrader/internal/strategy"
	"os"
	"reflect"
	"strings"
	"testing"
)

// dayCase164 は原データを読まない人工手法を作ります。
//
// 引数: n(int)。返り値: *DayResult164。
func dayCase164(n int) *DayResult164 {
	return newDay164(configsDay164()[n], Scene{Kind: "Day", Start: 100, ForceClose: 10000})
}

// shortCase164 は円毎秒を明示した人工短期観測です。
//
// 引数: five,fifteen(float64)。返り値: Short164。
func shortCase164(five, fifteen float64) Short164 {
	return Short164{Five: ShortWindow164{Known: true, Move: five * 5, Speed: five, Elapsed: 5}, Fifteen: ShortWindow164{Known: true, Move: fifteen * 15, Speed: fifteen, Elapsed: 15}}
}

// doDay164 は人工原行のエラーをテスト失敗にします。
//
// 引数: t(*testing.T)、r(*DayResult164)、o(Observation)、signals([]Signal)、short(Short164)。返り値: なし。
func doDay164(t *testing.T, r *DayResult164, o strategy.Observation, signals []strategy.Signal, short Short164) {
	t.Helper()
	if e := stepDay164(r, o, signals, supportPair157(.8, .5, 1), short); e != nil {
		t.Fatal(e)
	}
}

// closeSignalDay164 はSource所有IDを指定した人工返済通知です。
//
// 引数: id,target(string)、qty(int)、o(Observation)。返り値: strategy.Signal。
func closeSignalDay164(id, target string, qty int, o strategy.Observation) strategy.Signal {
	return strategy.Signal{ID: id, Owner: "core", Campaign: 1, Side: -1, Action: "close", Quantity: qty, Time: o.Time, SourceIndex: o.Index, Targets: []strategy.LotTarget{{ID: target + "-玉", Quantity: qty}}}
}

// seededDay164 は46microの人工初回を次板Ask1001で保有させます。
//
// 引数: t(*testing.T)、n(int)。返り値: *DayResult164。
func seededDay164(t *testing.T, n int) *DayResult164 {
	r := dayCase164(n)
	o := sample157(0, 100, 999, 1001)
	doDay164(t, r, o, []strategy.Signal{newSignal157("a", "core", 1, 1, 5, o)}, Short164{})
	doDay164(t, r, sample157(1, 101, 999, 1001), nil, Short164{})
	return r
}

// TestDay164BaselineExact は00が新しい保護処理に入らず旧step157と完全一致することを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestDay164BaselineExact(t *testing.T) {
	r := dayCase164(0)
	c := policyBy157("J02")
	c.ID = r.Config.ID
	old := newPolicy157(c, r.Base.Scene)
	for i := 0; i < 6; i++ {
		o := sample157(int64(i), float64(100+i), 999+float64(i*10), 1001+float64(i*10))
		sigs := []strategy.Signal{}
		if i == 0 {
			sigs = append(sigs, newSignal157("a", "core", 1, 1, 5, o))
		}
		if i == 2 {
			sigs = append(sigs, closeSignalDay164("p", "a", 2, o))
		}
		if i == 3 {
			sigs = append(sigs, newSignal157("b", "core", 1, 1, 1, o))
		}
		if i == 4 {
			sigs = append(sigs, closeSignalDay164("e", "a", 3, o), closeSignalDay164("f", "b", 1, o))
		}
		ss := supportPair157(.8, .5, 1)
		if e := step157(old, o, sigs, ss); e != nil {
			t.Fatal(e)
		}
		if e := stepDay164(r, o, sigs, ss, shortCase164(10, 10)); e != nil {
			t.Fatal(e)
		}
	}
	if !reflect.DeepEqual(old, r.Base) {
		t.Fatal("正本00が変わった")
	}
}

// TestDay164NoProtectionEconomicEquality は07の未知で元を維持する経路と00の会計を照合します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestDay164NoProtectionEconomicEquality(t *testing.T) {
	a := dayCase164(0)
	b := dayCase164(7)
	for i := 0; i < 8; i++ {
		o := sample157(int64(i), float64(100+i), 999+float64(i*10), 1001+float64(i*10))
		s := []strategy.Signal{}
		switch i {
		case 0:
			s = []strategy.Signal{newSignal157("a", "core", 1, 1, 5, o), newSignal157("other", "episode", 2, -1, 2, o)}
		case 2:
			s = []strategy.Signal{newSignal157("b", "core", 1, 1, 1, o)}
		case 4:
			s = []strategy.Signal{closeSignalDay164("p", "a", 2, o)}
		case 6:
			s = []strategy.Signal{closeSignalDay164("e", "a", 3, o), closeSignalDay164("f", "b", 1, o)}
		}
		doDay164(t, a, o, s, Short164{})
		doDay164(t, b, o, s, Short164{})
	}
	if a.Actual.Realized != b.Actual.Realized || a.Actual.Last.Equity != b.Actual.Last.Equity || !equalRiskDay164(a.Actual.Risk, b.Actual.Risk, a.Config.ID, b.Config.ID) {
		t.Fatal("保護非発火で数量又は経済会計が変わった", a.Actual.Realized, b.Actual.Realized, a.Actual.Risk, b.Actual.Risk)
	}
	if len(a.Actual.Events) != len(b.Actual.Events) {
		t.Fatal("非発火約定数")
	}
	for i, x := range a.Actual.Events {
		y := b.Actual.Events[i]
		if x.Price != y.Price || x.FillIndex != y.FillIndex || x.Order.Quantity != y.Order.Quantity || x.Gross != y.Gross {
			t.Fatal(i)
		}
	}
}

// TestDay164ShortUnitsAndUnknown は同速度を失速と扱わず、価格時計の欠測を未知にします。
//
// 引数: t(*testing.T)。返り値: なし。
func TestDay164ShortUnitsAndUnknown(t *testing.T) {
	for _, side := range []int{1, -1} {
		s := shortCase164(float64(side)*2, float64(side)*2)
		if decelDay164(s, side) {
			t.Fatal("同速度で失速")
		}
		s = shortCase164(float64(side)*.5, float64(side)*2)
		if !decelDay164(s, side) {
			t.Fatal("半速以下不検知")
		}
		s = shortCase164(float64(side)*3, float64(side)*2)
		if !recoverDay164(s, side) {
			t.Fatal("再加速")
		}
	}
	f := &SupportBuilder157{}
	for i := 0; i <= 20; i++ {
		f.add(strategy.Board{Reference: "NK225", Time: float64(i), Bid: 999 + float64(i)*2, Ask: 1001 + float64(i)*2})
	}
	s := short164(f, 20)
	if s.Five.Move != 10 || s.Fifteen.Move != 30 || s.Five.Speed != 2 || s.Fifteen.Speed != 2 {
		t.Fatal(s)
	}
	f.add(strategy.Board{Reference: "NK225", Time: 40, Bid: 1080, Ask: 1082})
	if short164(f, 40).Five.Known {
		t.Fatal("20秒空白を既知")
	}
}

// TestDay164ActualProtectionIdentity はCanonical含みと異なってもActual建値を保護し二重予約しません。
//
// 引数: t(*testing.T)。返り値: なし。
func TestDay164ActualProtectionIdentity(t *testing.T) {
	r := seededDay164(t, 4)
	aid := r.Actual.Active[0]
	cid := r.Canonical.Active[0]
	r.Canonical.Lots[cid].Entry = 1101
	doDay164(t, r, sample157(2, 102, 1011, 1013), nil, Short164{})
	if !r.Lots[aid].TenActivated || r.Lots[aid].ActivatedAt != 102 || r.Lots[aid].ActivatedIndex != 2 {
		t.Fatal("Actual+10未起動")
	}
	doDay164(t, r, sample157(3, 103, 1001, 1003), nil, Short164{})
	if len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Targets[0].ID != aid || len(r.Canonical.Pending) != 1 {
		t.Fatal("所有返済又は同期")
	}
	if e := r.projectNewDay164(sample157(3, 103, 1001, 1003)); e != nil {
		t.Fatal(e)
	}
	if len(r.Actual.Pending) != 1 {
		t.Fatal("再投影二重注文")
	}
	doDay164(t, r, sample157(4, 104, 991, 993), nil, Short164{})
	if r.Actual.Realized != -4600 || len(r.Actual.Active) != 0 {
		t.Fatal("次板gapを利益へ置換", r.Actual.Realized)
	}
}

// TestDay164HalfAndResidualFloor は実玉100円半量と残玉床、最良値維持を確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestDay164HalfAndResidualFloor(t *testing.T) {
	r := seededDay164(t, 3)
	id := r.Actual.Active[0]
	doDay164(t, r, sample157(2, 102, 1101, 1103), nil, Short164{})
	if r.Actual.Pending[0].Quantity != 23 {
		t.Fatal("半量")
	}
	doDay164(t, r, sample157(3, 103, 1091, 1093), nil, Short164{})
	if r.Actual.Lots[id].Remaining != 23 || r.Actual.Lots[id].Best != 100 {
		t.Fatal("部分利確で極値消失")
	}
	doDay164(t, r, sample157(4, 104, 1051, 1053), nil, Short164{})
	if r.Actual.Pending[0].Quantity != 23 || r.Actual.Pending[0].Reason != "protect_100floor" {
		t.Fatal("50円床")
	}
}

// TestDay164SingleLotHalfZero は一枚玉の半分0を注文せず、残り保護を有効にします。
//
// 引数: t(*testing.T)。返り値: なし。
func TestDay164SingleLotHalfZero(t *testing.T) {
	r := seededDay164(t, 3)
	a := r.Actual.Lots[r.Actual.Active[0]]
	c := r.Canonical.Lots[r.Canonical.Active[0]]
	a.Quantity = 1
	a.Remaining = 1
	c.Quantity = 1
	c.Remaining = 1
	doDay164(t, r, sample157(2, 102, 1101, 1103), nil, Short164{})
	if len(r.Actual.Pending) != 0 || !r.Lots[a.ID].Milestone100 {
		t.Fatal("0注文又は節目未使用")
	}
	doDay164(t, r, sample157(3, 103, 1051, 1053), nil, Short164{})
	if len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Quantity != 1 {
		t.Fatal("1枚残り床")
	}
}

// TestDay164NativeProfitQualification はSource仮想益でなくActual部分返済実益から資格を付けます。
//
// 引数: t(*testing.T)。返り値: なし。
func TestDay164NativeProfitQualification(t *testing.T) {
	for _, price := range []float64{1021, 981} {
		r := seededDay164(t, 1)
		id := r.Actual.Active[0]
		o := sample157(2, 102, price, price+2)
		doDay164(t, r, o, []strategy.Signal{closeSignalDay164("p", "a", 2, o)}, Short164{})
		if r.Lots[id] != nil && r.Lots[id].ResidualEligible {
			t.Fatal("約定前資格")
		}
		doDay164(t, r, sample157(3, 103, price, price+2), nil, Short164{})
		got := r.Lots[id] != nil && r.Lots[id].ResidualEligible
		if got != (price > 1001) {
			t.Fatal("Actual実益資格", price, got)
		}
	}
}

// TestDay164DelaySourceReductionAndEnd は延期中の減量・追加・終了と30秒境界を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestDay164DelaySourceReductionAndEnd(t *testing.T) {
	r := dayCase164(7)
	o := sample157(0, 100, 999, 1001)
	doDay164(t, r, o, []strategy.Signal{newSignal157("a", "core", 1, 1, 5, o)}, shortCase164(.5, 2))
	if len(r.Actual.Pending) != 0 {
		t.Fatal("待機前発注")
	}
	o = sample157(1, 105, 989, 991)
	doDay164(t, r, o, []strategy.Signal{closeSignalDay164("p", "a", 2, o), newSignal157("b", "core", 1, 1, 1, o)}, shortCase164(.5, 2))
	if r.Parents["core/1"].SourceQty != 40 {
		t.Fatal("源残量")
	}
	o = sample157(2, 130, 1009, 1011)
	doDay164(t, r, o, nil, shortCase164(3, 2))
	sum := 0
	for _, ord := range r.Actual.Pending {
		sum += ord.Quantity
		if ord.SourceID != "a" && ord.SourceID != "b" {
			t.Fatal("SourceID")
		}
	}
	if sum != 36 {
		t.Fatal("現在残量40/peak50と30秒解除", sum)
	}
	z := dayCase164(7)
	o = sample157(0, 100, 999, 1001)
	doDay164(t, z, o, []strategy.Signal{newSignal157("a", "core", 1, 1, 5, o)}, shortCase164(.5, 2))
	o = sample157(1, 110, 1009, 1011)
	doDay164(t, z, o, []strategy.Signal{closeSignalDay164("end", "a", 5, o)}, shortCase164(3, 2))
	if len(z.Actual.Pending) > 0 || z.States["core/1"].Deferred {
		t.Fatal("Source終了後復活")
	}
	z = dayCase164(7)
	o = sample157(0, 100, 999, 1001)
	doDay164(t, z, o, []strategy.Signal{newSignal157("a", "core", 1, 1, 5, o)}, shortCase164(.5, 2))
	doDay164(t, z, sample157(1, 130.001, 1009, 1011), nil, shortCase164(3, 2))
	if len(z.Actual.Pending) > 0 || !z.States["core/1"].Cancelled {
		t.Fatal("30秒超を解除")
	}
}

// TestDay164AddOnlyStopAndGate は初回50円損切りを混ぜず、追加の当時方向を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestDay164AddOnlyStopAndGate(t *testing.T) {
	r := seededDay164(t, 9)
	doDay164(t, r, sample157(2, 102, 941, 943), nil, Short164{})
	if len(r.Actual.Pending) > 0 {
		t.Fatal("初回50損切り混入")
	}
	o := sample157(3, 103, 1009, 1011)
	doDay164(t, r, o, []strategy.Signal{newSignal157("b", "core", 1, 1, 1, o)}, Short164{})
	doDay164(t, r, sample157(4, 104, 1009, 1011), nil, Short164{})
	doDay164(t, r, sample157(5, 105, 959, 961), nil, Short164{})
	if len(r.Actual.Pending) != 1 || r.Actual.Lots[r.Actual.Pending[0].Targets[0].ID].Kind != "source_add" {
		t.Fatal("追加IDだけの退出")
	}
	g := seededDay164(t, 8)
	o = sample157(2, 102, 1009, 1011)
	doDay164(t, g, o, []strategy.Signal{newSignal157("b", "core", 1, 1, 1, o)}, Short164{})
	if len(g.Actual.Pending) > 0 || g.Parents["core/1"].SourceQty != 60 {
		t.Fatal("未知追加拒否と論理量")
	}
}

// TestDay164ReentryAfterActualProtection は元親継続中も新波で再参加し、元返済では再開しません。
//
// 引数: t(*testing.T)。返り値: なし。
func TestDay164ReentryAfterActualProtection(t *testing.T) {
	r := seededDay164(t, 5)
	doDay164(t, r, sample157(2, 102, 1011, 1013), nil, Short164{})
	doDay164(t, r, sample157(3, 103, 1001, 1003), nil, Short164{})
	doDay164(t, r, sample157(4, 104, 1001, 1003), nil, shortCase164(1, 1))
	if !r.States["core/1"].WaveArmed || len(r.Actual.Pending) > 0 {
		t.Fatal("保護約定後の待機")
	}
	doDay164(t, r, sample157(5, 105, 981, 983), nil, shortCase164(-1, -1))
	doDay164(t, r, sample157(6, 106, 1001, 1003), nil, shortCase164(1, 1))
	if len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Kind != "reentry" || r.Actual.Pending[0].Quantity != 46 {
		t.Fatal("20逆行20回復の再参加")
	}
	doDay164(t, r, sample157(7, 107, 1001, 1003), nil, shortCase164(1, 1))
	if r.Actual.Lots[r.Actual.Active[0]].Kind != "reentry" {
		t.Fatal("Actual役割")
	}
	n := seededDay164(t, 5)
	o := sample157(2, 102, 991, 993)
	doDay164(t, n, o, []strategy.Signal{closeSignalDay164("end", "a", 5, o)}, shortCase164(1, 1))
	doDay164(t, n, sample157(3, 103, 991, 993), nil, shortCase164(1, 1))
	if n.States["core/1"].WaveArmed {
		t.Fatal("元損切り後の再参加混入")
	}
}

// TestDay164NativeCloseAndOwnProtectionNoDouble は元部分返済を優先して同玉を二重返済しません。
//
// 引数: t(*testing.T)。返り値: なし。
func TestDay164NativeCloseAndOwnProtectionNoDouble(t *testing.T) {
	r := seededDay164(t, 4)
	doDay164(t, r, sample157(2, 102, 1011, 1013), nil, Short164{})
	o := sample157(3, 103, 1001, 1003)
	doDay164(t, r, o, []strategy.Signal{closeSignalDay164("p", "a", 2, o)}, Short164{})
	total := 0
	for _, ord := range r.Actual.Pending {
		total += ord.Quantity
	}
	if total != 18 {
		t.Fatal("元部分返済以外の重複", total)
	}
	doDay164(t, r, sample157(4, 104, 1001, 1003), nil, Short164{})
	if r.Actual.Pending[0].Quantity != 28 {
		t.Fatal("次原行で残玉保護")
	}
}

// TestDay164MirrorAndCapacity は売り側の利益保護と両側上限を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestDay164MirrorAndCapacity(t *testing.T) {
	r := dayCase164(4)
	o := sample157(0, 100, 999, 1001)
	ss := supportPair157(1, 1, -1)
	if e := stepDay164(r, o, []strategy.Signal{newSignal157("a", "core", 1, -1, 5, o)}, ss, Short164{}); e != nil {
		t.Fatal(e)
	}
	if e := stepDay164(r, sample157(1, 101, 999, 1001), nil, ss, Short164{}); e != nil {
		t.Fatal(e)
	}
	if r.Actual.Risk.MaxShort != 100 {
		t.Fatal("強支持の上限")
	}
	if e := stepDay164(r, sample157(2, 102, 987, 989), nil, ss, Short164{}); e != nil {
		t.Fatal(e)
	}
	if e := stepDay164(r, sample157(3, 103, 997, 999), nil, ss, Short164{}); e != nil {
		t.Fatal(e)
	}
	if len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Side != 1 {
		t.Fatal("売り建値床")
	}
}

// TestDay164ExportConfigs は金融入力なしで固定条件のJSONを出力できます。
//
// 引数: t(*testing.T)。返り値: なし。環境変数が未設定なら保存しません。
func TestDay164ExportConfigs(t *testing.T) {
	v := configsDay164()
	if len(v) != 12 {
		t.Fatal("12条件")
	}
	ids := map[string]bool{}
	for _, c := range v {
		if ids[c.ID] || len(c.RuleHash) != 64 {
			t.Fatal("一意規則")
		}
		ids[c.ID] = true
	}
	if path := os.Getenv("EXPORT_DAY164_CONFIGS"); path != "" {
		b, e := json.MarshalIndent(v, "", "  ")
		if e != nil {
			t.Fatal(e)
		}
		if e = os.WriteFile(path, append(b, '\n'), 0600); e != nil {
			t.Fatal(e)
		}
	}
}

// equalRiskDay164 は手法ID接頭辞だけを除いて同じ時価履歴指標を比較します。
//
// 引数: a,b(Risk157)、ida,idb(string)。返り値: bool。
func equalRiskDay164(a, b Risk157, ida, idb string) bool {
	ra, _ := json.Marshal(a)
	rb, _ := json.Marshal(b)
	return strings.ReplaceAll(string(ra), ida, "共通") == strings.ReplaceAll(string(rb), idb, "共通")
}

// TestDay164SyncFallbackAndReservation は同Source不足時の同期先と既予約控除を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestDay164SyncFallbackAndReservation(t *testing.T) {
	r := seededDay164(t, 7)
	o := sample157(2, 102, 1009, 1011)
	doDay164(t, r, o, []strategy.Signal{newSignal157("b", "core", 1, 1, 1, o)}, Short164{})
	doDay164(t, r, sample157(3, 103, 1009, 1011), nil, Short164{})
	a := r.Actual.Lots[r.Actual.Active[0]]
	ca := r.Canonical.Lots[r.Canonical.Active[0]]
	cb := r.Canonical.Lots[r.Canonical.Active[1]]
	ca.Remaining = 10
	cb.Remaining = 45
	p := r.Parents[a.Parent]
	o = sample157(4, 104, 1021, 1023)
	n := r.protectDay164(p, o, a.ID, "protect_test", 20, supportPair157(.8, .5, 1)[1])
	if n != 20 {
		t.Fatal(n)
	}
	if r.Canonical.reservedClose(ca.ID) != 10 || r.Canonical.reservedClose(cb.ID) != 10 {
		t.Fatal("同源優先と不足FIFO")
	}
	n = r.protectDay164(p, o, a.ID, "protect_test", 50, supportPair157(.8, .5, 1)[1])
	if n != 26 || r.Actual.reservedClose(a.ID) != 46 || r.Canonical.reservedClose(cb.ID) != 36 {
		t.Fatal("既予約の再消費", n)
	}
	if e := r.projectNewDay164(o); e != nil {
		t.Fatal(e)
	}
	for _, ord := range r.Actual.Pending {
		if len(ord.Targets) == 0 {
			t.Fatal("同期後の再新規")
		}
	}
	doDay164(t, r, sample157(5, 105, 1021, 1023), nil, Short164{})
	al, as := r.Actual.position(p.Key, "")
	cl, cs := r.Canonical.position(p.Key, "")
	if al-as != cl-cs || al != 9 {
		t.Fatal("同期後の純量")
	}
}

// TestDay164SameRowInitialAndRejectedAddition は同時通知で初回を追加と誤認せず源残量を保存します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestDay164SameRowInitialAndRejectedAddition(t *testing.T) {
	r := dayCase164(8)
	o := sample157(0, 100, 999, 1001)
	doDay164(t, r, o, []strategy.Signal{newSignal157("a", "core", 1, 1, 5, o), newSignal157("b", "core", 1, 1, 1, o)}, Short164{})
	p := r.Parents["core/1"]
	if p.OldInitial != 50 || p.SourceQty != 60 || p.SourceHolds["b-玉"] != 10 || len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Quantity != 46 {
		t.Fatal("同原行の初回・追加")
	}
}
