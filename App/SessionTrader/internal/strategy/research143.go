package strategy

import (
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"sort"
)

// ResearchLot は実約定の建玉ID単位の残高です。仮想源の玉とは分離します。
type ResearchLot struct {
	ID, EntryID      string
	Ticket, Quantity int
	Price, At        float64
}

// ResearchGoal は未約定取消後も維持する個別玉の返済目標です。
type ResearchGoal struct {
	Remaining, Reason int
	Priority          int
}

// ResearchSleeve は独立枠の候補生成、採否、実約定、利益予算を保存します。
type ResearchSleeve struct {
	Name                                                 string
	Capacity                                             int
	Source                                               *ResearchSource
	Campaign, Side                                       int
	Accepted                                             map[int]bool
	Virtual                                              map[int]int
	Requested, Opened, CloseReason                       map[int]int
	Lots                                                 []ResearchLot
	Goals                                                map[string]ResearchGoal
	Cash, Fees, FixedR, FixedMA, FailureSince, LastValid float64
	MAKnown, Blocked                                     bool
	Stage                                                int
	Retained                                             string
	Budget, Best                                         float64
	ForceReason                                          int
	GoalSequence                                         int
}

// ResearchPortfolio は00143の固定配分と実建玉管理です。
type ResearchPortfolio struct {
	Version int
	Method  string
	Sleeves []*ResearchSleeve
}

// ResearchAllocation は固定比率を最大剰余法で整数化します。
//
// 引数: method(string) はTG04/PG04、cap(int)は同時枚数上限です。
// 返り値: map[string]int は枠別上限です。同率は基本・追加・別入口の順に配分します。
func ResearchAllocation(method string, cap int) map[string]int {
	weights := []int{5, 3, 2}
	names := []string{"core", "addon", "episode"}
	if method == "PG04" {
		weights, names = []int{5, 5}, []string{"core", "episode"}
	}
	result := map[string]int{}
	used := 0
	for i, n := range names {
		result[n] = (cap/10)*weights[i] + (cap%10)*weights[i]/10
		used += result[n]
	}
	order := make([]int, len(names))
	for i := range order {
		order[i] = i
	}
	sort.SliceStable(order, func(i, j int) bool { return (cap%10)*weights[order[i]]%10 > (cap%10)*weights[order[j]]%10 })
	for i := 0; i < cap-used; i++ {
		result[names[order[i]]]++
	}
	return result
}

// researchFee はユーザー提示の標準片道手数料を返します。
//
// 引数: product(string)は売買商品です。返り値: float64は1枚当たり円です。
func researchFee(product string) float64 {
	switch product {
	case "NK225":
		return 275
	case "NK225mini":
		return 38.5
	case "NK225micro":
		return 11
	}
	return 0
}

// newResearchPortfolio はTG04/PG04の独立仮想源を作ります。
//
// 引数: cfg(Config)、session(Session)。返り値: *ResearchPortfolioと設定不正のerrorです。
func newResearchPortfolio(cfg Config, session Session) (*ResearchPortfolio, error) {
	if cfg.Reference != "NK225" || (cfg.Parameters.Method != "TG04" && cfg.Parameters.Method != "PG04") || researchFee(cfg.Product) == 0 {
		return nil, errors.New("TG04/PG04は日経先物・mini・micro専用です")
	}
	r := &ResearchPortfolio{Version: 1, Method: cfg.Parameters.Method}
	allocation := ResearchAllocation(r.Method, cfg.Cap)
	for _, name := range []string{"core", "addon", "episode"} {
		cap := allocation[name]
		if cap == 0 {
			continue
		}
		source, err := newResearchSource(cfg, session, name, cap)
		if err != nil {
			return nil, err
		}
		r.Sleeves = append(r.Sleeves, &ResearchSleeve{Name: name, Capacity: cap, Source: source, Campaign: -1, Accepted: map[int]bool{}, Virtual: map[int]int{}, Requested: map[int]int{}, Opened: map[int]int{}, CloseReason: map[int]int{}, Goals: map[string]ResearchGoal{}, FailureSince: -1})
	}
	return r, nil
}

