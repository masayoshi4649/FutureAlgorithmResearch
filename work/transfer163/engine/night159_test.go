package main

import (
	"encoding/json"
	"futurealgorithm/sessiontrader/internal/rules"
	"futurealgorithm/sessiontrader/internal/strategy"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"
)

// quote159 は実市場資料を使わない人工の正常原板を作ります。
//
// 引数: index(int64)、at/bid/ask(float64)。返り値: strategy.Observationです。
func quote159(index int64, at, bid, ask float64) strategy.Observation {
	return strategy.Observation{Reference: "NK225", Index: index, Time: at, Bid: bid, Ask: ask, QuoteOK: true}
}

// TestPhaseTransitionsArtificial159 は人工の無方向板だけで全夜の時間枠と後半新規状態を検査します。
//
// 引数: t(*testing.T)。返り値: なし。市場資料・保存損益は読みません。
func TestPhaseTransitionsArtificial159(t *testing.T) {
	dir := t.TempDir()
	start := 1700000000.0
	scene := Scene{Session: "人工_Night", Kind: "Night", Start: start, USOpen: start + 7200, ForceClose: start + 17400, End: start + 18000, Books: map[string]string{}, Candles: map[string]map[string]string{}}
	for _, ref := range []string{"NK225", "TOPIX"} {
		path := filepath.Join(dir, ref+".jsonl")
		file, e := os.Create(path)
		if e != nil {
			t.Fatal(e)
		}
		for second := 0; second <= 18000; second += 30 {
			stamp := time.Unix(int64(start)+int64(second), 0).UTC().Format(time.RFC3339)
			price := 10000.0
			if ref == "TOPIX" {
				price = 4000
			}
			b := map[string]any{"CurrentPriceTime": stamp, "CurrentPrice": price, "Buy1": map[string]float64{"Price": price - 5, "Qty": 100}, "Sell1": map[string]float64{"Price": price + 5, "Qty": 100}}
			if e = json.NewEncoder(file).Encode(b); e != nil {
				t.Fatal(e)
			}
		}
		file.Close()
		scene.Books[ref] = path
		scene.Candles[ref] = map[string]string{}
		for _, interval := range []string{"60", "300"} {
			p := filepath.Join(dir, ref+interval+".json")
			if e = os.WriteFile(p, []byte(`{"Data":[]}`), 0600); e != nil {
				t.Fatal(e)
			}
			scene.Candles[ref][interval] = p
		}
	}
	sets := map[string]map[string]string{}
	for _, m := range []string{"D07", "P05", "S01"} {
		profile := map[string]string{"D07": "d07", "P05": "p05", "S01": "s01"}[m]
		s, e := rules.LoadFor("rules/NK225_"+m+".toml", profile)
		if e != nil {
			t.Fatal(e)
		}
		sets[m] = s.Expressions()
	}
	r, e := run159(scene, configs159(), sets)
	if e != nil {
		t.Fatal(e)
	}
	if len(r.Sources) != 2 || r.Sources[0].Method != "P05" || r.Sources[1].Method != "D07" || len(r.Transitions) != 2 || r.Transitions[1].At < scene.USOpen+900 || r.Transitions[1].Index <= 0 {
		t.Fatal("時間枠又は新Sourceが異なる")
	}
	day := scene
	day.Kind = "Day"
	day.Session = "人工_Day"
	v, e := run159(day, configs159(), sets)
	if e != nil {
		t.Fatal(e)
	}
	if len(v.Sources) != 1 || v.Sources[0].Method != "S01" || len(v.Cases) != 2 {
		t.Fatal("追加DayがS01二条件でない")
	}
}

// support159 は人工の既知支持を両方向へ分けて作ります。
//
// 引数: なし。返り値: map[int]Support157です。
func support159() map[int]Support157 {
	return map[int]Support157{1: {Known: true, M: .8, T: .8, Opp: .1, Own5: 1, Own15: 1}, -1: {Known: true, M: .2, T: .2, Opp: .8, Own5: 1, Own15: 1}}
}

// seed159 は当行に約定しない初回判断を、次原行で約定させます。
//
// 引数: t(*testing.T)、id/phase(string)。返り値: *PolicyResult157です。
func seed159(t *testing.T, id, phase string) *PolicyResult157 {
	t.Helper()
	var cfg Policy157
	for _, p := range configs159() {
		if p.ID == id {
			cfg = p
		}
	}
	r := newPolicy157(cfg, Scene{Start: 100, ForceClose: 10000, End: 10100, Kind: "Night"})
	sig := strategy.Signal{ID: phase + "/seed", Owner: phase + "/core", Campaign: 1, Action: "new", Side: 1, Quantity: 5, Time: 100, SourceIndex: 0}
	if e := stepPolicy159(r, quote159(0, 100, 999, 1001), []strategy.Signal{sig}, support159()); e != nil {
		t.Fatal(e)
	}
	if len(r.Actual.Events) != 0 {
		t.Fatal("同じ板で約定した")
	}
	if e := stepPolicy159(r, quote159(1, 101, 999, 1001), nil, support159()); e != nil {
		t.Fatal(e)
	}
	return r
}

