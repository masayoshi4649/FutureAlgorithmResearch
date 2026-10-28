package strategy

import "testing"

// sourceHold1562 は人工主担当の仮想源だけへ既知の保有を設定します。
//
// 引数: s(*ResearchSleeve)、quantity(int)。返り値: なし。実玉は通常OnFillで作ります。
func sourceHold1562(s *ResearchSleeve, quantity int) {
	if s.Source.Legacy != nil {
		s.Source.Legacy.Core.Position = Position{Side: s.Side, Quantity: 2 * quantity, Campaign: s.Campaign}
	}
	if s.Source.Episode != nil {
		s.Source.Episode.Book.Parent = s.Campaign
		s.Source.Episode.Book.Side = s.Side
		s.Source.Episode.Book.Held[0] = quantity
	}
}

// readyReentry1562 は初回実約定から保護完済までを通常注文経路で進めます。
//
// 引数: t(*testing.T)、side/quantity(int)。返り値: *Portfolio、*ResearchSleeve。
func readyReentry1562(t *testing.T, side, quantity int) (*Portfolio, *ResearchSleeve) {
	t.Helper()
	p := studyTest156(t, 20, 0, false, 0)
	if err := p.ConfigureReentry1562(20); err != nil {
		t.Fatal(err)
	}
	s := hold156(t, p, "core", side, quantity)
	sourceHold1562(s, quantity)
	p.updateLot156(s, obs156(1, 3, 1000+float64(side)*35))
	o := obs156(2, 4, 1000+float64(side)*15)
	p.updateLot156(s, o)
	p.applyLot156(s, o, true)
	out := p.flushResearchGoals(s, o)
	if len(out) != 1 {
		t.Fatal(out)
	}
	if err := p.OnFill(Fill{SignalID: out[0].ID, ExecutionID: "保護返済", Quantity: quantity, Price: 1000 + float64(side)*10, Time: 5, Closed: out[0].Targets}); err != nil {
		t.Fatal(err)
	}
	if err := p.OnOrderDone(out[0].ID); err != nil {
		t.Fatal(err)
	}
	if s.held() != 0 || p.Reentry1562.Arms["core"] == nil || p.Reentry1562.Arms["core"].Quantity != quantity {
		t.Fatal("全保護から準備", s.held(), p.Reentry1562)
	}
	return p, s
}

// fireReentry1562 は完済行・新極値行・回復行を別原行で与えます。
//
// 引数: t(*testing.T)、p(*Portfolio)、s(*ResearchSleeve)。返り値: Signalは次板約定待ちです。
func fireReentry1562(t *testing.T, p *Portfolio, s *ResearchSleeve) Signal {
	t.Helper()
	p.s01Fresh = true
	d := float64(s.Side)
	if out := p.manageReentry1562(s, obs156(3, 5, 1000+d*100), nil, true, true); len(out) != 0 {
		t.Fatal("実返済行で即再参加", out)
	}
	if out := p.manageReentry1562(s, obs156(4, 6, 1000-d*15), nil, true, true); len(out) != 0 {
		t.Fatal("極値初期化行で即再参加", out)
	}
	out := p.manageReentry1562(s, obs156(5, 7, 1000+d*5), nil, true, true)
	if len(out) != 1 || out[0].ReasonCode != 15630 || out[0].Ticket >= 0 {
		t.Fatal(out, p.Reentry1562)
	}
	if len(p.manageReentry1562(s, obs156(6, 7, 1000+d*20), nil, true, true)) != 0 {
		t.Fatal("未約定二重予約")
	}
	return out[0]
}

