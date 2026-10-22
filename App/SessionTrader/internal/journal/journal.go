// Package journal はSQLiteを正本として、復元状態・約定・受信原文・判断履歴を保存します。
package journal

import (
	"bytes"
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sync"
	"time"

	_ "modernc.org/sqlite"
)

// Trade は、受付とは区別した確認済みの実約定または仮想約定です。
type Trade struct {
	ID            string          `json:"id"`
	At            time.Time       `json:"at"`
	Session       string          `json:"session"`
	Symbol        string          `json:"symbol"`
	Product       string          `json:"product"`
	Owner         string          `json:"owner"`
	Evidence      json.RawMessage `json:"evidence,omitempty"`
	TradeType     string          `json:"trade_type"`
	Side          string          `json:"side"`
	Quantity      int             `json:"quantity"`
	Price         float64         `json:"price"`
	PnL           float64         `json:"pnl"`
	Reason        string          `json:"reason"`
	ClientOrderID string          `json:"client_order_id"`
	ReservationID string          `json:"reservation_id"`
	BrokerOrderID string          `json:"broker_order_id"`
	ExecutionID   string          `json:"execution_id"`
	DryRun        bool            `json:"dryrun"`
}

// BookRecord は、同値受信も省略せず保存する一件の入力原文です。
type BookRecord struct {
	Session    string
	Generation string
	Code       string
	Received   time.Time
	Raw        json.RawMessage
	Source     string
}

// Store は単一DBと、そのDB専用のログディレクトリを管理します。
type Store struct {
	mu                sync.Mutex
	db                *sql.DB
	path, logDir      string
	traceSequence     int64
	traceNeedsRebuild bool
	tradesNeedRebuild bool
	closed            bool
}

// ProjectionError は、SQLiteへの確定後に派生ログの書出しだけが失敗した状態です。
type ProjectionError struct{ Err error }

// Error は、正本を巻き戻してはいけない保存状態を説明します。
//
// 引数: なし。
// 返り値: string はエラー説明です。
func (e *ProjectionError) Error() string {
	return "SQLite正本は保存済みですがログ更新に失敗しました: " + e.Err.Error()
}

// Unwrap は、派生ログの保存エラーを返します。
//
// 引数: なし。
// 返り値: error は元の入出力エラーです。
func (e *ProjectionError) Unwrap() error { return e.Err }

