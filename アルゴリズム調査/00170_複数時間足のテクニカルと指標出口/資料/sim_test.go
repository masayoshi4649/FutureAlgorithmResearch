package main

import (
	"math"
	"testing"
	"time"
)

// simQuote は同時計の試験原行を作ります。
// 引数 s は Session 型、line は int64 型、bid と ask は float64 型です。
// 返り値は Quote 型です。
func simQuote(s Session, line int64, bid, ask float64) Quote {
	return Quote{TimeNS: s.StartNS, Line: line, Last: (bid + ask) / 2, Bid: bid, Ask: ask}
}

// requireValue は会計の浮動小数誤差だけを許容して照合します。
// 引数 t は *testing.T 型、got と want は float64 型です。
// 返り値はありません。
func requireValue(t *testing.T, got, want float64) {
	t.Helper()
	if math.Abs(got-want) > 0.00001 {
		t.Fatalf("会計不一致: 実績=%g 期待=%g", got, want)
	}
}

// TestSimulatorNextNormalPhysicalRow は判断行で約定せず同時計の次正常行を使います。
// 引数 t は *testing.T 型です。
// 返り値はありません。
func TestSimulatorNextNormalPhysicalRow(t *testing.T) {
	session := feedSession(t)
	s := NewSimulator("試験", session, true)
	q := simQuote(session, 1, 100, 102)
	s.Advance(q)
	if err := s.Decide(q, &Signal{Target: 10, Reason: "新規"}); err != nil {
		t.Fatal(err)
	}
	s.Advance(q)
	if s.Position().Qty != 0 {
		t.Fatal("同じ原行で約定しました")
	}
	s.Advance(simQuote(session, 2, 110, 110))
	s.Advance(simQuote(session, 3, 120, 119))
	if s.Position().Qty != 0 {
		t.Fatal("同値又は交差気配で約定しました")
	}
	s.Advance(simQuote(session, 4, 130, 132))
	if s.Position().Qty != 10 || s.Position().Entry != 132 {
		t.Fatalf("次正常行Ask約定が不一致: %+v", s.Position())
	}
	r := s.Finalize(SessionAudit{})
	if len(r.Trades) != 1 || r.Trades[0].SourceLine != 4 || r.Trades[0].DecisionLine != 1 || r.FinalPosition.Side != 1 {
		t.Fatalf("判断・約定原行の分離が不一致: %+v", r)
	}
	requireValue(t, r.FinalEquityYen, -2000)
}

// TestSimulatorPartialReverse は部分返済・加重建値・反転を全玉会計へ反映します。
// 引数 t は *testing.T 型です。
// 返り値はありません。
func TestSimulatorPartialReverse(t *testing.T) {
	session := feedSession(t)
	s := NewSimulator("試験", session, true)
	q := simQuote(session, 1, 98, 100)
	_ = s.Decide(q, &Signal{Target: 4})
	s.Advance(simQuote(session, 2, 98, 100))
	_ = s.Decide(simQuote(session, 2, 98, 100), &Signal{Target: 10})
	s.Advance(simQuote(session, 3, 108, 110))
	requireValue(t, s.Position().Entry, 106)
	_ = s.Decide(simQuote(session, 3, 108, 110), &Signal{Target: 6})
	s.Advance(simQuote(session, 4, 120, 122))
	_ = s.Decide(simQuote(session, 4, 120, 122), &Signal{Target: -10})
	s.Advance(simQuote(session, 5, 130, 132))
	_ = s.Decide(simQuote(session, 5, 130, 132), &Signal{Target: 0})
	s.Advance(simQuote(session, 6, 118, 120))
	r := s.Finalize(SessionAudit{})
	requireValue(t, r.RealizedYen, 30000)
	if r.Episodes != 2 || r.Wins != 2 || r.Fills != 6 || r.FinalPosition.Qty != 0 {
		t.Fatalf("部分返済と反転の集計が不一致: %+v", r)
	}
	if r.Trades[0].PositionID != r.Trades[3].PositionID || r.Trades[4].PositionID == r.Trades[3].PositionID {
		t.Fatal("保有IDの所有系列が不一致です")
	}
	if r.EntryCount != 3 || r.NewQty != 20 || r.ClosedQty != 20 || r.TotalEpisodeHoldSeconds != 0 {
		t.Fatalf("追加新規の数量又は同時計保有時間が不一致: %+v", r)
	}
}

