package main

import (
	"compress/gzip"
	"encoding/json"
	"math"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

// adversaryTime は独立人工例の日本時間を返します。
//
// 引数: seconds(int)は場開始からの秒数。返り値: time.Time。
func adversaryTime(seconds int) time.Time {
	return time.Date(2026, 10, 27, 8, 45, 0, 0, japan).Add(time.Duration(seconds) * time.Second)
}

// adversaryBook は名称が逆に見える上位気配項目も持つ人工原板を作ります。
//
// 引数: seconds(int)、last/bid/ask(any)。返り値: map[string]any。
func adversaryBook(seconds int, last, bid, ask any) map[string]any {
	return map[string]any{"CurrentPriceTime": adversaryTime(seconds).Format(time.RFC3339Nano), "CurrentPrice": last,
		"Buy1": map[string]any{"Price": bid}, "Sell1": map[string]any{"Price": ask}, "BidPrice": ask, "AskPrice": bid}
}

// adversaryWrite はUTF-8の人工JSONLを一時ディレクトリへ保存します。
//
// 引数: t(*testing.T)、path(string)、rows([]map[string]any)。返り値: なし。
func adversaryWrite(t *testing.T, path string, rows []map[string]any) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	var out strings.Builder
	for _, row := range rows {
		b, err := json.Marshal(row)
		if err != nil {
			t.Fatal(err)
		}
		out.Write(b)
		out.WriteByte('\n')
	}
	if err := os.WriteFile(path, []byte(out.String()), 0600); err != nil {
		t.Fatal(err)
	}
}

// adversaryTrade は価格と対象玉を明示した人工約定片を返します。
//
// 引数: id/kind/positionID(string)、seconds/qty/line(int)、price/fee(float64)。返り値: map[string]any。
func adversaryTrade(id, kind, positionID string, seconds, qty, line int, price, fee float64) map[string]any {
	r := map[string]any{"id": id, "timestamp": adversaryTime(seconds).Format(time.RFC3339Nano), "type": kind,
		"position_id": positionID, "qty": qty, "price": price, "fee_yen": fee}
	if line > 0 {
		r["source_line"] = line
	}
	return r
}

// adversaryFixture は原資料を変更しない独立入力と解決済みリソースを作ります。
//
// 引数: t(*testing.T)、books/rows([]map[string]any)、format(string)。返り値: Config、ResourceMeta、一覧のパス(string)。
func adversaryFixture(t *testing.T, books, rows []map[string]any, format string) (Config, ResourceMeta, string) {
	t.Helper()
	dir := t.TempDir()
	var cfg Config
	cfg.BaseDir = dir
	cfg.Paths.DataRoot = filepath.Join(dir, "raw")
	cfg.Paths.ResourceRoot = filepath.Join(dir, "resources")
	r := ResourceMeta{ID: "人工", Title: "独立人工", Symbol: "NK225", Session: "2026-10-27_Day", Product: "NK225micro", PointValue: 10,
		PNLFormat: format, PNLBasis: "gross", PNLPath: "人工.jsonl"}
	adversaryWrite(t, filepath.Join(cfg.Paths.DataRoot, "NK225", r.Session, "book.jsonl"), books)
	adversaryWrite(t, filepath.Join(cfg.Paths.ResourceRoot, r.PNLPath), rows)
	c, err := validateCatalog(cfg, Catalog{SchemaVersion: 1, Resources: []ResourceMeta{r}})
	if err != nil {
		t.Fatal(err)
	}
	return cfg, c.Resources[0], filepath.Join(cfg.Paths.ResourceRoot, "人工.resources.json")
}

