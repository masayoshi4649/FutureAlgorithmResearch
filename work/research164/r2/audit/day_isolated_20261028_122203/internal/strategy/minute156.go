package strategy

import "math"

type Minute156 struct {
	Slot       int
	End, Close float64
}
type EntryRejection156 struct {
	Rule, Campaign, Side int
	Owner                string
	Time                 float64
	Index                int64
	Unknown              bool
	Minutes              []Minute156
}

// updateMinutes156 は原Lastの当分最終観測を保持し、次分へ到達して初めて前分を確定します。
//
// 引数: o(Observation)。返り値: なし。空白の分を補間せず、当分末の未来値も使いません。
func (p *Portfolio) updateMinutes156(o Observation) {
	s := p.Study156
	if s == nil || s.EntryRule == 0 || !finite(o.Last) || o.Last <= 0 {
		return
	}
	slot := int(math.Floor((o.Time - p.Session.Start) / 60))
	if s.MinuteSeen && slot > s.MinuteSlot {
		s.Minutes = append(s.Minutes, Minute156{Slot: s.MinuteSlot, End: p.Session.Start + float64(s.MinuteSlot+1)*60, Close: s.MinuteLast})
		if len(s.Minutes) > 6 {
			s.Minutes = s.Minutes[len(s.Minutes)-6:]
		}
	}
	s.MinuteSeen = true
	s.MinuteSlot = slot
	s.MinuteLast = o.Last
}

// entryMinuteAllowed156 はcore初回親の入口だけを過去の連続確定足で検査します。
//
// 引数: o(Observation)、campaign/side(int)、owner(string)。返り値: boolは入口受付です。
// E1/E2は連続3終値、E3は連続6終値が必須。最新確定分が現在の直前分でない場合も未知です。
func (p *Portfolio) entryMinuteAllowed156(o Observation, campaign, side int, owner string) bool {
	s := p.Study156
	need := 3
	if s.EntryRule == 3 {
		need = 6
	}
	known := len(s.Minutes) >= need
	var rows []Minute156
	if known {
		rows = s.Minutes[len(s.Minutes)-need:]
		for i, r := range rows {
			if r.End > o.Time || (i > 0 && r.Slot != rows[i-1].Slot+1) {
				known = false
			}
		}
		known = known && rows[len(rows)-1].Slot == s.MinuteSlot-1
	}
	allowed := false
	if known {
		n := len(rows)
		d := float64(side)
		two := d * (rows[n-1].Close - rows[n-3].Close)
		switch s.EntryRule {
		case 1:
			allowed = two > 0
		case 2:
			allowed = d*(rows[n-1].Close-rows[n-2].Close) > 0 && d*(rows[n-2].Close-rows[n-3].Close) > 0
		case 3:
			prior := d * (rows[n-3].Close - rows[n-6].Close)
			allowed = !(prior >= 60 && two <= 20)
		}
	}
	if !allowed {
		s.EntryRejected = append(s.EntryRejected, EntryRejection156{Rule: s.EntryRule, Campaign: campaign, Side: side, Owner: owner, Time: o.Time, Index: o.Index, Unknown: !known, Minutes: append([]Minute156(nil), rows...)})
	}
	return allowed
}