var sessionPattern = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}_(Day|Night)$`)

const schema = `
CREATE TABLE IF NOT EXISTS snapshot (
 id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL,
 state BLOB NOT NULL CHECK(json_valid(state)), updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trades (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
 session TEXT NOT NULL, dryrun INTEGER NOT NULL CHECK(dryrun IN(0,1)),
 body BLOB NOT NULL CHECK(json_valid(body))
);
CREATE TABLE IF NOT EXISTS sessions (
 session TEXT NOT NULL, dryrun INTEGER NOT NULL CHECK(dryrun IN(0,1)),
 PRIMARY KEY(session,dryrun)
);
CREATE TABLE IF NOT EXISTS books (
 id INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT NOT NULL,
 generation TEXT NOT NULL, code TEXT NOT NULL, received_at TEXT NOT NULL,
 source TEXT NOT NULL, raw BLOB NOT NULL CHECK(json_valid(raw))
);
CREATE INDEX IF NOT EXISTS books_session_code ON books(session,code,id);
CREATE TABLE IF NOT EXISTS events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
 session TEXT NOT NULL, code TEXT NOT NULL, correlation TEXT NOT NULL,
 at TEXT NOT NULL, payload BLOB NOT NULL CHECK(json_valid(payload))
);
CREATE INDEX IF NOT EXISTS events_session ON events(session,seq);
PRAGMA user_version=1;
`

// Open は、純GoのSQLiteを開き、正本からCSV・JSONLを復元します。
//
// 引数: path string はDBファイル、logDir string はこのDB専用の派生ログ保存先です。
// 返り値: *Store は保存器、error は設定・DB・ログの復元失敗です。
func Open(path, logDir string) (*Store, error) {
	if path == "" || logDir == "" || path == ":memory:" {
		return nil, fmt.Errorf("永続DBとログのパスを指定してください")
	}
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return nil, err
	}
	db, err := sql.Open("sqlite", path)
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)
	s := &Store{db: db, path: path, logDir: logDir, traceNeedsRebuild: true}
	fail := func(err error) (*Store, error) {
		_ = db.Close()
		return nil, err
	}
	for _, pragma := range []string{"PRAGMA busy_timeout=5000", "PRAGMA journal_mode=WAL", "PRAGMA synchronous=FULL", "PRAGMA foreign_keys=ON"} {
		if _, err = db.Exec(pragma); err != nil {
			return fail(err)
		}
	}
	var version int
	if err = db.QueryRow("PRAGMA user_version").Scan(&version); err != nil {
		return fail(err)
	}
	if version != 0 && version != 1 {
		return fail(fmt.Errorf("未対応のSQLite形式です: %d", version))
	}
	var integrity string
	if err = db.QueryRow("PRAGMA quick_check").Scan(&integrity); err != nil || integrity != "ok" {
		return fail(fmt.Errorf("SQLite整合性確認に失敗しました: %s: %v", integrity, err))
	}
	tx, err := db.Begin()
	if err != nil {
		return fail(err)
	}
	if _, err = tx.Exec(schema); err != nil {
		_ = tx.Rollback()
		return fail(err)
	}
	if err = tx.Commit(); err != nil {
		return fail(err)
	}
	if err = s.projectTrades(); err != nil {
		return fail(err)
	}
	if err = s.projectTrace(); err != nil {
		return fail(err)
	}
	return s, nil
}

// Load は、最後に確定した状態と、重複のない全約定を復元します。
//
// 引数: dst any は状態の格納先ポインタです。
// 返り値: []Trade は確定順の全約定、error はDB・JSONの復元失敗です。
func (s *Store) Load(dst any) ([]Trade, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var raw []byte
	err := s.db.QueryRow("SELECT state FROM snapshot WHERE id=1").Scan(&raw)
	if err != nil && err != sql.ErrNoRows {
		return nil, err
	}
	if len(raw) > 0 {
		if err = json.Unmarshal(raw, dst); err != nil {
			return nil, err
		}
	}
	return readTrades(s.db)
}

// Save は、状態・新約定・台帳変化履歴を一つのトランザクションで確定します。
//
// 引数: state any は復元用状態、trades []Trade は従来の確定順を保つ全約定です。
// 返り値: error は保存失敗です。ProjectionErrorだけはDB確定済みを意味します。
func (s *Store) Save(state any, trades []Trade) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	raw, err := json.Marshal(state)
	if err != nil {
		return err
	}
	bodies := make([][]byte, len(trades))
	seen := make(map[string]bool)
	for i, trade := range trades {
		if trade.ID == "" || seen[trade.ID] || !sessionPattern.MatchString(trade.Session) {
			return fmt.Errorf("約定IDの空欄・重複または不正セッションです: %s", trade.ID)
		}
		seen[trade.ID] = true
		if bodies[i], err = json.Marshal(trade); err != nil {
			return err
		}
	}
	tx, err := s.db.BeginTx(context.Background(), nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	old, err := readTrades(tx)
	if err != nil {
		return err
	}
	if len(trades) < len(old) {
		return fmt.Errorf("確定済み約定を消す保存はできません")
	}
	for i, trade := range old {
		body, marshalErr := json.Marshal(trade)
		if marshalErr != nil {
			return marshalErr
		}
		if !bytes.Equal(body, bodies[i]) {
			return fmt.Errorf("確定済み約定の内容または順序が変わっています: %s", trade.ID)
		}
	}
	var previous []byte
	var revision int64
	err = tx.QueryRow("SELECT state,revision FROM snapshot WHERE id=1").Scan(&previous, &revision)
	if err != nil && err != sql.ErrNoRows {
		return err
	}
	now := time.Now()
	if !bytes.Equal(previous, raw) {
		revision++
		if _, err = tx.Exec("INSERT INTO snapshot(id,revision,state,updated_at) VALUES(1,?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,state=excluded.state,updated_at=excluded.updated_at", revision, raw, now.Format(time.RFC3339Nano)); err != nil {
			return err
		}
		payload := map[string]any{"revision": revision, "previous_sha256": digest(previous), "state_sha256": digest(raw), "state": json.RawMessage(raw)}
		if err = insertEvent(tx, "台帳更新", "", "", "", now, payload); err != nil {
			return err
		}
	}
	for i := len(old); i < len(trades); i++ {
		trade := trades[i]
		if _, err = tx.Exec("INSERT INTO trades(id,session,dryrun,body) VALUES(?,?,?,?)", trade.ID, trade.Session, trade.DryRun, bodies[i]); err != nil {
			return err
		}
		if _, err = tx.Exec("INSERT OR IGNORE INTO sessions(session,dryrun) VALUES(?,?)", trade.Session, trade.DryRun); err != nil {
			return err
		}
		if err = insertEvent(tx, "約定確定", trade.Session, trade.Symbol, trade.ClientOrderID, now, trade); err != nil {
			return err
		}
	}
	if err = tx.Commit(); err != nil {
		return err
	}
	if len(old) != len(trades) || s.tradesNeedRebuild {
		if err = s.projectTrades(); err != nil {
			return &ProjectionError{Err: err}
		}
	}
	if err = s.projectTrace(); err != nil {
		return &ProjectionError{Err: err}
	}
	return nil
}

// EnsureSession は、無約定のセッションにもCSVと約定JSONLを用意します。
//
// 引数: session string はAPI由来セッション名、dryRun bool は仮想運転です。
// 返り値: error はDBまたは派生ログの保存失敗です。
func (s *Store) EnsureSession(session string, dryRun bool) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !sessionPattern.MatchString(session) {
		return fmt.Errorf("不正なセッション名です: %s", session)
	}
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	result, err := tx.Exec("INSERT OR IGNORE INTO sessions(session,dryrun) VALUES(?,?)", session, dryRun)
	if err != nil {
		return err
	}
	n, err := result.RowsAffected()
	if err != nil {
		return err
	}
	if n > 0 {
		if err = insertEvent(tx, "セッション記録開始", session, "", "", time.Now(), map[string]any{"dryrun": dryRun}); err != nil {
			return err
		}
	}
	if err = tx.Commit(); err != nil {
		return err
	}
	if err = s.projectTrades(); err != nil {
		return &ProjectionError{Err: err}
	}
	if err = s.projectTrace(); err != nil {
		return &ProjectionError{Err: err}
	}
	return nil
}

// RecordBook は、一受信の原文を重複排除せず保存します。
//
// 引数: session/generation/code string、received time.Time、raw json.RawMessage は受信識別情報と原文です。
// 返り値: int64 はDB入力ID、error は保存失敗です。派生失敗時も確定IDを返します。
func (s *Store) RecordBook(session, generation, code string, received time.Time, raw json.RawMessage) (int64, error) {
	ids, err := s.RecordBooks([]BookRecord{{Session: session, Generation: generation, Code: code, Received: received, Raw: raw}})
	if len(ids) == 0 {
		return 0, err
	}
	return ids[0], err
}

// RecordBooks は、履歴バッチを一つのトランザクションで受信順に保存します。
//
// 引数: records []BookRecord は同値受信も含む原文群です。
// 返り値: []int64 は対応する入力ID、error は保存失敗です。未確定時にはIDを返しません。
func (s *Store) RecordBooks(records []BookRecord) ([]int64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(records) == 0 {
		return []int64{}, nil
	}
	for _, r := range records {
		if !sessionPattern.MatchString(r.Session) || r.Generation == "" || r.Code == "" || r.Received.IsZero() || !json.Valid(r.Raw) {
			return nil, fmt.Errorf("受信原文の識別情報またはJSONが不正です")
		}
	}
	tx, err := s.db.Begin()
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()
	stmt, err := tx.Prepare("INSERT INTO books(session,generation,code,received_at,source,raw) VALUES(?,?,?,?,?,?)")
	if err != nil {
		return nil, err
	}
	defer stmt.Close()
	ids := make([]int64, len(records))
	for i, r := range records {
		result, execErr := stmt.Exec(r.Session, r.Generation, r.Code, r.Received.Format(time.RFC3339Nano), r.Source, []byte(r.Raw))
		if execErr != nil {
			return nil, execErr
		}
		if ids[i], err = result.LastInsertId(); err != nil {
			return nil, err
		}
	}
	if err = insertEvent(tx, "入力原文保存", records[0].Session, records[0].Code, "", time.Now(), map[string]any{"count": len(ids), "first_input_id": ids[0], "last_input_id": ids[len(ids)-1]}); err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	if err = s.projectTrace(); err != nil {
		return ids, &ProjectionError{Err: err}
	}
	return ids, nil
}

// Event は、判断・照合・異常などの汎用履歴を正本とトレースJSONLへ保存します。
//
// 引数: kind/session/code/correlation string、at time.Time、payload any は分類・相関ID・発生時刻・JSON化可能な内容です。
// 返り値: error は保存失敗です。
func (s *Store) Event(kind, session, code, correlation string, at time.Time, payload any) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if kind == "" || at.IsZero() || (session != "" && !sessionPattern.MatchString(session)) {
		return fmt.Errorf("イベント分類・時刻・セッションが不正です")
	}
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	if err = insertEvent(tx, kind, session, code, correlation, at, payload); err != nil {
		return err
	}
	if err = tx.Commit(); err != nil {
		return err
	}
	if err = s.projectTrace(); err != nil {
		return &ProjectionError{Err: err}
	}
	return nil
}

// Close はDB接続を閉じます。正本は各変更の完了時点で確定済みです。
//
// 引数: なし。
// 返り値: error は終了失敗です。複数回の終了は許容します。
func (s *Store) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.closed {
		return nil
	}
	s.closed = true
	return s.db.Close()
}

// queryer はDBとトランザクションの共通読取操作です。
type queryer interface {
	Query(string, ...any) (*sql.Rows, error)
}

// readTrades は確定順に約定を読み込みます。
//
// 引数: q queryer はDBまたはトランザクションです。
// 返り値: []Trade は約定列、error は読取失敗です。
func readTrades(q queryer) ([]Trade, error) {
	rows, err := q.Query("SELECT body FROM trades ORDER BY seq")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []Trade{}
	for rows.Next() {
		var raw []byte
		if err = rows.Scan(&raw); err != nil {
			return nil, err
		}
		var trade Trade
		if err = json.Unmarshal(raw, &trade); err != nil {
			return nil, err
		}
		out = append(out, trade)
	}
	return out, rows.Err()
}

// insertEvent は同じトランザクションへ履歴を挿入します。
//
// 引数: tx *sql.Tx、kind/session/code/correlation string、at time.Time、payload any。
// 返り値: error はJSON化・挿入失敗です。
func insertEvent(tx *sql.Tx, kind, session, code, correlation string, at time.Time, payload any) error {
	raw, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	_, err = tx.Exec("INSERT INTO events(kind,session,code,correlation,at,payload) VALUES(?,?,?,?,?,?)", kind, session, code, correlation, at.Format(time.RFC3339Nano), raw)
	return err
}

// digest は状態変更の前後を照合する指紋を返します。
//
// 引数: raw []byte は状態JSONです。
// 返り値: string はSHA256の16進表現です。
func digest(raw []byte) string {
	value := sha256.Sum256(raw)
	return hex.EncodeToString(value[:])
}