// adversaryStates は出力JSONと同じ数値・null型へ正規化して状態行を返します。
//
// 引数: t(*testing.T)、data(DataResponse)。返り値: []map[string]any。非有限数はJSON生成時に失敗します。
func adversaryStates(t *testing.T, data DataResponse) []map[string]any {
	t.Helper()
	b, err := json.Marshal(data)
	if err != nil {
		t.Fatal(err)
	}
	var out struct {
		StateColumns []string `json:"state_columns"`
		States       [][]any  `json:"states"`
	}
	if err := json.Unmarshal(b, &out); err != nil {
		t.Fatal(err)
	}
	rows := make([]map[string]any, 0, len(out.States))
	for _, values := range out.States {
		if len(values) != len(out.StateColumns) {
			t.Fatalf("状態列数が不一致: %d/%d", len(values), len(out.StateColumns))
		}
		r := map[string]any{}
		for i, name := range out.StateColumns {
			r[name] = values[i]
		}
		rows = append(rows, r)
	}
	return rows
}

// adversaryLastAt は指定時刻までの最後の既知行を順序を変えず返します。
//
// 引数: t(*testing.T)、rows([]map[string]any)、at(time.Time)。返り値: map[string]any。
func adversaryLastAt(t *testing.T, rows []map[string]any, at time.Time) map[string]any {
	t.Helper()
	var selected map[string]any
	for _, row := range rows {
		stamp, ok := row["t"].(float64)
		if ok && stamp <= millis(at) {
			selected = row
		}
	}
	if selected == nil {
		t.Fatal("対象時刻までの状態がありません")
	}
	return selected
}

// adversaryNumber は人工例の数値又は未知を厳密に比較します。
//
// 引数: t(*testing.T)、row(map[string]any)、key(string)、want(any)。返り値: なし。
func adversaryNumber(t *testing.T, row map[string]any, key string, want any) {
	t.Helper()
	actual, found := row[key]
	if !found {
		t.Fatalf("必須列がありません: %s", key)
	}
	if want == nil {
		if actual != nil {
			t.Fatalf("%s: 未知が必要ですが %v", key, actual)
		}
		return
	}
	n, ok := actual.(float64)
	expected, valid := numeric(want)
	if !ok || !valid || math.Abs(n-expected) > 1e-8 {
		t.Fatalf("%s: got=%v want=%v", key, actual, want)
	}
}

// TestAdversaryViewerPartialOwnership は追加約定と対象指定返済・費用基準を検査します。
//
// 引数: t(*testing.T)。返り値: なし。別玉をFIFOで閉じず、加重建値を使用します。
func TestAdversaryViewerPartialOwnership(t *testing.T) {
	for _, basis := range []string{"gross", "net"} {
		t.Run(basis, func(t *testing.T) {
			l := newDisplayLedger(ResourceMeta{PointValue: 10, PNLBasis: basis})
			trades := []Trade{
				{Type: "LongN", PositionID: "A", Price: 110, Qty: 2, FeeYen: 2},
				{Type: "LongN", PositionID: "A", Price: 120, Qty: 2, FeeYen: 4},
				{Type: "LongN", PositionID: "B", Price: 200, Qty: 1, FeeYen: 1},
				{Type: "LongR", PositionID: "A", Price: 130, Qty: 1, FeeYen: 1},
			}
			for _, tr := range trades {
				if _, err := l.apply(tr); err != nil {
					t.Fatal(err)
				}
			}
			want := 150.0
			if basis == "net" {
				want = 142
			}
			if l.Realized != want || l.Positions["A"].Qty != 3 || l.Positions["A"].Average != 115 || l.Positions["B"].Qty != 1 {
				t.Fatalf("部分返済の配賦不正: %+v %+v", l, l.Positions)
			}
			if _, err := l.apply(Trade{Type: "LongR", PositionID: "A", Price: 90, Qty: 3, FeeYen: 3}); err != nil {
				t.Fatal(err)
			}
			if _, err := l.apply(Trade{Type: "LongR", PositionID: "B", Price: 210, Qty: 1, FeeYen: 1}); err != nil {
				t.Fatal(err)
			}
			want = -500
			if basis == "net" {
				want = -512
			}
			if l.Realized != want {
				t.Fatalf("確定損益 got=%v want=%v", l.Realized, want)
			}
		})
	}
}

