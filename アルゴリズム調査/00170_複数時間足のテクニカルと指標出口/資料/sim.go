package main

import (
	"fmt"
	"math"
	"time"
)

// pendingTarget は判断した原行と次正常行へ渡す目標を保持します。
type pendingTarget struct {
	signal Signal
	line   int64
	timeNS int64
}

// Simulator は1場・1候補の片方向最大10枚の約定と全玉会計を処理します。
type Simulator struct {
	session       Session
	methodID      string
	multiplier    float64
	keepDetails   bool
	position      Position
	pending       *pendingTarget
	result        SimResult
	episode       *Episode
	positionID    string
	sequence      int
	peakEquity    float64
	lastMark      Quote
	hasMark       bool
	finished      bool
	latestClockNS int64
}

// NewSimulator は手数料0円の場別シミュレータを作ります。
// 引数 methodID は string 型、s は Session 型、keepDetails は bool 型です。
// 返り値は *Simulator 型の会計器です。倍率は日経mini100円、TOPIXmini1000円です。
func NewSimulator(methodID string, s Session, keepDetails bool) *Simulator {
	multiplier := 100.0
	if s.Symbol == "TOPIX" {
		multiplier = 1000
	}
	return &Simulator{session: s, methodID: methodID, multiplier: multiplier, keepDetails: keepDetails,
		result: SimResult{MethodID: methodID, Symbol: s.Symbol, Session: s.Name}}
}

// Position は当原行までに約定済みの建玉を取得します。
// 引数はありません。
// 返り値は Position 型の値コピーです。
func (s *Simulator) Position() Position {
	return s.position
}

// Advance は前行以前の判断を次の正常原行で約定し、当行の時価を更新します。
// 引数 q は Quote 型の当原行です。
// 返り値はありません。同時計でも Line が増えれば次行として扱います。
func (s *Simulator) Advance(q Quote) {
	if s.finished || q.TimeNS < s.session.StartNS || q.TimeNS > s.session.EndNS {
		return
	}
	if q.TimeNS > s.latestClockNS {
		s.latestClockNS = q.TimeNS
	}
	if q.Bid <= 0 || q.Ask <= q.Bid {
		return
	}
	s.mark(q)
	if s.pending != nil && q.Line > s.pending.line {
		pending := s.pending
		s.pending = nil
		s.fillTarget(q, pending, false)
		s.mark(q)
	}
}

// Decide は当行で決めた目標保有を次正常行へ予約します。
// 引数 q は Quote 型の判断原行、signal は *Signal 型の判断又は nil です。
// 返り値は error 型です。枚数上限違反と終了済みの判断を拒否します。
// 未約定判断がある間は先の予約を維持し、後続判断で過去の判断を置換しません。
func (s *Simulator) Decide(q Quote, signal *Signal) error {
	if signal == nil {
		return nil
	}
	if s.finished {
		return fmt.Errorf("終了済み場への判断です")
	}
	if signal.Target < -10 || signal.Target > 10 {
		return fmt.Errorf("目標枚数が片方向上限10枚を超過しました: %d", signal.Target)
	}
	if s.pending != nil || signal.Target == s.position.Side*s.position.Qty {
		return nil
	}
	s.pending = &pendingTarget{signal: *signal, line: q.Line, timeNS: q.TimeNS}
	return nil
}

// RestrictNewEntries は締切到達前から残っている予約の新規部分を取り除きます。
// 引数はありません。締切時計の判定は呼出側が Advance より前に行います。
// 返り値は bool 型で、予約を取消又は返済だけへ変更した場合は true です。
// 反転予約は Target を0へ変更し、元の判断原行・判断時計・理由を維持します。
// 単なる縮小と全返済は維持し、将来の判断を一律禁止する状態は保存しません。
func (s *Simulator) RestrictNewEntries() bool {
	if s.pending == nil || s.pending.signal.Target == 0 {
		return false
	}
	target := s.pending.signal.Target
	if s.position.Qty == 0 {
		s.pending = nil
		return true
	}
	if signInt(target) != s.position.Side {
		s.pending.signal.Target = 0
		return true
	}
	if absInt(target) > s.position.Qty {
		s.pending = nil
		return true
	}
	return false
}

