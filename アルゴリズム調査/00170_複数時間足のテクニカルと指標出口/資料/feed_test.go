package main

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// feedSession は試験用の予定場を作ります。
// 引数 t は *testing.T 型です。
// 返り値は Session 型です。
func feedSession(t *testing.T) Session {
	t.Helper()
	s, err := ParseSession("NK225", "2026-10-28_Day", filepath.Join(t.TempDir(), "book.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	return s
}

// rawLine は経済側とAPI側の名前を逆にした試験原行を作ります。
// 引数 clock は string 型、last、bid、ask は float64 型です。
// 返り値は string 型のJSONL行です。
func rawLine(clock string, last, bid, ask float64) string {
	return fmt.Sprintf("{\"CurrentPriceTime\":%s,\"CurrentPrice\":%g,\"Buy1\":{\"Price\":%g},\"Sell1\":{\"Price\":%g},\"BidPrice\":%g,\"AskPrice\":%g,\"TradingVolume\":null,\"TradingVolumeTime\":null}\n", clock, last, bid, ask, ask, bid)
}

// TestFeedPhysicalOrder は時計重複・逆転・欠測を全原行番号で監査します。
// 引数 t は *testing.T 型です。
// 返り値はありません。
func TestFeedPhysicalOrder(t *testing.T) {
	s := feedSession(t)
	content := rawLine("null", 0, 99, 101) +
		rawLine(`"2026-10-28T08:44:59+09:00"`, 100, 99, 101) +
		rawLine(`"2026-10-28T08:45:01+09:00"`, 100, 99, 101) +
		rawLine(`"2026-10-28T08:45:01+09:00"`, 101, 100, 102) +
		rawLine(`"2026-10-28T08:45:00+09:00"`, 99, 101, 100) +
		rawLine(`"2026-10-28T15:39:00+09:00"`, 110, 109, 111) +
		rawLine(`"2026-10-28T15:40:00+09:00"`, 110, 110, 110)
	if err := os.WriteFile(s.Path, []byte(content), 0600); err != nil {
		t.Fatal(err)
	}
	var quotes []Quote
	a, err := ReadSession(s, func(q Quote) error { quotes = append(quotes, q); return nil })
	if err != nil {
		t.Fatal(err)
	}
	if a.Rows != 7 || a.MissingClockRows != 1 || a.OutsideRows != 1 || a.InSessionRows != 5 || a.DuplicateClockRows != 1 || a.ReversedClockRows != 1 {
		t.Fatalf("原行監査が不一致: %+v", a)
	}
	if len(quotes) != 5 || quotes[0].Line != 3 || quotes[1].Line != 4 || quotes[2].Line != 5 || quotes[0].Bid != 99 || quotes[0].Ask != 101 {
		t.Fatalf("行順又は経済側が不一致: %+v", quotes)
	}
	if a.NullVolumeRows != 7 || a.NullVolumeTimeRows != 7 || a.CloseProxyLine != 7 || a.CloseQuoteLine != 6 || !a.Complete || len(a.SHA256) != 64 {
		t.Fatalf("終端又は全行欠測監査が不一致: %+v", a)
	}
	if a.FirstValidLast != 100 || a.LastValidLast != 110 {
		t.Fatalf("場内の最初・最後の有効Lastが不一致: %+v", a)
	}
}

// TestFeedNightBounds は翌朝6時を夜間場の終端にします。
// 引数 t は *testing.T 型です。
// 返り値はありません。
func TestFeedNightBounds(t *testing.T) {
	s, err := ParseSession("TOPIX", "2026-10-28_Night", "")
	if err != nil {
		t.Fatal(err)
	}
	if d := time.Duration(s.EndNS - s.StartNS); d != 13*time.Hour {
		t.Fatalf("夜間長が不一致: %v", d)
	}
	if time.Unix(0, s.EndNS).In(japan).Format("2006-01-02 15:04") != "2026-10-29 06:00" {
		t.Fatal("夜間終了日が不正です")
	}
}

// TestMinuteBuilderCausality は未来価格と逆時計行を確定足へ混ぜません。
// 引数 t は *testing.T 型です。
// 返り値はありません。
func TestMinuteBuilderCausality(t *testing.T) {
	s := feedSession(t)
	b := MinuteBuilder{Session: s}
	q := Quote{TimeNS: s.StartNS, Line: 1, Last: 100, Volume: 10, VolumeValid: true}
	if got := b.Add(q); len(got) != 0 {
		t.Fatal("当分の足が早期確定しました")
	}
	q.Line = 2
	q.Last = 120
	q.Volume = 12
	b.Add(q)
	q.TimeNS += int64(time.Minute)
	q.Line = 3
	q.Last = 999
	q.Volume = 13
	got := b.Add(q)
	if len(got) != 1 || got[0].Open != 100 || got[0].High != 120 || got[0].Close != 120 || got[0].SourceLine != 3 || got[0].Volume != 2 || got[0].VolumeComplete {
		t.Fatalf("確定足が未来値又は不明出来高を含みます: %+v", got)
	}
	q.TimeNS -= int64(time.Second)
	q.Line = 4
	q.Last = 2000
	if len(b.Add(q)) != 0 {
		t.Fatal("逆時計行から足が確定しました")
	}
	q.TimeNS = s.StartNS + int64(2*time.Minute)
	q.Line = 5
	q.Last = 500
	got = b.Add(q)
	if len(got) != 1 || got[0].High != 999 || got[0].Close != 999 {
		t.Fatalf("逆時計行が未来の足に混入しました: %+v", got)
	}
	if len(b.Flush(q.TimeNS, q.Line)) != 0 {
		t.Fatal("未確定最終足を補完しました")
	}
}
