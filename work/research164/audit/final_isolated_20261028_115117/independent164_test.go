package main

import (
	"encoding/json"
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
	"os"
	"testing"
)

// auditObservation164 は正常な人工気配を作ります。
//
// 引数: index(int64)、at/bid/ask(float64)。返り値: strategy.Observation。
func auditObservation164(index int64, at, bid, ask float64) strategy.Observation {
	return strategy.Observation{Index: index, Time: at, Bid: bid, Ask: ask, Last: (bid + ask) / 2, Reference: "NK225", QuoteOK: true}
}

// auditNight164 は実資料を読まない夜間人工口座を作ります。
//
// 引数: mode(string)、reentry(bool)。返り値: *NightResult164。
func auditNight164(mode string, reentry bool) *NightResult164 {
	return newNight164(NightConfig164{ID: "監査専用", Scope: "PreUS", RiskBudget: 50000, Protection: mode, Reentry: reentry}, Scene{Start: 0, USOpen: 10000, ForceClose: 20000})
}

// auditParent164 は独立した所有親を人工口座へ登録します。
//
// 引数: r(*NightResult164)、key(string)、side(int)。返り値: *NightParent164。
func auditParent164(r *NightResult164, key string, side int) *NightParent164 {
	p := &NightParent164{Base: AllocationParent157{Key: key, Owner: "監査", Side: side}}
	r.Parents[key] = p
	r.Sides[side].Parent = key
	return p
}

// TestIndependentNightUnknownRearm164 は経路未知を反対進行と誤認しないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependentNightUnknownRearm164(t *testing.T) {
	r := auditNight164("正利益開始", true)
	s := r.Sides[1]
	s.Ready = false
	s.FlatIndex = 1
	f := NightFeatures164{Time: 100, FirstNormal: true, Known15: false, Path15: false, Own15: -10}
	if err := r.stepNight164(auditObservation164(2, 100, 1000, 1010), f); err != nil {
		t.Fatal(err)
	}
	if s.Ready {
		t.Fatal("過去端が未知なのに通常入口を再解禁した")
	}
	f.Known15 = true
	f.Path15 = true
	if err := r.stepNight164(auditObservation164(3, 101, 1000, 1010), f); err != nil {
		t.Fatal(err)
	}
	if !s.Ready {
		t.Fatal("観測可能な非正を確認しても再解禁されない")
	}
}

// TestIndependentNightReservedRisk164 は両側新規予約と返済予約の危険枠を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependentNightReservedRisk164(t *testing.T) {
	r := auditNight164("R利益開始", false)
	b := auditParent164(r, "買", 1)
	s := auditParent164(r, "売", -1)
	o := auditObservation164(1, 1, 990, 1000)
	if n := r.reserveNight164(b, o, NightFeatures164{}, "初回", 100, 40); n != 100 {
		t.Fatalf("買の予約数=%d", n)
	}
	if n := r.reserveNight164(s, o, NightFeatures164{}, "初回", 100, 60); n != 16 {
		t.Fatalf("売の予約は残危険1万円から16枚のはず: %d", n)
	}
	if r.riskUsed() != 49600 {
		t.Fatalf("予約だけの危険=%v", r.riskUsed())
	}
	if err := r.fillNight164(auditObservation164(2, 2, 990, 1000)); err != nil {
		t.Fatal(err)
	}
	for _, id := range r.Actual.Active {
		l := r.Actual.Lots[id]
		if l.Side == 1 {
			r.Actual.closeLot(&b.Base, auditObservation164(3, 3, 990, 1000), id, "監査返済", l.Remaining, Support157{})
		}
	}
	if r.riskUsed() != 49600 {
		t.Fatalf("未約定の返済が危険を先取りして消した: %v", r.riskUsed())
	}
	if n := r.reserveNight164(s, auditObservation164(3, 3, 990, 1000), NightFeatures164{}, "順行追加", 10, 60); n != 0 {
		t.Fatalf("危険枠400円で60円停止を追加した: %d", n)
	}
}

