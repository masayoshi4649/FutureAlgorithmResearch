package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"reflect"
	"testing"
	"time"
)

// barAdversaryServer は一時原資料だけを読む独立APIを作ります。
//
// 引数: t(*testing.T)、books/rows([]map[string]any)、format(string)。返り値: *Server。
func barAdversaryServer(t *testing.T, books, rows []map[string]any, format string) *Server {
	t.Helper()
	cfg, resource, _ := adversaryFixture(t, books, rows, format)
	cfg.Viewer.CacheMB = 8
	s, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	s.catalogs["独立分足"] = CatalogResponse{Resources: []ResourceMeta{resource}}
	return s
}

// barAdversaryGet は列契約を固定せずAPIのJSONを読みます。
//
// 引数: t(*testing.T)、s(*Server)、query(string)、status(int)。返り値: map[string]any。
func barAdversaryGet(t *testing.T, s *Server, query string, status int) map[string]any {
	t.Helper()
	w := httptest.NewRecorder()
	r := httptest.NewRequest(http.MethodGet, "/api/data?catalog="+url.QueryEscape("独立分足")+"&resource="+url.QueryEscape("人工")+"&"+query, nil)
	s.Handler().ServeHTTP(w, r)
	if w.Code != status {
		t.Fatalf("API応答 %d != %d: %s", w.Code, status, w.Body.String())
	}
	var result map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	return result
}

// barAdversaryRows は応答の列名と値を対応づけます。
//
// 引数: t(*testing.T)、data(map[string]any)、key(string)。返り値: []map[string]any。
func barAdversaryRows(t *testing.T, data map[string]any, key string) []map[string]any {
	t.Helper()
	columnKey := "state_columns"
	if key == "candles" {
		columnKey = "candle_columns"
	}
	columns, ok := data[columnKey].([]any)
	if !ok {
		t.Fatalf("列契約なし: %s", columnKey)
	}
	values, ok := data[key].([]any)
	if !ok {
		t.Fatalf("配列なし: %s", key)
	}
	rows := make([]map[string]any, 0, len(values))
	for _, value := range values {
		items, ok := value.([]any)
		if !ok || len(items) != len(columns) {
			t.Fatalf("不正な列: %v", value)
		}
		row := map[string]any{}
		for i, column := range columns {
			row[column.(string)] = items[i]
		}
		rows = append(rows, row)
	}
	return rows
}

// barAdversaryRow は時刻に一致する集計行を返します。
//
// 引数: t(*testing.T)、rows([]map[string]any)、at(time.Time)。返り値: map[string]any。
func barAdversaryRow(t *testing.T, rows []map[string]any, at time.Time) map[string]any {
	t.Helper()
	for _, row := range rows {
		if row["t"] == millis(at) {
			return row
		}
	}
	t.Fatalf("集計時刻が見つかりません: %s", at.Format(time.RFC3339Nano))
	return nil
}

// barAdversaryOHLC は価格四本値を独立期待値と比較します。
//
// 引数: t(*testing.T)、row(map[string]any)、want([4]float64)。返り値: なし。
func barAdversaryOHLC(t *testing.T, row map[string]any, want [4]float64) {
	t.Helper()
	for i, key := range []string{"open", "high", "low", "close"} {
		adversaryNumber(t, row, key, want[i])
	}
}