// sleeve は役割名で独立枠を参照します。
//
// 引数: name(string)。返り値: *ResearchSleeve、未知ならnilです。
func (p *Portfolio) sleeve(name string) *ResearchSleeve {
	for _, s := range p.Research.Sleeves {
		if s.Name == name {
			return s
		}
	}
	return nil
}

// held は実保有枚数だけを数えます。
//
// 引数: なし。返り値: intは当該枠の実玉合計です。
func (s *ResearchSleeve) held() int {
	n := 0
	for _, l := range s.Lots {
		n += l.Quantity
	}
	return n
}

// pendingResearch は未確定注文の存在と新規残予約を返します。
//
// 引数: owner(string)。返り値: boolは未確定の存在、intは未約定新規枚数です。
func (p *Portfolio) pendingResearch(owner string) (bool, int) {
	found, n := false, 0
	for _, v := range p.Orders {
		if v.Done || v.Signal.Owner != owner {
			continue
		}
		found = true
		if v.Signal.Action == "new" {
			n += v.Signal.Quantity - v.Filled
		}
	}
	return found, n
}

// researchGate は当時の120秒逆流を初回通知へ適用します。
//
// 引数: o(Observation)、side(int)、r(float64)。返り値: boolは採用可能です。
func (p *Portfolio) researchGate(o Observation, side int, r float64) bool {
	f := o.Research
	own := f.Known[13] && f.Known[9] && f.Values[9] > 0
	if p.Session.Kind == "Day" {
		return !own || float64(side)*f.Values[13]*f.Values[9]/r >= -.25
	}
	peer := f.Known[21] && f.Known[22] && o.Time-f.Values[22] >= 0 && o.Time-f.Values[22] <= 15
	return !(own && peer && float64(side)*f.Values[13] < 0 && float64(side)*f.Values[21] < 0)
}

// emitResearch は建玉IDを特定した依頼を予約し、実約定は増やしません。
//
// 引数: s(*ResearchSleeve)、o(Observation)、e(ResearchEvent)、targets([]LotTarget)。
// 返り値: Signalは保存済み依頼です。
func (p *Portfolio) emitResearch(s *ResearchSleeve, o Observation, e ResearchEvent, targets []LotTarget) Signal {
	p.Sequence++
	id := fmt.Sprintf("%s-%s-%s-%06d", p.Session.ID, p.Config.Product, s.Name, p.Sequence)
	if p.Config.Namespace != "" {
		id = p.Config.Namespace + "-" + id
	}
	evidence, _ := json.Marshal(map[string]any{"method": p.Research.Method, "owner": s.Name, "observation": o, "campaign": s.Campaign, "fixed_r": s.FixedR, "fixed_ma20": s.FixedMA, "ma_known": s.MAKnown, "realized_net": s.Cash, "residual_stage": s.Stage, "profit_budget": s.Budget, "retained_hold_id": s.Retained})
	sig := Signal{ID: id, Owner: s.Name, Action: e.Action, Side: e.Side, Quantity: e.Quantity, Time: o.Time, SourceIndex: o.Index, Reason: researchReason(p.Session.Kind, e.Action, e.Reason), ReasonCode: e.Reason, Risk: e.Risk, Boundary: e.Boundary, Campaign: s.Campaign, Ticket: e.Ticket, Targets: targets, Evidence: evidence}
	p.Orders[id] = &orderState{Signal: sig}
	return sig
}

// researchReason は研究理由コードを運転ログへ変換します。
//
// 引数: kind/action(string)、reason(int)。返り値: stringは短い日本語の理由です。
func researchReason(kind, action string, reason int) string {
	names := map[int]string{1431: "帯外突破の失敗後に回復", 1433: "帯端から反発", 1434: "利益保護後の追加", 1435: "帯中心で部分利確", 1436: "固定支持または初回極値の破綻", 1437: "帯幅で利益追尾", 14312: "入口固定平均と20分・120秒方向の破綻", 14380: "残り1枚の広い利益追尾", 14381: "実現利益の損失予算に到達", 14382: "残玉の実現利益不足"}
	if name, ok := names[reason]; ok {
		return name
	}
	return reasonText(kind, action, reason)
}

