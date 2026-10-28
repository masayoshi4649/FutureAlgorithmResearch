package strategy

import "testing"

// auditReentry1562 は元源だけ保有を継続し、実玉は保護完済済みの人工状態を作ります。
//
// 引数: side(int)。返り値: *Portfolio、*ResearchSleeve。
func auditReentry1562(side int) (*Portfolio, *ResearchSleeve) {
	p, s := auditPortfolio156(0, 20, 0)
	s.Name = "addon"
	s.Capacity = 3
	s.Side = side
	s.Virtual[0] = 3
	s.Requested[0] = 3
	s.Source = &ResearchSource{Active145: &ResearchActive145{ResearchActive: ResearchActive{Book: ResearchBook{Parent: 1, Side: side, Held: [6]int{3}}}}}
	p.s01Fresh = true
	p.Reentry1562 = &ReentryState1562{Width: 20, Arms: map[string]*ReentryArm1562{"addon": {Owner: "addon", Campaign: 1, Side: side, Quantity: 3, ClosedAt: 100, FillIndex: -1, SeedIndex: -1}}, Batches: map[string]*ReentryBatch1562{}, Targets: map[int]*ReentryTarget1562{}}
	return p, s
}

// TestAudit1562NewExtremeAfterFillAndSeed は約定原行・種原行・回復原行を分け、買売鏡像の新情報だけで再参加します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit1562NewExtremeAfterFillAndSeed(t *testing.T) {
	for _, side := range []int{1, -1} {
		p, s := auditReentry1562(side)
		if out := p.manageReentry1562(s, auditObservation156(100, 1000, side), nil, true, true); len(out) > 0 {
			t.Fatal("返済fill当行の再新規")
		}
		if out := p.manageReentry1562(s, auditObservation156(101, 1000, side), nil, true, true); len(out) > 0 {
			t.Fatal("極値初期化行の再新規")
		}
		if out := p.manageReentry1562(s, auditObservation156(102, 1000-float64(side)*20, side), nil, true, true); len(out) > 0 {
			t.Fatal("順方向へ戻る前の再新規")
		}
		out := p.manageReentry1562(s, auditObservation156(103, 1000, side), nil, true, true)
		if len(out) != 1 || out[0].Side != side || out[0].Quantity != 3 || out[0].Ticket >= 0 || out[0].ReasonCode != 15630 {
			t.Fatal("新しい回復で発注されない", out)
		}
		if originalQuantity1562(s) != 3 || len(s.Virtual) != 1 {
			t.Fatal("再参加が元仮想数量を改変")
		}
		if p.Reentry1562.Arms["addon"] != nil {
			t.Fatal("予約と待機が二重存在")
		}
		if again := p.manageReentry1562(s, auditObservation156(104, 1020, side), nil, true, true); len(again) > 0 {
			t.Fatal("未約定中の二重参加")
		}
	}
}

// TestAudit1562SourceEndReversalAndNormalOrderCancel は元終了・反転・通常追加・場末を極値成立より優先します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit1562SourceEndReversalAndNormalOrderCancel(t *testing.T) {
	for _, kind := range []string{"完済", "反転", "通常追加", "場末", "既玉"} {
		p, s := auditReentry1562(1)
		a := p.Reentry1562.Arms[s.Name]
		a.FillIndex = 98
		a.SeedIndex = 99
		a.Seeded = true
		a.Extreme = 980
		o := auditObservation156(100, 1020, 1)
		var events []ResearchEvent
		switch kind {
		case "完済":
			s.Source.Active145.Book.Held = [6]int{}
		case "反転":
			s.Source.Active145.Book.Side = -1
		case "通常追加":
			events = []ResearchEvent{{Action: "new", Campaign: s.Campaign, Quantity: 1, Side: 1}}
		case "場末":
			o.Time = p.Session.ForceClose
		case "既玉":
			s.Lots = []ResearchLot{{ID: "通常玉", Quantity: 1, Price: 1000}}
		}
		if out := p.manageReentry1562(s, o, events, true, true); len(out) > 0 || p.Reentry1562.Arms[s.Name] != nil {
			t.Fatal("優先取消漏れ", kind, out)
		}
	}
}

// TestAudit1562FreshnessAndAllowGate は古い板・許可なし・未確定注文を新たな発注根拠にしません。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit1562FreshnessAndAllowGate(t *testing.T) {
	for _, kind := range []string{"古い板", "新規禁止", "注文中"} {
		p, s := auditReentry1562(1)
		a := p.Reentry1562.Arms[s.Name]
		a.FillIndex = 98
		a.SeedIndex = 99
		a.Seeded = true
		a.Extreme = 980
		allow := true
		switch kind {
		case "古い板":
			p.s01Fresh = false
		case "新規禁止":
			allow = false
		case "注文中":
			p.Orders["未確定"] = &orderState{Signal: Signal{Owner: s.Name, Action: "close", Quantity: 1}}
		}
		if out := p.manageReentry1562(s, auditObservation156(100, 1020, 1), nil, allow, true); len(out) > 0 {
			t.Fatal("制約を超えて再新規", kind)
		}
	}
}

