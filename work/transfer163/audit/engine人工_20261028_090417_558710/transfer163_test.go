package main

import (
	"encoding/json"
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

// chosen163 は人工に使う固定候補をIDから選びます。
//
// 引数: id(string)。返り値: Policy163。実データは読みません。
func chosen163(id string) Policy163 {
	for _, c := range configs163() {
		if c.ID == id {
			return c
		}
	}
	panic("人工の候補なし")
}

// short163 は人工的な既知の短期円幅を作ります。
//
// 引数: five/fifteen(float64)。返り値: Short163。
func short163(five, fifteen float64) Short163 {
	return Short163{Own5: ShortWindow163{Known: true, Points: five}, Own15: ShortWindow163{Known: true, Points: fifteen}}
}

// observation163 は中値と気配差を指定した人工のラージ板を作ります。
//
// 引数: i(int64)、mid(float64)。返り値: strategy.Observation。
func observation163(i int64, mid float64) strategy.Observation {
	return quote159(i, 100+float64(i), mid-5, mid+5)
}

// newSignal163 は実約定より前の元Source新規判断を作ります。
//
// 引数: id(string)、side/q(int)、o(Observation)。返り値: Signal。
func newSignal163(id string, side, q int, o strategy.Observation) strategy.Signal {
	return strategy.Signal{ID: id, Owner: "日中/core", Campaign: 1, Side: side, Quantity: q, Action: "new", SourceIndex: o.Index, Time: o.Time}
}

// closeSignal163 は一つの元SourceIDの返済を作ります。
//
// 引数: id/source(string)、side/q(int)、o(Observation)。返り値: Signal。
func closeSignal163(id, source string, side, q int, o strategy.Observation) strategy.Signal {
	return strategy.Signal{ID: id, Owner: "日中/core", Campaign: 1, Side: -side, Quantity: q, Action: "close", SourceIndex: o.Index, Time: o.Time, Targets: []strategy.LotTarget{{ID: source + "-玉", Quantity: q}}}
}

// seed163 は初回五枚を判断し、次の人工板で約定させます。
//
// 引数: t(*testing.T)、id(string)、side(int)。返り値: 数量台帳と親。
func seed163(t *testing.T, id string, side int) (*TransferResult163, *TransferParent163) {
	t.Helper()
	r := newTransfer163(chosen163(id), Scene{Start: 100})
	o := observation163(0, 1000)
	if e := r.stepTransfer163(o, []strategy.Signal{newSignal163("first", side, 5, o)}, Short163{}, true); e != nil {
		t.Fatal(e)
	}
	if len(r.Actual.Events) != 0 {
		t.Fatal("同原行約定")
	}
	if e := r.stepTransfer163(observation163(1, 1000), nil, Short163{}, true); e != nil {
		t.Fatal(e)
	}
	return r, r.Parents["日中/core/1"]
}

// TestShortYenEndpoint163 は円換算・端点包含・一秒許容・現板不正を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestShortYenEndpoint163(t *testing.T) {
	b := &ShortBuilder163{}
	for i := int64(0); i <= 20; i++ {
		o := observation163(i, 1000+float64(i)*2)
		b.add(o)
	}
	s := b.get()
	if !s.Own5.Known || s.Own5.Points != 10 || s.Own15.Points != 30 || s.Own5.EndpointAt != 115 {
		t.Fatalf("円又は端点:%+v", s)
	}
	c := &ShortBuilder163{}
	c.add(quote159(0, 100, 995, 1005))
	c.add(quote159(1, 106, 1007, 1017))
	if w := c.window(5); !w.Known || w.Delay != 1 || w.Points != 10 {
		t.Fatalf("端点1秒境界:%+v", w)
	}
	c.add(quote159(2, 106.01, 1007, 1017))
	if c.window(5).Known {
		t.Fatal("遅れ1秒超を既知")
	}
	x := observation163(30, 1000)
	x.QuoteOK = false
	b.add(x)
	if b.get().Own5.Known {
		t.Fatal("現在不正を既知")
	}
}