// TestBarAdversaryOHLCUsesAllRawRows は1画素表示でも区間の全原行を使い、ズームで四本値を変えないことを調べます。
//
// 引数: t(*testing.T)。返り値: なし。同時計の最終原行も終値へ反映します。
func TestBarAdversaryOHLCUsesAllRawRows(t *testing.T) {
	seconds := []int{1, 10, 20, 59, 59, 61, 70, 80, 119, 121, 122}
	prices := []float64{100, 110, 90, 99, 95, 200, 250, 180, 210, 300, 310}
	books := make([]map[string]any, 0, len(seconds))
	for i, at := range seconds {
		books = append(books, adversaryBook(at, prices[i], prices[i]-1, prices[i]+1))
	}
	s := barAdversaryServer(t, books, nil, "trades")
	full := barAdversaryGet(t, s, "interval=1&price=last&width=1", http.StatusOK)
	rows := barAdversaryRows(t, full, "candles")
	first := barAdversaryRow(t, rows, adversaryTime(0))
	barAdversaryOHLC(t, first, [4]float64{100, 110, 90, 95})
	adversaryNumber(t, first, "end_ms", millis(adversaryTime(60)))
	barAdversaryOHLC(t, barAdversaryRow(t, rows, adversaryTime(60)), [4]float64{200, 250, 180, 210})
	barAdversaryOHLC(t, barAdversaryRow(t, rows, adversaryTime(120)), [4]float64{300, 310, 300, 310})
	zoom := barAdversaryGet(t, s, fmt.Sprintf("interval=1&price=last&width=1200&from=%.0f&to=%.0f", millis(adversaryTime(15)), millis(adversaryTime(25))), http.StatusOK)
	zoomFirst := barAdversaryRow(t, barAdversaryRows(t, zoom, "candles"), adversaryTime(0))
	if !reflect.DeepEqual(first, zoomFirst) {
		t.Fatalf("ズームで四本値が変わりました: %v/%v", first, zoomFirst)
	}
	for _, interval := range []int{5, 15} {
		data := barAdversaryGet(t, s, fmt.Sprintf("interval=%d&price=last&width=1", interval), http.StatusOK)
		row := barAdversaryRow(t, barAdversaryRows(t, data, "candles"), adversaryTime(0))
		barAdversaryOHLC(t, row, [4]float64{100, 310, 90, 310})
		adversaryNumber(t, row, "end_ms", millis(adversaryTime(interval*60)))
	}
}

// TestBarAdversaryStateUsesLastValue は区間中の最大枚数・最大利益でなく区間最後の全状態を採用するか調べます。
//
// 引数: t(*testing.T)。返り値: なし。分境界の新規は次の区間へ帰属します。
func TestBarAdversaryStateUsesLastValue(t *testing.T) {
	seconds := []int{1, 20, 40, 59, 60, 61, 119, 120}
	prices := []float64{100, 110, 90, 95, 100, 98, 110, 110}
	books := make([]map[string]any, 0, len(seconds))
	for i, at := range seconds {
		books = append(books, adversaryBook(at, prices[i], prices[i]-1, prices[i]+1))
	}
	trades := []map[string]any{
		adversaryTrade("入1", "LongN", "買玉", 1, 8, 1, 100, 0),
		adversaryTrade("返1", "LongR", "買玉", 20, 2, 2, 110, 0),
		adversaryTrade("入2", "ShortN", "売玉", 40, 4, 3, 90, 0),
		adversaryTrade("返2", "LongR", "買玉", 59, 6, 4, 95, 0),
		adversaryTrade("入3", "LongN", "次買玉", 60, 3, 5, 100, 0),
		adversaryTrade("返3", "ShortR", "売玉", 119, 4, 7, 110, 0),
		adversaryTrade("返4", "LongR", "次買玉", 120, 3, 8, 110, 0),
	}
	s := barAdversaryServer(t, books, trades, "trades")
	data := barAdversaryGet(t, s, "interval=1&width=1", http.StatusOK)
	rows := barAdversaryRows(t, data, "states")
	first := barAdversaryRow(t, rows, adversaryTime(60))
	for key, want := range map[string]any{"long_qty": 0, "short_qty": 4, "realized_pnl_yen": -100, "unrealized_pnl_yen": -240} {
		adversaryNumber(t, first, key, want)
	}
	second := barAdversaryRow(t, rows, adversaryTime(120))
	for key, want := range map[string]any{"long_qty": 3, "short_qty": 0, "realized_pnl_yen": -900, "unrealized_pnl_yen": 270} {
		adversaryNumber(t, second, key, want)
	}
	third := barAdversaryRow(t, rows, adversaryTime(180))
	for key, want := range map[string]any{"long_qty": 0, "short_qty": 0, "realized_pnl_yen": -600, "unrealized_pnl_yen": 0} {
		adversaryNumber(t, third, key, want)
	}
}