// setGoal は未約定返済を含め、目標残数を縮める方向だけに更新します。
//
// 引数: id(string)、remaining/reason(int)。返り値: なし。
func (s *ResearchSleeve) setGoal(id string, remaining, reason int) {
	old, ok := s.Goals[id]
	if !ok || remaining < old.Remaining {
		s.GoalSequence++
		s.Goals[id] = ResearchGoal{remaining, reason, s.GoalSequence}
	}
}

// closeAllResearch は未返済玉を全て返済待ちへ移します。
//
// 引数: s(*ResearchSleeve)、reason(int)。返り値: なし。
func closeAllResearch(s *ResearchSleeve, reason int) {
	s.Blocked = true
	s.ForceReason = reason
	for _, l := range s.Lots {
		if l.Quantity > 0 {
			s.setGoal(l.ID, 0, reason)
		}
	}
}

// flushResearchGoals は担当の注文終了後に残った返済だけを再依頼します。
//
// 引数: s(*ResearchSleeve)、o(Observation)。返り値: []SignalはUID別の返済です。
func (p *Portfolio) flushResearchGoals(s *ResearchSleeve, o Observation) []Signal {
	if pending, _ := p.pendingResearch(s.Name); pending {
		return nil
	}
	var out []Signal
	type group struct {
		ticket, reason, quantity, priority int
		targets                            []LotTarget
	}
	groups := []group{}
	for _, l := range s.Lots {
		g, ok := s.Goals[l.ID]
		if !ok || l.Quantity <= g.Remaining {
			continue
		}
		q := l.Quantity - g.Remaining
		found := -1
		for i, v := range groups {
			if v.ticket == l.Ticket && v.reason == g.Reason {
				found = i
				break
			}
		}
		if found < 0 {
			groups = append(groups, group{ticket: l.Ticket, reason: g.Reason, priority: g.Priority})
			found = len(groups) - 1
		}
		groups[found].quantity += q
		groups[found].targets = append(groups[found].targets, LotTarget{l.ID, q})
	}
	sort.SliceStable(groups, func(i, j int) bool { return groups[i].priority < groups[j].priority })
	for _, g := range groups {
		out = append(out, p.emitResearch(s, o, ResearchEvent{Action: "close", Side: -s.Side, Quantity: g.quantity, Reason: g.reason, Campaign: s.Campaign, Ticket: g.ticket, Risk: s.FixedR}, g.targets))
	}
	return out
}

