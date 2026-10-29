package main

import (
	"compress/gzip"
	"container/list"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
)

type cacheEntry struct {
	Key  string
	Data []byte
}
type Server struct {
	cfg          Config
	mu           sync.Mutex
	parseMu      sync.Mutex
	renderMu     sync.Mutex
	catalogs     map[string]CatalogResponse
	catalogOrder []string
	catalogSizes map[string]int64
	catalogBytes int64
	cache        map[string]*list.Element
	lru          *list.List
	cacheBytes   int64
}

// NewServer は独立閲覧APIと上限付きメモリキャッシュを作ります。
//
// 引数: cfg(Config)。返り値: *Server と error。原資料の取得やファイル生成はしません。
func NewServer(cfg Config) (*Server, error) {
	if cfg.Paths.DataRoot == "" || cfg.Paths.ResourceRoot == "" || cfg.Viewer.CacheMB < 0 || cfg.Viewer.CacheMB > 4096 {
		return nil, fmt.Errorf("設定が不正です")
	}
	return &Server{cfg: cfg, catalogs: map[string]CatalogResponse{}, catalogSizes: map[string]int64{}, cache: map[string]*list.Element{}, lru: list.New()}, nil
}

// Config は起動時に確定した閲覧設定を返します。
//
// 引数: なし。返り値: Config。
func (s *Server) Config() Config { return s.cfg }

// Handler はAPIだけのハンドラを返します。静的画面は呼出側が登録します。
//
// 引数: なし。返り値: http.Handler。
func (s *Server) Handler() http.Handler {
	m := http.NewServeMux()
	m.HandleFunc("GET /api/info", s.info)
	m.HandleFunc("GET /api/sessions", s.sessions)
	m.HandleFunc("POST /api/catalogs/load", s.loadCatalog)
	m.HandleFunc("GET /api/data", s.data)
	m.HandleFunc("GET /api/resources", s.resources)
	m.HandleFunc("GET /api/chart", s.chartMetadata)
	m.HandleFunc("GET /api/chart.png", s.chartPNG)
	m.HandleFunc("GET /api/chart.svg", s.chartSVG)
	m.HandleFunc("GET /api/openapi.json", s.openAPI)
	return m
}

// writeJSON は圧縮可能なJSON応答を返します。
//
// 引数: w(http.ResponseWriter)、r(*http.Request)、status(int)、value(any)。返り値: なし。
func writeJSON(w http.ResponseWriter, r *http.Request, status int, value any) {
	b, err := json.Marshal(value)
	if err != nil {
		http.Error(w, "JSON生成に失敗", 500)
		return
	}
	writeJSONBytes(w, r, status, b)
}

// writeJSONBytes は内容が確定したJSONをgzip対応で出力します。
//
// 引数: w(http.ResponseWriter)、r(*http.Request)、status(int)、b([]byte)。返り値: なし。
func writeJSONBytes(w http.ResponseWriter, r *http.Request, status int, b []byte) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Add("Vary", "Accept-Encoding")
	compressed := false
	for _, item := range strings.Split(r.Header.Get("Accept-Encoding"), ",") {
		parts := strings.Split(strings.TrimSpace(item), ";")
		if parts[0] != "gzip" {
			continue
		}
		disabled := false
		for _, p := range parts[1:] {
			if strings.TrimSpace(p) == "q=0" {
				disabled = true
			}
		}
		if !disabled {
			compressed = true
		}
	}
	if compressed {
		w.Header().Set("Content-Encoding", "gzip")
	}
	w.WriteHeader(status)
	if compressed {
		gz := gzip.NewWriter(w)
		_, _ = gz.Write(b)
		_ = gz.Close()
	} else {
		_, _ = w.Write(b)
	}
}

// apiError は利用者が原因を追えるJSONエラーを返します。
//
// 引数: w(http.ResponseWriter)、r(*http.Request)、status(int)、err(error)。返り値: なし。
func apiError(w http.ResponseWriter, r *http.Request, status int, err error) {
	writeJSON(w, r, status, map[string]string{"error": err.Error()})
}

// info はTOMLから確定したパスと待受先だけを公開します。
//
// 引数: w(http.ResponseWriter)、r(*http.Request)。返り値: なし。
func (s *Server) info(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, r, 200, map[string]any{"data_root": s.cfg.Paths.DataRoot, "resource_root": s.cfg.Paths.ResourceRoot, "default_catalog": s.cfg.Paths.DefaultCatalog, "listen": s.cfg.Server.Listen})
}

