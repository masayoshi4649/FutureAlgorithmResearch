package journal

import (
	"bufio"
	"bytes"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"time"
)

// traceRecord は連番で正本へ対応する一件の判断・台帳変化履歴です。
type traceRecord struct {
	Sequence    int64           `json:"seq"`
	Kind        string          `json:"kind"`
	Session     string          `json:"session"`
	Code        string          `json:"code"`
	Correlation string          `json:"correlation"`
	At          string          `json:"at"`
	Payload     json.RawMessage `json:"payload"`
}

// projectTrades はSQLiteからセッションCSVと約定JSONLを原子的に再構成します。
//
// 引数: なし。呼出元がStoreの排他を保有します。
// 返り値: error は派生ログの生成・置換失敗です。
func (s *Store) projectTrades() (err error) {
	defer func() { s.tradesNeedRebuild = err != nil }()
	groups := make(map[string][]Trade)
	rows, err := s.db.Query("SELECT session,dryrun FROM sessions ORDER BY session,dryrun")
	if err != nil {
		return err
	}
	for rows.Next() {
		var session string
		var dry bool
		if err = rows.Scan(&session, &dry); err != nil {
			_ = rows.Close()
			return err
		}
		if !sessionPattern.MatchString(session) {
			_ = rows.Close()
			return fmt.Errorf("DBに不正なセッション名があります")
		}
		groups[sessionName(session, dry)] = nil
	}
	err = rows.Err()
	_ = rows.Close()
	if err != nil {
		return err
	}
	trades, err := readTrades(s.db)
	if err != nil {
		return err
	}
	for _, trade := range trades {
		if !sessionPattern.MatchString(trade.Session) {
			return fmt.Errorf("DBに不正な約定セッションがあります")
		}
		name := sessionName(trade.Session, trade.DryRun)
		groups[name] = append(groups[name], trade)
	}
	names := make([]string, 0, len(groups))
	for name := range groups {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		var table, lines bytes.Buffer
		w := csv.NewWriter(&table)
		if err = w.Write([]string{"記録ID", "約定確認時刻", "セッション", "銘柄", "区分", "売買", "枚数", "約定価格", "実現損益円", "理由", "発注意図ID", "予約ID", "上流注文ID", "約定ID", "仮想実行", "担当", "商品", "判断根拠JSON", "標準手数料円", "新規建玉ID", "返済建玉内訳JSON", "返済内訳の根拠"}); err != nil {
			return err
		}
		encoder := json.NewEncoder(&lines)
		encoder.SetEscapeHTML(false)
		for _, trade := range groups[name] {
			kind, side := "新規", "買い"
			if trade.TradeType == "close" {
				kind = "返済"
			}
			if trade.Side == "sell" {
				side = "売り"
			}
			closed := ""
			if len(trade.Closed) > 0 {
				encoded, encodeErr := json.Marshal(trade.Closed)
				if encodeErr != nil {
					return encodeErr
				}
				closed = string(encoded)
			}
			if err = w.Write([]string{trade.ID, trade.At.Format(time.RFC3339Nano), trade.Session, trade.Symbol,
				kind, side, strconv.Itoa(trade.Quantity), strconv.FormatFloat(trade.Price, 'f', -1, 64),
				strconv.FormatFloat(trade.PnL, 'f', -1, 64), trade.Reason, trade.ClientOrderID,
				trade.ReservationID, trade.BrokerOrderID, trade.ExecutionID, strconv.FormatBool(trade.DryRun),
				trade.Owner, trade.Product, string(trade.Evidence), strconv.FormatFloat(trade.Fee, 'f', -1, 64), trade.HoldID, closed, trade.ClosedBasis}); err != nil {
				return err
			}
			if err = encoder.Encode(trade); err != nil {
				return err
			}
		}
		w.Flush()
		if err = w.Error(); err != nil {
			return err
		}
		if err = atomicWrite(filepath.Join(s.logDir, name+".csv"), table.Bytes()); err != nil {
			return err
		}
		if err = atomicWrite(filepath.Join(s.logDir, name+".jsonl"), lines.Bytes()); err != nil {
			return err
		}
	}
	return nil
}

// projectTrace は確定イベントを追記し、起動時または前回失敗後は全件再構成します。
//
// 引数: なし。呼出元がStoreの排他を保有します。
// 返り値: error は読み込み・ログ同期失敗です。失敗後の次回は先頭から修復します。
func (s *Store) projectTrace() (err error) {
	defer func() {
		if err != nil {
			s.traceNeedsRebuild = true
		}
	}()
	if err = os.MkdirAll(s.logDir, 0700); err != nil {
		return err
	}
	target := filepath.Join(s.logDir, "trace.jsonl")
	if _, statErr := os.Stat(target); os.IsNotExist(statErr) {
		s.traceNeedsRebuild = true
	} else if statErr != nil {
		return statErr
	}
	start := s.traceSequence
	if s.traceNeedsRebuild {
		start = 0
	}
	rows, err := s.db.Query("SELECT seq,kind,session,code,correlation,at,payload FROM events WHERE seq>? ORDER BY seq", start)
	if err != nil {
		return err
	}
	defer rows.Close()
	var f *os.File
	if s.traceNeedsRebuild {
		f, err = os.CreateTemp(s.logDir, ".trace-*")
	} else {
		f, err = os.OpenFile(target, os.O_WRONLY|os.O_APPEND, 0600)
	}
	if err != nil {
		return err
	}
	tempName := f.Name()
	defer func() {
		_ = f.Close()
		if tempName != target {
			_ = os.Remove(tempName)
		}
	}()
	w := bufio.NewWriter(f)
	encoder := json.NewEncoder(w)
	encoder.SetEscapeHTML(false)
	last := start
	for rows.Next() {
		var event traceRecord
		if err = rows.Scan(&event.Sequence, &event.Kind, &event.Session, &event.Code, &event.Correlation, &event.At, &event.Payload); err != nil {
			return err
		}
		if err = encoder.Encode(event); err != nil {
			return err
		}
		last = event.Sequence
	}
	if err = rows.Err(); err != nil {
		return err
	}
	if err = w.Flush(); err != nil {
		return err
	}
	if err = f.Sync(); err != nil {
		return err
	}
	if err = f.Close(); err != nil {
		return err
	}
	if s.traceNeedsRebuild {
		if err = os.Rename(tempName, target); err != nil {
			return err
		}
	}
	s.traceSequence = last
	s.traceNeedsRebuild = false
	return nil
}

// sessionName は、実運転と仮想運転を区別したファイルの基底名を返します。
//
// 引数: session string は検証済みセッション名、dryRun bool は仮想運転です。
// 返り値: string は拡張子を含まないファイル名です。
func sessionName(session string, dryRun bool) string {
	if dryRun {
		return session + "_dryrun"
	}
	return session
}

// atomicWrite は同一ディレクトリの一時ファイルを同期後に置換します。
//
// 引数: path string は派生ファイル、data []byte は内容です。
// 返り値: error は作成・同期・置換失敗です。正本SQLiteは変更しません。
func atomicWrite(path string, data []byte) error {
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".sessiontrader-*")
	if err != nil {
		return err
	}
	name := f.Name()
	defer os.Remove(name)
	if _, err = f.Write(data); err != nil {
		_ = f.Close()
		return err
	}
	if err = f.Sync(); err != nil {
		_ = f.Close()
		return err
	}
	if err = f.Close(); err != nil {
		return err
	}
	return os.Rename(name, path)
}