// TestAdversaryViewerLiquidationAndUnknown は返済側気配・両建て・未知と無保有を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAdversaryViewerLiquidationAndUnknown(t *testing.T) {
	l := newDisplayLedger(ResourceMeta{PointValue: 10, PNLBasis: "gross"})
	for _, tr := range []Trade{{Type: "LongN", PositionID: "L", Qty: 2, Price: 110}, {Type: "ShortN", PositionID: "S", Qty: 3, Price: 100}} {
		if _, err := l.apply(tr); err != nil {
			t.Fatal(err)
		}
	}
	bid, ask := 120.0, 130.0
	q := &marketQuote{Bid: &bid, Ask: &ask}
	s := l.mark(q)
	if *s.LongQty != 2 || *s.ShortQty != 3 || s.Unrealized == nil || *s.Unrealized != -700 {
		t.Fatalf("返済側気配の計算不正: %+v", s)
	}
	for _, q := range []*marketQuote{nil, {Bid: &bid}, {Bid: &ask, Ask: &bid}, {Bid: &bid, Ask: &bid}} {
		if l.mark(q).Unrealized != nil {
			t.Fatal("不明/交差/同値気配を正常価格にしている")
		}
	}
	l.Positions["L"].Qty = 0
	l.Positions["S"].Qty = 0
	if s = l.mark(nil); s.Unrealized == nil || *s.Unrealized != 0 {
		t.Fatal("無保有は評価板不明でも含み0")
	}
}

// TestAdversaryViewerRejectInvalidTrades は壊れた約定を成功表示へ変換しないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAdversaryViewerRejectInvalidTrades(t *testing.T) {
	base := adversaryTrade("n", "LongN", "A", 0, 1, 1, 110, 0)
	cases := map[string][]map[string]any{
		"重複ID":  {base, adversaryTrade("n", "LongN", "B", 1, 1, 2, 120, 0)},
		"過剰返済":  {base, adversaryTrade("r", "LongR", "A", 1, 2, 2, 120, 0)},
		"別方向返済": {base, adversaryTrade("r", "ShortR", "A", 1, 1, 2, 120, 0)},
		"他人の玉":  {base, adversaryTrade("r", "LongR", "B", 1, 1, 2, 120, 0)},
		"異側追加":  {base, adversaryTrade("s", "ShortN", "A", 1, 1, 2, 120, 0)},
		"時計後退":  {adversaryTrade("n", "LongN", "A", 2, 1, 3, 110, 0), adversaryTrade("r", "LongR", "A", 1, 1, 2, 120, 0)},
		"0枚":    {adversaryTrade("n", "LongN", "A", 0, 0, 1, 110, 0)},
	}
	for name, trades := range cases {
		t.Run(name, func(t *testing.T) {
			cfg, r, catalog := adversaryFixture(t, []map[string]any{adversaryBook(0, 105, 100, 110), adversaryBook(1, 115, 110, 120), adversaryBook(2, 125, 120, 130)}, trades, "trades")
			if _, err := loadData(cfg, r, catalog, 0, 0, 100); err == nil {
				t.Fatal("壊れた約定を成功扱いした")
			}
		})
	}
}

// TestAdversaryViewerExactSameClock は同秒の原行順・中間状態と経済側の気配名を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAdversaryViewerExactSameClock(t *testing.T) {
	books := []map[string]any{adversaryBook(0, 105, 100, 110), adversaryBook(0, 155, 150, 160), adversaryBook(0, 95, 90, 100), adversaryBook(1, 125, 120, 130)}
	trades := []map[string]any{adversaryTrade("n", "LongN", "A", 0, 1, 1, 110, 0), adversaryTrade("r", "LongR", "A", 0, 1, 3, 90, 0)}
	cfg, r, catalog := adversaryFixture(t, books, trades, "trades")
	data, err := loadData(cfg, r, catalog, 0, 0, 100)
	if err != nil {
		t.Fatal(err)
	}
	seen := map[float64]bool{}
	held := false
	for _, row := range adversaryStates(t, data) {
		if row["long_qty"] == float64(1) {
			held = true
			if v, ok := row["unrealized_pnl_yen"].(float64); ok {
				seen[v] = true
			}
		}
	}
	if !held || !seen[-100] || !seen[400] {
		t.Fatalf("同秒内の新規/中間値が消えた又は未来板を使用: held=%v gains=%v", held, seen)
	}
	if data.Summary.Realized == nil || *data.Summary.Realized != -200 || data.Summary.LongQty == nil || *data.Summary.LongQty != 0 {
		t.Fatalf("最終会計が不一致: %+v", data.Summary)
	}
	if len(data.Events) != 2 {
		t.Fatalf("同秒の約定を統合している: %d", len(data.Events))
	}
}

