package main

import (
	"bytes"
	"compress/zlib"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"encoding/xml"
	"fmt"
	"image/png"
	"io"
	"math"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strconv"
	"strings"
	"testing"
	"unicode/utf8"
)

type visualMeta struct {
	SchemaVersion int          `json:"schema_version"`
	SHA           string       `json:"data_sha256"`
	PNG           string       `json:"png_url"`
	SVG           string       `json:"svg_url"`
	Data          string       `json:"data_url"`
	Width         int          `json:"width"`
	Height        int          `json:"height"`
	Resource      ResourceMeta `json:"resource"`
	Summary       DataSummary  `json:"summary"`
	Files         DataFiles    `json:"files"`
	Range         DataRange    `json:"range"`
	Events        []ViewEvent  `json:"events"`
	Interval      string       `json:"interval"`
}

type visualSVG struct {
	Description map[string]json.RawMessage
	Panes       map[string]map[string]string
	Series      map[string]int
}

// visualClone はクエリを共有参照せずに複製します。
//
// 引数: source(url.Values)。返り値: url.Values。
func visualClone(source url.Values) url.Values {
	out := url.Values{}
	for name, values := range source {
		out[name] = append([]string(nil), values...)
	}
	return out
}

// visualFixture は別手法の返済と管理外移管を含む、小さい独立表示資料を作ります。
//
// 引数: t(*testing.T)。返り値: *Server、列挙ファイルの相対名(string)、原板パス(string)。
func visualFixture(t *testing.T) (*Server, string, string) {
	t.Helper()
	books := []map[string]any{adversaryBook(0, 100, 99, 101), adversaryBook(20, 110, 109, 111), adversaryBook(30, 95, 94, 96), adversaryBook(45, 115, 114, 116), adversaryBook(60, 120, 119, 121)}
	rows := []map[string]any{adversaryTrade("入口A", "LongN", "所有A", 0, 3, 1, 100, 3), adversaryTrade("入口B", "LongN", "所有B", 20, 1, 2, 110, 1), adversaryTrade("返済A", "LongR", "所有A", 30, 1, 3, 95, 2), adversaryTrade("管理外", "Detach", "所有A", 45, 2, 0, 0, 0), adversaryTrade("返済B", "LongR", "所有B", 60, 1, 5, 120, 2)}
	for i := range rows {
		rows[i]["method_id"] = "出口担当"
	}
	rows[0]["method_id"], rows[1]["method_id"] = "入口A", "入口B"
	cfg, r, _ := adversaryFixture(t, books, rows, "trades")
	cfg.Viewer.CacheMB = 8
	r.ID, r.MethodID, r.Title = "全体 & 日本語", "*", `日本語 <script>注記</script> & "資料"`
	a, b, n := r, r, r
	a.ID, a.MethodID, a.EntryMethodID = "入口A", "入口A", "入口A"
	b.ID, b.MethodID, b.EntryMethodID = "入口B", "入口B", "入口B"
	n.ID, n.Title, n.PNLBasis = "手数料後", "手数料後の全体", "net"
	name := "画像 & 日本語.resources.json"
	path := filepath.Join(cfg.Paths.ResourceRoot, name)
	data, err := json.Marshal(Catalog{SchemaVersion: 1, Resources: []ResourceMeta{r, a, b, n}})
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
	cfg.Paths.DefaultCatalog = path
	s, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	return s, name, r.MarketPath
}

// visualRequest は画像又はJSONを、ネットワークを使わずHTTPハンドラ経由で取得します。
//
// 引数: t(*testing.T)、s(*Server)、endpoint(string)、query(url.Values)、want(int)。返り値: *httptest.ResponseRecorder。
func visualRequest(t *testing.T, s *Server, endpoint string, query url.Values, want int) *httptest.ResponseRecorder {
	t.Helper()
	if query != nil {
		endpoint += "?" + query.Encode()
	}
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, httptest.NewRequest(http.MethodGet, endpoint, nil))
	if w.Code != want {
		t.Fatalf("%s: HTTP%d、期待%d、本文%.500s", endpoint, w.Code, want, w.Body.String())
	}
	return w
}