// sessions は選んだ国内市場の保存セッションを列挙します。
//
// 引数: w(http.ResponseWriter)、r(*http.Request)。返り値: なし。
func (s *Server) sessions(w http.ResponseWriter, r *http.Request) {
	rows, err := listSessions(s.cfg, r.URL.Query().Get("symbol"))
	if err != nil {
		apiError(w, r, 400, err)
		return
	}
	writeJSON(w, r, 200, map[string]any{"sessions": rows})
}

// loadCatalog は一覧ファイル又は送信された一覧を実行中IDへ登録します。
//
// 引数: w(http.ResponseWriter)、r(*http.Request)。返り値: なし。任意ファイル取得APIにはしません。
func (s *Server) loadCatalog(w http.ResponseWriter, r *http.Request) {
	var input struct {
		Path    string   `json:"path"`
		Catalog *Catalog `json:"catalog"`
	}
	d := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4*1024*1024))
	d.DisallowUnknownFields()
	if err := d.Decode(&input); err != nil {
		apiError(w, r, 400, err)
		return
	}
	if err := d.Decode(new(any)); err != io.EOF {
		apiError(w, r, 400, fmt.Errorf("JSONは1件のみです"))
		return
	}
	if (input.Path == "") == (input.Catalog == nil) {
		apiError(w, r, 400, fmt.Errorf("path又はcatalogを一つ指定してください"))
		return
	}
	var c Catalog
	var path string
	var err error
	if input.Catalog != nil {
		c, err = validateCatalog(s.cfg, *input.Catalog)
	} else {
		c, path, err = readCatalog(s.cfg, input.Path)
	}
	if err != nil {
		status := 400
		if os.IsNotExist(err) {
			status = 404
		}
		apiError(w, r, status, err)
		return
	}
	value, err := s.registerCatalog(c, path)
	if err != nil {
		apiError(w, r, 400, err)
		return
	}
	writeJSON(w, r, 200, value)
}

// registerCatalog は検証済み一覧へ内容由来IDを付け、同じ資料のAPI間で共有します。
//
// 引数: c(Catalog)、path(string)。返り値: CatalogResponseとerror。直近64件・本文計32MiBまで保持します。
func (s *Server) registerCatalog(c Catalog, path string) (CatalogResponse, error) {
	value := CatalogResponse{Path: path, Resources: c.Resources}
	b, err := json.Marshal(value)
	if err != nil {
		return value, err
	}
	const registryLimit = 32 * 1024 * 1024
	size := int64(len(b) + 64)
	if size > registryLimit {
		return value, fmt.Errorf("一覧が32MiBを超えています。必要な資源へ分割してください")
	}
	hash := sha256.Sum256(b)
	value.CatalogID = hex.EncodeToString(hash[:16])
	s.mu.Lock()
	defer s.mu.Unlock()
	if prior, ok := s.catalogs[value.CatalogID]; ok {
		s.touchCatalogLocked(value.CatalogID)
		return prior, nil
	}
	for len(s.catalogs) >= 64 || s.catalogBytes+size > registryLimit {
		s.evictCatalogLocked()
	}
	s.catalogs[value.CatalogID] = value
	s.catalogSizes[value.CatalogID] = size
	s.catalogBytes += size
	s.touchCatalogLocked(value.CatalogID)
	return value, nil
}

// touchCatalogLocked は同じIDを複製せず、一覧の使用順だけを更新します。
//
// 引数: id(string)。返り値: なし。呼出元はmuを保持します。
func (s *Server) touchCatalogLocked(id string) {
	if s.catalogSizes[id] == 0 {
		return
	}
	for i, old := range s.catalogOrder {
		if old == id {
			s.catalogOrder = append(s.catalogOrder[:i], s.catalogOrder[i+1:]...)
			break
		}
	}
	s.catalogOrder = append(s.catalogOrder, id)
}

// evictCatalogLocked は最も古い実行中IDだけを失効させ、資料や数値キャッシュを消しません。
//
// 引数: なし。返り値: なし。呼出元はmuを保持します。
func (s *Server) evictCatalogLocked() {
	id := ""
	if len(s.catalogOrder) > 0 {
		id = s.catalogOrder[0]
		s.catalogOrder = s.catalogOrder[1:]
	} else {
		for key := range s.catalogs {
			id = key
			break
		}
	}
	delete(s.catalogs, id)
	s.catalogBytes -= s.catalogSizes[id]
	delete(s.catalogSizes, id)
}

