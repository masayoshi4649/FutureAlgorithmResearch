package main

import (
	"encoding/json"
	"fmt"
	"math"
	"time"
)

// floatValue は欠損数値をJSONのnullとして保持します。
//
// 引数: x(*float64)。返り値: any。
func floatValue(x *float64) any {
	if x == nil {
		return nil
	}
	return *x
}

// intValue は欠損数量をJSONのnullとして保持します。
//
// 引数: x(*int)。返り値: any。
func intValue(x *int) any {
	if x == nil {
		return nil
	}
	return *x
}

// lineValue は省略された原行をnullに変換します。
//
// 引数: x(*int64)。返り値: any。
func lineValue(x *int64) any {
	if x == nil {
		return nil
	}
	return *x
}

// stateRow は表示用台帳の値を共通列順に並べます。
//
// 引数: at(float64)、seq(int64)、line(any)、s(DataSummary)。返り値: []any。
func stateRow(at float64, seq int64, line any, s DataSummary) []any {
	return []any{at, seq, line, intValue(s.LongQty), intValue(s.ShortQty), floatValue(s.Realized), floatValue(s.Unrealized)}
}

// addWarning は同じ警告を重複させず品質情報へ保存します。
//
// 引数: q(*Quality)、message(string)。返り値: なし。
func addWarning(q *Quality, message string) {
	for _, s := range q.Warnings {
		if s == message {
			return
		}
	}
	q.Warnings = append(q.Warnings, message)
}

// loadData は保存価格と外部約定を読み、表示専用の損益系列を構築します。
//
// 引数: cfg(Config)、resource(ResourceMeta)、catalogPath(string)、from/to(float64、0は場全体)、width(int)。
// 返り値: DataResponse と error。売買判断、注文、ファイル生成は行いません。
func loadData(cfg Config, resource ResourceMeta, catalogPath string, from, to float64, width int) (DataResponse, error) {
	return loadDataMode(cfg, resource, catalogPath, from, to, width, "raw", "last")
}