// visualMetadata は画像URLと根拠JSONの最小メタデータを読みます。
//
// 引数: t(*testing.T)、s(*Server)、query(url.Values)。返り値: visualMeta。
func visualMetadata(t *testing.T, s *Server, query url.Values) visualMeta {
	t.Helper()
	w := visualRequest(t, s, "/api/chart", query, http.StatusOK)
	var meta visualMeta
	if err := json.Unmarshal(w.Body.Bytes(), &meta); err != nil {
		t.Fatal(err)
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(w.Body.Bytes(), &fields); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"prices", "states", "candles"} {
		if _, ok := fields[name]; ok {
			t.Fatalf("数値の全系列をメタへ重複しました: %s", name)
		}
	}
	if meta.SchemaVersion != 1 || len(meta.SHA) != 64 || w.Header().Get("X-Chart-Data-SHA256") != meta.SHA {
		t.Fatalf("画像根拠の指紋がありません: %+v", meta)
	}
	for _, link := range []string{meta.PNG, meta.SVG, meta.Data} {
		u, err := url.Parse(link)
		if err != nil || u.IsAbs() || u.Query().Get("data_sha256") != meta.SHA {
			t.Fatalf("別根拠又は外部URLへ誘導: %s", link)
		}
	}
	return meta
}

// visualParseSVG はSVGをXMLとして検査し、描画座標と埋込根拠を抽出します。
//
// 引数: t(*testing.T)、body([]byte)。返り値: visualSVG。能動要素や外部画像を許可しません。
func visualParseSVG(t *testing.T, body []byte) visualSVG {
	t.Helper()
	d := xml.NewDecoder(bytes.NewReader(body))
	out := visualSVG{Description: map[string]json.RawMessage{}, Panes: map[string]map[string]string{}, Series: map[string]int{}}
	var stack []string
	for {
		token, err := d.Token()
		if err == io.EOF {
			break
		}
		if err != nil {
			t.Fatalf("SVGがXMLとして不正: %v", err)
		}
		switch v := token.(type) {
		case xml.StartElement:
			switch strings.ToLower(v.Name.Local) {
			case "script", "foreignobject", "image":
				t.Fatalf("SVGへ能動又は外部参照要素が入りました: %s", v.Name.Local)
			}
			attrs := map[string]string{}
			for _, a := range v.Attr {
				attrs[a.Name.Local] = a.Value
			}
			if v.Name.Local == "desc" {
				var text string
				if err = d.DecodeElement(&text, &v); err != nil {
					t.Fatal(err)
				}
				if err = json.Unmarshal([]byte(text), &out.Description); err != nil {
					t.Fatalf("descの根拠JSONが不正: %v", err)
				}
				continue
			}
			pane := ""
			if len(stack) > 0 {
				pane = stack[len(stack)-1]
			}
			if name := attrs["data-series"]; name != "" {
				pane = name
				out.Panes[name] = attrs
			}
			if attrs["data-role"] == "series" && pane != "" {
				out.Series[pane]++
			}
			stack = append(stack, pane)
		case xml.EndElement:
			if len(stack) > 0 {
				stack = stack[:len(stack)-1]
			}
		}
	}
	return out
}

// visualSymmetry は損益軸が中央0・正負対称であることを座標から確認します。
//
// 引数: t(*testing.T)、svg(visualSVG)。返り値: なし。
func visualSymmetry(t *testing.T, svg visualSVG) {
	t.Helper()
	for _, name := range []string{"price", "short", "long", "realized", "unrealized"} {
		if svg.Panes[name] == nil {
			t.Fatalf("5段の描画がありません: %s", name)
		}
	}
	for _, name := range []string{"realized", "unrealized"} {
		p := svg.Panes[name]
		read := func(key string) float64 {
			v, e := strconv.ParseFloat(p[key], 64)
			if e != nil {
				t.Fatalf("%s.%sが不正: %q", name, key, p[key])
			}
			return v
		}
		lo, hi, zero, y, h := read("data-min"), read("data-max"), read("data-zero-y"), read("data-plot-y"), read("data-plot-height")
		if lo >= 0 || hi <= 0 || math.Abs(lo+hi) > 1e-6 || math.Abs(zero-y-h/2) > .02 {
			t.Fatalf("%sの軸が対称中央ではありません: %+v", name, p)
		}
	}
}

