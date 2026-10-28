package main

import (
	"encoding/json"
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
	"reflect"
	"testing"
)

// quoteNightTest164 は人工ラージ気配と原行番号を作ります。
//
// 引数: index(int64)、at/bid/ask(float64)。返り値: strategy.Observation。
func quoteNightTest164(index int64, at, bid, ask float64) strategy.Observation {
	return strategy.Observation{Reference: "NK225", Index: index, Time: at, Received: at, Last: (bid + ask) / 2, Bid: bid, Ask: ask, QuoteOK: bid > 0 && ask > bid}
}

// featuresNightTest164 は価格以外の既知条件を明示した人工特徴を作ります。
//
// 引数: o(Observation)。返り値: NightFeatures164。
func featuresNightTest164(o strategy.Observation) NightFeatures164 {
	return NightFeatures164{Time: o.Time, Mid: (o.Bid + o.Ask) / 2, Spread: o.Ask - o.Bid, Own5: 10, Own15: 20, Own120: 100, ER15: .5, ER120: .5, High60: 1060, Low60: 900, Known5: true, Known15: true, Known60: true, Known120: true, Known300: true, Path15: true, Path120: true, FirstNormal: true}
}

// seedNightTest164 は通常予約経路で人工初回を作ります。
//
// 引数: t(*testing.T)、number/side/q(int)、risk(float64)。返り値: *NightResult164、*NightParent164。
func seedNightTest164(t *testing.T, number, side, q int, risk float64) (*NightResult164, *NightParent164) {
	t.Helper()
	r := newNight164(configsNight164()[number], Scene{Start: 0, USOpen: 10000, ForceClose: 20000})
	p := &NightParent164{Base: AllocationParent157{Key: "人工親", Owner: "PreUS", Side: side, Campaign: 1}}
	r.Parents[p.Base.Key] = p
	r.Sides[side].Parent = p.Base.Key
	o := quoteNightTest164(0, 100, 990, 1000)
	if r.reserveNight164(p, o, featuresNightTest164(o), "初回", q, risk) != q {
		t.Fatal("人工数量不足")
	}
	if e := r.fillNight164(quoteNightTest164(1, 101, 990, 1000)); e != nil {
		t.Fatal(e)
	}
	return r, p
}

// TestNight164Features は厳密端点、同時計prefix、未知と経路を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestNight164Features(t *testing.T) {
	h := &NightHistory164{}
	var f NightFeatures164
	for i := 0; i <= 310; i++ {
		o := quoteNightTest164(int64(i), float64(i), 1000+float64(i), 1010+float64(i))
		f = h.add(o)
	}
	if !f.Known300 || f.Own5 != 5 || f.Own15 != 15 || f.ER15 != 1 || f.Range300 != 300 {
		t.Fatalf("線形特徴 %+v", f)
	}
	before := f
	later := h.add(quoteNightTest164(311, 310, 2000, 2010))
	if later.FirstNormal || !reflect.DeepEqual(f, before) {
		t.Fatal("同時計の後続が既判断を変更")
	}
	h.add(quoteNightTest164(312, 311, 2000, 1990))
	f = h.add(quoteNightTest164(313, 312, 1312, 1322))
	if f.Known300 || f.Path15 || !f.Known5 {
		t.Fatalf("価格端と異常経路の混同 %+v", f)
	}
	h = &NightHistory164{}
	h.add(quoteNightTest164(0, 0, 1000, 1010))
	f = h.add(quoteNightTest164(1, 6, 1060, 1070))
	if !f.Known5 || f.Elapsed5 != 6 || f.Own5 != 50 {
		t.Fatal("1秒許容又は実経過換算")
	}
	f = h.add(quoteNightTest164(2, 6.01, 1060, 1070))
	if f.Known5 {
		t.Fatal("許容超過端点")
	}
}

// TestNight164ProtectionAndGap は即時床とR開始を分離し、次板損失を計上します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestNight164ProtectionAndGap(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, number := range []int{1, 2} {
			r, _ := seedNightTest164(t, number, side, 10, 40)
			entry := 1000.
			if side < 0 {
				entry = 990
			}
			makeO := func(i int64, gain float64) strategy.Observation {
				price := entry + float64(side)*gain
				if side > 0 {
					return quoteNightTest164(i, 100+float64(i), price, price+10)
				}
				return quoteNightTest164(i, 100+float64(i), price-10, price)
			}
			o := makeO(2, 10)
			r.Actual.mark(o)
			r.protectNight164(o, featuresNightTest164(o))
			g := r.Guards[r.Actual.Active[0]]
			if g.Active != (number == 2) {
				t.Fatal("起動条件の交絡")
			}
			o = makeO(3, 0)
			r.Actual.mark(o)
			r.protectNight164(o, featuresNightTest164(o))
			if number == 1 {
				if len(r.Actual.Pending) != 0 {
					t.Fatal("R未起動の床")
				}
				continue
			}
			if len(r.Actual.Pending) != 1 {
				t.Fatal("建値床未発火")
			}
			if e := r.fillNight164(makeO(4, -20)); e != nil {
				t.Fatal(e)
			}
			if r.Actual.Realized != -2000 || r.Sides[side].Ready {
				t.Fatal("次板損失又は無条件再参加")
			}
		}
	}
}