// loadDataMode はraw又は固定分足の表示用系列を縮約前の原板から構築します。
//
// 引数: cfg(Config)、resource(ResourceMeta)、catalogPath(string)、from/to(float64)、width(int)、interval/price(string)。
// 返り値: DataResponseとerror。分足の保有・損益は完全区間の最後値です。
func loadDataMode(cfg Config, resource ResourceMeta, catalogPath string, from, to float64, width int, interval, price string) (DataResponse, error) {
	mode, err := parseDisplayMode(interval, price)
	if err != nil {
		return DataResponse{}, err
	}
	start, end, err := sessionBounds(resource.Session)
	if err != nil {
		return DataResponse{}, err
	}
	if width < 1 || width > 4000 {
		return DataResponse{}, fmt.Errorf("widthは1〜4000です")
	}
	if from == 0 {
		from = millis(start)
	}
	if to == 0 {
		to = millis(end)
	}
	if !finite(from) || !finite(to) || to <= from {
		return DataResponse{}, fmt.Errorf("表示範囲が不正です")
	}
	from = math.Max(from, millis(start))
	to = math.Min(to, millis(end))
	if to <= from {
		return DataResponse{}, fmt.Errorf("表示範囲がセッション外です")
	}
	d := DataResponse{Resource: resource, Range: DataRange{millis(start), millis(end), from, to}, PriceColumns: []string{"t", "line", "last", "bid", "ask"}, StateColumns: []string{"t", "sequence", "source_line", "long_qty", "short_qty", "realized_pnl_yen", "unrealized_pnl_yen"}, Prices: [][]any{}, States: [][]any{}, Events: []ViewEvent{}, Quality: Quality{Warnings: []string{"価格時計CurrentPriceTimeを使用。受信時計ではありません。"}}, Files: DataFiles{resource.MarketPath, resource.PNLPath, catalogPath}, Sampling: Sampling{Algorithm: "first_minmax_last"}}
	d.Interval, d.CandlePrice = mode.Interval, mode.Price
	d.CandleColumns, d.Candles = []string{"t", "end_ms", "open", "high", "low", "close"}, [][]any{}
	prices := newSampler(from, to, width, 2)
	states := newSampler(from, to, width, 3)
	var bars *barCollector
	if mode.Minutes > 0 {
		bars = newBarCollector(millis(start), millis(end), mode)
	}
	addState := func(row []any, force bool, clock ...time.Time) {
		if bars != nil {
			if len(clock) > 0 {
				bars.addStateAt(row, clock[0])
			} else {
				bars.addState(row)
			}
		} else {
			states.add(row, force)
		}
	}
	var seq int64
	emit := func(at float64, line any, s DataSummary, force bool, clock ...time.Time) {
		seq++
		addState(stateRow(at, seq, line, s), force, clock...)
		if at <= to {
			d.Summary = s
		}
	}
	var trades []Trade
	if resource.PNLFormat == "trades" {
		trades, err = readTrades(resource.PNLPath, start, end)
		if err != nil {
			return d, err
		}
		trades = entryMethodTrades(trades, resource.EntryMethodID)
	}
	ledger := newDisplayLedger(resource)
	unknownClock := map[int64]bool{}
	for _, t := range trades {
		if t.Type == "Detach" {
			addWarning(&d.Quality, "管理外移管は返済・利確ではありません。移管後の玉や手動決済は、この資料の保有・含み・確定損益に含めません。")
		}
		if t.SourceLine == nil {
			unknownClock[t.At.UnixNano()] = true
		}
	}
	if len(unknownClock) > 0 {
		addWarning(&d.Quality, "source_lineのない約定と板の同時計内順序は不明。その価格時計の含みはnullです。")
	}
	if resource.EntryMethodID != "" {
		addWarning(&d.Quality, "新規時の手法で建玉を帰属し、その玉の返済・管理外移管を全て表示します。各行の手法IDは当時のままです。")
	}
	if resource.PNLFormat == "trades" {
		emit(millis(start), nil, ledger.mark(nil), true)
	}
	tradeIndex := 0
	matched := make([]bool, len(trades))
	var lastMarketAt time.Time
	apply := func(t Trade, q *marketQuote) error {
		delta, e := ledger.apply(t)
		if e != nil {
			return fmt.Errorf("約定原行%d: %w", t.Sequence, e)
		}
		at := millis(t.At)
		emit(at, lineValue(t.SourceLine), ledger.mark(q), true, t.At)
		if at >= from && at <= to {
			method := t.MethodID
			if method == "" {
				method = resource.MethodID
			}
			d.Events = append(d.Events, ViewEvent{at, t.Sequence, t.Type, t.Price, t.Qty, t.PositionID, method, delta})
		}
		return nil
	}
	err = readMarket(resource.MarketPath, start, end, &d.Quality, func(q marketQuote) error {
		lastMarketAt = q.At
		at := millis(q.At)
		if bars != nil {
			bars.addQuote(q)
		} else {
			prices.add([]any{at, q.Line, floatValue(q.Last), floatValue(q.Bid), floatValue(q.Ask)}, false)
		}
		if resource.PNLFormat != "trades" {
			return nil
		}
		// ----------------------------------------
		// 現在行より過去の約定だけを先に反映し、まだ来ていない板では評価しません。
		for tradeIndex < len(trades) && trades[tradeIndex].At.Before(q.At) {
			if e := apply(trades[tradeIndex], nil); e != nil {
				return e
			}
			tradeIndex++
		}
		var usable *marketQuote = &q
		if unknownClock[q.At.UnixNano()] {
			usable = nil
		}
		emit(at, q.Line, ledger.mark(usable), false, q.At)
		for tradeIndex < len(trades) && trades[tradeIndex].At.Equal(q.At) {
			t := trades[tradeIndex]
			if t.SourceLine != nil && *t.SourceLine > q.Line {
				break
			}
			actualQuote := usable
			if t.SourceLine == nil || *t.SourceLine != q.Line {
				actualQuote = nil
			} else {
				matched[tradeIndex] = true
			}
			// 約定直前の状態も極値や保有量の段差として保持します。
			emit(at, q.Line, ledger.mark(actualQuote), true, q.At)
			if e := apply(t, actualQuote); e != nil {
				return e
			}
			tradeIndex++
		}
		return nil
	})
	if err != nil {
		return d, err
	}
	// ----------------------------------------
	// 末尾の原行対応不明約定を反映後、観測端を越える含みだけを未知にします。
	for tradeIndex < len(trades) && !trades[tradeIndex].At.After(lastMarketAt) {
		if e := apply(trades[tradeIndex], nil); e != nil {
			return d, e
		}
		tradeIndex++
	}
	if resource.PNLFormat == "trades" && !lastMarketAt.IsZero() && lastMarketAt.Before(end) {
		emit(math.Nextafter(millis(lastMarketAt), math.Inf(1)), nil, ledger.mark(nil), true, lastMarketAt.Add(time.Nanosecond))
	}
	for tradeIndex < len(trades) {
		if e := apply(trades[tradeIndex], nil); e != nil {
			return d, e
		}
		tradeIndex++
	}
	for i, t := range trades {
		if t.SourceLine != nil && !matched[i] {
			addWarning(&d.Quality, "source_lineと原板時計が一致しない約定があります。約定時計は改変せず、その時点の含みは不明です。")
		}
	}
	if resource.PNLFormat == "snapshots" {
		if err := loadSnapshots(resource.PNLPath, start, end, func(at float64, snapshotSequence int64, line any, s DataSummary, force bool, clock time.Time) {
			addState(stateRow(at, snapshotSequence, line, s), force, clock)
			if at <= to {
				d.Summary = s
			}
		}); err != nil {
			return d, err
		}
	}
	// ----------------------------------------
	// 表示右端の補助点は右端以前の既知値だけを使い、未来の板を補間しません。
	if bars == nil && resource.PNLFormat != "" && states.Previous != nil {
		last, _ := numeric(states.Previous.Values[0])
		if last < to {
			lastSequence, _ := numeric(states.Previous.Values[1])
			states.add(stateRow(to, int64(lastSequence)+1, nil, d.Summary), true)
		}
	}
	d.Prices = prices.result()
	d.States = states.result()
	d.Sampling.PriceInput = prices.Input
	d.Sampling.PriceOutput = len(d.Prices)
	d.Sampling.StateInput = states.Input
	d.Sampling.StateOutput = len(d.States)
	if bars != nil {
		d.Candles, d.States = bars.result(from, to, resource.PNLFormat != "")
		d.Sampling = Sampling{PriceInput: bars.PriceInput, PriceOutput: len(d.Candles), StateInput: bars.StateInput, StateOutput: len(d.States), Algorithm: "ohlc_interval_last_state"}
		addWarning(&d.Quality, "分足は表示端と重なる完全区間を含み、保有・損益は各区間の最後値です。")
		if lastMarketAt.IsZero() || lastMarketAt.Before(end) {
			addWarning(&d.Quality, "原板の最終観測が場末より前のため、未完区間の分足は観測済みデータだけの暫定値です。")
		}
	}
	return d, nil
}

