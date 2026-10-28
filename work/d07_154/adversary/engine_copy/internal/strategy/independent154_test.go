package strategy

import "testing"

// audit154Portfolio は独立検査用の有限な日中状態を作ります。
//
// 引数: t(*testing.T)、id(string)は候補ID。返り値: *Portfolioは人工状態です。
func audit154Portfolio(t *testing.T, id string) *Portfolio {
	t.Helper()
	params, err := ParametersForMethod("NK225", "Day", "D07")
	if err != nil {
		t.Fatal(err)
	}
	p, err := New(Config{Reference: "NK225", Product: "NK225mini", CoreQuantity: 5, ExtraMaxQuantity: 5, Cap: 10, LargeTick: 10, PointValue: 100, Parameters: params, Study154: id}, Session{ID: "人工_Day", Kind: "Day", Start: 0, End: 21000, ForceClose: 20000, USOpen: 50000})
	if err != nil {
		t.Fatal(err)
	}
	return p
}

// audit154Observation は因果的な短期支持の人工行を作ります。
//
// 引数: index(int64)、at/bid(float64)。返り値: Observationは正常BBOです。
func audit154Observation(index int64, at, bid float64) Observation {
	o := Observation{Reference: "NK225", Index: index, Time: at, Received: at, Bid: bid, Ask: bid + 10, Last: bid, ATR: 20, QuoteOK: true}
	for _, k := range []int{12, 13, 20} {
		o.Research.Known[k] = true
		o.Research.Values[k] = 1
	}
	return o
}

// audit154Fill は人工依頼だけを全約定させます。
//
// 引数: t(*testing.T)、p(*Portfolio)、sig(Signal)、price(float64)。返り値: なし。
func audit154Fill(t *testing.T, p *Portfolio, sig Signal, price float64) {
	t.Helper()
	f := Fill{SignalID: sig.ID, ExecutionID: sig.ID + "約定", HoldID: sig.ID + "玉", Closed: sig.Targets, Quantity: sig.Quantity, Price: price, Time: sig.Time + 1}
	if err := p.OnFill(f); err != nil {
		t.Fatal(err)
	}
	if err := p.OnOrderDone(sig.ID); err != nil {
		t.Fatal(err)
	}
}

// audit154Entry は元の影枚数を変えず、現在候補の実初回を約定させます。
//
// 引数: t(*testing.T)、p(*Portfolio)、owner(string)、quantity(int)。返り値: *ResearchSleeve。
func audit154Entry(t *testing.T, p *Portfolio, owner string, quantity int) *ResearchSleeve {
	t.Helper()
	s := p.sleeve(owner)
	out := p.nativeResearch(s, audit154Observation(0, 100, 990), []ResearchEvent{{Action: "new", Side: 1, Quantity: quantity, Campaign: 0, Ticket: 0}}, true, true)
	if len(out) != 1 {
		t.Fatal(out)
	}
	audit154Fill(t, p, out[0], 1000)
	return s
}

