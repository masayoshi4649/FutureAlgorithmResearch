package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"sort"
	"sync"
	"sync/atomic"
	"time"
)

const futureHistoryMinuteSlots = 1801
const futureHistoryCandleSlots = 1024
const futureHistoryChunkSize = 64

var errFutureHistorySessionChanged = errors.New("履歴の対象セッションが切り替わりました")
var futureHistoryGenerationSequence atomic.Uint64

// futureHistoryRecord は、受信順と受信時刻を付けた変更不可の生JSONです。
type futureHistoryRecord struct {
	receivedAt time.Time
	sequence   uint64
	payload    json.RawMessage
}

// futureHistoryChunk は、同じ受信分の最大64件を保持する変更不可の連結ブロックです。
type futureHistoryChunk struct {
	previous *futureHistoryChunk
	records  []futureHistoryRecord
}

// futureHistoryHead は、読み取り開始時点を固定する小さな公開値です。
type futureHistoryHead struct {
	asOf                    time.Time
	sequence, bytes         uint64
	firstMinute, lastMinute int
	count1, count5          int
	last1, last5            futureHistoryCandle
}

// futureHistoryProduct は、銘柄単位の追加領域と単一書き手専用集計器を保持します。
type futureHistoryProduct struct {
	raw       [futureHistoryMinuteSlots]atomic.Pointer[futureHistoryChunk]
	one       [futureHistoryCandleSlots]atomic.Pointer[futureHistoryCandle]
	five      [futureHistoryCandleSlots]atomic.Pointer[futureHistoryCandle]
	head      atomic.Pointer[futureHistoryHead]
	aggregate *futureHistoryCandles
}

// futureHistorySession は、終了後にそのまま保存担当へ所有権を移すセッションです。
// 公開済みのproductsは変更せず、OPの追加時はマップを複製して再公開します。
type futureHistorySession struct {
	id         string
	generation string
	session    futureOrderSession
	baseDate   time.Time
	createdAt  time.Time
	products   map[string]*futureHistoryProduct
}

// futureHistorySnapshot は、生データ本体への参照を持たない読み取り開始点です。
type futureHistorySnapshot struct {
	ID         string             `json:"sessionId"`
	Generation string             `json:"generation"`
	Code       string             `json:"code"`
	Session    futureOrderSession `json:"session"`
	AsOf       time.Time          `json:"asOf"`
	Sequence   uint64             `json:"sequence"`
	head       futureHistoryHead
	baseDate   time.Time
}

// futureHistoryStatus は、現在量と保存待ち量を公開します。
type futureHistoryStatus struct {
	Current          []futureHistoryProductStatus `json:"current"`
	PendingArchives  int                          `json:"pendingArchives"`
	PendingBytes     uint64                       `json:"pendingBytes"`
	LastArchiveError string                       `json:"lastArchiveError,omitempty"`
}

// futureHistoryProductStatus は、JSON本文のバイト数と足数を公開します。
type futureHistoryProductStatus struct {
	SessionID string `json:"sessionId"`
	Code      string `json:"code"`
	Records   uint64 `json:"records"`
	Bytes     uint64 `json:"bytes"`
	Candles1  int    `json:"candles1min"`
	Candles5  int    `json:"candles5min"`
}

// futureHistoryManager は、短時間の書き手ロックと独立した保存待ち列を管理します。
// HTTP読み取り、ファイル保存はwriteMuを取得しません。
type futureHistoryManager struct {
	writeMu          sync.Mutex
	current          atomic.Pointer[futureHistorySession]
	config           SessionConfig
	lookup           func(string) string
	root             string
	latest           time.Time
	closed           bool
	queueMu          sync.Mutex
	pending          []*futureHistorySession
	lastArchiveError string
	wake             chan struct{}
	stop             chan struct{}
	done             chan struct{}
	startOnce        sync.Once
	closeOnce        sync.Once
	archive          func(*futureHistorySession) error
}

// newFutureHistoryManager は、まだ起動していない履歴管理を生成します。
//
// 引数:
//   - root string: book、candle_1min、candle_5minの親ディレクトリ。
//   - config SessionConfig: 既存のセッション設定。
//   - lookup func(string) string: 登録済み銘柄IDから先物またはOPの履歴コードを返す関数。
//
// 返り値:
//   - *futureHistoryManager: ディスクや上流への接続をまだ行わない管理器。
func newFutureHistoryManager(root string, config SessionConfig, lookup func(string) string) *futureHistoryManager {
	manager := &futureHistoryManager{root: root, config: config, lookup: lookup,
		wake: make(chan struct{}, 1), stop: make(chan struct{}), done: make(chan struct{})}
	manager.archive = manager.archiveSession
	return manager
}

