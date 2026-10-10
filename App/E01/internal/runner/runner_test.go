package runner

import (
	"os"
	"testing"
	"time"

	"ose-future/e01/internal/controller"
	"ose-future/e01/internal/strategy"
)

// testCandleSet は場替わり検査用のAPI形式を作ります。
//
// 引数: start/end time.Time、generation string。返り値: candleSet。
func testCandleSet(start, end time.Time, generation string) candleSet {
	s := candleSet{Registration: controller.Registrations{State: "succeeded", Futures: []controller.Future{{FutureCode: "NK225", Symbol: "nk", DerivMonth: 202612}, {FutureCode: "TOPIX", Symbol: "tp", DerivMonth: 202612}, {FutureCode: "TOPIXmini", Symbol: "tm", DerivMonth: 202612}}}, Candles: map[string]controller.Candles{}}
	for _, code := range []string{"NK225", "TOPIX"} {
		for _, period := range []string{"1min", "5min"} {
			s.Candles[code+"/"+period] = controller.Candles{Snapshot: controller.Snapshot{SessionID: "2026-10-02_Night", Generation: generation, Code: code, Session: controller.Session{StartsAt: start, EndsAt: end}}}
		}
	}
	return s
}

// TestSessionBatchAndGeneration は世代混在と変更前にキューへ入ったPUSHを除外します。
//
// 引数: t *testing.T。返り値: なし。
func TestSessionBatchAndGeneration(t *testing.T) {
	now := time.Now()
	set := testCandleSet(now.Add(-2*time.Hour), now.Add(2*time.Hour), "first")
	if err := validateBatch(set); err != nil {
		t.Fatal(err)
	}
	v := set.Candles["TOPIX/5min"]
	v.Snapshot.Generation = "different"
	set.Candles["TOPIX/5min"] = v
	if validateBatch(set) == nil {
		t.Fatal("世代混在を受理しました")
	}
	r, _ := integrationRuntime(t, true, "")
	r.engine = nil
	r.activated = now
	set = testCandleSet(now.Add(-2*time.Hour), now.Add(2*time.Hour), "first")
	if err := r.acceptCandles(set, now); err != nil {
		t.Fatal(err)
	}
	set = testCandleSet(now.Add(-2*time.Hour), now.Add(2*time.Hour), "second")
	changed := now.Add(time.Second)
	if err := r.acceptCandles(set, changed); err != nil {
		t.Fatal(err)
	}
	board := controller.Board{Symbol: "tm", CurrentPrice: 4100, CurrentPriceTime: now.Format(time.RFC3339Nano)}
	if err := r.acceptBook(board, now); err != nil {
		t.Fatal(err)
	}
	if len(r.counts) != 0 || !r.activated.Equal(changed) {
		t.Fatal("変更前の板が新しい世代へ入りました")
	}
	set.Registration.State = "running"
	if err := r.acceptCandles(set, changed); err != nil {
		t.Fatal(err)
	}
	if r.registrationReady {
		t.Fatal("登録中の旧一覧で新規を許可しました")
	}
}

// TestClockCloseWithoutNewPush は停止時の返済が新しいPUSHを必要としないことを検査します。
//
// 引数: t *testing.T。返り値: なし。
func TestClockCloseWithoutNewPush(t *testing.T) {
	r, _ := integrationRuntime(t, true, "")
	integrationTick(t, r, 1200, 100, 0)
	integrationTick(t, r, 1201, 103, 0)
	at := atTime(r.engine.Session.Start + 1202)
	r.lastTarget = controller.Board{CurrentPrice: 110}
	r.lastQuote[r.cfg.Trading.Symbol] = at.Add(-time.Second)
	r.stopping = true
	r.lastWall = at
	r.lastCheckpoint = at
	r.lastStatus = at
	if err := r.watch(at); err != nil {
		t.Fatal(err)
	}
	integrationBalance(t, r, 0, 35000)
	if r.manager.Records()[1].Reason != "停止時返済" {
		t.Fatal("時刻監視の返済を記録できていません")
	}
}

