package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
)

// dataDigest は画像と数値が参照した同じJSON本文の指紋を返します。
//
// 引数: body([]byte)。返り値: stringはSHA256の16進64文字です。
func dataDigest(body []byte) string {
	sum := sha256.Sum256(body)
	return hex.EncodeToString(sum[:])
}

// checkedDataBytes は取得途中の資料更新を異なる画像との黙示的な混在にしません。
//
// 引数: r(*http.Request)、body([]byte)。返り値: 本文([]byte)、HTTP状態(int)、error。
func checkedDataBytes(r *http.Request, body []byte) ([]byte, int, error) {
	if expected := r.URL.Query().Get("data_sha256"); expected != "" && !strings.EqualFold(expected, dataDigest(body)) {
		return nil, http.StatusConflict, fmt.Errorf("入力が更新されました。同じ画像と数値を得るにはメタ情報を再取得してください")
	}
	return body, http.StatusOK, nil
}

// resources はサーバー上の列挙ファイルをGETだけで登録・取得します。
//
// 引数: w(http.ResponseWriter)、r(*http.Request)。返り値: なし。元資料を変更しません。
func (s *Server) resources(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	path, id := q.Get("catalog_path"), q.Get("catalog")
	if path != "" && id != "" {
		apiError(w, r, 400, fmt.Errorf("catalogとcatalog_pathは一つだけ指定してください"))
		return
	}
	if id != "" {
		value, ok := s.lookupCatalog(id)
		if !ok {
			apiError(w, r, 404, fmt.Errorf("一覧IDが見つかりません。列挙ファイルを再取得してください"))
			return
		}
		writeJSON(w, r, 200, value)
		return
	}
	if path == "" {
		path = s.cfg.Paths.DefaultCatalog
	}
	if path == "" {
		apiError(w, r, 400, fmt.Errorf("catalog_path又はcatalogを指定してください"))
		return
	}
	catalog, resolved, err := readCatalog(s.cfg, path)
	if err != nil {
		status := http.StatusBadRequest
		if os.IsNotExist(err) {
			status = http.StatusNotFound
		}
		apiError(w, r, status, err)
		return
	}
	value, err := s.registerCatalog(catalog, resolved)
	if err != nil {
		apiError(w, r, 400, err)
		return
	}
	writeJSON(w, r, 200, value)
}

// chartQueryDimensions は画像割当ての前に出力サイズを制限します。
//
// 引数: q(url.Values)。返り値: 幅/高さ(int)、error。数値APIのwidth制限とは独立です。
func chartQueryDimensions(q url.Values) (int, int, error) {
	width, height := 1600, 1200
	for _, field := range []struct {
		name      string
		value     *int
		low, high int
	}{
		{"width", &width, 800, 2400}, {"height", &height, 700, 2400},
	} {
		if raw := q.Get(field.name); raw != "" {
			n, err := strconv.Atoi(raw)
			if err != nil || n < field.low || n > field.high {
				return 0, 0, fmt.Errorf("%sは%d〜%dです", field.name, field.low, field.high)
			}
			*field.value = n
		}
	}
	return width, height, nil
}

// chartData は表示寸法と同じ幅の共通数値応答を取り、描画用の型へ復元します。
//
// 引数: r(*http.Request)。返り値: DataResponse、元JSON([]byte)、幅/高さ/HTTP状態(int)、error。
func (s *Server) chartData(r *http.Request) (DataResponse, []byte, int, int, int, error) {
	var data DataResponse
	width, height, err := chartQueryDimensions(r.URL.Query())
	if err != nil {
		return data, nil, 0, 0, 400, err
	}
	clone := r.Clone(r.Context())
	u := *r.URL
	clone.URL = &u
	q := clone.URL.Query()
	q.Set("width", strconv.Itoa(width))
	q.Del("height")
	clone.URL.RawQuery = q.Encode()
	body, status, err := s.dataBytes(clone)
	if err != nil || status == 0 {
		return data, nil, width, height, status, err
	}
	if err = json.Unmarshal(body, &data); err != nil {
		return data, nil, width, height, 500, err
	}
	return data, body, width, height, 200, nil
}