// Start は、秒境界の確定処理と独立した保存処理を開始します。
//
// 引数: なし。
// 返り値: なし。複数回呼び出しても一度だけ起動します。
func (manager *futureHistoryManager) Start() {
	manager.startOnce.Do(func() {
		go manager.archiveLoop()
		go func() {
			defer close(manager.done)
			ticker := time.NewTicker(time.Second)
			defer ticker.Stop()
			for {
				select {
				case now := <-ticker.C:
					manager.Advance(now)
				case <-manager.stop:
					return
				}
			}
		}()
	})
}

// Close は、収集とタイマーを停止し、現セッションを破棄します。
// 保存中の終了済みセッションは保存完了後に解放し、停止時に未保存のデータ復元は行いません。
//
// 引数: なし。
// 返り値: なし。低速ディスクの完了を待ってアプリ停止を妨げません。
func (manager *futureHistoryManager) Close() {
	manager.closeOnce.Do(func() {
		manager.writeMu.Lock()
		manager.closed = true
		manager.current.Store(nil)
		manager.writeMu.Unlock()
		close(manager.stop)
	})
}

// Observe は、対象先物・OPの受信JSONを追加し、現在の足だけを差分更新します。
//
// 引数:
//   - symbol string: 受信JSONの銘柄ID。
//   - payload []byte: 保存する生JSON。呼び出し後の変更と独立させます。
//   - receivedAt time.Time: アプリケーションで受信した時刻。
//
// 返り値: なし。未登録銘柄と対象外商品は複製も保存もしません。
func (manager *futureHistoryManager) Observe(symbol string, payload []byte, receivedAt time.Time) {
	if manager.lookup == nil {
		return
	}
	code := manager.lookup(symbol)
	if !isHistoryCode(code) {
		return
	}
	var quote futureHistoryQuote
	if json.Unmarshal(payload, &quote) != nil {
		return
	}
	var compact bytes.Buffer
	if json.Compact(&compact, payload) != nil {
		return
	}
	retained := compact.Bytes()
	manager.writeMu.Lock()
	defer manager.writeMu.Unlock()
	state := manager.advanceLocked(receivedAt)
	if state == nil {
		return
	}
	minute := int(receivedAt.Sub(state.baseDate) / time.Minute)
	if minute < 0 || minute >= futureHistoryMinuteSlots {
		return
	}
	product := state.products[code]
	newProduct := product == nil
	if newProduct {
		product = newFutureHistoryProduct(state.session, receivedAt)
	}
	oldHead := product.head.Load()
	head := *oldHead
	if receivedAt.After(head.asOf) {
		head.asOf = receivedAt
	}
	head.sequence++
	head.bytes += uint64(len(retained))
	if head.firstMinute < 0 || minute < head.firstMinute {
		head.firstMinute = minute
	}
	if minute > head.lastMinute {
		head.lastMinute = minute
	}
	record := futureHistoryRecord{receivedAt: receivedAt, sequence: head.sequence, payload: retained}
	previous := product.raw[minute].Load()
	chunk := &futureHistoryChunk{}
	if previous != nil && len(previous.records) < futureHistoryChunkSize {
		chunk.previous = previous.previous
		chunk.records = make([]futureHistoryRecord, len(previous.records)+1)
		copy(chunk.records, previous.records)
		chunk.records[len(previous.records)] = record
	} else {
		chunk.previous = previous
		chunk.records = []futureHistoryRecord{record}
	}
	product.raw[minute].Store(chunk)
	product.publishCandles(&head, product.aggregate.Apply(quote, receivedAt))
	product.head.Store(&head)
	if newProduct {
		manager.addProductLocked(state, code, product)
	}
}

// ----------------------------------------