// TestReductionRestorationChain163 は買売鏡像で減枚・約定・極値・復元・元部分終了を連鎖させます。
//
// 引数: t(*testing.T)。返り値: なし。実建値や約定の未来補正はありません。
func TestReductionRestorationChain163(t *testing.T) {
	for _, side := range []int{1, -1} {
		r, p := seed163(t, "R40", side)
		d := float64(side)
		step := func(i int64, mid float64, sigs []strategy.Signal, s Short163) {
			t.Helper()
			if e := r.stepTransfer163(observation163(i, mid), sigs, s, true); e != nil {
				t.Fatal(e)
			}
		}
		step(2, 1000-d*40, nil, short163(-d*10, -d*20))
		if !p.Reduced || len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Quantity != 25 {
			t.Fatal("半量予約不足")
		}
		step(3, 1000-d*70, nil, short163(d*10, d*30))
		if p.ReductionFillIndex != 3 || p.ExtremeMid != 1000-d*70 || p.Restored {
			t.Fatal("減枚fill起点又は同原行復元")
		}
		step(4, 1000-d*90, nil, Short163{})
		step(5, 1000-d*50, nil, short163(d*10, d*30))
		if !p.Restored || len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Quantity != 25 {
			t.Fatal("未知期間の極値又は復元量")
		}
		step(6, 1000-d*30, nil, Short163{})
		if p.AnchorMid != 1000 {
			t.Fatal("復元でanchor変更")
		}
		o := observation163(7, 1000)
		step(7, 1000, []strategy.Signal{closeSignal163("partial", "first", side, 2, o)}, Short163{})
		if len(r.Actual.Pending) != 1 || r.Actual.Pending[0].Quantity != 20 {
			t.Fatal("復元後Source部分量")
		}
		step(8, 1000, nil, Short163{})
		held, _, _ := r.sourceHeld163(p, "first")
		if held != 30 || p.SourceMini["first"] != 3 {
			t.Fatal("Source別残数")
		}
		o = observation163(9, 1000)
		step(9, 1000, []strategy.Signal{closeSignal163("final", "first", side, 3, o)}, Short163{})
		step(10, 1000, nil, Short163{})
		if !p.Ended || len(r.Actual.Active) != 0 {
			t.Fatal("元終了で未返済")
		}
		if r.MaxReservedLong > 100 || r.MaxReservedShort > 100 {
			t.Fatal("予約枠")
		}
	}
}

// TestMissingAndEntryRestore163 は未知をゼロ扱いせず、RとEの回復条件を分けます。
//
// 引数: t(*testing.T)。返り値: なし。
func TestMissingAndEntryRestore163(t *testing.T) {
	g, p := seed163(t, "G40", 1)
	if e := g.stepTransfer163(observation163(2, 900), nil, Short163{}, true); e != nil {
		t.Fatal(e)
	}
	if p.Reduced {
		t.Fatal("未知でG発火")
	}
	d, dp := seed163(t, "D40", 1)
	_ = d.stepTransfer163(observation163(2, 960), nil, Short163{}, true)
	if !dp.Reduced {
		t.Fatal("Dが短期要求")
	}
	e, ep := seed163(t, "E40", 1)
	_ = e.stepTransfer163(observation163(2, 960), nil, short163(-1, -20), true)
	_ = e.stepTransfer163(observation163(3, 900), nil, Short163{}, true)
	_ = e.stepTransfer163(observation163(4, 940), nil, short163(1, 2), true)
	if ep.Restored {
		t.Fatal("Eが極値だけで復元")
	}
	_ = e.stepTransfer163(observation163(5, 1000), nil, short163(1, 2), false)
	if ep.Restored {
		t.Fatal("境界で復元")
	}
	_ = e.stepTransfer163(observation163(6, 1000), nil, short163(1, 2), true)
	if !ep.Restored {
		t.Fatal("E初回mid未判定")
	}
}

