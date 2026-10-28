package main

import (
	"bytes"
	"encoding/json"
	"reflect"
	"testing"

	"futurealgorithm/sessiontrader/internal/strategy"
)

// configsFor150 は原板を読まずに固定17条件だけを読み込みます。
//
// 引数: t(*testing.T)。返り値: []StudyConfigは検査済みの条件です。
func configsFor150(t *testing.T) []StudyConfig {
	t.Helper()
	var configs []StudyConfig
	if e := readJSON("../configs150.json", &configs); e != nil {
		t.Fatal(e)
	}
	if e := validateConfigs150(configs); e != nil {
		t.Fatal(e)
	}
	return configs
}

// jsonFor150 は人工状態を順序一定のJSONへ直列化します。
//
// 引数: t(*testing.T)、v(any)。返り値: []byteは比較用の状態です。
func jsonFor150(t *testing.T, v any) []byte {
	t.Helper()
	raw, e := json.Marshal(v)
	if e != nil {
		t.Fatal(e)
	}
	return raw
}

// Test150PostIdentical は全17条件の後半がS04と同じ新規状態になることを確かめます。
//
// 引数: t(*testing.T)。返り値: なし。前半用式の元マップへの漏洩も確認します。
func Test150PostIdentical(t *testing.T) {
	s, r := testSetup(t)
	configs := configsFor150(t)
	oldRules := jsonFor150(t, r)
	base, _, _, e := newPortfolio(s, StudyConfig{Reset: true, CloseBeforeMinutes: 15, RestartWaitMinutes: 15, KeepFeatures: true, PostOriginalClocks: true}, true, r)
	if e != nil {
		t.Fatal(e)
	}
	for _, c := range configs {
		if _, _, _, e = newPortfolio(s, c, false, r); e != nil {
			t.Fatal(c.ID, e)
		}
		p, from, end, e := newPortfolio(s, c, true, r)
		if e != nil || from != s.USOpen+900 || end != s.ForceClose {
			t.Fatal(c.ID, "後半時計", e)
		}
		if !bytes.Equal(jsonFor150(t, p), jsonFor150(t, base)) || !bytes.Equal(jsonFor150(t, r), oldRules) {
			t.Fatal(c.ID, "前半設定が後半又は元式へ漏洩")
		}
	}
}

// Test150ExplicitSourceWiring は前半だけの入口差分と独立episodeの不変を確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test150ExplicitSourceWiring(t *testing.T) {
	s, r := testSetup(t)
	configs := configsFor150(t)
	base, _, _, _ := newPortfolio(s, configs[0], false, r)
	episode := jsonFor150(t, base.Research.Sleeves[2].Source.Active)
	for _, c := range configs {
		p, from, end, e := newPortfolio(s, c, false, r)
		if e != nil || from != s.Start || end != s.USOpen-900 {
			t.Fatal(c.ID, "前半時計", e)
		}
		core := p.Research.Sleeves[0].Source
		if core.Legacy.Config.Parameters.Night.PostOpenPrepareSeconds != s.Start-s.USOpen || core.Session.ExtraAt != s.USOpen+1800 || core.Session.StudyEarlyFallback {
			t.Fatal(c.ID, "主担当早期解禁又は補完禁止が不正")
		}
		if !bytes.Equal(jsonFor150(t, p.Research.Sleeves[2].Source.Active), episode) || p.Research.Sleeves[2].Source.Active.D07Rules {
			t.Fatal(c.ID, "episodeの条件を変更")
		}
		if p.Config.Cap != 10 || p.Research.Sleeves[0].Capacity != 5 || p.Research.Sleeves[1].Capacity != 3 || p.Research.Sleeves[2].Capacity != 2 {
			t.Fatal(c.ID, "固定配分を変更")
		}
		wantInitial := 2
		if c.ID == "A13" {
			wantInitial = 1
		}
		if p.Research.Sleeves[1].Source.Active145.Initial != wantInitial {
			t.Fatal(c.ID, "初回枚数が未接続")
		}
	}
}

// Test150EfficiencyHasCausalEffect は同じ人工板で主担当の方向効率変更だけが準備を開始することを確かめます。
//
// 引数: t(*testing.T)。返り値: なし。実価格や将来価格を使いません。
func Test150EfficiencyHasCausalEffect(t *testing.T) {
	s, r := testSetup(t)
	configs := configsFor150(t)
	o := strategy.Observation{Reference: "NK225", Index: 0, Time: s.Start + 2700, Received: s.Start + 2700, Last: 1000, Bid: 1000, Ask: 1010, ATR: 40, QuoteOK: true}
	o.MidMarket = strategy.Market{Known: true, Own30Known: true, Peer30Known: true, Own120Known: true, Peer120Known: true, Own30: 1, Peer30: 1, Own120: 1, Peer120: 1}
	o.MidHistory.Known = true
	o.MidHistory.Values[3], o.MidHistory.Values[4] = 1000, 900
	o.MidHistory.Values[5], o.MidHistory.Values[10], o.MidHistory.Values[11] = .30, 5, 10
	for _, i := range []int{0, 1} {
		p, _, _, e := newPortfolio(s, configs[i], false, r)
		if e != nil {
			t.Fatal(e)
		}
		if _, e = p.Observe(o, true); e != nil {
			t.Fatal(e)
		}
		arm := p.Research.Sleeves[0].Source.Legacy.Core.Arm.Side
		if (i == 0 && arm != 0) || (i == 1 && arm != 1) {
			t.Fatal(configs[i].ID, "効率の変更が入口へ接続されていない", arm)
		}
	}
}

