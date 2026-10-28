package strategy

import (
	"errors"
	"math"
)

// LotGuard156 は実所有玉ごとの建値・有利気配・単調な利益床を保存します。
type LotGuard156 struct {
	ID, Owner                    string
	Campaign, Side               int
	Entry, BestPrice, FloorPrice float64
	Active                       bool
	ActivatedAt, TriggeredAt     float64
}

// Reference156 は同原行までの無変更S01の担当占有だけを保持します。
type Reference156 struct {
	Campaign int
	Occupied bool
	Time     float64
}
type Rejection156 struct {
	Owner     string
	Campaign  int
	Index     int64
	Time      float64
	Reference Reference156
}

// StudyState156 は研究専用の玉別保護と当時の参照を保存します。実アプリへは移植しません。
type StudyState156 struct {
	EntryRule         int
	MinuteSlot        int
	MinuteSeen        bool
	MinuteLast        float64
	Minutes           []Minute156
	EntryRejected     []EntryRejection156
	Width, Activation float64
	Gate              bool
	Lots              map[string]*LotGuard156
	Reference         map[string]Reference156
	Rejected          []Rejection156
}

// Configure156 は観測開始前に固定された研究条件を設定します。
//
// 引数: width/activation(float64)、gate(bool)、entryRule(int)。返り値: errorは条件又は初期化順の不正です。
func (p *Portfolio) Configure156(width, activation float64, gate bool, entryRule int) error {
	if p.Config.Parameters.Method != "S01" || p.Session.Kind != "Day" || p.LastIndex != -1 || p.Study156 != nil {
		return errors.New("156は未観測の日中S01だけ設定可能です")
	}
	if (width != 10 && width != 20 && width != 40 && width != 80 && !(width == 0 && entryRule > 0)) || (activation != 0 && activation != 20) || entryRule < 0 || entryRule > 3 {
		return errors.New("156の固定条件ではありません")
	}
	p.Study156 = &StudyState156{Width: width, Activation: activation, Gate: gate, EntryRule: entryRule, Lots: map[string]*LotGuard156{}, Reference: map[string]Reference156{}}
	return nil
}

// SetReference156 は基準S01の現在の親と保有・予約を値コピーします。
//
// 引数: base(*Portfolio)。返り値: なし。将来の終了時計や注文列は渡しません。
func (p *Portfolio) SetReference156(base *Portfolio) {
	if p.Study156 == nil {
		return
	}
	p.Study156.Reference = map[string]Reference156{}
	if base == nil || base.Research == nil {
		return
	}
	for _, s := range base.Research.Sleeves {
		pending, _ := base.pendingResearch(s.Name)
		p.Study156.Reference[s.Name] = Reference156{Campaign: s.Campaign, Occupied: s.held() > 0 || pending, Time: base.LastTime}
	}
}

// entryAllowed156 は別親への移行だけを当時の基準占有で制限します。
//
// 引数: s(*ResearchSleeve)、o(Observation)、campaign/side(int)。返り値: boolは受付可否です。
func (p *Portfolio) entryAllowed156(s *ResearchSleeve, o Observation, campaign, side int) bool {
	if p.Study156 == nil {
		return true
	}
	if s.Name == "core" && p.Study156.EntryRule > 0 && !p.entryMinuteAllowed156(o, campaign, side, s.Name) {
		return false
	}
	if !p.Study156.Gate {
		return true
	}
	ref, known := p.Study156.Reference[s.Name]
	allowed := known && ref.Time == o.Time && (!ref.Occupied || ref.Campaign == campaign)
	if !allowed {
		p.Study156.Rejected = append(p.Study156.Rejected, Rejection156{Owner: s.Name, Campaign: campaign, Index: o.Index, Time: o.Time, Reference: ref})
	}
	return allowed
}