// TestReducedSourceAddAndEndedID163 は縮小後元追加の半量、SourceID終了、後続同親を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestReducedSourceAddAndEndedID163(t *testing.T) {
	r, p := seed163(t, "R40", 1)
	_ = r.stepTransfer163(observation163(2, 960), nil, short163(-1, -20), true)
	_ = r.stepTransfer163(observation163(3, 950), nil, Short163{}, true)
	o := observation163(4, 900)
	if e := r.stepTransfer163(o, []strategy.Signal{newSignal163("second", 1, 2, o)}, Short163{}, true); e != nil {
		t.Fatal(e)
	}
	if r.Actual.Pending[0].Quantity != 10 {
		t.Fatal("縮小中追加が半量でない")
	}
	o = observation163(5, 900)
	if e := r.stepTransfer163(o, []strategy.Signal{closeSignal163("endfirst", "first", 1, 5, o)}, short163(20, 40), true); e != nil {
		t.Fatal(e)
	}
	if p.Restored {
		t.Fatal("元返済予約中復元")
	}
	if e := r.stepTransfer163(observation163(6, 950), nil, short163(20, 40), true); e != nil {
		t.Fatal(e)
	}
	if !p.Restored || len(r.Actual.Pending) != 1 || r.Actual.Pending[0].SourceID != "second" || r.Actual.Pending[0].Quantity != 10 {
		t.Fatal("終了SourceID復活又は量不整合")
	}
	_ = r.stepTransfer163(observation163(7, 950), nil, Short163{}, true)
	o = observation163(8, 950)
	_ = r.stepTransfer163(o, []strategy.Signal{closeSignal163("endsecond", "second", 1, 2, o)}, Short163{}, true)
	_ = r.stepTransfer163(observation163(9, 950), nil, Short163{}, true)
	if !p.Ended {
		t.Fatal("Source全終了不明")
	}
	o = observation163(10, 950)
	if e := r.stepTransfer163(o, []strategy.Signal{newSignal163("third", 1, 1, o)}, Short163{}, true); e != nil {
		t.Fatal(e)
	}
	if p.Ended || !p.Restored || !p.Reduced || p.AnchorMid != 1000 {
		t.Fatal("同親再開が権又はanchorをリセット")
	}
	_ = r.stepTransfer163(observation163(11, 850), nil, short163(-20, -60), true)
	if len(r.Actual.Pending) > 0 {
		t.Fatal("減枚二回")
	}
	o = observation163(12, 850)
	if r.stepTransfer163(o, []strategy.Signal{newSignal163("reverse", -1, 1, o)}, Short163{}, true) == nil {
		t.Fatal("同親逆方向未検出")
	}
}

// TestSourceExitPriorityGapCap163 は元終了優先・異常板保留・次板飛び・共有予約を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestSourceExitPriorityGapCap163(t *testing.T) {
	r, p := seed163(t, "R40", 1)
	o := observation163(2, 960)
	if e := r.stepTransfer163(o, []strategy.Signal{closeSignal163("exit", "first", 1, 5, o)}, short163(-10, -30), true); e != nil {
		t.Fatal(e)
	}
	if p.Reduced || len(r.Actual.Pending) != 1 {
		t.Fatal("元全返済と減枚競合")
	}
	bad := observation163(3, 800)
	bad.QuoteOK = false
	_ = r.stepTransfer163(bad, nil, Short163{}, true)
	if len(r.Actual.Pending) != 1 {
		t.Fatal("異常板で約定")
	}
	_ = r.stepTransfer163(observation163(4, 700), nil, Short163{}, true)
	if r.Actual.Events[1].Price != 695 || r.Actual.Realized != -155000 {
		t.Fatal("次板飛び損失を置換")
	}
	b, _ := seed163(t, "B00", 1)
	o = observation163(2, 1000)
	sig := newSignal163("other", 1, 5, o)
	sig.Owner = "日中/addon"
	if e := b.stepTransfer163(o, []strategy.Signal{sig}, Short163{}, true); e != nil {
		t.Fatal(e)
	}
	if b.MaxReservedLong != 100 {
		t.Fatal("予約上限計数")
	}
	sig.ID = "over"
	sig.Owner = "日中/episode"
	sig.Quantity = 1
	if b.sourceSignals163(o, []strategy.Signal{sig}) == nil {
		t.Fatal("共有枠超過未拒否")
	}
}

