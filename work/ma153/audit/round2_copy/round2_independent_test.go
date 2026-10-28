package main

import "testing"

// rcase は第二巡の人工口座を作ります。
//
// 引数: id/allocation/exit(string)。返り値: *Resultです。
func rcase(id, allocation, exit string) *Result {
	c := ac(allocation, exit)
	c.Config.ID = id
	return c
}

// rstep は短期傾きと主傾きを独立して人工行へ渡します。
//
// 引数: t(*testing.T)、c(*Result)、q(Quote)、f/s(Feature)。返り値: なし。
func rstep(t *testing.T, c *Result, q Quote, f, s Feature) {
	t.Helper()
	if err := step(c, q, f, s); err != nil {
		t.Fatal(err)
	}
}

// TestAuditRound2ColdAfterFillOnly は全返済行の弱化を再準備に使わず、後続原行だけを使うことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditRound2ColdAfterFillOnly(t *testing.T) {
	c := rcase("R01", "entry", "D")
	for _, v := range []struct {
		i          int64
		at, mid, s float64
	}{{0, 0, 10000, .5}, {1, 1, 10000, .5}, {2, 2, 10008, .5}, {3, 3, 10004, .5}, {4, 4, 10004, .1}} {
		rstep(t, c, aq(v.i, v.at, v.mid), af(v.s), Feature{})
	}
	if c.Quantity != 0 || c.Armed[1] || c.ArmResetIndex[1] != 4 {
		t.Fatal("全返済fill同原行で同方向を再準備")
	}
	rstep(t, c, aq(5, 4, 10004), af(.1), Feature{})
	if !c.Armed[1] {
		t.Fatal("後続原行の冷却が無効")
	}
	rstep(t, c, aq(6, 14, 10004), af(.5), Feature{})
	if c.Pending == nil || c.Pending.Action != "new" || c.Pending.Side != 1 {
		t.Fatal("冷却と10秒経過後の再参加が不可")
	}
}

// TestAuditRound2NoColdNoReentry は古い傾きの残存だけでは同方向再参加できず、反対側準備は独立であることを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditRound2NoColdNoReentry(t *testing.T) {
	c := rcase("R01", "entry", "D")
	for _, v := range []struct {
		i          int64
		at, mid, s float64
	}{{0, 0, 10000, .5}, {1, 1, 10000, .5}, {2, 2, 10008, .5}, {3, 3, 10004, .5}, {4, 4, 10004, .5}, {5, 14, 10004, .5}} {
		rstep(t, c, aq(v.i, v.at, v.mid), af(v.s), Feature{})
	}
	if c.Pending != nil || c.Armed[1] {
		t.Fatal("冷却なしの再参加")
	}
	rstep(t, c, aq(6, 15, 10004), Feature{}, Feature{})
	if c.Armed[1] {
		t.Fatal("未知角度を冷却に使用")
	}
	rstep(t, c, aq(7, 16, 10004), af(-.5), Feature{})
	if c.Pending == nil || c.Pending.Side != -1 {
		t.Fatal("反対側準備を同方向停止へ巻き込み")
	}
}

// TestAuditRound2EntryAlignment は短期未知・逆向き・価格逆側を新規だけで拒否することを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditRound2EntryAlignment(t *testing.T) {
	for _, side := range []int{1, -1} {
		c := rcase("R02", "entry", "D")
		sg := float64(side)
		rstep(t, c, aq(0, 0, 10000+sg*10), af(sg*.5), Feature{})
		if c.Pending != nil {
			t.Fatal("短期未知を許可")
		}
		rstep(t, c, aq(1, 1, 10000+sg*10), af(sg*.5), af(-sg))
		if c.Pending != nil {
			t.Fatal("短期逆向きを許可")
		}
		rstep(t, c, aq(2, 2, 10000-sg*10), af(sg*.5), af(sg))
		if c.Pending != nil {
			t.Fatal("現在価格の逆側を許可")
		}
		rstep(t, c, aq(3, 3, 10000+sg*10), af(sg*.5), af(sg))
		if c.Pending == nil || c.Pending.Side != side {
			t.Fatal("一致時にも拒否")
		}
		rstep(t, c, aq(4, 4, 10000+sg*10), Feature{}, Feature{})
		if c.Quantity != 2 {
			t.Fatal("送信済み注文へ未来の短期状態を適用")
		}
	}
}

// TestAuditRound2GuardedAddAndLossReduction は初回基準正益・直前追加価格・現在幅・差2枚の接続と、損失中減量を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditRound2GuardedAddAndLossReduction(t *testing.T) {
	c := rcase("R08", "dynamic", "T")
	rstep(t, c, aq(0, 0, 10010), af(.5), af(.5))
	rstep(t, c, aq(1, 1, 10010), af(.5), af(.5))
	rstep(t, c, aq(2, 11, 10011), af(2.5), af(2.5))
	if c.Pending != nil {
		t.Fatal("初回基準で含み負又はゼロなのに追加")
	}
	rstep(t, c, aq(3, 12, 10013), af(2.5), af(2.5))
	if c.Pending != nil {
		t.Fatal("前new価格からspread未満で追加")
	}
	rstep(t, c, aq(4, 13, 10014), af(2.5), af(2.5))
	if c.Pending == nil || c.Pending.Quantity != 8 {
		t.Fatal("spread以上の順行でも追加不可")
	}
	rstep(t, c, aq(5, 14, 10014), af(2.5), af(2.5))
	near(t, c.Current.Anchor, 10011)
	near(t, c.LastNewPrice, 10015)
	rstep(t, c, aq(6, 24, 10014), af(2.25), af(2.25))
	if c.Pending != nil {
		t.Fatal("差1枚の調整を許可")
	}
	rstep(t, c, aq(7, 25, 10011), af(1.75), af(1.75))
	if c.Pending == nil || c.Pending.Action != "close" || c.Pending.Quantity != 3 {
		t.Fatal("含み損中に数量減量できない")
	}
	rstep(t, c, aq(8, 26, 10011), af(1.75), af(1.75))
	if c.Quantity != 7 {
		t.Fatal("縮小数量不整合")
	}
	near(t, c.Current.Anchor, 10011)
	near(t, c.LastNewPrice, 10015)
}

// TestAuditRound2AddedPriceCanGap は追加判断条件が成立しても次板の約定悪化を消さないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditRound2AddedPriceCanGap(t *testing.T) {
	c := rcase("R08", "dynamic", "T")
	rstep(t, c, aq(0, 0, 10010), af(.5), af(.5))
	rstep(t, c, aq(1, 1, 10010), af(.5), af(.5))
	rstep(t, c, aq(2, 11, 10014), af(2.5), af(2.5))
	if c.Pending == nil {
		t.Fatal("人工追加なし")
	}
	rstep(t, c, aq(3, 12, 10000), af(2.5), af(2.5))
	if c.Quantity != 10 || c.Lots[1].Price != 10001 {
		t.Fatal("当時発注を未来価格で選別")
	}
	near(t, c.Current.Anchor, 10011)
	near(t, c.LastNewPrice, 10001)
	if c.Unrealized >= 0 {
		t.Fatal("原玉の含み損を消した")
	}
}