// newFutureHistoryProduct は、銘柄ごとに独立した受信領域と足集計器を作成します。
//
// 引数:
//   - session futureOrderSession: 収集対象のセッション。
//   - now time.Time: 空の履歴の基準時刻。
//
// 返り値: *futureHistoryProduct: 受信件数がゼロの未公開領域。
func newFutureHistoryProduct(session futureOrderSession, now time.Time) *futureHistoryProduct {
	product := &futureHistoryProduct{aggregate: newFutureHistoryCandles(session.StartsAt, session.EndsAt)}
	product.head.Store(&futureHistoryHead{asOf: now, firstMinute: -1, lastMinute: -1})
	return product
}

// addProductLocked は、既存銘柄の領域を共有したままOPを追加したマップを公開します。
// 読み取り中のマップを変更せず、セッション識別子と取得済みの上限を維持します。
//
// 引数:
//   - state *futureHistorySession: writeMu取得中の現在セッション。
//   - code string: 追加するOPの履歴コード。
//   - product *futureHistoryProduct: 最初の受信データを格納済みの銘柄領域。
//
// 返り値: なし。
func (manager *futureHistoryManager) addProductLocked(state *futureHistorySession, code string, product *futureHistoryProduct) {
	next := *state
	next.products = make(map[string]*futureHistoryProduct, len(state.products)+1)
	for existingCode, existingProduct := range state.products {
		next.products[existingCode] = existingProduct
	}
	next.products[code] = product
	manager.current.Store(&next)
}

// ----------------------------------------

// Advance は、受信がない場合も足の確定とセッションの交代を行います。
//
// 引数: now time.Time: 判定時刻。
// 返り値: なし。
func (manager *futureHistoryManager) Advance(now time.Time) {
	manager.writeMu.Lock()
	defer manager.writeMu.Unlock()
	manager.advanceLocked(now)
}

// advanceLocked は、既存セッション判定を使い終了済み領域を保存待ちへ移します。
//
// 引数: now time.Time: 判定時刻。writeMu取得中だけ呼び出します。
// 返り値: *futureHistorySession: 有効な現在領域。スキップ中や過去時刻ならnil。
func (manager *futureHistoryManager) advanceLocked(now time.Time) *futureHistorySession {
	if manager.closed {
		return nil
	}
	session, err := resolveFutureOrderSessionWithConfig(now, manager.config)
	state := manager.current.Load()
	if now.Before(manager.latest) {
		if state == nil || err != nil || !session.StartsAt.Equal(state.session.StartsAt) {
			return nil
		}
	} else {
		manager.latest = now
	}
	if state != nil && (err != nil || !session.StartsAt.Equal(state.session.StartsAt)) {
		for _, product := range state.products {
			head := *product.head.Load()
			product.publishCandles(&head, product.aggregate.Advance(state.session.EndsAt))
			product.head.Store(&head)
		}
		manager.current.Store(nil)
		manager.enqueueArchive(state)
		state = nil
	}
	if err != nil {
		return nil
	}
	if state == nil {
		local := session.StartsAt.In(futureOrderSessionLocation)
		label := "Day"
		if session.Name == "night" {
			label = "Night"
		}
		state = &futureHistorySession{id: local.Format("2006-01-02") + "_" + label, generation: newFutureHistoryGeneration(), session: session,
			baseDate:  time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, futureOrderSessionLocation),
			createdAt: now,
			products:  make(map[string]*futureHistoryProduct, 2)}
		for _, code := range []string{"NK225", "TOPIX"} {
			state.products[code] = newFutureHistoryProduct(session, now)
		}
		manager.current.Store(state)
	}
	for _, product := range state.products {
		updates := product.aggregate.Advance(now)
		if len(updates) > 0 {
			head := *product.head.Load()
			head.asOf = now
			product.publishCandles(&head, updates)
			product.head.Store(&head)
		}
	}
	return state
}

// publishCandles は、変更された足だけを変更不可の値として公開します。
//
// 引数:
//   - head *futureHistoryHead: 書き手が更新する未公開の読み取り開始点。
//   - updates []futureHistoryCandleUpdate: 集計器からの差分。
//
// 返り値: なし。
func (product *futureHistoryProduct) publishCandles(head *futureHistoryHead, updates []futureHistoryCandleUpdate) {
	for _, update := range updates {
		if update.Index < 0 || update.Index >= futureHistoryCandleSlots {
			continue
		}
		candle := update.Candle
		if update.Interval == 1 {
			product.one[update.Index].Store(&candle)
			head.count1, head.last1 = update.Index+1, candle
		} else if update.Interval == 5 {
			product.five[update.Index].Store(&candle)
			head.count5, head.last5 = update.Index+1, candle
		}
	}
}

