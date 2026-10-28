package main

import (
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
	"reflect"
	"testing"
)

// adversaryResult165 は実資料を読まない米国後の人工運転を作ります。
//
// 引数: number(int、手法番号)。返り値: *Result165。
func adversaryResult165(number int) *Result165 {
	return newResult165(configs165()[number-1], Scene{Start: 0, USOpen: 100, ForceClose: 10000})
}

// adversaryQuote165 は原行番号と正常気配を明示した人工観測を作ります。
//
// 引数: index(int64)、bid/ask(float64)。返り値: strategy.Observation。
func adversaryQuote165(index int64, bid, ask float64) strategy.Observation {
	return strategy.Observation{Reference: "NK225", Index: index, Time: 1000 + float64(index), Received: 1000 + float64(index), Last: (bid + ask) / 2, Bid: bid, Ask: ask, QuoteOK: ask > bid && bid > 0}
}

// adversarySignal165 は同親のSource通知と所有対象を明示します。
//
// 引数: id/action(string)、side/quantity(int)、targets(...strategy.LotTarget)。返り値: strategy.Signal。
func adversarySignal165(id, action string, side, quantity int, targets ...strategy.LotTarget) strategy.Signal {
	return strategy.Signal{ID: "後半/" + id, Owner: "後半/core", Campaign: 1, Action: action, Side: side, Quantity: quantity, Targets: targets}
}

// adversaryStep165 は金融原板を使わず通常の約定・判断順を進めます。
//
// 引数: t(*testing.T)、r(*Result165)、o(strategy.Observation)、v(StateView165)、signals(...strategy.Signal)。返り値: なし。
func adversaryStep165(t *testing.T, r *Result165, o strategy.Observation, v StateView165, signals ...strategy.Signal) {
	t.Helper()
	if err := r.step165Policy(o, signals, v); err != nil {
		t.Fatal(err)
	}
}

// adversarySeed165 は初回50microを次原行で約定させます。
//
// 引数: t(*testing.T)、number(int)。返り値: *Result165、実所有ID(string)。
func adversarySeed165(t *testing.T, number int) (*Result165, string) {
	t.Helper()
	r := adversaryResult165(number)
	adversaryStep165(t, r, adversaryQuote165(0, 990, 1000), StateView165{}, adversarySignal165("初回", "new", 1, 5))
	adversaryStep165(t, r, adversaryQuote165(1, 990, 1000), StateView165{})
	if len(r.Actual.Active) != 1 {
		t.Fatal("人工初回がありません")
	}
	return r, r.Actual.Active[0]
}

// TestAdversary165QuantityDenominator は価格のみ更新が0寄与で数量平均の分母へ入る現尺度を固定します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAdversary165QuantityDenominator(t *testing.T) {
	h := &BookFeatures165{}
	a := bookTest165(100, 1000, 1010)
	h.add165(a, 0, 1)
	b := a
	b.AskQuantity = 30
	b.AskLevels[0].Quantity = 30
	h.add165(b, 1, 2)
	c := bookTest165(100, 1010, 1020)
	h.add165(c, 2, 3)
	z := bookTest165(100, 1020, 1030)
	h.add165(z, 3, 4)
	got := between165(h.Frames[0], h.Frames[3])
	if got.QuantityEvents != 3 || got.Events != 2 || math.Abs(got.AskRefill-1.0/6) > 1e-12 {
		t.Fatalf("現尺度は価格又は数量の3更新で平均する必要があります: %+v", got)
	}
	for i := 4; i < 20; i++ {
		h.add165(z, int64(i), int64(i+1))
	}
	last := between165(h.Frames[0], h.Frames[len(h.Frames)-1])
	if last.QuantityEvents != 3 || last.AskRefill != got.AskRefill {
		t.Fatal("同値板の複製で平均が変わりました")
	}
}