// retainResearch は全返済通知から最古の利益玉1枚を選び、他玉見込益だけで資格を判定します。
//
// 引数: s(*ResearchSleeve)、o(Observation)、events([]ResearchEvent)。返り値: boolは残玉化の成立です。
func (p *Portfolio) retainResearch(s *ResearchSleeve, o Observation, events []ResearchEvent) bool {
	if s.Name == "addon" || s.Stage != 0 || s.Blocked || s.held() == 0 || !quoteValid(o) || o.Time >= p.Session.ForceClose || p.researchQuiet(o.Time) {
		return false
	}
	if pending, _ := p.pendingResearch(s.Name); pending {
		return false
	}
	n, virtual := 0, 0
	for _, q := range s.Virtual {
		virtual += q
	}
	for _, e := range events {
		if e.Campaign != s.Campaign {
			continue
		}
		if e.Action == "new" || (e.Reason != 2 && e.Reason != 70 && e.Reason != 1437) {
			return false
		}
		n += e.Quantity
	}
	if n == 0 || n != virtual {
		return false
	}
	mark := liquidation(o, s.Side)
	fee := researchFee(p.Config.Product)
	candidate := -1
	for i, l := range s.Lots {
		if l.Quantity > 0 && float64(s.Side)*(mark-l.Price)*p.Config.PointValue > math.Floor(fee) && (candidate < 0 || l.At < s.Lots[candidate].At) {
			candidate = i
		}
	}
	if candidate < 0 {
		return false
	}
	estimate := s.Cash
	// 元UIDごとの返済注文を維持し、その注文ごとに端数を切り捨てます。
	for _, e := range events {
		if e.Campaign != s.Campaign {
			continue
		}
		q := 0
		for i, l := range s.Lots {
			if l.Ticket != e.Ticket || l.Quantity == 0 {
				continue
			}
			amount := l.Quantity
			if i == candidate {
				amount--
			}
			estimate += float64(s.Side) * (mark - l.Price) * float64(amount) * p.Config.PointValue
			q += amount
		}
		estimate -= math.Floor(float64(q) * fee)
	}
	if estimate <= 0 {
		return false
	}
	s.Stage = 1
	s.Retained = s.Lots[candidate].ID
	s.ForceReason = 0
	for _, e := range events {
		if e.Campaign != s.Campaign {
			continue
		}
		for i, l := range s.Lots {
			if l.Quantity > 0 && l.Ticket == e.Ticket {
				remain := 0
				if i == candidate {
					remain = 1
				}
				s.setGoal(l.ID, remain, e.Reason)
			}
		}
	}
	return true
}

// researchQuiet は残玉専用の米国寄付前後15分を判定します。
//
// 引数: at(float64)。返り値: boolは静観時間内です。
func (p *Portfolio) researchQuiet(at float64) bool {
	return p.Session.USOpen > 0 && at >= p.Session.USOpen-900 && at < p.Session.USOpen+900
}

// researchManage は固定入口の反証と確定利益予算を、現在観測だけで管理します。
//
// 引数: s(*ResearchSleeve)、o(Observation)。返り値: なし。返済要求を保持します。
func (p *Portfolio) researchManage(s *ResearchSleeve, o Observation) {
	if o.Time >= p.Session.ForceClose {
		closeAllResearch(s, 93)
	}
	if s.Stage > 0 && p.researchQuiet(o.Time) {
		closeAllResearch(s, 94)
	}
	pending, _ := p.pendingResearch(s.Name)
	if s.ForceReason != 0 {
		for _, l := range s.Lots {
			if l.Quantity > 0 {
				s.setGoal(l.ID, 0, s.ForceReason)
			}
		}
	}
	if s.held() == 0 {
		return
	}
	if s.Stage == 1 && !pending && s.held() == 1 && quoteValid(o) {
		// 他玉が実約定し、注文終了した後だけ予算を確定します。
		s.Budget = math.Max(0, s.Cash)
		s.Stage = 2
		for _, l := range s.Lots {
			if l.ID == s.Retained {
				s.Best = float64(s.Side) * (liquidation(o, s.Side) - l.Price)
			}
		}
		if s.Cash <= 0 {
			closeAllResearch(s, 14382)
		}
	}
	if s.Stage == 2 && !pending && quoteValid(o) {
		for _, l := range s.Lots {
			if l.ID != s.Retained || l.Quantity != 1 {
				continue
			}
			gain := float64(s.Side) * (liquidation(o, s.Side) - l.Price)
			s.Best = math.Max(s.Best, gain)
			floor := (math.Floor(researchFee(p.Config.Product)) - s.Budget) / p.Config.PointValue
			trail := s.Best - 3*s.FixedR
			if gain <= math.Max(floor, trail) {
				reason := 14380
				if floor >= trail {
					reason = 14381
				}
				closeAllResearch(s, reason)
			}
		}
	}
	if s.Name != "core" || p.Session.Kind != "Day" || s.Blocked || s.Stage > 0 {
		return
	}
	f := o.Research
	adverse := quoteValid(o) && s.MAKnown && f.Known[10] && f.Known[13] && f.Known[9] && f.Values[9] > 0 && f.Known[28] && float64(s.Side)*f.Values[13] < 0 && float64(s.Side)*f.Values[28] < 0 && float64(s.Side)*(f.Values[10]-s.FixedMA) <= -.1*s.FixedR
	if !quoteValid(o) || (s.LastValid > 0 && o.Time-s.LastValid > 15) {
		s.FailureSince = -1
	}
	if adverse {
		if s.FailureSince < 0 {
			s.FailureSince = o.Time
		}
		if o.Time-s.FailureSince >= 15 {
			closeAllResearch(s, 14312)
		}
	} else {
		s.FailureSince = -1
	}
	if quoteValid(o) {
		s.LastValid = o.Time
	}
}

