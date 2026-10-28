package runner

import (
	"context"
	"fmt"
	"sync"
	"time"

	"ose-future/e01/internal/config"
	"ose-future/e01/internal/controller"
)

type feedEvent struct {
	Kind  string
	At    time.Time
	Value any
	Err   error
}
type candleSet struct {
	Registration controller.Registrations
	Candles      map[string]controller.Candles
}

// seconds は設定秒数を時間間隔へ変換します。
//
// 引数: v float64。秒数。
// 返り値: time.Duration。指定間隔。
func seconds(v float64) time.Duration { return time.Duration(v * float64(time.Second)) }

// emit は受信順に有界キューへ通知し、停止時に抜けます。
//
// 引数: ctx context.Context、out chan<- feedEvent、event feedEvent。
// 返り値: bool。通知できた場合true。
func emit(ctx context.Context, out chan<- feedEvent, event feedEvent) bool {
	select {
	case out <- event:
		return true
	case <-ctx.Done():
		return false
	}
}

// wait は取消可能な再取得待機を行います。
//
// 引数: ctx context.Context、duration time.Duration。
// 返り値: bool。待機終了時true、取消時false。
func wait(ctx context.Context, duration time.Duration) bool {
	t := time.NewTimer(duration)
	defer t.Stop()
	select {
	case <-t.C:
		return true
	case <-ctx.Done():
		return false
	}
}

// fetchCandles は登録一覧と両市場の4系統の足を並列取得します。
//
// 引数: ctx context.Context、client *controller.Client。
// 返り値: candleSet と error。途中切替で混在した応答は拒否します。
func fetchCandles(ctx context.Context, client *controller.Client) (candleSet, error) {
	reg, err := client.Registrations(ctx)
	if err != nil {
		return candleSet{}, err
	}
	type result struct {
		key  string
		data controller.Candles
		err  error
	}
	ch := make(chan result, 4)
	for _, code := range []string{"NK225", "TOPIX"} {
		for _, interval := range []string{"1min", "5min"} {
			go func(code, interval string) {
				v, e := client.Candles(ctx, code, interval, "", time.Time{}, time.Time{})
				ch <- result{code + "/" + interval, v, e}
			}(code, interval)
		}
	}
	set := candleSet{Registration: reg, Candles: map[string]controller.Candles{}}
	for i := 0; i < 4; i++ {
		v := <-ch
		if v.err != nil {
			err = v.err
		}
		set.Candles[v.key] = v.data
	}
	if err != nil {
		return set, err
	}
	return set, validateBatch(set)
}

// validateBatch は全応答のセッション・世代・時刻・商品が揃うことを検証します。
//
// 引数: set candleSet。取得結果。
// 返り値: error。不整合の説明、正常時nil。
func validateBatch(set candleSet) error {
	if len(set.Candles) != 4 {
		return fmt.Errorf("足の4系統が揃っていません")
	}
	base, ok := set.Candles["NK225/1min"]
	if !ok {
		return fmt.Errorf("NK225の1分足がありません")
	}
	b := base.Snapshot
	if b.SessionID == "" || b.Generation == "" || b.Session.StartsAt.IsZero() || !b.Session.EndsAt.After(b.Session.StartsAt) {
		return fmt.Errorf("セッション情報が未確定です")
	}
	for _, code := range []string{"NK225", "TOPIX"} {
		for _, interval := range []string{"1min", "5min"} {
			v, ok := set.Candles[code+"/"+interval]
			s := v.Snapshot
			if !ok || s.Code != code || s.SessionID != b.SessionID || s.Generation != b.Generation || !s.Session.StartsAt.Equal(b.Session.StartsAt) || !s.Session.EndsAt.Equal(b.Session.EndsAt) {
				return fmt.Errorf("足取得中にセッション・世代が切り替わりました")
			}
		}
	}
	return nil
}

// startFeed はPUSH・足・口座状態を独立取得し、停止関数を返します。
//
// 引数: parent context.Context、client *controller.Client、cfg config.Config。
// 返り値: <-chan feedEvent と func()。停止関数は全受信処理の終了を待ちます。
func startFeed(parent context.Context, client *controller.Client, cfg config.Config) (<-chan feedEvent, func()) {
	ctx, cancel := context.WithCancel(parent)
	out := make(chan feedEvent, 8192)
	var wg sync.WaitGroup
	wg.Add(3)
	go func() {
		defer wg.Done()
		for ctx.Err() == nil {
			set, err := fetchCandles(ctx, client)
			if !emit(ctx, out, feedEvent{Kind: "candles", At: time.Now(), Value: set, Err: err}) {
				return
			}
			if !wait(ctx, seconds(cfg.Controller.CandlePollSeconds)) {
				return
			}
		}
	}()
	go func() {
		defer wg.Done()
		for ctx.Err() == nil {
			view, err := client.Orders(ctx, "all")
			if !emit(ctx, out, feedEvent{Kind: "orders", At: time.Now(), Value: view, Err: err}) {
				return
			}
			if !wait(ctx, seconds(cfg.Controller.OrderPollSeconds)) {
				return
			}
		}
	}()
	go func() {
		defer wg.Done()
		for ctx.Err() == nil {
			err := client.Stream(ctx, func(board controller.Board) error {
				if !emit(ctx, out, feedEvent{Kind: "book", At: time.Now(), Value: board}) {
					return ctx.Err()
				}
				return nil
			})
			if ctx.Err() != nil {
				return
			}
			if !emit(ctx, out, feedEvent{Kind: "disconnect", At: time.Now(), Err: err}) {
				return
			}
			if !wait(ctx, seconds(cfg.Controller.ReconnectSeconds)) {
				return
			}
		}
	}()
	return out, func() { cancel(); wg.Wait() }
}
