package journal

import (
	"bufio"
	"bytes"
	"encoding/csv"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

// testStore は各試験専用のSQLiteと派生ログを作ります。
//
// 引数: t *testing.T は試験です。
// 返り値: *Store、string、string は保存器・DBパス・ログディレクトリです。
func testStore(t *testing.T) (*Store, string, string) {
	t.Helper()
	dir := t.TempDir()
	path, logs := filepath.Join(dir, "state.sqlite"), filepath.Join(dir, "log")
	s, err := Open(path, logs)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = s.Close() })
	return s, path, logs
}

// testTrade は所有担当と判断根拠を持つ仮想約定を返します。
//
// 引数: id string は約定IDです。
// 返り値: Trade は試験用の一約定です。
func testTrade(id string) Trade {
	return Trade{ID: id, At: time.Date(2026, 10, 21, 9, 0, 0, 0, time.FixedZone("JST", 9*3600)),
		Session: "2026-10-21_Day", Symbol: "TOPIXmini", Product: "TOPIXmini", Owner: "core",
		TradeType: "new", Side: "buy", Quantity: 5, Price: 4000.5, DryRun: true,
		Reason: "理由,改行\nあり", Evidence: json.RawMessage(`{"input_id":10,"peer_input_id":9}`),
		ClientOrderID: "intent-1", BrokerOrderID: "order-1", ExecutionID: id}
}

// scalar は試験用SQLの一整数結果を取得します。
//
// 引数: t *testing.T、s *Store、query string は試験・保存器・読取SQLです。
// 返り値: int は整数結果です。
func scalar(t *testing.T, s *Store, query string) int {
	t.Helper()
	var n int
	if err := s.db.QueryRow(query).Scan(&n); err != nil {
		t.Fatal(err)
	}
	return n
}

// traces はJSONLを一行ずつ解析し、連番と改行終端を確認します。
//
// 引数: t *testing.T、path string は試験とトレースパスです。
// 返り値: []traceRecord は復元した履歴です。
func traces(t *testing.T, path string) []traceRecord {
	t.Helper()
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if len(raw) > 0 && raw[len(raw)-1] != '\n' {
		t.Fatal("JSONL末尾に改行がありません")
	}
	var out []traceRecord
	scanner := bufio.NewScanner(bytes.NewReader(raw))
	scanner.Buffer(make([]byte, 4096), 1024*1024)
	for scanner.Scan() {
		var row traceRecord
		if err = json.Unmarshal(scanner.Bytes(), &row); err != nil {
			t.Fatal(err)
		}
		if row.Sequence != int64(len(out)+1) {
			t.Fatal("イベントの連番が不正です")
		}
		out = append(out, row)
	}
	if err = scanner.Err(); err != nil {
		t.Fatal(err)
	}
	return out
}

