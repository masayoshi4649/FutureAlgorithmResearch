package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

// testQuoteは人工の正常板を作ります。
//
// 引数: index(int64)、at/bid(float64)。返り値: Quoteは気配差10ptの人工板です。
func testQuote(index int64, at, bid float64) Quote {
	return Quote{Index: index, Line: index + 1, Time: at, Last: bid + 5, Bid: bid, Ask: bid + 10}
}

// testNoticeは人工の入口通知を作ります。
//
// 引数: id(string)、q(Quote)、side/qty(int)。返り値: EntryNoticeは当該原行の通知です。
func testNotice(id string, q Quote, side, qty int) EntryNotice {
	return EntryNotice{ID: id, Phase: "前半", Owner: "core", Side: side, Quantity: qty, Time: q.Time, Index: q.Index}
}

// testCaseは部分観測の標準人工運転を作ります。
//
// 引数: なし。返り値: *Resultは利益開始80pt・追尾40ptです。
func testCase() *Result {
	return newResult(Scene{Start: 100, USOpen: 2000, ForceClose: 10000, End: 11000, Partial: true}, fixedConfigs()[1])
}

// mustStepは人工原行の処理失敗を試験失敗にします。
//
// 引数: t(*testing.T)、c(*Result)、q(Quote)、ns(...EntryNotice)。返り値: なし。
func mustStep(t *testing.T, c *Result, q Quote, ns ...EntryNotice) {
	t.Helper()
	if err := step(c, q, ns); err != nil {
		t.Fatal(err)
	}
}

// Test151NextQuoteAndIndependentSidesは同原行・異常板約定を拒否し、逆側保有を独立させます。
//
// 引数: t(*testing.T)。返り値: なし。
func Test151NextQuoteAndIndependentSides(t *testing.T) {
	c := testCase()
	q := testQuote(0, 100, 1000)
	mustStep(t, c, q, testNotice("買", q, 1, 5), testNotice("売", q, -1, 5))
	if len(c.Events) != 0 || len(c.Pending) != 2 {
		t.Fatal("判断行で約定")
	}
	bad := testQuote(1, 100, 1000)
	bad.Ask = bad.Bid
	mustStep(t, c, bad)
	if len(c.Events) != 0 {
		t.Fatal("異常板で約定")
	}
	mustStep(t, c, testQuote(2, 100, 1010))
	if len(c.Events) != 2 || c.Lots[0].Price != 1020 || c.Lots[1].Price != 1010 || c.MaxLong != 5 || c.MaxShort != 5 {
		t.Fatal("次正常板又は方向独立の不整合")
	}
	if c.Unrealized != -10000 {
		t.Fatal("両側気配差を隠している", c.Unrealized)
	}
}

// Test151ReservationsAndClosingCapacityは予約上限と返済中枠の先取り防止を確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test151ReservationsAndClosingCapacity(t *testing.T) {
	c := testCase()
	q := testQuote(0, 100, 1000)
	mustStep(t, c, q, testNotice("甲", q, 1, 8), testNotice("乙", q, 1, 5))
	if c.Decisions[1].Accepted != 2 || c.MaxLongReserved != 10 {
		t.Fatal("予約上限を超過")
	}
	mustStep(t, c, testQuote(1, 101, 1000))
	mustStep(t, c, testQuote(2, 102, 1100))
	q = testQuote(3, 103, 1060)
	mustStep(t, c, q, testNotice("丙", q, 1, 1))
	if c.Decisions[2].Accepted != 0 || len(c.Pending) != 2 {
		t.Fatal("返済予約を空き枠に数えた")
	}
	q = testQuote(4, 104, 1060)
	mustStep(t, c, q, testNotice("丁", q, 1, 5))
	if c.Decisions[3].Accepted != 5 {
		t.Fatal("返済約定後の枠再利用ができない")
	}
}

