package runner

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"ose-future/e01/internal/config"
	"ose-future/e01/internal/controller"
	"ose-future/e01/internal/execution"
	"ose-future/e01/internal/strategy"
)

type integrationBroker struct {
	mu       sync.Mutex
	requests []controller.BrokerRequest
}

// ServeHTTP はローカル試験用の受付番号だけを発行し、実際の証券 API へ送信しません。
//
// 引数: w(http.ResponseWriter)、r(*http.Request) は試験 HTTP。返り値: なし。
func (b *integrationBroker) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" || r.URL.Path != "/kabusapi/sendorder/future" {
		http.Error(w, "試験対象外の要求です", http.StatusNotFound)
		return
	}
	var request controller.BrokerRequest
	if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
		http.Error(w, err.Error(), 400)
		return
	}
	b.mu.Lock()
	b.requests = append(b.requests, request)
	n := len(b.requests)
	b.mu.Unlock()
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(controller.OrderResponse{Result: 0, OrderID: fmt.Sprintf("order%d", n)})
}

// Requests は同期された試験要求のコピーを返します。
//
// 引数: なし。返り値: []controller.BrokerRequest は記録済み要求です。
func (b *integrationBroker) Requests() []controller.BrokerRequest {
	b.mu.Lock()
	defer b.mu.Unlock()
	return append([]controller.BrokerRequest(nil), b.requests...)
}

// integrationRuntime は分離された一時台帳と E01 を持つ運転状態を作ります。
//
// 引数: t(*testing.T)、dry(bool)、url(string) は仮想指定と試験サーバー。
// 返り値: *runtime は状態、string は正本パスです。
func integrationRuntime(t *testing.T, dry bool, url string) (*runtime, string) {
	t.Helper()
	dir := t.TempDir()
	cfg := config.Defaults()
	cfg.Root = dir
	cfg.Trading = config.Trading{Symbol: "TOPIXmini", MaxPositionPerSide: 10, InitialQuantity: 5, DryRun: dry, FillMode: "observed"}
	cfg.Products = map[string]config.Product{"TOPIXmini": {Reference: "TOPIX", Tick: .25, PointValue: 1000}, "TOPIX": {Reference: "TOPIX", Tick: .5, PointValue: 10000}, "NK225": {Reference: "NK225", Tick: 10, PointValue: 1000}}
	path := filepath.Join(dir, "state.json")
	manager, err := execution.Open(filepath.Join(dir, "log"), path, dry, "TOPIXmini", 1000, 10)
	if err != nil {
		t.Fatal(err)
	}
	r := &runtime{cfg: cfg, manager: manager, output: io.Discard, registration: map[string]controller.Future{"TOPIXmini": {Symbol: "167120019", FutureCode: "TOPIXmini"}}, messages: map[string]time.Time{}, readyAfter: map[string]time.Time{}, lastPush: map[string]time.Time{}, lastFresh: map[string]time.Time{}, lastQuote: map[string]time.Time{}, gapStart: map[string]time.Time{}, counts: map[string]int{}, referenceEvidence: -1, evidenceRow: -1}
	start := time.Date(2026, 10, 2, 9, 0, 0, 0, jst)
	session := strategy.Session{ID: "2026-10-02_Day", Start: unix(start), ForceClose: unix(start.Add(30000 * time.Second)), Close: unix(start.Add(30600 * time.Second))}
	r.engine, err = strategy.NewEngine(r.engineConfig(), session)
	if err != nil {
		t.Fatal(err)
	}
	r.view = controller.OrdersView{InstanceID: "試験世代", Connected: true, Session: &controller.Session{Name: "Day", Exchange: 33, StartsAt: start, SendFrom: start, SendUntil: atTime(session.Close), EndsAt: atTime(session.Close)}}
	if url != "" {
		r.client, err = controller.New(url, time.Second)
		if err != nil {
			t.Fatal(err)
		}
	}
	return r, path
}

