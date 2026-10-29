package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestTraderDetachDoesNotRealize は部分移管と全移管を架空決済・費用計上にしないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。指定数量の超過・不明玉も拒否します。
func TestTraderDetachDoesNotRealize(t *testing.T) {
	l := newDisplayLedger(ResourceMeta{PointValue: 10, PNLBasis: "net"})
	if _, err := l.apply(Trade{Type: "LongN", PositionID: "買玉", Price: 100, Qty: 3, FeeYen: 2}); err != nil {
		t.Fatal(err)
	}
	if _, err := l.apply(Trade{Type: "ShortN", PositionID: "売玉", Price: 120, Qty: 2, FeeYen: 3}); err != nil {
		t.Fatal(err)
	}
	before := l.Realized
	if delta, err := l.apply(Trade{Type: "Detach", PositionID: "買玉", Qty: 2}); err != nil || delta != 0 || l.Realized != before || l.Positions["買玉"].Qty != 1 {
		t.Fatalf("部分移管を売買にしました: %v %v %+v", delta, err, l)
	}
	for _, bad := range []Trade{
		{Type: "Detach", PositionID: "不明", Qty: 1}, {Type: "Detach", PositionID: "買玉", Qty: 2},
		{Type: "Detach", PositionID: "買玉", Qty: 1, Price: 100}, {Type: "Detach", PositionID: "買玉", Qty: 1, FeeYen: 1},
	} {
		if _, err := l.apply(bad); err == nil {
			t.Fatalf("不正移管を通しました: %+v", bad)
		}
	}
	if _, err := l.apply(Trade{Type: "Detach", PositionID: "買玉", Qty: 1}); err != nil {
		t.Fatal(err)
	}
	if _, err := l.apply(Trade{Type: "Detach", PositionID: "売玉", Qty: 2}); err != nil {
		t.Fatal(err)
	}
	s := l.mark(nil)
	if *s.LongQty != 0 || *s.ShortQty != 0 || *s.Realized != before || s.Unrealized == nil || *s.Unrealized != 0 {
		t.Fatalf("管理外玉を保有へ含めました: %+v", s)
	}
}

// TestTraderEntryMethodOwnsAllPositionEvents は入口手法による抽出が異手法返済と移管を落とさないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。同じJSONLを合計・手法別・費用別へ使い、元行順を保持します。
func TestTraderEntryMethodOwnsAllPositionEvents(t *testing.T) {
	books := []map[string]any{}
	for i := 0; i < 5; i++ {
		books = append(books, adversaryBook(i, 100+i, 100+i, 110+i))
	}
	rows := []map[string]any{
		adversaryTrade("A新規", "LongN", "A玉", 0, 3, 1, 100, 2),
		adversaryTrade("B新規", "ShortN", "B玉", 1, 2, 2, 120, 3),
		adversaryTrade("A返済", "LongR", "A玉", 2, 1, 3, 110, 1),
		adversaryTrade("A移管", "Detach", "A玉", 3, 2, 0, 0, 0),
		adversaryTrade("B返済", "ShortR", "B玉", 4, 2, 5, 115, 4),
	}
	for i, method := range []string{"A", "B", "B", "A", "A"} {
		rows[i]["method_id"] = method
	}
	delete(rows[3], "price")
	cfg, r, path := adversaryFixture(t, books, rows, "trades")
	r.MethodID = "*"
	for _, basis := range []string{"gross", "net"} {
		for _, tc := range []struct {
			method     string
			gross, net float64
			count      int
		}{{"", 200, 190, 5}, {"A", 100, 97, 3}, {"B", 100, 93, 2}} {
			r.EntryMethodID, r.PNLBasis = tc.method, basis
			data, err := loadData(cfg, r, path, 0, 0, 200)
			if err != nil {
				t.Fatal(tc.method, basis, err)
			}
			want := tc.gross
			if basis == "net" {
				want = tc.net
			}
			if *data.Summary.Realized != want || *data.Summary.LongQty != 0 || *data.Summary.ShortQty != 0 || len(data.Events) != tc.count {
				t.Fatalf("帰属・損益不一致 %s/%s: %+v events=%v", tc.method, basis, data.Summary, data.Events)
			}
			if tc.method == "A" {
				foundWarning := false
				for _, warning := range data.Quality.Warnings {
					foundWarning = foundWarning || strings.Contains(warning, "管理外移管は返済・利確ではありません")
				}
				if !foundWarning {
					t.Fatal("移管を返済と区別する説明がありません")
				}
				if data.Events[1].MethodID != "B" || data.Events[1].Sequence != 3 || data.Events[2].Type != "Detach" || data.Events[2].Sequence != 4 {
					t.Fatalf("当時手法又は順序を変更しました: %+v", data.Events)
				}
				b, err := json.Marshal(data.Events[2])
				if err != nil {
					t.Fatal(err)
				}
				if strings.Contains(string(b), `"price"`) || data.Events[2].RealizedDelta != 0 {
					t.Fatalf("移管を約定としました: %s", b)
				}
			}
		}
	}
	all, err := readTrades(r.PNLPath, adversaryTime(0), adversaryTime(25200))
	if err != nil {
		t.Fatal(err)
	}
	if got := entryMethodTrades(all, "未登録"); len(got) != 0 {
		t.Fatal("未知手法へ別の玉を入れました")
	}
	// 同じIDへの後続追加も、最初の新規手法から動かしません。
	all = append(all, Trade{ID: "再新規", Type: "LongN", PositionID: "A玉", MethodID: "B"})
	if len(entryMethodTrades(all, "A")) != 4 || len(entryMethodTrades(all, "B")) != 2 {
		t.Fatal("建玉帰属を途中で変更しました")
	}
}

