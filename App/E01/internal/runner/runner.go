// Package runner は受信・判断・注文・復旧状態の境界を管理します。
package runner

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"
	"strings"
	"time"

	"ose-future/e01/internal/config"
	"ose-future/e01/internal/controller"
	"ose-future/e01/internal/execution"
	"ose-future/e01/internal/journal"
	"ose-future/e01/internal/strategy"
)

var jst = time.FixedZone("JST", 9*60*60)

type Options struct {
	Duration time.Duration
	Output   io.Writer
}
type saved struct {
	Signature         string                       `json:"signature"`
	Generation        string                       `json:"generation"`
	Instance          string                       `json:"instance"`
	Registration      map[string]controller.Future `json:"registration"`
	Engine            json.RawMessage              `json:"engine"`
	Features          json.RawMessage              `json:"features"`
	At                time.Time                    `json:"saved_at"`
	TargetQuantity    *int                         `json:"target_quantity"`
	TargetReason      string                       `json:"target_reason"`
	Halted            string                       `json:"halted"`
	CampaignStart     int                          `json:"campaign_start"`
	ReferenceEvidence int64                        `json:"reference_evidence"`
	EvidenceRow       int64                        `json:"evidence_row"`
	Origin            *strategy.Event              `json:"origin"`
	LastPush          map[string]time.Time         `json:"last_push"`
	LastFresh         map[string]time.Time         `json:"last_fresh"`
	LastQuote         map[string]time.Time         `json:"last_quote"`
	ReadyAfter        map[string]time.Time         `json:"ready_after"`
	GapStart          map[string]time.Time         `json:"gap_start"`
	LongGap           bool                         `json:"long_gap"`
}

type runtime struct {
	cfg                                          config.Config
	client                                       *controller.Client
	manager                                      *execution.Manager
	output                                       io.Writer
	health                                       *os.File
	engine                                       *strategy.Engine
	features                                     *strategy.Features
	registration                                 map[string]controller.Future
	generation, instance                         string
	view                                         controller.OrdersView
	viewAt, lastPoll, lastCheckpoint, lastStatus time.Time
	lastPush, lastFresh, lastQuote, readyAfter   map[string]time.Time
	lastTarget                                   controller.Board
	quoteAt                                      time.Time
	gapStart                                     map[string]time.Time
	longGap, recovery                            bool
	started, activated, lastWall                 time.Time
	stopping                                     bool
	finished                                     bool
	halted                                       string
	targetQuantity                               *int
	targetReason                                 string
	campaignStart                                int
	referenceEvidence, evidenceRow               int64
	lastAttempt                                  time.Time
	origin                                       *strategy.Event
	registrationReady                            bool
	counts                                       map[string]int
	rejected                                     int
	messages                                     map[string]time.Time
}

// unix はAPI/受信時刻を小数UNIX秒に変換します。
//
// 引数: at time.Time。返り値: float64。UNIX秒。
func unix(at time.Time) float64 { return float64(at.UnixNano()) / 1e9 }

// atTime は小数UNIX秒を日本時間に変換します。
//
// 引数: value float64。返り値: time.Time。日本時間。
func atTime(value float64) time.Time { return time.Unix(0, int64(value*1e9)).In(jst) }