// TestAdversary165ClockPrefixAndQuantityOnly は同時計の後行改変を前行へ伝播させず数量のみの行を窓へ含めます。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAdversary165ClockPrefixAndQuantityOnly(t *testing.T) {
	h1, h2 := &BookFeatures165{}, &BookFeatures165{}
	var before Feature165
	for i := int64(0); i <= 8; i++ {
		b := bookTest165(100, 1000+float64(i)*10, 1010+float64(i)*10)
		a, z := h1.add165(b, i, i+1), h2.add165(b, i, i+1)
		if !reflect.DeepEqual(a, z) {
			t.Fatal("同時計prefixが不一致")
		}
		before = a
	}
	x := bookTest165(100, 1080, 1090)
	x.BidQuantity = 90
	x.BidLevels[0].Quantity = 90
	a := h1.add165(x, 9, 10)
	z := h2.add165(bookTest165(100, 900, 910), 9, 10)
	if !a.Event8.Known || a.Event8.Events != 8 || a.Changed || a.Event8.BidRefill <= 0 {
		t.Fatal("価格8イベント後の数量だけの原行を落としました")
	}
	if before.Current.Bid != 1080 || before.Event8.UpFraction != 1 || before.Event8.Elapsed != 0 || reflect.DeepEqual(a, z) {
		t.Fatal("過去値書換え又は時計とイベントの混同")
	}
}

// TestAdversary165VisiblePriceIdentity は観測外の板を取消し扱いせず共通価格の変化だけを数えます。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAdversary165VisiblePriceIdentity(t *testing.T) {
	a := bookTest165(100, 1000, 1010)
	b := bookTest165(100, 1010, 1020)
	b.BidLevels[0].Quantity = 1000000
	u, d, known := commonDepth165(a.BidLevels, b.BidLevels)
	if !known || u != 0 || d != 0 {
		t.Fatal("新たに見えた価格の量を補充へ混ぜました")
	}
	b.BidLevels[1].Quantity = 30
	u, d, known = commonDepth165(a.BidLevels, b.BidLevels)
	if !known || d != 0 || math.Abs(u-.1) > 1e-12 {
		t.Fatalf("同じ1000円の純増20/共通量200だけが対象です: %v %v %v", u, d, known)
	}
	b.BidLevels[1].Price = b.BidLevels[0].Price
	_, _, known = commonDepth165(a.BidLevels, b.BidLevels)
	if known {
		t.Fatal("重複価格を既知として採用しました")
	}
}

// TestAdversary165RejectedParentAndUnknown は拒否親の追加復活を防ぎ、未知初回は元量で受けます。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAdversary165RejectedParentAndUnknown(t *testing.T) {
	for _, known := range []bool{true, false} {
		r := adversaryResult165(2)
		v := StateView165{Known: known, Sell: Hold165{Active: true, Side: -1, QuantitySupport: true, Index: 0}}
		adversaryStep165(t, r, adversaryQuote165(0, 990, 1000), v, adversarySignal165("初回", "new", 1, 5))
		adversaryStep165(t, r, adversaryQuote165(1, 990, 1000), v, adversarySignal165("追加", "new", 1, 2))
		adversaryStep165(t, r, adversaryQuote165(2, 990, 1000), v)
		long, _ := r.Actual.position("", "")
		want := 70
		if known {
			want = 0
		}
		if long != want || r.Parents["後半/core/1"].Base.SourceQty != 70 {
			t.Fatalf("未知fallbackと拒否Source寿命が不正 known=%v actual=%d", known, long)
		}
	}
}

// TestAdversary165DeferredQuantityAndDeath は待機中の源部分返済と終了を当時量へ反映します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAdversary165DeferredQuantityAndDeath(t *testing.T) {
	for _, closed := range []int{2, 5} {
		r := adversaryResult165(3)
		v := StateView165{Known: true, Sell: Hold165{Active: true, QuantitySupport: true, Side: -1}}
		adversaryStep165(t, r, adversaryQuote165(0, 990, 1000), v, adversarySignal165("初回", "new", 1, 5))
		v = StateView165{Known: true, Buy: Hold165{Active: true, Side: 1, Index: 1}}
		cl := adversarySignal165("返済", "close", -1, closed, strategy.LotTarget{ID: "後半/初回-玉", Quantity: closed})
		adversaryStep165(t, r, adversaryQuote165(1, 990, 1000), v, cl)
		adversaryStep165(t, r, adversaryQuote165(2, 990, 1000), v)
		long, _ := r.Actual.position("", "")
		if long != (5-closed)*10 {
			t.Fatal("待機量の復活又は源残量を超える解除")
		}
		if closed == 5 {
			adversaryStep165(t, r, adversaryQuote165(3, 990, 1000), v, adversarySignal165("遅い追加", "new", 1, 2))
			if len(r.Actual.Pending) != 0 {
				t.Fatal("取消済み親が後続追加で復活")
			}
		}
	}
}