// TestSimulatorLossOfProfit は気配差・正益回復・正益消失と場内DDを数えます。
// 引数 t は *testing.T 型です。
// 返り値はありません。
func TestSimulatorLossOfProfit(t *testing.T) {
	session := feedSession(t)
	s := NewSimulator("試験", session, true)
	_ = s.Decide(simQuote(session, 1, 98, 100), &Signal{Target: 10})
	s.Advance(simQuote(session, 2, 98, 100))
	s.Advance(simQuote(session, 3, 110, 112))
	if s.Position().PeakPoints != 10 {
		t.Fatal("利益追尾の基準が買Bidではありません")
	}
	s.Advance(simQuote(session, 4, 95, 97))
	_ = s.Decide(simQuote(session, 4, 95, 97), &Signal{Target: 0})
	s.Advance(simQuote(session, 5, 94, 96))
	r := s.Finalize(SessionAudit{})
	requireValue(t, r.RealizedYen, -6000)
	requireValue(t, r.GrossLossYen, 6000)
	requireValue(t, r.MaxDrawdownYen, 16000)
	if r.PositiveThenNegative != 1 || r.InitialNegative != 1 || r.RecoveredPositive != 1 || r.MaxDrawdownLine != 5 {
		t.Fatalf("利益消失の原行診断が不一致: %+v", r)
	}
	if len(r.EpisodeDetails) != 1 || r.EpisodeDetails[0].FirstPositiveLine != 3 || r.EpisodeDetails[0].PositiveLostLine != 4 {
		t.Fatalf("利益消失の行番号が不一致: %+v", r.EpisodeDetails)
	}
}

// TestSimulatorCloseProxyUsesBBO は終値Lastを有利な約定値へ転用しません。
// 引数 t は *testing.T 型です。
// 返り値はありません。
func TestSimulatorCloseProxyUsesBBO(t *testing.T) {
	session := feedSession(t)
	session.Symbol = "TOPIX"
	s := NewSimulator("試験", session, true)
	_ = s.Decide(simQuote(session, 1, 98, 100), &Signal{Target: -10})
	s.Advance(simQuote(session, 2, 98, 100))
	a := SessionAudit{Session: session, Complete: true, CloseProxyPrice: 80, CloseProxyTimeNS: session.EndNS - int64(5*time.Minute), CloseProxyLine: 9, CloseQuoteBid: 90, CloseQuoteAsk: 92, CloseQuoteTimeNS: session.EndNS - int64(5*time.Minute), CloseQuoteLine: 8}
	r := s.Finalize(a)
	requireValue(t, r.RealizedYen, 60000)
	if !r.ProxyClose || r.FinalPosition.Qty != 0 || len(r.Trades) != 2 || r.Trades[1].SourceLine != 8 || r.Trades[1].Price != 92 || !r.Trades[1].Proxy {
		t.Fatalf("場末BBO代理が不一致: %+v", r)
	}
}

// TestSimulatorRejectsExcessQty は片方向上限を超える判断を拒否します。
// 引数 t は *testing.T 型です。
// 返り値はありません。
func TestSimulatorRejectsExcessQty(t *testing.T) {
	session := feedSession(t)
	s := NewSimulator("試験", session, false)
	if s.Decide(simQuote(session, 1, 98, 100), &Signal{Target: 11}) == nil {
		t.Fatal("上限超過を許可しました")
	}
}

// TestSimulatorSummaryWithoutDetails は詳細保存なしでも買売別会計と実数量を残します。
// 引数 t は *testing.T 型です。
// 返り値はありません。
func TestSimulatorSummaryWithoutDetails(t *testing.T) {
	session := feedSession(t)
	s := NewSimulator("試験", session, false)
	quotes := []Quote{
		simQuote(session, 1, 100, 102), simQuote(session, 2, 100, 102),
		simQuote(session, 3, 102, 104), simQuote(session, 4, 102, 104),
		simQuote(session, 5, 104, 106), simQuote(session, 6, 104, 106),
		simQuote(session, 7, 110, 112), simQuote(session, 8, 110, 112),
	}
	seconds := []int64{0, 1, 11, 12, 20, 21, 31, 32}
	for i := range quotes {
		quotes[i].TimeNS += seconds[i] * int64(time.Second)
		s.Advance(quotes[i])
		switch i {
		case 0:
			_ = s.Decide(quotes[i], &Signal{Target: -5})
		case 2, 6:
			_ = s.Decide(quotes[i], &Signal{Target: 0})
		case 4:
			_ = s.Decide(quotes[i], &Signal{Target: 10})
		}
	}
	r := s.Finalize(SessionAudit{})
	if r.EntryCount != 2 || r.FirstEntryTimeNS != quotes[1].TimeNS || r.FirstEntryLine != 2 || r.NewQty != 15 || r.ClosedQty != 15 || r.LongEpisodes != 1 || r.ShortEpisodes != 1 || len(r.Trades) != 0 || len(r.EpisodeDetails) != 0 {
		t.Fatalf("詳細なしの買売別集計が不一致: %+v", r)
	}
	requireValue(t, r.RealizedYen, 2000)
	requireValue(t, r.LongProfitYen, 4000)
	requireValue(t, r.LongLossYen, 0)
	requireValue(t, r.ShortProfitYen, 0)
	requireValue(t, r.ShortLossYen, 2000)
	requireValue(t, r.TotalEpisodeHoldSeconds, 22)
}