// TestIndependentNightFloorGap164 は利益床を飛んだ実損失を隠さないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependentNightFloorGap164(t *testing.T) {
	for _, side := range []int{1, -1} {
		r := auditNight164("R利益開始", true)
		p := auditParent164(r, "床の親", side)
		quote := func(index int64, gain float64) strategy.Observation {
			if side > 0 {
				return auditObservation164(index, float64(index), 1000+gain, 1010+gain)
			}
			return auditObservation164(index, float64(index), 990-gain, 1000-gain)
		}
		entry := quote(1, -10)
		r.reserveNight164(p, entry, NightFeatures164{}, "初回", 50, 40)
		if err := r.fillNight164(quote(2, -10)); err != nil {
			t.Fatal(err)
		}
		if err := r.stepNight164(quote(3, 40), NightFeatures164{}); err != nil {
			t.Fatal(err)
		}
		if len(r.Actual.Pending) != 0 {
			t.Fatal("40円順行時に建値床で即返済した")
		}
		if err := r.stepNight164(quote(4, -10), NightFeatures164{}); err != nil {
			t.Fatal(err)
		}
		if len(r.Actual.Pending) != 1 {
			t.Fatal("床を飛んだ損失玉を返済しなかった")
		}
		if err := r.stepNight164(quote(5, -20), NightFeatures164{}); err != nil {
			t.Fatal(err)
		}
		if r.Actual.Realized != -10000 || len(r.Actual.Active) != 0 || r.Sides[side].ProfitSeed {
			t.Fatalf("実損失・完済又は再参加資格が不正: %v", r.Actual.Realized)
		}
	}
}

// TestIndependentNightSameClockPrefix164 は同時計後続の中値が過去判断を変えないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependentNightSameClockPrefix164(t *testing.T) {
	h := &NightHistory164{}
	for i, at := range []float64{0, 5, 10, 15} {
		h.add(auditObservation164(int64(i), at, 995+at*2, 1005+at*2))
	}
	first := h.add(auditObservation164(4, 20, 1035, 1045))
	later := h.add(auditObservation164(5, 20, 1085, 1095))
	if !first.FirstNormal || later.FirstNormal || first.Mid != 1040 {
		t.Fatal("同時計原行の代表又は既存特徴を上書きした")
	}
	next := h.add(auditObservation164(6, 21, 1035, 1045))
	if !next.FirstNormal || !next.Known5 || math.Abs(next.Own5-50.0/6) > 1e-8 || next.Elapsed5 != 6 {
		t.Fatalf("1秒遅れ端点の実経過換算が違う: %+v", next)
	}
}

// TestIndependentDayActualFloorAfterDifferentSourceClose164 は元の配賦と実FIFOの建値差が生じた残玉を検査します。
//
// 引数: t(*testing.T)。返り値: なし。実玉建値の床・Canonical同期・再投影防止を一つの因果経路で確認します。
func TestIndependentDayActualFloorAfterDifferentSourceClose164(t *testing.T) {
	r := newDay164(configsDay164()[1], Scene{Start: 0, ForceClose: 10000, End: 11000})
	support := map[int]Support157{1: {Known: true}, -1: {Known: true}}
	newSignal := func(id string, index int64) strategy.Signal {
		return strategy.Signal{ID: id, Owner: "core", Campaign: 1, Action: "new", Side: 1, Quantity: 5, Time: float64(index), SourceIndex: index}
	}
	closeSignal := func(id, target string, index int64) strategy.Signal {
		return strategy.Signal{ID: id, Owner: "core", Campaign: 1, Action: "close", Side: -1, Quantity: 5, Time: float64(index), SourceIndex: index, Targets: []strategy.LotTarget{{ID: target + "-玉", Quantity: 5}}}
	}
	step := func(index int64, bid, ask float64, signals ...strategy.Signal) {
		if err := stepDay164(r, auditObservation164(index, float64(index), bid, ask), signals, support, Short164{}); err != nil {
			t.Fatal(err)
		}
	}
	step(1, 990, 1000, newSignal("先玉", 1))
	step(2, 990, 1000)
	step(3, 1090, 1100, newSignal("後玉", 3))
	step(4, 1090, 1100)
	step(5, 1120, 1130, closeSignal("後玉を返済", "後玉", 5))
	step(6, 1120, 1130)
	if len(r.Actual.Active) != 1 || len(r.Canonical.Active) != 1 {
		t.Fatal("源部分返済後の残数が不正")
	}
	a := r.Actual.Lots[r.Actual.Active[0]]
	c := r.Canonical.Lots[r.Canonical.Active[0]]
	if a.Entry != 1100 || c.Entry != 1000 || a.Remaining != 10 || c.Remaining != 10 {
		t.Fatalf("異なる残建値を作れない: Actual=%+v Canonical=%+v", a, c)
	}
	step(7, 1090, 1100)
	if len(r.Actual.Pending) != 1 || len(r.Canonical.Pending) != 1 {
		t.Fatal("実建値1100の床割れで両台帳の数量同期返済が起動しない")
	}
	if len(r.Actual.Pending[0].Targets) != 1 || r.Actual.Pending[0].Targets[0].ID != a.ID {
		t.Fatal("保護返済が実所有IDを指していない")
	}
	step(8, 1080, 1090)
	if len(r.Actual.Active) != 0 || len(r.Canonical.Active) != 0 || len(r.Actual.Pending) != 0 || len(r.Canonical.Pending) != 0 {
		t.Fatal("独自保護後のCanonical再投影で玉が復活した")
	}
	if r.Actual.Realized != 10000 || r.Canonical.Realized != 10000 || a.Gross != -2000 {
		t.Fatalf("実玉損失/親合計が不正: %v %v %+v", r.Actual.Realized, r.Canonical.Realized, a)
	}
	step(9, 1080, 1090, closeSignal("源終了", "先玉", 9))
	step(10, 1080, 1090)
	if len(r.Actual.Events) != 4 || len(r.Actual.Pending) != 0 {
		t.Fatal("源終了で死亡した玉を再返済した")
	}
}