// updateLot156 は全保有玉の当行のラージ返済側価格から、各玉の利益床を更新します。
//
// 引数: s(*ResearchSleeve)、o(Observation)。返り値: なし。
// 同HoldIDの分割約定は現在の平均建値へ更新しますが、一度上げた絶対停止価格は緩めません。
func (p *Portfolio) updateLot156(s *ResearchSleeve, o Observation) {
	state := p.Study156
	if state == nil || state.Width <= 0 || !quoteValid(o) {
		return
	}
	mark := liquidation(o, s.Side)
	d := float64(s.Side)
	for _, l := range s.Lots {
		if l.Quantity <= 0 {
			continue
		}
		g := state.Lots[l.ID]
		if g == nil {
			g = &LotGuard156{ID: l.ID, Owner: s.Name, Campaign: s.Campaign, Side: s.Side, Entry: l.Price, BestPrice: mark}
			state.Lots[l.ID] = g
		}
		g.Entry = l.Price
		if d*(mark-g.BestPrice) > 0 {
			g.BestPrice = mark
		}
		gain := d * (mark - g.Entry)
		active := gain > 0
		if state.Activation > 0 {
			active = gain >= state.Activation
		}
		if !g.Active && active {
			g.Active = true
			g.ActivatedAt = o.Time
			g.FloorPrice = g.Entry
		}
		if !g.Active {
			continue
		}
		floor := g.BestPrice - d*state.Width
		if d*(floor-g.Entry) < 0 {
			floor = g.Entry
		}
		if d*(floor-g.FloorPrice) > 0 {
			g.FloorPrice = floor
		}
	}
}

// applyLot156 は元退出の目標がない玉だけへ、建値以上の停止を追加します。
//
// 引数: s(*ResearchSleeve)、o(Observation)、fresh(bool)。返り値: なし。
// 部分返済を優先した場合も玉の床は保持し、返済約定後の残数へ次観測で再適用します。
func (p *Portfolio) applyLot156(s *ResearchSleeve, o Observation, fresh bool) {
	if p.Study156 == nil || p.Study156.Width <= 0 || !fresh || !quoteValid(o) || s.ForceReason != 0 {
		return
	}
	mark := liquidation(o, s.Side)
	for _, l := range s.Lots {
		g := p.Study156.Lots[l.ID]
		if l.Quantity <= 0 || g == nil || !g.Active || float64(s.Side)*(mark-g.FloorPrice) > 0 {
			continue
		}
		if goal, ok := s.Goals[l.ID]; ok && goal.Remaining < l.Quantity {
			continue
		}
		reason := 15601
		if math.Abs(g.FloorPrice-g.Entry) < 1e-8 {
			reason = 15602
		}
		s.setGoal(l.ID, 0, reason)
		if g.TriggeredAt == 0 {
			g.TriggeredAt = o.Time
		}
	}
}

// closing156 は成立済みの返済を同担当の追加新規より優先します。
//
// 引数: s(*ResearchSleeve)。返り値: boolは返済目標が実残数未満ならtrueです。
func closing156(s *ResearchSleeve) bool {
	if s.ForceReason != 0 && s.held() > 0 {
		return true
	}
	for _, l := range s.Lots {
		if goal, ok := s.Goals[l.ID]; ok && goal.Remaining < l.Quantity {
			return true
		}
	}
	return false
}

// diagnostics156 は親の予算へ利益が入る経路と各玉の独立した床を区別して表示します。
//
// 引数: s(*ResearchSleeve)、o(Observation)。返り値: map[string]anyは現在の状態だけです。
func (p *Portfolio) diagnostics156(s *ResearchSleeve, o Observation) map[string]any {
	lots := []map[string]any{}
	for _, l := range s.Lots {
		if g := p.Study156.Lots[l.ID]; g != nil {
			lots = append(lots, map[string]any{"guard": *g, "remaining": l.Quantity, "goal": s.Goals[l.ID]})
		}
	}
	return map[string]any{"entry_rule": p.Study156.EntryRule, "completed_minutes": append([]Minute156(nil), p.Study156.Minutes...), "width": p.Study156.Width, "activation": p.Study156.Activation, "gate": p.Study156.Gate, "reference": p.Study156.Reference[s.Name], "lots": lots, "parent_cash_yen": p.researchCash(s), "parent_budget_yen": s.Budget}
}