// Test150RuleThresholds は外部式の緩和が当時値に対して実際に成立条件を変えることを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test150RuleThresholds(t *testing.T) {
	s, r := testSetup(t)
	configs := configsFor150(t)
	cases := []struct {
		Index int
		Name  string
		Env   map[string]any
	}{
		{7, "addon.entry.confirmed", map[string]any{"elapsed": 10.}},
		{8, "addon.entry.rebound", map[string]any{"distance": 15., "risk": 100.}},
		{9, "addon.entry.range_rebound", map[string]any{"rebound": 7., "risk": 100., "boundary_distance": 1.}},
		{11, "addon.reentry_ready", map[string]any{"elapsed": 5., "spread": 10., "risk": 100.}},
		{12, "addon.add_trigger", map[string]any{"own30": 1., "peer30": 0., "gain": 75., "next_ticket": 2., "risk": 100., "elapsed": 30.}},
	}
	base, _, _, _ := newPortfolio(s, configs[0], false, r)
	for _, x := range cases {
		changed, _, _, e := newPortfolio(s, configs[x.Index], false, r)
		if e != nil || base.Rules.Bool(x.Name, x.Env) || !changed.Rules.Bool(x.Name, x.Env) {
			t.Fatal(x.Name, "式の緩和が未接続", e)
		}
	}
	p, _, _, _ := newPortfolio(s, configs[6], false, r)
	if p.Rules.Number("addon.entry.mode", map[string]any{"efficiency": .32}) != 1 || p.Rules.Number("addon.entry.mode", map[string]any{"efficiency": .23}) != 4 {
		t.Fatal("型選択の効率区分が未接続")
	}
}

// Test150RangeZonesSymmetric は狭い帯でもA10が買い側を優先せず、上下を反転した方向を返すことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test150RangeZonesSymmetric(t *testing.T) {
	s, r := testSetup(t)
	c := configsFor150(t)[10]
	p, _, _, e := newPortfolio(s, c, false, r)
	if e != nil {
		t.Fatal(e)
	}
	for _, width := range []float64{0, 10, 20, 100, 300} {
		for i := -5; i <= 15; i++ {
			mid := 1000 + float64(i)*width/10
			env := map[string]any{"efficiency": .1, "risk": 200., "low": 1000., "high": 1000. + width, "mid": mid}
			d := p.Rules.Number("addon.entry.range_side", env)
			env["mid"] = 2000 + width - mid
			other := p.Rules.Number("addon.entry.range_side", env)
			if d != -other {
				t.Fatal("買売で異なる候補", width, mid, d, other)
			}
		}
	}
}

// Test150UnsafeOverridesRejected は鮮度・板品質・未知名の上書きと不正な前半設定を拒否します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test150UnsafeOverridesRejected(t *testing.T) {
	s, r := testSetup(t)
	for _, name := range []string{"core.peer_fresh", "addon.entry.spread_reject", "不明"} {
		if _, e := strategy.StudyRuleOverrides150(r, map[string]string{name: "true"}); e == nil {
			t.Fatal("変更対象外を許可", name)
		}
	}
	for _, override := range []map[string]float64{{"不明": 1}, {"efficiency": 1.5}, {"bounce_r": -1}, {"retest_return_r": 1}} {
		c := configsFor150(t)[0]
		c.PreCore = override
		if _, _, _, e := newPortfolio(s, c, false, r); e == nil {
			t.Fatal("不正値を許可", override)
		}
	}
}

// Test150CombinedConditionsFixed は組合せ条件を単因子の固定和として照合します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test150CombinedConditionsFixed(t *testing.T) {
	configs := configsFor150(t)
	for _, group := range []struct {
		Target  int
		Sources []int
	}{{15, []int{1, 2, 3, 5, 6, 7, 8}}, {16, []int{15, 11, 12, 14}}} {
		core, rules := map[string]float64{}, map[string]string{}
		for _, index := range group.Sources {
			for k, v := range configs[index].PreCore {
				core[k] = v
			}
			for k, v := range configs[index].PreRules {
				rules[k] = v
			}
		}
		if !reflect.DeepEqual(core, configs[group.Target].PreCore) || !reflect.DeepEqual(rules, configs[group.Target].PreRules) {
			t.Fatal("組合せ条件が事前定義と異なる", group.Target)
		}
	}
}
