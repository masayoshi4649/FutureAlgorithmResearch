package main

import (
	"bufio"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
)

// DiscoverSessions は既存原板の場一覧を名前順で列挙します。
// 引数 dataRoot は string 型の future ディレクトリです。
// 返り値は []Session 型の場一覧と error 型の読込エラーです。
func DiscoverSessions(dataRoot string) ([]Session, error) {
	var result []Session
	for _, symbol := range []string{"NK225", "TOPIX"} {
		entries, err := os.ReadDir(filepath.Join(dataRoot, symbol))
		if err != nil {
			return nil, err
		}
		for _, entry := range entries {
			if !entry.IsDir() {
				continue
			}
			s, err := ParseSession(symbol, entry.Name(), filepath.Join(dataRoot, symbol, entry.Name(), "book.jsonl"))
			if err != nil {
				continue
			}
			if _, err = os.Stat(s.Path); err == nil {
				result = append(result, s)
			}
		}
	}
	sort.Slice(result, func(i, j int) bool {
		if result[i].Symbol != result[j].Symbol {
			return result[i].Symbol < result[j].Symbol
		}
		return result[i].StartNS < result[j].StartNS
	})
	return result, nil
}

// ParseSession は場名から日本時間の予定境界を生成します。
// 引数 symbol、name、path は string 型の銘柄・場名・原板パスです。
// 返り値は Session 型の境界情報と error 型の形式エラーです。
func ParseSession(symbol, name, path string) (Session, error) {
	parts := strings.Split(name, "_")
	if len(parts) != 2 || (parts[1] != "Day" && parts[1] != "Night") {
		return Session{}, fmt.Errorf("場名が不正です: %s", name)
	}
	d, err := time.ParseInLocation("2006-01-02", parts[0], japan)
	if err != nil {
		return Session{}, err
	}
	start := d.Add(8*time.Hour + 45*time.Minute)
	end := d.Add(15*time.Hour + 45*time.Minute)
	if parts[1] == "Night" {
		start = d.Add(17 * time.Hour)
		end = d.Add(30 * time.Hour)
	}
	return Session{Symbol: symbol, Name: name, Path: path, StartNS: start.UnixNano(), EndNS: end.UnixNano()}, nil
}

// ReadSession は全物理行を順番に読み、場内の価格時計付き原行を通知します。
// 引数 s は Session 型、visit は func(Quote) error 型の逐次処理です。
// 返り値は SessionAudit 型の全原行監査と error 型の読込・通知エラーです。
// 並べ替え・同時計統合・受信時計の推定・原板の複製を行いません。
func ReadSession(s Session, visit func(Quote) error) (SessionAudit, error) {
	a := SessionAudit{Session: s}
	f, err := os.Open(s.Path)
	if err != nil {
		return a, err
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return a, err
	}
	a.Bytes = info.Size()
	hash := sha256.New()
	scanner := bufio.NewScanner(io.TeeReader(f, hash))
	scanner.Buffer(make([]byte, 64*1024), 2*1024*1024)
	var previous int64
	for scanner.Scan() {
		a.Rows++
		raw := scanner.Bytes()
		if !json.Valid(raw) {
			a.InvalidJSONRows++
			continue
		}
		volume, volumeOK := numberField(raw, "TradingVolume")
		if !volumeOK {
			a.NullVolumeRows++
		}
		volumeClock, volumeClockOK := stringField(raw, "TradingVolumeTime")
		if !volumeClockOK {
			a.NullVolumeTimeRows++
		}
		clock, found := stringField(raw, "CurrentPriceTime")
		if !found {
			a.MissingClockRows++
			continue
		}
		at, parseErr := time.Parse(time.RFC3339Nano, clock)
		if parseErr != nil {
			a.InvalidClockRows++
			continue
		}
		t := at.UnixNano()
		if t < s.StartNS || t > s.EndNS {
			a.OutsideRows++
			continue
		}
		a.InSessionRows++
		if a.FirstTimeNS == 0 {
			a.FirstTimeNS = t
		}
		a.LastTimeNS = t
		if previous != 0 {
			if t == previous {
				a.DuplicateClockRows++
			} else if t < previous {
				a.ReversedClockRows++
			} else {
				gap := float64(t-previous) / float64(time.Second)
				if gap > a.MaximumClockGapSeconds {
					a.MaximumClockGapSeconds = gap
				}
			}
		}
		previous = t
		q := Quote{TimeNS: t, Line: a.Rows}
		q.Last, _ = numberField(raw, "CurrentPrice")
		q.Bid, _ = levelPrice(raw, "Buy1")
		q.Ask, _ = levelPrice(raw, "Sell1")
		if q.Last <= 0 {
			a.MissingLastRows++
		} else {
			if a.FirstValidLast == 0 {
				a.FirstValidLast = q.Last
			}
			a.LastValidLast = q.Last
		}
		if q.Bid <= 0 || q.Ask <= 0 {
			a.MissingQuoteRows++
		} else if q.Bid < q.Ask {
			a.NormalQuoteRows++
		} else if q.Bid == q.Ask {
			a.LockedQuoteRows++
		} else {
			a.CrossedQuoteRows++
		}
		apiBid, apiBidOK := numberField(raw, "BidPrice")
		apiAsk, apiAskOK := numberField(raw, "AskPrice")
		if apiBidOK && apiAskOK && apiBid == q.Ask && apiAsk == q.Bid {
			a.ReversedNameMatches++
		}
		q.Volume, q.VolumeValid = volume, volumeOK
		if !volumeClockOK {
			q.VolumeValid = false
		} else {
			vtime, e := time.Parse(time.RFC3339Nano, volumeClock)
			q.VolumeValid = q.VolumeValid && e == nil && vtime.UnixNano() <= q.TimeNS
		}
		if q.Last > 0 && t >= s.EndNS-int64(6*time.Minute) {
			a.CloseProxyPrice = q.Last
			a.CloseProxyTimeNS = t
			a.CloseProxyLine = q.Line
		}
		if q.Bid > 0 && q.Ask > q.Bid && t >= s.EndNS-int64(6*time.Minute) {
			a.CloseQuoteBid = q.Bid
			a.CloseQuoteAsk = q.Ask
			a.CloseQuoteTimeNS = t
			a.CloseQuoteLine = q.Line
		}
		if visit != nil {
			if err = visit(q); err != nil {
				return a, err
			}
		}
	}
	if err = scanner.Err(); err != nil {
		return a, err
	}
	a.Complete = a.CloseProxyLine != 0
	a.SHA256 = hex.EncodeToString(hash.Sum(nil))
	return a, nil
}