// TestNight164RiskReservations は両側予約と返済待ちを危険上限へ含めます。
//
// 引数: t(*testing.T)。返り値: なし。
func TestNight164RiskReservations(t *testing.T) {
	r, _ := seedNightTest164(t, 2, 1, 80, 60)
	if r.riskUsed() != 48000 {
		t.Fatal("初期危険")
	}
	p := &NightParent164{Base: AllocationParent157{Key: "逆親", Owner: "PreUS", Side: -1, Campaign: 2}}
	r.Parents[p.Base.Key] = p
	o := quoteNightTest164(2, 102, 990, 1000)
	if q := r.reserveNight164(p, o, featuresNightTest164(o), "初回", 100, 60); q != 3 {
		t.Fatalf("両側危険 q%d", q)
	}
	old := r.Parents["人工親"]
	r.Actual.closeQuantity(&old.Base, o, "", "試験返済", 80, Support157{})
	if r.riskUsed() != 49800 {
		t.Fatal("返済予約で危険枠を先取り")
	}
}

// TestNight164OwnLotRisk は追加の固定Rと既存利益を相殺しない非負危険を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestNight164OwnLotRisk(t *testing.T) {
	r, p := seedNightTest164(t, 2, 1, 30, 40)
	o := quoteNightTest164(2, 120, 1100, 1110)
	r.Actual.mark(o)
	r.protectNight164(o, featuresNightTest164(o))
	if r.riskUsed() != 0 {
		t.Fatal("利益床の危険0下限")
	}
	if q := r.reserveNight164(p, o, featuresNightTest164(o), "順行追加", 70, 80); q != 62 {
		t.Fatalf("既得益が予算を拡大 q%d", q)
	}
	if e := r.fillNight164(quoteNightTest164(3, 121, 1150, 1160)); e != nil {
		t.Fatal(e)
	}
	last := r.Actual.Lots[r.Actual.Active[1]]
	g := r.Guards[last.ID]
	if last.Entry != 1160 || g.R != 80 || r.riskUsed() != 49600 {
		t.Fatal("追加の実建値と独自固定R")
	}
	if p.LastR != 80 {
		t.Fatal("次追加の間隔R")
	}
}

// TestNight164UnknownRearm は欠測を非正へ置換せず同時計で再準備しません。
//
// 引数: t(*testing.T)。返り値: なし。
func TestNight164UnknownRearm(t *testing.T) {
	r := newNight164(configsNight164()[2], Scene{Start: 0, USOpen: 10000, ForceClose: 20000})
	s := r.Sides[1]
	s.Ready = false
	s.FlatIndex = 0
	o := quoteNightTest164(1, 100, 1000, 1010)
	f := featuresNightTest164(o)
	f.Own15 = -10
	f.Path15 = false
	if e := r.stepNight164(o, f); e != nil {
		t.Fatal(e)
	}
	if s.Ready {
		t.Fatal("未知の再arm")
	}
	f.Path15 = true
	f.FirstNormal = false
	o.Index++
	r.stepNight164(o, f)
	if s.Ready {
		t.Fatal("同時計再arm")
	}
	f.FirstNormal = true
	o.Index++
	o.Time++
	r.stepNight164(o, f)
	if !s.Ready {
		t.Fatal("既知非正で再armしない")
	}
}

// TestNight164PatternNewExtreme は準備当行で遡及せず、新しい反発だけを予約します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestNight164PatternNewExtreme(t *testing.T) {
	for _, side := range []int{1, -1} {
		r := newNight164(configsNight164()[2], Scene{Start: 0, USOpen: 10000, ForceClose: 20000})
		for i, x := range []float64{1000, 980, 1000} {
			mid := x
			if side < 0 {
				mid = 2000 - x
			}
			o := quoteNightTest164(int64(i), 100+float64(i), mid-5, mid+5)
			f := featuresNightTest164(o)
			f.High60 = 1060
			f.Low60 = 940
			f.Own5 *= float64(side)
			f.Own15 *= float64(side)
			if e := r.stepNight164(o, f); e != nil {
				t.Fatal(e)
			}
			if i < 2 && len(r.Actual.Pending) > 0 {
				t.Fatal("準備前の反発採用")
			}
		}
		if len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Side != side {
			t.Fatalf("新極値反発未発火 side%d %+v", side, r.Trace)
		}
	}
}