// TestVisualAdversaryMetadataAndSVG は絞込・費用基準・画像根拠が同じ会計を指すか検査します。
//
// 引数: t(*testing.T)。返り値: なし。SVGのラベルはXMLとして安全な文字列です。
func TestVisualAdversaryMetadataAndSVG(t *testing.T) {
	s, name, _ := visualFixture(t)
	listed := visualRequest(t, s, "/api/resources", url.Values{"catalog_path": {name}}, http.StatusOK)
	var resources CatalogResponse
	if err := json.Unmarshal(listed.Body.Bytes(), &resources); err != nil {
		t.Fatal(err)
	}
	if len(resources.Resources) != 4 || resources.Path != s.cfg.Paths.DefaultCatalog {
		t.Fatalf("GETの一覧が異なる資料を選びました: %+v", resources)
	}
	for _, test := range []struct {
		id     string
		real   float64
		events int
	}{{"全体 & 日本語", 50, 5}, {"入口A", -50, 3}, {"入口B", 100, 2}, {"手数料後", 42, 5}} {
		for _, interval := range []string{"raw", "1"} {
			query := url.Values{"catalog_path": {name}, "resource": {test.id}, "interval": {interval}, "width": {"1000"}, "height": {"900"}}
			meta := visualMetadata(t, s, query)
			if meta.Width != 1000 || meta.Height != 900 || meta.Interval != interval || meta.Summary.Realized == nil || *meta.Summary.Realized != test.real || meta.Summary.LongQty == nil || *meta.Summary.LongQty != 0 || meta.Summary.ShortQty == nil || *meta.Summary.ShortQty != 0 || meta.Summary.Unrealized == nil || *meta.Summary.Unrealized != 0 || len(meta.Events) != test.events {
				t.Fatalf("別資源又は別会計のメタ: %+v", meta)
			}
			dataResponse := visualRequest(t, s, meta.Data, nil, http.StatusOK)
			digest := sha256.Sum256(dataResponse.Body.Bytes())
			if hex.EncodeToString(digest[:]) != meta.SHA {
				t.Fatal("数値API本文と画像の指紋が一致しません")
			}
			var data DataResponse
			if err := json.Unmarshal(dataResponse.Body.Bytes(), &data); err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(meta.Summary, data.Summary) || !reflect.DeepEqual(meta.Files, data.Files) || !reflect.DeepEqual(meta.Resource, data.Resource) {
				t.Fatal("画像・数値の対象/会計/参照パスが不一致です")
			}
			svgResponse := visualRequest(t, s, meta.SVG, nil, http.StatusOK)
			if !strings.HasPrefix(svgResponse.Header().Get("Content-Type"), "image/svg+xml") || svgResponse.Header().Get("X-Chart-Data-SHA256") != meta.SHA {
				t.Fatal("SVGが違う形式/根拠です")
			}
			svg := visualParseSVG(t, svgResponse.Body.Bytes())
			visualSymmetry(t, svg)
			for field, want := range map[string]any{"summary": meta.Summary, "files": meta.Files, "resource": meta.Resource} {
				b, _ := json.Marshal(want)
				var left, right any
				if err := json.Unmarshal(b, &left); err != nil {
					t.Fatal(err)
				}
				if err := json.Unmarshal(svg.Description[field], &right); err != nil {
					t.Fatalf("SVG根拠%sなし: %v", field, err)
				}
				if !reflect.DeepEqual(left, right) {
					t.Fatalf("SVGの根拠%sが別の値です", field)
				}
			}
			var sha string
			if err := json.Unmarshal(svg.Description["data_sha256"], &sha); err != nil || sha != meta.SHA {
				t.Fatal("SVG descの根拠指紋が違います", err)
			}
		}
	}
	query := url.Values{"catalog": {resources.CatalogID}, "resource": {"入口A"}}
	if visualMetadata(t, s, query).Summary.Realized == nil {
		t.Fatal("runtime一覧ID経由で読めません")
	}
}

// TestVisualAdversaryHashGuardsSourceChange は取得間の原板更新で画像と数値を混在させないか検査します。
//
// 引数: t(*testing.T)。返り値: なし。変更するのは自身の一時原板だけです。
func TestVisualAdversaryHashGuardsSourceChange(t *testing.T) {
	s, name, market := visualFixture(t)
	q := url.Values{"catalog_path": {name}, "resource": {"手数料後"}, "width": {"1000"}, "height": {"900"}}
	old := visualMetadata(t, s, q)
	f, err := os.OpenFile(market, os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		t.Fatal(err)
	}
	if err = json.NewEncoder(f).Encode(adversaryBook(90, 145, 144, 146)); err != nil {
		f.Close()
		t.Fatal(err)
	}
	if err = f.Close(); err != nil {
		t.Fatal(err)
	}
	for _, link := range []string{old.SVG, old.PNG, old.Data} {
		visualRequest(t, s, link, nil, http.StatusConflict)
	}
	current := visualMetadata(t, s, q)
	if current.SHA == old.SHA {
		t.Fatal("原板更新後も古いデータ指紋です")
	}
	visualRequest(t, s, current.SVG, nil, http.StatusOK)
	visualRequest(t, s, current.Data, nil, http.StatusOK)
}

