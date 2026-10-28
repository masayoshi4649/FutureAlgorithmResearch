package strategy

import (
	"errors"
	"math"
)

// ReentryArm1562 は実保護完済後だけ存在する同波の新しい追尾準備です。
type ReentryArm1562 struct {
	Owner                    string
	Campaign, Side, Quantity int
	ClosedAt                 float64
	FillIndex, SeedIndex     int64
	Extreme                  float64
	Seeded                   bool
}

// ReentryBatch1562 は同担当を全て保護返済する注文群の実約定累計です。
type ReentryBatch1562 struct {
	Campaign, Side, Quantity, Filled int
}

// ReentryTarget1562 は元仮想数量とは独立した再参加玉の比例返済目標です。
type ReentryTarget1562 struct {
	Owner                                        string
	Campaign, Side, Ticket, Requested, Remaining int
}

// ReentryAudit1562 は再参加の準備・取消・発注を当時の原行とともに保存します。
type ReentryAudit1562 struct {
	Owner, Action, Reason            string
	Campaign, Side, Quantity, Ticket int
	Time, Extreme, Mark              float64
	Index                            int64
}

// ReentryState1562 は第2巡だけの元源を待たない再参加状態です。
type ReentryState1562 struct {
	Width    float64
	Sequence int
	Arms     map[string]*ReentryArm1562
	Batches  map[string]*ReentryBatch1562
	Targets  map[int]*ReentryTarget1562
	Audit    []ReentryAudit1562
}

// ConfigureReentry1562 は全玉保護を設定済みの日中候補へ再参加幅を固定します。
//
// 引数: width(float64)は20/40/80pt。返り値: errorは設定順又は数値の不正です。
func (p *Portfolio) ConfigureReentry1562(width float64) error {
	if p.Study156 == nil || p.Study156.Width <= 0 || p.Study156.Gate || p.Study156.Activation != 0 || p.LastIndex != -1 || p.Reentry1562 != nil || (width != 20 && width != 40 && width != 80) {
		return errors.New("第2巡は未観測の即時玉別保護だけに固定再参加幅を設定します")
	}
	p.Reentry1562 = &ReentryState1562{Width: width, Arms: map[string]*ReentryArm1562{}, Batches: map[string]*ReentryBatch1562{}, Targets: map[int]*ReentryTarget1562{}}
	return nil
}

// originalQuantity1562 は再参加の負番号ticketを含めず元通知の残数だけを合計します。
//
// 引数: s(*ResearchSleeve)。返り値: intは元の採用済み仮想数量です。
func originalQuantity1562(s *ResearchSleeve) int {
	n := 0
	for ticket, quantity := range s.Virtual {
		if ticket >= 0 {
			n += quantity
		}
	}
	return n
}

// sourceContinues1562 は当時の元源が同じ親・同方向を実際に継続しているか確認します。
//
// 引数: s(*ResearchSleeve)。返り値: bool。実側の残数だけで継続を推定しません。
func sourceContinues1562(s *ResearchSleeve) bool {
	if originalQuantity1562(s) <= 0 || s.Source == nil {
		return false
	}
	v := s.Source
	if v.Legacy != nil {
		pos := v.Legacy.Core.Position
		if s.Campaign == 10000 {
			pos = v.Supplement.Extra.Position
		}
		return pos.Quantity > 0 && pos.Campaign == s.Campaign && pos.Side == s.Side
	}
	var b *ResearchBook
	if v.Episode != nil {
		b = &v.Episode.Book
	}
	if v.Active != nil {
		b = &v.Active.Book
	}
	if v.Active145 != nil {
		b = &v.Active145.Book
	}
	return b != nil && b.Parent == s.Campaign && b.Side == s.Side && b.total() > 0
}

// allProtected1562 は残玉全てが玉別保護の全返済目標に入っていることを検査します。
//
// 引数: s(*ResearchSleeve)。返り値: boolは元部分返済や一部玉だけの保護を除外します。
func allProtected1562(s *ResearchSleeve) bool {
	if s.held() == 0 {
		return false
	}
	for _, l := range s.Lots {
		if l.Quantity <= 0 {
			continue
		}
		g, ok := s.Goals[l.ID]
		if !ok || g.Remaining != 0 || (g.Reason != 15601 && g.Reason != 15602) {
			return false
		}
	}
	return true
}

