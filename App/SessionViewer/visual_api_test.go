package main

import (
	"encoding/json"
	"fmt"
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

// visualAPIRequest は読取専用APIをネットワーク接続せず実行します。
//
// 引数: s(*Server)、path(string)。返り値: *httptest.ResponseRecorder。
func visualAPIRequest(s *Server, path string) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, httptest.NewRequest(http.MethodGet, path, nil))
	return w
}

// visualAPIFixture は既存の最小原板・約定へ、直接指定できる一覧ファイルだけを追加します。
//
// 引数: t(*testing.T)。返り値: Config、*Server、一覧相対名(string)。
func visualAPIFixture(t *testing.T) (Config, *Server, string) {
	t.Helper()
	cfg, catalog := apiFixture(t)
	path := "人工.resources.json"
	body, err := json.Marshal(catalog)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(filepath.Join(cfg.Paths.ResourceRoot, path), body, 0600); err != nil {
		t.Fatal(err)
	}
	cfg.Paths.DefaultCatalog = path
	s, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	return cfg, s, path
}

// TestVisualAPIResourcesAndMetadata はPOST不要の列挙から同一データURLまで照合します。
//
// 引数: t(*testing.T)。返り値: なし。画像用heightが数値系列やキャッシュを変えないことも確認します。
func TestVisualAPIResourcesAndMetadata(t *testing.T) {
	cfg, s, path := visualAPIFixture(t)
	listed := visualAPIRequest(s, "/api/resources")
	var catalog CatalogResponse
	if listed.Code != 200 || json.Unmarshal(listed.Body.Bytes(), &catalog) != nil || catalog.CatalogID == "" || len(catalog.Resources) != 1 {
		t.Fatalf("一覧取得: %d %s", listed.Code, listed.Body.String())
	}
	direct := "/api/chart?" + url.Values{"catalog_path": {path}, "resource": {"人工"}, "interval": {"1"}, "width": {"800"}, "height": {"700"}}.Encode()
	w := visualAPIRequest(s, direct)
	var meta struct {
		DataHash      string `json:"data_sha256"`
		DataURL       string `json:"data_url"`
		SVGURL        string `json:"svg_url"`
		PNGURL        string `json:"png_url"`
		Width, Height int
		Summary       DataSummary
		Files         DataFiles
		Events        []ViewEvent
	}
	if w.Code != 200 || json.Unmarshal(w.Body.Bytes(), &meta) != nil {
		t.Fatalf("画像メタ: %d %s", w.Code, w.Body.String())
	}
	if len(meta.DataHash) != 64 || meta.Width != 800 || meta.Height != 700 || meta.Summary.Realized == nil || *meta.Summary.Realized != 200 || len(meta.Events) != 2 || meta.Files.PNL == "" {
		t.Fatalf("根拠不足: %s", w.Body.String())
	}
	if w.Header().Get("X-Chart-Data-SHA256") != meta.DataHash {
		t.Fatal("メタの指紋が不一致")
	}
	data := visualAPIRequest(s, meta.DataURL)
	if data.Code != 200 || dataDigest(data.Body.Bytes()) != meta.DataHash || data.Header().Get("X-Chart-Data-SHA256") != meta.DataHash {
		t.Fatalf("数値の指紋不一致: %d %s", data.Code, data.Body.String())
	}
	if len(s.cache) != 1 {
		t.Fatalf("同じ元系列を二重保存: %d", len(s.cache))
	}
	byID := visualAPIRequest(s, "/api/resources?catalog="+catalog.CatalogID)
	if byID.Code != 200 || !reflect.DeepEqual(byID.Body.Bytes(), listed.Body.Bytes()) {
		t.Fatalf("runtimeID一覧: %d %s", byID.Code, byID.Body.String())
	}
	otherHeight := visualAPIRequest(s, strings.Replace(direct, "height=700", "height=900", 1))
	if otherHeight.Code != 200 || len(s.cache) != 1 {
		t.Fatal("画像の高さでデータを重複取得しました")
	}
	for _, name := range []string{meta.DataURL, meta.SVGURL, meta.PNGURL} {
		u, err := url.Parse(name)
		if err != nil || u.Query().Get("data_sha256") != meta.DataHash {
			t.Fatalf("同一指紋の取得先がありません: %s", name)
		}
	}
	files, err := os.ReadDir(cfg.Paths.ResourceRoot)
	if err != nil || len(files) != 2 {
		t.Fatal("メタAPIが派生ファイルを保存しました", files, err)
	}
}

