package main

import "testing"

// artificialState165 は手計算した窓を使って状態遷移を検査します。
//
// 引数: index(int64)、bid/ask(float64)、buy(bool)。返り値: Feature165。
func artificialState165(index int64, bid, ask float64, buy bool) Feature165 {
	d := 1.0
	if !buy {
		d = -1
	}
	fraction := 1.0
	if !buy {
		fraction = 0
	}
	b := Band165{Known: true, QuantityKnown: true, BidMove: d * 20, AskMove: d * 20, GrossPriceMove: 40, UpFraction: fraction}
	return Feature165{Current: Frame165{Index: index, Line: index + 1, Time: 100, Bid: bid, Ask: ask}, Changed: true, Event8: b, Clock15: b}
}

// TestState165TwoLaterEvents は未来二更新を先取りしない買売鏡像を確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestState165TwoLaterEvents(t *testing.T) {
	for _, side := range []int{1, -1} {
		s := &Repricing165{}
		d := float64(side)
		for i := int64(0); i <= 2; i++ {
			bid := 1000 + d*float64(i)*10
			b := bookTest165(100, bid, bid+10)
			v := s.step165(artificialState165(i, b.Bid, b.Ask, side > 0), b)
			if (i < 2 && v.ConfirmedSide != 0) || (i == 2 && v.ConfirmedSide != side) {
				t.Fatalf("先取り/不足 %+v", v)
			}
		}
	}
}

// TestState165PressureHoldsAndNewPullback は数量だけの逆圧力で降りず、新しい押戻りを要求します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestState165PressureHoldsAndNewPullback(t *testing.T) {
	s := &Repricing165{}
	for i := int64(0); i <= 2; i++ {
		b := bookTest165(100, 1000+float64(i)*10, 1010+float64(i)*10)
		s.step165(artificialState165(i, b.Bid, b.Ask, true), b)
	}
	b := bookTest165(100, 1020, 1030)
	b.AskQuantity = 1000
	f := artificialState165(3, b.Bid, b.Ask, true)
	f.Changed = false
	v := s.step165(f, b)
	if !v.Buy.Active || v.RetestID != 0 {
		t.Fatal("数量だけで価格帯を破棄")
	}
	for i, bid := range []float64{1010, 1020, 1030} {
		b = bookTest165(100, bid, bid+10)
		v = s.step165(artificialState165(int64(i+4), b.Bid, b.Ask, true), b)
		if i < 2 && v.RetestID != 0 {
			t.Fatal("押戻り後の二更新先取り")
		}
	}
	if v.RetestSide != 1 || v.RetestID != 1 {
		t.Fatalf("新波:%+v", v)
	}
	b = bookTest165(100, 1040, 1050)
	v = s.step165(artificialState165(8, b.Bid, b.Ask, true), b)
	if v.RetestID != 0 {
		t.Fatal("同波を再発火")
	}
}

// TestState165UnknownReset は不正板/実端点未知をゼロ圧力として使いません。
//
// 引数: t(*testing.T)。返り値: なし。
func TestState165UnknownReset(t *testing.T) {
	s := &Repricing165{}
	b := bookTest165(100, 1000, 1010)
	f := artificialState165(0, 1000, 1010, true)
	f.Event8.Known = false
	s.step165(f, b)
	if s.Candidates[0].Active {
		t.Fatal("未知を新準備")
	}
	s.step165(artificialState165(1, 1010, 1020, true), bookTest165(100, 1010, 1020))
	s.step165(Feature165{}, bookTest165(100, 1010, 1010))
	if s.Candidates[0].Active || s.Holds[0].Active {
		t.Fatal("不正板を越えた状態")
	}
}
