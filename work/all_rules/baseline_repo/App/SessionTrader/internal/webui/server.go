package webui

import (
	"context"
	"crypto/rand"
	"crypto/subtle"
	"embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"mime"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"futurealgorithm/sessiontrader/internal/config"
	"futurealgorithm/sessiontrader/internal/runner"
)

//go:embed assets/*
var assets embed.FS

// NewHandler は画面と同一オリジン限定の操作APIを構成します。
//
// 引数: manager(*Manager)は商品管理。返り値: http.Handlerとerror。乱数をCSRF対策に使用します。
func NewHandler(manager *Manager) (http.Handler, error) {
	var nonce [32]byte
	if _, err := rand.Read(nonce[:]); err != nil {
		return nil, err
	}
	token := hex.EncodeToString(nonce[:])
	files, err := fs.Sub(assets, "assets")
	if err != nil {
		return nil, err
	}
	static := http.FileServer(http.FS(files))
	mux := http.NewServeMux()
	mux.HandleFunc("GET /api/state", func(w http.ResponseWriter, r *http.Request) {
		state := manager.State()
		state.CSRFToken = token
		respond(w, http.StatusOK, state)
	})
	mux.HandleFunc("POST /api/products/{product}/enabled", func(w http.ResponseWriter, r *http.Request) {
		if subtle.ConstantTimeCompare([]byte(r.Header.Get("X-CSRF-Token")), []byte(token)) != 1 {
			respond(w, http.StatusForbidden, map[string]string{"error": "操作画面を再読み込みしてください"})
			return
		}
		kind, _, _ := mime.ParseMediaType(r.Header.Get("Content-Type"))
		if kind != "application/json" {
			respond(w, http.StatusUnsupportedMediaType, map[string]string{"error": "JSONで指定してください"})
			return
		}
		var body struct {
			Enabled *bool `json:"enabled"`
		}
		decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1024))
		decoder.DisallowUnknownFields()
		if err := decoder.Decode(&body); err != nil || body.Enabled == nil {
			respond(w, http.StatusBadRequest, map[string]string{"error": "enabledにtrueまたはfalseを指定してください"})
			return
		}
		var extra any
		if decoder.Decode(&extra) != io.EOF {
			respond(w, http.StatusBadRequest, map[string]string{"error": "JSONは一件だけ指定してください"})
			return
		}
		if err := manager.SetEnabled(r.PathValue("product"), *body.Enabled, "画面 / "+r.RemoteAddr); err != nil {
			respond(w, http.StatusConflict, map[string]string{"error": err.Error()})
			return
		}
		respond(w, http.StatusOK, map[string]any{"product": r.PathValue("product"), "enabled": *body.Enabled})
	})
	mux.HandleFunc("GET /", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/" && r.URL.Path != "/app.js" && r.URL.Path != "/style.css" {
			http.NotFound(w, r)
			return
		}
		static.ServeHTTP(w, r)
	})
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Referrer-Policy", "no-referrer")
		w.Header().Set("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
		if !validHost(r.Host) {
			http.Error(w, "IPアドレスまたはlocalhostで接続してください", http.StatusForbidden)
			return
		}
		if origin := r.Header.Get("Origin"); origin != "" {
			u, err := url.Parse(origin)
			scheme := "http"
			if r.TLS != nil {
				scheme = "https"
			}
			if err != nil || u.Scheme != scheme || !strings.EqualFold(u.Host, r.Host) || u.User != nil {
				http.Error(w, "別のサイトからの操作は受け付けません", http.StatusForbidden)
				return
			}
		}
		if r.Header.Get("Sec-Fetch-Site") == "cross-site" {
			http.Error(w, "別のサイトからの接続は受け付けません", http.StatusForbidden)
			return
		}
		mux.ServeHTTP(w, r)
	}), nil
}

// validHost は任意のDNS名を拒否し、外部サイトによるDNS再割当てを避けます。
//
// 引数: authority(string)はHTTP Host。返り値: boolは数値IPまたはlocalhostの場合true。
func validHost(authority string) bool {
	host := authority
	if parsed, _, err := net.SplitHostPort(authority); err == nil {
		host = parsed
	}
	host = strings.Trim(host, "[]")
	return strings.EqualFold(host, "localhost") || net.ParseIP(host) != nil
}

// respond はJSONをUTF-8で一回返します。
//
// 引数: w(http.ResponseWriter)、code(int)、body(any)。返り値: なし。
func respond(w http.ResponseWriter, code int, body any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(body)
}

// Run は設定したポートで画面を提供し、終了時は全商品の安全終了を待ちます。
//
// 引数: ctx(context.Context)は停止要求、cfg(config.Config)は検査済みWeb設定。
// 返り値: errorは待受失敗・終了時の未返済などです。
func Run(ctx context.Context, cfg config.Config) error {
	if err := cfg.Validate(); err != nil {
		return err
	}
	if cfg.Web == nil {
		return errors.New("[web]設定が必要です")
	}
	listener, err := net.Listen("tcp", net.JoinHostPort(cfg.Web.Host, strconv.Itoa(cfg.Web.Port)))
	if err != nil {
		return fmt.Errorf("Webの待受を開始できません: %w", err)
	}
	defer listener.Close()
	manager, err := NewManager(cfg, runner.RunControlled)
	if err != nil {
		return err
	}
	defer manager.Close()
	handler, err := NewHandler(manager)
	if err != nil {
		return err
	}
	server := &http.Server{Handler: handler, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second,
		WriteTimeout: 60 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 16 * 1024}
	done := make(chan error, 1)
	go func() { done <- server.Serve(listener) }()
	fmt.Printf("Web画面: http://%s / 初期OFFの商品は画面からONにしてください。\n", listener.Addr())
	if err = manager.StartConfigured(); err == nil {
		select {
		case <-ctx.Done():
		case err = <-done:
			if errors.Is(err, http.ErrServerClosed) {
				err = nil
			}
		}
	}
	// 待受を維持したまま新規を禁止し、状態画面で返済中の状況を確認可能にします。
	closeErr := manager.Close()
	shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	httpErr := server.Shutdown(shutdown)
	if httpErr != nil {
		_ = server.Close()
	}
	return errors.Join(err, closeErr, httpErr)
}