// TestAdversaryViewerAmbiguousClock は原行不明の同秒へ未来の気配を結合しないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAdversaryViewerAmbiguousClock(t *testing.T) {
	cfg, r, catalog := adversaryFixture(t, []map[string]any{adversaryBook(0, 105, 100, 110), adversaryBook(0, 155, 150, 160), adversaryBook(1, 125, 120, 130)}, []map[string]any{adversaryTrade("n", "LongN", "A", 0, 1, 0, 110, 0)}, "trades")
	data, err := loadData(cfg, r, catalog, 0, 0, 100)
	if err != nil {
		t.Fatal(err)
	}
	rows := adversaryStates(t, data)
	for _, row := range rows {
		if row["t"] == millis(adversaryTime(0)) && row["long_qty"] == float64(1) {
			adversaryNumber(t, row, "unrealized_pnl_yen", nil)
		}
	}
	row := adversaryLastAt(t, rows, adversaryTime(1))
	adversaryNumber(t, row, "long_qty", 1)
	adversaryNumber(t, row, "unrealized_pnl_yen", 100)
	if len(data.Quality.Warnings) == 0 {
		t.Fatal("同秒順序不明の警告がありません")
	}
}

// TestAdversaryViewerInvalidBookCreatesGap は保有中の異常気配で含みを0/前値へ埋めないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAdversaryViewerInvalidBookCreatesGap(t *testing.T) {
	cfg, r, catalog := adversaryFixture(t, []map[string]any{adversaryBook(0, 105, 100, 110), adversaryBook(1, 115, 120, 110), adversaryBook(2, nil, nil, 130), adversaryBook(3, 125, 120, 130)}, []map[string]any{adversaryTrade("n", "LongN", "A", 0, 1, 1, 110, 0)}, "trades")
	data, err := loadData(cfg, r, catalog, 0, 0, 100)
	if err != nil {
		t.Fatal(err)
	}
	rows := adversaryStates(t, data)
	for _, sec := range []int{1, 2} {
		row := adversaryLastAt(t, rows, adversaryTime(sec))
		adversaryNumber(t, row, "long_qty", 1)
		adversaryNumber(t, row, "unrealized_pnl_yen", nil)
	}
	adversaryNumber(t, adversaryLastAt(t, rows, adversaryTime(3)), "unrealized_pnl_yen", 100)
}

