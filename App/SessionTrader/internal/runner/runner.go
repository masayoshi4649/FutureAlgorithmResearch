// Package runner は受信、判断、発注、実約定の照合を一つの実行ループで結びます。
package runner

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"time"

	"futurealgorithm/sessiontrader/internal/config"
	"futurealgorithm/sessiontrader/internal/controller"
	"futurealgorithm/sessiontrader/internal/execution"
	"futurealgorithm/sessiontrader/internal/journal"
	"futurealgorithm/sessiontrader/internal/schedule"
	"futurealgorithm/sessiontrader/internal/strategy"
)

const algorithmVersion = "00131-v1"

type queuedSignal struct {
	Signal   strategy.Signal `json:"signal"`
	Evidence json.RawMessage `json:"evidence"`
	Created  time.Time       `json:"created"`
}

type savedRuntime struct {
	Version              int `json:"version"`
	Algorithm, Signature string
	Namespace            string          `json:"namespace"`
	Methods              *config.Methods `json:"methods,omitempty"`
	LegacyDataDirectory  string          `json:"legacy_data_directory,omitempty"`
	Plan                 schedule.Plan
	Contract             controller.Future
	Portfolio            json.RawMessage
	Queue                []queuedSignal
	Done                 map[string]bool
	IndexOffset          int64
	LastRawHash          string
}

type marketRuntime struct {
	Reference        string
	Manager          *execution.Manager
	Portfolio        *strategy.Portfolio
	Saved            savedRuntime
	Dirty            bool
	NextDispatch     time.Time
	OwnershipSince   time.Time
	OwnershipProblem string
}

type quote struct {
	Board    controller.Board
	Received time.Time
	InputID  int64
}

type app struct {
	cfg                              config.Config
	client, history                  *controller.Client
	store                            *journal.Store
	markets                          map[string]*marketRuntime
	registrations                    map[string]controller.Future
	symbols                          map[string]string
	quotes                           map[string]quote
	view                             controller.OrdersView
	viewAt                           time.Time
	bundle                           candleBundle
	features                         *strategy.Features
	plan                             schedule.Plan
	generation                       string
	cutoff, activeAt, bootstrapAfter time.Time
	lastSource                       map[string]float64
	lastHandled                      map[string]time.Time
	observed                         map[string]strategy.Observation
	inputCounts, decisionCounts      map[string]uint64
	lastIgnored                      map[string]string
	preparing                        bool
	prepareBuffer                    []bufferedBoard
	lastMessage                      map[string]time.Time
	nextCheckpoint, nextStatus       time.Time
	stopping                         bool
	shutdownEnd                      time.Time
	started                          time.Time
}

type bufferedBoard struct {
	Event   feedEvent
	InputID int64
}
type prepareResult struct {
	Prepared *prepared
	Err      error
}

// seconds はゼロ時計を0に保ったままUNIX秒へ変換します。
//
// 引数: at(time.Time)。返り値: float64。
func seconds(at time.Time) float64 {
	if at.IsZero() {
		return 0
	}
	return float64(at.UnixNano()) / 1e9
}

// timeFrom は戦略のUNIX秒をGo時計へ変換します。
//
// 引数: at(float64)。返り値: time.Time。
func timeFrom(at float64) time.Time { return time.Unix(0, int64(at*1e9)) }

// mode は保存先を実注文と仮想注文で分離します。
//
// 引数: dry(bool)。返り値: string。
func mode(dry bool) string {
	if dry {
		return "dryrun"
	}
	return "live"
}

