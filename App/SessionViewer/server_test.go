package main

import (
	"bytes"
	"compress/gzip"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// apiFixture はAPIだけを検査する小さな保存ファイルを作ります。
//
// 引数: t(*testing.T)。返り値: Config、未解決Catalog。
func apiFixture(t *testing.T) (Config, Catalog) {
	t.Helper()
	d := t.TempDir()
	var c Config
	c.Paths.DataRoot = filepath.Join(d, "raw")
	c.Paths.ResourceRoot = filepath.Join(d, "resources")
	c.Viewer.CacheMB = 1
	market := filepath.Join(c.Paths.DataRoot, "NK225", "2026-10-27_Day", "book.jsonl")
	for _, p := range []string{filepath.Dir(market), c.Paths.ResourceRoot} {
		if err := os.MkdirAll(p, 0700); err != nil {
			t.Fatal(err)
		}
	}
	raw := "{\"CurrentPriceTime\":\"2026-10-27T08:45:00+09:00\",\"CurrentPrice\":100,\"Buy1\":{\"Price\":100},\"Sell1\":{\"Price\":110}}\n{\"CurrentPriceTime\":\"2026-10-27T08:45:01+09:00\",\"CurrentPrice\":120,\"Buy1\":{\"Price\":120},\"Sell1\":{\"Price\":130}}\n"
	trades := "{\"id\":\"n\",\"timestamp\":\"2026-10-27T08:45:00+09:00\",\"type\":\"LongN\",\"position_id\":\"p\",\"qty\":2,\"price\":110,\"source_line\":1}\n{\"id\":\"c\",\"timestamp\":\"2026-10-27T08:45:01+09:00\",\"type\":\"LongR\",\"position_id\":\"p\",\"qty\":2,\"price\":120,\"source_line\":2}\n"
	if err := os.WriteFile(market, []byte(raw), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(c.Paths.ResourceRoot, "trades.jsonl"), []byte(trades), 0600); err != nil {
		t.Fatal(err)
	}
	cat := Catalog{SchemaVersion: 1, Resources: []ResourceMeta{{ID: "人工", Symbol: "NK225", Session: "2026-10-27_Day", PointValue: 10, PNLFormat: "trades", PNLBasis: "gross", PNLPath: "trades.jsonl"}}}
	return c, cat
}

// TestViewerAPIAndGzipCache は登録一覧、HTTP圧縮、キャッシュ更新、原資料不変を確認します。
//
// 引数: t(*testing.T)。返り値: なし。人工ファイルだけを読みます。
func TestViewerAPIAndGzipCache(t *testing.T) {
	cfg, cat := apiFixture(t)
	s, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	b, _ := json.Marshal(map[string]any{"catalog": cat})
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/api/catalogs/load", bytes.NewReader(b)))
	if w.Code != 200 {
		t.Fatal(w.Code, w.Body.String())
	}
	var loaded CatalogResponse
	if err := json.Unmarshal(w.Body.Bytes(), &loaded); err != nil {
		t.Fatal(err)
	}
	url := "/api/data?catalog=" + loaded.CatalogID + "&resource=%E4%BA%BA%E5%B7%A5&width=1"
	req := httptest.NewRequest(http.MethodGet, url, nil)
	req.Header.Set("Accept-Encoding", "gzip")
	w = httptest.NewRecorder()
	s.Handler().ServeHTTP(w, req)
	if w.Code != 200 || w.Header().Get("Content-Encoding") != "gzip" {
		t.Fatal(w.Code, w.Body.String())
	}
	gz, err := gzip.NewReader(w.Body)
	if err != nil {
		t.Fatal(err)
	}
	data, err := io.ReadAll(gz)
	if err != nil {
		t.Fatal(err)
	}
	_ = gz.Close()
	var out DataResponse
	if err := json.Unmarshal(data, &out); err != nil {
		t.Fatal(err)
	}
	if out.Summary.Realized == nil || *out.Summary.Realized != 200 || len(out.Events) != 2 {
		t.Fatalf("会計API: %+v", out)
	}
	if s.cacheBytes <= 0 || s.cacheBytes > 1024*1024 {
		t.Fatal("キャッシュ枠", s.cacheBytes)
	}
	pnl := filepath.Join(cfg.Paths.ResourceRoot, "trades.jsonl")
	original, _ := os.ReadFile(pnl)
	if err := os.WriteFile(pnl, append(original, []byte("{不正}\n")...), 0600); err != nil {
		t.Fatal(err)
	}
	w = httptest.NewRecorder()
	s.Handler().ServeHTTP(w, httptest.NewRequest(http.MethodGet, url, nil))
	if w.Code != 422 {
		t.Fatalf("更新後の不正ファイルを旧キャッシュで隠した: %d", w.Code)
	}
	items, err := os.ReadDir(cfg.Paths.ResourceRoot)
	if err != nil || len(items) != 1 {
		t.Fatal("生成物を作った", items, err)
	}
}

// TestViewerCatalogRestrictions は一覧拡張子・相対親抜け・定義欠測を拒否します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestViewerCatalogRestrictions(t *testing.T) {
	cfg, cat := apiFixture(t)
	if _, _, err := readCatalog(cfg, "trades.jsonl"); err == nil {
		t.Fatal("任意ファイルを一覧として許可")
	}
	if _, err := resolvePath(cfg.Paths.ResourceRoot, "../外部.jsonl"); err == nil {
		t.Fatal("相対親抜けを許可")
	}
	bad := cat
	bad.Resources = append([]ResourceMeta(nil), cat.Resources...)
	bad.Resources[0].PointValue = 0
	if _, err := validateCatalog(cfg, bad); err == nil {
		t.Fatal("点価欠測を許可")
	}
	s, _ := NewServer(cfg)
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/api/data?symbol=NK225&session=../../bad", nil))
	if w.Code != 400 {
		t.Fatal(w.Code)
	}
	w = httptest.NewRecorder()
	s.Handler().ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/api/catalogs/load", strings.NewReader(`{"path":"a.resources.json","catalog":{"schema_version":1}}`)))
	if w.Code != 400 {
		t.Fatal(w.Code)
	}
}

// TestViewerMemoryLRUEvicts はキャッシュの上限と最近使用順を検査します。
//
// 引数: t(*testing.T)。返り値: なし。キャッシュファイルは作りません。
func TestViewerMemoryLRUEvicts(t *testing.T) {
	cfg, _ := apiFixture(t)
	s, _ := NewServer(cfg)
	payload := make([]byte, 400*1024)
	s.remember("1", payload)
	s.remember("2", payload)
	s.cached("1")
	s.remember("3", payload)
	if _, ok := s.cached("2"); ok {
		t.Fatal("最古のキャッシュが残った")
	}
	if _, ok := s.cached("1"); !ok {
		t.Fatal("最近のキャッシュが消えた")
	}
	s.remember("巨大", make([]byte, 2*1024*1024))
	if s.cacheBytes > 1024*1024 {
		t.Fatal("キャッシュ上限超過")
	}
}