// TestAdversaryViewerSnapshotCoverage はスナップショットの前後を未知のまま表示することを検査します。
//
// 引数: t(*testing.T)。返り値: なし。途中のnullを勝手に計算しません。
func TestAdversaryViewerSnapshotCoverage(t *testing.T) {
	rows := []map[string]any{
		{"timestamp": adversaryTime(1).Format(time.RFC3339Nano), "long_qty": 2, "short_qty": 1, "realized_pnl_yen": 123, "unrealized_pnl_yen": nil},
		{"timestamp": adversaryTime(3).Format(time.RFC3339Nano), "long_qty": 0, "short_qty": 0, "realized_pnl_yen": 456, "unrealized_pnl_yen": 0},
	}
	cfg, r, catalog := adversaryFixture(t, []map[string]any{adversaryBook(0, 105, 100, 110), adversaryBook(1, 105, 100, 110), adversaryBook(3, 125, 120, 130), adversaryBook(4, 125, 120, 130)}, rows, "snapshots")
	data, err := loadData(cfg, r, catalog, 0, 0, 100)
	if err != nil {
		t.Fatal(err)
	}
	states := adversaryStates(t, data)
	adversaryNumber(t, adversaryLastAt(t, states, adversaryTime(0)), "long_qty", nil)
	at := adversaryLastAt(t, states, adversaryTime(1))
	adversaryNumber(t, at, "long_qty", 2)
	adversaryNumber(t, at, "realized_pnl_yen", 123)
	adversaryNumber(t, at, "unrealized_pnl_yen", nil)
	adversaryNumber(t, adversaryLastAt(t, states, adversaryTime(4)), "realized_pnl_yen", nil)
}

// TestAdversaryViewerSamplerPreservesCausalState は縮約の極値・null境界・範囲前状態を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAdversaryViewerSamplerPreservesCausalState(t *testing.T) {
	s := newSampler(10, 20, 1, 2)
	input := [][]any{{float64(0), int64(1), 1.0}, {float64(9), int64(2), 2.0}, {float64(11), int64(3), 3.0}, {float64(12), int64(4), 100.0}, {float64(13), int64(5), nil}, {float64(14), int64(6), -50.0}, {float64(15), int64(7), 4.0}, {float64(19), int64(8), 5.0}, {float64(21), int64(9), 999.0}}
	for _, row := range input {
		s.add(row, false)
	}
	out := s.result()
	got := map[float64]bool{}
	for _, row := range out {
		got[row[0].(float64)] = true
	}
	for _, required := range []float64{9, 11, 12, 13, 14, 19} {
		if !got[required] {
			t.Fatalf("縮約で因果状態/極値/null消失: %v", required)
		}
	}
	if got[0] || got[21] {
		t.Fatalf("余分な過去又は未来を表示: %+v", got)
	}
	if out[0][2] != 2.0 {
		t.Fatal("区間始点を未来の初値で埋めている")
	}
	unknown := newSampler(10, 20, 1, 2)
	unknown.add([]any{float64(21), int64(1), 9.0}, false)
	if len(unknown.result()) != 0 {
		t.Fatal("未来にしかない状態を表示範囲へ埋めている")
	}
}

// TestAdversaryViewerGzipAndPhysicalLines はgzipと空行を含む物理行番号が保たれることを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAdversaryViewerGzipAndPhysicalLines(t *testing.T) {
	dir := t.TempDir()
	plain := []byte("{\"n\":1}\n\n{\"n\":3}\n")
	path := filepath.Join(dir, "人工.jsonl.gz")
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	gz := gzip.NewWriter(f)
	if _, err = gz.Write(plain); err != nil {
		t.Fatal(err)
	}
	if err = gz.Close(); err != nil {
		t.Fatal(err)
	}
	if err = f.Close(); err != nil {
		t.Fatal(err)
	}
	lines := []int64{}
	if err = scanJSONL(path, func(n int64, b []byte) error {
		lines = append(lines, n)
		var v map[string]int
		return json.Unmarshal(b, &v)
	}); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(lines, []int64{1, 3}) {
		t.Fatalf("gzip展開後物理行が不一致: %v", lines)
	}
}