// TestAudit1562ProportionalExitPreservesOriginalVirtual は元の減量比を再参加玉へ接続し、原終了では全返済します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit1562ProportionalExitPreservesOriginalVirtual(t *testing.T) {
	p, s := auditReentry1562(1)
	s.Capacity = 5
	s.Virtual[0] = 3
	s.Source.Active145.Book.Held = [6]int{3}
	s.Requested[-1] = 5
	s.Opened[-1] = 5
	s.Lots = []ResearchLot{{ID: "再参加玉", Ticket: -1, Quantity: 5, Price: 1000}}
	target := &ReentryTarget1562{Owner: s.Name, Campaign: 1, Side: 1, Ticket: -1, Requested: 5, Remaining: 5}
	p.Reentry1562.Targets[-1] = target
	p.applySourceToReentry1562(s, auditObservation156(101, 1010, 1), []ResearchEvent{{Action: "close", Campaign: 1, Quantity: 2, Reason: 70}}, 5)
	if target.Remaining != 3 || s.Goals["再参加玉"].Remaining != 3 || originalQuantity1562(s) != 3 {
		t.Fatal("5→3比例又は元Virtual改変", target, s.Goals)
	}
	s.Lots[0].Quantity = 3
	s.Virtual[0] = 2
	s.Source.Active145.Book.Held = [6]int{2}
	p.applySourceToReentry1562(s, auditObservation156(102, 1010, 1), []ResearchEvent{{Action: "close", Campaign: 1, Quantity: 1, Reason: 70}}, 3)
	if target.Remaining != 2 || s.Goals["再参加玉"].Remaining != 2 {
		t.Fatal("3→2比例不正")
	}
	s.Lots[0].Quantity = 2
	s.Virtual[0] = 0
	s.Source.Active145.Book.Held = [6]int{}
	p.applySourceToReentry1562(s, auditObservation156(103, 1010, 1), nil, 2)
	if target.Remaining != 0 || s.Goals["再参加玉"].Remaining != 0 {
		t.Fatal("元源の完済後に残玉")
	}
}

// TestAudit1562NewFillGetsOwnPriceAndGuard は再参加実玉が旧利益玉の建値や高値を引き継がないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit1562NewFillGetsOwnPriceAndGuard(t *testing.T) {
	p, s := auditReentry1562(1)
	p.Study156.Lots["旧玉"] = &LotGuard156{ID: "旧玉", Entry: 900, BestPrice: 1100, FloorPrice: 1080, Active: true}
	s.Lots = []ResearchLot{{ID: "旧玉", Price: 900, Quantity: 0}, {ID: "再参加玉", Ticket: -1, Price: 1020, Quantity: 3}}
	p.updateLot156(s, auditObservation156(104, 1010, 1))
	p.applyLot156(s, auditObservation156(104, 1010, 1), true)
	g := p.Study156.Lots["再参加玉"]
	if g.Entry != 1020 || g.Active || len(s.Goals) > 0 {
		t.Fatal("旧高値を新玉へ転用", g, s.Goals)
	}
}

// TestAudit1562MixedBatchCannotBecomeEligible は元退出と保護の混在を発注順・約定順から独立して拒否します。
//
// 引数: t(*testing.T)。返り値: なし。対象2玉のうち最後だけ保護でも準備を作りません。
func TestAudit1562MixedBatchCannotBecomeEligible(t *testing.T) {
	for _, reverse := range []bool{false, true} {
		p, s := auditReentry1562(1)
		delete(p.Reentry1562.Arms, s.Name)
		s.Lots = []ResearchLot{{ID: "元退出玉", Ticket: 0, Quantity: 1, Price: 1000}, {ID: "保護玉", Ticket: 1, Quantity: 2, Price: 1000}}
		s.Goals["元退出玉"] = ResearchGoal{Remaining: 0, Reason: 30}
		s.Goals["保護玉"] = ResearchGoal{Remaining: 0, Reason: 15601}
		orders := []Signal{{Action: "close", Quantity: 1, ReasonCode: 30}, {Action: "close", Quantity: 2, ReasonCode: 15601}}
		p.planReentryBatch1562(s, orders)
		if p.Reentry1562.Batches[s.Name] != nil {
			t.Fatal("混合注文群が適格")
		}
		if reverse {
			orders[0], orders[1] = orders[1], orders[0]
		}
		for i, sig := range orders {
			if i == 1 {
				s.Lots = nil
			}
			p.recordReentryFill1562(s, Fill{Time: 100, Quantity: sig.Quantity}, sig)
		}
		if p.Reentry1562.Arms[s.Name] != nil {
			t.Fatal("最後の保護約定だけで再参加資格を新設")
		}
	}
}

// TestAudit1562PrepareAuditUsesFillObservation は準備の時刻と原行を実返済行へ揃えます。
//
// 引数: t(*testing.T)。返り値: なし。直前判断行のIndexを完済原行として保存しません。
func TestAudit1562PrepareAuditUsesFillObservation(t *testing.T) {
	p, s := auditReentry1562(1)
	o := auditObservation156(100, 1000, 1)
	p.LastIndex = 99
	p.manageReentry1562(s, o, nil, true, true)
	if len(p.Reentry1562.Audit) != 1 {
		t.Fatal("準備監査件数")
	}
	a := p.Reentry1562.Audit[0]
	if a.Index != o.Index || a.Time != 100 || a.Action != "準備" {
		t.Fatal("準備監査の時計・原行差", a)
	}
}