// integrationTick は人工価格を E01 へ投入して運転層の発注・同期まで実行します。
//
// 引数: t(*testing.T)、r(*runtime)、second(int)、price(float64)、adverse(int)。
// 返り値: []strategy.Event は判断された意図です。
func integrationTick(t *testing.T, r *runtime, second int, price float64, adverse int) []strategy.Event {
	t.Helper()
	at := atTime(r.engine.Session.Start + float64(second))
	integrationAccountAt(r, at)
	events, err := r.engine.OnTick(strategy.Tick{Time: unix(at), Price: price, ATR: 10, Direction: 1, Adverse: adverse, AdverseSource: r.engine.Row + 1, AllowEntry: true, InputIndex: r.engine.Row + 1})
	if err != nil {
		t.Fatal(err)
	}
	if err = r.execute(events, at); err != nil {
		t.Fatal(err)
	}
	return events
}

// integrationAccountAt は口座データ自体の更新時計と HTTP 受信時計を揃えます。
//
// 引数: r(*runtime) は試験運転、at(time.Time) は口座更新の時刻。返り値: なし。
func integrationAccountAt(r *runtime, at time.Time) {
	brokerAt, positionsAt := at, at
	r.viewAt = at
	r.view.BrokerUpdatedAt = &brokerAt
	r.view.PositionsUpdatedAt = &positionsAt
}

// integrationRestore は正本を再読込し、運転層による未反映約定同期を実行します。
//
// 引数: t(*testing.T)、prior(*runtime)、path(string) は復元元。
// 返り値: *runtime は復元状態です。
func integrationRestore(t *testing.T, prior *runtime, path string) *runtime {
	t.Helper()
	m, err := execution.Open(filepath.Join(filepath.Dir(path), "log"), path, prior.cfg.Trading.DryRun, "TOPIXmini", 1000, 10)
	if err != nil {
		t.Fatal(err)
	}
	r := &runtime{cfg: prior.cfg, manager: m, client: prior.client, output: io.Discard, messages: map[string]time.Time{}, readyAfter: map[string]time.Time{}, view: prior.view, viewAt: prior.viewAt, counts: map[string]int{}}
	if err = r.restore(); err != nil {
		t.Fatal(err)
	}
	return r
}

// integrationBalance は正本と戦略状態の数量・損益が一致することを確認します。
//
// 引数: t(*testing.T)、r(*runtime)、quantity(int)、pnl(float64)。返り値: なし。
func integrationBalance(t *testing.T, r *runtime, quantity int, pnl float64) {
	t.Helper()
	n := 0
	for _, p := range r.manager.Positions() {
		n += p.Quantity
	}
	value := 0.0
	for _, v := range r.manager.Records() {
		value += v.PnL
	}
	if n != quantity || r.engine.Status().Quantity != quantity || value != pnl || r.engine.RealizedYen != pnl {
		t.Fatalf("台帳不一致: 実枚数=%d 戦略枚数=%d 実損益=%v 戦略損益=%v", n, r.engine.Status().Quantity, value, r.engine.RealizedYen)
	}
}