// TestSaveReopenAndProjection は再保存・CSV引用符・破損した派生物の復元を確認します。
//
// 引数: t *testing.T は試験です。
// 返り値: なし。
func TestSaveReopenAndProjection(t *testing.T) {
	s, path, logs := testStore(t)
	if scalar(t, s, "PRAGMA synchronous") != 2 {
		t.Fatal("FULL同期ではありません")
	}
	var mode string
	if err := s.db.QueryRow("PRAGMA journal_mode").Scan(&mode); err != nil || mode != "wal" {
		t.Fatal("WALではありません", err)
	}
	if err := s.EnsureSession("2026-10-21_Day", true); err != nil {
		t.Fatal(err)
	}
	state := map[string]any{"status": "sending", "intent": "intent-1"}
	trade := testTrade("fill-1")
	if err := s.Save(state, []Trade{trade}); err != nil {
		t.Fatal(err)
	}
	count := scalar(t, s, "SELECT count(*) FROM events")
	if err := s.Save(state, []Trade{trade}); err != nil {
		t.Fatal(err)
	}
	if scalar(t, s, "SELECT count(*) FROM events") != count || scalar(t, s, "SELECT count(*) FROM trades") != 1 {
		t.Fatal("同一Saveが履歴または約定を増やしました")
	}
	csvPath := filepath.Join(logs, "2026-10-21_Day_dryrun.csv")
	raw, err := os.ReadFile(csvPath)
	if err != nil {
		t.Fatal(err)
	}
	rows, err := csv.NewReader(bytes.NewReader(raw)).ReadAll()
	if err != nil || len(rows) != 2 || rows[1][9] != trade.Reason || rows[1][15] != "core" || rows[1][17] != string(trade.Evidence) {
		t.Fatal("CSVの値・引用符・追加列が不正です", err)
	}
	if err = s.Close(); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"2026-10-21_Day_dryrun.csv", "2026-10-21_Day_dryrun.jsonl", "trace.jsonl"} {
		if err = os.WriteFile(filepath.Join(logs, name), []byte("途中で切れた記録"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	restored, err := Open(path, logs)
	if err != nil {
		t.Fatal(err)
	}
	defer restored.Close()
	var loaded map[string]any
	fills, err := restored.Load(&loaded)
	if err != nil || len(fills) != 1 || loaded["status"] != "sending" || fills[0].Owner != "core" {
		t.Fatal("正本からの復元失敗", err)
	}
	if len(traces(t, filepath.Join(logs, "trace.jsonl"))) != count {
		t.Fatal("履歴の復元件数が異なります")
	}
	after, err := os.ReadFile(csvPath)
	if err != nil || !bytes.Equal(raw, after) {
		t.Fatal("CSVが正本どおり復元されませんでした", err)
	}
}

// TestAtomicRollbackAndDuplicate は状態・約定・履歴が同時に確定することを確認します。
//
// 引数: t *testing.T は試験です。
// 返り値: なし。
func TestAtomicRollbackAndDuplicate(t *testing.T) {
	s, _, _ := testStore(t)
	before := map[string]int{"stage": 1}
	if err := s.Save(before, nil); err != nil {
		t.Fatal(err)
	}
	if _, err := s.db.Exec("CREATE TRIGGER fail_trade BEFORE INSERT ON trades WHEN NEW.id='fail' BEGIN SELECT RAISE(ABORT,'試験中断'); END"); err != nil {
		t.Fatal(err)
	}
	if err := s.Save(map[string]int{"stage": 2}, []Trade{testTrade("ok"), testTrade("fail")}); err == nil {
		t.Fatal("挿入中断を検出しませんでした")
	}
	var loaded map[string]int
	fills, err := s.Load(&loaded)
	if err != nil || loaded["stage"] != 1 || len(fills) != 0 || scalar(t, s, "SELECT count(*) FROM events") != 1 {
		t.Fatal("状態・約定・履歴の一部が先走りました", err)
	}
	trade := testTrade("fill-1")
	if err = s.Save(before, []Trade{trade}); err != nil {
		t.Fatal(err)
	}
	conflict := trade
	conflict.Quantity = 4
	for _, items := range [][]Trade{nil, {conflict}, {trade, trade}} {
		if err = s.Save(map[string]int{"stage": 9}, items); err == nil {
			t.Fatal("確定済み約定の消失・変更・重複を許しました")
		}
	}
	fills, err = s.Load(&loaded)
	if err != nil || loaded["stage"] != 1 || len(fills) != 1 || fills[0].Quantity != 5 {
		t.Fatal("拒否後の正本が変化しました", err)
	}
}

// TestCommittedProjectionFailure はログ失敗後もDB確定を保ち再起動で修復することを確認します。
//
// 引数: t *testing.T は試験です。
// 返り値: なし。
func TestCommittedProjectionFailure(t *testing.T) {
	s, path, logs := testStore(t)
	block := filepath.Join(logs, "2026-10-21_Day_dryrun.csv")
	if err := os.Mkdir(block, 0700); err != nil {
		t.Fatal(err)
	}
	err := s.Save(map[string]int{"stage": 2}, []Trade{testTrade("fill-1")})
	var projection *ProjectionError
	if !errors.As(err, &projection) {
		t.Fatal("正本確定後の失敗を区別しませんでした", err)
	}
	var state map[string]int
	fills, err := s.Load(&state)
	if err != nil || state["stage"] != 2 || len(fills) != 1 {
		t.Fatal("確定済み正本を失いました", err)
	}
	if err = os.Remove(block); err != nil {
		t.Fatal(err)
	}
	if err = s.Save(map[string]int{"stage": 2}, []Trade{testTrade("fill-1")}); err != nil {
		t.Fatal("同じ確定内容の再保存で派生物を修復できません", err)
	}
	if _, err = os.Stat(block); err != nil {
		t.Fatal("同一保存の再試行でCSVが復元されません", err)
	}
	_ = s.Close()
	restored, err := Open(path, logs)
	if err != nil {
		t.Fatal(err)
	}
	defer restored.Close()
	if len(traces(t, filepath.Join(logs, "trace.jsonl"))) != 2 {
		t.Fatal("確定済みイベントを修復できませんでした")
	}
	if scalar(t, restored, "SELECT count(*) FROM trades") != 1 {
		t.Fatal("修復時に重複約定を作りました")
	}
}

// TestBookBatchAndEvent は同原文の別受信・原文保持・バッチ原子性を確認します。
//
// 引数: t *testing.T は試験です。
// 返り値: なし。
func TestBookBatchAndEvent(t *testing.T) {
	s, _, logs := testStore(t)
	raw := json.RawMessage(" { \"CurrentPrice\" : 4000.5 } ")
	record := BookRecord{Session: "2026-10-21_Day", Generation: "g1", Code: "TOPIX",
		Received: time.Now(), Source: "履歴", Raw: raw}
	ids, err := s.RecordBooks([]BookRecord{record, record})
	if err != nil || len(ids) != 2 || ids[1] != ids[0]+1 {
		t.Fatal("同値原文の受信を消しました", err)
	}
	var restored []byte
	if err = s.db.QueryRow("SELECT raw FROM books WHERE id=?", ids[0]).Scan(&restored); err != nil || !bytes.Equal(raw, restored) {
		t.Fatal("原文を変更しました", err)
	}
	if _, err = s.db.Exec("CREATE TRIGGER fail_book BEFORE INSERT ON books WHEN NEW.code='BAD' BEGIN SELECT RAISE(ABORT,'試験中断'); END"); err != nil {
		t.Fatal(err)
	}
	bad := record
	bad.Code = "BAD"
	if ids, err = s.RecordBooks([]BookRecord{record, bad}); err == nil || len(ids) != 0 {
		t.Fatal("未確定の入力IDを返しました")
	}
	if scalar(t, s, "SELECT count(*) FROM books") != 2 || scalar(t, s, "SELECT count(*) FROM events") != 1 {
		t.Fatal("失敗バッチの一部を確定しました")
	}
	if err = s.Event("入口見送り", record.Session, record.Code, "decision-1", time.Now(), map[string]any{"input_id": 2, "reason": "相手市場の逆行"}); err != nil {
		t.Fatal(err)
	}
	history := traces(t, filepath.Join(logs, "trace.jsonl"))
	if len(history) != 2 || history[1].Kind != "入口見送り" || history[1].Correlation != "decision-1" {
		t.Fatal("イベントを追跡できません")
	}
	record.Raw = json.RawMessage(`{"途中":`)
	if _, err = s.RecordBooks([]BookRecord{record}); err == nil {
		t.Fatal("壊れた原文を受理しました")
	}
	if err = s.Event("不正内容", "", "", "", time.Now(), make(chan int)); err == nil {
		t.Fatal("JSON化できないイベントを受理しました")
	}
	if scalar(t, s, "SELECT count(*) FROM events") != 2 {
		t.Fatal("不正イベントが履歴に残りました")
	}
}

// TestTraceFailureRebuild はトレースの書出し失敗後に確定イベントを重複なく再構成します。
//
// 引数: t *testing.T は試験です。
// 返り値: なし。
func TestTraceFailureRebuild(t *testing.T) {
	s, _, logs := testStore(t)
	tracePath := filepath.Join(logs, "trace.jsonl")
	if err := os.Remove(tracePath); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(tracePath, 0700); err != nil {
		t.Fatal(err)
	}
	err := s.Event("送信前確定", "", "", "intent-1", time.Now(), map[string]int{"attempt": 1})
	var projection *ProjectionError
	if !errors.As(err, &projection) || scalar(t, s, "SELECT count(*) FROM events") != 1 {
		t.Fatal("トレース失敗時の確定範囲が不正です", err)
	}
	if err = os.Remove(tracePath); err != nil {
		t.Fatal(err)
	}
	if err = s.Event("照合待ち", "", "", "intent-1", time.Now(), nil); err != nil {
		t.Fatal(err)
	}
	history := traces(t, tracePath)
	if len(history) != 2 || history[0].Kind != "送信前確定" || history[1].Kind != "照合待ち" {
		t.Fatal("履歴の修復で欠落または重複しました")
	}
}

// TestConcurrentRecords は同時受信でも入力ID・履歴順が衝突しないことを確認します。
//
// 引数: t *testing.T は試験です。
// 返り値: なし。
func TestConcurrentRecords(t *testing.T) {
	s, _, logs := testStore(t)
	var wg sync.WaitGroup
	errs := make(chan error, 20)
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, err := s.RecordBook("2026-10-21_Day", "g1", "NK225", time.Now(), json.RawMessage(`{"CurrentPrice":65000}`))
			errs <- err
		}()
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		if err != nil {
			t.Fatal(err)
		}
	}
	if scalar(t, s, "SELECT count(*) FROM books") != 20 || len(traces(t, filepath.Join(logs, "trace.jsonl"))) != 20 {
		t.Fatal("同時受信で欠落しました")
	}
}