// chartURL は同じ対象・表示範囲・指紋を持つAPIの相対URLを作ります。
//
// 引数: endpoint(string)、query(url.Values)、digest(string)、width/height(int)、image(bool)。返り値: string。
func chartURL(endpoint string, query url.Values, digest string, width, height int, image bool) string {
	q := url.Values{}
	for _, name := range []string{"catalog", "catalog_path", "resource", "symbol", "session", "from", "to", "interval", "price"} {
		if value := query.Get(name); value != "" {
			q.Set(name, value)
		}
	}
	q.Set("width", strconv.Itoa(width))
	if image {
		q.Set("height", strconv.Itoa(height))
	}
	q.Set("data_sha256", digest)
	return endpoint + "?" + q.Encode()
}

// chartMetadata は画像の取得先と同じ根拠の数値・約定・参照パスを返します。
//
// 引数: w(http.ResponseWriter)、r(*http.Request)。返り値: なし。元系列や画像を二重保存しません。
func (s *Server) chartMetadata(w http.ResponseWriter, r *http.Request) {
	data, body, width, height, status, err := s.chartData(r)
	if status == 0 {
		return
	}
	if err != nil {
		apiError(w, r, status, err)
		return
	}
	digest := dataDigest(body)
	q := r.URL.Query()
	w.Header().Set("X-Chart-Data-SHA256", digest)
	writeJSON(w, r, 200, map[string]any{
		"schema_version": 1, "data_sha256": digest, "width": width, "height": height,
		"png_url": chartURL("/api/chart.png", q, digest, width, height, true), "svg_url": chartURL("/api/chart.svg", q, digest, width, height, true), "data_url": chartURL("/api/data", q, digest, width, height, false),
		"resource": data.Resource, "range": data.Range, "interval": data.Interval, "candle_price": data.CandlePrice, "summary": data.Summary, "summary_at_ms": data.Range.ToMS, "sampling": data.Sampling, "quality": data.Quality, "files": data.Files, "events": data.Events,
	})
}

// chartPNG は共通系列を日本語の5段PNGへ変換し、メモリから返します。
//
// 引数: w(http.ResponseWriter)、r(*http.Request)。返り値: なし。描画失敗を成功扱いしません。
func (s *Server) chartPNG(w http.ResponseWriter, r *http.Request) { s.chartImage(w, r, true) }

// chartSVG は同じ系列の5段SVGを外部参照なしで返します。
//
// 引数: w(http.ResponseWriter)、r(*http.Request)。返り値: なし。ブラウザーやフォントの同梱は不要です。
func (s *Server) chartSVG(w http.ResponseWriter, r *http.Request) { s.chartImage(w, r, false) }

// chartImage は画像形式だけを切り替え、同じ読み取り経路とエラー規則を維持します。
//
// 引数: w(http.ResponseWriter)、r(*http.Request)、png(bool)。返り値: なし。
func (s *Server) chartImage(w http.ResponseWriter, r *http.Request, png bool) {
	// 大きな描画用配列の復元も直列化し、待機中の画像依頼へ同じ配列を大量複製しません。
	s.renderMu.Lock()
	defer s.renderMu.Unlock()
	if r.Context().Err() != nil {
		return
	}
	data, source, width, height, status, err := s.chartData(r)
	if status == 0 {
		return
	}
	if err != nil {
		apiError(w, r, status, err)
		return
	}
	// ----------------------------------------
	// chartDataの原板読取が終わり、parseMuを解放してから画像を描きます。
	if r.Context().Err() != nil {
		return
	}
	var body []byte
	kind := "image/svg+xml; charset=utf-8"
	if png {
		body, err = RenderChartPNG(data, width, height, s.cfg.Viewer.FontPath)
		kind = "image/png"
	} else {
		body, err = RenderChartSVG(data, width, height)
	}
	if err != nil {
		apiError(w, r, 422, err)
		return
	}
	w.Header().Set("Content-Type", kind)
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("X-Chart-Data-SHA256", dataDigest(source))
	w.Header().Set("Content-Length", strconv.Itoa(len(body)))
	if !png {
		w.Header().Set("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
	}
	w.WriteHeader(200)
	_, _ = w.Write(body)
}