// Test1562FullLifecycleSymmetric は初回から保護・再参加・元部分/全返済までを買売鏡像で検査します。
//
// 引数: t(*testing.T)。返り値: なし。元源通知は有限人工列で、未来の終了は渡しません。
func Test1562FullLifecycleSymmetric(t *testing.T) {
	for _, side := range []int{-1, 1} {
		p, s := readyReentry1562(t, side, 5)
		d := float64(side)
		sig := fireReentry1562(t, p, s)
		if err := p.OnFill(Fill{SignalID: sig.ID, ExecutionID: "再参加約定", HoldID: "再参加玉", Quantity: 5, Price: 1000 + d*5, Time: 8}); err != nil {
			t.Fatal(err)
		}
		if err := p.OnOrderDone(sig.ID); err != nil {
			t.Fatal(err)
		}
		if originalQuantity1562(s) != 5 || s.held() != 5 || s.Requested[0] != 5 {
			t.Fatal("元分母の変更", s)
		}
		p.updateLot156(s, obs156(7, 8, 1000+d*5))
		g := p.Study156.Lots["再参加玉"]
		if g.Active || g.Entry != 1000+d*5 {
			t.Fatal("旧玉の床を新玉へ流用", g)
		}
		// ----------------------------------------
		// 再参加後の新しい元減枚2/5だけを適用し、実5枚から2枚返します。
		o := obs156(8, 9, 1000+d*25)
		events := []ResearchEvent{{Action: "close", Side: -side, Quantity: 2, Reason: 30, Campaign: 0, Ticket: 0}}
		before := originalQuantity1562(s)
		p.nativeResearch(s, o, events, true, true)
		sourceHold1562(s, 3)
		p.applySourceToReentry1562(s, o, events, before)
		out := p.flushResearchGoals(s, o)
		if len(out) != 1 || out[0].Quantity != 2 || out[0].Targets[0].ID != "再参加玉" {
			t.Fatal(out)
		}
		if err := p.OnFill(Fill{SignalID: out[0].ID, ExecutionID: "元部分約定", Quantity: 2, Price: 1000 + d*20, Time: 10, Closed: out[0].Targets}); err != nil {
			t.Fatal(err)
		}
		p.OnOrderDone(out[0].ID)
		if s.held() != 3 || p.Reentry1562.Arms["core"] != nil {
			t.Fatal("元部分で再準備又は枚数差")
		}
		// ----------------------------------------
		// 元源が全終了した時点で、負ticketの実3枚も確実に全返済します。
		o = obs156(10, 11, 1000+d*15)
		events = []ResearchEvent{{Action: "close", Side: -side, Quantity: 3, Reason: 2, Campaign: 0, Ticket: 0}}
		before = originalQuantity1562(s)
		p.nativeResearch(s, o, events, true, true)
		sourceHold1562(s, 0)
		p.applySourceToReentry1562(s, o, events, before)
		out = p.flushResearchGoals(s, o)
		if len(out) != 1 || out[0].Quantity != 3 {
			t.Fatal(out)
		}
		if err := p.OnFill(Fill{SignalID: out[0].ID, ExecutionID: "元全約定", Quantity: 3, Price: 1000 + d*10, Time: 12, Closed: out[0].Targets}); err != nil {
			t.Fatal(err)
		}
		p.OnOrderDone(out[0].ID)
		if s.held() != 0 || p.researchCash(s) != 9500 || p.Reentry1562.Arms["core"] != nil {
			t.Fatal("全連鎖会計", s.held(), p.researchCash(s))
		}
	}
}

// Test1562SourceEndsAndPriority は元終了・別親・場末・通常新規が再参加より優先することを確かめます。
//
// 引数: t(*testing.T)。返り値: なし。
func Test1562SourceEndsAndPriority(t *testing.T) {
	for _, mode := range []string{"元完済", "別親", "反転", "場末", "通常追加"} {
		p, s := readyReentry1562(t, 1, 5)
		p.s01Fresh = true
		o := obs156(3, 5, 1100)
		events := []ResearchEvent{}
		switch mode {
		case "元完済":
			sourceHold1562(s, 0)
		case "別親":
			s.Source.Legacy.Core.Position.Campaign = 1
		case "反転":
			s.Source.Legacy.Core.Position.Side = -1
		case "場末":
			o.Time = p.Session.ForceClose
		case "通常追加":
			events = []ResearchEvent{{Action: "new", Campaign: 0, Side: 1, Quantity: 1}}
		}
		if len(p.manageReentry1562(s, o, events, true, true)) != 0 || p.Reentry1562.Arms["core"] != nil {
			t.Fatal(mode)
		}
	}
}