// TestAdversaryViewerClockOrderAndNight は夜間・前場の古い板・逆時計の扱いを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAdversaryViewerClockOrderAndNight(t *testing.T) {
	start, end, err := sessionBounds("2026-10-27_Night")
	if err != nil {
		t.Fatal(err)
	}
	if start.Hour() != 17 || end.Day() != 28 || end.Hour() != 6 || end.Sub(start) != 13*time.Hour {
		t.Fatalf("夜間境界不正: %v %v", start, end)
	}
	path := filepath.Join(t.TempDir(), "clock.jsonl")
	times := []time.Time{start.Add(-time.Hour), start, start.Add(time.Second), start, start.Add(time.Second), start.Add(7 * time.Hour)}
	rows := []map[string]any{}
	for _, at := range times {
		r := adversaryBook(0, 105, 100, 110)
		r["CurrentPriceTime"] = at.Format(time.RFC3339Nano)
		rows = append(rows, r)
	}
	rows = append(rows, map[string]any{"CurrentPriceTime": nil})
	adversaryWrite(t, path, rows)
	q := Quality{}
	lines := []int64{}
	if err = readMarket(path, start, end, &q, func(m marketQuote) error { lines = append(lines, m.Line); return nil }); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(lines, []int64{2, 3, 5, 6}) || q.ReversedClockRows != 1 || q.DuplicateClockRows != 1 || q.InvalidClockRows != 1 {
		t.Fatalf("原順序/除外判定不正: %v %+v", lines, q)
	}
}

// TestAdversaryViewerConfigRelativePaths は配布基点の相対パスと前方斜線の可搬性を検査します。
//
// 引数: t(*testing.T)。返り値: なし。カレントディレクトリへ依存しません。
func TestAdversaryViewerConfigRelativePaths(t *testing.T) {
	base := t.TempDir()
	if err := os.MkdirAll(filepath.Join(base, "conf"), 0700); err != nil {
		t.Fatal(err)
	}
	text := "[server]\nlisten = '127.0.0.1:8091'\n[paths]\ndata_root = '資料/future'\nresource_root = 'resources'\ndefault_catalog = '一覧/test.resources.json'\n"
	if err := os.WriteFile(filepath.Join(base, "conf", "viewer.toml"), []byte(text), 0600); err != nil {
		t.Fatal(err)
	}
	c, err := LoadConfig("conf/viewer.toml", base)
	if err != nil {
		t.Fatal(err)
	}
	if c.Paths.DataRoot != filepath.Join(base, "資料", "future") || c.Paths.DefaultCatalog != filepath.Join(base, "resources", "一覧", "test.resources.json") {
		t.Fatalf("相対root解決が不正: %+v", c.Paths)
	}
	p, err := resolvePath(c.Paths.ResourceRoot, "日本語/session/data.jsonl.gz")
	if err != nil || p != filepath.Join(base, "resources", "日本語", "session", "data.jsonl.gz") {
		t.Fatalf("相対データパス不正: %s %v", p, err)
	}
	if _, err = resolvePath(c.Paths.ResourceRoot, "../outside.jsonl"); err == nil {
		t.Fatal("相対root外を受け入れた")
	}
}

// TestAdversaryViewerRangeAndMissingSource は範囲前状態と誤った原行指定を検査します。
//
// 引数: t(*testing.T)。返り値: なし。未来の返済や未来板を表示開始へ運びません。
func TestAdversaryViewerRangeAndMissingSource(t *testing.T) {
	books := []map[string]any{adversaryBook(0, 105, 100, 110), adversaryBook(1, 115, 110, 120), adversaryBook(3, 125, 120, 130), adversaryBook(4, 135, 130, 140)}
	trades := []map[string]any{adversaryTrade("n", "LongN", "A", 1, 2, 2, 120, 0), adversaryTrade("r", "LongR", "A", 4, 2, 4, 130, 0)}
	cfg, r, catalog := adversaryFixture(t, books, trades, "trades")
	data, err := loadData(cfg, r, catalog, millis(adversaryTime(2)), millis(adversaryTime(3)), 10)
	if err != nil {
		t.Fatal(err)
	}
	states := adversaryStates(t, data)
	adversaryNumber(t, adversaryLastAt(t, states, adversaryTime(2)), "long_qty", 2)
	adversaryNumber(t, adversaryLastAt(t, states, adversaryTime(3)), "realized_pnl_yen", 0)
	if len(data.Events) != 0 || data.Summary.LongQty == nil || *data.Summary.LongQty != 2 {
		t.Fatal("表示範囲外の未来返済が混ざりました")
	}

	// ----------------------------------------
	// 原行を示しても時計が合わない場合は正確な同期と称しません。
	trades = []map[string]any{adversaryTrade("n", "LongN", "A", 0, 1, 4, 110, 0)}
	adversaryWrite(t, r.PNLPath, trades)
	data, err = loadData(cfg, r, catalog, 0, 0, 100)
	if err != nil {
		t.Fatal(err)
	}
	states = adversaryStates(t, data)
	adversaryNumber(t, adversaryLastAt(t, states, adversaryTime(0)), "unrealized_pnl_yen", nil)
	matchedWarning := false
	for _, warning := range data.Quality.Warnings {
		if strings.Contains(warning, "一致しない") {
			matchedWarning = true
		}
	}
	if !matchedWarning {
		t.Fatal("原行と時計の不一致を隠しています")
	}
}

