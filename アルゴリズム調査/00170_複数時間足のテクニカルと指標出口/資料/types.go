package main

import "time"

// Quote は原板の必要最小限の情報を保持します。
// TimeNS は受信時計ではなく CurrentPriceTime の Unix ナノ秒です。
// Line は欠測・場外行を含む元ファイルの物理行番号です。
type Quote struct {
	TimeNS      int64
	Line        int64
	Last        float64
	Bid         float64
	Ask         float64
	Volume      float64
	VolumeValid bool
}

// Candle は全原行から作る確定分足です。
// SourceLine は確定を観測できた原行番号です。
type Candle struct {
	StartNS        int64
	EndNS          int64
	Open           float64
	High           float64
	Low            float64
	Close          float64
	Volume         float64
	VolumeComplete bool
	SourceLine     int64
	Samples        int
}

// Signal は当原行で判断した符号付きの目標保有枚数です。
type Signal struct {
	Target int
	Reason string
}

// Position は判断時点で約定済みの片方向建玉です。
type Position struct {
	Side        int
	Qty         int
	Entry       float64
	EntryLine   int64
	EntryTimeNS int64
	PeakPoints  float64
}

// Session は原板ファイルと日本時間の場境界を表します。
type Session struct {
	Symbol  string `json:"symbol"`
	Name    string `json:"session"`
	Path    string `json:"path"`
	StartNS int64  `json:"start_ns"`
	EndNS   int64  `json:"end_ns"`
}

// SessionAudit は元データの行順と欠測・終値代理の監査情報です。
type SessionAudit struct {
	Session
	Bytes                  int64   `json:"bytes"`
	Rows                   int64   `json:"rows"`
	InvalidJSONRows        int64   `json:"invalid_json_rows"`
	MissingClockRows       int64   `json:"missing_clock_rows"`
	InvalidClockRows       int64   `json:"invalid_clock_rows"`
	OutsideRows            int64   `json:"outside_rows"`
	InSessionRows          int64   `json:"in_session_rows"`
	DuplicateClockRows     int64   `json:"duplicate_clock_rows"`
	ReversedClockRows      int64   `json:"reversed_clock_rows"`
	NullVolumeRows         int64   `json:"null_volume_rows"`
	NullVolumeTimeRows     int64   `json:"null_volume_time_rows"`
	MissingLastRows        int64   `json:"missing_last_rows"`
	NormalQuoteRows        int64   `json:"normal_quote_rows"`
	LockedQuoteRows        int64   `json:"locked_quote_rows"`
	CrossedQuoteRows       int64   `json:"crossed_quote_rows"`
	MissingQuoteRows       int64   `json:"missing_quote_rows"`
	ReversedNameMatches    int64   `json:"reversed_name_matches"`
	FirstTimeNS            int64   `json:"first_time_ns"`
	LastTimeNS             int64   `json:"last_time_ns"`
	FirstValidLast         float64 `json:"first_valid_last"`
	LastValidLast          float64 `json:"last_valid_last"`
	MaximumClockGapSeconds float64 `json:"maximum_clock_gap_seconds"`
	CloseProxyPrice        float64 `json:"close_proxy_price"`
	CloseProxyTimeNS       int64   `json:"close_proxy_time_ns"`
	CloseProxyLine         int64   `json:"close_proxy_line"`
	CloseQuoteBid          float64 `json:"close_quote_bid"`
	CloseQuoteAsk          float64 `json:"close_quote_ask"`
	CloseQuoteTimeNS       int64   `json:"close_quote_time_ns"`
	CloseQuoteLine         int64   `json:"close_quote_line"`
	Complete               bool    `json:"complete"`
	SHA256                 string  `json:"sha256"`
}

// Trade は Viewer 互換の約定片と判断原行を保持します。
type Trade struct {
	ID           string  `json:"id"`
	Timestamp    string  `json:"timestamp"`
	Type         string  `json:"type"`
	PositionID   string  `json:"position_id"`
	Price        float64 `json:"price"`
	Qty          int     `json:"qty"`
	MethodID     string  `json:"method_id"`
	SourceLine   int64   `json:"source_line"`
	DecisionLine int64   `json:"decision_line"`
	DecisionNS   int64   `json:"decision_ns"`
	Reason       string  `json:"reason"`
	Proxy        bool    `json:"proxy,omitempty"`
}