// TestIndependentExportFixture164 は実際のGo構造から制御器接続用の人工JSONを出力します。
//
// 引数: t(*testing.T)。返り値: なし。環境変数がある時だけ監査指定先へ保存します。
func TestIndependentExportFixture164(t *testing.T) {
	path := os.Getenv("AUDIT164_FIXTURE")
	if path == "" {
		return
	}
	scene := Scene{Session: "人工", Kind: "Day", Start: 0, USOpen: 10000, ForceClose: 20000, End: 21000}
	day := SavedDay164{Scene: scene}
	for _, config := range configsDay164() {
		r := newDay164(config, scene)
		ss := map[int]Support157{1: {Known: true}, -1: {Known: true}}
		for i := int64(1); i <= 4; i++ {
			o := auditObservation164(i, float64(i), 990, 1000)
			signals := []strategy.Signal{}
			if i == 1 {
				signals = append(signals, strategy.Signal{ID: "人工新規", Owner: "core", Campaign: 1, Side: 1, Action: "new", Quantity: 5, Time: o.Time, SourceIndex: i})
			}
			if i == 3 {
				signals = append(signals, strategy.Signal{ID: "人工返済", Owner: "core", Campaign: 1, Side: -1, Action: "close", Quantity: 5, Time: o.Time, SourceIndex: i, Targets: []strategy.LotTarget{{ID: "人工新規-玉", Quantity: 5}}})
			}
			if err := stepDay164(r, o, signals, ss, Short164{}); err != nil {
				t.Fatal(err)
			}
		}
		day.Cases = append(day.Cases, r)
	}
	scene.Kind = "Night"
	night := SavedNight164{Scene: scene}
	for _, config := range configsNight164() {
		r := newNight164(config, scene)
		p := auditParent164(r, "人工親", 1)
		r.Actual.open(&p.Base, auditObservation164(1, r.Start+1, 990, 1000), "人工", "人工", 1, 37, Support157{})
		if _, err := r.Actual.fill(auditObservation164(2, r.Start+2, 990, 1000)); err != nil {
			t.Fatal(err)
		}
		r.Actual.closeQuantity(&p.Base, auditObservation164(3, r.Start+3, 1030, 1040), "", "人工", 37, Support157{})
		if _, err := r.Actual.fill(auditObservation164(4, r.Start+4, 1030, 1040)); err != nil {
			t.Fatal(err)
		}
		p.Closed = true
		night.Cases = append(night.Cases, r)
	}
	data, err := json.MarshalIndent(map[string]any{"day": day, "night": night, "configs": allConfigs164(), "financial_runs": 0}, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(path, append(data, '\n'), 0600); err != nil {
		t.Fatal(err)
	}
}