// TestAudit154ShadowAndAddedTickets は影5枚と実増玉を区別し、元退出で全玉を返すことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit154ShadowAndAddedTickets(t *testing.T) {
	p := audit154Portfolio(t, "C03")
	s := audit154Entry(t, p, "core", 5)
	if s.held() != 1 || s.Requested[0] != 5 || s.Virtual[0] != 5 || s.Opened[0] != 1 {
		t.Fatalf("初回紐付け %+v", s)
	}
	for i, at := range []float64{132, 164} {
		o := audit154Observation(int64(i+1), at, 1040+40*float64(i))
		out := p.addJab154(s, o)
		if len(out) != 1 || out[0].Quantity != 1 || out[0].Ticket != 0 {
			t.Fatal(out)
		}
		if duplicate := p.addJab154(s, o); len(duplicate) != 0 {
			t.Fatal("予約を無視した追加", duplicate)
		}
		audit154Fill(t, p, out[0], o.Ask)
	}
	if s.held() != 3 || s.Opened[0] != 3 || s.Requested[0] != 5 || s.Anchor154 != 1000 {
		t.Fatalf("増玉紐付け %+v", s)
	}
	o := audit154Observation(5, 200, 1120)
	p.nativeResearch(s, o, []ResearchEvent{{Action: "close", Side: -1, Quantity: 2, Campaign: 0, Ticket: 0, Reason: 7}}, true, true)
	out := p.flushResearchGoals(s, o)
	if len(out) != 1 || out[0].Quantity != 1 {
		t.Fatal("影2/5の実3枚返済", out)
	}
	audit154Fill(t, p, out[0], 1120)
	if s.held() != 2 || s.PartialProtection == nil {
		t.Fatal("部分返済後の残玉と保護")
	}
	if extra := p.addJab154(s, audit154Observation(6, 250, 1400)); len(extra) != 0 {
		t.Fatal("部分返済後の追加", extra)
	}
	o = audit154Observation(7, 260, 1050)
	p.nativeResearch(s, o, []ResearchEvent{{Action: "close", Side: -1, Quantity: 3, Campaign: 0, Ticket: 0, Reason: 32}}, true, true)
	out = p.flushResearchGoals(s, o)
	q := 0
	for _, sig := range out {
		q += sig.Quantity
		audit154Fill(t, p, sig, 1050)
	}
	if q != 2 || s.held() != 0 {
		t.Fatal("元の全返済が追加玉へ適用されない", q, s.held())
	}
}

// TestAudit154JabOneRounding は実1枚の端数返済を勝手に増やさないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit154JabOneRounding(t *testing.T) {
	p := audit154Portfolio(t, "C02")
	s := audit154Entry(t, p, "core", 5)
	o := audit154Observation(1, 150, 1120)
	p.nativeResearch(s, o, []ResearchEvent{{Action: "close", Side: -1, Quantity: 2, Campaign: 0, Ticket: 0, Reason: 7}}, true, true)
	if out := p.flushResearchGoals(s, o); len(out) != 0 || s.held() != 1 || s.PartialProtection != nil {
		t.Fatal("実0.4枚を1枚返済した", out)
	}
	if out := p.addJab154(s, audit154Observation(2, 250, 1600)); len(out) != 0 {
		t.Fatal("追加なし対照で追加", out)
	}
	p.nativeResearch(s, o, []ResearchEvent{{Action: "close", Side: -1, Quantity: 3, Campaign: 0, Ticket: 0, Reason: 32}}, true, true)
	out := p.flushResearchGoals(s, o)
	if len(out) != 1 || out[0].Quantity != 1 {
		t.Fatal("影終了時の実1枚", out)
	}
}

// TestAudit154ResidualFixedFloor は残玉化時の床が未来ピークや過去ピークへ変化しないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit154ResidualFixedFloor(t *testing.T) {
	p := audit154Portfolio(t, "E05")
	s := audit154Entry(t, p, "episode", 2)
	o := audit154Observation(1, 110, 1100)
	p.nativeResearch(s, o, []ResearchEvent{{Action: "close", Side: -1, Quantity: 1, Campaign: 0, Ticket: 0, Reason: 1435}}, true, true)
	out := p.flushResearchGoals(s, o)
	if len(out) != 1 {
		t.Fatal(out)
	}
	audit154Fill(t, p, out[0], 1100)
	s.FixedR = 1000
	o = audit154Observation(2, 120, 1120)
	p.nativeResearch(s, o, []ResearchEvent{{Action: "close", Side: -1, Quantity: 1, Campaign: 0, Ticket: 0, Reason: 1437}}, true, true)
	p.researchManage(s, o)
	if s.Stage != 2 || s.ResidualFloor154 != 60 || s.Budget != 10000 {
		t.Fatalf("残玉化の床 %+v", s)
	}
	p.researchManage(s, audit154Observation(3, 130, 1300))
	p.researchManage(s, audit154Observation(4, 140, 1070))
	if out := p.flushResearchGoals(s, o); len(out) != 0 || s.ResidualFloor154 != 60 {
		t.Fatal("固定床を追尾半分へ変更", out)
	}
	o = audit154Observation(5, 150, 1060)
	p.researchManage(s, o)
	out = p.flushResearchGoals(s, o)
	if len(out) != 1 || out[0].Quantity != 1 {
		t.Fatal("固定床で返済しない", out)
	}
	audit154Fill(t, p, out[0], 1050)
	if s.Cash != 15000 || s.held() != 0 {
		t.Fatal("判断床価格で保証した", s.Cash)
	}
}