// TestQuantityAndMissing159 は支持による数量と未知・逆支持対照の境界を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestQuantityAndMissing159(t *testing.T) {
	policies := configs159()
	s := Support157{Known: true, M: .8, T: .5}
	expected := map[string]int{"N01": 10, "N02": 46, "N05": 24, "N06": 64}
	for _, p := range policies {
		if n, ok := expected[p.ID]; ok {
			r := newPolicy157(p, Scene{})
			if got := r.desired157(s); got != n {
				t.Fatalf("%s 数量%d", p.ID, got)
			}
			if r.desired157(Support157{}) != 10 {
				t.Fatal("未知を強い支持にした")
			}
		}
	}
	if !decelerated159(Support157{Known: true, Own15: 6, Own5: .9}, 1) || decelerated159(Support157{Known: true, Own15: 6, Own5: 1}, 1) || decelerated159(Support157{Known: false, Own15: 6}, 1) {
		t.Fatal("失速境界")
	}
	if !decelerated159(Support157{Known: true, Own15: -6, Own5: -.9}, -1) {
		t.Fatal("売り非対称")
	}
	for _, p := range []Policy157{policies[3], policies[4]} {
		if effective159(p, p.PhaseSelection).Exact {
			t.Fatal("対象枠を基準にした")
		}
		other := "前半"
		if other == p.PhaseSelection {
			other = "後半"
		}
		if !effective159(p, other).Exact {
			t.Fatal("非対象枠に数量変更")
		}
	}
}

// TestConstantSpeedAndSourceCampaign159 は一定速度・加速・反転とP05の返済親補完を検査します。
//
// 引数: t(*testing.T)。返り値: なし。P05元通知を変更せず政策通知だけへ所有親を写します。
func TestConstantSpeedAndSourceCampaign159(t *testing.T) {
	for _, v := range []struct {
		five, fifteen float64
		want          bool
	}{{2, 6, false}, {3, 6, false}, {.9, 6, true}, {-1, 6, true}, {-2, -6, false}} {
		side := 1
		if v.fifteen < 0 {
			side = -1
		}
		if decelerated159(Support157{Known: true, Own5: v.five, Own15: v.fifteen}, side) != v.want {
			t.Fatalf("速度例 %+v", v)
		}
	}
	s := &SourceState159{Lots: map[string]*SourceLot159{"new-玉": {Owner: "core", Campaign: 7}}}
	raw := strategy.Signal{ID: "close", Owner: "core", Campaign: 0, Action: "close", Side: -1, Quantity: 2, Targets: []strategy.LotTarget{{ID: "new-玉", Quantity: 2}}}
	mapped, e := s.policySignal159(raw)
	if e != nil || mapped.Campaign != 7 || raw.Campaign != 0 || mapped.ID != raw.ID {
		t.Fatal("元通知を壊したか補完不足", e)
	}
}

// TestSourceImmediateLiquidationMark159 は買Askと売Bidの約定直後に気配差がMAEへ入ることを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestSourceImmediateLiquidationMark159(t *testing.T) {
	s := &SourceState159{Lots: map[string]*SourceLot159{"buy": {Side: 1, Entry: 1001, Remaining: 1}, "sell": {Side: -1, Entry: 999, Remaining: 1}}}
	s.markSource159(quote159(1, 101, 999, 1001))
	for _, l := range s.Lots {
		if l.Worst != -2 || l.Best != 0 {
			t.Fatalf("約定直後の返済気配 %+v", l)
		}
	}
}

// TestExactQuantityAndBoundary159 は元通知の10倍換算と次正常板・所有返済を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestExactQuantityAndBoundary159(t *testing.T) {
	r := seed159(t, "N00", "前半")
	if len(r.Actual.Events) != 1 || r.Actual.Events[0].Order.Quantity != 50 {
		t.Fatal("元量の10倍不一致")
	}
	sig := strategy.Signal{ID: "前半/close", Owner: "前半/core", Campaign: 1, Action: "close", Side: -1, Quantity: 5, Time: 102, SourceIndex: 2, Targets: []strategy.LotTarget{{ID: "前半/seed-玉", Quantity: 5}}}
	if e := stepPolicy159(r, quote159(2, 102, 1020, 1022), []strategy.Signal{sig}, support159()); e != nil {
		t.Fatal(e)
	}
	bad := quote159(3, 103, 0, 0)
	bad.QuoteOK = false
	if e := stepPolicy159(r, bad, nil, support159()); e != nil {
		t.Fatal(e)
	}
	if len(r.Actual.Events) != 1 {
		t.Fatal("異常板約定")
	}
	if e := stepPolicy159(r, quote159(4, 104, 1030, 1032), nil, support159()); e != nil {
		t.Fatal(e)
	}
	if len(r.Actual.Active) != 0 || r.Actual.Realized != 14500 {
		t.Fatalf("全返済収支 %v", r.Actual.Realized)
	}
}

