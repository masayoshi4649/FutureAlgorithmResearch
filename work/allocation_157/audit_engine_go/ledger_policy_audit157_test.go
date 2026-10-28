package main

import (
	"math"
	"testing"

	"futurealgorithm/sessiontrader/internal/strategy"
)

// auditObservation157 は実データを使わず正常な判断板を作ります。
//
// 引数: at/bid(float64)、index(int64)。返り値: strategy.Observation。
func auditObservation157(at, bid float64, index int64) strategy.Observation {
	return strategy.Observation{Time: at, Index: index, Bid: bid, Ask: bid + 10, QuoteOK: true, Reference: "NK225"}
}

// auditPolicy157 は固定候補を人工の長い日中セッションに設定します。
//
// 引数: id(string)。返り値: *PolicyResult157。不明IDはpanicします。
func auditPolicy157(id string) *PolicyResult157 {
	for _, cfg := range configs157() {
		if cfg.ID == id {
			return newPolicy157(cfg, Scene{Session: "人工_Day", Kind: "Day", Start: 1000, End: 10000, ForceClose: 9900})
		}
	}
	panic("人工候補不明")
}

// auditSupports157 は買い方向に既知支持を持つ人工状態を返します。
//
// 引数: m/value(float64)。返り値: map[int]Support157。
func auditSupports157(m, value float64) map[int]Support157 {
	return map[int]Support157{1: {Known: true, M: m, T: value, Own5: 1, Own15: 2}, -1: {Known: true, M: 0, T: 0, Opp: value, Own5: 1, Own15: 2}}
}

// auditSourceNew157 は旧Sourceの初回又は追加通知を作ります。
//
// 引数: id(string)、q(int)、o(Observation)。返り値: strategy.Signal。
func auditSourceNew157(id string, q int, o strategy.Observation) strategy.Signal {
	return strategy.Signal{ID: id, Action: "new", Owner: "core", Campaign: 0, Side: 1, Quantity: q, SourceIndex: o.Index}
}

// TestAuditReservationAndOwnership157 は予約上限・返済予定枠・所有IDを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditReservationAndOwnership157(t *testing.T) {
	b := newLedger157("人工", 1000)
	p := &AllocationParent157{Key: "core/0", Owner: "core", Side: 1}
	o := auditObservation157(1001, 64000, 1)
	if b.open(p, o, "initial", "人工", 1, 60, Support157{}) != 60 || b.open(p, o, "source_add", "人工", 1, 60, Support157{}) != 40 || b.capacity(1) != 0 {
		t.Fatal("新規予約込み上限が不一致")
	}
	if _, err := b.fill(o); err == nil {
		t.Fatal("判断と同じ原行で約定")
	}
	o = auditObservation157(1002, 64000, 2)
	if _, err := b.fill(o); err != nil {
		t.Fatal(err)
	}
	b.closeLot(p, o, b.Active[0], "人工部分", 20, Support157{})
	if b.capacity(1) != 0 {
		t.Fatal("返済未確定なのに枠が解放")
	}
	if _, err := b.fill(auditObservation157(1003, 64000, 3)); err != nil || b.capacity(1) != 20 {
		t.Fatalf("実返済後の枠: %v %d", err, b.capacity(1))
	}
	other := &AllocationParent157{Key: "episode/9", Owner: "episode", Side: 1}
	b.closeLot(other, auditObservation157(1004, 64000, 4), b.Active[0], "外部玉", 1, Support157{})
	if _, err := b.fill(auditObservation157(1005, 64000, 5)); err == nil {
		t.Fatal("別親の所有玉を返済できた")
	}
}

