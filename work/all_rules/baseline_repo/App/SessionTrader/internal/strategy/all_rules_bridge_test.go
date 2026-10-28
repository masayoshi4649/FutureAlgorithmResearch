package strategy
import "testing"
// allRulesExternalExpressions は変更前の内部条件をそのまま使います。
//
// 引数: t(*testing.T)、symbol/kind/method(string)。返り値: nilは旧Goの標準条件です。
func allRulesExternalExpressions(t *testing.T, symbol, kind, method string) map[string]string { return nil }