// Run は当場履歴を準備して運転し、停止要求時は担当建玉の返済を試みます。
//
// 引数: parent(context.Context)は停止要求、cfg(config.Config)は検証済み設定。
// 返り値: errorは復旧不整合・保存失敗・停止後の未返済です。
func Run(parent context.Context, cfg config.Config) error {
	if err := cfg.Validate(); err != nil {
		return err
	}
	if err := validateMethodSelection(cfg); err != nil {
		return err
	}
	_, selected := cfg.Selected()
	base := filepath.Join(cfg.Path(cfg.Runtime.DataDirectory), mode(cfg.Trading.DryRun))
	data := filepath.Join(base, cfg.InstanceID())
	logs := filepath.Join(cfg.Path(cfg.Runtime.LogDirectory), mode(cfg.Trading.DryRun), cfg.InstanceID())
	legacyLock, err := acquireSharedLock(base)
	if err != nil {
		return fmt.Errorf("旧版運転または移行処理との同時起動はできません: %w", err)
	}
	defer legacyLock.Close()
	productLock, err := acquireProductLock(cfg)
	if err != nil {
		return err
	}
	defer productLock.Close()
	if err := os.MkdirAll(data, 0700); err != nil {
		return err
	}
	lock, err := acquireLock(data)
	if err != nil {
		return err
	}
	defer lock.Close()
	logLock, err := acquireLock(logs)
	if err != nil {
		return err
	}
	defer logLock.Close()
	if _, err = os.Stat(filepath.Join(data, selected.Product+".sqlite")); errors.Is(err, os.ErrNotExist) {
		if _, oldErr := os.Stat(filepath.Join(base, selected.Product+".sqlite")); oldErr == nil {
			return errors.New("旧版の取引状態があります。旧版を停止し、confのstartup.action=migrate_legacyとstartup.legacy_confを設定して移行してください。既存の所有建玉を無視して新規運転しません")
		} else if !errors.Is(oldErr, os.ErrNotExist) {
			return oldErr
		}
	} else if err != nil {
		return err
	}
	// 移行元の旧版も止めるため、注文台帳の復旧更新より先に共有ロックを確保します。
	migratedLock, err := acquireMigratedLegacyLock(filepath.Join(data, selected.Product+".sqlite"), base)
	if err != nil {
		return err
	}
	if migratedLock != nil {
		defer migratedLock.Close()
	}
	client, err := controller.New(cfg.Controller.BaseURL, duration(cfg.Controller.RequestTimeoutSeconds))
	if err != nil {
		return err
	}
	client.SetDryRun(cfg.Trading.DryRun)
	history, err := controller.New(cfg.Controller.BaseURL, duration(cfg.Controller.HistoryTimeoutSeconds))
	if err != nil {
		return err
	}
	store, err := journal.Open(filepath.Join(data, "market.sqlite"), filepath.Join(logs, "market"))
	if err != nil {
		return err
	}
	defer store.Close()
	a := &app{cfg: cfg, client: client, history: history, store: store,
		markets: map[string]*marketRuntime{}, registrations: map[string]controller.Future{},
		symbols: map[string]string{}, quotes: map[string]quote{}, lastSource: map[string]float64{}, lastHandled: map[string]time.Time{}, lastMessage: map[string]time.Time{}, started: time.Now()}
	defer func() {
		for _, m := range a.markets {
			_ = m.Manager.Close()
		}
	}()
	for _, ref := range []string{"TOPIX", "NK225"} {
		mc := cfg.Markets[ref]
		if !mc.Enabled {
			continue
		}
		m, err := execution.Open(filepath.Join(logs, mc.Product), filepath.Join(data, mc.Product+".sqlite"),
			cfg.Trading.DryRun, mc.Product, cfg.Products[mc.Product].PointValue, mc.MaxPerSide)
		if err != nil {
			return err
		}
		r := &marketRuntime{Reference: ref, Manager: m, Saved: savedRuntime{Version: 1, Algorithm: algorithmVersion, Signature: cfg.Signature(), Done: map[string]bool{}}}
		a.markets[ref] = r
		if raw := m.State(); len(raw) > 0 && string(raw) != "null" {
			if err = json.Unmarshal(raw, &r.Saved); err != nil {
				return fmt.Errorf("%s 復元: %w", ref, err)
			}
			if r.Saved.Version != 1 || r.Saved.Algorithm != algorithmVersion || r.Saved.Signature != cfg.Signature() {
				if err := resetChangedStrategy(r, cfg, raw); err != nil {
					return err
				}
			}
			if r.Saved.Methods != nil && *r.Saved.Methods != resolvedMethods(cfg) {
				return fmt.Errorf("%s 保存した昼夜の手法と設定指紋が一致しません", ref)
			}
			if rawPortfolio := bytes.TrimSpace(r.Saved.Portfolio); len(rawPortfolio) > 0 && !bytes.Equal(rawPortfolio, []byte("null")) {
				r.Portfolio, err = strategy.Restore(r.Saved.Portfolio)
				if err != nil {
					return err
				}
			}
			if r.Saved.Done == nil {
				r.Saved.Done = map[string]bool{}
			}
		}
		if err = a.applyFills(r); err != nil {
			return err
		}
		if r.Saved.Namespace == "" {
			r.Saved.Namespace, err = newNamespace()
			if err != nil {
				return err
			}
		}
		if r.Portfolio != nil {
			if r.Portfolio.Config.Namespace != "" && r.Portfolio.Config.Namespace != r.Saved.Namespace {
				return fmt.Errorf("%s 保存注文IDの名前空間が一致しません", ref)
			}
			r.Portfolio.Config.Namespace = r.Saved.Namespace
		}
		r.Dirty = true
		if err = a.checkpoint(r); err != nil {
			return err
		}
	}
	if err = a.store.Event("起動", "", "", "", time.Now(), map[string]any{"algorithm": algorithmVersion, "signature": cfg.Signature(), "dryrun": cfg.Trading.DryRun, "instance_id": cfg.InstanceID(), "product": selected.Product}); err != nil {
		return err
	}
	fmt.Printf("%s [%s / %s / %s] 起動。履歴と新鮮な板を準備します。\n", time.Now().Format(time.RFC3339), mode(cfg.Trading.DryRun), cfg.InstanceID(), selected.Product)
	// ----------------------------------------
	// 停止要求後も照合・返済用の通信を継続する独立コンテキストです。
	runCtx, cancel := context.WithCancel(context.Background())
	defer cancel()
	events, stopFeed := startFeed(runCtx, client, cfg)
	defer stopFeed()
	preparedCh := make(chan prepareResult, 1)
	var preparingDone chan struct{}
	var cancelPrepare context.CancelFunc
	// 実行ループの終了後に履歴保存だけが走り続けないよう、DBを閉じる前に待ちます。
	defer func() {
		if cancelPrepare != nil {
			cancelPrepare()
		}
		if preparingDone != nil {
			<-preparingDone
		}
	}()
	ticker := time.NewTicker(250 * time.Millisecond)
	defer ticker.Stop()
	stop := parent.Done()
	for {
		select {
		case <-stop:
			stop = nil
			a.stopping = true
			a.shutdownEnd = time.Now().Add(duration(cfg.Runtime.ShutdownSeconds))
			if cancelPrepare != nil {
				cancelPrepare()
			}
			fmt.Println("新規を停止し、担当建玉の返済と未確定注文の照合を行います。")
			if err = a.tick(runCtx, time.Now()); err != nil {
				return err
			}
		case event, ok := <-events:
			if !ok {
				return errors.New("受信処理が終了しました")
			}
			if err = a.handle(runCtx, event); err != nil {
				return err
			}
		case now := <-ticker.C:
			if err = a.tick(runCtx, now); err != nil {
				return err
			}
		case result := <-preparedCh:
			a.preparing = false
			if result.Err != nil {
				a.prepareBuffer = nil
				if !a.stopping {
					if err = a.notice("履歴準備", result.Err); err != nil {
						return err
					}
				}
			} else if !a.stopping {
				snap := a.bundle.One["TOPIX"].Snapshot
				if result.Prepared.Plan.ID == snap.SessionID && result.Prepared.Generation == snap.Generation {
					if err = a.activate(result.Prepared); err != nil {
						return err
					}
					for _, b := range a.prepareBuffer {
						if b.Event.At.After(a.cutoff) {
							if err = a.processReference(runCtx, b.Event, b.InputID); err != nil {
								return err
							}
						}
					}
				}
				a.prepareBuffer = nil
			}
		}
		if !a.stopping && !a.preparing && a.needsPrepare() && time.Now().After(a.bootstrapAfter) {
			a.bootstrapAfter = time.Now().Add(10 * time.Second)
			prepCtx, cancelPrep := context.WithCancel(runCtx)
			cancelPrepare = cancelPrep
			a.preparing = true
			a.prepareBuffer = nil
			preparingDone = make(chan struct{})
			bundle := a.bundle
			done := preparingDone
			go func() {
				defer close(done)
				defer cancelPrep()
				p, e := prepare(prepCtx, a.history, a.cfg, bundle, a.store)
				preparedCh <- prepareResult{p, e}
			}()
		}
		if a.stopping {
			if a.flat() {
				return a.finish("停止完了", nil)
			}
			if time.Now().After(a.shutdownEnd) {
				return a.finish("未返済あり", errors.New("停止期限になりました。未返済または結果不明の注文をSQLiteに保持しました。口座・ログを確認してください"))
			}
		}
	}
}