// TestAuditMarkBeforeAfterFill157 は新規前の時間を保有に算入しないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditMarkBeforeAfterFill157(t *testing.T) {
	b := newLedger157("時価", 1000)
	p := &AllocationParent157{Key: "core/0", Owner: "core", Side: 1}
	if b.Risk.PeakAt.Time != 1000 || b.Risk.PeakAt.Index != -1 {
		t.Fatal("初期0円の山が場開始でない")
	}
	b.open(p, auditObservation157(1001, 64000, 1), "initial", "人工", 1, 50, Support157{})
	o := auditObservation157(1010, 64000, 2)
	b.mark(o)
	if _, err := b.fill(o); err != nil {
		t.Fatal(err)
	}
	b.mark(o)
	b.closeLot(p, auditObservation157(1011, 64000, 3), b.Active[0], "人工", 50, Support157{})
	o = auditObservation157(1020, 64050, 4)
	b.mark(o)
	if _, err := b.fill(o); err != nil {
		t.Fatal(err)
	}
	b.mark(o)
	if b.Risk.HeldSeconds != 10 || b.Risk.GrossSeconds != 500 || b.Realized != 20000 || b.Events[1].Pieces[0].Best != 40 {
		t.Fatalf("時間又は返済原行の順行: %+v %+v", b.Risk, b.Events)
	}
}

// TestAuditRejectedParentNeverPickedLater157 は低支持の初回拒否を後追い解除しません。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditRejectedParentNeverPickedLater157(t *testing.T) {
	r := auditPolicy157("Q01")
	o := auditObservation157(1001, 64000, 1)
	r.source157(o, []strategy.Signal{auditSourceNew157("初回", 5, o)}, auditSupports157(.1, .1))
	o = auditObservation157(1100, 64050, 2)
	r.source157(o, []strategy.Signal{auditSourceNew157("後続", 1, o)}, auditSupports157(1, 1))
	if len(r.Canonical.Pending) != 0 || r.Parents["core/0"].Rejected == "" {
		t.Fatal("拒否親を後の強支持で拾い直した")
	}
}

// TestAuditInitialFactorAndSourceAdd157 は支持数量の初回係数を後続Source追加へ維持します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditInitialFactorAndSourceAdd157(t *testing.T) {
	r := auditPolicy157("B01")
	o := auditObservation157(1001, 64000, 1)
	if err := step157(r, o, []strategy.Signal{auditSourceNew157("初回", 5, o)}, auditSupports157(.8, .5)); err != nil {
		t.Fatal(err)
	}
	if r.Canonical.Pending[0].Quantity != 40 || r.Parents["core/0"].Factor != .8 {
		t.Fatal("初回量係数不一致")
	}
	if err := step157(r, auditObservation157(1002, 64000, 2), nil, auditSupports157(1, 1)); err != nil {
		t.Fatal(err)
	}
	o = auditObservation157(1030, 64020, 3)
	if err := step157(r, o, []strategy.Signal{auditSourceNew157("追加", 1, o)}, auditSupports157(1, 1)); err != nil {
		t.Fatal(err)
	}
	if len(r.Canonical.Pending) != 1 || r.Canonical.Pending[0].Quantity != 8 {
		t.Fatalf("後の支持で初回係数を変更: %+v", r.Canonical.Pending)
	}
}

// TestAuditSessionLimitBeforeNew157 は当行の場停止を新規より先に適用します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditSessionLimitBeforeNew157(t *testing.T) {
	r := auditPolicy157("D05")
	r.Canonical.Realized = -160000
	o := auditObservation157(1001, 64000, 1)
	if err := step157(r, o, []strategy.Signal{auditSourceNew157("初回", 5, o)}, auditSupports157(1, 1)); err != nil {
		t.Fatal(err)
	}
	if !r.Stopped || len(r.Canonical.Pending) != 0 || len(r.Actual.Pending) != 0 {
		t.Fatalf("当行停止より先に新規: %+v", r.Canonical.Pending)
	}
	for _, x := range []struct{ eq, scale float64 }{{0, 1}, {-80000, 1}, {-120000, .5}, {-160000, 0}} {
		r.Canonical.Last.Equity = x.eq
		if math.Abs(r.scale157()-x.scale) > 1e-12 {
			t.Fatal("場開始比線形抑制の基準違い")
		}
	}
}