// TestTraderEntryFilterCacheIsIndependent は同一JSONLの合計と入口手法別を同じキャッシュへ混在させません。
//
// 引数: t(*testing.T)。返り値: なし。資源ID以外も同じ場合に抽出条件をキーへ含めることを検査します。
func TestTraderEntryFilterCacheIsIndependent(t *testing.T) {
	books := []map[string]any{adversaryBook(0, 100, 100, 110), adversaryBook(1, 120, 120, 130)}
	rows := []map[string]any{
		adversaryTrade("A新規", "LongN", "A玉", 0, 1, 1, 100, 0), adversaryTrade("B新規", "LongN", "B玉", 0, 2, 1, 105, 0),
		adversaryTrade("A返済", "LongR", "A玉", 1, 1, 2, 120, 0), adversaryTrade("B返済", "LongR", "B玉", 1, 2, 2, 120, 0),
	}
	for i, method := range []string{"A", "B", "B", "A"} {
		rows[i]["method_id"] = method
	}
	cfg, r, _ := adversaryFixture(t, books, rows, "trades")
	cfg.Viewer.CacheMB = 1
	s, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		method string
		want   float64
	}{{"", 500}, {"A", 200}, {"B", 300}, {"", 500}} {
		r.EntryMethodID = tc.method
		s.catalogs["同じ一覧"] = CatalogResponse{Resources: []ResourceMeta{r}}
		w := httptest.NewRecorder()
		query := url.Values{"catalog": {"同じ一覧"}, "resource": {r.ID}}
		s.Handler().ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/api/data?"+query.Encode(), nil))
		if w.Code != 200 {
			t.Fatal(w.Code, w.Body.String())
		}
		var d DataResponse
		if err = json.Unmarshal(w.Body.Bytes(), &d); err != nil {
			t.Fatal(err)
		}
		if d.Summary.Realized == nil || *d.Summary.Realized != tc.want || d.Resource.EntryMethodID != tc.method {
			t.Fatalf("抽出キャッシュが混在しました: %s %+v", tc.method, d.Summary)
		}
	}
}