// nativeResearch は当時の源通知を受け、親単位の採否を確定します。
//
// 引数: s(*ResearchSleeve)、o(Observation)、events([]ResearchEvent)、allow/emit(bool)。
// 返り値: []Signalは新規予約です。返済は個別玉目標として残します。
func (p *Portfolio) nativeResearch(s *ResearchSleeve, o Observation, events []ResearchEvent, allow, emit bool) []Signal {
	var out []Signal
	retained := p.retainResearch(s, o, events)
	for _, e := range events {
		accepted, known := s.Accepted[e.Campaign]
		if e.Action == "new" && !known {
			pending, _ := p.pendingResearch(s.Name)
			r := math.Max(8*p.Config.LargeTick, o.ATR)
			accepted = allow && emit && !pending && s.held() == 0 && o.Time < p.Session.ForceClose
			if accepted && s.Name == "core" {
				accepted = p.researchGate(o, e.Side, r)
			}
			s.Accepted[e.Campaign] = accepted
			if accepted {
				s.Campaign = e.Campaign
				s.Side = e.Side
				s.Virtual = map[int]int{}
				s.Requested = map[int]int{}
				s.Opened = map[int]int{}
				s.CloseReason = map[int]int{}
				s.Lots = nil
				s.Goals = map[string]ResearchGoal{}
				s.Cash = 0
				s.Fees = 0
				s.FixedR = r
				s.FixedMA = o.Research.MA20
				s.MAKnown = o.Research.MA20Known
				s.FailureSince = -1
				s.LastValid = 0
				s.Blocked = false
				s.Stage = 0
				s.Retained = ""
				s.Budget = 0
				s.Best = 0
				s.ForceReason = 0
			}
		}
		if !accepted || e.Campaign != s.Campaign {
			continue
		}
		before := s.Virtual[e.Ticket]
		if e.Action == "new" {
			s.Virtual[e.Ticket] += e.Quantity
			s.Requested[e.Ticket] += e.Quantity
			if !allow || !emit || s.Blocked || s.Stage > 0 {
				continue
			}
			_, reserved := p.pendingResearch(s.Name)
			q := min(e.Quantity, s.Capacity-s.held()-reserved)
			// 独立枠の和が上限以内なので、枠の貸借も逆方向の相殺も不要です。
			if q > 0 {
				e.Quantity = q
				out = append(out, p.emitResearch(s, o, e, nil))
			}
		} else {
			s.Virtual[e.Ticket] = max(0, before-e.Quantity)
			s.CloseReason[e.Ticket] = e.Reason
			if retained || s.Stage > 0 {
				continue
			}
			actual := 0
			for _, l := range s.Lots {
				if l.Ticket == e.Ticket {
					actual += l.Quantity
				}
			}
			q := actual
			if before > e.Quantity && before > 0 {
				q = int(math.Floor(float64(actual*e.Quantity)/float64(before) + .5))
			}
			for _, l := range s.Lots {
				if l.Ticket != e.Ticket || q <= 0 {
					continue
				}
				close := min(q, l.Quantity)
				s.setGoal(l.ID, l.Quantity-close, e.Reason)
				q -= close
			}
		}
	}
	return out
}