// fieldToken は指定キーの JSON 値の先頭を探します。
// 引数 raw は []byte 型、key は string 型です。
// 返り値は []byte 型の値以降の部分列です。未発見時は nil です。
func fieldToken(raw []byte, key string) []byte {
	needle := []byte("\"" + key + "\"")
	i := bytes.Index(raw, needle)
	if i < 0 {
		return nil
	}
	v := bytes.TrimLeft(raw[i+len(needle):], " \t\r\n")
	if len(v) == 0 || v[0] != ':' {
		return nil
	}
	return bytes.TrimLeft(v[1:], " \t\r\n")
}

// numberField は有限の非負 JSON 数値を取得します。
// 引数 raw は []byte 型、key は string 型です。
// 返り値は float64 型の数値と bool 型の有効性です。
func numberField(raw []byte, key string) (float64, bool) {
	v := fieldToken(raw, key)
	if len(v) == 0 || v[0] == 'n' {
		return 0, false
	}
	n := bytes.IndexAny(v, ",}\r\n \t")
	if n < 0 {
		n = len(v)
	}
	x, err := strconv.ParseFloat(string(v[:n]), 64)
	return x, err == nil && x >= 0 && !math.IsNaN(x) && !math.IsInf(x, 0)
}

// stringField はエスケープを含まない時計文字列を取得します。
// 引数 raw は []byte 型、key は string 型です。
// 返り値は string 型の文字列と bool 型の有効性です。
func stringField(raw []byte, key string) (string, bool) {
	v := fieldToken(raw, key)
	if len(v) < 2 || v[0] != '"' {
		return "", false
	}
	n := bytes.IndexByte(v[1:], '"')
	if n < 0 {
		return "", false
	}
	return string(v[1 : n+1]), true
}

// levelPrice は Buy1/Sell1 の入れ子価格を取得します。
// 引数 raw は []byte 型、key は string 型です。
// 返り値は float64 型の価格と bool 型の有効性です。
func levelPrice(raw []byte, key string) (float64, bool) {
	v := fieldToken(raw, key)
	if len(v) == 0 || v[0] != '{' {
		return 0, false
	}
	n := bytes.IndexByte(v, '}')
	if n < 0 {
		return 0, false
	}
	return numberField(v[:n+1], "Price")
}

// ----------------------------------------

// MinuteBuilder は未確定の1分足を1本だけ保持します。
type MinuteBuilder struct {
	Session     Session
	current     Candle
	hasCurrent  bool
	latestNS    int64
	volume      float64
	volumeKnown bool
}

// Add は当原行までで確定した1分足だけを通知します。
// 引数 q は Quote 型の原行です。
// 返り値は []Candle 型で、通常は空又は直前の1本です。
// 逆時計行は閉じた過去足へ混入せず、同時計行は原行順で全て反映します。
func (b *MinuteBuilder) Add(q Quote) []Candle {
	if q.TimeNS < b.latestNS {
		return nil
	}
	b.latestNS = q.TimeNS
	minute := q.TimeNS / int64(time.Minute) * int64(time.Minute)
	if q.TimeNS == b.Session.EndNS {
		minute -= int64(time.Minute)
	}
	var completed []Candle
	if b.hasCurrent && minute > b.current.StartNS {
		b.current.SourceLine = q.Line
		completed = append(completed, b.current)
		b.hasCurrent = false
	}
	if q.Last > 0 {
		if !b.hasCurrent {
			b.current = Candle{StartNS: minute, EndNS: minute + int64(time.Minute), Open: q.Last, High: q.Last, Low: q.Last, Close: q.Last, VolumeComplete: b.volumeKnown && q.VolumeValid}
			b.hasCurrent = true
		}
		b.current.High = math.Max(b.current.High, q.Last)
		b.current.Low = math.Min(b.current.Low, q.Last)
		b.current.Close = q.Last
		b.current.Samples++
		if !q.VolumeValid || !b.volumeKnown || q.Volume < b.volume {
			b.current.VolumeComplete = false
		} else {
			b.current.Volume += q.Volume - b.volume
		}
	}
	if q.VolumeValid {
		b.volume = q.Volume
		b.volumeKnown = true
	} else {
		b.volumeKnown = false
	}
	return completed
}

// Flush は場末到達を観測できた場合だけ最後の確定足を返します。
// 引数 observedNS は int64 型の観測時計、line は int64 型の原行番号です。
// 返り値は []Candle 型の最後の足です。終了前6分の代理値は確定足へ変換しません。
func (b *MinuteBuilder) Flush(observedNS, line int64) []Candle {
	if !b.hasCurrent || observedNS < b.current.EndNS {
		return nil
	}
	b.current.SourceLine = line
	result := []Candle{b.current}
	b.hasCurrent = false
	return result
}
