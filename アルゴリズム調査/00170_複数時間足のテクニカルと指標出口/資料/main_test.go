package main

import (
	"fmt"
	"math"
	"os"
	"strings"
	"testing"
	"time"
)

// mainQuotes170 は、全原行処理の結合試験用に各分2行の同時計原板を生成します。
// 引数: s は Session 型の境界、minutes は int 型の人工分数。
// 返り値: []Quote 型の人工原行列。
func mainQuotes170(s Session, minutes int) []Quote {
	quotes := make([]Quote, 0, minutes*2)
	for minute := 0; minute < minutes; minute++ {
		price := 10000 + 0.15*float64(minute) + 40*math.Sin(float64(minute)*0.14) + 12*math.Sin(float64(minute)*0.8)
		for duplicate := 0; duplicate < 2; duplicate++ {
			quotes = append(quotes, Quote{TimeNS: s.StartNS + int64(time.Duration(minute)*time.Minute), Line: int64(len(quotes) + 1), Last: price, Bid: price - 1, Ask: price + 1})
		}
	}
	return quotes
}

// writeMainQuotes170 は、人工原行だけを一時JSONLへ保存します。
// 引数: t は *testing.T 型、s は Session 型の一時出力先、quotes は []Quote 型の人工行。
// 返り値: なし。
func writeMainQuotes170(t *testing.T, s Session, quotes []Quote) {
	t.Helper()
	var content strings.Builder
	for _, q := range quotes {
		content.WriteString(rawLine(fmt.Sprintf("%q", time.Unix(0, q.TimeNS).In(japan).Format(time.RFC3339Nano)), q.Last, q.Bid, q.Ask))
	}
	if err := os.WriteFile(s.Path, []byte(content.String()), 0600); err != nil {
		t.Fatal(err)
	}
}

// firstMainEntry170 は、人工系列で最初の入口が実際に生じる候補と約定を取得します。
// 引数: t は *testing.T 型、s は Session 型、quotes は []Quote 型の人工行。
// 返り値: CandidateConfig 型の候補と Trade 型の最初の新規約定。
func firstMainEntry170(t *testing.T, s Session, quotes []Quote) (CandidateConfig, Trade) {
	t.Helper()
	configs := CandidateConfigs()
	writeMainQuotes170(t, s, quotes)
	rows, _, err := processSession170(s, configs, true)
	if err != nil {
		t.Fatal(err)
	}
	for index, row := range rows {
		for _, trade := range row.Trades {
			if trade.Type == "LongN" || trade.Type == "ShortN" {
				config := configs[index]
				config.ID = "人工入口試験"
				config.ExitMode = "T"
				config.IndicatorExit = false
				config.HardStopRatio = 1
				config.TrailActivationRatio = 1
				config.TrailDistanceRatio = 0.5
				return config, trade
			}
		}
	}
	t.Fatal("人工系列に入口がなく結合検証が空です")
	return CandidateConfig{}, Trade{}
}

// TestMainPhysicalRowsAndEconomicBBO は、共有72候補で全原行と同時計次行の経済側約定を照合します。
// 引数: t は *testing.T 型の検証状態。
// 返り値: なし。
func TestMainPhysicalRowsAndEconomicBBO(t *testing.T) {
	s := feedSession(t)
	s.EndNS = s.StartNS + int64(240*time.Minute)
	quotes := mainQuotes170(s, 180)
	writeMainQuotes170(t, s, quotes)
	rows, audit, err := processSession170(s, CandidateConfigs(), true)
	if err != nil {
		t.Fatal(err)
	}
	if audit.Rows != int64(len(quotes)) || audit.InSessionRows != audit.Rows || audit.DuplicateClockRows != 180 || len(rows) != 72 {
		t.Fatalf("全行・共有候補数の不一致: %+v", audit)
	}
	buys, sells, unclosed := 0, 0, 0
	for _, row := range rows {
		if row.FinalPosition.Qty > 0 {
			unclosed++
		}
		if row.Complete || row.ProxyClose {
			t.Fatal("終了60分前のEOFを完了・代理返済扱いにしました")
		}
		for _, trade := range row.Trades {
			if trade.Proxy || trade.SourceLine != trade.DecisionLine+1 || trade.SourceLine%2 != 0 {
				t.Fatalf("同時計の次物理行約定が不一致: %+v", trade)
			}
			q := quotes[trade.SourceLine-1]
			if q.TimeNS != trade.DecisionNS {
				t.Fatal("同時計次行を待たず別の時計へ遅延しました")
			}
			want := q.Bid
			if trade.Type == "LongN" || trade.Type == "ShortR" {
				want = q.Ask
			}
			requireValue(t, trade.Price, want)
			if trade.Type == "LongN" {
				buys++
			}
			if trade.Type == "ShortN" {
				sells++
			}
		}
	}
	if buys == 0 || sells == 0 || unclosed == 0 {
		t.Fatalf("買%d 売%d 未完残玉%dで検証経路が不足しています", buys, sells, unclosed)
	}
}