// Episode は新規から保有ゼロまでの損益と初期経路を表します。
type Episode struct {
	EntryNS               int64   `json:"entry_ns"`
	EntryLine             int64   `json:"entry_line"`
	ExitNS                int64   `json:"exit_ns"`
	ExitLine              int64   `json:"exit_line"`
	Side                  int     `json:"side"`
	ProfitYen             float64 `json:"profit_yen"`
	MaxUnrealizedYen      float64 `json:"max_unrealized_yen"`
	MinUnrealizedYen      float64 `json:"min_unrealized_yen"`
	EverPositive          bool    `json:"ever_positive"`
	PositiveThenNegative  bool    `json:"positive_then_negative"`
	InitialNegative       bool    `json:"initial_negative"`
	RecoveredPositive     bool    `json:"recovered_positive"`
	FirstPositiveLine     int64   `json:"first_positive_line"`
	PositiveLostLine      int64   `json:"positive_lost_line"`
	InitialMarkMidAdverse float64 `json:"initial_mark_mid_adverse"`
	MaxMidAdversePoints   float64 `json:"max_mid_adverse_points"`
	observed              bool
	entryMid              float64
	realizedStart         float64
}

// EquityPoint は場内の極値と約定時点だけの小容量時価資料です。
type EquityPoint struct {
	TimeNS     int64   `json:"time_ns"`
	SourceLine int64   `json:"source_line"`
	Realized   float64 `json:"realized_yen"`
	Unrealized float64 `json:"unrealized_yen"`
	Equity     float64 `json:"equity_yen"`
}

// SimResult は全残玉を含めた場別会計結果です。
type SimResult struct {
	MethodID         string  `json:"method_id"`
	Symbol           string  `json:"symbol"`
	Session          string  `json:"session"`
	Complete         bool    `json:"complete"`
	RealizedYen      float64 `json:"realized_yen"`
	UnrealizedYen    float64 `json:"unrealized_yen"`
	FinalEquityYen   float64 `json:"final_equity_yen"`
	GrossProfitYen   float64 `json:"gross_profit_yen"`
	GrossLossYen     float64 `json:"gross_loss_yen"`
	Wins             int     `json:"wins"`
	Losses           int     `json:"losses"`
	Episodes         int     `json:"episodes"`
	Fills            int     `json:"fills"`
	EntryCount       int     `json:"entry_count"`
	FirstEntryTimeNS int64   `json:"first_entry_time_ns"`
	FirstEntryLine   int64   `json:"first_entry_line"`
	NewQty           int     `json:"new_qty"`
	ClosedQty        int     `json:"closed_qty"`
	LongProfitYen    float64 `json:"long_profit_yen"`
	LongLossYen      float64 `json:"long_loss_yen"`
	ShortProfitYen   float64 `json:"short_profit_yen"`
	ShortLossYen     float64 `json:"short_loss_yen"`
	LongEpisodes     int     `json:"long_episodes"`
	ShortEpisodes    int     `json:"short_episodes"`
	// TotalEpisodeHoldSeconds は枚数によらない保有区間長の合計です。
	// 未完玉は最終観測時計まで含め、逆時計の負区間と同時計は0秒です。
	TotalEpisodeHoldSeconds float64       `json:"total_episode_hold_seconds"`
	MinEquityYen            float64       `json:"min_equity_yen"`
	MaxDrawdownYen          float64       `json:"max_drawdown_yen"`
	MaxDrawdownTimeNS       int64         `json:"max_drawdown_time_ns"`
	MaxDrawdownLine         int64         `json:"max_drawdown_line"`
	MinEquityTimeNS         int64         `json:"min_equity_time_ns"`
	MinEquityLine           int64         `json:"min_equity_line"`
	PositiveThenNegative    int           `json:"positive_then_negative"`
	InitialNegative         int           `json:"initial_negative"`
	RecoveredPositive       int           `json:"recovered_positive"`
	FinalPosition           Position      `json:"final_position"`
	UnfilledAtEnd           bool          `json:"unfilled_at_end"`
	ProxyClose              bool          `json:"proxy_close"`
	ValuationTimeNS         int64         `json:"valuation_time_ns"`
	ValuationLine           int64         `json:"valuation_line"`
	Trades                  []Trade       `json:"trades,omitempty"`
	EpisodeDetails          []Episode     `json:"episode_details,omitempty"`
	EquityExtrema           []EquityPoint `json:"equity_extrema,omitempty"`
}

var japan = time.FixedZone("日本標準時", 9*60*60)