// TestAdversary165ResidualIgnoresEarlierMFE は資格前だけ順行した別建値玉へ保護を遡及しません。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAdversary165ResidualIgnoresEarlierMFE(t *testing.T) {
	r, first := adversarySeed165(t, 5)
	adversaryStep165(t, r, adversaryQuote165(2, 1090, 1100), StateView165{}, adversarySignal165("追加", "new", 1, 2))
	adversaryStep165(t, r, adversaryQuote165(3, 1090, 1100), StateView165{})
	added := r.Actual.Active[1]
	adversaryStep165(t, r, adversaryQuote165(4, 1200, 1210), StateView165{})
	cl := adversarySignal165("部分", "close", -1, 2, strategy.LotTarget{ID: "後半/初回-玉", Quantity: 2})
	adversaryStep165(t, r, adversaryQuote165(5, 1050, 1060), StateView165{}, cl)
	adversaryStep165(t, r, adversaryQuote165(6, 1050, 1060), StateView165{})
	if !r.LotStates[added].ResidualEligible || r.LotStates[added].Activated || r.Actual.Lots[added].Best != 100 {
		t.Fatal("資格前の追加玉MFEを保護起動に流用しました")
	}
	v := StateView165{Known: true, Sell: Hold165{Active: true, Side: -1, Index: 7}}
	adversaryStep165(t, r, adversaryQuote165(7, 1050, 1060), v)
	if len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Targets[0].ID != first || r.Actual.Pending[0].Quantity != 30 {
		t.Fatal("資格後に正益の元残玉だけを返済していません")
	}
}

// TestAdversary165HalfAfterSourceReservation は元返済中は半減せず、次板残量だけを一度減らします。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAdversary165HalfAfterSourceReservation(t *testing.T) {
	r, id := adversarySeed165(t, 6)
	v := StateView165{Known: true, Sell: Hold165{Active: true, Side: -1, Index: 2}}
	cl := adversarySignal165("部分", "close", -1, 2, strategy.LotTarget{ID: "後半/初回-玉", Quantity: 2})
	adversaryStep165(t, r, adversaryQuote165(2, 990, 1000), v, cl)
	if len(r.Actual.Pending) != 1 || r.States["後半/core/1"].Reduced || r.Actual.Pending[0].Quantity != 20 {
		t.Fatal("元予約と半減を同じ原行で重複しました")
	}
	adversaryStep165(t, r, adversaryQuote165(3, 990, 1000), v)
	if len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Quantity != 15 || r.Actual.Lots[id].Remaining != 30 {
		t.Fatal("次板残30を15減らす予約又は実保有が不正")
	}
	adversaryStep165(t, r, adversaryQuote165(4, 990, 1000), v, adversarySignal165("追加", "new", 1, 2))
	if r.Actual.Lots[id].Remaining != 15 || len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Quantity != 10 {
		t.Fatal("半減後の追加も半量にしていません")
	}
	adversaryStep165(t, r, adversaryQuote165(5, 990, 1000), v)
	if len(r.Actual.Pending) != 0 {
		t.Fatal("一度だけの半減が反復しました")
	}
}

// TestAdversary165SupplyMustStillBePassed は通過履歴だけで壁の裏や期限切れの新規を認めません。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAdversary165SupplyMustStillBePassed(t *testing.T) {
	for _, test := range []struct {
		name        string
		bid, wallAt float64
		event       int64
		want        int
	}{
		{"現在も通過", 1020, 999, 5, 1},
		{"壁へ戻った", 1010, 999, 5, 0},
		{"時計期限切れ", 1020, 938, 5, 0},
		{"更新期限切れ", 1020, 999, 40, 0},
	} {
		t.Run(test.name, func(t *testing.T) {
			r := adversaryResult165(11)
			hold := Hold165{Active: true, Side: 1, ID: 1, SupplyPassed: true, Barrier: Barrier165{Known: true, Price: 1010, Time: test.wallAt, Index: 0, Event: 1}}
			v := StateView165{Known: true, PriceEvent: test.event, RetestSide: 1, RetestID: 1, Buy: hold}
			r.independent165(adversaryQuote165(0, test.bid, test.bid+10), v)
			if len(r.Actual.Pending) != test.want {
				t.Fatalf("過去通過フラグのみで新規判定: got=%d want=%d", len(r.Actual.Pending), test.want)
			}
		})
	}
}