// notice は同じ通信障害を30秒単位にまとめ、運転ログへ残します。
//
// 引数: kind(string)、err(error)。返り値: errorは保存失敗のみです。
func (a *app) notice(kind string, err error) error {
	if err == nil {
		return nil
	}
	key := kind + ":" + err.Error()
	now := time.Now()
	if now.Sub(a.lastMessage[key]) < 30*time.Second {
		return nil
	}
	a.lastMessage[key] = now
	fmt.Printf("%s [%s] %v\n", now.Format(time.RFC3339), kind, err)
	return a.store.Event(kind, a.plan.ID, "", "", now, map[string]string{"message": err.Error()})
}

// handle は各受信イベントを保存し、同一ループで戦略へ適用します。
//
// 引数: ctx(context.Context)、e(feedEvent)。返り値: errorは保存・状態矛盾です。
func (a *app) handle(ctx context.Context, e feedEvent) error {
	switch e.Kind {
	case "通信", "PUSH中断":
		return a.notice(e.Kind, e.Err)
	case "登録":
		reg := map[string]controller.Future{}
		symbols := map[string]string{}
		for _, f := range e.Registrations.Futures {
			if f.FutureCode == "" || f.Symbol == "" {
				continue
			}
			if old, ok := reg[f.FutureCode]; ok && old.Symbol != f.Symbol {
				return errors.New("同一商品の登録限月が複数あります")
			}
			reg[f.FutureCode] = f
			symbols[f.Symbol] = f.FutureCode
		}
		a.registrations = reg
		a.symbols = symbols
	case "口座":
		a.view = e.View
		a.viewAt = e.At
		for _, m := range a.markets {
			if _, err := m.Manager.Reconcile(e.View); err != nil {
				return err
			}
			if err := a.applyFills(m); err != nil {
				return err
			}
			if a.accountFresh(e.At) {
				if err := m.Manager.VerifyOwned(e.View); err != nil {
					m.OwnershipProblem = err.Error()
					if m.OwnershipSince.IsZero() {
						m.OwnershipSince = e.At
					}
					if err := a.notice("所有建玉の口座照合", err); err != nil {
						return err
					}
					if e.At.Sub(m.OwnershipSince) >= duration(a.cfg.Runtime.AccountMaxAgeSeconds) {
						if saveErr := a.checkpoint(m); saveErr != nil {
							return saveErr
						}
						return fmt.Errorf("%s 口座と所有台帳の不一致が継続しました。数量を推測で変更せず停止します: %s", m.Reference, m.OwnershipProblem)
					}
				} else {
					m.OwnershipSince = time.Time{}
					m.OwnershipProblem = ""
				}
			}
		}
	case "足":
		a.bundle = e.Candles
		snap := e.Candles.One["TOPIX"].Snapshot
		if a.features != nil && snap.SessionID == a.plan.ID && snap.Generation == a.generation {
			if err := a.addCandles(e.Candles, e.At); err != nil {
				return err
			}
		}
	case "板":
		return a.onBoard(ctx, e)
	}
	return nil
}

// needsPrepare はセッションまたは履歴世代の変更を判定します。
//
// 引数: なし。返り値: boolは同期準備が必要な場合trueです。
func (a *app) needsPrepare() bool {
	snap, ok := a.bundle.One["TOPIX"]
	if !ok || a.view.Session == nil {
		return false
	}
	if !snap.Snapshot.Session.StartsAt.Equal(a.view.Session.StartsAt) {
		return false
	}
	if _, ok = a.registrations["TOPIX"]; !ok {
		return false
	}
	if _, ok = a.registrations["NK225"]; !ok {
		return false
	}
	for _, m := range a.markets {
		if _, ok = a.registrations[a.cfg.Markets[m.Reference].Product]; !ok {
			return false
		}
	}
	if a.features != nil && snap.Snapshot.SessionID == a.plan.ID && snap.Snapshot.Generation == a.generation {
		return false
	}
	for _, m := range a.markets {
		if m.Portfolio != nil && m.Saved.Plan.ID != snap.Snapshot.SessionID && (len(m.Manager.Positions()) > 0 || m.Manager.HasPending()) {
			return false
		}
	}
	return true
}