// TestAudit154GuardPrecedence は返済待ちと未知支持を追加機会にしないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit154GuardPrecedence(t *testing.T) {
	for _, kind := range []string{"停止", "返済目標", "未知", "逆向き", "場末"} {
		p := audit154Portfolio(t, "C03")
		s := audit154Entry(t, p, "core", 5)
		o := audit154Observation(2, 150, 1120)
		switch kind {
		case "停止":
			s.ForceReason = 32
		case "返済目標":
			s.setGoal(s.Lots[0].ID, 0, 32)
		case "未知":
			o.Research.Known[20] = false
		case "逆向き":
			o.Research.Values[13] = -1
		case "場末":
			o.Time = p.Session.ForceClose - 299
		}
		if out := p.addJab154(s, o); len(out) != 0 {
			t.Fatal(kind, out)
		}
	}
}

// TestAudit154GuardRealPartialAccounting は実部分返済を二重計上せず、親金額の床を維持することを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit154GuardRealPartialAccounting(t *testing.T) {
	p := audit154Portfolio(t, "G01")
	s := audit154Entry(t, p, "episode", 2)
	o := audit154Observation(1, 120, 1100)
	p.manageGuard154(s, o)
	if s.GuardBest154 != 20000 || s.GuardFloor154 != 10000 || s.GuardQ154 != 2 {
		t.Fatal("初期床", s.GuardBest154, s.GuardFloor154, s.GuardQ154)
	}
	p.nativeResearch(s, o, []ResearchEvent{{Action: "close", Side: -1, Quantity: 1, Campaign: 0, Ticket: 0, Reason: 1435}}, true, true)
	out := p.flushResearchGoals(s, o)
	if len(out) != 1 {
		t.Fatal(out)
	}
	audit154Fill(t, p, out[0], 1100)
	p.manageGuard154(s, audit154Observation(2, 130, 1100))
	if s.Cash != 10000 || s.held() != 1 || s.GuardBest154 != 20000 || s.GuardFloor154 != 10000 {
		t.Fatal("部分返済の二重計上又は床の再初期化", s.Cash, s.GuardBest154, s.GuardFloor154)
	}
	o = audit154Observation(3, 140, 1000)
	p.manageGuard154(s, o)
	out = p.flushResearchGoals(s, o)
	if len(out) != 1 || out[0].Quantity != 1 || !s.Blocked {
		t.Fatal("親金額半減で返済しない", out)
	}
	audit154Fill(t, p, out[0], 980)
	if s.Cash != 8000 {
		t.Fatal("利益床価格で仮想約定した", s.Cash)
	}
}

// TestAudit154GuardAdditionKeepsInitialBudget は追加の気配差負担と固定起動枚数を確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit154GuardAdditionKeepsInitialBudget(t *testing.T) {
	p := audit154Portfolio(t, "G01")
	s := audit154Entry(t, p, "addon", 2)
	o := audit154Observation(1, 120, 1100)
	p.manageGuard154(s, o)
	out := p.nativeResearch(s, o, []ResearchEvent{{Action: "new", Side: 1, Quantity: 1, Campaign: 0, Ticket: 1, Reason: 142}}, true, true)
	if len(out) != 1 {
		t.Fatal(out)
	}
	audit154Fill(t, p, out[0], 1110)
	p.manageGuard154(s, audit154Observation(2, 130, 1100))
	if s.GuardQ154 != 2 || s.GuardBest154 != 20000 || s.GuardFloor154 != 10000 {
		t.Fatal("追加による起動枚数又は床の変更", s.GuardQ154, s.GuardBest154, s.GuardFloor154)
	}
	o = audit154Observation(3, 140, 1050)
	p.manageGuard154(s, o)
	out = p.flushResearchGoals(s, o)
	q := 0
	for _, sig := range out {
		q += sig.Quantity
		audit154Fill(t, p, sig, 1040)
	}
	if q != 3 || s.Cash != 1000 || s.held() != 0 {
		t.Fatal("追加損失を含む親清算が不一致", q, s.Cash)
	}
}