// TestBaselineAndHalfExact163 は二Source玉の部分返済を含む元全経路と半量を検査します。
//
// 引数: t(*testing.T)。返り値: なし。源約定は人工通知の次正常価格から独立作成します。
func TestBaselineAndHalfExact163(t *testing.T) {
	result := Saved163{Scene: Scene{Session: "人工_Day", Kind: "Day", Start: 100}}
	for _, c := range configs163() {
		result.Cases = append(result.Cases, newTransfer163(c, result.Scene))
	}
	s := &SourceState159{Phase: "日中", Lots: map[string]*SourceLot159{}}
	result.Sources = []*SourceState159{s}
	batches := map[int64][]strategy.Signal{}
	for _, i := range []int64{0, 2} {
		o := observation163(i, 1000)
		id, q := "first", 5
		if i == 2 {
			id, q = "second", 2
		}
		batches[i] = []strategy.Signal{newSignal163(id, 1, q, o)}
	}
	batches[4] = []strategy.Signal{closeSignal163("partial", "first", 1, 2, observation163(4, 1000))}
	batches[6] = []strategy.Signal{closeSignal163("final1", "first", 1, 3, observation163(6, 1000)), closeSignal163("final2", "second", 1, 2, observation163(6, 1000))}
	for i, sigs := range batches {
		for j := range sigs {
			sigs[j].Owner = "core"
			sigs[j] = namespace159(sigs[j], "日中")
		}
		batches[i] = sigs
	}
	pending := []strategy.Signal{}
	for i := int64(0); i < 9; i++ {
		o := observation163(i, 1000+float64(i)*2)
		for _, sig := range pending {
			price := o.Bid
			if sig.Side > 0 {
				price = o.Ask
			}
			gross := 0.
			if sig.Action == "new" {
				s.Lots[sig.ID+"-玉"] = &SourceLot159{Owner: "日中/core", Campaign: 1, Side: 1, Remaining: sig.Quantity, Entry: price}
			} else {
				for _, tg := range sig.Targets {
					l := s.Lots[tg.ID]
					gross += (price - l.Entry) * float64(tg.Quantity) * 100
					l.Remaining -= tg.Quantity
				}
			}
			s.Gross += gross
			s.Events = append(s.Events, SourceEvent159{Phase: "", Signal: sig, FillIndex: i, FillTime: o.Time, Price: price, Gross: gross})
		}
		pending = batches[i]
		for _, r := range result.Cases {
			if e := r.stepTransfer163(o, batches[i], short163(1, 1), true); e != nil {
				t.Fatal(e)
			}
		}
	}
	// 元Sourceは時間枠を持たないIDを保存するため、人工の名前空間だけ先に外します。
	for i := range s.Events {
		e := &s.Events[i]
		e.Phase = "日中"
		e.Signal.Owner = "core"
		e.Signal.ID = strings.TrimPrefix(e.Signal.ID, "日中/")
		old := e.Signal.Targets
		e.Signal.Targets = append([]strategy.LotTarget(nil), old...)
		for j := range e.Signal.Targets {
			e.Signal.Targets[j].ID = strings.TrimPrefix(e.Signal.Targets[j].ID, "日中/")
		}
	}
	oldLots := s.Lots
	s.Lots = map[string]*SourceLot159{}
	for id, l := range oldLots {
		l.Owner = "core"
		s.Lots[strings.TrimPrefix(id, "日中/")] = l
	}
	if e := verify163(&result); e != nil {
		t.Fatal(e)
	}
	base, half := result.Cases[0].Actual, result.Cases[1].Actual
	if len(base.Events) != 5 || base.Realized != s.Gross || half.Realized*2 != base.Realized || half.Risk.Minimum*2 != base.Risk.Minimum || half.Risk.MaxDD*2 != base.Risk.MaxDD {
		t.Fatal("対照会計", len(base.Events), base.Realized, s.Gross)
	}
	for i, e := range base.Events {
		h := half.Events[i]
		if h.Order.ID != e.Order.ID || h.Order.Quantity*2 != e.Order.Quantity || h.Price != e.Price || h.FillIndex != e.FillIndex || h.Gross*2 != e.Gross {
			t.Fatal("半量経路")
		}
		for j, p := range e.Pieces {
			if h.Pieces[j].Quantity*2 != p.Quantity || h.Pieces[j].Gross*2 != p.Gross {
				t.Fatal("半量配賦")
			}
		}
	}
	if os.Getenv("EXPORT_SYNTHETIC163") != "" {
		p := os.Getenv("EXPORT_SYNTHETIC163")
		if e := save159(p, result); e != nil {
			t.Fatal(e)
		}
	}
}