// activate は暖機特徴と実約定状態を結合し、過去の新規発注を禁止します。
//
// 引数: p(*prepared)。返り値: errorは復元・照合失敗です。
func (a *app) activate(p *prepared) error {
	for ref, m := range a.markets {
		mc := a.cfg.Markets[ref]
		contract := a.registrations[mc.Product]
		if m.Portfolio == nil || m.Saved.Plan.ID != p.Plan.ID {
			if len(m.Manager.Positions()) > 0 || m.Manager.HasPending() {
				return errors.New("前場の所有建玉・未確定注文を残したまま場を切り替えられません")
			}
			params, err := methodParameters(a.cfg, ref, p.Plan.Kind)
			if err != nil {
				return err
			}
			extra := p.Plan.TopixExtra
			if ref == "NK225" {
				extra = p.Plan.NKExtra
			}
			m.Portfolio, err = strategy.New(strategy.Config{Namespace: m.Saved.Namespace, Reference: ref, Product: mc.Product, CoreQuantity: mc.CoreQuantity, ExtraMaxQuantity: mc.ExtraQuantity,
				Cap: mc.MaxPerSide, LargeTick: a.cfg.Products[ref].Tick, PointValue: a.cfg.Products[mc.Product].PointValue, Parameters: params},
				strategy.Session{ID: p.Plan.ID, Kind: p.Plan.Kind, Start: seconds(p.Plan.Start), End: seconds(p.Plan.End), ForceClose: seconds(p.Plan.ForceClose), USOpen: seconds(p.Plan.USOpen), ExtraAt: seconds(extra)})
			if err != nil {
				return err
			}
			m.Saved.Plan = p.Plan
			// 研究手法の候補生成は過去から進め、過去の新規は実注文・仮想実玉にしません。
			if m.Portfolio.Research != nil {
				for _, o := range p.Rows {
					if o.Reference == ref {
						if err := m.Portfolio.Advance(o); err != nil {
							return err
						}
					}
				}
			}
			m.Saved.Contract = contract
			m.Saved.Queue = nil
			m.Saved.IndexOffset = 0
			m.Saved.LastRawHash = ""
		} else {
			if m.Saved.Contract.Symbol != contract.Symbol {
				return fmt.Errorf("%s 保存限月と登録限月が異なります。自動で別限月へ注文しません", ref)
			}
			// 欠測期間は既存実玉の管理だけ進め、古い気配で約定させません。
			after := m.Portfolio.LastTime
			anchor, exact := restoreAnchor(m, p)
			m.Saved.IndexOffset = m.Portfolio.LastIndex - anchor
			if !exact {
				if err := a.store.Event("復元原行の時計接続", p.Plan.ID, ref, "", time.Now(), map[string]any{"last_time": after, "anchor": anchor,
					"note": "最後の原文を特定できないため同価格時計の区間は新規に利用せず、直後から管理を再開"}); err != nil {
					return err
				}
			}
			for _, o := range p.Rows {
				if o.Reference != ref || o.Index <= anchor {
					continue
				}
				sourceIndex := o.Index
				o = shiftObservation(o, m.Saved.IndexOffset)
				if err := m.Portfolio.Advance(o); err != nil {
					return err
				}
				if hashes := p.SourceHashes[ref]; sourceIndex >= 0 && sourceIndex < int64(len(hashes)) {
					m.Saved.LastRawHash = hashes[sourceIndex]
				}
			}
		}
		if err := m.Manager.EnsureSession(p.Plan.ID); err != nil {
			return err
		}
		m.Dirty = true
		if err := a.checkpoint(m); err != nil {
			return err
		}
	}
	a.features = p.Features
	a.plan = p.Plan
	a.generation = p.Generation
	a.cutoff = p.Cutoff
	a.activeAt = time.Now()
	a.lastSource = map[string]float64{}
	for ref, o := range p.Last {
		a.lastSource[ref] = o.Time
	}
	a.observed = map[string]strategy.Observation{}
	a.lastIgnored = map[string]string{}
	fmt.Printf("%s [履歴同期完了] %s / %s / 適用手法=%s（昼=%s・夜=%s）。指標が揃うまで準備し、新鮮な受信から判断します。\n", time.Now().Format(time.RFC3339), p.Plan.ID, mode(a.cfg.Trading.DryRun), a.cfg.MethodID(p.Plan.Kind), a.cfg.MethodID("Day"), a.cfg.MethodID("Night"))
	a.nextStatus = time.Time{}
	return a.store.Event("準備完了", p.Plan.ID, "", "", time.Now(), map[string]any{"plan": p.Plan, "generation": p.Generation, "cutoff": p.Cutoff, "algorithm": algorithmVersion,
		"method": a.cfg.MethodID(p.Plan.Kind), "methods": map[string]string{"day": a.cfg.MethodID("Day"), "night": a.cfg.MethodID("Night")}})
}

// addCandles はライブで実際に受信した時刻を持つ確定足だけを追加します。
//
// 引数: b(candleBundle)、at(time.Time)。返り値: errorは未来足・改訂足です。
func (a *app) addCandles(b candleBundle, at time.Time) error {
	for _, ref := range []string{"TOPIX", "NK225"} {
		for _, interval := range []int{60, 300} {
			data := b.One[ref]
			if interval == 300 {
				data = b.Five[ref]
			}
			rows := make([]strategy.Candle, 0, len(data.Data))
			for _, c := range data.Data {
				rows = append(rows, strategy.Candle{Time: seconds(c.Time), Open: c.Open, High: c.High, Low: c.Low, Close: c.Close, Closed: c.Closed, Received: seconds(at)})
			}
			if _, err := a.features.AddCandles(ref, interval, rows, seconds(at)); err != nil {
				return err
			}
		}
	}
	return nil
}

