package main

import (
	"math"
	"reflect"
	"testing"
)

// aq は人工正常板を生成します。
//
// 引数: i(int64)、at/mid(float64)。返り値: Quoteは気配差2の人工板です。
func aq(i int64, at, mid float64) Quote {
	return Quote{Index: i, Line: i + 1, Time: at, Bid: mid - 1, Ask: mid + 1}
}

// af は人工の既知傾きを生成します。
//
// 引数: s(float64)。返り値: Featureです。
func af(s float64) Feature { return Feature{Known: true, MA: 10000, Previous: 10000, Slope: s} }

// ac は試験用の独立口座を作ります。
//
// 引数: alloc/exit(string)。返り値: *Resultです。
func ac(alloc, exit string) *Result {
	return newResult(Scene{Session: "人工_Day", Kind: "Day", Start: 0, End: 1000, ForceClose: 900, Partial: true}, "NK225", Config{ID: "人工", Window: 60, Lag: 30, Allocation: alloc, Exit: exit})
}

// astep は人工行の処理エラーを検査します。
//
// 引数: t(*testing.T)、c(*Result)、q(Quote)、f(Feature)。返り値: なし。
func astep(t *testing.T, c *Result, q Quote, f Feature) {
	t.Helper()
	if err := step(c, q, f); err != nil {
		t.Fatal(err)
	}
}

// near は独立期待値との浮動小数差を検査します。
//
// 引数: t(*testing.T)、got/want(float64)。返り値: なし。
func near(t *testing.T, got, want float64) {
	t.Helper()
	if math.Abs(got-want) > 1e-7 {
		t.Fatalf("実測%g 期待%g", got, want)
	}
}

// TestAuditTimeIntegral は原行数でなく過去の既知時間だけが面積になることを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditTimeIntegral(t *testing.T) {
	a := Average{}
	for _, q := range []Quote{aq(0, 0, 100), aq(1, 60, 200), aq(2, 90, 300)} {
		if err := a.Add(q); err != nil {
			t.Fatal(err)
		}
	}
	f := a.Get(60, 30)
	if !f.Known {
		t.Fatal("90秒で既知でない")
	}
	near(t, f.MA, 150)
	near(t, f.Previous, 100)
	near(t, f.Slope, 10000)
	a.Add(aq(3, 90, 900))
	same := a.Get(60, 30)
	if !reflect.DeepEqual(f, same) {
		t.Fatal("同時刻の未来保持値が過去面積を変更")
	}
	a.Add(aq(4, 100, 900))
	m, ok := a.mean(90, 60)
	if !ok {
		t.Fatal("過去窓消失")
	}
	near(t, m, 150)
}

// TestAuditUnknownIntervals は欠測期限・異常板の前後を平均へ混ぜないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditUnknownIntervals(t *testing.T) {
	a := Average{}
	a.Add(aq(0, 0, 100))
	a.Add(aq(1, 121, 100))
	if a.Get(60, 30).Known {
		t.Fatal("120秒超欠測を既知扱い")
	}
	a.Add(aq(2, 210, 100))
	if a.Get(60, 30).Known {
		t.Fatal("窓左端に残る欠測を無視")
	}
	a.Add(aq(3, 211, 100))
	if !a.Get(60, 30).Known {
		t.Fatal("完全回復後も未知")
	}
	a.Add(Quote{Index: 4, Time: 212, Bid: 100, Ask: 99})
	a.Add(aq(5, 213, 100))
	a.Add(aq(6, 302, 100))
	if a.Get(60, 30).Known {
		t.Fatal("異常板区間を除去")
	}
	a.Add(aq(7, 303, 100))
	if !a.Get(60, 30).Known {
		t.Fatal("異常板後90秒で復帰しない")
	}
}