// Finalize は終了前6分以内の最後の正常気配を明示代理にして全残玉を閉じます。
// 引数 audit は SessionAudit 型の同じ原板の監査です。
// 返り値は SimResult 型の確定した場別結果です。
// 尾不足では架空終値を作らず、残玉と最終観測時価を保持します。
func (s *Simulator) Finalize(audit SessionAudit) SimResult {
	if s.finished {
		return s.result
	}
	s.result.Complete = audit.Complete
	s.result.UnfilledAtEnd = s.pending != nil
	s.pending = nil
	if audit.Complete && s.position.Qty > 0 && audit.CloseQuoteLine >= s.position.EntryLine {
		q := Quote{TimeNS: audit.CloseQuoteTimeNS, Line: audit.CloseQuoteLine, Last: audit.CloseProxyPrice, Bid: audit.CloseQuoteBid, Ask: audit.CloseQuoteAsk}
		p := &pendingTarget{signal: Signal{Target: 0, Reason: "場末最終正常気配代理"}, line: q.Line, timeNS: q.TimeNS}
		s.fillTarget(q, p, true)
		s.mark(q)
		s.result.ProxyClose = true
	}
	s.result.FinalPosition = s.position
	if s.episode != nil && s.latestClockNS > s.episode.EntryNS {
		s.result.TotalEpisodeHoldSeconds += float64(s.latestClockNS-s.episode.EntryNS) / float64(time.Second)
	}
	s.result.RealizedYen = cleanZero(s.result.RealizedYen)
	s.result.FinalEquityYen = s.result.RealizedYen + s.result.UnrealizedYen
	if s.hasMark {
		s.result.ValuationTimeNS = s.lastMark.TimeNS
		s.result.ValuationLine = s.lastMark.Line
	}
	if s.keepDetails && s.hasMark {
		s.appendEquity(s.lastMark)
	}
	s.finished = true
	return s.result
}

// fillTarget は予約目標と現保有の差分を経済側の気配で約定します。
// 引数 q は Quote 型、pending は *pendingTarget 型、proxy は bool 型です。
// 返り値はありません。反転は旧玉全返済後に新規を同じ原行で記録します。
func (s *Simulator) fillTarget(q Quote, pending *pendingTarget, proxy bool) {
	target := pending.signal.Target
	side := signInt(target)
	qty := absInt(target)
	if s.position.Qty > 0 && (side != s.position.Side || qty < s.position.Qty) {
		closeQty := s.position.Qty
		if side == s.position.Side {
			closeQty -= qty
		}
		price := q.Bid
		kind := "LongR"
		if s.position.Side < 0 {
			price = q.Ask
			kind = "ShortR"
		}
		s.result.RealizedYen += float64(s.position.Side*closeQty) * (price - s.position.Entry) * s.multiplier
		s.position.Qty -= closeQty
		s.addTrade(q, pending, kind, price, closeQty, proxy)
		if s.position.Qty == 0 {
			s.finishEpisode(q)
			s.position = Position{}
		}
		s.mark(q)
	}
	if qty > 0 && (s.position.Qty == 0 || (s.position.Side == side && qty > s.position.Qty)) {
		addQty := qty - s.position.Qty
		price := q.Ask
		kind := "LongN"
		if side < 0 {
			price = q.Bid
			kind = "ShortN"
		}
		if s.position.Qty == 0 {
			s.sequence++
			s.positionID = fmt.Sprintf("%s/%s/%s/%d", s.methodID, s.session.Symbol, s.session.Name, s.sequence)
			s.position = Position{Side: side, Entry: price, EntryLine: q.Line, EntryTimeNS: q.TimeNS}
			s.episode = &Episode{EntryNS: q.TimeNS, EntryLine: q.Line, Side: side, entryMid: (q.Bid + q.Ask) / 2, realizedStart: s.result.RealizedYen}
		}
		previousEntry := s.position.Entry
		s.position.Entry = (s.position.Entry*float64(s.position.Qty) + price*float64(addQty)) / float64(s.position.Qty+addQty)
		s.position.PeakPoints = math.Max(0, s.position.PeakPoints-float64(side)*(s.position.Entry-previousEntry))
		s.position.Qty += addQty
		s.addTrade(q, pending, kind, price, addQty, proxy)
	}
}