// observeResearch は候補生成と実玉の管理を独立して進めます。
//
// 引数: o(Observation)、allow/emit(bool)。返り値: []Signalと源の不整合errorです。
func (p *Portfolio) observeResearch(o Observation, allow, emit bool) ([]Signal, error) {
	var out []Signal
	for _, s := range p.Research.Sleeves {
		events, err := s.Source.Step(o)
		if err != nil {
			return nil, err
		}
		out = append(out, p.nativeResearch(s, o, events, allow, emit)...)
		p.researchManage(s, o)
		if emit {
			out = append(out, p.flushResearchGoals(s, o)...)
		}
	}
	return out, nil
}

// fillResearch は個別玉と確定利益を実約定のみから更新します。
//
// 引数: f(Fill)、order(*orderState)。返り値: errorは建玉所有・数量・対象の矛盾です。
func (p *Portfolio) fillResearch(f Fill, order *orderState) error {
	e := order.Signal
	s := p.sleeve(e.Owner)
	if s == nil || s.Campaign != e.Campaign {
		return errors.New("約定の担当又は親が現存状態と異なります")
	}
	if e.Action == "new" {
		id := f.HoldID
		if id == "" {
			id = f.ExecutionID
		}
		for _, l := range s.Lots {
			if l.ID == id {
				return errors.New("建玉IDを重複して追加できません")
			}
		}
		if s.held()+f.Quantity > s.Capacity {
			return errors.New("実約定が担当枚数上限を超えました")
		}
		s.Lots = append(s.Lots, ResearchLot{ID: id, EntryID: e.ID, Ticket: e.Ticket, Quantity: f.Quantity, Price: f.Price, At: f.Time})
		s.Opened[e.Ticket] += f.Quantity
		if s.Blocked {
			s.setGoal(id, 0, s.ForceReason)
		} else if reason, closed := s.CloseReason[e.Ticket]; closed && s.Requested[e.Ticket] > 0 {
			// 新規が部分約定中に到着した返済通知を、遅れて約定した玉にも適用します。
			target := int(math.Floor(float64(s.Opened[e.Ticket]*s.Virtual[e.Ticket])/float64(s.Requested[e.Ticket]) + .5))
			count := 0
			for _, l := range s.Lots {
				if l.Ticket == e.Ticket {
					count += l.Quantity
				}
			}
			remaining := max(0, count-target)
			for _, l := range s.Lots {
				if l.Ticket == e.Ticket && remaining > 0 {
					q := min(l.Quantity, remaining)
					s.setGoal(l.ID, l.Quantity-q, reason)
					remaining -= q
				}
			}
		}
	} else {
		targets := f.Closed
		if len(targets) == 0 {
			// 人工試験では指定順、実稼働は確認済み返済内訳を必ず使用します。
			remaining := f.Quantity
			for _, target := range e.Targets {
				for _, l := range s.Lots {
					if l.ID != target.ID {
						continue
					}
					q := min(remaining, min(target.Quantity-order.CloseConsumed[target.ID], l.Quantity))
					if q > 0 {
						targets = append(targets, LotTarget{l.ID, q})
						remaining -= q
					}
				}
			}
		}
		quantity := 0
		used := map[string]int{}
		for _, target := range targets {
			limit := 0
			for _, allowed := range e.Targets {
				if target.ID == allowed.ID {
					limit += allowed.Quantity
				}
			}
			used[target.ID] += target.Quantity
			if target.Quantity <= 0 || used[target.ID]+order.CloseConsumed[target.ID] > limit {
				return errors.New("指定外の建玉又は枚数が返済約定へ含まれます")
			}
			found := false
			for _, l := range s.Lots {
				if l.ID == target.ID && l.Quantity >= used[target.ID] {
					found = true
				}
			}
			if !found {
				return errors.New("返済約定に対応する所有玉が不足しています")
			}
			quantity += target.Quantity
		}
		if quantity != f.Quantity {
			return errors.New("返済の建玉内訳と約定数量が異なります")
		}
		for _, target := range targets {
			if order.CloseConsumed == nil {
				order.CloseConsumed = map[string]int{}
			}
			order.CloseConsumed[target.ID] += target.Quantity
			for i := range s.Lots {
				l := &s.Lots[i]
				if l.ID == target.ID {
					s.Cash += float64(s.Side) * (f.Price - l.Price) * float64(target.Quantity) * p.Config.PointValue
					l.Quantity -= target.Quantity
				}
			}
		}
	}
	s.Cash -= f.Fee
	s.Fees += f.Fee
	order.Filled += f.Quantity
	p.Executions[f.ExecutionID] = f
	if e.Action == "new" {
		if e.Owner == "core" {
			p.CoreEntered = true
		} else {
			p.ExtraAttempted = true
		}
	}
	return nil
}

