package main

import (
	"futurealgorithm/sessiontrader/internal/rules"
	"testing"
)

// Test154Round2Expressions はJ03の通常追撃抑止を昼だけに限定します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test154Round2Expressions(t *testing.T) {
	r, e := rules.Load("NK225_D07.toml")
	if e != nil {
		t.Fatal(e)
	}
	base := r.Expressions()
	for _, id := range []string{"S00", "S01", "S04", "S02", "S03", "J01", "J02", "J03"} {
		for _, kind := range []string{"Day", "Night"} {
			got := variantExpressions(base, id, kind)
			for k, v := range base {
				want := v
				if id == "J03" && kind == "Day" && k == "addon.add_ready" {
					want = "false"
				}
				if got[k] != want {
					t.Fatal(id, kind, k)
				}
			}
		}
	}
}