// TestAuditEntryNextRowAndGapLoss は判断時の買気配やトレール予定値で楽観約定しないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditEntryNextRowAndGapLoss(t *testing.T) {
	c := ac("entry", "T")
	astep(t, c, aq(0, 0, 10000), af(.25))
	if len(c.Events) != 0 {
		t.Fatal("同原行で約定")
	}
	astep(t, c, aq(1, 1, 10000), af(.25))
	near(t, c.Current.Anchor, 10001)
	astep(t, c, aq(2, 2, 10010), af(.25))
	if !c.Current.Activated {
		t.Fatal("利益追尾未開始")
	}
	astep(t, c, aq(3, 3, 10006), af(.25))
	if c.Pending == nil || c.Pending.Reason != "利益開始後3bp戻り" {
		t.Fatal("追尾返済未発注")
	}
	astep(t, c, aq(4, 4, 9995), af(.25))
	near(t, c.Gross, -700)
	if c.Quantity != 0 {
		t.Fatal("全返済でない")
	}
	if c.Events[1].FillIndex <= c.Events[1].Order.DecisionIndex {
		t.Fatal("未来順序不整合")
	}
}

// TestAuditFixedAnchorAndFIFO は追加・縮小で親の建値・傾き基準を変えず、古い玉から減らすことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditFixedAnchorAndFIFO(t *testing.T) {
	c := ac("dynamic", "T")
	astep(t, c, aq(0, 0, 10000), af(.5))
	astep(t, c, aq(1, 1, 10000), af(.5))
	astep(t, c, aq(2, 11, 10004), af(2.5))
	astep(t, c, aq(3, 12, 10004), af(2.5))
	if c.Quantity != 10 {
		t.Fatalf("追加後%d枚", c.Quantity)
	}
	near(t, c.Current.Anchor, 10001)
	near(t, c.Current.EntrySlope, .5)
	near(t, c.Current.PeakSlope, 2.5)
	astep(t, c, aq(4, 22, 10004), af(-1))
	if c.Pending == nil || c.Pending.Quantity != 9 || c.Pending.Reason != "比例枚数へ縮小" {
		t.Fatal("弱化で最低1枚へ減らない")
	}
	astep(t, c, aq(5, 23, 10004), af(-1))
	if c.Quantity != 1 || c.Lots[0].Quantity != 0 || c.Lots[1].Quantity != 1 {
		t.Fatal("FIFO減量不整合")
	}
	near(t, c.Current.Anchor, 10001)
	near(t, c.Current.EntrySlope, .5)
	near(t, c.Current.PeakSlope, 2.5)
	if err := finish(c); err != nil {
		t.Fatal(err)
	}
}

// TestAuditUnknownKeepsQuantityButNotProtection は未知傾きで増減しない一方、既存玉の価格防御を維持することを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditUnknownKeepsQuantityButNotProtection(t *testing.T) {
	c := ac("dynamic", "D")
	astep(t, c, aq(0, 0, 10000), af(2.5))
	astep(t, c, aq(1, 1, 10000), af(2.5))
	astep(t, c, aq(2, 20, 10000), Feature{})
	if c.Pending != nil || c.Quantity != 10 {
		t.Fatal("未知角度で数量変更")
	}
	astep(t, c, aq(3, 21, 9988), Feature{})
	if c.Pending == nil || c.Pending.Reason != "初期逆行12bp" || c.Pending.Quantity != 10 {
		t.Fatal("未知角度で防御停止")
	}
}

// TestAuditAngleExitPrecedesReduction はD全返済が数量減量より優先し、反対方向を最高傾きへ混ぜないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditAngleExitPrecedesReduction(t *testing.T) {
	c := ac("dynamic", "D")
	astep(t, c, aq(0, 0, 10000), af(1))
	astep(t, c, aq(1, 1, 10000), af(1))
	astep(t, c, aq(2, 11, 10000), af(-100))
	if c.Pending == nil || c.Pending.Reason != "傾きの方向反転" || c.Pending.Quantity != c.Quantity {
		t.Fatal("全返済優先でない")
	}
	near(t, c.Current.PeakSlope, 1)
	d := ac("entry", "D")
	astep(t, d, aq(0, 0, 10000), af(.5))
	astep(t, d, aq(1, 1, 10000), af(.5))
	astep(t, d, aq(2, 2, 10000), af(1))
	astep(t, d, aq(3, 3, 10000), af(.5))
	if d.Pending == nil || d.Pending.Reason != "2倍へ増勢後に傾き半減" {
		t.Fatal("半減出口未発火")
	}
}