// TestOldTradeTimeIsNotNetworkOutage は約定価格が動かなくても板受信中は通信断にしません。
//
// 引数: t *testing.T。返り値: なし。
func TestOldTradeTimeIsNotNetworkOutage(t *testing.T) {
	r, _ := integrationRuntime(t, true, "")
	integrationTick(t, r, 1200, 100, 0)
	integrationTick(t, r, 1201, 103, 0)
	at := atTime(r.engine.Session.Start + 1600)
	r.lastWall = at
	r.lastCheckpoint = at
	r.lastStatus = at
	for _, s := range r.codes() {
		r.lastPush[s] = at
		r.lastFresh[s] = at.Add(-5 * time.Minute)
		r.lastQuote[s] = at.Add(-5 * time.Minute)
	}
	if err := r.watch(at); err != nil {
		t.Fatal(err)
	}
	if r.longGap {
		t.Fatal("板が届いているのに価格不変を長時間通信断として扱いました")
	}
	integrationBalance(t, r, 5, 0)
	if _, ok := r.validQuote(controller.Board{CurrentPrice: 103, CurrentPriceTime: r.lastQuote[r.cfg.Trading.Symbol].Format(time.RFC3339Nano)}, at, r.cfg.Trading.Symbol); ok {
		t.Fatal("古い約定価格を採用しました")
	}
}

// TestShortGapAndNullPrices は短い中断で保有を維持しnull時刻を安全に除外します。
//
// 引数: t *testing.T。返り値: なし。
func TestShortGapAndNullPrices(t *testing.T) {
	r, _ := integrationRuntime(t, true, "")
	integrationTick(t, r, 1200, 100, 0)
	integrationTick(t, r, 1201, 103, 0)
	at := atTime(r.engine.Session.Start + 1202)
	r.features, _ = strategy.NewFeatures(r.engine.Session.ID, r.engine.Session.Start, map[string]float64{"NK225": 10, "TOPIX": .5}, strategy.DefaultFeatureConfig())
	for _, code := range r.codes() {
		r.lastPush[code] = at.Add(-2 * time.Second)
	}
	r.markGap("試験中断", at, true)
	if r.longGap {
		t.Fatal("2秒の切断で返済状態になりました")
	}
	integrationBalance(t, r, 5, 0)
	if _, ok := r.validQuote(controller.Board{CurrentPrice: 0, CurrentPriceTime: ""}, at, r.cfg.Trading.Symbol); ok {
		t.Fatal("null相当の価格を採用しました")
	}
	if err := r.checkpoint(); err != nil {
		t.Fatal(err)
	}
}

// TestDirectoryLock は同時起動の拒否と解放後の再起動を検査します。
//
// 引数: t *testing.T。返り値: なし。
func TestDirectoryLock(t *testing.T) {
	dir := t.TempDir()
	a, err := lockDirectory(dir)
	if err != nil {
		t.Fatal(err)
	}
	if b, err := lockDirectory(dir); err == nil {
		b.Close()
		a.Close()
		t.Fatal("同時起動を許可しました")
	}
	if err = a.Close(); err != nil {
		t.Fatal(err)
	}
	b, err := lockDirectory(dir)
	if err != nil {
		t.Fatal(err)
	}
	b.Close()
	if _, err = os.Stat(dir); err != nil {
		t.Fatal(err)
	}
}

// TestAccountFreshness は古い口座内容を新しいHTTP応答で包んでも新規に使用しません。
//
// 引数: t *testing.T。返り値: なし。
func TestAccountFreshness(t *testing.T) {
	r, _ := integrationRuntime(t, true, "")
	at := atTime(r.engine.Session.Start + 1200)
	r.viewAt = at
	if r.orderReady(at) {
		t.Fatal("更新時刻なしの口座を使用しました")
	}
	old := at.Add(-time.Minute)
	r.view.BrokerUpdatedAt = &old
	r.view.PositionsUpdatedAt = &old
	if r.orderReady(at) {
		t.Fatal("古い口座を使用しました")
	}
	r.view.BrokerUpdatedAt = &at
	r.view.PositionsUpdatedAt = &at
	if !r.orderReady(at) {
		t.Fatal("新鮮な口座が利用できません")
	}
}