// TestSimulatorUnfinishedHoldTime は不正気配でも観測できた保有時間を捨てません。
// 引数 t は *testing.T 型です。
// 返り値はありません。
func TestSimulatorUnfinishedHoldTime(t *testing.T) {
	session := feedSession(t)
	s := NewSimulator("試験", session, false)
	_ = s.Decide(simQuote(session, 1, 100, 102), &Signal{Target: 10})
	entry := simQuote(session, 2, 100, 102)
	entry.TimeNS += int64(time.Second)
	s.Advance(entry)
	last := simQuote(session, 3, 101, 101)
	last.TimeNS += int64(11 * time.Second)
	s.Advance(last)
	r := s.Finalize(SessionAudit{})
	requireValue(t, r.TotalEpisodeHoldSeconds, 10)
	if r.EntryCount != 1 || r.NewQty != 10 || r.ClosedQty != 0 || r.Episodes != 0 || r.FinalPosition.Qty != 10 || r.ValuationLine != 2 {
		t.Fatalf("未完玉の数量又は評価時計が不一致: %+v", r)
	}
}

// TestRestrictNewEntriesCancelsStaleEntry は不正気配を跨ぐ旧新規予約を取消します。
// 引数 t は *testing.T 型です。
// 返り値はありません。
func TestRestrictNewEntriesCancelsStaleEntry(t *testing.T) {
	session := feedSession(t)
	s := NewSimulator("試験", session, true)
	_ = s.Decide(simQuote(session, 1, 100, 102), &Signal{Target: 10, Reason: "締切前の新規"})
	if !s.RestrictNewEntries() || s.RestrictNewEntries() {
		t.Fatal("旧新規予約の取消状態が不一致です")
	}
	s.Advance(simQuote(session, 2, 102, 102))
	s.Advance(simQuote(session, 3, 103, 105))
	r := s.Finalize(SessionAudit{})
	if r.Fills != 0 || r.NewQty != 0 || r.FinalPosition.Qty != 0 {
		t.Fatalf("締切後に旧新規が約定しました: %+v", r)
	}
}

// TestRestrictNewEntriesKeepsOnlyFlipClose は反転予約の返済と元判断原行を残します。
// 引数 t は *testing.T 型です。
// 返り値はありません。
func TestRestrictNewEntriesKeepsOnlyFlipClose(t *testing.T) {
	session := feedSession(t)
	s := NewSimulator("試験", session, true)
	_ = s.Decide(simQuote(session, 1, 100, 102), &Signal{Target: 10})
	s.Advance(simQuote(session, 2, 100, 102))
	decision := simQuote(session, 3, 100, 102)
	_ = s.Decide(decision, &Signal{Target: -10, Reason: "締切前の反転"})
	if !s.RestrictNewEntries() || s.RestrictNewEntries() {
		t.Fatal("反転の新規部分の取消状態が不一致です")
	}
	s.Advance(simQuote(session, 4, 103, 102))
	s.Advance(simQuote(session, 5, 110, 112))
	r := s.Finalize(SessionAudit{})
	if r.NewQty != 10 || r.ClosedQty != 10 || r.FinalPosition.Qty != 0 || len(r.Trades) != 2 {
		t.Fatalf("反転予約が返済だけになっていません: %+v", r)
	}
	close := r.Trades[1]
	if close.Type != "LongR" || close.DecisionLine != decision.Line || close.DecisionNS != decision.TimeNS || close.Reason != "締切前の反転" || close.SourceLine != 5 {
		t.Fatalf("元の判断記録が変わりました: %+v", close)
	}
}

// TestRestrictNewEntriesKeepsReduction は縮小・全返済を維持し、増玉だけを取消します。
// 引数 t は *testing.T 型です。
// 返り値はありません。
func TestRestrictNewEntriesKeepsReduction(t *testing.T) {
	for _, target := range []int{0, 3, 10} {
		session := feedSession(t)
		s := NewSimulator("試験", session, false)
		_ = s.Decide(simQuote(session, 1, 100, 102), &Signal{Target: 5})
		s.Advance(simQuote(session, 2, 100, 102))
		_ = s.Decide(simQuote(session, 3, 100, 102), &Signal{Target: target})
		if changed := s.RestrictNewEntries(); changed != (target == 10) {
			t.Fatalf("目標%d枚の制限変更状態が不一致です", target)
		}
		s.Advance(simQuote(session, 4, 100, 100))
		s.Advance(simQuote(session, 5, 110, 112))
		want := target
		if target == 10 {
			want = 5
		}
		if s.Position().Qty != want {
			t.Fatalf("目標%d枚の制限後保有が不一致です: %+v", target, s.Position())
		}
	}
}