// onBoard は原文IDを確定後に特徴・判断・注文待ち列を更新します。
//
// 引数: ctx(context.Context)、e(feedEvent)。返り値: errorは保存・戦略不整合です。
func (a *app) onBoard(ctx context.Context, e feedEvent) error {
	code, ok := a.symbols[e.Board.Symbol]
	if !ok {
		return nil
	}
	raw := e.Board.Raw
	if len(raw) == 0 {
		var err error
		raw, err = json.Marshal(e.Board)
		if err != nil {
			return err
		}
	}
	var id int64
	snapshot := a.bundle.One["TOPIX"].Snapshot
	if snapshot.SessionID != "" && snapshot.Generation != "" && !e.At.Before(snapshot.Session.StartsAt) && e.At.Before(snapshot.Session.EndsAt) {
		var err error
		id, err = a.store.RecordBook(snapshot.SessionID, snapshot.Generation, code, e.At, raw)
		if err != nil {
			return err
		}
	} else {
		if err := a.store.Event("立会照合前の受信", "", code, "", e.At, map[string]any{"raw": json.RawMessage(raw)}); err != nil {
			return err
		}
	}
	a.quotes[code] = quote{Board: e.Board, Received: e.At, InputID: id}
	if a.inputCounts == nil {
		a.inputCounts = map[string]uint64{}
	}
	a.inputCounts[code]++
	if a.preparing && (code == "TOPIX" || code == "NK225") {
		a.prepareBuffer = append(a.prepareBuffer, bufferedBoard{e, id})
	}
	return a.processReference(ctx, e, id)
}

// processReference は保存済みの板を特徴へ供給し、履歴再接続で同じ判断を繰り返しません。
//
// 引数: ctx(context.Context)、e(feedEvent)、id(int64)は原文ID。返り値: error。
func (a *app) processReference(ctx context.Context, e feedEvent, id int64) error {
	code, ok := a.symbols[e.Board.Symbol]
	if !ok {
		return nil
	}
	if a.features == nil || (code != "TOPIX" && code != "NK225") || !e.At.After(a.cutoff) {
		return nil
	}
	clock, err := time.Parse(time.RFC3339Nano, e.Board.CurrentPriceTime)
	if err != nil {
		a.ignoreReference(code, "価格時刻が不明")
		return nil
	}
	if clock.Before(a.plan.Start) || !clock.Before(a.plan.End) {
		a.ignoreReference(code, "当場外の価格時刻")
		return nil
	}
	if clock.After(e.At) {
		a.ignoreReference(code, "価格時刻が端末の受信時刻より未来")
		return nil
	}
	t := seconds(clock)
	if e.Board.CurrentPrice <= 0 || math.IsNaN(e.Board.CurrentPrice) || math.IsInf(e.Board.CurrentPrice, 0) {
		a.ignoreReference(code, "現在価格が不正")
		return nil
	}
	if t < a.lastSource[code] {
		a.ignoreReference(code, "価格時計が逆行")
		return nil
	}
	o, err := a.features.OnBoard(referenceBoard(code, t, seconds(e.At), e.Board))
	if err != nil {
		return err
	}
	a.lastSource[code] = t
	m := a.markets[code]
	if m == nil || m.Portfolio == nil || m.Saved.Plan.ID != a.plan.ID {
		return nil
	}
	if !e.At.After(a.lastHandled[code]) {
		return nil
	}
	if t < m.Portfolio.LastTime {
		return nil
	}
	o = shiftObservation(o, m.Saved.IndexOffset)
	if o.Index <= m.Portfolio.LastIndex {
		return nil
	}
	// 準備中にたまった受信では入口を作らず、返済条件だけ現在まで進めます。
	fresh := !e.At.Before(a.activeAt) && time.Since(e.At) <= duration(a.cfg.Runtime.QuoteMaxAgeSeconds)
	allowed := fresh && a.canEnter(m, time.Now())
	signals, err := m.Portfolio.Observe(o, allowed)
	if err != nil {
		return err
	}
	a.lastHandled[code] = e.At
	if a.observed == nil {
		a.observed = map[string]strategy.Observation{}
	}
	if a.decisionCounts == nil {
		a.decisionCounts = map[string]uint64{}
	}
	a.observed[code] = o
	a.decisionCounts[code]++
	a.ignoreReference(code, "")
	m.Saved.LastRawHash = rawHash(e.Board.Raw)
	m.Dirty = true
	if err = a.enqueue(m, signals, id, e.At); err != nil {
		return err
	}
	if fresh {
		return a.dispatch(ctx, m, time.Now())
	}
	return nil
}

// rawHash は同じ価格時計に複数ある原板を区別する指紋を返します。
//
// 引数: raw(json.RawMessage)。返り値: stringはSHA256、空原文は空文字です。
func rawHash(raw json.RawMessage) string {
	if len(raw) == 0 {
		return ""
	}
	return fmt.Sprintf("%x", sha256.Sum256(raw))
}