// TestBarAdversarySnapshotUnknownIsFinal は最後のnullを早い時刻の既知値で置き換えないか調べます。
//
// 引数: t(*testing.T)。返り値: なし。snapshot観測終了後は全列未知です。
func TestBarAdversarySnapshotUnknownIsFinal(t *testing.T) {
	snapshot := func(second, qty int, realized float64, unrealized any) map[string]any {
		return map[string]any{"timestamp": adversaryTime(second).Format(time.RFC3339Nano), "long_qty": qty, "short_qty": 0, "realized_pnl_yen": realized, "unrealized_pnl_yen": unrealized}
	}
	s := barAdversaryServer(t, []map[string]any{adversaryBook(1, 100, 99, 101), adversaryBook(180, 110, 109, 111)}, []map[string]any{snapshot(10, 5, 100, 1000), snapshot(50, 1, 50, nil), snapshot(65, 2, 100, 500), snapshot(110, 0, -30, 0)}, "snapshots")
	data := barAdversaryGet(t, s, "interval=1", http.StatusOK)
	rows := barAdversaryRows(t, data, "states")
	first := barAdversaryRow(t, rows, adversaryTime(60))
	adversaryNumber(t, first, "long_qty", 1)
	adversaryNumber(t, first, "realized_pnl_yen", 50)
	adversaryNumber(t, first, "unrealized_pnl_yen", nil)
	second := barAdversaryRow(t, rows, adversaryTime(120))
	for _, key := range []string{"long_qty", "short_qty", "realized_pnl_yen", "unrealized_pnl_yen"} {
		adversaryNumber(t, second, key, nil)
	}
}

// TestBarAdversaryPriceModesAndCache は価格種類・時間足ごとに完成応答のキャッシュを分離するか調べます。
//
// 引数: t(*testing.T)。返り値: なし。未知の種類を暗黙の既定値へ丸めません。
func TestBarAdversaryPriceModesAndCache(t *testing.T) {
	s := barAdversaryServer(t, []map[string]any{adversaryBook(1, 100, 200, 220), adversaryBook(2, 110, 190, 250)}, nil, "trades")
	for _, mode := range []struct {
		name string
		want [4]float64
	}{{"last", [4]float64{100, 110, 100, 110}}, {"bid", [4]float64{200, 200, 190, 190}}, {"ask", [4]float64{220, 250, 220, 250}}, {"mid", [4]float64{210, 220, 210, 220}}} {
		data := barAdversaryGet(t, s, "interval=1&price="+mode.name, http.StatusOK)
		if data["interval"] != "1" || data["candle_price"] != mode.name {
			t.Fatalf("表示種類の応答が不一致: %v/%v", data["interval"], data["candle_price"])
		}
		barAdversaryOHLC(t, barAdversaryRow(t, barAdversaryRows(t, data, "candles"), adversaryTime(0)), mode.want)
	}
	data := barAdversaryGet(t, s, "interval=15&price=last", http.StatusOK)
	adversaryNumber(t, barAdversaryRow(t, barAdversaryRows(t, data, "candles"), adversaryTime(0)), "end_ms", millis(adversaryTime(15*60)))
	raw := barAdversaryGet(t, s, "interval=raw", http.StatusOK)
	if raw["interval"] != "raw" {
		t.Fatalf("raw表示種別が不一致: %v", raw["interval"])
	}
	if prices, ok := raw["prices"].([]any); !ok || len(prices) == 0 {
		t.Fatal("raw価格が消えました")
	}
	barAdversaryGet(t, s, "interval=2", http.StatusBadRequest)
	barAdversaryGet(t, s, "interval=1&price=未知", http.StatusBadRequest)
}