// addTrade は全約定片を数え、詳細指定時だけ標準JSONL互換行を保持します。
// 引数 q は Quote 型、pending は *pendingTarget 型、kind は string 型です。
// 引数 price は float64 型、qty は int 型、proxy は bool 型です。
// 返り値はありません。
func (s *Simulator) addTrade(q Quote, pending *pendingTarget, kind string, price float64, qty int, proxy bool) {
	s.result.Fills++
	if kind == "LongN" || kind == "ShortN" {
		s.result.EntryCount++
		s.result.NewQty += qty
		if s.result.FirstEntryTimeNS == 0 {
			s.result.FirstEntryTimeNS = q.TimeNS
			s.result.FirstEntryLine = q.Line
		}
	} else {
		s.result.ClosedQty += qty
	}
	if !s.keepDetails {
		return
	}
	s.result.Trades = append(s.result.Trades, Trade{ID: fmt.Sprintf("%s/f%d", s.positionID, s.result.Fills), Timestamp: time.Unix(0, q.TimeNS).In(japan).Format(time.RFC3339Nano), Type: kind, PositionID: s.positionID, Price: price, Qty: qty, MethodID: s.methodID, SourceLine: q.Line, DecisionLine: pending.line, DecisionNS: pending.timeNS, Reason: pending.signal.Reason, Proxy: proxy})
}

// mark は正常気配で全残玉含みと初期0を含む時価極値を更新します。
// 引数 q は Quote 型の観測原行です。
// 返り値はありません。買い玉Bid・売り玉Askで評価します。
func (s *Simulator) mark(q Quote) {
	unrealized := 0.0
	if s.position.Qty > 0 {
		price := q.Bid
		if s.position.Side < 0 {
			price = q.Ask
		}
		points := float64(s.position.Side) * (price - s.position.Entry)
		if points > s.position.PeakPoints {
			s.position.PeakPoints = points
		}
		unrealized = points * float64(s.position.Qty) * s.multiplier
	}
	s.result.UnrealizedYen = cleanZero(unrealized)
	equity := s.result.RealizedYen + unrealized
	if equity > s.peakEquity {
		s.peakEquity = equity
	}
	if equity < s.result.MinEquityYen {
		s.result.MinEquityYen = equity
		s.result.MinEquityLine = q.Line
		s.result.MinEquityTimeNS = q.TimeNS
	}
	if dd := s.peakEquity - equity; dd > s.result.MaxDrawdownYen {
		s.result.MaxDrawdownYen = dd
		s.result.MaxDrawdownLine = q.Line
		s.result.MaxDrawdownTimeNS = q.TimeNS
	}
	s.observeEpisode(q, unrealized)
	s.lastMark = q
	s.hasMark = true
}

