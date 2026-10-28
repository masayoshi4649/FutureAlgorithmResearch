package main

import (
	"encoding/json"
	"math"
	"os"
	"path/filepath"
	"testing"
)

// auditQuote151 は原板を使わず独立した人工気配を作ります。
//
// 引数: index(int64)、at/bid/ask(float64)。返り値: Quoteは人工観測です。
func auditQuote151(index int64, at, bid, ask float64) Quote {
	return Quote{Index: index, Line: index + 1, Time: at, Last: (bid + ask) / 2, Bid: bid, Ask: ask}
}

// auditNotice151 は現在行だけから新規通知を作ります。
//
// 引数: id(string)、q(Quote)、side/quantity(int)。返り値: EntryNoticeは人工通知です。
func auditNotice151(id string, q Quote, side, quantity int) EntryNotice {
	return EntryNotice{ID: id, Phase: "前半", Owner: "core", Side: side, Quantity: quantity, Time: q.Time, Index: q.Index}
}

// auditStep151 は人工一行を処理し、処理失敗なら試験を停止します。
//
// 引数: t(*testing.T)、c(*Result)、q(Quote)、notices(...EntryNotice)。返り値: なし。
func auditStep151(t *testing.T, c *Result, q Quote, notices ...EntryNotice) {
	t.Helper()
	if err := step(c, q, notices); err != nil {
		t.Fatal(err)
	}
}

// auditNear151 は金額の人工期待値との一致を確認します。
//
// 引数: t(*testing.T)、got/want(float64)。返り値: なし。
func auditNear151(t *testing.T, got, want float64) {
	t.Helper()
	if math.Abs(got-want) > 1e-7 {
		t.Fatalf("金額不一致: 実際%v、期待%v", got, want)
	}
}

// TestAudit151EqualHedgeIdentity は同数玉の価格中立と気配幅の影響を検査します。
//
// 引数: t(*testing.T)。返り値: なし。市場資料は使いません。
func TestAudit151EqualHedgeIdentity(t *testing.T) {
	c := newResult(Scene{Start: 100, ForceClose: 1000}, Config{ID: "独立", Scope: "night", Activation: 100000, Trail: 40, RequirePositive: true})
	q0 := auditQuote151(0, 100, 995, 1005)
	auditStep151(t, c, q0, auditNotice151("買", q0, 1, 1))
	q1 := auditQuote151(1, 101, 995, 1005)
	auditStep151(t, c, q1, auditNotice151("売", q1, -1, 1))
	auditStep151(t, c, auditQuote151(2, 102, 995, 1005))
	auditNear151(t, c.Gross+c.Unrealized, -2000)
	auditStep151(t, c, auditQuote151(3, 103, 945, 955))
	auditNear151(t, c.Gross+c.Unrealized, -2000)
	auditStep151(t, c, auditQuote151(4, 104, 940, 960))
	auditNear151(t, c.Gross+c.Unrealized, -3000)
}

// TestAudit151WinnerCloseKeepsEquityThenChangesExposure は利確直後の資産保存と以後の方向変化を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit151WinnerCloseKeepsEquityThenChangesExposure(t *testing.T) {
	c := newResult(Scene{Start: 100, ForceClose: 1000}, Config{ID: "独立", Scope: "night", Activation: 100000, Trail: 40, RequirePositive: true})
	c.Lots = []*Lot{
		{ID: "買", SlotID: "買", Side: 1, Quantity: 1, OriginalQuantity: 1, Price: 100},
		{ID: "売", SlotID: "売", Side: -1, Quantity: 1, OriginalQuantity: 1, Price: 90},
	}
	q0 := auditQuote151(0, 100, 79, 81)
	auditStep151(t, c, q0)
	auditNear151(t, c.Gross+c.Unrealized, -1200)
	queueClose(c, c.Lots[1], q0, "独立人工の利益側返済")
	auditStep151(t, c, auditQuote151(1, 101, 79, 81))
	auditNear151(t, c.Gross, 900)
	auditNear151(t, c.Gross+c.Unrealized, -1200)
	auditStep151(t, c, auditQuote151(2, 102, 69, 71))
	auditNear151(t, c.Gross+c.Unrealized, -2200)
}