// TestTraderDetachReadValidation は移管の価格・費用・数量の契約をJSONL入力で検査します。
//
// 引数: t(*testing.T)。返り値: なし。価格省略は許可し、実約定の価格省略は拒否します。
func TestTraderDetachReadValidation(t *testing.T) {
	for _, tc := range []struct {
		kind       string
		price, fee any
		qty        int
		valid      bool
	}{{"Detach", nil, 0, 1, true}, {"Detach", 100, 0, 1, false}, {"Detach", 0, 1, 1, false}, {"Detach", 0, 0, 0, false}, {"LongN", nil, 0, 1, false}} {
		row := adversaryTrade("入力", tc.kind, "所有", 0, tc.qty, 0, 0, 0)
		if tc.price == nil {
			delete(row, "price")
		} else {
			row["price"] = tc.price
		}
		row["fee_yen"] = tc.fee
		path := filepath.Join(t.TempDir(), "input.jsonl")
		adversaryWrite(t, path, []map[string]any{row})
		_, err := readTrades(path, adversaryTime(0), adversaryTime(60))
		if (err == nil) != tc.valid {
			t.Fatalf("入力検証が不一致: %+v %v", tc, err)
		}
	}
}

// TestTraderCatalogMovesWithItsFiles は実在一覧の位置を優先し、アップロードだけ明示基準を使うことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。従来resource_root相対と原板data_root基準も維持します。
func TestTraderCatalogMovesWithItsFiles(t *testing.T) {
	cfg, c := apiFixture(t)
	c.PathBase = "catalog"
	c.BaseDir = filepath.Join(t.TempDir(), "移動前")
	dir := t.TempDir()
	catalogPath := filepath.Join(dir, "moved.resources.json")
	raw, err := json.Marshal(c)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(catalogPath, raw, 0600); err != nil {
		t.Fatal(err)
	}
	loaded, _, err := readCatalog(cfg, catalogPath)
	if err != nil {
		t.Fatal(err)
	}
	if loaded.Resources[0].PNLPath != filepath.Join(dir, "trades.jsonl") {
		t.Fatal("一覧の実在場所を優先しません", loaded.Resources[0].PNLPath)
	}
	if loaded.Resources[0].MarketPath != filepath.Join(cfg.Paths.DataRoot, "NK225", "2026-10-27_Day", "book.jsonl") {
		t.Fatal("原板相対基準を変えました")
	}
	uploaded, err := validateCatalog(cfg, c)
	if err != nil {
		t.Fatal(err)
	}
	if uploaded.Resources[0].PNLPath != filepath.Join(c.BaseDir, "trades.jsonl") {
		t.Fatal("アップロード明示基準を使いません")
	}
	c.BaseDir = ""
	if _, err = validateCatalog(cfg, c); err == nil {
		t.Fatal("位置不明のアップロードを受けました")
	}
	c.BaseDir = "relative"
	if _, err = validateCatalog(cfg, c); err == nil {
		t.Fatal("相対base_dirを受けました")
	}
	if _, _, err = readCatalog(cfg, catalogPath); err != nil {
		t.Fatal("実在一覧の移動互換を壊しました", err)
	}
	c.PathBase, c.BaseDir = "", ""
	legacy, err := validateCatalog(cfg, c)
	if err != nil {
		t.Fatal(err)
	}
	if legacy.Resources[0].PNLPath != filepath.Join(cfg.Paths.ResourceRoot, "trades.jsonl") {
		t.Fatal("旧相対基準を変えました")
	}
}

// TestTraderCatalogUploadErrorsRemainJSON はリンク一覧アップロードの位置不足をRESTで明確に拒否します。
//
// 引数: t(*testing.T)。返り値: なし。新規フィールドを未知キーとして拒否しないことも検査します。
func TestTraderCatalogUploadErrorsRemainJSON(t *testing.T) {
	cfg, c := apiFixture(t)
	c.PathBase = "catalog"
	s, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		base   string
		status int
	}{{"", 400}, {cfg.Paths.ResourceRoot, 200}} {
		c.BaseDir = tc.base
		raw, _ := json.Marshal(map[string]any{"catalog": c})
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/api/catalogs/load", bytes.NewReader(raw)))
		if w.Code != tc.status {
			t.Fatal(w.Code, w.Body.String())
		}
		if w.Code == 400 && !strings.Contains(w.Body.String(), "base_dir") {
			t.Fatal(w.Body.String())
		}
	}
}