// Test151NoOppositeIncludesPendingは両建て禁止対照が逆側の未約定も拒否することを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test151NoOppositeIncludesPending(t *testing.T) {
	c := testCase()
	c.Config.NoOpposite = true
	q := testQuote(0, 100, 1000)
	mustStep(t, c, q, testNotice("買", q, 1, 3), testNotice("売", q, -1, 3))
	if c.Decisions[1].Accepted != 0 {
		t.Fatal("逆側予約を無視")
	}
	q = testQuote(1, 101, 1000)
	mustStep(t, c, q, testNotice("売2", q, -1, 3))
	if c.Decisions[2].Accepted != 0 {
		t.Fatal("逆側実玉を無視")
	}
}

// Test151ActivationUsesLiquidationPriceはmidで早く利益追尾を開始しないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test151ActivationUsesLiquidationPrice(t *testing.T) {
	c := testCase()
	q := testQuote(0, 100, 1000)
	mustStep(t, c, q, testNotice("買", q, 1, 1))
	mustStep(t, c, testQuote(1, 101, 1000))
	mustStep(t, c, testQuote(2, 102, 1085))
	if c.Lots[0].Activated {
		t.Fatal("midの80ptで追尾を開始")
	}
	mustStep(t, c, testQuote(3, 103, 1090))
	if !c.Lots[0].Activated {
		t.Fatal("返済bidの80ptで追尾を開始しない")
	}
}

// Test151PositiveDecisionMayLoseOnFillは利確判断後の次板赤字を消さないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test151PositiveDecisionMayLoseOnFill(t *testing.T) {
	c := testCase()
	c.Config.ReentryDistance = 40
	q := testQuote(0, 100, 1000)
	mustStep(t, c, q, testNotice("買", q, 1, 2))
	mustStep(t, c, testQuote(1, 101, 1000))
	mustStep(t, c, testQuote(2, 102, 1090))
	mustStep(t, c, testQuote(3, 103, 1050))
	mustStep(t, c, testQuote(4, 104, 990))
	if c.Gross != -4000 || c.Loss != 4000 || c.PositiveDecisionNegativeFill != 1 || len(c.Arms) != 0 {
		t.Fatal("次板の損失を隠した又は赤字返済から再新規", c.Gross, c.Arms)
	}
}

// Test151PositiveOnlyVersusOrdinaryTrailは利益玉限定と通常追尾の板飛び時の差を確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test151PositiveOnlyVersusOrdinaryTrail(t *testing.T) {
	a, b := testCase(), testCase()
	b.Config.RequirePositive = false
	for _, c := range []*Result{a, b} {
		q := testQuote(0, 100, 1000)
		mustStep(t, c, q, testNotice("買", q, 1, 1))
		mustStep(t, c, testQuote(1, 101, 1000))
		mustStep(t, c, testQuote(2, 102, 1090))
		mustStep(t, c, testQuote(3, 103, 1000))
	}
	if len(a.Pending) != 0 || len(b.Pending) != 1 {
		t.Fatal("利益玉限定と通常追尾が区別されない")
	}
	mustStep(t, a, testQuote(4, 104, 1010))
	if len(a.Pending) != 0 {
		t.Fatal("利益ゼロを利確した")
	}
	mustStep(t, b, testQuote(4, 104, 990))
	if b.Gross != -2000 {
		t.Fatal("通常追尾の損失を計上しない")
	}
}

// Test151BoundaryCrossingPendingは境界前の成行を未来価格で取消さないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test151BoundaryCrossingPending(t *testing.T) {
	c := testCase()
	c.ScheduledClose = 105
	q := testQuote(0, 104, 1000)
	mustStep(t, c, q, testNotice("買", q, 1, 2))
	bad := testQuote(1, 105, 1000)
	bad.Ask = bad.Bid
	mustStep(t, c, bad)
	mustStep(t, c, testQuote(2, 107, 990))
	if len(c.Events) != 1 || len(c.Pending) != 1 || c.FlatAt != 0 {
		t.Fatal("境界後新規の消去又は同原行返済")
	}
	mustStep(t, c, testQuote(3, 108, 980))
	if c.Gross != -4000 || c.FlatAt != 108 || c.CloseDecisionAt != 105 {
		t.Fatal("境界の完済時計又は会計不整合")
	}
}