// TestAudit151ProfitDecisionCanFillAtLoss は利益条件で出した返済の次板損失を計上します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit151ProfitDecisionCanFillAtLoss(t *testing.T) {
	c := newResult(Scene{Start: 100, ForceClose: 1000}, Config{ID: "独立", Scope: "night", Activation: 80, Trail: 40, RequirePositive: true})
	q0 := auditQuote151(0, 100, 990, 1000)
	auditStep151(t, c, q0, auditNotice151("買", q0, 1, 5))
	auditStep151(t, c, auditQuote151(1, 101, 990, 1000))
	auditStep151(t, c, auditQuote151(2, 102, 1100, 1110))
	auditStep151(t, c, auditQuote151(3, 103, 1060, 1070))
	if len(c.Pending) != 1 || c.Pending[0].DecisionGain != 60 {
		t.Fatal("利益60ptで返済予約されていません")
	}
	auditStep151(t, c, auditQuote151(4, 104, 980, 990))
	auditNear151(t, c.Gross, -10000)
	if c.PositiveDecisionNegativeFill != 1 || len(c.Events) != 2 {
		t.Fatal("利益判断後の実損失が脱落しています")
	}
}

// TestAudit151PositiveOnlyAndNormalTrail は0を飛び越す戻りに対する二政策の違いを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit151PositiveOnlyAndNormalTrail(t *testing.T) {
	for _, positiveOnly := range []bool{true, false} {
		c := newResult(Scene{Start: 100, ForceClose: 1000}, Config{ID: "独立", Scope: "night", Activation: 80, Trail: 40, RequirePositive: positiveOnly})
		q0 := auditQuote151(0, 100, 990, 1000)
		auditStep151(t, c, q0, auditNotice151("買", q0, 1, 1))
		auditStep151(t, c, auditQuote151(1, 101, 990, 1000))
		auditStep151(t, c, auditQuote151(2, 102, 1080, 1090))
		auditStep151(t, c, auditQuote151(3, 103, 990, 1000))
		if positiveOnly && len(c.Pending) != 0 {
			t.Fatal("利益限定型が赤字判断時に返済しました")
		}
		if !positiveOnly && (len(c.Pending) != 1 || c.Pending[0].Action != "close") {
			t.Fatal("通常追尾型が飛び越し損失で返済していません")
		}
	}
}

// TestAudit151BoundaryKeepsAlreadySubmittedNew は境界を跨ぐ送信済み新規を消さず二段階で返します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit151BoundaryKeepsAlreadySubmittedNew(t *testing.T) {
	c := newResult(Scene{Start: 100, USOpen: 1100, ForceClose: 2000}, Config{ID: "独立", Scope: "pre", Activation: 80, Trail: 40, RequirePositive: true})
	q0 := auditQuote151(0, 199, 990, 1000)
	auditStep151(t, c, q0, auditNotice151("買", q0, 1, 5))
	auditStep151(t, c, auditQuote151(1, 200, 990, 1000))
	if len(c.Events) != 1 || len(c.Pending) != 1 || c.Pending[0].DecisionIndex != 1 {
		t.Fatal("境界で新規を消したか同原行で返済しました")
	}
	auditStep151(t, c, auditQuote151(2, 201, 980, 990))
	if len(c.Events) != 2 || c.FlatAt != 201 || len(c.Pending) != 0 {
		t.Fatal("次正常板で全返済していません")
	}
	auditNear151(t, c.Gross, -10000)
}

// TestAudit151OppositeQuantityIncludesReservations は逆方向予約をP08の拒否判定へ含めます。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit151OppositeQuantityIncludesReservations(t *testing.T) {
	for _, noOpposite := range []bool{true, false} {
		c := newResult(Scene{Start: 100, ForceClose: 1000}, Config{ID: "独立", Scope: "night", Activation: 80, Trail: 40, NoOpposite: noOpposite, RequirePositive: true})
		q0 := auditQuote151(0, 100, 990, 1000)
		auditStep151(t, c, q0, auditNotice151("買", q0, 1, 10), auditNotice151("売", q0, -1, 10))
		want := 2
		if noOpposite {
			want = 1
		}
		if len(c.Pending) != want {
			t.Fatal("逆側の新規予約を正しく扱っていません")
		}
		auditStep151(t, c, auditQuote151(1, 101, 990, 1000))
		long, short, _, _ := exposure(c)
		if long != 10 || (noOpposite && short != 0) || (!noOpposite && short != 10) {
			t.Fatal("両側独立上限または逆側拒否が不正です")
		}
	}
}