// TestBarAdversaryNightAndTerminal は日本時間の午前0時と場終端の帰属を確認します。
//
// 引数: t(*testing.T)。返り値: なし。06:00ちょうどの原行は最後の15分足に入ります。
func TestBarAdversaryNightAndTerminal(t *testing.T) {
	at := func(text string) time.Time {
		value, err := time.Parse(time.RFC3339Nano, text)
		if err != nil {
			t.Fatal(err)
		}
		return value
	}
	quote := func(text string, last float64) map[string]any {
		return map[string]any{"CurrentPriceTime": text, "CurrentPrice": last, "Buy1": map[string]any{"Price": last - 1}, "Sell1": map[string]any{"Price": last + 1}}
	}
	books := []map[string]any{
		quote("2026-10-27T23:59:50+09:00", 100),
		quote("2026-10-27T23:59:59+09:00", 110),
		quote("2026-10-28T00:00:00+09:00", 200),
		quote("2026-10-28T00:00:01+09:00", 190),
		quote("2026-10-28T05:59:59+09:00", 300),
		quote("2026-10-28T06:00:00+09:00", 350),
		quote("2026-10-28T06:00:01+09:00", 999),
	}
	cfg, resource, _ := adversaryFixture(t, books, nil, "trades")
	resource.Session = "2026-10-27_Night"
	s, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	s.catalogs["独立分足"] = CatalogResponse{Resources: []ResourceMeta{resource}}
	data := barAdversaryGet(t, s, "interval=15", http.StatusOK)
	rows := barAdversaryRows(t, data, "candles")
	before := barAdversaryRow(t, rows, at("2026-10-27T23:45:00+09:00"))
	barAdversaryOHLC(t, before, [4]float64{100, 110, 100, 110})
	adversaryNumber(t, before, "end_ms", millis(at("2026-10-28T00:00:00+09:00")))
	barAdversaryOHLC(t, barAdversaryRow(t, rows, at("2026-10-28T00:00:00+09:00")), [4]float64{200, 200, 190, 190})
	last := barAdversaryRow(t, rows, at("2026-10-28T05:45:00+09:00"))
	barAdversaryOHLC(t, last, [4]float64{300, 350, 300, 350})
	adversaryNumber(t, last, "end_ms", millis(at("2026-10-28T06:00:00+09:00")))
	for _, row := range rows {
		if row["t"].(float64) >= millis(at("2026-10-28T06:00:00+09:00")) {
			t.Fatalf("場外の足を作りました: %v", row)
		}
	}
}

// TestBarAdversaryMissingPriceStaysMissing は欠測区間や片側欠測時の中値を補完しないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。Lastと気配中値の有効性は区別します。
func TestBarAdversaryMissingPriceStaysMissing(t *testing.T) {
	books := []map[string]any{
		adversaryBook(1, 100, 99, 101),
		adversaryBook(120, 200, 199, 201),
		adversaryBook(130, 250, nil, 200),
	}
	s := barAdversaryServer(t, books, nil, "trades")
	data := barAdversaryGet(t, s, "interval=1&price=last", http.StatusOK)
	rows := barAdversaryRows(t, data, "candles")
	empty := barAdversaryRow(t, rows, adversaryTime(60))
	for _, key := range []string{"open", "high", "low", "close"} {
		adversaryNumber(t, empty, key, nil)
	}
	barAdversaryOHLC(t, barAdversaryRow(t, rows, adversaryTime(120)), [4]float64{200, 250, 200, 250})
	data = barAdversaryGet(t, s, "interval=1&price=mid", http.StatusOK)
	rows = barAdversaryRows(t, data, "candles")
	barAdversaryOHLC(t, barAdversaryRow(t, rows, adversaryTime(120)), [4]float64{200, 200, 200, 200})
}

// TestBarAdversaryCrossedMidIsUnknown は交差板の派生中値を未知とし、観測価格を消さないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。Bid/Ask/Lastの原値と派生Midを区別します。
func TestBarAdversaryCrossedMidIsUnknown(t *testing.T) {
	s := barAdversaryServer(t, []map[string]any{
		adversaryBook(1, 100, 99, 101),
		adversaryBook(61, 110, 120, 100),
		adversaryBook(121, 120, 119, 121),
	}, nil, "trades")
	data := barAdversaryGet(t, s, "interval=1&price=mid", http.StatusOK)
	row := barAdversaryRow(t, barAdversaryRows(t, data, "candles"), adversaryTime(60))
	for _, key := range []string{"open", "high", "low", "close"} {
		adversaryNumber(t, row, key, nil)
	}
	for mode, price := range map[string]float64{"last": 110, "bid": 120, "ask": 100} {
		data = barAdversaryGet(t, s, "interval=1&price="+mode, http.StatusOK)
		barAdversaryOHLC(t, barAdversaryRow(t, barAdversaryRows(t, data, "candles"), adversaryTime(60)), [4]float64{price, price, price, price})
	}
}