// TestAuditStopBeforeSourceAdd157 は玉の停止が同原行のSource追加を抑止します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditStopBeforeSourceAdd157(t *testing.T) {
	r := auditPolicy157("C01")
	o := auditObservation157(1001, 64000, 1)
	if err := step157(r, o, []strategy.Signal{auditSourceNew157("初回", 5, o)}, auditSupports157(1, 1)); err != nil {
		t.Fatal(err)
	}
	if err := step157(r, auditObservation157(1002, 64000, 2), nil, auditSupports157(1, 1)); err != nil {
		t.Fatal(err)
	}
	o = auditObservation157(1020, 63930, 3)
	if err := step157(r, o, []strategy.Signal{auditSourceNew157("追加", 1, o)}, auditSupports157(1, 1)); err != nil {
		t.Fatal(err)
	}
	if len(r.Canonical.Pending) == 0 {
		t.Fatal("80pt停止なし")
	}
	for _, order := range r.Canonical.Pending {
		if len(order.Targets) == 0 {
			t.Fatalf("停止当行に新規: %+v", order)
		}
	}
}

// TestAuditAdverseExtremeWhileOppositeSupport157 は反対支持・10秒内の底も追跡します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditAdverseExtremeWhileOppositeSupport157(t *testing.T) {
	r := auditPolicy157("Q08")
	o := auditObservation157(1001, 64000, 1)
	if err := step157(r, o, []strategy.Signal{auditSourceNew157("初回", 5, o)}, auditSupports157(.8, .5)); err != nil {
		t.Fatal(err)
	}
	if err := step157(r, auditObservation157(1002, 64000, 2), nil, auditSupports157(.8, .5)); err != nil {
		t.Fatal(err)
	}
	opposite := map[int]Support157{1: {Known: true, M: 1, Opp: 1, Own5: -1, Own15: -2}, -1: {Known: true, T: 1, Own5: -1, Own15: -2}}
	if err := step157(r, auditObservation157(1003, 63970, 3), nil, opposite); err != nil {
		t.Fatal(err)
	}
	p := r.Parents["core/0"]
	if p.Extreme != 63970 || !p.AdverseReady || len(r.Canonical.Pending) != 0 {
		t.Fatal("短期逆方向中の底を捨てた又は早期注文")
	}
	if err := step157(r, auditObservation157(1014, 63990, 4), nil, auditSupports157(1, 1)); err != nil {
		t.Fatal(err)
	}
	if len(r.Canonical.Pending) != 1 || r.Canonical.Pending[0].Kind != "adverse" || r.Canonical.Pending[0].Quantity != 25 {
		t.Fatalf("20反発での限定追加がない: %+v", r.Canonical.Pending)
	}
	if err := step157(r, auditObservation157(1015, 63990, 5), nil, auditSupports157(1, 1)); err != nil {
		t.Fatal(err)
	}
	if p.AdverseUsed != 25 {
		t.Fatal("実約定の逆行追加累計が違う")
	}
}

// TestAuditParentNetHedgeIdentity157 は同じ親の両建てと純量投影の会計差を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditParentNetHedgeIdentity157(t *testing.T) {
	r := auditPolicy157("Q05")
	p := &AllocationParent157{Key: "core/0", Owner: "core", Side: 1, SourceQty: 50}
	r.Parents[p.Key] = p
	fill := func(o strategy.Observation) {
		r.Canonical.mark(o)
		r.Actual.mark(o)
		if _, err := r.Canonical.fill(o); err != nil {
			t.Fatal(err)
		}
		if _, err := r.Actual.fill(o); err != nil {
			t.Fatal(err)
		}
		r.Canonical.mark(o)
		r.Actual.mark(o)
	}
	o := auditObservation157(1001, 64000, 1)
	r.Canonical.open(p, o, "initial", "初回", 1, 10, Support157{})
	r.project157(o)
	fill(auditObservation157(1002, 64000, 2))
	o = auditObservation157(1003, 63990, 3)
	r.Canonical.open(p, o, "cover", "カバー", -1, 3, Support157{})
	r.project157(o)
	fill(auditObservation157(1004, 63990, 4))
	cl, cs := r.Canonical.position(p.Key, "")
	al, as := r.Actual.position(p.Key, "")
	if cl != 10 || cs != 3 || al != 7 || as != 0 {
		t.Fatal("親内純量の写像が違う")
	}
	if r.Canonical.Last.MidEquity != r.Actual.Last.MidEquity || r.Canonical.Last.Equity-r.Actual.Last.Equity != -300 {
		t.Fatal("同現金・同純量のBBO重複差不一致")
	}
	o = auditObservation157(1005, 63990, 5)
	r.Canonical.closeQuantity(p, o, "", "場末", 1000, Support157{})
	r.project157(o)
	fill(auditObservation157(1006, 63990, 6))
	if len(r.Canonical.Active) != 0 || len(r.Actual.Active) != 0 || r.Canonical.Realized-r.Actual.Realized != -300 {
		t.Fatal("純相殺した終端往復の差不一致")
	}
}