// TestVisualAdversaryBoundsAndPaths は画像割当て前に不正寸法・曖昧な対象を拒否するか検査します。
//
// 引数: t(*testing.T)。返り値: なし。巨大な画像の実割当ては要求しません。
func TestVisualAdversaryBoundsAndPaths(t *testing.T) {
	s, name, _ := visualFixture(t)
	base := url.Values{"catalog_path": {name}, "resource": {"全体 & 日本語"}}
	for _, test := range []struct{ key, value string }{{"width", "799"}, {"width", "2401"}, {"height", "699"}, {"height", "2401"}, {"width", "-1"}, {"width", "999999999999999999999999999999"}, {"height", "NaN"}, {"width", "800.5"}, {"interval", "2"}, {"price", "future"}, {"from", "NaN"}, {"catalog_path", "../outside.resources.json"}, {"resource", "存在しないID"}} {
		q := visualClone(base)
		q.Set(test.key, test.value)
		for _, endpoint := range []string{"/api/chart", "/api/chart.svg", "/api/chart.png"} {
			visualRequest(t, s, endpoint, q, http.StatusBadRequest)
		}
	}
	q := visualClone(base)
	q.Set("catalog", "別一覧")
	visualRequest(t, s, "/api/chart", q, http.StatusBadRequest)
	for _, dims := range []struct{ w, h string }{{"800", "700"}, {"2400", "2400"}} {
		q = visualClone(base)
		q.Set("width", dims.w)
		q.Set("height", dims.h)
		visualRequest(t, s, "/api/chart.svg", q, http.StatusOK)
	}
	s.cfg.Viewer.FontPath = filepath.Join(s.cfg.BaseDir, "存在しないフォント.ttf")
	meta := visualMetadata(t, s, base)
	visualRequest(t, s, meta.SVG, nil, http.StatusOK)
	visualRequest(t, s, meta.PNG, nil, http.StatusUnprocessableEntity)
}

// TestVisualAdversaryNullAndPriceOnly は未観測を0へ描かず、null前後を別の系列へ切るか検査します。
//
// 引数: t(*testing.T)。返り値: なし。価格だけと無取引実績の違いも保ちます。
func TestVisualAdversaryNullAndPriceOnly(t *testing.T) {
	books := []map[string]any{adversaryBook(0, 100, 99, 101), adversaryBook(20, 110, 109, 111), adversaryBook(30, 95, 94, 96), adversaryBook(45, 115, 114, 116), adversaryBook(60, 120, 119, 121)}
	rows := []map[string]any{}
	for i, r := range []struct {
		at     int
		long   int
		real   float64
		unreal any
	}{{0, 0, 0, nil}, {20, 1, 10, 20}, {30, 1, 10, nil}, {45, 1, 10, -10}, {60, 0, 5, 0}} {
		rows = append(rows, map[string]any{"timestamp": adversaryTime(r.at).Format("2006-01-02T15:04:05Z07:00"), "sequence": i + 1, "long_qty": r.long, "short_qty": 0, "realized_pnl_yen": r.real, "unrealized_pnl_yen": r.unreal})
	}
	cfg, resource, path := adversaryFixture(t, books, rows, "snapshots")
	raw, err := json.Marshal(Catalog{SchemaVersion: 1, Resources: []ResourceMeta{resource}})
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	s, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	q := url.Values{"catalog_path": {path}, "resource": {resource.ID}, "to": {strconv.FormatFloat(millis(adversaryTime(60)), 'f', 0, 64)}}
	meta := visualMetadata(t, s, q)
	svg := visualParseSVG(t, visualRequest(t, s, meta.SVG, nil, http.StatusOK).Body.Bytes())
	visualSymmetry(t, svg)
	if svg.Series["unrealized"] < 2 {
		t.Fatalf("null区間をまたいで一本に接続しました: %+v", svg.Series)
	}
	priceOnly := visualMetadata(t, s, url.Values{"symbol": {"NK225"}, "session": {"2026-10-27_Day"}})
	if priceOnly.Summary.Realized != nil || priceOnly.Summary.Unrealized != nil || priceOnly.Files.PNL != "" {
		t.Fatalf("損益資料なしを実績0へ変更しました: %+v", priceOnly)
	}
	unknown := visualParseSVG(t, visualRequest(t, s, priceOnly.SVG, nil, http.StatusOK).Body.Bytes())
	if unknown.Series["realized"] != 0 || unknown.Series["unrealized"] != 0 {
		t.Fatal("未知の損益線を描きました")
	}
	emptyCfg, emptyResource, emptyPath := adversaryFixture(t, nil, nil, "trades")
	emptyRaw, _ := json.Marshal(Catalog{SchemaVersion: 1, Resources: []ResourceMeta{emptyResource}})
	if err = os.WriteFile(emptyPath, emptyRaw, 0600); err != nil {
		t.Fatal(err)
	}
	empty, err := NewServer(emptyCfg)
	if err != nil {
		t.Fatal(err)
	}
	flat := visualMetadata(t, empty, url.Values{"catalog_path": {emptyPath}, "resource": {emptyResource.ID}})
	if flat.Summary.Realized == nil || *flat.Summary.Realized != 0 || flat.Summary.LongQty == nil || *flat.Summary.LongQty != 0 {
		t.Fatalf("空の確認済み約定と未知を混同しました: %+v", flat.Summary)
	}
	visualSymmetry(t, visualParseSVG(t, visualRequest(t, empty, flat.SVG, nil, http.StatusOK).Body.Bytes()))
}