// Test151PartialDoesNotLiquidateは途中のデータ終端を場末精算しないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test151PartialDoesNotLiquidate(t *testing.T) {
	scene := Scene{Start: 100, USOpen: 2000, ForceClose: 10000, End: 11000, Partial: true}
	q := testQuote(0, 100, 1000)
	input := Input{Scene: scene, Notices: []EntryNotice{testNotice("買", q, 1, 1)}}
	results, err := replay(input, []Quote{q, testQuote(1, 101, 1000), testQuote(2, 102, 900)}, []Config{fixedConfigs()[1]})
	if err != nil {
		t.Fatal(err)
	}
	c := results[0]
	if c.Gross != 0 || c.Unrealized != -11000 || c.Lots[0].Quantity != 1 {
		t.Fatal("途中に強制返済を作った")
	}
}

// Test151PostRequiresStrictEarlierFlatは保存後半と残玉が重なる合算を拒否します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test151PostRequiresStrictEarlierFlat(t *testing.T) {
	c := testCase()
	scene := Scene{Partial: true}
	post := ReusedPost{FirstNewTime: 120, Gross: 100, Profit: 100}
	if finish(scene, c, post) == nil {
		t.Fatal("未完済で後半へ合算")
	}
	c.FlatAt = 120
	if finish(scene, c, post) == nil {
		t.Fatal("同時計で前後非重複を主張")
	}
	c.FlatAt = 119
	if err := finish(scene, c, post); err != nil || c.CombinedGross != 100 {
		t.Fatal("完済後の後半合算", err)
	}
}

// Test151ReentryUsesPostFillExtremeは黒字返済後の追尾枠が同じ行で再新規しないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test151ReentryUsesPostFillExtreme(t *testing.T) {
	c := testCase()
	c.Config.ReentryDistance = 40
	q := testQuote(0, 100, 1000)
	mustStep(t, c, q, testNotice("買", q, 1, 2))
	mustStep(t, c, testQuote(1, 101, 1000))
	mustStep(t, c, testQuote(2, 102, 1090))
	mustStep(t, c, testQuote(3, 103, 1050))
	mustStep(t, c, testQuote(4, 104, 1050))
	if len(c.Arms) != 1 || len(c.Pending) != 0 || c.Gross != 8000 {
		t.Fatal("黒字返済からの待機不整合")
	}
	mustStep(t, c, testQuote(5, 105, 1010))
	mustStep(t, c, testQuote(6, 106, 1040))
	if len(c.Pending) != 0 {
		t.Fatal("30ptで40pt再新規が発火")
	}
	mustStep(t, c, testQuote(7, 107, 1050))
	if len(c.Arms) != 0 || len(c.Pending) != 1 || c.Pending[0].Quantity != 2 || c.ReentryNewCount != 1 {
		t.Fatal("40pt再新規が発火しない")
	}
	mustStep(t, c, testQuote(8, 108, 1060))
	if len(c.Lots) != 2 || c.Lots[1].Price != 1070 || c.Lots[0].SlotID != c.Lots[1].SlotID {
		t.Fatal("再新規の次板又は枠ID不整合")
	}
}