// TestMainFreshnessAndEntryCutoff は、古い足の新規と予定終了10分前の新規を抑制します。
// 引数: t は *testing.T 型の検証状態。
// 返り値: なし。
func TestMainFreshnessAndEntryCutoff(t *testing.T) {
	s := feedSession(t)
	s.EndNS = s.StartNS + int64(240*time.Minute)
	quotes := mainQuotes170(s, 180)
	config, entry := firstMainEntry170(t, s, quotes)
	prefix := append([]Quote(nil), quotes[:entry.SourceLine]...)
	cutoff := s
	cutoff.EndNS = entry.DecisionNS + int64(10*time.Minute)
	writeMainQuotes170(t, cutoff, prefix)
	rows, _, err := processSession170(cutoff, []CandidateConfig{config}, true)
	if err != nil {
		t.Fatal(err)
	}
	if rows[0].EntryCount != 0 {
		t.Fatal("10分前の締切と同時刻に新規しました")
	}
	stale := append([]Quote(nil), prefix...)
	stale[len(stale)-2].TimeNS += int64(61 * time.Second)
	stale[len(stale)-1].TimeNS = stale[len(stale)-2].TimeNS
	writeMainQuotes170(t, s, stale)
	rows, _, err = processSession170(s, []CandidateConfig{config}, true)
	if err != nil {
		t.Fatal(err)
	}
	if rows[0].EntryCount != 0 {
		t.Fatal("61秒遅れて確定を観測した古い足で新規しました")
	}
	fresh := append([]Quote(nil), prefix...)
	fresh[len(fresh)-2].TimeNS += int64(60 * time.Second)
	fresh[len(fresh)-1].TimeNS = fresh[len(fresh)-2].TimeNS
	writeMainQuotes170(t, s, fresh)
	rows, _, err = processSession170(s, []CandidateConfig{config}, true)
	if err != nil {
		t.Fatal(err)
	}
	if rows[0].EntryCount != 1 {
		t.Fatal("60秒ちょうどの許容境界で入口を拒否しました")
	}
	pending := append([]Quote(nil), prefix...)
	pending[len(pending)-1].Bid = pending[len(pending)-1].Ask
	cutoff.EndNS = entry.DecisionNS + int64(11*time.Minute)
	tail := prefix[len(prefix)-1]
	tail.TimeNS = cutoff.EndNS - int64(10*time.Minute)
	tail.Line = int64(len(pending) + 1)
	pending = append(pending, tail)
	writeMainQuotes170(t, cutoff, pending)
	rows, _, err = processSession170(cutoff, []CandidateConfig{config}, true)
	if err != nil {
		t.Fatal(err)
	}
	if rows[0].EntryCount != 0 || rows[0].UnfilledAtEnd {
		t.Fatal("締切前の未約定新規を締切後の正常原行で約定又は残存させました")
	}
}