// TestAdversaryViewerAPIRejectsChangedBrokenInput は実APIで破損入力をキャッシュ成功へ置き換えないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。外部接続は行わずhttptestのハンドラを使います。
func TestAdversaryViewerAPIRejectsChangedBrokenInput(t *testing.T) {
	cfg, r, _ := adversaryFixture(t, []map[string]any{adversaryBook(0, 105, 100, 110), adversaryBook(1, 125, 120, 130)},
		[]map[string]any{adversaryTrade("n", "LongN", "A", 0, 1, 1, 110, 0), adversaryTrade("r", "LongR", "A", 1, 1, 2, 120, 0)}, "trades")
	cfg.Viewer.CacheMB = 1
	s, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	h := s.Handler()
	body, err := json.Marshal(map[string]any{"catalog": Catalog{SchemaVersion: 1, Resources: []ResourceMeta{r}}})
	if err != nil {
		t.Fatal(err)
	}
	registered := httptest.NewRecorder()
	h.ServeHTTP(registered, httptest.NewRequest(http.MethodPost, "/api/catalogs/load", strings.NewReader(string(body))))
	if registered.Code != 200 {
		t.Fatalf("一覧登録: %d %s", registered.Code, registered.Body.String())
	}
	var catalog CatalogResponse
	if err = json.Unmarshal(registered.Body.Bytes(), &catalog); err != nil {
		t.Fatal(err)
	}
	query := url.Values{"catalog": []string{catalog.CatalogID}, "resource": []string{r.ID}, "width": []string{"100"}}
	endpoint := "/api/data?" + query.Encode()
	first := httptest.NewRecorder()
	h.ServeHTTP(first, httptest.NewRequest(http.MethodGet, endpoint, nil))
	if first.Code != 200 {
		t.Fatalf("表示取得: %d %s", first.Code, first.Body.String())
	}
	var output DataResponse
	if err = json.Unmarshal(first.Body.Bytes(), &output); err != nil {
		t.Fatal(err)
	}
	if output.Summary.Realized == nil || *output.Summary.Realized != 100 {
		t.Fatalf("APIの確定値が不一致: %+v", output.Summary)
	}
	if err = os.WriteFile(r.PNLPath, []byte("{壊れたJSONL\n"), 0600); err != nil {
		t.Fatal(err)
	}
	broken := httptest.NewRecorder()
	h.ServeHTTP(broken, httptest.NewRequest(http.MethodGet, endpoint, nil))
	if broken.Code == 200 || !strings.Contains(broken.Body.String(), "error") {
		t.Fatalf("破損を以前の成功値で隠した: %d %s", broken.Code, broken.Body.String())
	}
}