// TestNight164ProfitReentry は利益返済後の新価格だけで再参加準備を作ります。
//
// 引数: t(*testing.T)。返り値: なし。
func TestNight164ProfitReentry(t *testing.T) {
	r, _ := seedNightTest164(t, 3, 1, 10, 40)
	o := quoteNightTest164(2, 110, 1060, 1070)
	r.Actual.mark(o)
	r.protectNight164(o, featuresNightTest164(o))
	o = quoteNightTest164(3, 111, 1020, 1030)
	r.Actual.mark(o)
	r.protectNight164(o, featuresNightTest164(o))
	o = quoteNightTest164(4, 112, 1020, 1030)
	if e := r.fillNight164(o); e != nil {
		t.Fatal(e)
	}
	s := r.Sides[1]
	if !s.ProfitSeed || s.Ready {
		t.Fatal("利益返済専用再参加権")
	}
	for i, mid := range []float64{1025, 1005, 1015} {
		o = quoteNightTest164(int64(5+i), 122+float64(i), mid-5, mid+5)
		f := featuresNightTest164(o)
		if e := r.stepNight164(o, f); e != nil {
			t.Fatal(e)
		}
		if i < 2 && len(r.Actual.Pending) > 0 {
			t.Fatal("再参加に新価格不足")
		}
	}
	if len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Kind != "利益後再参加" {
		t.Fatalf("再参加しない %+v", r.Trace)
	}
	if g := r.PendingRisk[r.Actual.Pending[0].ID]; g.Floor != -40 || g.Active {
		t.Fatal("旧保護床継承")
	}
}

// TestNight164NativeMapping はP05親補完とmicro十倍の通知・配賦を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestNight164NativeMapping(t *testing.T) {
	scene := Scene{Start: 0, USOpen: 10000, ForceClose: 20000}
	r := newNight164(configsNight164()[0], scene)
	src := &SourceStateNative164{Phase: "前半", Method: "P05", Lots: map[string]*SourceLotNative164{}}
	sig := strategy.Signal{ID: "a", Owner: "core", Action: "new", Side: 1, Quantity: 5, Time: 100, SourceIndex: 0, Campaign: 7}
	r.nativeStepNight164(quoteNightTest164(0, 100, 990, 1000), []strategy.Signal{namespaceNative164(sig, "前半")})
	r.nativeStepNight164(quoteNightTest164(1, 101, 990, 1000), nil)
	src.Lots["a-玉"] = &SourceLotNative164{ID: "a-玉", Owner: "core", Campaign: 7, Side: 1, Quantity: 5, Entry: 1000, Remaining: 0}
	src.Events = append(src.Events, SourceEventNative164{Phase: "前半", Signal: sig, FillIndex: 1, FillTime: 101, Price: 1000})
	close := strategy.Signal{ID: "b", Owner: "core", Action: "close", Side: -1, Quantity: 5, Time: 102, SourceIndex: 2, Targets: []strategy.LotTarget{{ID: "a-玉", Quantity: 5}}}
	mapped, e := src.policySignalNative164(close)
	if e != nil || mapped.Campaign != 7 {
		t.Fatal("P05元親補完")
	}
	r.nativeStepNight164(quoteNightTest164(2, 102, 1040, 1050), []strategy.Signal{namespaceNative164(mapped, "前半")})
	r.nativeStepNight164(quoteNightTest164(3, 103, 1050, 1060), nil)
	src.Events = append(src.Events, SourceEventNative164{Phase: "前半", Signal: close, FillIndex: 3, FillTime: 103, Price: 1050, Gross: 25000})
	src.Gross = 25000
	saved := SavedNight164{Scene: scene, Cases: []*NightResult164{r}, Sources: []*SourceStateNative164{src}}
	if e = verifyNative164(&saved); e != nil {
		t.Fatal(e)
	}
	if saved.ExactChecks != 2 {
		t.Fatal("照合件数")
	}
}

// TestNight164FixedIdentity は8IDの区分と規則指紋を人工で確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestNight164FixedIdentity(t *testing.T) {
	seen := map[string]bool{}
	for _, c := range configsNight164() {
		if seen[c.ID] || len(c.RuleHash) != 64 {
			t.Fatal("ID重複又は指紋不足")
		}
		seen[c.ID] = true
		raw, e := json.Marshal(c)
		if e != nil || len(raw) == 0 {
			t.Fatal(e)
		}
	}
	r, ok := riskNight164(NightFeatures164{Known300: true, Spread: 30, Range300: 330}, "PostUS")
	if !ok || math.Abs(r-90) > 1e-9 {
		t.Fatal("R切上げ")
	}
}