// recordReentryFill1562 は実完済だけを準備へ変え、元部分返済では準備しません。
//
// 引数: s(*ResearchSleeve)、f(Fill)、e(Signal)。返り値: なし。
// 複数所有玉の保護返済は同じ注文群として実約定量を積算し、当初自己数を超えません。
func (p *Portfolio) recordReentryFill1562(s *ResearchSleeve, f Fill, e Signal) {
	r := p.Reentry1562
	if r == nil {
		return
	}
	if e.Action == "new" {
		delete(r.Arms, s.Name)
		delete(r.Batches, s.Name)
		if target := r.Targets[e.Ticket]; target != nil {
			p.applyReentryTarget1562(s, target, 15634)
		}
		return
	}
	if e.ReasonCode != 15601 && e.ReasonCode != 15602 {
		delete(r.Batches, s.Name)
		return
	}
	b := r.Batches[s.Name]
	if b == nil || b.Campaign != s.Campaign {
		return
	}
	b.Filled += f.Quantity
	if s.held() > 0 {
		return
	}
	delete(r.Batches, s.Name)
	if b.Filled != b.Quantity || s.Blocked || s.ForceReason != 0 {
		return
	}
	requested := 0
	for ticket, n := range s.Requested {
		if ticket >= 0 {
			requested += n
		}
	}
	q := min(b.Quantity, min(s.Capacity, requested))
	if q <= 0 {
		return
	}
	r.Arms[s.Name] = &ReentryArm1562{Owner: s.Name, Campaign: s.Campaign, Side: s.Side, Quantity: q, ClosedAt: f.Time, FillIndex: -1, SeedIndex: -1}
}

// applyReentryTarget1562 は再参加玉へ専用の比例残数目標を所有ID順に適用します。
//
// 引数: s(*ResearchSleeve)、target(*ReentryTarget1562)、reason(int)。返り値: なし。
// 初回注文の部分約定中にも累計約定比で残目標を計算し、遅着分を逃がしません。
func (p *Portfolio) applyReentryTarget1562(s *ResearchSleeve, target *ReentryTarget1562, reason int) {
	if target.Campaign != s.Campaign || target.Requested <= 0 {
		return
	}
	left := int(math.Floor(float64(s.Opened[target.Ticket]*target.Remaining)/float64(target.Requested) + .5))
	actual := 0
	for _, l := range s.Lots {
		if l.Ticket == target.Ticket {
			actual += l.Quantity
		}
	}
	close := max(0, actual-left)
	for _, l := range s.Lots {
		if l.Ticket != target.Ticket || close <= 0 {
			continue
		}
		q := min(l.Quantity, close)
		s.setGoal(l.ID, l.Quantity-q, reason)
		close -= q
	}
}

// applySourceToReentry1562 は参加後に新しく出た元源の退出だけを再参加玉へ比例接続します。
//
// 引数: s(*ResearchSleeve)、o(Observation)、events([]ResearchEvent)、before(int)。返り値: なし。
// 最近整数へ丸め、仮想全返済又は親変更は必ず全数返済します。元親の分母は変更しません。
func (p *Portfolio) applySourceToReentry1562(s *ResearchSleeve, o Observation, events []ResearchEvent, before int) {
	r := p.Reentry1562
	if r == nil {
		return
	}
	closed, reason := 0, 15634
	for _, e := range events {
		if e.Action == "close" && e.Campaign == s.Campaign {
			closed += e.Quantity
			reason = e.Reason
		}
	}
	continuing := sourceContinues1562(s)
	if continuing && closed == 0 && o.Time < p.Session.ForceClose {
		return
	}
	for _, target := range r.Targets {
		if target.Owner != s.Name || target.Campaign != s.Campaign || target.Remaining <= 0 {
			continue
		}
		if !continuing || o.Time >= p.Session.ForceClose {
			target.Remaining = 0
		} else if closed > 0 && before > 0 {
			target.Remaining = int(math.Floor(float64(target.Remaining)*float64(max(0, before-closed))/float64(before) + .5))
		}
		p.applyReentryTarget1562(s, target, reason)
	}
}

