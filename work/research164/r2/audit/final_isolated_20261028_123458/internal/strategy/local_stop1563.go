package strategy

import "errors"

// ConfigureLocalStop1563 は未観測の再参加候補へ実建値からの損失幅を固定します。
//
// 引数: width(float64)は20/40/80pt。返り値: errorは設定順又は固定条件の不正です。
// 元Sourceと初回玉を変更せず、負ticketの再参加玉だけを対象にします。
func (p *Portfolio) ConfigureLocalStop1563(width float64) error {
	if p.Reentry1562 == nil || p.Reentry1562.Width != 20 || p.Reentry1562.LocalStop != 0 || p.LastIndex != -1 || (width != 20 && width != 40 && width != 80) {
		return errors.New("第三巡は未観測の20pt再参加へ固定20/40/80pt損失幅だけを設定します")
	}
	p.Reentry1562.LocalStop = width
	return nil
}

// applyLocalStop1563 は再参加玉の実建値から固定幅を逆行した残数へ返済目標を置きます。
//
// 引数: s(*ResearchSleeve)、o(Observation)、fresh(bool)。返り値: なし。
// 元退出・部分返済・利益床・未確定注文を優先し、未保有予約や正ticketを触りません。
// 発火価格での約定は保証せず、既存の次正常板約定と全損失計上を維持します。
func (p *Portfolio) applyLocalStop1563(s *ResearchSleeve, o Observation, fresh bool) {
	r := p.Reentry1562
	if r == nil || r.LocalStop <= 0 || !fresh || !quoteValid(o) || s.ForceReason != 0 {
		return
	}
	if pending, _ := p.pendingResearch(s.Name); pending {
		return
	}
	mark := liquidation(o, s.Side)
	for _, l := range s.Lots {
		if l.Ticket >= 0 || l.Quantity <= 0 || float64(s.Side)*(mark-l.Price) > -r.LocalStop {
			continue
		}
		if goal, ok := s.Goals[l.ID]; ok && goal.Remaining < l.Quantity {
			continue
		}
		s.setGoal(l.ID, 0, 15631)
	}
}