// TestAuditCoverClosesWhenBaseFlat157 は元玉0で逆玉だけを放置しないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditCoverClosesWhenBaseFlat157(t *testing.T) {
	r := auditPolicy157("H05")
	p := &AllocationParent157{Key: "core/0", Owner: "core", Side: 1, SourceQty: 50, OldInitial: 50}
	r.Parents[p.Key] = p
	o := auditObservation157(1001, 64000, 1)
	r.Canonical.open(p, o, "cover", "人工残カバー", -1, 3, Support157{})
	if _, err := r.Canonical.fill(auditObservation157(1002, 64000, 2)); err != nil {
		t.Fatal(err)
	}
	o = auditObservation157(1003, 64000, 3)
	r.Canonical.mark(o)
	r.manage157(o, auditSupports157(1, 1), true)
	if len(r.Canonical.Pending) != 1 || len(r.Canonical.Pending[0].Targets) == 0 || r.Canonical.Pending[0].Reason != "base_flat" {
		t.Fatalf("元玉0でカバーが残る: %+v", r.Canonical.Pending)
	}
}

// TestAuditSourceTargetPartialMapping157 は元返済対象を別の追加玉へ誤配賦しません。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditSourceTargetPartialMapping157(t *testing.T) {
	r := auditPolicy157("B01")
	s := auditSupports157(.8, .5)
	o := auditObservation157(1001, 64000, 1)
	if err := step157(r, o, []strategy.Signal{auditSourceNew157("初回", 5, o)}, s); err != nil {
		t.Fatal(err)
	}
	if err := step157(r, auditObservation157(1002, 64000, 2), nil, s); err != nil {
		t.Fatal(err)
	}
	o = auditObservation157(1015, 64020, 3)
	if err := step157(r, o, []strategy.Signal{auditSourceNew157("追加", 1, o)}, s); err != nil {
		t.Fatal(err)
	}
	if err := step157(r, auditObservation157(1016, 64020, 4), nil, s); err != nil {
		t.Fatal(err)
	}
	o = auditObservation157(1020, 64050, 5)
	partial := strategy.Signal{ID: "部分", Action: "close", Owner: "core", Campaign: 0, Side: -1, Quantity: 2, SourceIndex: o.Index, Targets: []strategy.LotTarget{{ID: "初回-玉", Quantity: 2}}}
	if err := step157(r, o, []strategy.Signal{partial}, s); err != nil {
		t.Fatal(err)
	}
	if len(r.Canonical.Pending) != 1 || r.Canonical.Pending[0].Quantity != 16 {
		t.Fatalf("初回40枚の2/5を比例配賦できない: %+v", r.Canonical.Pending)
	}
	if err := step157(r, auditObservation157(1021, 64050, 6), nil, s); err != nil {
		t.Fatal(err)
	}
	left := map[string]int{}
	for _, id := range r.Canonical.Active {
		l := r.Canonical.Lots[id]
		left[l.SourceID] = l.Remaining
	}
	if left["初回"] != 24 || left["追加"] != 8 {
		t.Fatalf("元の対象でない追加玉へ返済: %+v", left)
	}
	o = auditObservation157(1030, 64060, 7)
	full := strategy.Signal{ID: "全終了", Action: "close", Owner: "core", Campaign: 0, Side: -1, Quantity: 4, SourceIndex: o.Index, Targets: []strategy.LotTarget{{ID: "初回-玉", Quantity: 3}, {ID: "追加-玉", Quantity: 1}}}
	if err := step157(r, o, []strategy.Signal{full}, s); err != nil {
		t.Fatal(err)
	}
	if err := step157(r, auditObservation157(1031, 64060, 8), nil, s); err != nil {
		t.Fatal(err)
	}
	if len(r.Canonical.Active) != 0 || len(r.Actual.Active) != 0 || !r.Parents["core/0"].Finished {
		t.Fatal("元親終了の残玉")
	}
}