// manageReentry1562 は元注文処理後に新しい気配極値から再参加を判断します。
//
// 引数: s(*ResearchSleeve)、o(Observation)、events([]ResearchEvent)、allow/emit(bool)。返り値: []Signal。
// 完済fill原行は記録だけ、翌正常原行を新極値の起点とし、その後の原行だけ発注可能です。
func (p *Portfolio) manageReentry1562(s *ResearchSleeve, o Observation, events []ResearchEvent, allow, emit bool) []Signal {
	r := p.Reentry1562
	if r == nil {
		return nil
	}
	a := r.Arms[s.Name]
	if a == nil {
		return nil
	}
	firstObservation := a.FillIndex < 0
	if firstObservation {
		a.FillIndex = o.Index
		r.Audit = append(r.Audit, ReentryAudit1562{Owner: s.Name, Action: "準備", Reason: "全自己玉の利益保護返済が実約定", Campaign: a.Campaign, Side: a.Side, Quantity: a.Quantity, Time: a.ClosedAt, Index: o.Index})
	}
	cancel := ""
	if a.Campaign != s.Campaign || a.Side != s.Side || !sourceContinues1562(s) {
		cancel = "元源の完済・反転・親変更"
	}
	if o.Time >= p.Session.ForceClose {
		cancel = "場末"
	}
	if s.Blocked || s.ForceReason != 0 || s.Stage > 0 {
		cancel = "元の親退出又は残玉段階"
	}
	pending, _ := p.pendingResearch(s.Name)
	if s.held() > 0 {
		cancel = "通常新規の実玉が優先"
	}
	for _, e := range events {
		if e.Action == "new" && e.Campaign == s.Campaign {
			cancel = "通常の追加通知が優先"
		}
	}
	if cancel != "" {
		r.Audit = append(r.Audit, ReentryAudit1562{Owner: s.Name, Action: "取消", Reason: cancel, Campaign: a.Campaign, Side: a.Side, Quantity: a.Quantity, Time: o.Time, Index: o.Index})
		delete(r.Arms, s.Name)
		return nil
	}
	if firstObservation {
		return nil
	}
	if !quoteValid(o) || !emit || !p.s01Fresh || o.Index <= a.FillIndex {
		return nil
	}
	mark := liquidation(o, a.Side)
	if !a.Seeded {
		a.Extreme, a.SeedIndex, a.Seeded = mark, o.Index, true
		return nil
	}
	if a.Side > 0 {
		a.Extreme = math.Min(a.Extreme, mark)
	} else {
		a.Extreme = math.Max(a.Extreme, mark)
	}
	if !allow || pending || closing156(s) || len(events) > 0 || o.Index <= a.SeedIndex || float64(a.Side)*(mark-a.Extreme) < r.Width {
		return nil
	}
	q := min(a.Quantity, s.Capacity)
	if q <= 0 {
		return nil
	}
	r.Sequence++
	ticket := -r.Sequence
	r.Targets[ticket] = &ReentryTarget1562{Owner: s.Name, Campaign: s.Campaign, Side: s.Side, Ticket: ticket, Requested: q, Remaining: q}
	s.Requested[ticket] = q
	e := ResearchEvent{Action: "new", Side: s.Side, Quantity: q, Reason: 15630, Campaign: s.Campaign, Ticket: ticket, Risk: s.FixedR, Boundary: a.Extreme + float64(s.Side)*r.Width}
	r.Audit = append(r.Audit, ReentryAudit1562{Owner: s.Name, Action: "発注", Reason: "新極値から同方向へ回復", Campaign: s.Campaign, Side: s.Side, Quantity: q, Ticket: ticket, Time: o.Time, Index: o.Index, Extreme: a.Extreme, Mark: mark})
	delete(r.Arms, s.Name)
	return []Signal{p.emitResearch(s, o, e, nil)}
}

// planReentryBatch1562 は発注時の全返済注文群だけで再参加資格と数量を固定します。
//
// 引数: s(*ResearchSleeve)、signals([]Signal)。返り値: なし。
// 元理由と保護理由の混合群は約定順によらず不適格、未約定取消後の残数再依頼は同群を維持します。
func (p *Portfolio) planReentryBatch1562(s *ResearchSleeve, signals []Signal) {
	r := p.Reentry1562
	if r == nil || len(signals) == 0 {
		return
	}
	if !allProtected1562(s) {
		delete(r.Batches, s.Name)
		return
	}
	n := 0
	for _, sig := range signals {
		if sig.Action != "close" || (sig.ReasonCode != 15601 && sig.ReasonCode != 15602) {
			delete(r.Batches, s.Name)
			return
		}
		n += sig.Quantity
	}
	if n != s.held() {
		delete(r.Batches, s.Name)
		return
	}
	if b := r.Batches[s.Name]; b != nil && b.Campaign == s.Campaign && b.Side == s.Side {
		return
	}
	r.Batches[s.Name] = &ReentryBatch1562{Campaign: s.Campaign, Side: s.Side, Quantity: s.held()}
}