// artificialScene163 は無方向の二市場原板と足を一時領域に作ります。
//
// 引数: t(*testing.T)、kind(string)。返り値: Scene。実資料は読みません。
func artificialScene163(t *testing.T, kind string) Scene {
	t.Helper()
	dir := t.TempDir()
	start := 1700000000.
	s := Scene{Session: "人工_" + kind, Kind: kind, Start: start, USOpen: start + 7200, ForceClose: start + 17400, End: start + 18000, Books: map[string]string{}, Candles: map[string]map[string]string{}}
	for _, ref := range []string{"NK225", "TOPIX"} {
		path := filepath.Join(dir, ref+".jsonl")
		f, e := os.Create(path)
		if e != nil {
			t.Fatal(e)
		}
		for second := 0; second <= 18000; second += 30 {
			at := time.Unix(int64(start)+int64(second), 0).UTC().Format(time.RFC3339)
			price := 10000.
			if ref == "TOPIX" {
				price = 4000
			}
			v := map[string]any{"CurrentPriceTime": at, "CurrentPrice": price, "Buy1": map[string]float64{"Price": price - 5, "Qty": 100}, "Sell1": map[string]float64{"Price": price + 5, "Qty": 100}}
			if e = json.NewEncoder(f).Encode(v); e != nil {
				t.Fatal(e)
			}
		}
		f.Close()
		s.Books[ref] = path
		s.Candles[ref] = map[string]string{}
		for _, interval := range []string{"60", "300"} {
			p := filepath.Join(dir, ref+interval+".json")
			if e = os.WriteFile(p, []byte(`{"Data":[]}`), 0600); e != nil {
				t.Fatal(e)
			}
			s.Candles[ref][interval] = p
		}
	}
	return s
}

// TestNativeSourceAndParallel163 は人工の昼夜で元Source不変と並列の完全同値を検査します。
//
// 引数: t(*testing.T)。返り値: なし。この人工は時間枠検査であり売買有効性の証拠にしません。
func TestNativeSourceAndParallel163(t *testing.T) {
	sets, e := rules163("rules")
	if e != nil {
		t.Fatal(e)
	}
	scenes := []Scene{artificialScene163(t, "Day"), artificialScene163(t, "Night")}
	for _, s := range scenes {
		got, e := run163(s, configs163(), sets)
		if e != nil {
			t.Fatal(e)
		}
		old, e := run159(s, configs159(), sets)
		if e != nil {
			t.Fatal(e)
		}
		if len(got.Sources) != len(old.Sources) || !reflect.DeepEqual(got.Transitions, old.Transitions) {
			t.Fatal("元時間枠差")
		}
		a, _ := json.Marshal(got.Sources)
		b, _ := json.Marshal(old.Sources)
		if string(a) != string(b) {
			t.Fatal("元Source差")
		}
	}
	a, b := t.TempDir(), t.TempDir()
	if _, e = execute163(scenes, configs163(), sets, a, 1); e != nil {
		t.Fatal(e)
	}
	if _, e = execute163(scenes, configs163(), sets, b, 8); e != nil {
		t.Fatal(e)
	}
	for _, s := range scenes {
		x, _ := os.ReadFile(filepath.Join(a, s.Session+".json"))
		y, _ := os.ReadFile(filepath.Join(b, s.Session+".json"))
		if string(x) != string(y) {
			t.Fatal("並列同値差")
		}
	}
}

// TestInitialAnchorIsMid163 はspreadを逆行へ誤算入せず初回実約定中値を固定します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestInitialAnchorIsMid163(t *testing.T) {
	r := newTransfer163(chosen163("D40"), Scene{Start: 100})
	o := quote159(0, 100, 950, 1050)
	sig := newSignal163("first", 1, 5, o)
	if e := r.stepTransfer163(o, []strategy.Signal{sig}, Short163{}, true); e != nil {
		t.Fatal(e)
	}
	o.Index = 1
	o.Time = 101
	if e := r.stepTransfer163(o, nil, Short163{}, true); e != nil {
		t.Fatal(e)
	}
	p := r.Parents["日中/core/1"]
	if p.AnchorMid != 1000 || p.Reduced || math.Abs(r.Actual.Last.Unrealized+50000) > 1e-8 {
		t.Fatal("建値又はspreadをmidに混ぜた")
	}
}
