package journal

import (
	"bytes"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// TestCompactPayloadKeepsDecisions は発注根拠と約定を丸ごと残し、資料の省略を明示することを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestCompactPayloadKeepsDecisions(t *testing.T) {
	large, err := json.Marshal(map[string]any{"count": 3, "state": map[string]string{"保有": strings.Repeat("保持", 100000)}, "raw": map[string]int{"価格": 65000}, "reason": "利益を伸ばす"})
	if err != nil {
		t.Fatal(err)
	}
	for _, kind := range []string{"発注判断", "約定確定"} {
		got, err := CompactPayload(kind, large)
		if err != nil || !bytes.Equal(got, large) {
			t.Fatal("売買の判断根拠を省略しました", kind, err)
		}
	}
	got, err := CompactPayload("台帳更新", large)
	if err != nil || len(got) >= len(large)/100 {
		t.Fatal("巨大状態を十分に軽量化できません", len(got), err)
	}
	var fields map[string]json.RawMessage
	if err = json.Unmarshal(got, &fields); err != nil || string(fields["reason"]) != `"利益を伸ばす"` || string(fields["count"]) != "3" || !alreadyOmitted(fields["state"]) || !alreadyOmitted(fields["raw"]) || len(fields["_trace_compaction"]) == 0 {
		t.Fatal("省略と判断の区別が不正です", string(got), err)
	}
	second, err := CompactPayload("台帳更新", got)
	if err != nil || !bytes.Equal(got, second) {
		t.Fatal("二重適用が元資料の指紋を変えました", err)
	}
	for _, bad := range []json.RawMessage{nil, []byte(`{"壊れた":`)} {
		if _, err = CompactPayload("台帳更新", bad); err == nil {
			t.Fatal("不正JSONを受理しました")
		}
	}
	for _, raw := range []json.RawMessage{[]byte("null"), []byte("true"), []byte("13.5"), []byte(`"短い記録"`)} {
		got, err = CompactPayload("補助", raw)
		if err != nil || !bytes.Equal(raw, got) {
			t.Fatal("短い値を変更しました", err)
		}
	}
}

// TestCompactArchiveRuntimeDoesNotExpand は起動切替の旧runtimeを派生traceへ巨大複製しないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestCompactArchiveRuntimeDoesNotExpand(t *testing.T) {
	runtime := map[string]string{"履歴": strings.Repeat("旧runtime全量", 100000)}
	raw, err := json.Marshal(map[string]any{"previous_state": map[string]any{"runtime_state": runtime}, "metadata": map[string]any{"reason": "新しい運転", "previous_runtime": runtime}})
	if err != nil {
		t.Fatal(err)
	}
	compact, err := CompactPayload("起動時状態切替", raw)
	if err != nil || len(compact) > 4096 || bytes.Contains(compact, []byte("旧runtime全量")) {
		t.Fatal("起動切替のruntimeを派生へ再展開しました", len(compact), err)
	}
	var fields map[string]json.RawMessage
	if err = json.Unmarshal(compact, &fields); err != nil || !alreadyOmitted(fields["previous_state"]) || !alreadyOmitted(fields["metadata"]) {
		t.Fatal("切替資料の省略を識別できません", err)
	}
}