// TestSupportCapAndSourceExit159 は大きい希望量でも予約込み100枚を守り元返済を優先します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestSupportCapAndSourceExit159(t *testing.T) {
	r := newPolicy157(configs159()[9], Scene{Start: 100, ForceClose: 1000})
	ss := map[int]Support157{1: {Known: true, M: 1, T: 1}}
	sigs := []strategy.Signal{}
	for i, owner := range []string{"core", "addon"} {
		sigs = append(sigs, strategy.Signal{ID: owner, Owner: "後半/" + owner, Campaign: 1, Action: "new", Side: 1, Quantity: 5, Time: 100, SourceIndex: 0})
		_ = i
	}
	if e := stepPolicy159(r, quote159(0, 100, 999, 1001), sigs, ss); e != nil {
		t.Fatal(e)
	}
	if e := stepPolicy159(r, quote159(1, 101, 999, 1001), nil, ss); e != nil {
		t.Fatal(e)
	}
	a, b := r.Actual.position("", "")
	if a != 100 || b != 0 {
		t.Fatalf("上限 %d/%d", a, b)
	}
	if e := stepPolicy159(r, quote159(2, 102, 1060, 1062), nil, ss); e != nil {
		t.Fatal(e)
	}
	closes := []strategy.Signal{}
	for _, s := range sigs {
		closes = append(closes, strategy.Signal{ID: s.ID + "close", Owner: s.Owner, Campaign: 1, Action: "close", Side: -1, Quantity: 5, Time: 103, SourceIndex: 3, Targets: []strategy.LotTarget{{ID: s.ID + "-玉", Quantity: 5}}})
	}
	if e := stepPolicy159(r, quote159(3, 103, 1000, 1002), closes, ss); e != nil {
		t.Fatal(e)
	}
	for _, o := range r.Actual.Pending {
		if o.Reason != "source_end" {
			t.Fatal("Source返済より新追尾が優先された")
		}
	}
}

// TestProfitProtectionUsesNextQuote159 は後半全玉だけの床と次板飛び損失を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestProfitProtectionUsesNextQuote159(t *testing.T) {
	r := seed159(t, "N10", "後半")
	for i, row := range []struct{ bid, ask float64 }{{1022, 1024}, {1040, 1042}, {1020, 1022}, {990, 992}} {
		if e := stepPolicy159(r, quote159(int64(i+2), 102+float64(i), row.bid, row.ask), nil, support159()); e != nil {
			t.Fatal(e)
		}
	}
	if len(r.Actual.Events) != 2 || r.Actual.Realized >= 0 {
		t.Fatal("次板の飛び越え損失を隠した")
	}
	pre := seed159(t, "N10", "前半")
	for i, p := range []float64{1040, 1000} {
		if e := stepPolicy159(pre, quote159(int64(i+2), 102+float64(i), p, p+2), nil, support159()); e != nil {
			t.Fatal(e)
		}
	}
	if len(pre.Actual.Pending) != 0 {
		t.Fatal("前半へ後半追尾を適用した")
	}
}

// TestGuardUnknownAndGapReset159 は未知又は観測間隔で逆支持の継続時計をリセットします。
//
// 引数: t(*testing.T)。返り値: なし。
func TestGuardUnknownAndGapReset159(t *testing.T) {
	r := seed159(t, "N11", "前半")
	bad := map[int]Support157{1: {Known: true, Opp: .8, Own5: -1, Own15: -1}}
	for i, at := range []float64{102, 104} {
		if e := stepPolicy159(r, quote159(int64(i+2), at, 900, 902), nil, bad); e != nil {
			t.Fatal(e)
		}
	}
	if e := stepPolicy159(r, quote159(4, 106, 900, 902), nil, map[int]Support157{}); e != nil {
		t.Fatal(e)
	}
	for i, at := range []float64{108, 110, 112} {
		if e := stepPolicy159(r, quote159(int64(i+5), at, 900, 902), nil, bad); e != nil {
			t.Fatal(e)
		}
	}
	if len(r.Actual.Pending) > 0 {
		t.Fatal("未知前の秒数を足した")
	}
	if e := stepPolicy159(r, quote159(8, 120, 900, 902), nil, bad); e != nil {
		t.Fatal(e)
	}
	if len(r.Actual.Pending) > 0 {
		t.Fatal("欠測時間を継続へ足した")
	}
	for i, at := range []float64{122, 124, 125} {
		if e := stepPolicy159(r, quote159(int64(i+9), at, 900, 902), nil, bad); e != nil {
			t.Fatal(e)
		}
	}
	if len(r.Actual.Pending) != 1 {
		t.Fatal("5秒継続返済がない")
	}
}

// TestNamespaceAndRegistration159 は所有名前空間の非破壊性と未登録拒否を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestNamespaceAndRegistration159(t *testing.T) {
	s := strategy.Signal{ID: "x", Owner: "core", Targets: []strategy.LotTarget{{ID: "a", Quantity: 2}}}
	copyS := s
	copyS.Targets = append([]strategy.LotTarget(nil), s.Targets...)
	a, b := namespace159(s, "前半"), namespace159(s, "後半")
	if a.ID == b.ID || !reflect.DeepEqual(s, copyS) {
		t.Fatal("枠ID衝突又は元通知破壊")
	}
	if registration159("") == nil {
		t.Fatal("未登録を許可")
	}
}