// Snapshot は、生データ全体を参照せず、現在の公開位置を固定します。
//
// 引数: code string: NK225、TOPIX、または限月・C/P・権利行使価格を含むOPの履歴コード。
// 返り値:
//   - futureHistorySnapshot: 応答の基準となる位置と時刻。
//   - error: 対象外銘柄または現セッションがない場合のエラー。
func (manager *futureHistoryManager) Snapshot(code string) (futureHistorySnapshot, error) {
	if !isHistoryCode(code) {
		return futureHistorySnapshot{}, errors.New("履歴コードにはNK225、TOPIX、または限月・C/P・権利行使価格を含むNK225opを指定してください")
	}
	state := manager.current.Load()
	if state == nil {
		return futureHistorySnapshot{}, errors.New("現在の履歴セッションはありません")
	}
	head := futureHistoryHead{asOf: state.createdAt, firstMinute: -1, lastMinute: -1}
	if product := state.products[code]; product != nil {
		head = *product.head.Load()
	}
	return futureHistorySnapshot{ID: state.id, Generation: state.generation, Code: code, Session: state.session,
		AsOf: head.asOf, Sequence: head.sequence, head: head, baseDate: state.baseDate}, nil
}

// rawMinute は、現在領域への参照を外へ持ち出さず必要な１分だけ取得します。
//
// 引数:
//   - snapshot futureHistorySnapshot: 固定済み読み取り位置。
//   - minute int: 開始日午前０時からの分番号。
//
// 返り値:
//   - *futureHistoryChunk: 指定分の変更不可ブロック。
//   - error: セッションが切り替わった場合のエラー。
func (manager *futureHistoryManager) rawMinute(snapshot futureHistorySnapshot, minute int) (*futureHistoryChunk, error) {
	state := manager.current.Load()
	if state == nil || state.generation != snapshot.Generation {
		return nil, errFutureHistorySessionChanged
	}
	return state.products[snapshot.Code].raw[minute].Load(), nil
}

// ReadRaw は、範囲に含まれる受信分だけを順番に取り出します。
//
// 引数:
//   - ctx context.Context: 読み取り中断の通知。
//   - snapshot futureHistorySnapshot: 応答開始時に固定した上限。
//   - from、to time.Time: 受信時刻の開始以上・終了未満。ゼロ値は無指定。
//   - emit func([]byte) error: JSONを１件送る関数。書き手ロックの外で呼びます。
//
// 返り値: error: 中断、セッション交代、または送信先のエラー。
func (manager *futureHistoryManager) ReadRaw(ctx context.Context, snapshot futureHistorySnapshot, from, to time.Time, emit func([]byte) error) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if manager.sessionChanged(snapshot.Generation) {
		return errFutureHistorySessionChanged
	}
	first, last := snapshot.head.firstMinute, snapshot.head.lastMinute
	if first < 0 {
		return nil
	}
	if !from.IsZero() && from.After(snapshot.baseDate.Add(time.Duration(first)*time.Minute)) {
		first = int(from.Sub(snapshot.baseDate) / time.Minute)
	}
	if !to.IsZero() && to.Before(snapshot.baseDate.Add(time.Duration(last+1)*time.Minute)) {
		last = int(to.Sub(snapshot.baseDate) / time.Minute)
	}
	for minute := first; minute <= last; minute++ {
		if err := ctx.Err(); err != nil {
			return err
		}
		chunk, err := manager.rawMinute(snapshot, minute)
		if err != nil {
			return err
		}
		chunks := make([]*futureHistoryChunk, 0, 16)
		for chunk != nil {
			chunks = append(chunks, chunk)
			chunk = chunk.previous
		}
		for index := len(chunks) - 1; index >= 0; index-- {
			for _, record := range chunks[index].records {
				if record.sequence > snapshot.Sequence || (!from.IsZero() && record.receivedAt.Before(from)) || (!to.IsZero() && !record.receivedAt.Before(to)) {
					continue
				}
				if err := ctx.Err(); err != nil {
					return err
				}
				if manager.sessionChanged(snapshot.Generation) {
					return errFutureHistorySessionChanged
				}
				if err := emit(record.payload); err != nil {
					return err
				}
			}
		}
	}
	state := manager.current.Load()
	if state == nil || state.generation != snapshot.Generation {
		return errFutureHistorySessionChanged
	}
	return nil
}