// TestExecutionIntegrationDryRunReductionRestart は新規・悪化半減・復元・追跡返済と二重反映防止を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestExecutionIntegrationDryRunReductionRestart(t *testing.T) {
	broker := &integrationBroker{}
	server := httptest.NewServer(broker)
	defer server.Close()
	r, path := integrationRuntime(t, true, server.URL)
	integrationTick(t, r, 1200, 100, 0)
	integrationTick(t, r, 1201, 103, 0)
	integrationBalance(t, r, 5, 0)
	if r.origin != nil || r.manager.HasPending() {
		t.Fatal("完了した新規意図が残っています")
	}
	integrationTick(t, r, 1202, 118, 0)
	integrationTick(t, r, 1203, 117, -1)
	events := integrationTick(t, r, 1204, 116, 0)
	if len(events) != 1 || events[0].ReasonCode != 30 {
		t.Fatalf("悪化半減が発生しません: %+v", events)
	}
	integrationBalance(t, r, 3, 26000)
	r = integrationRestore(t, r, path)
	integrationBalance(t, r, 3, 26000)
	for i := 0; i < 3; i++ {
		if err := r.synchronize(); err != nil {
			t.Fatal(err)
		}
	}
	if len(r.manager.Records()) != 2 {
		t.Fatal("再同期が記録を二重反映しました")
	}
	integrationTick(t, r, 1205, 123, 0)
	integrationTick(t, r, 1206, 133, 0)
	integrationTick(t, r, 1207, 125, 0)
	integrationBalance(t, r, 0, 92000)
	if r.origin != nil || r.targetQuantity != nil || len(r.manager.Records()) != 3 {
		t.Fatal("完済後の意図・元枠・記録数が不一致です")
	}
	if len(broker.Requests()) != 0 {
		t.Fatal("dryrun が HTTP 発注しました")
	}
	r = integrationRestore(t, r, path)
	integrationBalance(t, r, 0, 92000)
	// ----------------------------------------
	// 次の組でも既存のセッション損益を重複加算せず、確定損失だけを追加します。
	integrationTick(t, r, 1208, 100, 0)
	integrationTick(t, r, 1509, 100, 0)
	integrationTick(t, r, 1510, 103, 0)
	integrationBalance(t, r, 5, 92000)
	integrationTick(t, r, 1511, 95, 0)
	integrationBalance(t, r, 0, 52000)
	if len(r.manager.Records()) != 5 {
		t.Fatal("次の組で約定を重複記録しました")
	}
}

// TestExecutionIntegrationCrashBeforeSynchronization は約定後・戦略同期前の停止を正本から復旧します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestExecutionIntegrationCrashBeforeSynchronization(t *testing.T) {
	r, path := integrationRuntime(t, true, "")
	integrationTick(t, r, 1200, 100, 0)
	at := atTime(r.engine.Session.Start + 1201)
	events, err := r.engine.OnTick(strategy.Tick{Time: unix(at), Price: 103, ATR: 10, Direction: 1, AdverseSource: -1, AllowEntry: true, InputIndex: r.engine.Row + 1})
	if err != nil || len(events) != 1 {
		t.Fatalf("新規準備: %v %+v", err, events)
	}
	r.origin = &events[0]
	if err = r.checkpoint(); err != nil {
		t.Fatal(err)
	}
	_, err = r.manager.Submit(context.Background(), nil, execution.Intent{ID: "同期直前停止", Session: r.engine.Session.ID, ContractSymbol: "167120019", Side: "buy", TradeType: "new", Reason: "追跡新規", Quantity: 5, Price: 104, At: at, ExpiresAt: at.Add(time.Minute)}, r.view)
	if err != nil {
		t.Fatal(err)
	}
	if len(r.manager.OutstandingFills()) != 1 {
		t.Fatal("未同期約定が保存されません")
	}
	r = integrationRestore(t, r, path)
	integrationBalance(t, r, 5, 0)
	if r.engine.Status().EntryPrice != 104 || r.origin != nil {
		t.Fatal("復元時に実約定単価を反映できません")
	}
	if err = r.checkpoint(); err != nil {
		t.Fatal(err)
	}
	r = integrationRestore(t, r, path)
	integrationBalance(t, r, 5, 0)
	if len(r.manager.Records()) != 1 || len(r.manager.OutstandingFills()) != 0 {
		t.Fatal("復旧が同一約定を重複処理しました")
	}
}