// TestAuditReservationsAndTerminal は不正板の間に重複注文せず、場末を跨ぐ送信済新規も返済することを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditReservationsAndTerminal(t *testing.T) {
	c := ac("dynamic", "T")
	c.ForceClose = 10
	astep(t, c, aq(0, 9, 10000), af(2.5))
	astep(t, c, Quote{Index: 1, Line: 2, Time: 10, Bid: 100, Ask: 99}, Feature{})
	if c.Quantity != 0 || c.Pending == nil || c.Pending.Quantity != 10 || c.Sequence != 1 {
		t.Fatal("不正板中の新規予約不整合")
	}
	astep(t, c, aq(2, 11, 10000), af(2.5))
	if c.Quantity != 10 || c.Pending == nil || c.Pending.Action != "close" {
		t.Fatal("境界後新規の返済未発注")
	}
	astep(t, c, aq(3, 12, 9999), af(2.5))
	c.Partial = false
	if err := finish(c); err != nil {
		t.Fatal(err)
	}
	if c.FlatAt != 12 {
		t.Fatal("完済時刻不整合")
	}
}

// TestAuditFixedQuantityControl は固定1枚と10枚で経路が同じとなり、会計だけ10倍になることを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditFixedQuantityControl(t *testing.T) {
	one, ten := ac("fixed1", "D"), ac("fixed10", "D")
	qs := []Quote{aq(0, 0, 10000), aq(1, 1, 10000), aq(2, 2, 10010), aq(3, 3, 10006), aq(4, 4, 10005)}
	for _, q := range qs {
		astep(t, one, q, af(.5))
		astep(t, ten, q, af(.5))
	}
	if len(one.Events) != len(ten.Events) {
		t.Fatal("数量で発注回数変化")
	}
	for i, a := range one.Events {
		b := ten.Events[i]
		if a.Order.DecisionIndex != b.Order.DecisionIndex || a.FillIndex != b.FillIndex || a.Price != b.Price || a.Order.Side != b.Order.Side {
			t.Fatal("数量で経路変化")
		}
		near(t, b.Gross, a.Gross*10)
	}
	near(t, ten.Gross, one.Gross*10)
}

// TestAuditPrefixAndMirror は未来枝分かれ前の状態が一致し、上下反転が同じ数量と収支になることを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditPrefixAndMirror(t *testing.T) {
	a, b, mirror := ac("dynamic", "D"), ac("dynamic", "D"), ac("dynamic", "D")
	prices := []float64{10000, 10000, 10004, 10004, 10004, 10004}
	slopes := []float64{.5, .5, 2.5, 2.5, -1, -1}
	times := []float64{0, 1, 11, 12, 22, 23}
	for i, p := range prices {
		q := aq(int64(i), times[i], p)
		astep(t, a, q, af(slopes[i]))
		astep(t, b, q, af(slopes[i]))
		astep(t, mirror, aq(int64(i), times[i], 20000-p), af(-slopes[i]))
	}
	if !reflect.DeepEqual(a, b) {
		t.Fatal("同一prefix状態不一致")
	}
	near(t, a.Gross, mirror.Gross)
	if len(a.Events) != len(mirror.Events) {
		t.Fatal("買売鏡像発注数不一致")
	}
	for i, e := range a.Events {
		m := mirror.Events[i]
		if e.Order.Side != -m.Order.Side || e.Order.Quantity != m.Order.Quantity || e.Order.DecisionIndex != m.Order.DecisionIndex {
			t.Fatal("買売鏡像不一致")
		}
	}
	astep(t, a, aq(6, 100, 12000), af(5))
	astep(t, b, aq(6, 100, 8000), af(-5))
	for i := 0; i < 3; i++ {
		if !reflect.DeepEqual(a.Events[i], b.Events[i]) {
			t.Fatal("未来価格で過去約定が変化")
		}
	}
}