// TestAuditSimultaneousSharedCapacity157 は同時初回希望を一件目へ全振りしません。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditSimultaneousSharedCapacity157(t *testing.T) {
	r := auditPolicy157("Q01")
	o := auditObservation157(1001, 64000, 1)
	signals := []strategy.Signal{}
	for _, owner := range []string{"core", "episode", "addon"} {
		s := auditSourceNew157(owner, 2, o)
		s.Owner = owner
		signals = append(signals, s)
	}
	r.source157(o, signals, auditSupports157(1, 1))
	q := map[string]int{}
	total := 0
	for _, ord := range r.Canonical.Pending {
		q[ord.Owner] = ord.Quantity
		total += ord.Quantity
	}
	if total != 100 || q["addon"] != 34 || q["core"] != 33 || q["episode"] != 33 {
		t.Fatalf("共通100枚を比例分配しない: %+v", q)
	}
}

// TestAuditUnknownBreaksCoverConfirmation157 は欠測を5秒の確認時間へ算入しません。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditUnknownBreaksCoverConfirmation157(t *testing.T) {
	r := auditPolicy157("H05")
	o := auditObservation157(1001, 64000, 1)
	if err := step157(r, o, []strategy.Signal{auditSourceNew157("初回", 5, o)}, auditSupports157(.8, .5)); err != nil {
		t.Fatal(err)
	}
	if err := step157(r, auditObservation157(1002, 64000, 2), nil, auditSupports157(.8, .5)); err != nil {
		t.Fatal(err)
	}
	opp := map[int]Support157{1: {Known: true, M: 1, Opp: 1, Own5: -1, Own15: -2}, -1: {Known: true, T: 1, Own5: -1, Own15: -2}}
	for _, x := range []struct {
		at  float64
		idx int64
		s   map[int]Support157
	}{{1012, 3, opp}, {1014, 4, map[int]Support157{}}, {1017, 5, opp}} {
		if err := step157(r, auditObservation157(x.at, 64000, x.idx), nil, x.s); err != nil {
			t.Fatal(err)
		}
	}
	if len(r.Canonical.Pending) != 0 {
		t.Fatal("未知を挟んだ5秒でカバーを出した")
	}
	if err := step157(r, auditObservation157(1022, 64000, 6), nil, opp); err != nil {
		t.Fatal(err)
	}
	if len(r.Canonical.Pending) != 1 || r.Canonical.Pending[0].Kind != "cover" {
		t.Fatal("連続5秒成立でもカバーなし")
	}
}

// TestAuditRemainingCapacityBelowMinimum157 は余枠控除後に5枚未満へ細切れ追加しません。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditRemainingCapacityBelowMinimum157(t *testing.T) {
	r := auditPolicy157("Q03")
	o := auditObservation157(1001, 64000, 1)
	if err := step157(r, o, []strategy.Signal{auditSourceNew157("初回", 5, o)}, auditSupports157(.8, .5)); err != nil {
		t.Fatal(err)
	}
	if err := step157(r, auditObservation157(1002, 64000, 2), nil, auditSupports157(.8, .5)); err != nil {
		t.Fatal(err)
	}
	p := &AllocationParent157{Key: "other/0", Owner: "other", Side: 1, SourceQty: 57}
	r.Parents[p.Key] = p
	r.Canonical.open(p, auditObservation157(1003, 64000, 3), "initial", "他親", 1, 57, Support157{})
	if _, err := r.Canonical.fill(auditObservation157(1004, 64000, 4)); err != nil {
		t.Fatal(err)
	}
	o = auditObservation157(1020, 64050, 5)
	r.Canonical.mark(o)
	r.manage157(o, auditSupports157(1, 1), true)
	r.manage157(o, auditSupports157(1, 1), false)
	for _, order := range r.Canonical.Pending {
		if len(order.Targets) == 0 {
			t.Fatalf("余枠3枚を細切れ追加した: %+v", order)
		}
	}
}