// restoreAnchor は再取得履歴内の最後に処理した行を原文と時計から探します。
//
// 引数: m(*marketRuntime)、p(*prepared)。返り値: int64は特徴連番、boolは原文一致です。
func restoreAnchor(m *marketRuntime, p *prepared) (int64, bool) {
	anchor := int64(-1)
	exact := int64(-1)
	for _, o := range p.Rows {
		if o.Reference != m.Reference || o.Time > m.Portfolio.LastTime {
			continue
		}
		anchor = o.Index
		hashes := p.SourceHashes[m.Reference]
		if o.Time == m.Portfolio.LastTime && m.Saved.LastRawHash != "" && o.Index >= 0 && o.Index < int64(len(hashes)) && hashes[o.Index] == m.Saved.LastRawHash {
			exact = o.Index
		}
	}
	if exact >= 0 {
		return exact, true
	}
	return anchor, false
}

// shiftObservation は特徴連番と逆行根拠を同じ差分で復元座標へ移します。
//
// 引数: o(strategy.Observation)、delta(int64)。返り値: strategy.Observation。
func shiftObservation(o strategy.Observation, delta int64) strategy.Observation {
	o.Index += delta
	o.E01.InputIndex += delta
	if o.E01.AdverseSource >= 0 {
		o.E01.AdverseSource += delta
	}
	return o
}

// accountFresh は上流接続と照会時刻・送信可能時間を別々に検査します。
//
// 引数: now(time.Time)。返り値: boolは送信の前提を満たす場合trueです。
func (a *app) accountFresh(now time.Time) bool {
	return a.accountBlockReason(now) == ""
}

// validQuote はPUSH受信鮮度と正常な売買気配を検査します。
//
// 引数: code(string)、now(time.Time)。返り値: quoteとbool。
func (a *app) validQuote(code string, now time.Time) (quote, bool) {
	q, ok := a.quotes[code]
	if !ok {
		return q, false
	}
	age := now.Sub(q.Received)
	bid, ask := q.Board.Buy1.Price, q.Board.Sell1.Price
	return q, age >= -time.Second && age <= duration(a.cfg.Runtime.QuoteMaxAgeSeconds) && bid > 0 && ask > bid &&
		!math.IsNaN(bid) && !math.IsNaN(ask) && !math.IsInf(bid, 0) && !math.IsInf(ask, 0)
}

// canEnter は新規に必要な二市場・発注商品の鮮度と立会一致を判定します。
//
// 引数: m(*marketRuntime)、now(time.Time)。返り値: bool。
func (a *app) canEnter(m *marketRuntime, now time.Time) bool {
	return a.entryBlockReason(m, now) == ""
}

// enqueue は条件成立の根拠を保存し、送信前に注文予約を永続化します。
//
// 引数: m(*marketRuntime)、signals([]strategy.Signal)、inputID(int64)、received(time.Time)。
// 返り値: errorは保存失敗です。
func (a *app) enqueue(m *marketRuntime, signals []strategy.Signal, inputID int64, received time.Time) error {
	for _, s := range signals {
		evidence, err := json.Marshal(map[string]any{"algorithm": algorithmVersion, "signature": a.cfg.Signature(),
			"instance_id": a.cfg.InstanceID(), "order_namespace": m.Saved.Namespace,
			"input_id": inputID, "generation": a.generation, "received": received, "decision": s})
		if err != nil {
			return err
		}
		m.Saved.Queue = append(m.Saved.Queue, queuedSignal{s, evidence, time.Now()})
		if err = m.Manager.Event("発注判断", m.Saved.Plan.ID, m.Reference, s.ID, time.Now(), json.RawMessage(evidence)); err != nil {
			return err
		}
	}
	if len(signals) > 0 {
		m.Dirty = true
		return a.checkpoint(m)
	}
	return nil
}

// applyFills は保存済み実約定を一度だけ戦略へ反映し、終了した残数量を解除します。
//
// 引数: m(*marketRuntime)。返り値: errorは約定所有・数量の矛盾です。
func (a *app) applyFills(m *marketRuntime) error {
	fills := m.Manager.OutstandingFills()
	if len(fills) > 0 && m.Portfolio == nil {
		return errors.New("未反映約定に対応する戦略状態がありません")
	}
	for _, f := range fills {
		closed := make([]strategy.LotTarget, 0, len(f.Closed))
		for _, target := range f.Closed {
			closed = append(closed, strategy.LotTarget{ID: target.HoldID, Quantity: target.Quantity})
		}
		if err := m.Portfolio.OnFill(strategy.Fill{SignalID: f.IntentID, ExecutionID: f.ID, Quantity: f.Quantity, Price: f.Price, Time: seconds(f.At), Fee: f.Fee, HoldID: f.HoldID, Closed: closed}); err != nil {
			return err
		}
		m.Dirty = true
		fmt.Printf("%s [%s] %s %s %s %s %d枚 @%.4f 損益%+.0f円 %s\n", f.At.Format(time.RFC3339), mode(a.cfg.Trading.DryRun), f.Product, f.Owner, f.TradeType, f.Side, f.Quantity, f.Price, f.PnL, f.Reason)
	}
	for _, o := range m.Manager.Orders() {
		if !o.Done || m.Saved.Done[o.IntentID] {
			continue
		}
		if m.Portfolio == nil {
			return errors.New("注文終了に対応する戦略状態がありません")
		}
		if _, exists := m.Portfolio.Orders[o.IntentID]; exists {
			if err := m.Portfolio.OnOrderDone(o.IntentID); err != nil {
				return err
			}
		}
		m.Saved.Done[o.IntentID] = true
		m.Dirty = true
	}
	if m.Portfolio != nil {
		expected := map[string]int{}
		for _, p := range m.Portfolio.Status().Positions {
			side := "buy"
			if p.Side < 0 {
				side = "sell"
			}
			expected[p.Owner+":"+side] += p.Quantity
		}
		for _, owner := range []string{"core", "extra", "addon", "episode"} {
			for _, side := range []string{"buy", "sell"} {
				if expected[owner+":"+side] != m.Manager.Quantity(owner, side) {
					return fmt.Errorf("%s %s %s 戦略と約定台帳の枚数が異なります", m.Reference, owner, side)
				}
			}
		}
		for _, h := range m.Manager.Positions() {
			if h.Owner != "core" && h.Owner != "extra" && h.Owner != "addon" && h.Owner != "episode" {
				return errors.New("未知担当の所有玉があります")
			}
		}
	}
	if m.Dirty {
		return a.checkpoint(m)
	}
	return nil
}