// visualFiles は人工資料の全ファイルを内容指紋で記録します。
//
// 引数: t(*testing.T)、root(string)。返り値: map[string]string。
func visualFiles(t *testing.T, root string) map[string]string {
	t.Helper()
	out := map[string]string{}
	err := filepath.WalkDir(root, func(path string, entry os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.IsDir() {
			return nil
		}
		data, e := os.ReadFile(path)
		if e != nil {
			return e
		}
		info, e := entry.Info()
		if e != nil {
			return e
		}
		sum := sha256.Sum256(data)
		out[path] = fmt.Sprintf("%s/%d/%d", hex.EncodeToString(sum[:]), info.Size(), info.ModTime().UnixNano())
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return out
}

// visualPNGDescription はPNGのUTF-8注記を画像デコーダと独立して読みます。
//
// 引数: t(*testing.T)、body([]byte)。返り値: map[string]json.RawMessage。
func visualPNGDescription(t *testing.T, body []byte) map[string]json.RawMessage {
	t.Helper()
	for at := 8; at+12 <= len(body); {
		n := int(binary.BigEndian.Uint32(body[at : at+4]))
		if n < 0 || n > len(body)-at-12 {
			t.Fatal("PNGチャンク長が不正です")
		}
		kind, data := string(body[at+4:at+8]), body[at+8:at+8+n]
		at += n + 12
		if kind != "iTXt" {
			continue
		}
		end := bytes.IndexByte(data, 0)
		if end < 0 || string(data[:end]) != "Description" {
			continue
		}
		data = data[end+1:]
		if len(data) < 2 || data[1] != 0 {
			t.Fatal("PNG注記の圧縮方式が不正です")
		}
		compressed := data[0]
		data = data[2:]
		for range 2 {
			end = bytes.IndexByte(data, 0)
			if end < 0 {
				t.Fatal("PNG注記の見出しが不正です")
			}
			data = data[end+1:]
		}
		if compressed == 1 {
			r, err := zlib.NewReader(bytes.NewReader(data))
			if err != nil {
				t.Fatal(err)
			}
			data, err = io.ReadAll(io.LimitReader(r, 4*1024*1024))
			_ = r.Close()
			if err != nil {
				t.Fatal(err)
			}
		} else if compressed != 0 {
			t.Fatal("PNG注記の圧縮指定が不正です")
		}
		if !utf8.Valid(data) {
			t.Fatal("PNG日本語注記がUTF-8ではありません")
		}
		var out map[string]json.RawMessage
		if err := json.Unmarshal(data, &out); err != nil {
			t.Fatal("PNG注記の根拠JSONが不正です", err)
		}
		return out
	}
	t.Fatal("PNGに根拠のDescriptionがありません")
	return nil
}

// TestVisualAdversaryPNGHasNoPersistentCopies は実PNGの寸法と非空描画・原資料不変を検査します。
//
// 引数: t(*testing.T)。返り値: なし。目視用保存は明示環境変数がある時のignored workだけです。
func TestVisualAdversaryPNGHasNoPersistentCopies(t *testing.T) {
	s, name, _ := visualFixture(t)
	before := visualFiles(t, s.cfg.BaseDir)
	for _, interval := range []string{"raw", "1"} {
		q := url.Values{"catalog_path": {name}, "resource": {"全体 & 日本語"}, "interval": {interval}, "width": {"1000"}, "height": {"900"}, "to": {strconv.FormatFloat(millis(adversaryTime(120)), 'f', 0, 64)}}
		meta := visualMetadata(t, s, q)
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, httptest.NewRequest(http.MethodGet, meta.PNG, nil))
		if w.Code == 422 && (strings.Contains(w.Body.String(), "フォント") || strings.Contains(strings.ToLower(w.Body.String()), "font")) {
			if runtime.GOOS != "windows" {
				t.Skipf("PNG日本語フォント依存がありません（SVG/API試験は別途必須）: %s", w.Body.String())
			}
			if _, err := os.Stat(`C:\Windows\Fonts\meiryo.ttc`); os.IsNotExist(err) {
				t.Skipf("Windows日本語フォント未配置: %s", w.Body.String())
			}
		}
		if w.Code != 200 {
			t.Fatalf("PNG作成失敗: %d %s", w.Code, w.Body.String())
		}
		if w.Header().Get("Content-Type") != "image/png" || w.Header().Get("X-Chart-Data-SHA256") != meta.SHA {
			t.Fatal("PNG形式又は根拠指紋が違います")
		}
		description := visualPNGDescription(t, w.Body.Bytes())
		var sha string
		var summary DataSummary
		var files DataFiles
		if err := json.Unmarshal(description["data_sha256"], &sha); err != nil || sha != meta.SHA {
			t.Fatal("PNG内の根拠指紋が一致しません", err)
		}
		if err := json.Unmarshal(description["summary"], &summary); err != nil || !reflect.DeepEqual(summary, meta.Summary) {
			t.Fatal("PNG内の損益根拠が一致しません", err)
		}
		if err := json.Unmarshal(description["files"], &files); err != nil || !reflect.DeepEqual(files, meta.Files) {
			t.Fatal("PNG内の原資料パスが一致しません", err)
		}
		img, err := png.Decode(bytes.NewReader(w.Body.Bytes()))
		if err != nil {
			t.Fatal(err)
		}
		if img.Bounds().Dx() != 1000 || img.Bounds().Dy() != 900 {
			t.Fatal("PNG寸法不一致", img.Bounds())
		}
		colors := map[string]bool{}
		for y := 0; y < 900; y += 7 {
			for x := 0; x < 1000; x += 7 {
				r, g, b, a := img.At(x, y).RGBA()
				colors[fmt.Sprintf("%d/%d/%d/%d", r, g, b, a)] = true
			}
		}
		if len(colors) < 12 {
			t.Fatalf("PNGが空又は単色です: %d色", len(colors))
		}
		if output := os.Getenv("VIEWER_VISUAL_QA_OUTPUT"); output != "" && interval == "1" {
			abs, err := filepath.Abs(output)
			if err != nil {
				t.Fatal(err)
			}
			work, err := filepath.Abs("work")
			if err != nil {
				t.Fatal(err)
			}
			rel, err := filepath.Rel(work, abs)
			if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(os.PathSeparator)) {
				t.Fatal("目視出力はこのアプリのwork内だけです")
			}
			if err = os.MkdirAll(filepath.Dir(abs), 0700); err != nil {
				t.Fatal(err)
			}
			if err = os.WriteFile(abs, w.Body.Bytes(), 0600); err != nil {
				t.Fatal(err)
			}
			t.Logf("明示指定した目視PNG: %s", abs)
		}
	}
	if after := visualFiles(t, s.cfg.BaseDir); !reflect.DeepEqual(before, after) {
		t.Fatal("画像取得で原資料を書換え又は画像/ZIP/中間ファイルを保存しました")
	}
}
