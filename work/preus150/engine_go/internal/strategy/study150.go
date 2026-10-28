package strategy

import (
	"errors"
	"fmt"
)

// StudyRuleOverrides150 は前半専用の式を複製し、鮮度や正常板の条件を変更対象から除きます。
//
// 引数: base/overrides(map[string]string)は元のD07式と事前固定の差分です。
// 返り値: map[string]stringは独立した式、errorは対象外又は空式です。
func StudyRuleOverrides150(base, overrides map[string]string) (map[string]string, error) {
	allowed := map[string]bool{
		"addon.entry.mode": true, "addon.entry.confirmed": true,
		"addon.entry.rebound": true, "addon.entry.range_rebound": true,
		"addon.entry.range_side": true, "addon.reentry_ready": true,
		"addon.add_trigger": true, "addon.trail_width": true,
	}
	result := make(map[string]string, len(base))
	for name, expression := range base {
		result[name] = expression
	}
	for name, expression := range overrides {
		if !allowed[name] || expression == "" {
			return nil, fmt.Errorf("研究150の変更対象外又は空の式: %s", name)
		}
		if _, ok := base[name]; !ok {
			return nil, fmt.Errorf("研究150の元式がありません: %s", name)
		}
		result[name] = expression
	}
	return result, nil
}

// StudyConfigure150 は前半D07の主担当入口と追加初回枚数だけを変更します。
//
// 引数: core(map[string]float64)は主担当入口の差分、initial(int)は追加初回枚数で0なら維持です。
// 返り値: errorは未知名・範囲外・対象外の手法です。共通指標、episode、後半状態は変更しません。
func (p *Portfolio) StudyConfigure150(core map[string]float64, initial int) error {
	if p.Research == nil || p.Research.Method != "D07" || p.Session.Kind != "Night" {
		return errors.New("研究150の対象はD07夜間だけです")
	}
	if initial < 0 || initial > 3 {
		return errors.New("追加初回枚数は0（維持）又は1〜3枚です")
	}
	for _, sleeve := range p.Research.Sleeves {
		source := sleeve.Source
		if sleeve.Name == "core" && source.Legacy != nil {
			n := source.Legacy.Config.Parameters.Night
			for name, value := range core {
				if !finite(value) || value <= 0 {
					return fmt.Errorf("前半入口の数値が不正: %s", name)
				}
				switch name {
				case "efficiency":
					if value > 1 {
						return errors.New("方向効率は1以下です")
					}
					n.Efficiency = value
				case "confirm_seconds":
					n.ConfirmSeconds = value
				case "retest_progress_r":
					n.RetestProgressR = value
				case "retest_return_r":
					n.RetestReturnR = value
				case "bounce_r":
					n.BounceR = value
				default:
					return fmt.Errorf("主担当入口の未知設定: %s", name)
				}
			}
			if n.RetestReturnR >= n.RetestProgressR {
				return errors.New("戻り幅は突破後の進行幅より小さくします")
			}
			source.Legacy.Config.Parameters.Night = n
		}
		if sleeve.Name == "addon" && initial > 0 {
			if source.Active145 == nil || initial > sleeve.Capacity {
				return errors.New("追加初回枚数が担当上限を超えます")
			}
			source.Active145.Initial = initial
		}
	}
	return nil
}

// StudyEntryState150 は入口準備の変化を数えるための小さい読取状態です。
type StudyEntryState150 struct {
	Owner         string
	Arm, Stage    int
	ArmTime       float64
	SinceKnown    bool
	PendingIndex  int64
	NewCandidates int
}

// StudyEntryState150 は売買状態を変えず、各担当の入口準備と現在の新規候補を取り出します。
//
// 引数: なし。返り値: [3]StudyEntryState150は担当別の読み取り専用コピーです。原行ごとのマップ確保は行いません。
func (p *Portfolio) StudyEntryState150() [3]StudyEntryState150 {
	var result [3]StudyEntryState150
	for index, sleeve := range p.Research.Sleeves {
		source := sleeve.Source
		v := StudyEntryState150{Owner: sleeve.Name, PendingIndex: -1}
		if source.Legacy != nil {
			a := source.Legacy.Core.Arm
			v.Arm, v.Stage, v.ArmTime = a.Side, a.Stage, a.At
			for _, signal := range source.PendingLegacy {
				if signal.Action == "new" && signal.SourceIndex >= v.PendingIndex {
					if signal.SourceIndex != v.PendingIndex {
						v.NewCandidates = 0
					}
					v.PendingIndex = signal.SourceIndex
					v.NewCandidates++
				}
			}
		} else {
			active := source.Active
			if source.Active145 != nil {
				active = &source.Active145.ResearchActive
			}
			if active != nil {
				v.Arm, v.Stage, v.ArmTime = active.Arm, active.Stage, active.ArmTime
				v.SinceKnown = active.SinceKnown
				v.PendingIndex = active.Book.PendingIndex
				for _, event := range active.Book.Pending {
					if event.Action == "new" {
						v.NewCandidates++
					}
				}
			}
		}
		result[index] = v
	}
	return result
}
