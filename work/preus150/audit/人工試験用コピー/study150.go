package main

import (
	"errors"
	"fmt"

	"futurealgorithm/sessiontrader/internal/strategy"
)

// validateConfigs150 は登録する17条件と前後の固定時計を検査します。
//
// 引数: configs([]StudyConfig)は保存条件です。
// 返り値: errorは条件数・ID・前後境界・補完解禁に意図しない差がある場合です。
func validateConfigs150(configs []StudyConfig) error {
	if len(configs) != 17 {
		return errors.New("研究150はA00からA16の17条件です")
	}
	for i, c := range configs {
		if c.ID != fmt.Sprintf("A%02d", i) || c.CoreHour != 17 || c.ExtraHour != 0 || len(c.Owners) != 0 || !c.Reset || c.CloseBeforeMinutes != 15 || c.RestartWaitMinutes != 15 || !c.KeepFeatures || !c.PostOriginalClocks {
			return fmt.Errorf("研究150の共通固定条件が異なります: %s", c.ID)
		}
	}
	return nil
}

// count150 は保存会計を変更せず、担当別の入口診断を加算します。
//
// 引数: c(*Case)、owner/key(string)、value(int)は対象と増分です。返り値: なし。
func count150(c *Case, owner, key string, value int) {
	name := c.Phase + "/" + owner
	if c.Diagnostics[name] == nil {
		c.Diagnostics[name] = map[string]int{}
	}
	c.Diagnostics[name][key] += value
}

// diagnoseTransitions150 は準備の開始・解除・候補・実注文判断を当時の前後状態だけで数えます。
//
// 引数: c(*Case)、o(strategy.Observation)、before/after([3]strategy.StudyEntryState150)、signals([]strategy.Signal)。
// 返り値: なし。解除理由は現在行の同時条件であり、全内部分岐の一意な原因判定とは区別します。
func diagnoseTransitions150(c *Case, o strategy.Observation, before, after [3]strategy.StudyEntryState150, signals []strategy.Signal) {
	known := true
	for i := 0; i < 24; i++ {
		known = known && o.Research.Known[i]
	}
	for index, a := range after {
		owner := a.Owner
		if owner == "" {
			continue
		}
		b := before[index]
		if a.Arm != 0 && (b.Arm == 0 || a.ArmTime != b.ArmTime) {
			count150(c, owner, "準備開始", 1)
		}
		if a.Arm != 0 && b.Arm != 0 && a.ArmTime == b.ArmTime && a.Stage > b.Stage {
			count150(c, owner, "準備段階の進行", 1)
		}
		if !b.SinceKnown && a.SinceKnown {
			count150(c, owner, "継続確認開始", 1)
		}
		if b.Arm != 0 && a.Arm == 0 {
			count150(c, owner, "準備終了又は解除", 1)
			if !quoteOK(o) {
				count150(c, owner, "解除行が異常気配", 1)
			} else if !known {
				count150(c, owner, "解除行で24列の一部未知", 1)
			}
		}
		if a.PendingIndex == o.Index && a.NewCandidates > 0 {
			count150(c, owner, "源の新規候補", a.NewCandidates)
		}
	}
	for _, signal := range signals {
		if signal.Action == "new" {
			count150(c, signal.Owner, "採用新規判断", 1)
		}
	}
}
