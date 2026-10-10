// Package journal は、復元用の正本とセッション別の約定CSVを保存します。
package journal

import (
	"bytes"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"time"
)

// Trade は、受付とは区別した実約定または仮想約定の記録です。
type Trade struct {
	ID            string    `json:"id"`
	At            time.Time `json:"at"`
	Session       string    `json:"session"`
	Symbol        string    `json:"symbol"`
	TradeType     string    `json:"trade_type"`
	Side          string    `json:"side"`
	Quantity      int       `json:"quantity"`
	Price         float64   `json:"price"`
	PnL           float64   `json:"pnl"`
	Reason        string    `json:"reason"`
	ClientOrderID string    `json:"client_order_id"`
	ReservationID string    `json:"reservation_id"`
	BrokerOrderID string    `json:"broker_order_id"`
	ExecutionID   string    `json:"execution_id"`
	DryRun        bool      `json:"dryrun"`
}

// envelope は、状態とCSVの元データを同一ファイルで確定する単位です。
type envelope struct {
	Version  int             `json:"version"`
	State    json.RawMessage `json:"state"`
	Trades   []Trade         `json:"trades"`
	Sessions []string        `json:"sessions"`
}

// Store は、呼出元の単一実行ループから利用する永続ストアです。
type Store struct {
	path, logDir string
	data         envelope
}

// ProjectionError は、正本は確定済みでCSVだけが未反映の保存失敗です。
type ProjectionError struct{ Err error }

// Error は、確定済み正本を巻き戻してはいけない保存状態を説明します。
//
// 引数: なし。
// 返り値: string はエラー説明です。
func (e *ProjectionError) Error() string {
	return "正本は保存済みですがCSV更新に失敗しました: " + e.Err.Error()
}

// Unwrap は、元のファイル保存エラーを返します。
//
// 引数: なし。
// 返り値: error は元のエラーです。
func (e *ProjectionError) Unwrap() error { return e.Err }

var sessionPattern = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}_(Day|Night)$`)

// Open は、保存状態を読み、未反映のCSVを正本から復元します。
//
// 引数: path string は状態ファイル、logDir string はCSV出力先です。
// 返り値: *Store は保存器、error は読み込み・復元失敗です。
func Open(path, logDir string) (*Store, error) {
	s := &Store{path: path, logDir: logDir, data: envelope{Version: 1}}
	b, err := os.ReadFile(path)
	if err == nil {
		if err = json.Unmarshal(b, &s.data); err != nil {
			return nil, fmt.Errorf("永続状態を解析できません: %w", err)
		}
		if s.data.Version != 1 {
			return nil, fmt.Errorf("未対応の永続状態形式です: %d", s.data.Version)
		}
	} else if !os.IsNotExist(err) {
		return nil, err
	}
	if err = s.writeCSV(); err != nil {
		return nil, err
	}
	return s, nil
}

// Load は、正本の実行状態を指定型へ復元します。
//
// 引数: dst any は状態の格納先ポインタです。
// 返り値: []Trade は既存約定、error は状態の復元失敗です。
func (s *Store) Load(dst any) ([]Trade, error) {
	if len(s.data.State) > 0 {
		if err := json.Unmarshal(s.data.State, dst); err != nil {
			return nil, err
		}
	}
	return append([]Trade(nil), s.data.Trades...), nil
}

// Save は、状態と約定を先に永続化し、そこからCSVを再構築します。
//
// 引数: state any は状態、trades []Trade は全約定です。
// 返り値: error は保存失敗です。失敗時は発注を継続してはいけません。
func (s *Store) Save(state any, trades []Trade) error {
	for _, t := range trades {
		if !sessionPattern.MatchString(t.Session) {
			return fmt.Errorf("不正なセッション名です: %s", t.Session)
		}
	}
	raw, err := json.Marshal(state)
	if err != nil {
		return err
	}
	data := envelope{Version: 1, State: raw, Trades: append([]Trade(nil), trades...), Sessions: s.data.Sessions}
	b, err := json.MarshalIndent(data, "", "  ")
	if err != nil {
		return err
	}
	if err = atomicWrite(s.path, append(b, '\n')); err != nil {
		return err
	}
	s.data = data
	if err = s.writeCSV(); err != nil {
		return &ProjectionError{Err: err}
	}
	return nil
}

// writeCSV は、正本の約定をセッションと仮想実行の別で分けて出力します。
//
// 引数: なし。
// 返り値: error はCSV生成・保存失敗です。
func (s *Store) writeCSV() error {
	groups := make(map[string][]Trade)
	for _, name := range s.data.Sessions {
		groups[name] = nil
	}
	for _, t := range s.data.Trades {
		if !sessionPattern.MatchString(t.Session) {
			return fmt.Errorf("保存済みセッション名が不正です")
		}
		name := t.Session
		if t.DryRun {
			name += "_dryrun"
		}
		groups[name] = append(groups[name], t)
	}
	names := make([]string, 0, len(groups))
	for name := range groups {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		var b bytes.Buffer
		w := csv.NewWriter(&b)
		_ = w.Write([]string{"記録ID", "約定確認時刻", "セッション", "銘柄", "区分", "売買", "枚数", "約定価格", "実現損益円", "理由", "発注意図ID", "予約ID", "上流注文ID", "約定ID", "仮想実行"})
		for _, t := range groups[name] {
			kind := "新規"
			if t.TradeType == "close" {
				kind = "返済"
			}
			side := "買い"
			if t.Side == "sell" {
				side = "売り"
			}
			_ = w.Write([]string{t.ID, t.At.Format(time.RFC3339Nano), t.Session, t.Symbol, kind, side, strconv.Itoa(t.Quantity), strconv.FormatFloat(t.Price, 'f', -1, 64), strconv.FormatFloat(t.PnL, 'f', -1, 64), t.Reason, t.ClientOrderID, t.ReservationID, t.BrokerOrderID, t.ExecutionID, strconv.FormatBool(t.DryRun)})
		}
		w.Flush()
		if err := w.Error(); err != nil {
			return err
		}
		if err := atomicWrite(filepath.Join(s.logDir, name+".csv"), b.Bytes()); err != nil {
			return err
		}
	}
	return nil
}

// EnsureSession は、まだ約定がないセッションにもCSV見出しを作ります。
//
// 引数: session string はAPI由来の日付と立会、dryRun bool は仮想実行です。
// 返り値: error は不正名または保存失敗です。
func (s *Store) EnsureSession(session string, dryRun bool) error {
	if !sessionPattern.MatchString(session) {
		return fmt.Errorf("セッション名が不正です")
	}
	name := session
	if dryRun {
		name += "_dryrun"
	}
	for _, existing := range s.data.Sessions {
		if existing == name {
			return nil
		}
	}
	s.data.Sessions = append(s.data.Sessions, name)
	return s.Save(s.data.State, s.data.Trades)
}

// atomicWrite は、同じディレクトリの一時ファイルを確定して置き換えます。
//
// 引数: path string は保存先、data []byte は内容です。
// 返り値: error は作成・同期・置換失敗です。
func atomicWrite(path string, data []byte) error {
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".e01-*")
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