// Test1562PartialRoundingAndNoRetroactivity は後発減枚の端数と新規予約中の遅着分を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test1562PartialRoundingAndNoRetroactivity(t *testing.T) {
	p, s := readyReentry1562(t, 1, 1)
	// 元は既に5から3へ減少済みとする。新しい再参加1枚にはこの過去比率を適用しません。
	s.Virtual[0] = 3
	sourceHold1562(s, 3)
	sig := fireReentry1562(t, p, s)
	if p.Reentry1562.Targets[sig.Ticket].Remaining != 1 {
		t.Fatal("過去部分減少を遡及")
	}
	if err := p.OnFill(Fill{SignalID: sig.ID, ExecutionID: "小口再参加", HoldID: "小口", Quantity: 1, Price: 1005, Time: 8}); err != nil {
		t.Fatal(err)
	}
	p.OnOrderDone(sig.ID)
	e := []ResearchEvent{{Action: "close", Side: -1, Quantity: 1, Reason: 30, Campaign: 0, Ticket: 0}}
	o := obs156(8, 9, 1025)
	p.nativeResearch(s, o, e, true, true)
	sourceHold1562(s, 2)
	p.applySourceToReentry1562(s, o, e, 3)
	if len(p.flushResearchGoals(s, o)) != 0 || p.Reentry1562.Targets[sig.Ticket].Remaining != 1 {
		t.Fatal("2/3の最近整数が違う")
	}
	s.Virtual[0] = 0
	sourceHold1562(s, 0)
	p.applySourceToReentry1562(s, obs156(9, 10, 1025), nil, 2)
	out := p.flushResearchGoals(s, obs156(9, 10, 1025))
	if len(out) != 1 || out[0].Quantity != 1 {
		t.Fatal("端数残玉を全終了できない", out)
	}
}

// Test1562PartialProtectionDoesNotArm は一部の玉だけ保護しても再参加枠を増やさないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test1562PartialProtectionDoesNotArm(t *testing.T) {
	p := studyTest156(t, 20, 0, false, 0)
	p.ConfigureReentry1562(20)
	s := hold156(t, p, "core", 1, 5)
	sourceHold1562(s, 5)
	s.setGoal("玉A", 3, 15601)
	out := p.flushResearchGoals(s, obs156(1, 3, 1050))
	if err := p.OnFill(Fill{SignalID: out[0].ID, ExecutionID: "一部保護", Quantity: 2, Price: 1045, Time: 4, Closed: out[0].Targets}); err != nil {
		t.Fatal(err)
	}
	p.OnOrderDone(out[0].ID)
	if p.Reentry1562.Arms["core"] != nil || p.Reentry1562.Batches["core"] != nil {
		t.Fatal("一部保護から追加枠が発生")
	}
}

// Test1562MixedCloseBatchOrdering は混合群の再参加可否が約定順で変わらないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。全保護の複数玉群だけは元の4枚で再準備します。
func Test1562MixedCloseBatchOrdering(t *testing.T) {
	for _, all := range []bool{false, true} {
		for _, reverse := range []bool{false, true} {
			p := studyTest156(t, 20, 0, false, 0)
			p.ConfigureReentry1562(20)
			s := hold156(t, p, "core", 1, 2)
			newSig := p.nativeResearch(s, obs156(1, 3, 1000), []ResearchEvent{{Action: "new", Side: 1, Quantity: 2, Campaign: 0, Ticket: 1, Risk: 80}}, true, true)
			if len(newSig) != 1 {
				t.Fatal(newSig)
			}
			if err := p.OnFill(Fill{SignalID: newSig[0].ID, ExecutionID: "第2玉", HoldID: "玉B", Quantity: 2, Price: 1000, Time: 4}); err != nil {
				t.Fatal(err)
			}
			p.OnOrderDone(newSig[0].ID)
			sourceHold1562(s, 4)
			reason := 30
			if all {
				reason = 15601
			}
			s.setGoal("玉A", 0, reason)
			s.setGoal("玉B", 0, 15601)
			out := p.flushResearchGoals(s, obs156(2, 5, 1040))
			if len(out) != 2 {
				t.Fatal(out)
			}
			if reverse {
				out[0], out[1] = out[1], out[0]
			}
			for i, sig := range out {
				if err := p.OnFill(Fill{SignalID: sig.ID, ExecutionID: sig.ID + "実", Quantity: 2, Price: 1030, Time: 6, Closed: sig.Targets}); err != nil {
					t.Fatal(err)
				}
				p.OnOrderDone(sig.ID)
				if i == 0 && p.Reentry1562.Arms["core"] != nil {
					t.Fatal("一部約定で早期準備")
				}
			}
			arm := p.Reentry1562.Arms["core"]
			if all {
				if arm == nil || arm.Quantity != 4 {
					t.Fatal("全保護群の数量", arm)
				}
			} else if arm != nil {
				t.Fatal("混合群を保護全返済扱い", reverse, arm)
			}
		}
	}
}