// TestVisualAPIRejectsUpdatedData は画像と数値の間に入力が変わった場合を409へ分離します。
//
// 引数: t(*testing.T)。返り値: なし。元の指紋を偽装して新しい画像を返しません。
func TestVisualAPIRejectsUpdatedData(t *testing.T) {
	cfg, s, path := visualAPIFixture(t)
	q := url.Values{"catalog_path": {path}, "resource": {"人工"}, "width": {"800"}, "height": {"700"}}
	w := visualAPIRequest(s, "/api/chart?"+q.Encode())
	var meta struct {
		DataURL string `json:"data_url"`
		PNGURL  string `json:"png_url"`
		SVGURL  string `json:"svg_url"`
	}
	if w.Code != 200 || json.Unmarshal(w.Body.Bytes(), &meta) != nil {
		t.Fatalf("メタ取得: %d %s", w.Code, w.Body.String())
	}
	market := filepath.Join(cfg.Paths.DataRoot, "NK225", "2026-10-27_Day", "book.jsonl")
	body, err := os.ReadFile(market)
	if err != nil {
		t.Fatal(err)
	}
	body = []byte(strings.Replace(string(body), `"CurrentPrice":120`, `"CurrentPrice":121`, 1))
	if err = os.WriteFile(market, body, 0600); err != nil {
		t.Fatal(err)
	}
	at := time.Now().Add(time.Second)
	if err = os.Chtimes(market, at, at); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{meta.DataURL, meta.PNGURL, meta.SVGURL} {
		got := visualAPIRequest(s, path)
		if got.Code != 409 || !strings.Contains(got.Body.String(), "メタ情報") {
			t.Fatalf("更新を隠しました: %s %d %s", path, got.Code, got.Body.String())
		}
	}
}

// TestVisualAPIInputLimitsAndFont は過大画像・不正指定・不存在資料を画像割当前に拒否します。
//
// 引数: t(*testing.T)。返り値: なし。PNG用フォント不在でもSVGや数値は停止しません。
func TestVisualAPIInputLimitsAndFont(t *testing.T) {
	cfg, s, path := visualAPIFixture(t)
	base := url.Values{"catalog_path": {path}, "resource": {"人工"}}
	for _, change := range []url.Values{
		{"width": {"799"}}, {"width": {"2401"}}, {"height": {"699"}}, {"height": {"2401"}}, {"width": {"1e3"}},
		{"interval": {"2"}}, {"price": {"bad"}}, {"data_sha256": {"bad"}}, {"catalog": {"conflict"}},
	} {
		q := url.Values{}
		for k, v := range base {
			q[k] = v
		}
		for k, v := range change {
			q[k] = v
		}
		w := visualAPIRequest(s, "/api/chart.svg?"+q.Encode())
		if w.Code != 400 {
			t.Fatalf("不正指定を通しました: %v %d %s", change, w.Code, w.Body.String())
		}
	}
	if w := visualAPIRequest(s, "/api/chart?catalog_path=missing.resources.json&resource=x"); w.Code != 404 {
		t.Fatalf("不存在一覧: %d %s", w.Code, w.Body.String())
	}
	if w := visualAPIRequest(s, "/api/resources?catalog=unknown"); w.Code != 404 {
		t.Fatalf("不存在ID: %d %s", w.Code, w.Body.String())
	}
	s.cfg.Viewer.FontPath = filepath.Join(cfg.Paths.ResourceRoot, "存在しない日本語.ttf")
	if w := visualAPIRequest(s, "/api/chart.png?"+base.Encode()); w.Code != 422 || !strings.Contains(w.Header().Get("Content-Type"), "application/json") {
		t.Fatalf("不正フォントをPNG成功扱い: %d %s", w.Code, w.Body.String())
	}
	if w := visualAPIRequest(s, "/api/chart.svg?"+base.Encode()); w.Code != 200 || !strings.HasPrefix(w.Header().Get("Content-Type"), "image/svg+xml") {
		t.Fatalf("SVGがフォントへ依存しました: %d %s", w.Code, w.Body.String())
	}
}