// TestCompactSnapshotAndLegacyRebuild は旧全量イベントの正本を保ったまま派生物を小さく再作成します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestCompactSnapshotAndLegacyRebuild(t *testing.T) {
	s, path, logs := testStore(t)
	state := map[string]any{"runtime": strings.Repeat("全量復元用", 100000), "保有": 2}
	trade := testTrade("大きな状態の約定")
	if err := s.Save(state, []Trade{trade}); err != nil {
		t.Fatal(err)
	}
	var payload []byte
	if err := s.db.QueryRow("SELECT payload FROM events WHERE kind='台帳更新'").Scan(&payload); err != nil || len(payload) > 1024 || bytes.Contains(payload, []byte(`"state":`)) {
		t.Fatal("新しい台帳更新イベントに全状態が複製されています", len(payload), err)
	}
	oldPayload := map[string]any{"revision": 1, "state": state, "state_sha256": "旧版の監査"}
	if err := s.Event("台帳更新", "", "", "", time.Now(), oldPayload); err != nil {
		t.Fatal(err)
	}
	var oldState, oldEvent []byte
	if err := s.db.QueryRow("SELECT state FROM snapshot").Scan(&oldState); err != nil {
		t.Fatal(err)
	}
	if err := s.db.QueryRow("SELECT payload FROM events ORDER BY seq DESC LIMIT 1").Scan(&oldEvent); err != nil {
		t.Fatal(err)
	}
	var csvBefore []byte
	csvBefore, err := os.ReadFile(filepath.Join(logs, "2026-10-21_Day_dryrun.csv"))
	if err != nil {
		t.Fatal(err)
	}
	if err = s.Close(); err != nil {
		t.Fatal(err)
	}
	// 旧版の巨大な派生ファイルが既に存在しても、正本の要約から再構築する。
	if err = os.WriteFile(filepath.Join(logs, "trace.jsonl"), oldEvent, 0600); err != nil {
		t.Fatal(err)
	}
	restored, err := Open(path, logs)
	if err != nil {
		t.Fatal(err)
	}
	defer restored.Close()
	var afterState, afterEvent []byte
	if err = restored.db.QueryRow("SELECT state FROM snapshot").Scan(&afterState); err != nil {
		t.Fatal(err)
	}
	if err = restored.db.QueryRow("SELECT payload FROM events ORDER BY seq DESC LIMIT 1").Scan(&afterEvent); err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(oldState, afterState) || !bytes.Equal(oldEvent, afterEvent) {
		t.Fatal("旧状態または旧監査の正本を書き換えました")
	}
	afterCSV, err := os.ReadFile(filepath.Join(logs, "2026-10-21_Day_dryrun.csv"))
	if err != nil || !bytes.Equal(csvBefore, afterCSV) {
		t.Fatal("約定CSVを変更しました", err)
	}
	info, err := os.Stat(filepath.Join(logs, "trace.jsonl"))
	if err != nil || info.Size() >= int64(len(oldEvent))/100 {
		t.Fatal("旧巨大traceが軽量化されません", err)
	}
	var loaded map[string]any
	fills, err := restored.Load(&loaded)
	wantedFills, _ := json.Marshal([]Trade{trade})
	actualFills, _ := json.Marshal(fills)
	if err != nil || loaded["runtime"] != state["runtime"] || loaded["保有"] != float64(2) || !bytes.Equal(wantedFills, actualFills) {
		t.Fatal("軽量化で復元情報が変化しました", err)
	}
	if len(traces(t, filepath.Join(logs, "trace.jsonl"))) != 3 {
		t.Fatal("重要イベントが消失しました")
	}
}

// TestArchiveAndSaveAtomic は運転切替の監査と新状態が同時確定し、旧約定が不変なことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestArchiveAndSaveAtomic(t *testing.T) {
	s, path, logs := testStore(t)
	previous := map[string]any{"run": "旧運転", "holdings": 2}
	trades := []Trade{testTrade("旧約定")}
	if err := s.Save(previous, trades); err != nil {
		t.Fatal(err)
	}
	var before []byte
	if err := s.db.QueryRow("SELECT state FROM snapshot").Scan(&before); err != nil {
		t.Fatal(err)
	}
	if _, err := s.db.Exec("CREATE TRIGGER fail_transition BEFORE UPDATE ON snapshot BEGIN SELECT RAISE(ABORT,'切替中断'); END"); err != nil {
		t.Fatal(err)
	}
	next := map[string]any{"run": "新運転", "holdings": 0}
	if err := s.ArchiveAndSave(next, trades, map[string]string{"reason": "起動"}); err == nil {
		t.Fatal("失敗した状態切替を受理しました")
	}
	if scalar(t, s, "SELECT count(*) FROM events WHERE kind='起動時状態切替'") != 0 {
		t.Fatal("失敗した切替の監査だけが確定しました")
	}
	var after []byte
	if err := s.db.QueryRow("SELECT state FROM snapshot").Scan(&after); err != nil || !bytes.Equal(before, after) {
		t.Fatal("切替中断で旧状態を失いました", err)
	}
	if _, err := s.db.Exec("DROP TRIGGER fail_transition"); err != nil {
		t.Fatal(err)
	}
	if err := s.ArchiveAndSave(next, nil, nil); err == nil {
		t.Fatal("切替で過去約定を削除できました")
	}
	if err := s.ArchiveAndSave(next, trades, map[string]string{"reason": "起動"}); err != nil {
		t.Fatal(err)
	}
	var payload []byte
	if err := s.db.QueryRow("SELECT payload FROM events WHERE kind='起動時状態切替'").Scan(&payload); err != nil {
		t.Fatal(err)
	}
	var archive map[string]json.RawMessage
	if err := json.Unmarshal(payload, &archive); err != nil || !bytes.Equal(archive["previous_state"], before) {
		t.Fatal("旧状態が監査へ保存されていません", err)
	}
	_ = s.Close()
	restored, err := Open(path, logs)
	if err != nil {
		t.Fatal(err)
	}
	defer restored.Close()
	var loaded map[string]any
	fills, err := restored.Load(&loaded)
	wantedFills, _ := json.Marshal(trades)
	actualFills, _ := json.Marshal(fills)
	if err != nil || loaded["run"] != "新運転" || !bytes.Equal(wantedFills, actualFills) {
		t.Fatal("再起動で切替先状態または約定が変わりました", err)
	}
	for _, event := range traces(t, filepath.Join(logs, "trace.jsonl")) {
		if event.Kind == "起動時状態切替" {
			if err = json.Unmarshal(event.Payload, &archive); err != nil || !alreadyOmitted(archive["previous_state"]) {
				t.Fatal("監査の全状態を派生traceへ複製しました", err)
			}
		}
	}
}