// TestAdversaryViewerResearchSamples は明示指定時だけ保存サンプルの表示会計を原結果へ照合します。
//
// 引数: t(*testing.T)。返り値: なし。環境変数SESSIONVIEWER_VERIFY_SAMPLES=1が必要です。
// 原板と既存約定を読むだけで、戦略判断・注文・新しい金融再生は行いません。
func TestAdversaryViewerResearchSamples(t *testing.T) {
	if os.Getenv("SESSIONVIEWER_VERIFY_SAMPLES") != "1" {
		t.Skip("保存サンプルの照合は環境変数による明示実行のみ")
	}
	repo, err := filepath.Abs(filepath.Join("..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	var cfg Config
	cfg.BaseDir = repo
	cfg.Paths.ResourceRoot = repo
	cfg.Paths.DataRoot = filepath.Join(filepath.Dir(repo), "JP_OSE_Data", "future")
	catalogPath := filepath.Join(repo, "アルゴリズム調査", "00169_セッションと売買経路の可視化", "比較.resources.json")
	catalog, path, err := readCatalog(cfg, catalogPath)
	if err != nil {
		t.Fatal(err)
	}
	if len(catalog.Resources) != 4 {
		t.Fatalf("固定サンプル数が変更されています: %d", len(catalog.Resources))
	}
	for _, r := range catalog.Resources {
		t.Run(r.ID, func(t *testing.T) {
			sourcePath := filepath.Join(repo, "work", "research168", "r3", "results_late", r.Session+".json")
			b, e := os.ReadFile(sourcePath)
			if e != nil {
				t.Fatal(e)
			}
			var source struct {
				Cases []struct {
					Config struct {
						ID string `json:"id"`
					} `json:"config"`
					Actual struct {
						Realized float64
						Events   []struct {
							Pieces []json.RawMessage
							Order  struct{ Targets []json.RawMessage }
						}
					} `json:"actual"`
				} `json:"cases"`
			}
			if e = json.Unmarshal(b, &source); e != nil {
				t.Fatal(e)
			}
			found := false
			expected := 0.0
			pieces := 0
			for _, c := range source.Cases {
				if c.Config.ID == r.MethodID {
					found = true
					expected = c.Actual.Realized
					for _, event := range c.Actual.Events {
						if len(event.Order.Targets) == 0 {
							pieces++
						} else {
							pieces += len(event.Pieces)
						}
					}
				}
			}
			if !found {
				t.Fatalf("元保存結果に手法IDがありません: %s", r.MethodID)
			}
			if r.Product != "NK225micro" || r.PointValue != 10 || r.PNLBasis != "gross" {
				t.Fatalf("元会計と単位/費用基準が不一致: %+v", r)
			}
			before, err := os.Stat(r.MarketPath)
			if err != nil {
				t.Fatal(err)
			}
			data, err := loadData(cfg, r, path, 0, 0, 500)
			if err != nil {
				t.Fatal(err)
			}
			if data.Summary.Realized == nil || math.Abs(*data.Summary.Realized-expected) > 1e-8 {
				t.Fatalf("アプリ会計と保存Actual不一致: %+v expected=%v", data.Summary, expected)
			}
			if data.Summary.LongQty == nil || data.Summary.ShortQty == nil || *data.Summary.LongQty != 0 || *data.Summary.ShortQty != 0 || data.Summary.Unrealized == nil || *data.Summary.Unrealized != 0 {
				t.Fatalf("保存場末の返済完了と不一致: %+v", data.Summary)
			}
			if len(data.Events) != pieces {
				t.Fatalf("全約定片の表示数不一致: %d/%d", len(data.Events), pieces)
			}
			for _, warning := range data.Quality.Warnings {
				if strings.Contains(warning, "一致しない") || strings.Contains(warning, "source_lineのない") {
					t.Fatalf("原行指定と原板が一致しません: %s", warning)
				}
			}
			if _, err = json.Marshal(data); err != nil {
				t.Fatalf("出力JSONに非有限値: %v", err)
			}
			after, err := os.Stat(r.MarketPath)
			if err != nil || before.Size() != after.Size() || before.ModTime() != after.ModTime() {
				t.Fatal("検査中に原資料が変更されました")
			}
			t.Logf("%s: 原Actual=%+.0f円、表示=%+.0f円、全%d約定片、原板%d行、残玉0", r.MethodID, expected, *data.Summary.Realized, pieces, data.Quality.RawRows)
		})
	}
}
