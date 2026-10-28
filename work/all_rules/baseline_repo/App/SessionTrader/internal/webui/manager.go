// Package webui は商品ごとに独立した売買運転を一つの画面へ公開します。
package webui

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	"futurealgorithm/sessiontrader/internal/config"
	"futurealgorithm/sessiontrader/internal/runner"
)

// Worker は一商品の運転入口です。試験では実通信をしない実装を渡します。
type Worker func(context.Context, config.Config, *runner.Control, func(runner.Snapshot)) error

// ProductState は画面に公開する商品別の状態です。
type ProductState struct {
	Product     string           `json:"product"`
	Reference   string           `json:"reference"`
	MaxPerSide  int              `json:"max_per_side"`
	DayMethod   string           `json:"day_method"`
	NightMethod string           `json:"night_method"`
	Enabled     bool             `json:"enabled"`
	Status      string           `json:"status"`
	Error       string           `json:"error"`
	Snapshot    *runner.Snapshot `json:"snapshot"`
}

// State は一つのHTTP応答にまとめる全商品の状態です。
type State struct {
	Mode          string         `json:"mode"`
	ServerTime    time.Time      `json:"server_time"`
	ControllerURL string         `json:"controller_url"`
	CSRFToken     string         `json:"csrf_token"`
	Closing       bool           `json:"closing"`
	Products      []ProductState `json:"products"`
}

type productWorker struct {
	operation sync.Mutex
	cfg       config.Config
	control   *runner.Control
	started   bool
	finished  bool
	state     ProductState
}

// Manager はHTTPからの操作と各商品からの通知を排他し、状態を混ぜません。
type Manager struct {
	mu        sync.Mutex
	cfg       config.Config
	ctx       context.Context
	cancel    context.CancelFunc
	worker    Worker
	products  []*productWorker
	wg        sync.WaitGroup
	closing   bool
	audit     *os.File
	closeOnce sync.Once
	closeErr  error
}