// TestCrashCommittedState はCloseなしのプロセス終了後も送信途中状態を復元します。
//
// 引数: t *testing.T は試験です。
// 返り値: なし。
func TestCrashCommittedState(t *testing.T) {
	dir := t.TempDir()
	command := exec.Command(os.Args[0], "-test.run=^TestCrashHelper$")
	command.Env = append(os.Environ(), "SESSIONTRADER_JOURNAL_CRASH="+dir)
	err := command.Run()
	var exit *exec.ExitError
	if !errors.As(err, &exit) || exit.ExitCode() != 23 {
		t.Fatal("意図した中断ではありません", err)
	}
	s, err := Open(filepath.Join(dir, "state.sqlite"), filepath.Join(dir, "log"))
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	var state map[string]string
	fills, err := s.Load(&state)
	if err != nil || state["status"] != "sending" || state["intent"] != "fixed-intent" || len(fills) != 0 {
		t.Fatal("送信途中の意図を復元できません", err)
	}
}

// TestCrashHelper は別プロセス内で確定直後に終了する試験専用入口です。
//
// 引数: t *testing.T は試験です。
// 返り値: なし。専用環境変数がなければ実行しません。
func TestCrashHelper(t *testing.T) {
	dir := os.Getenv("SESSIONTRADER_JOURNAL_CRASH")
	if dir == "" {
		return
	}
	s, err := Open(filepath.Join(dir, "state.sqlite"), filepath.Join(dir, "log"))
	if err != nil {
		t.Fatal(err)
	}
	if err = s.Save(map[string]string{"status": "sending", "intent": "fixed-intent"}, nil); err != nil {
		t.Fatal(err)
	}
	os.Exit(23)
}

// TestInvalidSessionAndVersion は不正パスおよび未来形式のDBを拒否することを確認します。
//
// 引数: t *testing.T は試験です。
// 返り値: なし。
func TestInvalidSessionAndVersion(t *testing.T) {
	s, path, logs := testStore(t)
	if err := s.EnsureSession("../escape", false); err == nil {
		t.Fatal("ログ保存先からの逸脱を許しました")
	}
	if _, err := s.db.Exec("PRAGMA user_version=99"); err != nil {
		t.Fatal(err)
	}
	_ = s.Close()
	_, err := Open(path, logs)
	if err == nil || !strings.Contains(err.Error(), "未対応") {
		t.Fatal("未知形式を開きました", err)
	}
}