// flattenResearch は価格受信停止時も全担当又は指定担当の返済を維持します。
//
// 引数: owner(string)、at(float64)、reason(string)。返り値: []Signalは現在送れる依頼です。
func (p *Portfolio) flattenResearch(owner string, at float64, reason string) []Signal {
	o := Observation{Reference: p.Config.Reference, Time: at, Index: p.LastIndex}
	var out []Signal
	for _, s := range p.Research.Sleeves {
		if owner != "" && owner != s.Name {
			continue
		}
		closeAllResearch(s, 93)
		out = append(out, p.flushResearchGoals(s, o)...)
	}
	for i := range out {
		out[i].Reason = reason
		p.Orders[out[i].ID].Signal = out[i]
	}
	return out
}

// researchStatus は担当別実残と未確定依頼だけを表示へ渡します。
//
// 引数: なし。返り値: Statusは仮想源の建玉を含みません。
func (p *Portfolio) researchStatus() Status {
	out := Status{CoreEntered: p.CoreEntered, ExtraAttempted: p.ExtraAttempted}
	for _, s := range p.Research.Sleeves {
		pos := Position{Owner: s.Name, Side: s.Side, Quantity: s.held(), Risk: s.FixedR, Campaign: s.Campaign, Realized: s.Cash + s.Fees, Fees: s.Fees}
		for _, l := range s.Lots {
			pos.Average += l.Price * float64(l.Quantity)
		}
		if pos.Quantity > 0 {
			pos.Average /= float64(pos.Quantity)
		} else {
			pos.Side = 0
		}
		out.Positions = append(out.Positions, pos)
	}
	for _, v := range p.Orders {
		if !v.Done {
			out.Pending = append(out.Pending, v.Signal)
		}
	}
	sort.Slice(out.Pending, func(i, j int) bool { return out.Pending[i].ID < out.Pending[j].ID })
	return out
}

// restoreResearch は担当数・配分・建玉IDと仮想源の復元を検査します。
//
// 引数: なし。返り値: errorは破損又は設定不一致です。
func (p *Portfolio) restoreResearch() error {
	r := p.Research
	if r.Version != 1 || r.Method != p.Config.Parameters.Method {
		return errors.New("研究戦略の保存版又は手法が不正です")
	}
	want := ResearchAllocation(r.Method, p.Config.Cap)
	seen := map[string]bool{}
	ids := map[string]bool{}
	for _, s := range r.Sleeves {
		if s == nil || seen[s.Name] || s.Capacity <= 0 || s.Capacity != want[s.Name] || s.Source == nil || s.Accepted == nil || s.Virtual == nil || s.Goals == nil || s.Requested == nil || s.Opened == nil || s.CloseReason == nil {
			return errors.New("研究戦略の配分又は保存状態が不正です")
		}
		seen[s.Name] = true
		if err := s.Source.Restore(); err != nil {
			return err
		}
		if s.held() > s.Capacity {
			return errors.New("研究戦略の保存残高が枠を超えています")
		}
		for _, l := range s.Lots {
			if l.ID == "" || ids[l.ID] || l.Quantity < 0 || !finite(l.Price) || l.Price <= 0 {
				return errors.New("研究戦略の個別玉が不正です")
			}
			ids[l.ID] = true
		}
	}
	for name, cap := range want {
		if cap > 0 && !seen[name] {
			return errors.New("研究戦略の担当が欠落しています")
		}
	}
	return nil
}
