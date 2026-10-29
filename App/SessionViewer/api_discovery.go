package main

import "net/http"

// openAPI はAI・外部ツール向けの読取API仕様を、その場でJSONへ組み立てます。
//
// 引数: w(http.ResponseWriter)、r(*http.Request)。返り値: なし。
// 仕様書・画像・原板の複製をディスクへ作らず、現在のサーバーを相対URLで示します。
func (s *Server) openAPI(w http.ResponseWriter, r *http.Request) {
	parameters := map[string]any{}
	add := func(name, description string, schema map[string]any) {
		parameters[name] = map[string]any{"name": name, "in": "query", "description": description, "schema": schema}
	}
	add("catalog_path", "サーバー上のリンク列挙ファイルのパス。相対パスはresource_root基準。catalogとは同時指定しません。", map[string]any{"type": "string"})
	add("catalog", "POST /api/catalogs/loadで取得した実行中サーバー内の一覧ID。catalog_pathとは同時指定しません。", map[string]any{"type": "string"})
	add("resource", "一覧のresource ID。一覧を使う場合は必須です。", map[string]any{"type": "string"})
	add("symbol", "価格だけを表示する場合のラージ銘柄。sessionと組み合わせます。", map[string]any{"type": "string", "enum": []string{"NK225", "TOPIX"}})
	add("session", "YYYY-MM-DD_Day又はYYYY-MM-DD_Night。Nightの日付は開始日です。", map[string]any{"type": "string"})
	add("from", "表示開始のエポックミリ秒。省略時はセッション開始。", map[string]any{"type": "number"})
	add("to", "表示終了のエポックミリ秒。省略時はセッション終了。", map[string]any{"type": "number"})
	add("interval", "rawは線、分足は原板の全更新によるOHLC。保有・損益は区間最後値です。", map[string]any{"type": "string", "enum": []string{"raw", "1", "5", "15"}, "default": "raw"})
	add("price", "表示価格。Midは正常なBid<Askの時だけ計算します。", map[string]any{"type": "string", "enum": []string{"last", "mid", "bid", "ask"}, "default": "last"})
	add("data_sha256", "期待するデータ指紋。入力更新で一致しなければ409となり、メタ情報を再取得します。", map[string]any{"type": "string", "pattern": "^[0-9a-f]{64}$"})
	add("image_width", "画像幅。実際のクエリ名はwidthです。", map[string]any{"type": "integer", "minimum": 800, "maximum": 2400, "default": 1600})
	parameters["image_width"].(map[string]any)["name"] = "width"
	add("data_width", "数値応答の縮約に使う表示幅。実際のクエリ名はwidthです。", map[string]any{"type": "integer", "minimum": 1, "maximum": 4000, "default": 1200})
	parameters["data_width"].(map[string]any)["name"] = "width"
	add("height", "5段を合わせた画像高さ。", map[string]any{"type": "integer", "minimum": 700, "maximum": 2400, "default": 1200})
	refs := func(names ...string) []any {
		out := []any{}
		for _, name := range names {
			out = append(out, map[string]string{"$ref": "#/components/parameters/" + name})
		}
		return out
	}
	common := []string{"catalog_path", "catalog", "resource", "symbol", "session", "from", "to", "interval", "price", "data_sha256"}
	errorResponse := map[string]any{"description": "入力不正・ファイル欠損・入力更新・フォント不足など。JSONのerrorに理由を示します。", "content": map[string]any{"application/json": map[string]any{"schema": map[string]any{"type": "object", "properties": map[string]any{"error": map[string]string{"type": "string"}}}}}}
	operation := func(summary, content string, params []any) map[string]any {
		schema := map[string]any{"type": "object"}
		if content != "application/json" {
			schema = map[string]any{"type": "string", "format": "binary"}
		}
		return map[string]any{"summary": summary, "parameters": params, "responses": map[string]any{"200": map[string]any{"description": "要求した表示・数値情報。画像と数値は同じデータ指紋で照合できます。", "content": map[string]any{content: map[string]any{"schema": schema}}, "headers": map[string]any{"X-Chart-Data-SHA256": map[string]any{"description": "画像又は数値の元データ指紋。", "schema": map[string]string{"type": "string"}}}}, "400": errorResponse, "404": errorResponse, "409": errorResponse, "422": errorResponse}}
	}
	imageParams := refs(append(append([]string{}, common...), "image_width", "height")...)
	paths := map[string]any{
		"/api/resources": map[string]any{"get": operation("リンク列挙から利用可能な商品・場・手法とresource IDを取得", "application/json", refs("catalog_path", "catalog"))},
		"/api/chart":     map[string]any{"get": operation("画像URL・数値URL・指紋・出所・表示範囲・損益を取得", "application/json", imageParams)},
		"/api/chart.png": map[string]any{"get": operation("AIが直接画像として読める5段グラフPNGを取得", "image/png", imageParams)},
		"/api/chart.svg": map[string]any{"get": operation("同じ5段グラフをベクター画像で取得", "image/svg+xml", imageParams)},
		"/api/data":      map[string]any{"get": operation("画像と同じ範囲の価格・保有・損益・約定・原資料パスを取得", "application/json", refs(append(append([]string{}, common...), "data_width")...))},
		"/api/info":      map[string]any{"get": operation("待受設定・原板ルート・初期一覧ファイルを取得", "application/json", []any{})},
		"/api/sessions":  map[string]any{"get": operation("銘柄の原板セッション一覧を取得", "application/json", refs("symbol"))},
	}
	load := operation("一覧パス又はアップロードした一覧JSONを登録", "application/json", []any{})
	load["requestBody"] = map[string]any{"required": true, "content": map[string]any{"application/json": map[string]any{"schema": map[string]any{"type": "object", "description": "path又はcatalogの一方だけを指定します。", "properties": map[string]any{"path": map[string]string{"type": "string"}, "catalog": map[string]string{"type": "object"}}}}}}
	paths["/api/catalogs/load"] = map[string]any{"post": load}
	writeJSON(w, r, http.StatusOK, map[string]any{"openapi": "3.0.3", "info": map[string]string{"title": "セッションビューアーの読取API", "version": "1.0.0", "description": "resources→chart→画像とdataの順に取得します。描画は要求時のメモリ内だけで行い、注文・売買判断・保存済み原資料の変更を行いません。"}, "servers": []any{map[string]string{"url": "/"}}, "paths": paths, "components": map[string]any{"parameters": parameters}})
}