// checkpoint は送信待ち・戦略状態を約定ACKと同じ正本へ記録します。
//
// 引数: m(*marketRuntime)。返り値: errorは保存失敗です。
func (a *app) checkpoint(m *marketRuntime) error {
	if m.Saved.Signature == a.cfg.Signature() {
		methods := resolvedMethods(a.cfg)
		if m.Saved.Methods != nil && *m.Saved.Methods != methods {
			return fmt.Errorf("%s 保存した昼夜の手法と設定指紋が一致しません", m.Reference)
		}
		m.Saved.Methods = &methods
	}
	if m.Portfolio != nil {
		data, err := m.Portfolio.Dump()
		if err != nil {
			return err
		}
		m.Saved.Portfolio = data
	}
	data, err := json.Marshal(m.Saved)
	if err != nil {
		return err
	}
	if err = m.Manager.Checkpoint(data); err != nil {
		return err
	}
	m.Dirty = false
	return nil
}

// dispatch は現在の発注商品気配で一件だけ送信し、結果不明を再送しません。
//
// 引数: ctx(context.Context)、m(*marketRuntime)、now(time.Time)。返り値: errorは保存・内部矛盾です。
func (a *app) dispatch(ctx context.Context, m *marketRuntime, now time.Time) error {
	if m.Portfolio == nil || len(m.Saved.Queue) == 0 {
		return nil
	}
	// 復旧時は送信済みIDを注文台帳で判定します。価格や時刻を変更して再送しません。
	orders := map[string]bool{}
	for _, o := range m.Manager.Orders() {
		orders[o.IntentID] = true
	}
	for len(m.Saved.Queue) > 0 && orders[m.Saved.Queue[0].Signal.ID] {
		m.Saved.Queue = m.Saved.Queue[1:]
		m.Dirty = true
	}
	if m.Dirty {
		if err := a.checkpoint(m); err != nil {
			return err
		}
	}
	if len(m.Saved.Queue) == 0 || m.Manager.HasPending() {
		return nil
	}
	item := m.Saved.Queue[0]
	s := item.Signal
	quiet := a.quiet(m, now)
	if s.Action == "new" && (a.stopping || !now.Before(m.Saved.Plan.ForceClose) || quiet && quietOwner(m, s.Owner) ||
		now.Sub(item.Created) > duration(a.cfg.Runtime.EntryOrderTimeoutSeconds)) {
		if err := m.Portfolio.OnOrderRejected(s.ID); err != nil {
			return err
		}
		m.Saved.Queue = m.Saved.Queue[1:]
		m.Dirty = true
		if err := m.Manager.Event("新規判断期限切れ", m.Saved.Plan.ID, m.Reference, s.ID, now, item); err != nil {
			return err
		}
		return a.checkpoint(m)
	}
	if s.Action == "new" && !a.canEnter(m, now) {
		return nil
	}
	if !a.accountFresh(now) || now.Before(m.NextDispatch) || m.OwnershipProblem != "" {
		return nil
	}
	product := a.cfg.Markets[m.Reference].Product
	q, fresh := a.validQuote(product, now)
	fresh = fresh && q.Board.Symbol == m.Saved.Contract.Symbol
	price := q.Board.Sell1.Price
	if s.Side < 0 {
		price = q.Board.Buy1.Price
	}
	if !fresh {
		if a.cfg.Trading.DryRun || s.Action == "new" {
			return nil
		}
		// 実返済の成行価格は上流約定で確定します。記録上の参考値に限定します。
		price = 0
		for _, h := range m.Manager.Positions() {
			if h.Owner == s.Owner {
				price = h.Price
				break
			}
		}
	}
	if price <= 0 || math.IsNaN(price) || math.IsInf(price, 0) {
		return nil
	}
	side := "buy"
	if s.Side < 0 {
		side = "sell"
	}
	expiry := now.Add(duration(a.cfg.Runtime.EntryOrderTimeoutSeconds))
	if expiry.After(a.view.Session.SendUntil) {
		expiry = a.view.Session.SendUntil
	}
	evidence, err := json.Marshal(map[string]any{"decision": json.RawMessage(item.Evidence), "execution_input_id": q.InputID,
		"execution_received": q.Received, "execution_quote_fresh": fresh, "sent_at": now})
	if err != nil {
		return err
	}
	intent := execution.Intent{ID: s.ID, Owner: s.Owner, Product: product, Evidence: evidence,
		Session: m.Saved.Plan.ID, ContractSymbol: m.Saved.Contract.Symbol, Side: side, TradeType: s.Action, Reason: s.Reason,
		Quantity: s.Quantity, Price: price, At: now, ExpiresAt: expiry}
	for _, target := range s.Targets {
		intent.ClosePositions = append(intent.ClosePositions, controller.ClosePosition{HoldID: target.ID, Quantity: target.Quantity})
	}
	_, sendErr := m.Manager.Submit(ctx, a.client, intent, a.view)
	known := false
	for _, o := range m.Manager.Orders() {
		if o.IntentID == s.ID {
			known = true
			break
		}
	}
	if known {
		m.Saved.Queue = m.Saved.Queue[1:]
		m.Dirty = true
		if err = a.applyFills(m); err != nil {
			return err
		}
		if err = a.checkpoint(m); err != nil {
			return err
		}
	} else if sendErr != nil {
		// 送信前の上限・所有検査による拒否。再参加は新たな判断を要求します。
		if err = m.Portfolio.OnOrderRejected(s.ID); err != nil {
			return err
		}
		m.Saved.Queue = m.Saved.Queue[1:]
		m.Dirty = true
		if err = a.checkpoint(m); err != nil {
			return err
		}
	}
	if sendErr != nil {
		m.NextDispatch = now.Add(duration(a.cfg.Controller.ReconnectSeconds))
		return a.notice("注文照合待ちまたは拒否", sendErr)
	}
	return nil
}