// Test151ReentryCapacityWaitAndBoundaryは待機枠の上限待ちと境界解除を確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test151ReentryCapacityWaitAndBoundary(t *testing.T) {
	c := testCase()
	c.Config.ReentryDistance = 40
	c.ScheduledClose = 110
	c.Arms = []ReentryArm{{SlotID: "再待", Generation: 1, Source: EntryNotice{ID: "原"}, Side: 1, Quantity: 3, Extreme: 1000, CreatedIndex: -1, CreatedTime: 99}}
	q := testQuote(0, 100, 1040)
	mustStep(t, c, q, testNotice("別枠", q, 1, 8))
	if len(c.Arms) != 1 || c.ReentryCapWaitRows != 1 || c.MaxLongReserved != 8 {
		t.Fatal("待機を予約枚数に数えた又は勝手に分割")
	}
	mustStep(t, c, testQuote(1, 101, 1040))
	mustStep(t, c, testQuote(2, 110, 1040))
	if len(c.Arms) != 0 || c.ReentryArmsCancelled != 1 {
		t.Fatal("境界で再新規待機が残った")
	}
	mustStep(t, c, testQuote(3, 111, 1040))
	if c.FlatAt != 111 {
		t.Fatal("境界の実玉を返済しない")
	}
}

// Test151ReentryRepeatsAndSideSymmetryは買売鏡像と再利確後の反復を確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test151ReentryRepeatsAndSideSymmetry(t *testing.T) {
	prices := []float64{1000, 1000, 1090, 1050, 1050, 1010, 1050, 1060, 1150, 1110, 1110}
	results := []*Result{}
	for _, side := range []int{1, -1} {
		c := testCase()
		c.Config.ReentryDistance = 40
		for i, bid := range prices {
			q := testQuote(int64(i), 100+float64(i), bid)
			if side < 0 {
				q.Bid, q.Ask, q.Last = 3000-q.Ask, 3000-q.Bid, 3000-q.Last
			}
			ns := []EntryNotice{}
			if i == 0 {
				ns = append(ns, testNotice("入口", q, side, 2))
			}
			mustStep(t, c, q, ns...)
		}
		if len(c.Arms) != 1 || c.Arms[0].Generation != 2 || len(c.Lots) != 2 || c.Gross != 16000 {
			t.Fatal("反復再利確の不整合", side, c.Gross, c.Arms)
		}
		results = append(results, c)
	}
	if results[0].Gross != results[1].Gross || results[0].HeldSeconds != results[1].HeldSeconds {
		t.Fatal("買売の非対称")
	}
}

// Test151FutureOutcomeNotInEntryTypeは将来約定と返済を改ざんしても入口が同一であることを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test151FutureOutcomeNotInEntryType(t *testing.T) {
	scene := Scene{Start: 100, USOpen: 2000, End: 11000}
	a := []byte(`{"cases":[{"config":{"id":"B04"},"events":[{"phase":"前半","decision_index":0,"signal":{"id":"n","owner":"core","action":"new","side":1,"quantity":2,"time":100,"source_index":0},"fill":{"Price":1000,"Time":101},"gross":0},{"phase":"前半","decision_index":5,"signal":{"id":"c","action":"close","side":-1,"quantity":2,"time":110,"source_index":5},"fill":{"Price":1100},"gross":20000}],"final_pending":[{"id":"pending","owner":"core","action":"new","side":-1,"quantity":1,"time":120,"source_index":9}]}]}`)
	var b map[string]any
	if err := json.Unmarshal(a, &b); err != nil {
		t.Fatal(err)
	}
	events := b["cases"].([]any)[0].(map[string]any)["events"].([]any)
	events[0].(map[string]any)["fill"] = map[string]any{"Price": -999, "Time": 999999}
	events[0].(map[string]any)["gross"] = -987654
	events[1].(map[string]any)["signal"].(map[string]any)["side"] = 1
	events[1].(map[string]any)["gross"] = -999999
	br, _ := json.Marshal(b)
	left, e := extractNotices(a, scene)
	if e != nil {
		t.Fatal(e)
	}
	right, e := extractNotices(br, scene)
	if e != nil {
		t.Fatal(e)
	}
	if !reflect.DeepEqual(left, right) || len(left) != 2 || left[1].ID != "pending" {
		t.Fatal("未来結果が入口へ混入又は未約定通知脱落")
	}
}

