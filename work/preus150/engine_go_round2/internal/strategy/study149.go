package strategy

// studyQuiet149 は研究だけの境界時刻を既存静観判定へ渡します。
//
// 引数: session(Session)、at/before/after(float64)は当時時計と静観秒幅です。
// 返り値: boolは静観中。明示指定がなければコピー元と同じ条件です。
func studyQuiet149(session Session, at, before, after float64) bool {
	if session.StudyQuietOverride {
		before, after = session.StudyQuietBefore, session.StudyQuietAfter
	}
	return at >= session.USOpen-before && at < session.USOpen+after
}

// StudyConfigure149 は生成済みの担当の時計制約だけを変更します。
//
// 引数: coreAt/extraAt(float64)は最早準備開始、owners([]string)は採用担当です。
// 返り値: なし。数量・価格条件・利確/損切りの幅は変更しません。
func (p *Portfolio) StudyConfigure149(coreAt, extraAt float64, owners []string) {
	selected := map[string]bool{}
	for _, name := range owners {
		selected[name] = true
	}
	out := []*ResearchSleeve{}
	for _, sleeve := range p.Research.Sleeves {
		if len(selected) > 0 && !selected[sleeve.Name] {
			continue
		}
		if source := sleeve.Source; source.Legacy != nil {
			if coreAt > 0 {
				source.Legacy.Config.Parameters.Night.PostOpenPrepareSeconds = coreAt - p.Session.USOpen
			}
			if extraAt > 0 {
				source.Session.ExtraAt = extraAt
				source.Session.StudyEarlyFallback = extraAt < p.Session.USOpen+1800
				source.Supplement.Session.ExtraAt = extraAt
			}
		}
		out = append(out, sleeve)
	}
	p.Research.Sleeves = out
}