// TestExecutionIntegrationLivePartialCloseRetry は受付と約定を分け、FAK 部分返済の残枚数だけを再返済します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestExecutionIntegrationLivePartialCloseRetry(t *testing.T) {
	broker := &integrationBroker{}
	server := httptest.NewServer(broker)
	defer server.Close()
	r, path := integrationRuntime(t, false, server.URL)
	integrationTick(t, r, 1200, 100, 0)
	integrationTick(t, r, 1201, 103, 0)
	integrationBalance(t, r, 0, 0)
	if r.origin == nil || !r.manager.HasPending() || len(broker.Requests()) != 1 {
		t.Fatal("受付を実約定と混同しました")
	}
	r.view.BrokerOrders = []controller.BrokerOrder{{ID: "order1", Symbol: "167120019", Side: "2", State: 5, CumQty: 3, Details: []controller.BrokerDetail{{RecType: 8, ExecutionID: "hold1", Qty: 3, Price: 104}}}}
	r.view.Positions = []controller.Position{{ExecutionID: "hold1", Symbol: "167120019", Side: "buy", Quantity: 3, AvailableQuantity: 3, Price: 104}}
	integrationAccountAt(r, atTime(r.engine.Session.Start+1201.5))
	if _, err := r.manager.Reconcile(r.view); err != nil {
		t.Fatal(err)
	}
	if err := r.synchronize(); err != nil {
		t.Fatal(err)
	}
	if err := r.checkpoint(); err != nil {
		t.Fatal(err)
	}
	integrationBalance(t, r, 3, 0)
	if r.origin != nil || r.engine.Status().EntryPrice != 104 {
		t.Fatal("部分新規の実数量・単価が反映されません")
	}
	integrationTick(t, r, 1202, 90, 0)
	if r.targetQuantity == nil || *r.targetQuantity != 0 {
		t.Fatal("全返済目標が残りません")
	}
	integrationBalance(t, r, 3, 0)
	r.view.BrokerOrders = append(r.view.BrokerOrders, controller.BrokerOrder{ID: "order2", Symbol: "167120019", Side: "1", State: 5, CumQty: 1, Details: []controller.BrokerDetail{{RecType: 8, ExecutionID: "close1", Qty: 1, Price: 91}}})
	r.view.Positions[0].Quantity = 2
	r.view.Positions[0].AvailableQuantity = 2
	integrationAccountAt(r, atTime(r.engine.Session.Start+1202.5))
	if _, err := r.manager.Reconcile(r.view); err != nil {
		t.Fatal(err)
	}
	if err := r.synchronize(); err != nil {
		t.Fatal(err)
	}
	if err := r.checkpoint(); err != nil {
		t.Fatal(err)
	}
	integrationBalance(t, r, 2, -13000)
	if r.origin == nil || r.targetQuantity == nil || r.manager.HasPending() {
		t.Fatal("確定部分返済の残玉追跡が不一致です")
	}
	r = integrationRestore(t, r, path)
	integrationBalance(t, r, 2, -13000)
	at := atTime(r.engine.Session.Start + 1206)
	integrationAccountAt(r, at)
	if err := r.retryClose(at, 92); err != nil {
		t.Fatal(err)
	}
	requests := broker.Requests()
	if len(requests) != 3 || requests[1].Qty != 3 || requests[2].Qty != 2 || len(requests[2].ClosePositions) != 1 || requests[2].ClosePositions[0].HoldID != "hold1" {
		t.Fatalf("未約定残の注文が不一致: %+v", requests)
	}
	r.view.BrokerOrders = append(r.view.BrokerOrders, controller.BrokerOrder{ID: "order3", Symbol: "167120019", Side: "1", State: 5, CumQty: 2, Details: []controller.BrokerDetail{{RecType: 8, ExecutionID: "close2", Qty: 2, Price: 92}}})
	r.view.Positions = nil
	integrationAccountAt(r, atTime(r.engine.Session.Start+1206.5))
	if _, err := r.manager.Reconcile(r.view); err != nil {
		t.Fatal(err)
	}
	if err := r.synchronize(); err != nil {
		t.Fatal(err)
	}
	if err := r.checkpoint(); err != nil {
		t.Fatal(err)
	}
	integrationBalance(t, r, 0, -37000)
	if r.origin != nil || r.targetQuantity != nil || r.manager.HasPending() {
		t.Fatal("完済後に意図が残っています")
	}
	if _, err := r.manager.Reconcile(r.view); err != nil {
		t.Fatal(err)
	}
	if err := r.synchronize(); err != nil {
		t.Fatal(err)
	}
	if len(r.manager.Records()) != 3 || len(r.manager.OutstandingFills()) != 0 {
		t.Fatal("確定約定を二重反映しました")
	}
}