// Test1562RealObservationPath は実際の元episodeから保護・新極値・再参加通知を一続きに生成します。
//
// 引数: t(*testing.T)。返り値: なし。Source.Stepを手動差替せず、仮想約定も次正常原行です。
func Test1562RealObservationPath(t *testing.T) {
	for _, side := range []int{-1, 1} {
		p := studyTest156(t, 20, 0, false, 0)
		p.ConfigureReentry1562(20)
		values := []float64{875, 925, 925, 925, 925, 925, 945, 930, 935, 925, 950, 950, 1005, 1005, 1115, 1115, 990, 990}
		var pending []Signal
		ordinary, protect, reenter := 0, 0, 0
		for i, v := range values {
			mid := v
			if side < 0 {
				mid = 2000 - v
			}
			o := obs156(int64(i), 100+float64(i)*5, mid)
			o.Research.Band20.Known = true
			o.Research.Band20.Values = [9]float64{1100, 900, 0, 0, 0, 0, 0, 0, 90}
			for _, sig := range pending {
				price := liquidation(o, -sig.Side)
				if err := p.OnFill(Fill{SignalID: sig.ID, ExecutionID: sig.ID + "実", HoldID: sig.ID + "玉", Quantity: sig.Quantity, Price: price, Time: o.Time, Closed: sig.Targets}); err != nil {
					t.Fatal(err)
				}
				p.OnOrderDone(sig.ID)
			}
			pending = nil
			out, err := p.Observe(o, true)
			if err != nil {
				t.Fatal(err)
			}
			for _, sig := range out {
				if sig.Owner != "episode" {
					t.Fatal("人工で対象外担当が発注", sig)
				}
				if sig.Action == "new" && sig.ReasonCode == 1431 {
					ordinary++
				}
				if sig.ReasonCode == 15601 || sig.ReasonCode == 15602 {
					protect++
				}
				if sig.ReasonCode == 15630 {
					reenter++
				}
			}
			pending = append(pending, out...)
		}
		if ordinary < 1 || protect < 1 || reenter < 1 {
			t.Fatal("実観測連鎖が不足", side, ordinary, protect, reenter, p.Reentry1562.Audit)
		}
	}
}

// Test1562SourceEndsDuringPending は新規予約中に元源が終わっても約定を消さず、その後返済することを確認します。
//
// 引数: t(*testing.T)。返り値: なし。部分約定・未約定残取消後も所有2枚だけ返済します。
func Test1562SourceEndsDuringPending(t *testing.T) {
	p, s := readyReentry1562(t, 1, 5)
	sig := fireReentry1562(t, p, s)
	s.Virtual[0] = 0
	sourceHold1562(s, 0)
	p.applySourceToReentry1562(s, obs156(6, 8, 1000), nil, 5)
	if p.Reentry1562.Targets[sig.Ticket].Remaining != 0 {
		t.Fatal("元全終了目標なし")
	}
	if err := p.OnFill(Fill{SignalID: sig.ID, ExecutionID: "遅着2枚", HoldID: "遅着玉", Quantity: 2, Price: 1010, Time: 9}); err != nil {
		t.Fatal(err)
	}
	if out := p.flushResearchGoals(s, obs156(7, 9, 1000)); len(out) != 0 {
		t.Fatal("未確定新規と返済を二重発注")
	}
	p.OnOrderDone(sig.ID)
	out := p.flushResearchGoals(s, obs156(8, 10, 990))
	if len(out) != 1 || out[0].Quantity != 2 || out[0].Targets[0].ID != "遅着玉" {
		t.Fatal(out)
	}
	if err := p.OnFill(Fill{SignalID: out[0].ID, ExecutionID: "遅着返済", Quantity: 2, Price: 985, Time: 11, Closed: out[0].Targets}); err != nil {
		t.Fatal(err)
	}
	p.OnOrderDone(out[0].ID)
	if s.held() != 0 || p.researchCash(s) != 0 {
		t.Fatal("保護利益5000と遅着損5000", s.held(), p.researchCash(s))
	}
}