// lookupCatalog は保存中の一覧IDを取り出し、使われたIDの有効期間を延長します。
//
// 引数: id(string)。返り値: CatalogResponse、存在(bool)。
func (s *Server) lookupCatalog(id string) (CatalogResponse, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	value, ok := s.catalogs[id]
	if ok {
		s.touchCatalogLocked(id)
	}
	return value, ok
}

// resource は登録済みID又は価格専用の銘柄・場から読取先を選びます。
//
// 引数: r(*http.Request)。返り値: ResourceMeta、一覧パス(string)、error。
func (s *Server) resource(r *http.Request) (ResourceMeta, string, error) {
	q := r.URL.Query()
	if q.Get("catalog") != "" && q.Get("catalog_path") != "" {
		return ResourceMeta{}, "", fmt.Errorf("catalogとcatalog_pathは一つだけ指定してください")
	}
	if q.Get("catalog_path") != "" {
		c, path, err := readCatalog(s.cfg, q.Get("catalog_path"))
		if err != nil {
			return ResourceMeta{}, "", err
		}
		for _, v := range c.Resources {
			if v.ID == q.Get("resource") {
				return v, path, nil
			}
		}
		return ResourceMeta{}, "", fmt.Errorf("リソースIDが見つかりません")
	}
	if q.Get("catalog") != "" {
		c, ok := s.lookupCatalog(q.Get("catalog"))
		if !ok {
			return ResourceMeta{}, "", fmt.Errorf("一覧IDが見つかりません。列挙ファイルを再取得してください")
		}
		for _, v := range c.Resources {
			if v.ID == q.Get("resource") {
				return v, c.Path, nil
			}
		}
		return ResourceMeta{}, "", fmt.Errorf("リソースIDが見つかりません")
	}
	symbol, session := q.Get("symbol"), q.Get("session")
	if symbol != "NK225" && symbol != "TOPIX" {
		return ResourceMeta{}, "", fmt.Errorf("未知の銘柄です")
	}
	if _, _, err := sessionBounds(session); err != nil {
		return ResourceMeta{}, "", err
	}
	p, err := resolvePath(s.cfg.Paths.DataRoot, filepath.Join(symbol, session, "book.jsonl"))
	if err != nil {
		return ResourceMeta{}, "", err
	}
	return ResourceMeta{ID: symbol + "/" + session, Title: symbol + " " + session, Symbol: symbol, Session: session, MarketPath: p}, "", nil
}

// inputStamp は参照ファイルの更新をキャッシュキーへ反映します。
//
// 引数: resource(ResourceMeta)、catalog(string)。返り値: string、error。
func inputStamp(resource ResourceMeta, catalog string) (string, error) {
	var b strings.Builder
	for _, p := range []string{resource.MarketPath, resource.PNLPath, catalog} {
		if p == "" {
			continue
		}
		st, err := os.Stat(p)
		if err != nil {
			return "", err
		}
		if !st.Mode().IsRegular() {
			return "", fmt.Errorf("通常ファイルではありません: %s", p)
		}
		fmt.Fprintf(&b, "%s:%d:%d;", p, st.Size(), st.ModTime().UnixNano())
	}
	return b.String(), nil
}

// cached は最近使用順を更新してメモリ内の完成応答を返します。
//
// 引数: key(string)。返り値: []byte、存在(bool)。
func (s *Server) cached(key string) ([]byte, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	e, ok := s.cache[key]
	if !ok {
		return nil, false
	}
	s.lru.MoveToFront(e)
	return e.Value.(cacheEntry).Data, true
}