// quiet は夜間主担当だけの米国開始前後の静観時間を返します。
//
// 引数: m(*marketRuntime)、now(time.Time)。返り値: bool。
func (a *app) quiet(m *marketRuntime, now time.Time) bool {
	if m.Portfolio == nil || m.Saved.Plan.Kind != "Night" {
		return false
	}
	width := duration(m.Portfolio.Config.Parameters.Night.QuietSeconds)
	return !now.Before(m.Saved.Plan.USOpen.Add(-width)) && now.Before(m.Saved.Plan.USOpen.Add(width))
}

// tick は価格到着とは独立した返済時計・取消・保存を進めます。
//
// 引数: ctx(context.Context)、now(time.Time)。返り値: errorは保存・状態矛盾です。
func (a *app) tick(ctx context.Context, now time.Time) error {
	for _, m := range a.markets {
		if m.Portfolio == nil {
			continue
		}
		terminal := a.stopping || !now.Before(m.Saved.Plan.ForceClose)
		quiet := a.quiet(m, now)
		if terminal || quiet {
			kept := m.Saved.Queue[:0]
			for _, item := range m.Saved.Queue {
				if item.Signal.Action == "new" && (terminal || quietOwner(m, item.Signal.Owner)) {
					// 送信済みか不明な依頼をローカル取消してはいけません。
					sent := false
					for _, o := range m.Manager.Orders() {
						if o.IntentID == item.Signal.ID {
							sent = true
							break
						}
					}
					if !sent {
						if err := m.Portfolio.OnOrderRejected(item.Signal.ID); err != nil {
							return err
						}
						m.Dirty = true
						continue
					}
				}
				kept = append(kept, item)
			}
			m.Saved.Queue = kept
		}
		cancel := terminal
		if quiet {
			for _, o := range m.Manager.Orders() {
				if !o.Done && quietOwner(m, o.Owner) && o.TradeType == "new" {
					cancel = true
				}
			}
		}
		if a.accountFresh(now) {
			if err := m.Manager.CancelPending(ctx, a.client, now, cancel); err != nil {
				if err = a.notice("取消照合待ち", err); err != nil {
					return err
				}
			}
		}
		signals := []strategy.Signal{}
		if terminal {
			signals = m.Portfolio.Flatten(seconds(now), "運転停止またはセッション内返済")
		} else if a.staleBeyondGrace(now) {
			signals = m.Portfolio.Flatten(seconds(now), "データ受信中断が猶予時間を超過")
		} else if quiet {
			if m.Portfolio.Research != nil {
				signals = m.Portfolio.Flatten(seconds(now), "米国現物開始の静観")
			} else {
				signals = m.Portfolio.FlattenOwner("core", seconds(now), "米国現物開始の静観")
			}
		}
		if err := a.enqueue(m, signals, 0, now); err != nil {
			return err
		}
		if err := a.dispatch(ctx, m, now); err != nil {
			return err
		}
	}
	if !now.Before(a.nextCheckpoint) {
		for _, m := range a.markets {
			if m.Dirty {
				if err := a.checkpoint(m); err != nil {
					return err
				}
			}
		}
		a.nextCheckpoint = now.Add(duration(a.cfg.Runtime.CheckpointSeconds))
	}
	if !now.Before(a.nextStatus) {
		if err := a.reportStatus(now); err != nil {
			return err
		}
		a.nextStatus = now.Add(duration(a.cfg.Runtime.StatusSeconds))
	}
	return nil
}

// staleBeyondGrace は短い通信断を許容し、長い判断不能だけを返済要求に変えます。
//
// 引数: now(time.Time)。返り値: boolは両参照市場のいずれかで猶予を超えた場合です。
func (a *app) staleBeyondGrace(now time.Time) bool {
	for _, ref := range []string{"TOPIX", "NK225"} {
		last := a.quotes[ref].Received
		if last.IsZero() {
			last = a.started
		}
		if !last.IsZero() && now.Sub(last) > duration(a.cfg.Runtime.ReconnectGraceSeconds) {
			return true
		}
	}
	return false
}

// flat は実玉と結果不明を含む未確定注文の両方がゼロか確認します。
//
// 引数: なし。返り値: bool。
func (a *app) flat() bool {
	for _, m := range a.markets {
		if len(m.Manager.Positions()) > 0 || m.Manager.HasPending() || len(m.Saved.Queue) > 0 {
			return false
		}
	}
	return true
}

// finish は終了理由と最後の状態を必ず記録します。
//
// 引数: reason(string)、cause(error)。返り値: errorは終了理由または保存失敗です。
func (a *app) finish(reason string, cause error) error {
	for _, m := range a.markets {
		if err := a.checkpoint(m); err != nil {
			return err
		}
	}
	message := ""
	if cause != nil {
		message = cause.Error()
	}
	if err := a.store.Event(reason, a.plan.ID, "", "", time.Now(), map[string]string{"message": message}); err != nil {
		return err
	}
	fmt.Println(reason)
	return cause
}
