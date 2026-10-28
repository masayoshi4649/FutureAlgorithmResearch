package strategy

import "futurealgorithm/sessiontrader/internal/rules"

// bindRules はD07の主担当と追加担当を同じ条件・エラー監視へ接続します。
//
// 引数: なし。返り値: errorは保存された式の不整合です。
func (p *Portfolio) bindRules() error {
	if p.Config.Parameters.Method != "D07" {
		return nil
	}
	runtime, err := rules.NewRuntime(p.Config.RuleExpressions)
	if err != nil {
		return err
	}
	p.Rules = runtime
	if p.Research != nil {
		for _, sleeve := range p.Research.Sleeves {
			sleeve.Source.attachRules(runtime)
		}
	}
	return nil
}

// bindRules は独立した担当の照合でも同じ外部条件を読み込みます。
//
// 引数: なし。返り値: errorは条件の不整合です。
func (s *ResearchSource) bindRules() error {
	if s.Config.Parameters.Method != "D07" {
		return nil
	}
	runtime, err := rules.NewRuntime(s.Config.RuleExpressions)
	if err != nil {
		return err
	}
	s.attachRules(runtime)
	return nil
}

// attachRules は保存対象外の評価器を担当へ接続します。
//
// 引数: runtime(*rules.Runtime)は一戦略専用の評価状態。返り値: なし。
func (s *ResearchSource) attachRules(runtime *rules.Runtime) {
	s.Rules = runtime
	if s.Active145 != nil {
		s.Active145.Rules, s.Active145.D07Rules = runtime, true
	}
	// 独立した夜間episodeはCS04のままで、追加担当の入口式は適用しません。
}