// TestAudit154GuardShortAndUnknown は売りにも同じ返済側基準を使い、不正板のピークを無視することを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit154GuardShortAndUnknown(t *testing.T) {
	p := audit154Portfolio(t, "G02")
	s := p.sleeve("episode")
	out := p.nativeResearch(s, audit154Observation(0, 100, 1000), []ResearchEvent{{Action: "new", Side: -1, Quantity: 2, Campaign: 0, Ticket: 0}}, true, true)
	audit154Fill(t, p, out[0], 1000)
	o := audit154Observation(1, 120, 900)
	p.manageGuard154(s, o)
	if s.GuardBest154 != 18000 || s.GuardFloor154 != 9000 {
		t.Fatal("売りでAskを使わない", s.GuardBest154)
	}
	bad := audit154Observation(2, 130, 100)
	bad.QuoteOK = false
	p.manageGuard154(s, bad)
	if s.GuardBest154 != 18000 {
		t.Fatal("不正板でピーク上書き")
	}
	o = audit154Observation(3, 140, 945)
	p.manageGuard154(s, o)
	out = p.flushResearchGoals(s, o)
	if len(out) != 1 || out[0].Side != 1 || out[0].Quantity != 2 {
		t.Fatal("売りの利益半減", out)
	}
}

// TestAudit154GuardBlocksSameRowAddAndAllowsNextParent は床割れ当行の追加を止め、完済後の新親だけを受け入れます。
//
// 引数: t(*testing.T)。返り値: なし。実約定と元の仮想親を分離して確認します。
func TestAudit154GuardBlocksSameRowAddAndAllowsNextParent(t *testing.T) {
	p := audit154Portfolio(t, "G01")
	s := audit154Entry(t, p, "addon", 2)
	p.manageGuard154(s, audit154Observation(1, 120, 1100))
	o := audit154Observation(2, 150, 1030)
	p.manageGuard154(s, o)
	if p.guardEntryAllowed154(s, false) {
		t.Fatal("床割れで当行新規を許可")
	}
	out := p.nativeResearch(s, o, []ResearchEvent{{Action: "new", Side: 1, Quantity: 1, Campaign: 0, Ticket: 1, Reason: 142}}, p.guardEntryAllowed154(s, false), true)
	if len(out) != 0 || s.held() != 2 || s.Virtual[1] != 1 {
		t.Fatal("当行追加又は仮想会計の削除", out)
	}
	out = p.flushResearchGoals(s, o)
	if len(out) != 1 || out[0].Quantity != 2 {
		t.Fatal(out)
	}
	audit154Fill(t, p, out[0], 1020)
	if !p.guardEntryAllowed154(s, false) {
		t.Fatal("完済後の新親まで禁止")
	}
	out = p.nativeResearch(s, audit154Observation(3, 180, 1200), []ResearchEvent{{Action: "new", Side: 1, Quantity: 1, Campaign: 0, Ticket: 2}}, true, true)
	if len(out) != 0 {
		t.Fatal("同じ停止親へ再追加", out)
	}
	out = p.nativeResearch(s, audit154Observation(4, 200, 1200), []ResearchEvent{{Action: "new", Side: 1, Quantity: 2, Campaign: 1, Ticket: 0}}, true, true)
	if len(out) != 1 || s.GuardActive154 || s.GuardQ154 != 0 || s.GuardFloor154 != 0 || s.Blocked {
		t.Fatal("新親で保護値が残留", out)
	}
	if p.guardEntryAllowed154(s, true) {
		t.Fatal("元退出と混在した同原行newを許可")
	}
}