// TestVisualAPIFontPathUsesExecutableBase はフォント設定の相対位置と省略互換を確認します。
//
// 引数: t(*testing.T)。返り値: なし。設定読込時にはフォント存在を要求しません。
func TestVisualAPIFontPathUsesExecutableBase(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "viewer.toml")
	raw := "[paths]\ndata_root='raw'\nresource_root='resources'\n[viewer]\nfont_path='fonts/日本語.ttf'\n"
	if err := os.WriteFile(path, []byte(raw), 0600); err != nil {
		t.Fatal(err)
	}
	cfg, err := LoadConfig(path, root)
	if err != nil || cfg.Viewer.FontPath != filepath.Join(root, "fonts", "日本語.ttf") {
		t.Fatal("フォント基準が不正", cfg.Viewer.FontPath, err)
	}
}

// TestVisualAPIRegistryIsBounded はライブ一覧の更新で古いIDが無制限に残らないか確認します。
//
// 引数: t(*testing.T)。返り値: なし。同じ一覧は再登録しても個数・本文量を増やしません。
func TestVisualAPIRegistryIsBounded(t *testing.T) {
	cfg, base := apiFixture(t)
	s, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	first, err := s.registerCatalog(base, "")
	if err != nil {
		t.Fatal(err)
	}
	bytes := s.catalogBytes
	for i := 0; i < 100; i++ {
		if _, err = s.registerCatalog(base, ""); err != nil {
			t.Fatal(err)
		}
	}
	if len(s.catalogs) != 1 || len(s.catalogOrder) != 1 || s.catalogBytes != bytes {
		t.Fatal("同じ一覧を複製しました")
	}
	last := ""
	for i := 0; i < 70; i++ {
		c := base
		c.Resources = append([]ResourceMeta(nil), base.Resources...)
		c.Resources[0].Title = fmt.Sprintf("変更された一覧%d", i)
		value, e := s.registerCatalog(c, "")
		if e != nil {
			t.Fatal(e)
		}
		last = value.CatalogID
	}
	if len(s.catalogs) != 64 || len(s.catalogOrder) != 64 || s.catalogBytes > 32*1024*1024 {
		t.Fatalf("一覧保持が上限外: %d %d %d", len(s.catalogs), len(s.catalogOrder), s.catalogBytes)
	}
	if _, ok := s.lookupCatalog(first.CatalogID); ok {
		t.Fatal("古い一覧が失効しません")
	}
	if _, ok := s.lookupCatalog(last); !ok {
		t.Fatal("新しい一覧を失いました")
	}
	w := visualAPIRequest(s, "/api/resources?catalog="+first.CatalogID)
	if w.Code != 404 || !strings.Contains(w.Body.String(), "再取得") {
		t.Fatalf("失効を説明しません: %d %s", w.Code, w.Body.String())
	}
}

// TestVisualAPIRegistryBoundsMetadataBytes は件数未満でも大きい一覧の本文合計を制限します。
//
// 引数: t(*testing.T)。返り値: なし。原板や巨大な試験ファイルは生成しません。
func TestVisualAPIRegistryBoundsMetadataBytes(t *testing.T) {
	cfg, base := apiFixture(t)
	s, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	title := strings.Repeat("閲覧", 180000)
	first := ""
	for i := 0; i < 36; i++ {
		c := base
		c.Resources = append([]ResourceMeta(nil), base.Resources...)
		c.Resources[0].Title = title + fmt.Sprint(i)
		value, e := s.registerCatalog(c, "")
		if e != nil {
			t.Fatal(e)
		}
		if i == 0 {
			first = value.CatalogID
		}
	}
	if len(s.catalogs) >= 36 || len(s.catalogs) >= 64 || s.catalogBytes > 32*1024*1024 {
		t.Fatalf("本文量で制限していません: 件数%d・本文%d", len(s.catalogs), s.catalogBytes)
	}
	if _, ok := s.lookupCatalog(first); ok {
		t.Fatal("本文量を超えた最古の一覧が残りました")
	}
}
