package config

import (
	"fmt"
	"path/filepath"

	"futurealgorithm/sessiontrader/internal/rules"
)

// RuleEngine は外部条件のファイルを指定します。銘柄規格や注文処理は含めません。
type RuleEngine struct {
	File string `toml:"file"`
}

// loadRules は指定済み外部条件を起動時に一度だけ読み込みます。
//
// 引数: なし。返り値: errorは構文・型・条件不足の不整合です。
func (c *Config) loadRules() error {
	if c.RuleEngine.File == "" {
		return c.bindDefaultRules()
	}
	path := c.RuleEngine.File
	if !filepath.IsAbs(path) {
		path = filepath.Join(c.Root, path)
	}
	set, err := rules.Load(path)
	if err != nil {
		return fmt.Errorf("売買ルール %s: %w", path, err)
	}
	c.RuleSet = set
	return nil
}

// RuleHash は起動時に固定した条件の指紋を返します。
//
// 引数: なし。返り値: stringはSHA256、D07も外部指定もない場合は空文字です。
func (c Config) RuleHash() string { return c.RuleSet.Hash() }

// RuleExpressions は戦略へ渡す条件を複製します。
//
// 引数: なし。返り値: map[string]stringは条件、D07も外部指定もない場合はnilです。
func (c Config) RuleExpressions() map[string]string { return c.RuleSet.Expressions() }

// bindDefaultRules は旧設定でD07を選んだ場合も実際に使う条件を監査対象にします。
//
// 引数: なし。返り値: errorは標準式の不整合です。
func (c *Config) bindDefaultRules() error {
	if c.RuleSet != nil {
		return nil
	}
	use := c.MethodID("Day") == "D07" || c.MethodID("Night") == "D07"
	for _, item := range c.Instruments {
		use = use || item.Day == "D07" || item.Night == "D07"
	}
	if !use {
		return nil
	}
	var err error
	c.RuleSet, err = rules.Default()
	return err
}