// TestAdversary165IndependentHalfHasSameSequence は11と12の仮想枠・同時親・次板・半量会計を照合します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAdversary165IndependentHalfHasSameSequence(t *testing.T) {
	full, half := adversaryResult165(11), adversaryResult165(12)
	for index := int64(0); index < 7; index++ {
		for _, r := range []*Result165{full, half} {
			v := StateView165{Known: true, PriceEvent: index + 2, RetestSide: 1, RetestID: int(index + 1), Buy: Hold165{Active: true, Side: 1, SupplyPassed: true, Barrier: Barrier165{Known: true, Price: 970, Time: 999, Index: 0, Event: 1}}}
			adversaryStep165(t, r, adversaryQuote165(index, 990, 1000), v)
		}
	}
	for _, r := range []*Result165{full, half} {
		adversaryStep165(t, r, adversaryQuote165(7, 940, 950), StateView165{})
		adversaryStep165(t, r, adversaryQuote165(8, 930, 940), StateView165{})
	}
	if full.NextIndependent != 5 || half.NextIndependent != 5 || len(full.Actual.Events) != 10 || len(half.Actual.Events) != 10 {
		t.Fatal("半量版だけ余った枠で再参加しています")
	}
	if err := half.finalize165(); err != nil {
		t.Fatal(err)
	}
	for i, f := range full.Actual.Events {
		h := half.Actual.Events[i]
		if f.FillIndex != h.FillIndex || f.Price != h.Price || f.Order.Quantity != 2*h.Order.Quantity || f.Gross != 2*h.Gross {
			t.Fatal("同じ判断・約定価格での厳密半量ではありません")
		}
	}
	if half.VirtualControl == nil || half.VirtualControl.Realized != full.Actual.Realized || 2*half.Actual.Realized != full.Actual.Realized || 2*half.Actual.Risk.Minimum != full.Actual.Risk.Minimum {
		t.Fatal("半量の全時価又は元仮想証跡が不一致")
	}
}

// TestAdversary165NewTrailingKeepsLargeProfit は13が100円で固定利確せず過去最高から追尾します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAdversary165NewTrailingKeepsLargeProfit(t *testing.T) {
	r := adversaryResult165(13)
	v := StateView165{Known: true, RetestID: 1, RetestSide: 1, Buy: Hold165{Active: true, Side: 1}}
	adversaryStep165(t, r, adversaryQuote165(0, 990, 1000), v)
	adversaryStep165(t, r, adversaryQuote165(1, 990, 1000), StateView165{})
	adversaryStep165(t, r, adversaryQuote165(2, 1120, 1130), StateView165{})
	if len(r.Actual.Pending) != 0 {
		t.Fatal("13の100円固定利確が残っています")
	}
	adversaryStep165(t, r, adversaryQuote165(3, 1080, 1090), StateView165{})
	if len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Reason != "independent_trail30_40_floor10" {
		t.Fatal("最高120円から40円戻りの追尾が不正")
	}
	adversaryStep165(t, r, adversaryQuote165(4, 970, 980), StateView165{})
	if r.Actual.Realized != -6000 {
		t.Fatal("追尾判断後の次板赤字を隠しました")
	}
}

// TestAdversary165AllDirectionParentCap は返済予約中の5親を空き枠にせず反対新規も待たせます。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAdversary165AllDirectionParentCap(t *testing.T) {
	r := adversaryResult165(10)
	for i := int64(0); i < 6; i++ {
		v := StateView165{Known: true, RetestSide: 1, RetestID: int(i + 1), Buy: Hold165{Active: true, Side: 1, ID: 1}}
		adversaryStep165(t, r, adversaryQuote165(i, 990, 1000), v)
	}
	if r.NextIndependent != 5 {
		t.Fatal("同方向5親の準備が不正")
	}
	v := StateView165{Known: true, RetestSide: -1, RetestID: 7, Sell: Hold165{Active: true, Side: -1, ID: 2, Index: 6}}
	adversaryStep165(t, r, adversaryQuote165(6, 990, 1000), v)
	if r.NextIndependent != 5 || len(r.Actual.Pending) != 5 {
		t.Fatal("買い5親の返済未約定中に6親目の売りを建てました")
	}
	for _, o := range r.Actual.Pending {
		if len(o.Targets) == 0 {
			t.Fatal("返済予約で全方向枠を先取りしました")
		}
	}
	v.RetestID = 8
	adversaryStep165(t, r, adversaryQuote165(7, 990, 1000), v)
	if r.NextIndependent != 6 || len(r.Actual.Pending) != 1 || len(r.Actual.Pending[0].Targets) != 0 {
		t.Fatal("実完済後の新しい押戻りまで拒否しました")
	}
}

