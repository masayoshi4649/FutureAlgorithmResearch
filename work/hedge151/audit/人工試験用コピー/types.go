// 研究151は保存された入口通知と原板だけを読む独立再生器です。通信・実注文を含みません。
package main

type Scene struct {
	Session    string            `json:"session"`
	Start      float64           `json:"start"`
	USOpen     float64           `json:"us_open"`
	ForceClose float64           `json:"force_close"`
	End        float64           `json:"end"`
	Cutoff     float64           `json:"cutoff"`
	Partial    bool              `json:"partial"`
	Books      map[string]string `json:"books"`
}

type Config struct {
	ID              string  `json:"id"`
	Description     string  `json:"description"`
	Scope           string  `json:"scope"`
	Activation      float64 `json:"activation"`
	Trail           float64 `json:"trail"`
	QuantityLimit   int     `json:"quantity_limit"`
	NoOpposite      bool    `json:"no_opposite"`
	RequirePositive bool    `json:"require_positive"`
	ReentryDistance float64 `json:"reentry_distance"`
}

// EntryNoticeには判断時に公開済みの入口情報だけを保持します。
// 将来の約定・返済・損益や元手法の将来ピークは、この型へ取り込みません。
type EntryNotice struct {
	ID       string  `json:"id"`
	Phase    string  `json:"phase"`
	Owner    string  `json:"owner"`
	Side     int     `json:"side"`
	Quantity int     `json:"quantity"`
	Time     float64 `json:"time"`
	Index    int64   `json:"index"`
	Reason   string  `json:"reason"`
}

type Quote struct {
	Index int64   `json:"index"`
	Line  int64   `json:"line"`
	Time  float64 `json:"time"`
	Last  float64 `json:"last"`
	Bid   float64 `json:"bid"`
	Ask   float64 `json:"ask"`
}

type Pending struct {
	ID            string      `json:"id"`
	Action        string      `json:"action"`
	LotID         string      `json:"lot_id"`
	SlotID        string      `json:"slot_id"`
	Generation    int         `json:"generation"`
	Source        EntryNotice `json:"source"`
	Side          int         `json:"side"`
	Quantity      int         `json:"quantity"`
	DecisionIndex int64       `json:"decision_index"`
	DecisionLine  int64       `json:"decision_line"`
	DecisionTime  float64     `json:"decision_time"`
	DecisionGain  float64     `json:"decision_gain"`
	Reason        string      `json:"reason"`
}

type Lot struct {
	ID               string      `json:"id"`
	SlotID           string      `json:"slot_id"`
	Generation       int         `json:"generation"`
	Source           EntryNotice `json:"source"`
	Side             int         `json:"side"`
	Quantity         int         `json:"quantity"`
	OriginalQuantity int         `json:"original_quantity"`
	Price            float64     `json:"price"`
	Time             float64     `json:"time"`
	Index            int64       `json:"index"`
	Line             int64       `json:"line"`
	Peak             float64     `json:"peak"`
	Worst            float64     `json:"worst"`
	Activated        bool        `json:"activated"`
	ActivationTime   float64     `json:"activation_time"`
	Closing          bool        `json:"closing"`
	ExitPrice        float64     `json:"exit_price"`
	ExitTime         float64     `json:"exit_time"`
	ExitIndex        int64       `json:"exit_index"`
	Gross            float64     `json:"gross"`
}

type ReentryArm struct {
	SlotID       string      `json:"slot_id"`
	Generation   int         `json:"generation"`
	Source       EntryNotice `json:"source"`
	Side         int         `json:"side"`
	Quantity     int         `json:"quantity"`
	Extreme      float64     `json:"extreme"`
	CreatedIndex int64       `json:"created_index"`
	CreatedTime  float64     `json:"created_time"`
}

type Event struct {
	Order     Pending `json:"order"`
	FillIndex int64   `json:"fill_index"`
	FillLine  int64   `json:"fill_line"`
	FillTime  float64 `json:"fill_time"`
	Price     float64 `json:"price"`
	Gross     float64 `json:"gross"`
}