// rowDigest はBLOB原文を行順に読み、正本の変更を検出する指紋を返します。
//
// 引数: t(*testing.T)、s(*Store)、query(string)は単一BLOB列の読取SQLです。
// 返り値: stringはSHA256、int64は全BLOBの合計バイト数です。
func rowDigest(t *testing.T, s *Store, query string) (string, int64) {
	t.Helper()
	rows, err := s.db.Query(query)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	hash, size := sha256.New(), int64(0)
	for rows.Next() {
		var body []byte
		if err = rows.Scan(&body); err != nil {
			t.Fatal(err)
		}
		_, _ = hash.Write(body)
		_, _ = hash.Write([]byte{0})
		size += int64(len(body))
	}
	if err = rows.Err(); err != nil {
		t.Fatal(err)
	}
	return hex.EncodeToString(hash.Sum(nil)), size
}

// TestLegacyFixtureCompact は作業用コピーの旧DBで軽量化率と正本不変を確認します。
//
// 引数: t(*testing.T)。環境変数SESSIONTRADER_COMPACT_FIXTUREは旧DBの作業用コピーです。
// 返り値: なし。原DBは指定せず、専用コピーのみ対象にします。
func TestLegacyFixtureCompact(t *testing.T) {
	path := os.Getenv("SESSIONTRADER_COMPACT_FIXTURE")
	if path == "" {
		t.Skip("旧DBの作業コピー指定なし")
	}
	// 通常Openの初回復元より前に原本の指紋を測る。
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	baseline := &Store{db: db}
	before := map[string]string{}
	queries := map[string]string{"snapshot": "SELECT state FROM snapshot ORDER BY id", "trades": "SELECT body FROM trades ORDER BY seq", "books": "SELECT raw FROM books ORDER BY id", "events": "SELECT payload FROM events ORDER BY seq"}
	var oldBytes int64
	for table, query := range queries {
		fingerprint, size := rowDigest(t, baseline, query)
		before[table] = fingerprint
		if table == "events" {
			oldBytes = size
		}
	}
	if err = db.Close(); err != nil {
		t.Fatal(err)
	}
	// Openは既存行を書換えず、派生物だけを一時領域へ作る。
	s, err := Open(path, t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	first, err := os.Stat(filepath.Join(s.logDir, "trace.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	if err = s.Close(); err != nil {
		t.Fatal(err)
	}
	secondDir := t.TempDir()
	s, err = Open(path, secondDir)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	for table, query := range queries {
		fingerprint, _ := rowDigest(t, s, query)
		if fingerprint != before[table] {
			t.Fatal("正本変更", table)
		}
	}
	second, err := os.Stat(filepath.Join(secondDir, "trace.jsonl"))
	if err != nil || second.Size() != first.Size() {
		t.Fatal("再構築が非決定的です", err)
	}
	t.Logf("旧DB %s: 元events payload=%d bytes、軽量trace=%d bytes、4正本のSHA256不変", filepath.Base(path), oldBytes, first.Size())
}
