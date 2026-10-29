package main

import (
	"bufio"
	"bytes"
	"compress/gzip"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strings"
	"time"
)

// scanJSONL は通常又はgzipのJSONLを物理行順に処理します。
//
// 引数: path(string)、visit(func(int64,[]byte)error)。返り値: error。原ファイルを書換えません。
func scanJSONL(path string, visit func(int64, []byte) error) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	var reader io.Reader = f
	if strings.HasSuffix(strings.ToLower(path), ".gz") {
		gz, e := gzip.NewReader(f)
		if e != nil {
			return e
		}
		defer gz.Close()
		reader = gz
	}
	s := bufio.NewScanner(reader)
	s.Buffer(make([]byte, 64*1024), 8*1024*1024)
	var line int64
	for s.Scan() {
		line++
		if len(bytes.TrimSpace(s.Bytes())) == 0 {
			continue
		}
		if err := visit(line, s.Bytes()); err != nil {
			return fmt.Errorf("%s 原行%d: %w", path, line, err)
		}
	}
	if err := s.Err(); err != nil {
		return fmt.Errorf("%s 原行%d: %w", path, line+1, err)
	}
	return nil
}

// readMarket は価格時計を保持し、当場外・時計欠損・逆時計を描画対象から除外します。
//
// 引数: path(string)、start/end(time.Time)、quality(*Quality)、visit(func(marketQuote)error)。返り値: error。
func readMarket(path string, start, end time.Time, quality *Quality, visit func(marketQuote) error) error {
	var previous time.Time
	return scanJSONL(path, func(line int64, b []byte) error {
		quality.RawRows++
		var v struct {
			CurrentPriceTime *string
			CurrentPrice     *float64
			Buy1, Sell1      struct{ Price *float64 }
		}
		if err := json.Unmarshal(b, &v); err != nil {
			return err
		}
		if v.CurrentPriceTime == nil {
			quality.InvalidClockRows++
			return nil
		}
		at, err := time.Parse(time.RFC3339Nano, *v.CurrentPriceTime)
		if err != nil {
			quality.InvalidClockRows++
			return nil
		}
		if at.Before(start) || at.After(end) {
			return nil
		}
		if !previous.IsZero() && at.Before(previous) {
			quality.ReversedClockRows++
			return nil
		}
		if at.Equal(previous) {
			quality.DuplicateClockRows++
		}
		previous = at
		clean := func(x *float64) *float64 {
			if x == nil || !finite(*x) || *x <= 0 {
				return nil
			}
			return x
		}
		return visit(marketQuote{At: at, Line: line, Last: clean(v.CurrentPrice), Bid: clean(v.Buy1.Price), Ask: clean(v.Sell1.Price)})
	})
}

// readTrades は約定片の一意ID・時計・必須値を確認して原順序を保持します。
//
// 引数: path(string)、start/end(time.Time)。返り値: []Trade と error。時刻で並べ直しません。
func readTrades(path string, start, end time.Time) ([]Trade, error) {
	result := []Trade{}
	seen := map[string]bool{}
	var previous time.Time
	err := scanJSONL(path, func(line int64, b []byte) error {
		var v Trade
		if err := json.Unmarshal(b, &v); err != nil {
			return err
		}
		at, err := time.Parse(time.RFC3339Nano, v.Timestamp)
		if err != nil {
			return fmt.Errorf("約定時計が不正です: %w", err)
		}
		if !previous.IsZero() && at.Before(previous) {
			return fmt.Errorf("約定時計が後退しました")
		}
		previous = at
		if v.ID == "" || seen[v.ID] {
			return fmt.Errorf("約定IDが空又は重複です")
		}
		seen[v.ID] = true
		if v.PositionID == "" || v.Qty <= 0 || !finite(v.Price) || !finite(v.FeeYen) || v.FeeYen < 0 {
			return fmt.Errorf("約定値が不正です")
		}
		if v.Type == "Detach" {
			if v.Price != 0 || v.FeeYen != 0 {
				return fmt.Errorf("管理外移管に約定価格・手数料は設定できません")
			}
		} else if v.Price <= 0 {
			return fmt.Errorf("約定価格が不正です")
		}
		if v.Type != "LongN" && v.Type != "LongR" && v.Type != "ShortN" && v.Type != "ShortR" && v.Type != "Detach" {
			return fmt.Errorf("売買種別が不正です")
		}
		if v.SourceLine != nil && *v.SourceLine <= 0 {
			return fmt.Errorf("source_lineは1始まりです")
		}
		if at.Before(start) || at.After(end) {
			return fmt.Errorf("約定時刻がセッション範囲外です")
		}
		v.At = at
		v.Sequence = line
		result = append(result, v)
		return nil
	})
	return result, err
}

// entryMethodTrades は最初の新規手法で建玉を帰属し、その玉の返済・移管も同じ資料に残します。
//
// 引数: trades([]Trade)、method(string)。返り値: []Trade。元の行順と連番を保持し、約定当時の手法IDを変更しません。
func entryMethodTrades(trades []Trade, method string) []Trade {
	if method == "" {
		return trades
	}
	first := map[string]string{}
	for _, t := range trades {
		if t.Type != "LongN" && t.Type != "ShortN" {
			continue
		}
		if _, ok := first[t.PositionID]; !ok {
			first[t.PositionID] = t.MethodID
		}
	}
	selected := []Trade{}
	for _, t := range trades {
		if entry, ok := first[t.PositionID]; ok && entry == method {
			selected = append(selected, t)
		}
	}
	return selected
}
