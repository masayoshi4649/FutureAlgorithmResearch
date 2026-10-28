// 研究153は移動平均の傾きと比例枚数を保存板だけで比較します。
package main

type Scene struct {
	Session    string            `json:"session"`
	Kind       string            `json:"kind"`
	Start      float64           `json:"start"`
	USOpen     float64           `json:"us_open"`
	ForceClose float64           `json:"force_close"`
	End        float64           `json:"end"`
	Cutoff     float64           `json:"cutoff"`
	Partial    bool              `json:"partial"`
	Books      map[string]string `json:"books"`
}
type Config struct {
	ID         string  `json:"id"`
	Window     float64 `json:"window_seconds"`
	Lag        float64 `json:"lag_seconds"`
	Allocation string  `json:"allocation"`
	Exit       string  `json:"exit"`
}
type Quote struct {
	Index, Line    int64
	Time, Bid, Ask float64
}
type Feature struct {
	Known               bool
	MA, Previous, Slope float64
}
type Lot struct {
	ID, ParentID            int
	Side, Initial, Quantity int
	Price, At, Realized     float64
}
type Parent struct {
	ID, Side, EntryQuantity                                          int
	EntryTime, Anchor, EntrySlope, PeakSlope, PeakGain               float64
	PeakGainTime, WorstGain, WorstGainTime, LastSlope, LastSlopeTime float64
	Activated, Strengthened                                          bool
	CloseTime, Realized                                              float64
	ExitReason                                                       string
}
type Allocation struct {
	LotID, Quantity              int
	EntryPrice, ExitPrice, Gross float64
}
type Order struct {
	ID, ParentID                    int
	Action, Reason                  string
	Side, Quantity                  int
	DecisionIndex                   int64
	DecisionLine                    int64
	DecisionTime                    float64
	DecisionBid, DecisionAsk        float64
	Feature                         Feature
	ShortFeature                    Feature
	LastNewPrice                    float64
	EntrySlope, PeakSlope, PeakGain float64
}
type Event struct {
	Order                  Order
	FillIndex, FillLine    int64
	FillTime, Price, Gross float64
	FillBid, FillAsk       float64
	Closed                 []Allocation
}
type Snapshot struct {
	Time                         float64
	Index                        int64
	Bid, Ask                     float64
	Side, Quantity               int
	Realized, Unrealized, Equity float64
}
type Result struct {
	Config                                                                       Config
	Session, Kind, Symbol                                                        string
	Partial                                                                      bool
	OpeningMid, PointValue                                                       float64
	ClosingMid, FirstKnownAt                                                     float64
	Events                                                                       []Event
	Lots                                                                         []Lot
	Parents                                                                      []Parent
	Pending                                                                      *Order
	Snapshots                                                                    []Snapshot
	Gross, Profit, Loss, Unrealized                                              float64
	MaximumDrawdown, MinimumEquity, MinimumUnrealized                            float64
	MaximumDrawdownAt, MaximumDrawdownFrom, MinimumEquityAt, MinimumUnrealizedAt Snapshot
	HeldSeconds, EligibleSeconds, KnownSeconds                                   float64
	MaxQuantity, MaxReserved                                                     int
	NewOrders, AddOrders, ReduceOrders, CloseOrders                              int
	FirstEntry, LastEntry, CloseDecisionAt, FlatAt, ObservationEnd               float64
	Current                                                                      *Parent  `json:"open_parent,omitempty"`
	OpenStart                                                                    int      `json:"-"`
	Quantity, Side, Sequence                                                     int      `json:"-"`
	LastIndex                                                                    int64    `json:"-"`
	LastTime, LastRebalance, ReadyAfter, PeakEquity                              float64  `json:"-"`
	PreviousHeld                                                                 bool     `json:"-"`
	PreviousKnown                                                                bool     `json:"-"`
	LastQuote                                                                    Quote    `json:"last_normal_quote"`
	PeakSnapshot                                                                 Snapshot `json:"-"`
	LastMinute                                                                   int64    `json:"-"`
	Start, ForceClose, End                                                       float64  `json:"-"`
	Armed                                                                        map[int]bool
	ArmResetIndex                                                                map[int]int64 `json:"-"`
	Rejections                                                                   map[string]int
	LastNewPrice, LastNewTime                                                    float64
	ShortCurrent                                                                 Feature `json:"-"`
}