// NewManager は運転を開始せず、商品ごとの独立した制御と操作記録を準備します。
//
// 引数: cfg(config.Config)はWeb設定、worker(Worker)は運転処理です。
// 返り値: *Managerとerror。ここではAPI接続・発注・取消を行いません。
func NewManager(cfg config.Config, worker Worker) (*Manager, error) {
	if cfg.Web == nil || worker == nil {
		return nil, errors.New("Web設定と運転処理が必要です")
	}
	workers, err := cfg.WorkerConfigs()
	if err != nil {
		return nil, err
	}
	ctx, cancel := context.WithCancel(context.Background())
	m := &Manager{cfg: cfg, ctx: ctx, cancel: cancel, worker: worker}
	for _, item := range workers {
		ref, market := item.Selected()
		m.products = append(m.products, &productWorker{cfg: item, control: runner.NewControl(false),
			state: ProductState{Product: market.Product, Reference: ref, MaxPerSide: market.MaxPerSide,
				DayMethod: item.MethodID("Day"), NightMethod: item.MethodID("Night"), Status: "待機（新規取引OFF）"}})
	}
	mode := "dryrun"
	if !cfg.Trading.DryRun {
		mode = "live"
	}
	directory := filepath.Join(cfg.Path(cfg.Runtime.LogDirectory), mode, "web")
	if err = os.MkdirAll(directory, 0700); err != nil {
		cancel()
		return nil, err
	}
	m.audit, err = os.OpenFile(filepath.Join(directory, "操作.jsonl"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		cancel()
		return nil, err
	}
	return m, nil
}

// State は時点が揃った状態のコピーを返します。
//
// 引数: なし。返り値: State。通知データは公開後に変更しません。
func (m *Manager) State() State {
	m.mu.Lock()
	defer m.mu.Unlock()
	s := State{Mode: "dryrun", ServerTime: time.Now(), ControllerURL: m.cfg.Controller.BaseURL,
		Closing: m.closing, Products: make([]ProductState, 0, len(m.products))}
	if !m.cfg.Trading.DryRun {
		s.Mode = "live"
	}
	for _, p := range m.products {
		s.Products = append(s.Products, p.state)
	}
	return s
}

// SetEnabled は新規・追加だけを切り替え、開始済みの運転や所有建玉を初期化しません。
//
// 引数: product(string)は発注商品、enabled(bool)は新規許可、source(string)は監査用操作元。
// 返り値: error。不明商品・終了中・停止済みエラーは新規を許可しません。
func (m *Manager) SetEnabled(product string, enabled bool, source string) error {
	var p *productWorker
	for _, item := range m.products {
		_, market := item.cfg.Selected()
		if market.Product == product {
			p = item
			break
		}
	}
	if p == nil {
		return errors.New("対象の商品がありません")
	}
	p.operation.Lock()
	defer p.operation.Unlock()
	m.mu.Lock()
	if m.closing {
		m.mu.Unlock()
		return errors.New("アプリの終了処理中です")
	}
	if p.finished && enabled {
		m.mu.Unlock()
		return errors.New("この商品の運転は停止しています。表示されたエラーを確認してアプリを再起動してください")
	}
	if p.state.Enabled == enabled {
		m.mu.Unlock()
		return nil
	}
	auditErr := json.NewEncoder(m.audit).Encode(map[string]any{"at": time.Now(), "product": product,
		"enabled": enabled, "source": source, "dryrun": m.cfg.Trading.DryRun})
	if auditErr == nil {
		auditErr = m.audit.Sync()
	}
	if auditErr != nil && enabled {
		m.mu.Unlock()
		return auditErr
	}
	m.mu.Unlock()
	// 送信の完了待ちで他商品の画面更新や返済監視を止めないよう、全体ロックを外します。
	p.control.SetEnabled(enabled)
	m.mu.Lock()
	if m.closing {
		m.mu.Unlock()
		p.control.SetEnabled(false)
		return errors.New("アプリの終了処理中です")
	}
	defer m.mu.Unlock()
	p.state.Enabled = enabled
	if enabled && !p.started {
		p.started = true
		p.state.Status = "開始中（履歴準備）"
		m.wg.Add(1)
		go m.runProduct(p)
	}
	if auditErr != nil {
		return fmt.Errorf("新規OFFは適用しましたが、操作記録の保存に失敗しました: %w", auditErr)
	}
	return nil
}

// runProduct は一商品の完了を記録し、失敗した運転を無断で再起動しません。
//
// 引数: p(*productWorker)は管理対象。返り値: なし。
func (m *Manager) runProduct(p *productWorker) {
	defer m.wg.Done()
	err := m.worker(m.ctx, p.cfg, p.control, func(snapshot runner.Snapshot) {
		// 可変スライス・マップを運転側と共有しない独立したスナップショットにします。
		raw, marshalErr := json.Marshal(snapshot)
		if marshalErr != nil {
			return
		}
		var copied runner.Snapshot
		if json.Unmarshal(raw, &copied) != nil {
			return
		}
		m.mu.Lock()
		defer m.mu.Unlock()
		p.state.Snapshot = &copied
		p.state.Status = "稼働中"
	})
	p.operation.Lock()
	defer p.operation.Unlock()
	p.control.SetEnabled(false)
	m.mu.Lock()
	defer m.mu.Unlock()
	p.finished = true
	p.state.Enabled = false
	p.state.Status = "停止"
	if err != nil {
		p.state.Error = err.Error()
		p.state.Status = "停止（エラー）"
	}
	_ = json.NewEncoder(m.audit).Encode(map[string]any{"at": time.Now(), "product": p.state.Product,
		"event": "運転終了", "error": p.state.Error})
}

// StartConfigured は明示された初期ONだけを、HTTP待受開始後に適用します。
//
// 引数: なし。返り値: errorは操作記録の失敗です。初期OFFの商品はAPIに接続しません。
func (m *Manager) StartConfigured() error {
	for _, item := range m.cfg.Instruments {
		if item.Enabled {
			if err := m.SetEnabled(item.Product, true, "設定ファイル"); err != nil {
				return err
			}
		}
	}
	return nil
}

// Close は全商品の新規を止め、既存runnerの取消・返済処理の完了を待ちます。
//
// 引数: なし。返り値: errorは未返済などの商品別終了エラーです。
func (m *Manager) Close() error {
	m.closeOnce.Do(func() {
		m.mu.Lock()
		m.closing = true
		m.cancel()
		m.mu.Unlock()
		for _, p := range m.products {
			p.operation.Lock()
			p.control.SetEnabled(false)
			m.mu.Lock()
			p.state.Enabled = false
			m.mu.Unlock()
			p.operation.Unlock()
		}
		m.wg.Wait()
		m.mu.Lock()
		defer m.mu.Unlock()
		for _, p := range m.products {
			if p.state.Error != "" {
				m.closeErr = errors.Join(m.closeErr, fmt.Errorf("%s: %s", p.state.Product, p.state.Error))
			}
		}
		m.closeErr = errors.Join(m.closeErr, m.audit.Close())
	})
	return m.closeErr
}