// TestAdversary165SourceHalfPartialInteger は01の奇数保有15microでも源部分返済が厳密半量になることを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAdversary165SourceHalfPartialInteger(t *testing.T) {
	wholeConfig := configs165()[0]
	wholeConfig.ID = "人工だけの全量対照"
	wholeConfig.Scale = 1
	whole := newResult165(wholeConfig, Scene{Start: 0, USOpen: 100, ForceClose: 10000})
	half := adversaryResult165(1)
	for _, r := range []*Result165{whole, half} {
		adversaryStep165(t, r, adversaryQuote165(0, 990, 1000), StateView165{}, adversarySignal165("初回", "new", 1, 3))
		adversaryStep165(t, r, adversaryQuote165(1, 990, 1000), StateView165{})
		for k := 0; k < 3; k++ {
			i := int64(2 + 2*k)
			cl := adversarySignal165("部分", "close", -1, 1, strategy.LotTarget{ID: "後半/初回-玉", Quantity: 1})
			adversaryStep165(t, r, adversaryQuote165(i, 1020, 1030), StateView165{}, cl)
			adversaryStep165(t, r, adversaryQuote165(i+1, 1010+float64(k)*10, 1020+float64(k)*10), StateView165{})
		}
	}
	if len(whole.Actual.Events) != 4 || len(half.Actual.Events) != 4 || len(half.Actual.Active) != 0 {
		t.Fatal("源終了の丸め残又は半量の注文差")
	}
	for i, a := range whole.Actual.Events {
		b := half.Actual.Events[i]
		if a.Order.Quantity != 2*b.Order.Quantity || a.Gross != 2*b.Gross || a.FillIndex != b.FillIndex || a.Price != b.Price {
			t.Fatal("元3mini→micro15保有・順次5枚返済の半量対照が不一致")
		}
	}
}

// TestAdversary165HalfParentTotalRounding は親合計の切捨て量を固定ID順へ配り玉別丸めを防ぎます。
//
// 引数: t(*testing.T)。返り値: なし。空き枠で部分採用された奇数実玉を人工状態として構成します。
func TestAdversary165HalfParentTotalRounding(t *testing.T) {
	for _, quantities := range [][]int{{5, 5}, {1, 1}, {1}} {
		r := adversaryResult165(6)
		p := &NightParent164R2{Base: AllocationParent157{Key: "後半/core/1", Owner: "後半/core", Campaign: 1, Side: 1, OldInitial: 10, SourceHolds: map[string]int{}}}
		r.Parents[p.Base.Key] = p
		total := 0
		for _, q := range quantities {
			total += q
			r.Actual.open(&p.Base, adversaryQuote165(0, 990, 1000), "initial", "人工の部分採用", 1, q, Support157{})
		}
		adversaryStep165(t, r, adversaryQuote165(1, 990, 1000), StateView165{})
		ids := append([]string(nil), r.Actual.Active...)
		v := StateView165{Known: true, Sell: Hold165{Active: true, Side: -1, Index: 2}}
		adversaryStep165(t, r, adversaryQuote165(2, 990, 1000), v)
		want, got := total/2, 0
		for _, order := range r.Actual.Pending {
			got += order.Quantity
		}
		if got != want || r.States[p.Base.Key].Reduced != (want > 0) {
			t.Fatalf("親合計halfが玉別floorになっています: 入力=%v got=%d want=%d", quantities, got, want)
		}
		if want > 0 && (len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Targets[0].ID != ids[0]) {
			t.Fatal("親半減の固定ActualID順配賦が不正")
		}
		adversaryStep165(t, r, adversaryQuote165(3, 990, 1000), v)
		long, _ := r.Actual.position(p.Base.Key, "")
		if long != total-want || len(r.Actual.Pending) != 0 {
			t.Fatal("半減後の切上げ残量又は二度目予約が不正")
		}
	}
}