// Run は1銘柄のE01を停止要求まで実行し、停止時に場内返済を試みます。
//
// 引数: ctx context.Context、cfg config.Config、options Options。
// 返り値: error。未返済・結果不明・運転不能の場合の説明。
func Run(ctx context.Context, cfg config.Config, options Options) error {
	if options.Output == nil {
		options.Output = os.Stdout
	}
	logDir, stateDir := cfg.Path(cfg.Runtime.LogDirectory), cfg.Path(cfg.Runtime.StateDirectory)
	lock, err := lockDirectory(logDir)
	if err != nil {
		return err
	}
	defer lock.Close()
	stateLock, err := lockDirectory(stateDir)
	if err != nil {
		return err
	}
	defer stateLock.Close()
	suffix := ""
	if cfg.Trading.DryRun {
		suffix = "_dryrun"
	}
	manager, err := execution.Open(logDir, filepath.Join(stateDir, "e01"+suffix+".json"), cfg.Trading.DryRun, cfg.Trading.Symbol, cfg.Products[cfg.Trading.Symbol].PointValue, cfg.Trading.MaxPositionPerSide)
	if err != nil {
		return err
	}
	client, err := controller.New(cfg.Controller.BaseURL, seconds(cfg.Controller.RequestTimeoutSeconds))
	if err != nil {
		return err
	}
	health, err := os.OpenFile(filepath.Join(logDir, "runtime"+suffix+".log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	defer health.Close()
	now := time.Now()
	r := &runtime{cfg: cfg, client: client, manager: manager, output: options.Output, health: health, started: now, activated: now, lastWall: now,
		registration: map[string]controller.Future{}, lastPush: map[string]time.Time{}, lastFresh: map[string]time.Time{}, lastQuote: map[string]time.Time{}, readyAfter: map[string]time.Time{}, gapStart: map[string]time.Time{}, counts: map[string]int{}, messages: map[string]time.Time{}, referenceEvidence: -1, evidenceRow: -1, recovery: true}
	if err = r.restore(); err != nil {
		return err
	}
	mode := "実注文"
	if cfg.Trading.DryRun {
		mode = "dryrun"
	}
	r.message("開始", fmt.Sprintf("E01 %s / %s / 初回%d枚・片方向上限%d枚", mode, cfg.Trading.Symbol, cfg.Trading.InitialQuantity, cfg.Trading.MaxPositionPerSide), now)
	// ----------------------------------------
	// 利用者の停止要求後も有限時間だけ価格受信と返済照合を継続します。
	feedCtx, cancelFeed := context.WithCancel(context.Background())
	defer cancelFeed()
	events, closeFeed := startFeed(feedCtx, client, cfg)
	defer closeFeed()
	heartbeat := time.NewTicker(250 * time.Millisecond)
	defer heartbeat.Stop()
	var limit <-chan time.Time
	var durationTimer *time.Timer
	if options.Duration > 0 {
		durationTimer = time.NewTimer(options.Duration)
		defer durationTimer.Stop()
		limit = durationTimer.C
	}
	stopSignal := ctx.Done()
	var stopDeadline time.Time
	for {
		select {
		case <-stopSignal:
			r.stopping = true
			stopSignal = nil
			stopDeadline = time.Now().Add(seconds(cfg.Runtime.ShutdownTimeoutSeconds))
			r.message("停止要求", "新規を停止し、未確定注文の照合と返済を行います", time.Now())
		case <-limit:
			r.stopping = true
			limit = nil
			stopDeadline = time.Now().Add(seconds(cfg.Runtime.ShutdownTimeoutSeconds))
			r.message("試運転終了", "新規を停止し、未確定注文の照合と返済を行います", time.Now())
		case event := <-events:
			if err = r.accept(event); err != nil {
				r.halted = err.Error()
				r.finished = true
				r.message("停止", r.halted, time.Now())
				_ = r.writeStatus(time.Now())
				return err
			}
		case <-heartbeat.C:
			if err = r.watch(time.Now()); err != nil {
				r.halted = err.Error()
				r.finished = true
				r.message("停止", r.halted, time.Now())
				_ = r.writeStatus(time.Now())
				return err
			}
		}
		if r.stopping {
			if r.engine != nil {
				r.engine.CancelEntry()
			}
			if len(manager.Positions()) == 0 && !manager.HasPending() {
				if err = r.checkpoint(); err != nil {
					return err
				}
				r.message("終了", "建玉・未確定注文なし。記録を保存しました", time.Now())
				r.finished = true
				if err = r.writeStatus(time.Now()); err != nil {
					return err
				}
				return nil
			}
			if !stopDeadline.IsZero() && time.Now().After(stopDeadline) {
				_ = r.checkpoint()
				return errors.New("停止猶予内に返済・照合を完了できませんでした。建玉と未確定注文を保存しました")
			}
		}
	}
}

// restore は正本に保存された判断状態を復元し、未反映の約定を同期します。
//
// 引数: なし。返り値: error。不整合や復元失敗。
func (r *runtime) restore() error {
	b := r.manager.State()
	if len(b) == 0 {
		return nil
	}
	var s saved
	if err := json.Unmarshal(b, &s); err != nil {
		return err
	}
	if s.Signature != r.cfg.Fingerprint() {
		return errors.New("保存状態と設定が異なります。既存記録を残して別のlog/state保存先を指定してください")
	}
	var err error
	if len(s.Engine) > 0 && string(s.Engine) != "null" {
		r.engine, err = strategy.RestoreEngine(s.Engine)
		if err != nil {
			return err
		}
		r.engine.CancelEntry()
	}
	if len(s.Features) > 0 && string(s.Features) != "null" {
		r.features, err = strategy.RestoreFeatures(s.Features)
		if err != nil {
			return err
		}
	}
	r.generation = s.Generation
	r.instance = s.Instance
	r.registration = s.Registration
	r.targetQuantity = s.TargetQuantity
	r.targetReason = s.TargetReason
	r.halted = s.Halted
	r.campaignStart = s.CampaignStart
	r.referenceEvidence = s.ReferenceEvidence
	r.evidenceRow = s.EvidenceRow
	r.origin = s.Origin
	if r.halted != "" {
		return fmt.Errorf("前回の停止理由が残っています: %s", r.halted)
	}
	r.longGap = s.LongGap || time.Since(s.At) > seconds(r.cfg.Runtime.ReconnectGraceSeconds)
	if s.LastPush != nil {
		r.lastPush = s.LastPush
	}
	if s.LastFresh != nil {
		r.lastFresh = s.LastFresh
	}
	if s.LastQuote != nil {
		r.lastQuote = s.LastQuote
	}
	if s.ReadyAfter != nil {
		r.readyAfter = s.ReadyAfter
	}
	if s.GapStart != nil {
		r.gapStart = s.GapStart
	}
	for _, t := range r.lastPush {
		if !t.IsZero() && time.Since(t) > seconds(r.cfg.Runtime.ReconnectGraceSeconds) {
			r.longGap = true
		}
	}
	if r.longGap && r.features != nil {
		if err = r.features.ResetShortHistory(""); err != nil {
			return err
		}
	}
	if r.features != nil {
		if err = r.features.ResetShortHistory(""); err != nil {
			return err
		}
	}
	for _, code := range r.codes() {
		if r.longGap || r.readyAfter[code].IsZero() {
			r.readyAfter[code] = time.Now().Add(seconds(r.cfg.Runtime.WarmupSeconds))
		}
	}
	if err = r.synchronize(); err != nil {
		return err
	}
	r.message("再開", "保存済みの建玉・条件を復元し、新鮮な受信を待ちます", time.Now())
	return nil
}

// checkpoint は約定反映と戦略を同一の正本へ保存します。
//
// 引数: なし。返り値: error。保存失敗。
func (r *runtime) checkpoint() error {
	s := saved{Signature: r.cfg.Fingerprint(), Generation: r.generation, Instance: r.instance, Registration: r.registration, At: time.Now(), TargetQuantity: r.targetQuantity, TargetReason: r.targetReason, Halted: r.halted, CampaignStart: r.campaignStart, ReferenceEvidence: r.referenceEvidence, EvidenceRow: r.evidenceRow, Origin: r.origin, LastPush: r.lastPush, LastFresh: r.lastFresh, LastQuote: r.lastQuote, ReadyAfter: r.readyAfter, GapStart: r.gapStart, LongGap: r.longGap}
	var err error
	if r.engine != nil {
		s.Engine, err = r.engine.Snapshot()
		if err != nil {
			return err
		}
	}
	if r.features != nil {
		s.Features, err = r.features.DumpState()
		if err != nil {
			return err
		}
	}
	b, err := json.Marshal(s)
	if err != nil {
		return err
	}
	if err = r.manager.Checkpoint(b); err != nil {
		return err
	}
	r.lastCheckpoint = s.At
	return nil
}

// message は状態変化を日本語で保存し、同じ警告の連続表示を抑制します。
//
// 引数: kind/message string、now time.Time。返り値: なし。
func (r *runtime) message(kind, message string, now time.Time) {
	key := kind + message
	if last := r.messages[key]; !last.IsZero() && now.Sub(last) < time.Minute {
		return
	}
	r.messages[key] = now
	line := fmt.Sprintf("%s [%s] %s\n", now.In(jst).Format(time.RFC3339Nano), kind, message)
	fmt.Fprint(r.output, line)
	if r.health != nil {
		fmt.Fprint(r.health, line)
	}
}

// codes は二つの参照市場と選択商品を重複なく返します。
//
// 引数: なし。返り値: []string。監視対象。
func (r *runtime) codes() []string {
	v := []string{"NK225", "TOPIX"}
	if r.cfg.Trading.Symbol != "NK225" && r.cfg.Trading.Symbol != "TOPIX" {
		v = append(v, r.cfg.Trading.Symbol)
	}
	return v
}

// engineConfig はTOMLからE01の数量・価格幅・保有時間を設定します。
//
// 引数: なし。返り値: strategy.Config。実効戦略設定。
func (r *runtime) engineConfig() strategy.Config {
	c := r.cfg
	p := c.Products[c.Trading.Symbol]
	e := strategy.DefaultConfig(c.Trading.Symbol, c.Trading.InitialQuantity, c.Trading.MaxPositionPerSide, p.Tick, p.PointValue)
	e.FillMode = c.Trading.FillMode
	e.EntryATR = c.E01.EntryATR
	e.TightRiskATR = c.E01.StopATR
	e.SplitATR = c.E01.PartialATR
	e.TrailArmATR = c.E01.TrailStartATR
	e.NormalTrailATR = c.E01.TrailWideATR
	e.TightArmATR = c.E01.TrailTightStartATR
	e.TightTrailATR = c.E01.TrailTightATR
	e.MaxHoldSeconds = c.E01.MaxHoldMinutes * 60
	e.CooldownSeconds = c.E01.CooldownMinutes * 60
	e.WarmupSeconds = c.E01.SessionWarmupSeconds
	e.EntryCutoffSeconds = c.E01.EntryCutoffSeconds
	e.PendingSeconds = c.E01.EntryPendingSeconds
	e.NormalRiskATR = c.E01.ShadowRiskATR
	e.ActualRiskATR = c.E01.ActualRiskATR
	return e
}

// accept は単一実行ループで受信イベントを適用します。
//
// 引数: event feedEvent。返り値: error。致命的な不整合だけ返します。
func (r *runtime) accept(event feedEvent) error {
	if event.Err != nil {
		r.message("再取得待ち", event.Kind+": "+event.Err.Error(), event.At)
		if event.Kind == "disconnect" {
			r.markGap("接続中断", event.At, true)
		}
		return nil
	}
	switch event.Kind {
	case "candles":
		return r.acceptCandles(event.Value.(candleSet), event.At)
	case "orders":
		v := event.Value.(controller.OrdersView)
		if r.instance != "" && v.InstanceID != r.instance {
			r.markGap("controllerの起動世代が変わりました", event.At, true)
			r.longGap = true
		}
		r.instance = v.InstanceID
		r.view = v
		r.viewAt = event.At
		var fills []execution.Fill
		var err error
		if r.cfg.Trading.DryRun || r.accountFresh(event.At) {
			fills, err = r.manager.Reconcile(v)
		}
		if err != nil {
			return err
		}
		if len(fills) > 0 || r.origin != nil {
			for _, f := range fills {
				r.message("約定", fmt.Sprintf("%s %s %d枚 @%g / %s / 損益%+.0f円", f.TradeType, f.Side, f.Quantity, f.Price, f.Reason, f.PnL), f.At)
			}
			if err = r.synchronize(); err != nil {
				return err
			}
			if err = r.checkpoint(); err != nil {
				return err
			}
		}
		if !r.cfg.Trading.DryRun {
			if err = r.manager.CancelPending(context.Background(), r.client, event.At, r.stopping); err != nil {
				if storageFailure(err) {
					return err
				}
				r.message("取消照合待ち", err.Error(), event.At)
			}
		}
		if pending := r.manager.PendingError(); pending != "" {
			r.message("注文照合待ち", pending, event.At)
		}
	case "book":
		return r.acceptBook(event.Value.(controller.Board), event.At)
	}
	return nil
}

// acceptCandles はAPIのセッション・銘柄を採用し確定足を取り込みます。
//
// 引数: set candleSet、at time.Time。返り値: error。未返済での場替わり等。
func (r *runtime) acceptCandles(set candleSet, at time.Time) error {
	r.registrationReady = false
	if err := validateBatch(set); err != nil {
		r.message("足待ち", err.Error(), at)
		return nil
	}
	if set.Registration.State != "succeeded" {
		r.message("登録待ち", "controllerの銘柄登録完了を待っています", at)
		return nil
	}
	reg := map[string]controller.Future{}
	for _, v := range set.Registration.Futures {
		if v.Symbol != "" {
			reg[v.FutureCode] = v
		}
	}
	for _, code := range r.codes() {
		if reg[code].Symbol == "" {
			r.message("登録待ち", code+"の登録銘柄を待っています", at)
			return nil
		}
	}
	p := r.cfg.Products[r.cfg.Trading.Symbol]
	if reg[r.cfg.Trading.Symbol].DerivMonth != reg[p.Reference].DerivMonth {
		return errors.New("取引商品と参照先物の限月が異なります")
	}
	snap := set.Candles["NK225/1min"].Snapshot
	if r.engine == nil || r.engine.Session.ID != snap.SessionID {
		if r.manager.HasPending() || len(r.manager.Positions()) > 0 {
			return errors.New("前セッションの建玉または未確定注文が残っています。翌セッションでは新規を行いません")
		}
		se := strategy.Session{ID: snap.SessionID, Start: unix(snap.Session.StartsAt), ForceClose: unix(snap.Session.EndsAt) - r.cfg.Runtime.ForceCloseBeforeSeconds, Close: unix(snap.Session.EndsAt)}
		var err error
		r.engine, err = strategy.NewEngine(r.engineConfig(), se)
		if err != nil {
			return err
		}
		r.features, err = strategy.NewFeatures(se.ID, se.Start, map[string]float64{"NK225": r.cfg.Products["NK225"].Tick, "TOPIX": r.cfg.Products["TOPIX"].Tick}, r.cfg.Features)
		if err != nil {
			return err
		}
		r.activated = at
		r.lastPush = map[string]time.Time{}
		r.lastFresh = map[string]time.Time{}
		r.lastQuote = map[string]time.Time{}
		r.readyAfter = map[string]time.Time{}
		r.gapStart = map[string]time.Time{}
		r.referenceEvidence = -1
		r.evidenceRow = -1
		r.origin = nil
		r.targetQuantity = nil
		r.campaignStart = len(r.manager.Records())
		r.recovery = true
		r.longGap = false
		if err = r.manager.EnsureSession(se.ID); err != nil {
			return err
		}
		r.message("セッション開始", fmt.Sprintf("%s / %s / 返済開始 %s", se.ID, r.cfg.Trading.Symbol, atTime(se.ForceClose).Format("15:04:05")), at)
	} else {
		if r.engine.Session.Start != unix(snap.Session.StartsAt) || r.engine.Session.Close != unix(snap.Session.EndsAt) {
			return errors.New("同一セッションの開始・終了時刻が変わりました")
		}
		changed := r.generation != "" && r.generation != snap.Generation
		for _, code := range r.codes() {
			if old := r.registration[code]; old.Symbol != "" && old.Symbol != reg[code].Symbol {
				if len(r.manager.Positions()) > 0 || r.manager.HasPending() {
					return errors.New("保有中に登録銘柄が変わりました。別限月へ自動で振り替えません")
				}
				changed = true
			}
		}
		if changed {
			var err error
			r.features, err = strategy.NewFeatures(snap.SessionID, r.engine.Session.Start, map[string]float64{"NK225": r.cfg.Products["NK225"].Tick, "TOPIX": r.cfg.Products["TOPIX"].Tick}, r.cfg.Features)
			if err != nil {
				return err
			}
			r.longGap = true
			r.activated = at
			r.lastPush = map[string]time.Time{}
			r.lastFresh = map[string]time.Time{}
			r.lastQuote = map[string]time.Time{}
			r.readyAfter = map[string]time.Time{}
			r.markGap("履歴世代または登録変更", at, true)
			r.referenceEvidence = -1
			r.evidenceRow = -1
		}
	}
	r.registration = reg
	r.generation = snap.Generation
	for key, data := range set.Candles {
		parts := strings.Split(key, "/")
		interval := 60
		if parts[1] == "5min" {
			interval = 300
		}
		rows := make([]strategy.Candle, 0, len(data.Data))
		for _, v := range data.Data {
			rows = append(rows, strategy.Candle{Time: unix(v.Time), Open: v.Open, High: v.High, Low: v.Low, Close: v.Close, Closed: v.Closed})
		}
		if _, err := r.features.AddCandles(parts[0], interval, rows, unix(at)); err != nil {
			r.message("足待ち", err.Error(), at)
			return nil
		}
	}
	r.lastPoll = at
	r.registrationReady = true
	return r.checkpoint()
}

// markGap は建玉を保持し新規だけを止め、欠測前後を短期根拠で接続しません。
//
// 引数: reason string、at time.Time、all bool。返り値: なし。
func (r *runtime) markGap(reason string, at time.Time, all bool) {
	if r.engine != nil {
		r.engine.CancelEntry()
	}
	r.recovery = true
	newGap := false
	for _, code := range r.codes() {
		if r.gapStart[code].IsZero() {
			newGap = true
			base := r.lastPush[code]
			if base.IsZero() {
				base = at
			}
			r.gapStart[code] = base
		}
	}
	if newGap && r.features != nil {
		_ = r.features.ResetShortHistory("")
		r.referenceEvidence = -1
		r.evidenceRow = -1
	}
	r.message("新規一時停止", reason, at)
}

// validQuote はnull・古い価格・時刻逆行・セッション外の価格を除外します。
//
// 引数: board controller.Board、at time.Time、code string。
// 返り値: time.Time と bool。価格時刻と採用可否。
func (r *runtime) validQuote(board controller.Board, at time.Time, code string) (time.Time, bool) {
	q, err := time.Parse(time.RFC3339Nano, board.CurrentPriceTime)
	if err != nil || board.CurrentPrice <= 0 || math.IsNaN(board.CurrentPrice) || math.IsInf(board.CurrentPrice, 0) {
		return q, false
	}
	if at.Sub(q) > seconds(r.cfg.Runtime.MaxPriceAgeSeconds) || q.After(at.Add(5*time.Second)) || q.Before(r.lastQuote[code]) || unix(q) < r.engine.Session.Start || unix(q) >= r.engine.Session.Close || unix(at) < r.engine.Session.Start || unix(at) >= r.engine.Session.Close {
		return q, false
	}
	return q, true
}

// acceptBook は参照市場の特徴を更新し、選択商品のPUSHで注文条件を判定します。
//
// 引数: board controller.Board、at time.Time。返り値: error。状態・永続化の異常。
func (r *runtime) acceptBook(board controller.Board, at time.Time) error {
	if r.engine == nil || r.features == nil || at.Before(r.activated) {
		return nil
	}
	code := ""
	for _, s := range r.codes() {
		if r.registration[s].Symbol == board.Symbol {
			code = s
			break
		}
	}
	if code == "" {
		return nil
	}
	if time.Since(at) > 5*time.Second {
		r.markGap("受信処理が5秒以上遅れています", time.Now(), true)
		return nil
	}
	old := r.lastPush[code]
	r.lastPush[code] = at
	if !old.IsZero() && at.Sub(old) > seconds(r.cfg.Runtime.StaleSeconds) {
		r.markGap("板の受信が中断しました", at, true)
		r.gapStart[code] = old
	}
	if gap := r.gapStart[code]; !gap.IsZero() {
		if at.Sub(gap) > seconds(r.cfg.Runtime.ReconnectGraceSeconds) {
			r.longGap = true
		}
		delete(r.gapStart, code)
	}
	q, ok := r.validQuote(board, at, code)
	if !ok {
		r.rejected++
		if code == r.cfg.Trading.Symbol {
			r.engine.CancelEntry()
			r.recovery = true
		}
		return nil
	}
	r.lastFresh[code] = at
	r.lastQuote[code] = q
	r.counts[code]++
	if r.readyAfter[code].IsZero() {
		r.readyAfter[code] = at.Add(seconds(r.cfg.Runtime.WarmupSeconds))
		r.message("価格受信", code+" / 短期判断を準備します", at)
	}
	if code == "NK225" || code == "TOPIX" {
		obs, err := r.features.OnBook(code, strategy.Book{QuoteTime: unix(q), Price: board.CurrentPrice, Bid: board.Buy1.Price, Ask: board.Sell1.Price, BidQty: board.Buy1.Qty, AskQty: board.Sell1.Qty}, unix(at))
		if err != nil {
			r.message("板除外", err.Error(), at)
			return nil
		}
		if code == r.cfg.Products[r.cfg.Trading.Symbol].Reference && obs.AdverseSource != r.referenceEvidence {
			r.referenceEvidence = obs.AdverseSource
			r.evidenceRow = r.engine.Row + 1
		}
	}
	if code != r.cfg.Trading.Symbol {
		return nil
	}
	r.lastTarget = board
	r.quoteAt = q
	if r.manager.HasPending() {
		r.engine.CancelEntry()
		return nil
	}
	if r.targetQuantity != nil {
		return r.retryClose(at, board.CurrentPrice)
	}
	if r.origin != nil {
		if err := r.synchronize(); err != nil {
			return err
		}
	}
	if r.stopping || r.longGap || unix(at) >= r.engine.Session.ForceClose {
		reason := "セッション内返済"
		if r.stopping {
			reason = "停止時返済"
		} else if r.longGap {
			reason = "長時間の中断後に返済"
		}
		events, err := r.engine.ForceFlatten(unix(at), board.CurrentPrice, reason)
		if err != nil {
			return err
		}
		if r.longGap {
			if err = r.features.ResetShortHistory(""); err != nil {
				return err
			}
			for _, s := range r.codes() {
				r.readyAfter[s] = at.Add(seconds(r.cfg.Runtime.WarmupSeconds))
			}
			r.longGap = false
		}
		return r.execute(events, at)
	}
	obs, err := r.features.Current(r.cfg.Products[r.cfg.Trading.Symbol].Reference, unix(at))
	if err != nil {
		return err
	}
	allow := !r.recovery && !r.stopping && r.registrationReady
	for _, s := range r.codes() {
		if r.lastFresh[s].IsZero() || at.Sub(r.lastFresh[s]) > seconds(r.cfg.Runtime.StaleSeconds) || r.lastQuote[s].IsZero() || at.Sub(r.lastQuote[s]) > seconds(r.cfg.Runtime.MaxPriceAgeSeconds) || !r.gapStart[s].IsZero() || r.readyAfter[s].IsZero() || at.Before(r.readyAfter[s]) {
			allow = false
		}
	}
	if r.lastPoll.IsZero() || at.Sub(r.lastPoll) > seconds(math.Max(30, 3*r.cfg.Controller.CandlePollSeconds)) {
		allow = false
	}
	for _, v := range []struct{ nominal, maxAge float64 }{{obs.MainNominal, 180}, {obs.PeerNominal, 180}, {obs.ATRNominal, 420}} {
		if v.nominal <= 0 || unix(at)-v.nominal > v.maxAge || unix(at) < v.nominal {
			allow = false
		}
	}
	if !r.cfg.Trading.DryRun && !r.orderReady(at) {
		allow = false
	}
	if !allow {
		r.engine.CancelEntry()
	}
	tick := strategy.Tick{Time: unix(at), Price: board.CurrentPrice, ATR: obs.ATR, Direction: obs.Direction, Adverse: obs.Adverse, AdverseSource: r.evidenceRow, AllowEntry: allow, InputIndex: r.engine.Row + 1, ObservedRecovery: r.recovery}
	events, err := r.engine.OnTick(tick)
	if err != nil {
		return err
	}
	r.recovery = false
	return r.execute(events, at)
}

// orderReady は注文に使うcontroller照会が現在セッションで新鮮か確認します。
//
// 引数: at time.Time。返り値: bool。注文照会が利用可能な場合true。
func (r *runtime) orderReady(at time.Time) bool {
	v := r.view
	if !r.accountFresh(at) {
		return false
	}
	return !r.viewAt.IsZero() && at.Sub(r.viewAt) <= seconds(math.Max(10, 3*r.cfg.Controller.OrderPollSeconds)) && v.Connected && !v.BrokerStale && !v.PositionsStale && v.Session != nil && unix(v.Session.StartsAt) == r.engine.Session.Start && unix(v.Session.EndsAt) == r.engine.Session.Close && v.SessionError == "" && at.Before(v.Session.SendUntil)
}

// accountFresh はHTTP応答時刻とは別に口座データ自体の更新時刻を検査します。
//
// 引数: at time.Time。返り値: bool。注文・建玉の両方が鮮度内の場合true。
func (r *runtime) accountFresh(at time.Time) bool {
	v := r.view
	if v.BrokerStale || v.PositionsStale || v.BrokerError != "" || v.PositionsError != "" {
		return false
	}
	for _, updated := range []*time.Time{v.BrokerUpdatedAt, v.PositionsUpdatedAt} {
		if updated == nil || at.Sub(*updated) > seconds(r.cfg.Runtime.AccountMaxAgeSeconds) || updated.After(at.Add(5*time.Second)) {
			return false
		}
	}
	return true
}

// execute は判断を先に永続化し、実約定と戦略状態を同期します。
//
// 引数: events []strategy.Event、at time.Time。返り値: error。保存や数量不整合。
func (r *runtime) execute(events []strategy.Event, at time.Time) error {
	if len(events) == 0 {
		return nil
	}
	if len(events) > 1 {
		return errors.New("同一観測の複数発注意図を安全に処理できません")
	}
	e := events[0]
	r.origin = &e
	if e.Event == "返済" {
		target := e.PositionAfter
		r.targetQuantity = &target
		r.targetReason = e.Reason
	}
	if e.Event == "新規" {
		r.campaignStart = len(r.manager.Records())
	}
	if err := r.checkpoint(); err != nil {
		return err
	}
	return r.submit(e.Quantity, e.Side(), e.Event, e.Price, e.Reason, at)
}

// submit は1件の成行発注意図を作り、受付・実約定・不明を区別します。
//
// 引数: quantity/side int、kind string、price float64、reason string、at time.Time。
// 返り値: error。整合性・保存エラー。通信失敗は正本に残し再送しません。
func (r *runtime) submit(quantity, side int, kind string, price float64, reason string, at time.Time) error {
	tradeType := "new"
	expires := at.Add(seconds(r.cfg.Runtime.EntryOrderTimeoutSeconds))
	if kind == "返済" {
		tradeType = "close"
		expires = atTime(r.engine.Session.Close)
	}
	direction := "buy"
	if side < 0 {
		direction = "sell"
	}
	r.lastAttempt = at
	intent := execution.Intent{Session: r.engine.Session.ID, ContractSymbol: r.registration[r.cfg.Trading.Symbol].Symbol, Side: direction, TradeType: tradeType, Reason: reason, Quantity: quantity, Price: price, At: at, ExpiresAt: expires}
	if !r.cfg.Trading.DryRun && !r.orderReady(at) {
		r.message("注文待ち", "新鮮な注文・建玉・セッション照会を待っています", at)
		if err := r.synchronize(); err != nil {
			return err
		}
		return r.checkpoint()
	}
	fills, err := r.manager.Submit(context.Background(), r.client, intent, r.view)
	if err != nil {
		if storageFailure(err) {
			return err
		}
		r.message("注文確認", err.Error(), at)
	}
	for _, f := range fills {
		r.message("約定", fmt.Sprintf("%s %s %d枚 @%g / %s / 損益%+.0f円", f.TradeType, f.Side, f.Quantity, f.Price, f.Reason, f.PnL), f.At)
	}
	if syncErr := r.synchronize(); syncErr != nil {
		return syncErr
	}
	if saveErr := r.checkpoint(); saveErr != nil {
		return saveErr
	}
	// APIの確定拒否と不明は台帳に残します。不明の場合はHasPendingで後続を遮断します。
	return nil
}

// storageFailure は注文継続できない正本・CSVの入出力障害を識別します。
//
// 引数: err error。返り値: bool。永続化障害ならtrue。
func storageFailure(err error) bool {
	var p *os.PathError
	var projection *journal.ProjectionError
	return errors.As(err, &p) || errors.As(err, &projection)
}

// synchronize は実約定台帳だけを使って戦略の実建玉を補正します。
//
// 引数: なし。返り値: error。方向・枚数・元枠の不一致。
func (r *runtime) synchronize() error {
	if r.engine == nil {
		return nil
	}
	qty, direction, value := 0, 0, 0.0
	for _, h := range r.manager.Positions() {
		d := 1
		if h.Side == "sell" {
			d = -1
		}
		if direction != 0 && direction != d {
			return errors.New("E01の所有建玉が両方向に存在します")
		}
		if h.Session != r.engine.Session.ID {
			return errors.New("所有建玉のセッションが戦略と一致しません")
		}
		direction = d
		qty += h.Quantity
		value += h.Price * float64(h.Quantity)
	}
	realized := 0.0
	for _, t := range r.manager.Records() {
		if t.Session == r.engine.Session.ID {
			realized += t.PnL
		}
	}
	avg := 0.0
	if qty > 0 {
		avg = value / float64(qty)
	}
	if r.origin != nil {
		if err := r.engine.SyncActual(qty, direction, avg, realized, *r.origin); err != nil {
			return err
		}
		if !r.manager.HasPending() {
			if r.targetQuantity == nil || qty <= *r.targetQuantity {
				r.targetQuantity = nil
				r.targetReason = ""
				r.origin = nil
			}
		}
	} else if qty != r.engine.Status().Quantity {
		return errors.New("保存済み戦略と約定台帳の建玉枚数が一致しません")
	}
	return nil
}

// retryClose は確定した返済注文の未約定残だけを新しい発注意図として返済します。
//
// 引数: at time.Time、price float64。返り値: error。状態異常。
func (r *runtime) retryClose(at time.Time, price float64) error {
	if r.targetQuantity == nil || r.manager.HasPending() {
		return nil
	}
	if at.Sub(r.lastAttempt) < seconds(r.cfg.Controller.OrderPollSeconds) {
		return nil
	}
	qty, side := 0, 0
	for _, h := range r.manager.Positions() {
		qty += h.Quantity
		side = -1
		if h.Side == "sell" {
			side = 1
		}
	}
	remaining := qty - *r.targetQuantity
	if remaining <= 0 {
		return r.synchronize()
	}
	return r.submit(remaining, side, "返済", price, r.targetReason+"（未約定残）", at)
}

// watch は場内返済・受信鮮度・状態保存を監視します。
//
// 引数: at time.Time。返り値: error。未返済での終場や時計逆行等。
func (r *runtime) watch(at time.Time) error {
	if at.Before(r.lastWall.Add(-time.Second)) {
		r.longGap = true
		r.markGap("コンピューター時計が逆行しました", at, true)
	}
	r.lastWall = at
	if r.engine != nil {
		active := unix(at) >= r.engine.Session.Start && unix(at) < r.engine.Session.Close
		if active {
			for _, code := range r.codes() {
				last := r.lastPush[code]
				if !last.IsZero() && at.Sub(last) > seconds(r.cfg.Runtime.StaleSeconds) {
					r.markGap(code+"の板受信待ち", at, true)
					if at.Sub(last) > seconds(r.cfg.Runtime.ReconnectGraceSeconds) {
						r.longGap = true
					}
				}
			}
		}
		if active && (r.stopping || unix(at) >= r.engine.Session.ForceClose) && !r.manager.HasPending() {
			if err := r.closeOnClock(at); err != nil {
				return err
			}
		}
		if unix(at) >= r.engine.Session.Close && (len(r.manager.Positions()) > 0 || r.manager.HasPending()) {
			return errors.New("セッション内返済を確認できませんでした。未返済建玉・未確定注文を保存して停止します")
		}
	}
	if at.Sub(r.lastCheckpoint) >= seconds(r.cfg.Runtime.CheckpointSeconds) {
		if err := r.checkpoint(); err != nil {
			return err
		}
	}
	if at.Sub(r.lastStatus) >= seconds(r.cfg.Runtime.StatusSeconds) {
		if err := r.writeStatus(at); err != nil {
			return err
		}
		r.lastStatus = at
	}
	return nil
}

// closeOnClock は停止・終場前の返済を、新しい約定価格PUSHだけに依存させません。
//
// 引数: at time.Time。返り値: error。発注意図や保存の異常。
// dryrunは鮮度内の観測価格だけを使用し、実注文は成行の実約定で損益を確定します。
func (r *runtime) closeOnClock(at time.Time) error {
	if r.engine == nil || r.manager.HasPending() || len(r.manager.Positions()) == 0 {
		return nil
	}
	price := r.lastTarget.CurrentPrice
	if price <= 0 {
		price = r.engine.LastPrice
	}
	if price <= 0 {
		return nil
	}
	if r.cfg.Trading.DryRun {
		last := r.lastQuote[r.cfg.Trading.Symbol]
		if last.IsZero() || at.Sub(last) > seconds(r.cfg.Runtime.MaxPriceAgeSeconds) {
			return nil
		}
	} else if !r.orderReady(at) {
		return nil
	}
	if r.targetQuantity != nil {
		return r.retryClose(at, price)
	}
	reason := "セッション内返済"
	if r.stopping {
		reason = "停止時返済"
	}
	events, err := r.engine.ForceFlatten(unix(at), price, reason)
	if err != nil {
		return err
	}
	return r.execute(events, at)
}

// writeStatus は受信件数・保有・停止理由を確認できるJSONを書き出します。
//
// 引数: at time.Time。返り値: error。出力失敗。
func (r *runtime) writeStatus(at time.Time) error {
	var state any
	var indicators any
	if r.engine != nil {
		state = r.engine.Status()
		if r.features != nil {
			indicators, _ = r.features.Current(r.cfg.Products[r.cfg.Trading.Symbol].Reference, unix(at))
		}
	}
	value := map[string]any{"更新時刻": at.In(jst), "銘柄": r.cfg.Trading.Symbol, "仮想運転": r.cfg.Trading.DryRun, "有効受信件数": r.counts, "無効価格除外数": r.rejected, "戦略": state, "指標": indicators, "所有建玉": r.manager.Positions(), "未確定注文": r.manager.HasPending(), "注文確認": r.manager.PendingError(), "停止理由": r.halted, "停止処理中": r.stopping && !r.finished, "稼働中": !r.finished, "最終板受信": r.lastPush, "最終採用価格時刻": r.lastQuote, "短期準備完了予定": r.readyAfter, "登録完了": r.registrationReady}
	b, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	suffix := ""
	if r.cfg.Trading.DryRun {
		suffix = "_dryrun"
	}
	path := filepath.Join(r.cfg.Path(r.cfg.Runtime.StateDirectory), "status"+suffix+".json")
	return os.WriteFile(path, append(b, '\n'), 0600)
}
