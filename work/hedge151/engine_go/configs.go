package main

// fixedConfigsは事前固定した18条件を返します。
//
// 引数: なし。返り値: []Configは入口通知・個別出口・数量・両建て・境界を分離した対照です。
func fixedConfigs() []Config {
	return []Config{
		{ID: "P01", Description: "前半・利益40ptから20pt追尾", Scope: "pre", Activation: 40, Trail: 20, RequirePositive: true},
		{ID: "P02", Description: "前半・利益80ptから40pt追尾", Scope: "pre", Activation: 80, Trail: 40, RequirePositive: true},
		{ID: "P03", Description: "前半・利益160ptから80pt追尾", Scope: "pre", Activation: 160, Trail: 80, RequirePositive: true},
		{ID: "P04", Description: "前半・利益80ptから20pt追尾", Scope: "pre", Activation: 80, Trail: 20, RequirePositive: true},
		{ID: "P05", Description: "前半・利益40ptから10pt追尾", Scope: "pre", Activation: 40, Trail: 10, RequirePositive: true},
		{ID: "P06", Description: "前半・80/40追尾・各通知最大1枚", Scope: "pre", Activation: 80, Trail: 40, QuantityLimit: 1, RequirePositive: true},
		{ID: "P07", Description: "前半・80/40追尾・各通知最大2枚", Scope: "pre", Activation: 80, Trail: 40, QuantityLimit: 2, RequirePositive: true},
		{ID: "P08", Description: "前半・80/40追尾・同時反対玉禁止", Scope: "pre", Activation: 80, Trail: 40, NoOpposite: true, RequirePositive: true},
		{ID: "P09", Description: "前半・80/40通常追尾・判断時損失でも返済", Scope: "pre", Activation: 80, Trail: 40},
		{ID: "P10", Description: "前半・80/40追尾・黒字返済後40pt追尾再新規", Scope: "pre", Activation: 80, Trail: 40, RequirePositive: true, ReentryDistance: 40},
		{ID: "P11", Description: "前半・80/40追尾・1枚・黒字返済後40pt追尾再新規", Scope: "pre", Activation: 80, Trail: 40, QuantityLimit: 1, RequirePositive: true, ReentryDistance: 40},
		{ID: "N01", Description: "全夜・利益40ptから20pt追尾", Scope: "night", Activation: 40, Trail: 20, RequirePositive: true},
		{ID: "N02", Description: "全夜・利益80ptから40pt追尾", Scope: "night", Activation: 80, Trail: 40, RequirePositive: true},
		{ID: "N03", Description: "全夜・利益160ptから80pt追尾", Scope: "night", Activation: 160, Trail: 80, RequirePositive: true},
		{ID: "N04", Description: "全夜・80/40追尾・各通知最大1枚", Scope: "night", Activation: 80, Trail: 40, QuantityLimit: 1, RequirePositive: true},
		{ID: "N05", Description: "全夜・80/40通常追尾・判断時損失でも返済", Scope: "night", Activation: 80, Trail: 40},
		{ID: "N06", Description: "全夜・80/40追尾・黒字返済後40pt追尾再新規", Scope: "night", Activation: 80, Trail: 40, RequirePositive: true, ReentryDistance: 40},
		{ID: "N07", Description: "全夜・80/40追尾・1枚・黒字返済後40pt追尾再新規", Scope: "night", Activation: 80, Trail: 40, QuantityLimit: 1, RequirePositive: true, ReentryDistance: 40},
	}
}