// Test151FuturePrefixInvariantは後続通知や価格を変えても既に実行した接頭部が変わらないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test151FuturePrefixInvariant(t *testing.T) {
	c, d := testCase(), testCase()
	q := testQuote(0, 100, 1000)
	for _, x := range []*Result{c, d} {
		mustStep(t, x, q, testNotice("入口", q, 1, 2))
		mustStep(t, x, testQuote(1, 101, 1000))
		mustStep(t, x, testQuote(2, 102, 1090))
	}
	before, _ := json.Marshal(c)
	mustStep(t, c, testQuote(3, 103, 1050))
	future := testQuote(3, 103, 1200)
	mustStep(t, d, future, testNotice("未来新規", future, -1, 3))
	copyPrefix := testCase()
	mustStep(t, copyPrefix, q, testNotice("入口", q, 1, 2))
	mustStep(t, copyPrefix, testQuote(1, 101, 1000))
	mustStep(t, copyPrefix, testQuote(2, 102, 1090))
	after, _ := json.Marshal(copyPrefix)
	if string(before) != string(after) {
		t.Fatal("未来による接頭部の変更")
	}
}

// Test151ParserRetainsInvalidQuotesAndIndicesは源と同じ採用添字を人工原板で確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test151ParserRetainsInvalidQuotesAndIndices(t *testing.T) {
	path := filepath.Join(t.TempDir(), "book.jsonl")
	raw := "{\"CurrentPriceTime\":null,\"CurrentPrice\":100}\n" +
		`{"CurrentPriceTime":"1970-01-01T00:01:40Z","CurrentPrice":100,"Buy1":{"Price":100},"Sell1":{"Price":100}}` + "\n" +
		`{"CurrentPriceTime":"1970-01-01T00:01:41Z","CurrentPrice":0}` + "\n" +
		`{"CurrentPriceTime":"1970-01-01T00:01:39Z","CurrentPrice":100}` + "\n" +
		`{"CurrentPriceTime":"1970-01-01T00:01:42Z","CurrentPrice":100,"TradingVolumeTime":null,"Buy1":{"Price":100},"Sell1":{"Price":110}}` + "\n"
	if err := os.WriteFile(path, []byte(raw), 0644); err != nil {
		t.Fatal(err)
	}
	qs, counts, err := loadQuotes(Scene{Start: 99, End: 200, Books: map[string]string{"NK225": path}})
	if err != nil {
		t.Fatal(err)
	}
	if len(qs) != 2 || qs[0].Index != 0 || qs[1].Index != 1 || qs[1].Line != 5 || counts["異常気配"] != 1 || counts["逆行"] != 1 {
		t.Fatal("原板採番不一致", qs, counts)
	}
}

// Test151RegisteredConfigSetは18条件が固定ファイルと一致することを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test151RegisteredConfigSet(t *testing.T) {
	var configs []Config
	if err := readJSON("../configs151.json", &configs); err != nil {
		t.Fatal(err)
	}
	if err := validateConfigs(configs); err != nil {
		t.Fatal(err)
	}
	configs[0].Trail++
	if validateConfigs(configs) == nil {
		t.Fatal("未登録条件を受理")
	}
}

// Test151ReceiptRequiresBothは登録旗又は終了コードだけの成功を拒否します。
//
// 引数: t(*testing.T)。返り値: なし。
func Test151ReceiptRequiresBoth(t *testing.T) {
	for _, receipt := range []map[string]any{{}, {"returncode": float64(0)}, {"registered": true}, {"returncode": float64(1), "registered": true}, {"returncode": float64(0), "registered": false}} {
		if validateReceipt(receipt) == nil {
			t.Fatal("未完成の登録を受理", receipt)
		}
	}
	if err := validateReceipt(map[string]any{"returncode": float64(0), "registered": true}); err != nil {
		t.Fatal(err)
	}
}
