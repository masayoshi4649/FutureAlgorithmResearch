package strategy

import "testing"

// Test154Round2GuardScope は保護対象を担当別に固定して初巡の動作を保存します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test154Round2GuardScope(t *testing.T) {
	for _, tc := range []struct {
		id              string
		episode, others float64
	}{{"S00", .5, 0}, {"S01", .5, 0}, {"S04", 1, 0}, {"S02", 1, 0}, {"S03", 1, 1}, {"G01", .5, .5}, {"G02", 1, 1}, {"J01", 0, 0}, {"J02", 0, 0}, {"J03", 0, 0}} {
		p, _ := setup154(t, tc.id, "Day")
		for _, s := range p.Research.Sleeves {
			want := tc.others
			if s.Name == "episode" {
				want = tc.episode
			}
			if p.guardFor154(s) != want {
				t.Fatal(tc.id, s.Name, p.guardFor154(s), want)
			}
		}
	}
}

// Test154Round2ReferenceOccupancy は未変更D07の実玉と未約定を新親受付へ接続します。
//
// 引数: t(*testing.T)。返り値: なし。将来の完済時刻を与えません。
func Test154Round2ReferenceOccupancy(t *testing.T) {
	for _, id := range []string{"S01", "S02", "S03"} {
		p, o := setup154(t, id, "Day")
		ref, _ := setup154(t, "D07", "Day")
		s := ref.sleeve("episode")
		s.Campaign, s.Side = 4, 1
		s.Lots = []ResearchLot{{ID: "既存玉", Quantity: 1, Price: 900}}
		ref.LastTime = o.Time
		p.SetReference154(ref)
		if p.referenceAllows154("episode", 5, o) || !p.referenceAllows154("episode", 4, o) || !p.referenceAllows154("core", 5, o) {
			t.Fatal("保有時の担当・親分離", id)
		}
		s.Lots = nil
		ref.emitResearch(s, o, ResearchEvent{Action: "new", Side: 1, Quantity: 1, Campaign: 4}, nil)
		p.SetReference154(ref)
		if p.referenceAllows154("episode", 5, o) {
			t.Fatal("未約定新規中の受理", id)
		}
		for oid := range ref.Orders {
			if err := ref.OnOrderDone(oid); err != nil {
				t.Fatal(err)
			}
		}
		p.SetReference154(ref)
		if !p.referenceAllows154("episode", 5, o) {
			t.Fatal("実玉・予約が消えた後も禁止", id)
		}
		if len(p.ReferenceRejected154) != 2 || !p.ReferenceRejected154[0].Reference.Occupied {
			t.Fatal("当時の拒否記録が更新された", id)
		}
	}
}

// Test154Round2ReferenceNative は拒否を仮想親へ固定し、次の新親を改めて判定します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test154Round2ReferenceNative(t *testing.T) {
	p, o := setup154(t, "S01", "Day")
	s := p.sleeve("episode")
	p.Reference154 = &ReferenceState154{Campaign: 0, Occupied: true, At: o.Time}
	e := ResearchEvent{Action: "new", Side: 1, Quantity: 2, Campaign: 1, Ticket: 1, Risk: 80}
	if got := p.nativeResearch(s, o, []ResearchEvent{e}, true, true); len(got) != 0 || s.Accepted[1] {
		t.Fatal("別親の採用")
	}
	p.Reference154 = &ReferenceState154{Campaign: 0, Occupied: false, At: o.Time + 1}
	if got := p.nativeResearch(s, o, []ResearchEvent{e}, true, true); len(got) != 0 {
		t.Fatal("拒否した同親への後追い採用")
	}
	e.Campaign, e.Ticket = 2, 2
	if got := p.nativeResearch(s, o, []ResearchEvent{e}, true, true); len(got) != 1 {
		t.Fatal("次親の採用", got)
	}
	for _, id := range []string{"S00", "S04"} {
		x, _ := setup154(t, id, "Day")
		if !x.referenceAllows154("episode", 2, o) {
			t.Fatal("影なし対照まで抑止", id)
		}
	}
}

// Test154Round2SelectiveQuantity は既存の同方向玉が進んだ時だけ入口枚数を変えます。
//
// 引数: t(*testing.T)。返り値: なし。買売を反転した人工例を同じ閾値で検査します。
func Test154Round2SelectiveQuantity(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, id := range []string{"J01", "J02", "J03"} {
			for _, strong := range []bool{false, true} {
				p, o := setup154(t, id, "Day")
				o.Research.Values[12] *= float64(side)
				o.Research.Values[13] *= float64(side)
				o.Research.Values[20] *= float64(side)
				ep := p.sleeve("episode")
				ep.Side, ep.FixedR = side, 80
				entry := 995 - float64(side)*80
				if side < 0 {
					entry = 1005 + 80
				}
				if !strong {
					entry += float64(side)
				}
				ep.Lots = []ResearchLot{{ID: "早い玉", Quantity: 1, Price: entry}}
				s := p.sleeve("core")
				got := p.nativeResearch(s, o, []ResearchEvent{{Action: "new", Side: side, Quantity: 5, Campaign: 0, Ticket: 0, Risk: 80}}, true, true)
				want := 5
				if strong {
					want = 1
				}
				if len(got) != 1 || got[0].Quantity != want {
					t.Fatal(id, side, strong, got)
				}
				mode := s.JabMode154
				ep.Lots = nil
				if strong && !p.jab154(s) || s.JabMode154 != mode {
					t.Fatal("入口後の判定変更", id)
				}
				fill154(t, p, got[0], liquidation(o, -side), 1001)
				if !strong {
					continue
				}
				o.Time = 1031
				o.Index = 2
				if side > 0 {
					o.Bid, o.Ask = 1045, 1055
				} else {
					o.Bid, o.Ask = 945, 955
				}
				add := p.addJab154(s, o)
				if id == "J01" && len(add) != 0 || id != "J01" && len(add) != 1 {
					t.Fatal("固定1枚と段階追加の分離", id, side, add)
				}
			}
		}
	}
}

// Test154Round2WeightedAndScope は数量加重・逆方向・未知板・夜間の不採用を確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test154Round2WeightedAndScope(t *testing.T) {
	p, o := setup154(t, "J02", "Day")
	s := p.sleeve("core")
	ep := p.sleeve("episode")
	ep.Side, ep.FixedR = 1, 80
	ep.Lots = []ResearchLot{{ID: "有利玉", Quantity: 1, Price: 900}, {ID: "不利玉", Quantity: 3, Price: 990}}
	if p.chooseJab154(s, o, 1) != 0 {
		t.Fatal("一番有利な玉だけを参照")
	}
	ep.Lots = []ResearchLot{{ID: "玉", Quantity: 1, Price: 900}}
	if p.chooseJab154(s, o, -1) != 0 {
		t.Fatal("逆向きepisodeを参照")
	}
	o.QuoteOK = false
	if p.chooseJab154(s, o, 1) != 0 {
		t.Fatal("未知板で数量判定")
	}
	o.QuoteOK = true
	p.Session.Kind = "Night"
	if p.chooseJab154(s, o, 1) != 0 {
		t.Fatal("夜間へ昼の変更が波及")
	}
}
