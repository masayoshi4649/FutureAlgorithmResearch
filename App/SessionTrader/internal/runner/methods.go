package runner

import (
	"fmt"
	"futurealgorithm/sessiontrader/internal/config"
	"futurealgorithm/sessiontrader/internal/strategy"
)

// methodParameters は選択手法へ時刻設定と旧形式の上書きを適用します。
//
// 引数: cfg(config.Config) は運転設定、reference/kind(string) は売買市場と昼夜です。
// 返り値: strategy.Parameters は実効設定、error は手法IDまたは上書きの不整合です。
func methodParameters(cfg config.Config, reference, kind string) (strategy.Parameters, error) {
	parameters, err := strategy.ParametersForMethod(reference, kind, cfg.MethodID(kind))
	if err != nil {
		return strategy.Parameters{}, err
	}
	if parameters.Method != "" && len(cfg.Algorithm) > 0 {
		return strategy.Parameters{}, fmt.Errorf("%sは固定仕様です。旧algorithm係数の上書きは外してください", parameters.Method)
	}
	parameters.Extra.EntryCutoffSeconds = cfg.Schedule.ExtraCutoffSeconds
	if err := strategy.ApplyOverrides(&parameters, cfg.Algorithm); err != nil {
		return strategy.Parameters{}, err
	}
	return parameters, nil
}

// validateMethodSelection は接続・台帳変更より前に昼夜両方の手法指定を確認します。
//
// 引数: cfg(config.Config) は単一商品に正規化済みの設定です。
// 返り値: error は未対応IDまたは旧上書きの不整合です。
func validateMethodSelection(cfg config.Config) error {
	reference, _ := cfg.Selected()
	for _, kind := range []string{"Day", "Night"} {
		if _, err := methodParameters(cfg, reference, kind); err != nil {
			return err
		}
	}
	return nil
}