// sessionChanged は、巨大なセッション領域への参照を呼び出し側へ残さず交代を確認します。
//
// 引数: generation string: 読み取り開始時のセッション領域識別子。
// 返り値: bool: 現在領域がないか、別のセッションへ移った場合true。
func (manager *futureHistoryManager) sessionChanged(generation string) bool {
	state := manager.current.Load()
	return state == nil || state.generation != generation
}

// Candles は、公開済み足から二分探索で指定範囲だけを複製します。
//
// 引数:
//   - snapshot futureHistorySnapshot: 現形成足の値も固定した位置。
//   - interval int: １または５。
//   - from、to time.Time: 足開始時刻の開始以上・終了未満。ゼロ値は無指定。
//
// 返り値:
//   - []futureHistoryCandle: 書き手から独立した足の配列。
//   - error: 不正な間隔またはセッション切替のエラー。
func (manager *futureHistoryManager) Candles(snapshot futureHistorySnapshot, interval int, from, to time.Time) ([]futureHistoryCandle, error) {
	state := manager.current.Load()
	if state == nil || state.generation != snapshot.Generation {
		return nil, errFutureHistorySessionChanged
	}
	if interval != 1 && interval != 5 {
		return nil, errors.New("足の間隔は１分または５分です")
	}
	product := state.products[snapshot.Code]
	if product == nil {
		return []futureHistoryCandle{}, nil
	}
	count, latest, slots := snapshot.head.count1, snapshot.head.last1, &product.one
	if interval == 5 {
		count, latest, slots = snapshot.head.count5, snapshot.head.last5, &product.five
	}
	get := func(index int) futureHistoryCandle {
		if index == count-1 {
			return latest
		}
		return *slots[index].Load()
	}
	low, high := 0, count
	if !from.IsZero() {
		for low < high {
			middle := (low + high) / 2
			if get(middle).Time.Before(from) {
				low = middle + 1
			} else {
				high = middle
			}
		}
	}
	result := make([]futureHistoryCandle, 0, count-low)
	for index := low; index < count; index++ {
		candle := get(index)
		if !to.IsZero() && !candle.Time.Before(to) {
			break
		}
		result = append(result, candle)
	}
	return result, nil
}

// ----------------------------------------

// newFutureHistoryGeneration は、再起動やセッション交代を識別する領域識別子を生成します。
//
// 引数: なし。
// 返り値:
//   - string: 128ビット乱数の16進表現。乱数取得失敗時は時刻・プロセスID・連番を使用します。
func newFutureHistoryGeneration() string {
	var value [16]byte
	if _, err := rand.Read(value[:]); err == nil {
		return hex.EncodeToString(value[:])
	}
	return fmt.Sprintf("%x-%x-%x", time.Now().UnixNano(), os.Getpid(), futureHistoryGenerationSequence.Add(1))
}

// ----------------------------------------

// productCodes は、セッション内の先物・OPの履歴コードを一定の順序で返します。
//
// 引数: なし。
// 返り値: []string: 履歴コードの昇順に並べた独立した配列。
func (state *futureHistorySession) productCodes() []string {
	codes := make([]string, 0, len(state.products))
	for code := range state.products {
		codes = append(codes, code)
	}
	sort.Strings(codes)
	return codes
}

// ----------------------------------------

// Status は、全生データの走査なしで現セッションと保存待ち量を返します。
//
// 引数: なし。
// 返り値: futureHistoryStatus: JSON本文量。Goの管理領域や一時割当量は含みません。
func (manager *futureHistoryManager) Status() futureHistoryStatus {
	result := futureHistoryStatus{Current: []futureHistoryProductStatus{}}
	if state := manager.current.Load(); state != nil {
		for _, code := range state.productCodes() {
			head := state.products[code].head.Load()
			result.Current = append(result.Current, futureHistoryProductStatus{SessionID: state.id, Code: code,
				Records: head.sequence, Bytes: head.bytes, Candles1: head.count1, Candles5: head.count5})
		}
	}
	manager.queueMu.Lock()
	result.PendingArchives, result.LastArchiveError = len(manager.pending), manager.lastArchiveError
	for _, state := range manager.pending {
		for _, product := range state.products {
			result.PendingBytes += product.head.Load().bytes
		}
	}
	manager.queueMu.Unlock()
	return result
}