// remember は上限を超える古い応答を破棄して完成応答を記憶します。
//
// 引数: key(string)、b([]byte)。返り値: なし。ディスクキャッシュを作りません。
func (s *Server) remember(key string, b []byte) {
	limit := int64(s.cfg.Viewer.CacheMB) * 1024 * 1024
	if limit == 0 || int64(len(b)) > limit {
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if old, ok := s.cache[key]; ok {
		s.cacheBytes -= int64(len(old.Value.(cacheEntry).Data))
		s.lru.Remove(old)
		delete(s.cache, key)
	}
	for s.cacheBytes+int64(len(b)) > limit {
		last := s.lru.Back()
		item := last.Value.(cacheEntry)
		s.cacheBytes -= int64(len(item.Data))
		delete(s.cache, item.Key)
		s.lru.Remove(last)
	}
	e := s.lru.PushFront(cacheEntry{key, b})
	s.cache[key] = e
	s.cacheBytes += int64(len(b))
}

// data は範囲を検査して表示用データを返します。
//
// 引数: w(http.ResponseWriter)、r(*http.Request)。返り値: なし。保存約定だけを会計します。
func (s *Server) data(w http.ResponseWriter, r *http.Request) {
	body, status, err := s.dataBytes(r)
	if status == 0 {
		return
	}
	if err != nil {
		apiError(w, r, status, err)
		return
	}
	w.Header().Set("X-Chart-Data-SHA256", dataDigest(body))
	writeJSONBytes(w, r, http.StatusOK, body)
}

// dataBytes は数値APIと画像APIが同じ根拠・縮約・キャッシュを使う読取本体です。
//
// 引数: r(*http.Request)。返り値: JSON本文([]byte)、HTTP状態(int)、error。
// 状態0は依頼取消です。原板を読むのはキャッシュがない時の一度だけです。
func (s *Server) dataBytes(r *http.Request) ([]byte, int, error) {
	if expected := r.URL.Query().Get("data_sha256"); expected != "" {
		decoded, err := hex.DecodeString(expected)
		if err != nil || len(decoded) != sha256.Size {
			return nil, http.StatusBadRequest, fmt.Errorf("data_sha256はSHA256の16進64文字です")
		}
	}
	resource, path, err := s.resource(r)
	if err != nil {
		status := http.StatusBadRequest
		if errors.Is(err, os.ErrNotExist) {
			status = http.StatusNotFound
		}
		return nil, status, err
	}
	parse := func(name string) (float64, error) {
		v := r.URL.Query().Get(name)
		if v == "" {
			return 0, nil
		}
		n, e := strconv.ParseFloat(v, 64)
		if e != nil || !finite(n) {
			return 0, fmt.Errorf("%sが不正です", name)
		}
		return n, nil
	}
	from, err := parse("from")
	if err != nil {
		return nil, http.StatusBadRequest, err
	}
	to, err := parse("to")
	if err != nil {
		return nil, http.StatusBadRequest, err
	}
	width := 1200
	if raw := r.URL.Query().Get("width"); raw != "" {
		width, err = strconv.Atoi(raw)
		if err != nil || width < 1 || width > 4000 {
			return nil, http.StatusBadRequest, fmt.Errorf("widthは1〜4000です")
		}
	}
	mode, err := parseDisplayMode(r.URL.Query().Get("interval"), r.URL.Query().Get("price"))
	if err != nil {
		return nil, http.StatusBadRequest, err
	}
	stamp, err := inputStamp(resource, path)
	if err != nil {
		status := http.StatusUnprocessableEntity
		if errors.Is(err, os.ErrNotExist) {
			status = http.StatusNotFound
		}
		return nil, status, err
	}
	meta, _ := json.Marshal(resource)
	key := fmt.Sprintf("%s|%s|%.9f|%.9f|%d|%s|%s", meta, stamp, from, to, width, mode.Interval, mode.Price)
	if b, ok := s.cached(key); ok {
		return checkedDataBytes(r, b)
	}
	// ----------------------------------------
	// 巨大原板の同時全読を抑え、完成した応答だけをキャッシュします。
	s.parseMu.Lock()
	defer s.parseMu.Unlock()
	if r.Context().Err() != nil {
		return nil, 0, r.Context().Err()
	}
	if b, ok := s.cached(key); ok {
		return checkedDataBytes(r, b)
	}
	value, err := loadDataMode(s.cfg, resource, path, from, to, width, mode.Interval, mode.Price)
	if err != nil {
		return nil, http.StatusUnprocessableEntity, err
	}
	after, err := inputStamp(resource, path)
	if err != nil || after != stamp {
		return nil, http.StatusConflict, fmt.Errorf("読取中に入力が更新されました。再読込してください")
	}
	b, err := json.Marshal(value)
	if err != nil {
		return nil, http.StatusInternalServerError, err
	}
	s.remember(key, b)
	return checkedDataBytes(r, b)
}