// loadSnapshots は外部評価値を再計算せず、そのまま読取ります。
//
// 引数: path(string)、start/end(time.Time)、emit(func(float64,int64,any,DataSummary,bool,time.Time))。
// 返り値: error。初行前と最終行後は全状態を未知とします。
func loadSnapshots(path string, start, end time.Time, emit func(float64, int64, any, DataSummary, bool, time.Time)) error {
	var previous time.Time
	var previousSequence int64
	var lastMS float64
	var lastClock time.Time
	found := false
	emit(millis(start), 0, nil, DataSummary{}, true, start)
	err := scanJSONL(path, func(line int64, b []byte) error {
		var v Snapshot
		if err := json.Unmarshal(b, &v); err != nil {
			return err
		}
		at, e := time.Parse(time.RFC3339Nano, v.Timestamp)
		if e != nil {
			return e
		}
		if !previous.IsZero() && at.Before(previous) {
			return fmt.Errorf("状態時計が後退しました")
		}
		sequence := line
		if v.Sequence != nil {
			sequence = *v.Sequence
		}
		if sequence < 0 || (at.Equal(previous) && sequence <= previousSequence) {
			return fmt.Errorf("状態sequenceが重複又は後退しました")
		}
		if v.LongQty == nil || v.ShortQty == nil || v.Realized == nil || *v.LongQty < 0 || *v.ShortQty < 0 || !finite(*v.Realized) || (v.Unrealized != nil && !finite(*v.Unrealized)) {
			return fmt.Errorf("状態値が不正又は不足です")
		}
		if v.SourceLine != nil && *v.SourceLine <= 0 {
			return fmt.Errorf("source_lineは1始まりです")
		}
		previous = at
		previousSequence = sequence
		if at.Before(start) || at.After(end) {
			return fmt.Errorf("状態時計がセッション範囲外です")
		}
		lastMS = millis(at)
		lastClock = at
		found = true
		emit(lastMS, sequence, lineValue(v.SourceLine), DataSummary{v.LongQty, v.ShortQty, v.Realized, v.Unrealized}, false, at)
		return nil
	})
	if err != nil {
		return err
	}
	if found && lastMS < millis(end) {
		emit(math.Nextafter(lastMS, math.Inf(1)), previousSequence+1, nil, DataSummary{}, true, lastClock.Add(time.Nanosecond))
	}
	return nil
}
