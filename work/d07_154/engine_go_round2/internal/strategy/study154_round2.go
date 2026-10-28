package strategy

// ReferenceState154 は並行する未変更D07の当行処理後の占有だけを保存します。
// 将来の返済時計・損益・成績を含みません。
type ReferenceState154 struct {
	Campaign int     `json:"campaign"`
	Occupied bool    `json:"occupied"`
	At       float64 `json:"at"`
}

// ReferenceRejection154 は旧親占有のため受け付けなかった新親を当時情報で記録します。
type ReferenceRejection154 struct {
	Time      float64            `json:"time"`
	Index     int64              `json:"index"`
	Owner     string             `json:"owner"`
	Campaign  int                `json:"campaign"`
	Reference *ReferenceState154 `json:"reference"`
}

// SetReference154 は同じ原行まで進んだ独立基準D07の別入口担当を参照します。
//
// 引数: reference(*Portfolio)は未変更D07です。返り値: なし。
// 返済予約中も実玉がある間は占有とし、未約定新規も占有へ数えます。
func (p *Portfolio) SetReference154(reference *Portfolio) {
	p.Reference154 = nil
	if reference == nil || reference.Research == nil {
		return
	}
	s := reference.sleeve("episode")
	if s == nil {
		return
	}
	pending, _ := reference.pendingResearch("episode")
	p.Reference154 = &ReferenceState154{Campaign: s.Campaign, Occupied: s.held() > 0 || pending, At: reference.LastTime}
}

// referenceAllows154 は早期利確で空いた担当への別親採用だけを制限します。
//
// 引数: owner(string)、campaign(int)、o(Observation)。返り値: boolは新しい仮想親の受付許可です。
func (p *Portfolio) referenceAllows154(owner string, campaign int, o Observation) bool {
	id := p.Config.Study154
	if owner != "episode" || (id != "S01" && id != "S02" && id != "S03") {
		return true
	}
	allowed := p.Reference154 != nil && (!p.Reference154.Occupied || p.Reference154.Campaign == campaign)
	if !allowed {
		p.ReferenceRejected154 = append(p.ReferenceRejected154, ReferenceRejection154{Time: o.Time, Index: o.Index, Owner: owner, Campaign: campaign, Reference: p.Reference154})
	}
	return allowed
}

// guardFor154 は担当限定対照と元の全担当対照の利益起動倍率を区別します。
//
// 引数: s(*ResearchSleeve)。返り値: float64は起動R倍率、0は無効です。
func (p *Portfolio) guardFor154(s *ResearchSleeve) float64 {
	id := p.Config.Study154
	if id == "S03" {
		return 1
	}
	if s.Name == "episode" {
		if id == "S00" || id == "S01" {
			return .5
		}
		if id == "S04" || id == "S02" {
			return 1
		}
	}
	return p.guard154()
}

// chooseJab154 は初回の採用時点に限り、既存の早い玉の順行を測って枚数方式を固定します。
//
// 引数: s(*ResearchSleeve)、o(Observation)、side(int)。返り値: intは0で元5枚、2で1枚固定、3で段階追加です。
// 別入口玉の数量加重建値と返済側気配を比較し、同担当の初回固定R以上の場合だけ変更します。
func (p *Portfolio) chooseJab154(s *ResearchSleeve, o Observation, side int) int {
	id := p.Config.Study154
	if p.Session.Kind != "Day" || s.Name != "core" || (id != "J01" && id != "J02" && id != "J03") || !quoteValid(o) {
		return 0
	}
	episode := p.sleeve("episode")
	if episode == nil || episode.Side != side || episode.held() == 0 || episode.FixedR <= 0 || !finite(episode.FixedR) {
		return 0
	}
	total, value := 0, 0.
	for _, lot := range episode.Lots {
		total += lot.Quantity
		value += float64(lot.Quantity) * lot.Price
	}
	width := float64(side) * (liquidation(o, side) - value/float64(total))
	if width < episode.FixedR {
		return 0
	}
	if id == "J01" {
		return 2
	}
	return 3
}