// TestMainStaleBarStillClosesPosition は、古い足の通常返済を新規抑制と混同しないことを確認します。
// 引数: t は *testing.T 型の検証状態。
// 返り値: なし。
func TestMainStaleBarStillClosesPosition(t *testing.T) {
	s := feedSession(t)
	s.EndNS = s.StartNS + int64(240*time.Minute)
	quotes := mainQuotes170(s, 180)
	configs := []CandidateConfig{}
	for _, config := range CandidateConfigs() {
		if config.ExitMode != "I" {
			continue
		}
		config.HardStopRatio, config.TrailActivationRatio, config.TrailDistanceRatio = 1, 1, 0.5
		configs = append(configs, config)
	}
	writeMainQuotes170(t, s, quotes)
	rows, _, err := processSession170(s, configs, true)
	if err != nil {
		t.Fatal(err)
	}
	for index, row := range rows {
		for _, trade := range row.Trades {
			if trade.Reason != "指標支持失効" {
				continue
			}
			prefix := append([]Quote(nil), quotes[:trade.SourceLine]...)
			prefix[len(prefix)-2].TimeNS += int64(61 * time.Second)
			prefix[len(prefix)-1].TimeNS = prefix[len(prefix)-2].TimeNS
			writeMainQuotes170(t, s, prefix)
			staleRows, _, err := processSession170(s, []CandidateConfig{configs[index]}, true)
			if err != nil {
				t.Fatal(err)
			}
			stale := staleRows[0]
			if stale.FinalPosition.Qty != 0 || len(stale.Trades) == 0 || stale.Trades[len(stale.Trades)-1].Reason != "指標支持失効" || stale.ProxyClose {
				t.Fatalf("61秒遅延した足の通常返済を拒否しました: %+v", stale)
			}
			return
		}
	}
	t.Fatal("人工系列に通常指標返済がなく古足出口検証が空です")
}

// TestMainScheduledCloseAndEOFCategories は、機械返済・明示EOF代理・未完残玉を区別します。
// 引数: t は *testing.T 型の検証状態。
// 返り値: なし。
func TestMainScheduledCloseAndEOFCategories(t *testing.T) {
	s := feedSession(t)
	s.EndNS = s.StartNS + int64(240*time.Minute)
	quotes := mainQuotes170(s, 180)
	config, entry := firstMainEntry170(t, s, quotes)
	prefix := append([]Quote(nil), quotes[:entry.SourceLine]...)
	s.EndNS = entry.DecisionNS + int64(20*time.Minute)
	last := prefix[len(prefix)-1]
	dense := append([]Quote(nil), prefix...)
	for at := last.TimeNS + int64(time.Minute); at <= s.EndNS-int64(5*time.Minute); at += int64(time.Minute) {
		for duplicate := 0; duplicate < 2; duplicate++ {
			q := last
			q.TimeNS = at
			q.Line = int64(len(dense) + 1)
			dense = append(dense, q)
		}
	}
	writeMainQuotes170(t, s, dense)
	rows, audit, err := processSession170(s, []CandidateConfig{config}, true)
	if err != nil {
		t.Fatal(err)
	}
	row := rows[0]
	if !audit.Complete || !row.Complete || row.ProxyClose || row.UnfilledAtEnd || row.FinalPosition.Qty != 0 || len(row.Trades) != 2 {
		t.Fatalf("予定場末の機械返済が不一致: %+v", row)
	}
	closeTrade := row.Trades[1]
	if closeTrade.Reason != "予定終了6分前の全返済" || closeTrade.DecisionNS != s.EndNS-int64(6*time.Minute) || closeTrade.SourceLine != closeTrade.DecisionLine+1 || closeTrade.Proxy {
		t.Fatalf("6分前判断・次原行約定が不一致: %+v", closeTrade)
	}
	writeMainQuotes170(t, s, prefix)
	rows, _, err = processSession170(s, []CandidateConfig{config}, true)
	if err != nil {
		t.Fatal(err)
	}
	row = rows[0]
	if row.Complete || row.ProxyClose || row.FinalPosition.Qty != 10 || row.EntryCount != 1 || row.ClosedQty != 0 {
		t.Fatalf("尾不足の残玉を架空返済しました: %+v", row)
	}
	tail := last
	tail.TimeNS = s.EndNS - int64(5*time.Minute)
	tail.Line = int64(len(prefix) + 1)
	sparse := append(append([]Quote(nil), prefix...), tail)
	writeMainQuotes170(t, s, sparse)
	rows, _, err = processSession170(s, []CandidateConfig{config}, true)
	if err != nil {
		t.Fatal(err)
	}
	row = rows[0]
	if !row.Complete || !row.ProxyClose || !row.UnfilledAtEnd || row.FinalPosition.Qty != 0 || len(row.Trades) != 2 || !row.Trades[1].Proxy {
		t.Fatalf("次正常行がないEOFの明示代理区分が不一致: %+v", row)
	}
}
