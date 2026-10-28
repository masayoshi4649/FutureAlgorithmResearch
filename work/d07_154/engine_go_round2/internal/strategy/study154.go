package strategy

// episode154 は残り1枚の変更を別入口担当だけへ適用します。
//
// 引数: s(*ResearchSleeve)、kind(string)。返り値: boolは研究条件への該当です。
func (p *Portfolio) episode154(s *ResearchSleeve, kind string) bool {
	if s.Name != "episode" {
		return false
	}
	id := p.Config.Study154
	if kind == "E03" && (id == "X01" || id == "X02") {
		return true
	}
	if kind == "E05" && id == "X03" {
		return true
	}
	return id == kind
}

// jab154 は日中の主担当だけを初回1枚へ分離する条件です。
//
// 引数: s(*ResearchSleeve)。返り値: boolはC02/C03又はその固定組合せです。
func (p *Portfolio) jab154(s *ResearchSleeve) bool {
	id := p.Config.Study154
	if id == "J01" || id == "J02" || id == "J03" {
		return p.Session.Kind == "Day" && s.Name == "core" && s.JabMode154 > 0
	}
	return p.Session.Kind == "Day" && s.Name == "core" && (id == "C02" || id == "C03" || id == "X02" || id == "X03")
}

// addJab154 は固定初回Rごとの順行と短期支持を確認し、1枚だけ追加予約します。
//
// 引数: s(*ResearchSleeve)、o(Observation)。返り値: []Signalは現在の予約、未成立ならnilです。
// 仮想源の枚数・出口は変更しません。元Ticketを共有し、既存退出を追加玉にも適用します。
func (p *Portfolio) addJab154(s *ResearchSleeve, o Observation) []Signal {
	if !p.jab154(s) || p.Config.Study154 == "C02" || s.JabMode154 == 2 || s.Opened154 <= 0 || s.Opened154 >= s.Capacity || s.held() == 0 || s.Blocked || s.Stage != 0 || s.ForceReason != 0 || !quoteValid(o) || o.Time >= p.Session.ForceClose-300 {
		return nil
	}
	if pending, _ := p.pendingResearch(s.Name); pending {
		return nil
	}
	if len(s.CloseReason) > 0 || s.PartialProtection != nil {
		return nil
	}
	for _, l := range s.Lots {
		if g, ok := s.Goals[l.ID]; ok && g.Remaining < l.Quantity {
			return nil
		}
	}
	f := o.Research
	d := float64(s.Side)
	if !featureKnown(f, 12, 13, 20) || d*f.Values[12] <= 0 || d*f.Values[13] <= 0 || d*f.Values[20] < 0 {
		return nil
	}
	if o.Time-s.LastAdd154 < 30 || d*(liquidation(o, s.Side)-s.Anchor154) < .5*float64(s.Opened154)*s.FixedR {
		return nil
	}
	e := ResearchEvent{Action: "new", Side: s.Side, Quantity: 1, Reason: 15403, Campaign: s.Campaign, Ticket: s.Ticket154, Risk: s.FixedR}
	return []Signal{p.emitResearch(s, o, e, nil)}
}

// guard154 は親の利益保護を開始する初回損失幅に対する倍率を返します。
//
// 引数: なし。返り値: float64はG01で0.5、G02で1、それ以外で0です。
func (p *Portfolio) guard154() float64 {
	if p.Config.Study154 == "G01" {
		return .5
	}
	if p.Config.Study154 == "G02" {
		return 1
	}
	return 0
}

// guardEntryAllowed154 は全返済中だけ新規を止め、完済後の新親まで禁止しません。
//
// 引数: s(*ResearchSleeve)、sourceClose(bool)。返り値: boolは当行の新規許可です。
func (p *Portfolio) guardEntryAllowed154(s *ResearchSleeve, sourceClose bool) bool {
	if sourceClose {
		return false
	}
	if s.held() > 0 && (s.Blocked || s.ForceReason != 0) {
		return false
	}
	for _, l := range s.Lots {
		if g, ok := s.Goals[l.ID]; ok && g.Remaining < l.Quantity {
			return false
		}
	}
	return true
}

// manageGuard154 は実現と現在清算含みの親合計に対して、最高益半分を保護します。
//
// 引数: s(*ResearchSleeve)、o(Observation)。返り値: なし。
// 初回Rと初回実約定枚数を固定し、追加・部分利確・残1化では保護を再起算しません。
func (p *Portfolio) manageGuard154(s *ResearchSleeve, o Observation) {
	ratio := p.guardFor154(s)
	if ratio <= 0 || s.GuardQ154 <= 0 || s.held() == 0 || !quoteValid(o) {
		return
	}
	value := p.researchCash(s)
	mark := liquidation(o, s.Side)
	for _, l := range s.Lots {
		value += float64(s.Side*l.Quantity) * (mark - l.Price) * p.Config.PointValue
	}
	if !s.GuardActive154 && value >= ratio*s.FixedR*float64(s.GuardQ154)*p.Config.PointValue {
		s.GuardActive154 = true
		s.GuardBest154 = value
	}
	if !s.GuardActive154 {
		return
	}
	if value > s.GuardBest154 {
		s.GuardBest154 = value
	}
	floor := .5 * s.GuardBest154
	if floor > s.GuardFloor154 {
		s.GuardFloor154 = floor
	}
	if value > s.GuardFloor154 || s.ForceReason != 0 {
		return
	}
	if pending, _ := p.pendingResearch(s.Name); pending {
		return
	}
	for _, l := range s.Lots {
		if g, ok := s.Goals[l.ID]; ok && g.Remaining < l.Quantity {
			return
		}
	}
	closeAllResearch(s, 15410)
}
