package main

import (
	"reflect"
	"testing"
)

// r2Case は固定第二巡候補の人工口座を作ります。
//
// 引数: t(*testing.T)、id(string)。返り値: *Result。実データは読みません。
func r2Case(t *testing.T, id string) *Result {
	t.Helper()
	var configs []Config
	if err := readJSON("../configs153r2.json", &configs); err != nil {
		t.Fatal(err)
	}
	for _, cfg := range configs {
		if cfg.ID == id {
			return newResult(Scene{Session: "人工", Kind: "Day", Start: 100, ForceClose: 900, End: 1000}, "NK225", cfg)
		}
	}
	t.Fatal("人工候補ID不明")
	return nil
}

// r2Step は傾きと当時平均を明示した人工板を一行だけ処理します。
//
// 引数: t(*testing.T)、c(*Result)、q(Quote)、f/short(Feature)。返り値: なし。
func r2Step(t *testing.T, c *Result, q Quote, f, short Feature) {
	t.Helper()
	if err := step(c, q, f, short); err != nil {
		t.Fatal(err)
	}
}

// TestRearmAfterFullClose153R2 は全返済行の冷却を使わず、返済後の新しい冷却だけを許します。
//
// 引数: t(*testing.T)。返り値: なし。同時計でも次原行なら冷却観測は可能です。
func TestRearmAfterFullClose153R2(t *testing.T) {
	c := r2Case(t, "R01")
	strong := Feature{Known: true, MA: 9990, Slope: 1}
	cool := Feature{Known: true, MA: 9990, Slope: .125}
	r2Step(t, c, testQuote(0, 100, 9999, 10000), strong, strong)
	if c.Armed[1] || !c.Armed[-1] {
		t.Fatal("初回判断が買いだけを消費しない")
	}
	r2Step(t, c, testQuote(1, 101, 9999, 10000), strong, strong)
	queue(c, testQuote(2, 102, 9999, 10000), cool, "close", "人工全返済", -1, c.Quantity)
	r2Step(t, c, testQuote(3, 103, 9999, 10000), cool, cool)
	if c.Armed[1] || c.ArmResetIndex[1] != 3 {
		t.Fatal("全返済行の冷却で再準備した")
	}
	r2Step(t, c, testQuote(4, 114, 9999, 10000), strong, strong)
	if c.Pending != nil || c.Rejections["同方向の冷却待ち"] != 1 {
		t.Fatal("強いまま再参加した")
	}
	r2Step(t, c, testQuote(5, 115, 9999, 10000), Feature{Slope: .01}, strong)
	if c.Armed[1] {
		t.Fatal("未知を冷却扱いした")
	}
	r2Step(t, c, testQuote(6, 115, 9999, 10000), cool, cool)
	if !c.Armed[1] {
		t.Fatal("次原行の0.125到達で再準備しない")
	}
	r2Step(t, c, testQuote(7, 116, 9999, 10000), strong, strong)
	if c.Pending == nil || c.Armed[1] {
		t.Fatal("冷却後の再増勢に再参加しない")
	}
}

// TestHeldCoolingDoesNotSurviveFullClose153R2 は保有中の冷却を次の売買へ持ち越しません。
//
// 引数: t(*testing.T)。返り値: なし。反対側の再準備とは独立です。
func TestHeldCoolingDoesNotSurviveFullClose153R2(t *testing.T) {
	c := r2Case(t, "R05")
	f := Feature{Known: true, Slope: 1}
	r2Step(t, c, testQuote(0, 100, 9999, 10000), f, f)
	r2Step(t, c, testQuote(1, 101, 9999, 10000), Feature{Known: true, Slope: .1}, f)
	if !c.Armed[1] {
		t.Fatal("保有中の冷却を記録しない")
	}
	queue(c, testQuote(2, 102, 9999, 10000), f, "close", "人工全返済", -1, c.Quantity)
	r2Step(t, c, testQuote(3, 103, 9999, 10000), f, f)
	if c.Armed[1] || !c.Armed[-1] {
		t.Fatal("全返済で当側だけをリセットしない")
	}
}

// TestAlignmentSymmetric153R2 は中値位置と短期傾きの入口条件を買売対称に確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAlignmentSymmetric153R2(t *testing.T) {
	for _, side := range []int{-1, 1} {
		for _, mode := range []string{"正常", "短期未知", "平均位置逆", "短期逆", "短期ゼロ", "平均同値"} {
			c := r2Case(t, "R02")
			q := testQuote(0, 100, 9999, 10001)
			f := Feature{Known: true, MA: 10000 - float64(side)*10, Slope: float64(side)}
			short := Feature{Known: true, Slope: float64(side)}
			switch mode {
			case "短期未知":
				short.Known = false
			case "平均位置逆":
				f.MA = 10000 + float64(side)*10
			case "短期逆":
				short.Slope *= -1
			case "短期ゼロ":
				short.Slope = 0
			case "平均同値":
				f.MA = 10000
			}
			r2Step(t, c, q, f, short)
			if (c.Pending != nil) != (mode == "正常") {
				t.Fatalf("方向%d 条件%sの判定不一致", side, mode)
			}
			if c.Pending == nil && !c.Armed[side] {
				t.Fatal("見送りだけで準備を消費した")
			}
		}
	}
}