type Decision struct {
	Notice        EntryNotice `json:"notice"`
	Accepted      int         `json:"accepted"`
	Rejected      int         `json:"rejected"`
	Reason        string      `json:"reason"`
	LongReserved  int         `json:"long_reserved"`
	ShortReserved int         `json:"short_reserved"`
}

type Snapshot struct {
	Time       float64 `json:"time"`
	Index      int64   `json:"index"`
	Line       int64   `json:"line"`
	Bid        float64 `json:"bid"`
	Ask        float64 `json:"ask"`
	Long       int     `json:"long"`
	Short      int     `json:"short"`
	Realized   float64 `json:"realized"`
	Unrealized float64 `json:"unrealized"`
	Equity     float64 `json:"equity"`
}

// ReusedPostは売買後の会計専用です。stepには渡しません。
type ReusedPost struct {
	Source       string       `json:"source"`
	FirstNewTime float64      `json:"first_new_time"`
	Gross        float64      `json:"gross"`
	Profit       float64      `json:"profit"`
	Loss         float64      `json:"loss"`
	NewCount     int          `json:"new_count"`
	Events       []SavedEvent `json:"events"`
}

type Input struct {
	Scene   Scene         `json:"scene"`
	Source  string        `json:"source"`
	Notices []EntryNotice `json:"notices"`
	Post    ReusedPost    `json:"post"`
}

type Result struct {
	Config                       Config       `json:"config"`
	Events                       []Event      `json:"events"`
	Lots                         []*Lot       `json:"lots"`
	Pending                      []Pending    `json:"pending"`
	Arms                         []ReentryArm `json:"arms"`
	Decisions                    []Decision   `json:"decisions"`
	Snapshots                    []Snapshot   `json:"snapshots"`
	Gross                        float64      `json:"gross"`
	Profit                       float64      `json:"profit"`
	Loss                         float64      `json:"loss"`
	Unrealized                   float64      `json:"unrealized"`
	MinimumEquity                float64      `json:"minimum_equity"`
	MinimumUnrealized            float64      `json:"minimum_unrealized"`
	MaximumDrawdown              float64      `json:"maximum_drawdown"`
	MinimumEquityAt              Snapshot     `json:"minimum_equity_at"`
	MinimumUnrealizedAt          Snapshot     `json:"minimum_unrealized_at"`
	MaximumDrawdownAt            Snapshot     `json:"maximum_drawdown_at"`
	MaximumDrawdownFrom          Snapshot     `json:"maximum_drawdown_from"`
	MaxLong                      int          `json:"max_long"`
	MaxShort                     int          `json:"max_short"`
	MaxLongReserved              int          `json:"max_long_reserved"`
	MaxShortReserved             int          `json:"max_short_reserved"`
	HeldSeconds                  float64      `json:"held_seconds"`
	HedgedSeconds                float64      `json:"hedged_seconds"`
	LongCapSeconds               float64      `json:"long_cap_seconds"`
	ShortCapSeconds              float64      `json:"short_cap_seconds"`
	ScheduledClose               float64      `json:"scheduled_close"`
	CloseDecisionAt              float64      `json:"close_decision_at"`
	FlatAt                       float64      `json:"flat_at"`
	PositiveDecisionNegativeFill int          `json:"positive_decision_negative_fill"`
	ReentryNewCount              int          `json:"reentry_new_count"`
	ReentryCapWaitRows           int          `json:"reentry_cap_wait_rows"`
	ReentryArmsCancelled         int          `json:"reentry_arms_cancelled"`
	Post                         ReusedPost   `json:"reused_post"`
	CombinedGross                float64      `json:"combined_gross"`
	CombinedProfit               float64      `json:"combined_profit"`
	CombinedLoss                 float64      `json:"combined_loss"`
	LastQuote                    Quote        `json:"last_quote"`
	LastIndex                    int64        `json:"-"`
	LastTime                     float64      `json:"observation_end_time"`
	EquityPeak                   float64      `json:"-"`
	EquityPeakAt                 Snapshot     `json:"-"`
	LastSnapshotMinute           int64        `json:"-"`
	PreviousLong                 int          `json:"-"`
	PreviousShort                int          `json:"-"`
}