// observeEpisode は保有エピソードの含みと正益消失を追跡します。
// 引数 q は Quote 型、unrealized は float64 型の全残玉含みです。
// 返り値はありません。部分返済益も含む同エピソードの時価を判定します。
func (s *Simulator) observeEpisode(q Quote, unrealized float64) {
	ep := s.episode
	if ep == nil {
		return
	}
	pnl := s.result.RealizedYen - ep.realizedStart + unrealized
	if !ep.observed {
		ep.InitialNegative = pnl < 0
		ep.MaxUnrealizedYen = unrealized
		ep.MinUnrealizedYen = unrealized
		ep.observed = true
	}
	ep.MaxUnrealizedYen = math.Max(ep.MaxUnrealizedYen, unrealized)
	ep.MinUnrealizedYen = math.Min(ep.MinUnrealizedYen, unrealized)
	midAdverse := -float64(ep.Side) * ((q.Bid+q.Ask)/2 - ep.entryMid)
	ep.MaxMidAdversePoints = math.Max(ep.MaxMidAdversePoints, midAdverse)
	if pnl > 0 {
		if !ep.EverPositive {
			ep.FirstPositiveLine = q.Line
		}
		ep.EverPositive = true
		ep.RecoveredPositive = ep.InitialNegative
	}
	if pnl < 0 && ep.EverPositive {
		if !ep.PositiveThenNegative {
			ep.PositiveLostLine = q.Line
		}
		ep.PositiveThenNegative = true
	}
}

// finishEpisode は保有ゼロの時点で損益を1回だけ集計します。
// 引数 q は Quote 型の最後の返済原行です。
// 返り値はありません。粗利益・粗損失はエピソード単位です。
func (s *Simulator) finishEpisode(q Quote) {
	if s.episode == nil {
		return
	}
	s.observeEpisode(q, 0)
	ep := s.episode
	ep.ExitNS = q.TimeNS
	ep.ExitLine = q.Line
	ep.ProfitYen = cleanZero(s.result.RealizedYen - ep.realizedStart)
	s.result.Episodes++
	if ep.ExitNS > ep.EntryNS {
		s.result.TotalEpisodeHoldSeconds += float64(ep.ExitNS-ep.EntryNS) / float64(time.Second)
	}
	if ep.Side > 0 {
		s.result.LongEpisodes++
		if ep.ProfitYen > 0 {
			s.result.LongProfitYen += ep.ProfitYen
		} else {
			s.result.LongLossYen -= ep.ProfitYen
		}
	} else {
		s.result.ShortEpisodes++
		if ep.ProfitYen > 0 {
			s.result.ShortProfitYen += ep.ProfitYen
		} else {
			s.result.ShortLossYen -= ep.ProfitYen
		}
	}
	if ep.ProfitYen > 0 {
		s.result.Wins++
		s.result.GrossProfitYen += ep.ProfitYen
	} else if ep.ProfitYen < 0 {
		s.result.Losses++
		s.result.GrossLossYen -= ep.ProfitYen
	}
	if ep.InitialNegative {
		s.result.InitialNegative++
	}
	if ep.RecoveredPositive {
		s.result.RecoveredPositive++
	}
	if ep.PositiveThenNegative {
		s.result.PositiveThenNegative++
	}
	if s.keepDetails {
		s.result.EpisodeDetails = append(s.result.EpisodeDetails, *ep)
	}
	s.episode = nil
}

// appendEquity は最終観測の小容量時価情報を追加します。
// 引数 q は Quote 型の観測原行です。
// 返り値はありません。連続曲線は原板と全約定からViewerで復元します。
func (s *Simulator) appendEquity(q Quote) {
	s.result.EquityExtrema = append(s.result.EquityExtrema, EquityPoint{TimeNS: q.TimeNS, SourceLine: q.Line, Realized: s.result.RealizedYen, Unrealized: s.result.UnrealizedYen, Equity: s.result.RealizedYen + s.result.UnrealizedYen})
}

// ----------------------------------------

// signInt は整数の符号を返します。
// 引数 value は int 型です。
// 返り値は int 型の -1、0、1 です。
func signInt(value int) int {
	if value < 0 {
		return -1
	}
	if value > 0 {
		return 1
	}
	return 0
}

// absInt は整数の絶対値を返します。
// 引数 value は int 型です。
// 返り値は int 型の絶対値です。
func absInt(value int) int {
	if value < 0 {
		return -value
	}
	return value
}

// cleanZero は丸め誤差による微小な会計値を0へ整えます。
// 引数 value は float64 型です。
// 返り値は float64 型の値です。
func cleanZero(value float64) float64 {
	if math.Abs(value) < 0.000001 {
		return 0
	}
	return value
}