// TestGuardUsesLiquidationPrice153R2 は追加の順行を中値ではなく返済側価格で測ります。
//
// 引数: t(*testing.T)。返り値: なし。
func TestGuardUsesLiquidationPrice153R2(t *testing.T) {
	for _, side := range []int{-1, 1} {
		c := r2Case(t, "R04")
		c.Side, c.Quantity = side, 2
		c.Current = &Parent{Anchor: 10000}
		c.LastNewPrice = 10000 + float64(side)
		q := testQuote(0, 100, 10002, 10003)
		if side < 0 {
			q.Bid, q.Ask = 9997, 9998
		}
		if !allocationAllowed(c, q, 4) {
			t.Fatal("返済側の丁度1spread順行を拒否")
		}
		q.Bid -= float64(side) * .5
		q.Ask -= float64(side) * .5
		if allocationAllowed(c, q, 4) {
			t.Fatal("中値だけ1spreadの順行で追加")
		}
		c.LastNewPrice = 10000 - float64(side)*10
		q.Bid, q.Ask = 9999.5, 10000.5
		if allocationAllowed(c, q, 4) {
			t.Fatal("初回anchorに対する損益が負なのに追加")
		}
		if allocationAllowed(c, q, 3) || !allocationAllowed(c, q, 0) {
			t.Fatal("1枚差又は含み損減量の判定が不正")
		}
	}
}

// TestGuardNewFillUpdatesReference153R2 は追加だけが次の順行起点を更新することを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestGuardNewFillUpdatesReference153R2(t *testing.T) {
	c := r2Case(t, "R08")
	f := Feature{Known: true, MA: 9990, Slope: .5}
	r2Step(t, c, testQuote(0, 100, 9999, 10000), f, f)
	r2Step(t, c, testQuote(1, 101, 9999, 10000), f, f)
	if c.Quantity != 2 || c.LastNewPrice != 10000 {
		t.Fatal("初回数量又は約定価格が不正")
	}
	f.Slope = 1
	r2Step(t, c, testQuote(2, 111, 10001, 10002), f, f)
	if c.Pending == nil || c.Pending.Quantity != 2 || c.Pending.LastNewPrice != 10000 {
		t.Fatal("順行2枚追加の判断記録が不正")
	}
	r2Step(t, c, testQuote(3, 112, 10002, 10003), f, f)
	if c.LastNewPrice != 10003 || c.Current.Anchor != 10000 {
		t.Fatal("追加価格又は親固定anchorが不正")
	}
	f.Slope = .5
	r2Step(t, c, testQuote(4, 122, 9999, 10000), f, f)
	if c.Pending == nil || c.Pending.Action != "close" || c.Pending.Quantity != 2 {
		t.Fatal("損状態で2枚縮小しない")
	}
	r2Step(t, c, testQuote(5, 123, 9998, 9999), f, f)
	if c.LastNewPrice != 10003 || c.LastNewTime != 112 {
		t.Fatal("減量の約定価格を追加順行の起点にした")
	}
}

// TestGuardOneQuantityNoChurn153R2 は1枚差の往復を止め、2枚以上の縮小だけを許します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestGuardOneQuantityNoChurn153R2(t *testing.T) {
	c := r2Case(t, "R08")
	f := Feature{Known: true, MA: 9990, Slope: 1.25}
	r2Step(t, c, testQuote(0, 100, 9999, 10000), f, f)
	r2Step(t, c, testQuote(1, 101, 9999, 10000), f, f)
	f.Slope = 1
	r2Step(t, c, testQuote(2, 111, 9999, 10000), f, f)
	if c.Pending != nil || c.Quantity != 5 {
		t.Fatal("1枚だけ縮小した")
	}
	f.Slope = .75
	r2Step(t, c, testQuote(3, 112, 9999, 10000), f, f)
	if c.Pending == nil || c.Pending.Quantity != 2 {
		t.Fatal("2枚差の縮小を止めた")
	}
}

// TestR2PriceDefenseIgnoresEntryGates は未知角度や再準備待ちでも価格防御を止めません。
//
// 引数: t(*testing.T)。返り値: なし。
func TestR2PriceDefenseIgnoresEntryGates(t *testing.T) {
	c := r2Case(t, "R04")
	f := Feature{Known: true, MA: 9990, Slope: 1}
	r2Step(t, c, testQuote(0, 100, 9999, 10000), f, f)
	r2Step(t, c, testQuote(1, 101, 9999, 10000), f, f)
	r2Step(t, c, testQuote(2, 102, 9980, 9981), Feature{}, Feature{})
	if c.Pending == nil || c.Pending.Reason != "初期逆行12bp" || c.Pending.Quantity != 4 {
		t.Fatal("未知又は未準備を価格防御の条件にした")
	}
}

// TestR2NoBindingGatesKeepOriginalPath は新条件が妨げない経路で元の入口出口を維持します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestR2NoBindingGatesKeepOriginalPath(t *testing.T) {
	base := testCase("entry", "D")
	c := r2Case(t, "R02")
	for i, v := range []struct{ at, bid, slope float64 }{{100, 9999, 1}, {101, 9999, 1}, {102, 10001, 2.2}, {103, 10001, 1}, {104, 10002, 1}, {115, 10000, -.1}, {116, 10000, -1}, {117, 10000, -1}, {900, 9990, -1}, {901, 9990, -1}} {
		f := Feature{Known: true, MA: v.bid - 10, Slope: v.slope}
		if v.slope < 0 {
			f.MA = v.bid + 10
		}
		q := testQuote(int64(i), v.at, v.bid, v.bid+1)
		r2Step(t, base, q, f, f)
		r2Step(t, c, q, f, f)
	}
	if !reflect.DeepEqual(base.Events, c.Events) || !reflect.DeepEqual(base.Lots, c.Lots) {
		t.Fatal("新条件が妨げない経路で旧売買・約定が変わる")
	}
}