// TestAudit151ReentryUsesActualFillLast は返済後のLastから新しく極値を追うことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit151ReentryUsesActualFillLast(t *testing.T) {
	c := newResult(Scene{Start: 100, ForceClose: 1000}, Config{ID: "独立", Scope: "night", Activation: 80, Trail: 40, RequirePositive: true, ReentryDistance: 40})
	q0 := auditQuote151(0, 100, 990, 1000)
	auditStep151(t, c, q0, auditNotice151("買", q0, 1, 1))
	auditStep151(t, c, auditQuote151(1, 101, 990, 1000))
	auditStep151(t, c, auditQuote151(2, 102, 1080, 1090))
	auditStep151(t, c, auditQuote151(3, 103, 1040, 1050))
	q4 := auditQuote151(4, 104, 1040, 1050)
	q4.Last = 1070
	auditStep151(t, c, q4)
	if len(c.Arms) != 1 || len(c.Pending) != 0 || c.Arms[0].Extreme != 1070 || c.Arms[0].CreatedIndex != 4 {
		t.Fatal("実返済前の値または中値を再参加の起点へ流用しました")
	}
	q5 := auditQuote151(5, 105, 990, 1000)
	q5.Last = 1000
	auditStep151(t, c, q5)
	q6 := auditQuote151(6, 106, 1020, 1030)
	q6.Last = 1039
	auditStep151(t, c, q6)
	if len(c.Pending) != 0 {
		t.Fatal("40pt未満で再参加しました")
	}
	q7 := auditQuote151(7, 107, 1020, 1030)
	q7.Last = 1040
	auditStep151(t, c, q7)
	if len(c.Pending) != 1 || len(c.Arms) != 0 || c.Pending[0].DecisionIndex != 7 {
		t.Fatal("当時のLast極値による再参加が不正です")
	}
	auditStep151(t, c, auditQuote151(8, 108, 1050, 1060))
	if len(c.Lots) != 2 || c.Lots[1].Price != 1060 || c.Lots[1].SlotID != c.Lots[0].SlotID {
		t.Fatal("再参加枠か次正常板約定が不正です")
	}
}

// TestAudit151TechnicalLoaderMatchesSavedIndices は原板読込の採番だけを独立保存期待へ照合します。
//
// 引数: t(*testing.T)。返り値: なし。明示環境変数がある時だけ原板1場を技術走査し、金融再生は呼びません。
func TestAudit151TechnicalLoaderMatchesSavedIndices(t *testing.T) {
	if os.Getenv("AUDIT_INDEX_151") != "1" {
		t.Skip("原板の技術照合は明示実行のみ")
	}
	root := filepath.Join("..", "..", "..", "..")
	var saved struct {
		Scene Scene `json:"scene"`
	}
	if err := readJSON(filepath.Join(root, "work/preus150/results_round2/2026-10-21_Night.json"), &saved); err != nil {
		t.Fatal(err)
	}
	var expected struct {
		Check struct {
			Counts map[string]int `json:"counts"`
			Rows   []struct {
				Index int64   `json:"source_index_0based"`
				Line  int64   `json:"physical_row_1based"`
				Last  float64 `json:"last"`
				Bid   float64 `json:"bid"`
				Ask   float64 `json:"ask"`
			} `json:"all_new_decisions_matched"`
		} `json:"source_index_check"`
	}
	raw, err := os.ReadFile("../保存通知と判断添字の独立照合.json")
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(raw, &expected); err != nil {
		t.Fatal(err)
	}
	quotes, counts, err := loadQuotes(saved.Scene)
	if err != nil {
		t.Fatal(err)
	}
	if len(quotes) != expected.Check.Counts["NK225_採用"] || counts["原行"] != expected.Check.Counts["NK225_原行"] {
		t.Fatal("採用行数または原行数が不一致です")
	}
	for _, want := range expected.Check.Rows {
		q := quotes[want.Index]
		if q.Index != want.Index || q.Line != want.Line || q.Last != want.Last || q.Bid != want.Bid || q.Ask != want.Ask {
			t.Fatal("新規判断の原行対応が不一致です", q, want)
		}
	}
	t.Logf("金融再生なし、%d採用行・%d新規判断の対応一致", len(quotes), len(expected.Check.Rows))
}
