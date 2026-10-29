package main

import "time"

type Config struct {
	Server struct {
		Listen string `toml:"listen"`
	} `toml:"server"`
	Paths struct {
		DataRoot       string `toml:"data_root"`
		ResourceRoot   string `toml:"resource_root"`
		DefaultCatalog string `toml:"default_catalog"`
	} `toml:"paths"`
	Viewer struct {
		CacheMB  int    `toml:"cache_mb"`
		FontPath string `toml:"font_path"`
	} `toml:"viewer"`
	BaseDir string `toml:"-"`
}

type ResourceMeta struct {
	ID            string  `json:"id"`
	Title         string  `json:"title"`
	Symbol        string  `json:"symbol"`
	Session       string  `json:"session"`
	Product       string  `json:"product,omitempty"`
	MethodID      string  `json:"method_id,omitempty"`
	EntryMethodID string  `json:"entry_method_id,omitempty"`
	PointValue    float64 `json:"point_value"`
	PNLFormat     string  `json:"pnl_format,omitempty"`
	PNLBasis      string  `json:"pnl_basis,omitempty"`
	PNLPath       string  `json:"pnl_path,omitempty"`
	MarketPath    string  `json:"market_path,omitempty"`
}

type Catalog struct {
	SchemaVersion int            `json:"schema_version"`
	PathBase      string         `json:"path_base,omitempty"`
	BaseDir       string         `json:"base_dir,omitempty"`
	Resources     []ResourceMeta `json:"resources"`
}

type CatalogResponse struct {
	CatalogID string         `json:"catalog_id"`
	Path      string         `json:"path"`
	Resources []ResourceMeta `json:"resources"`
}

type DataRange struct {
	StartMS float64 `json:"start_ms"`
	EndMS   float64 `json:"end_ms"`
	FromMS  float64 `json:"from_ms"`
	ToMS    float64 `json:"to_ms"`
}
type Quality struct {
	Warnings           []string `json:"warnings"`
	RawRows            int64    `json:"raw_rows"`
	InvalidClockRows   int64    `json:"invalid_clock_rows"`
	ReversedClockRows  int64    `json:"reversed_clock_rows"`
	DuplicateClockRows int64    `json:"duplicate_clock_rows"`
}
type DataFiles struct {
	Market  string `json:"market"`
	PNL     string `json:"pnl"`
	Catalog string `json:"catalog"`
}
type Sampling struct {
	PriceInput  int64  `json:"price_input"`
	PriceOutput int    `json:"price_output"`
	StateInput  int64  `json:"state_input"`
	StateOutput int    `json:"state_output"`
	Algorithm   string `json:"algorithm"`
}
type DataSummary struct {
	LongQty    *int     `json:"long_qty"`
	ShortQty   *int     `json:"short_qty"`
	Realized   *float64 `json:"realized_pnl_yen"`
	Unrealized *float64 `json:"unrealized_pnl_yen"`
}
type ViewEvent struct {
	TimestampMS   float64 `json:"timestamp_ms"`
	Sequence      int64   `json:"sequence"`
	Type          string  `json:"type"`
	Price         float64 `json:"price,omitempty"`
	Qty           int     `json:"qty"`
	PositionID    string  `json:"position_id"`
	MethodID      string  `json:"method_id"`
	RealizedDelta float64 `json:"realized_delta_yen"`
}
type DataResponse struct {
	Resource      ResourceMeta `json:"resource"`
	Range         DataRange    `json:"range"`
	Interval      string       `json:"interval"`
	CandlePrice   string       `json:"candle_price"`
	CandleColumns []string     `json:"candle_columns"`
	Candles       [][]any      `json:"candles"`
	PriceColumns  []string     `json:"price_columns"`
	Prices        [][]any      `json:"prices"`
	StateColumns  []string     `json:"state_columns"`
	States        [][]any      `json:"states"`
	Events        []ViewEvent  `json:"events"`
	Quality       Quality      `json:"quality"`
	Files         DataFiles    `json:"files"`
	Sampling      Sampling     `json:"sampling"`
	Summary       DataSummary  `json:"summary"`
}
type Trade struct {
	ID         string    `json:"id"`
	Timestamp  string    `json:"timestamp"`
	Type       string    `json:"type"`
	PositionID string    `json:"position_id"`
	Price      float64   `json:"price"`
	Qty        int       `json:"qty"`
	FeeYen     float64   `json:"fee_yen"`
	MethodID   string    `json:"method_id"`
	SourceLine *int64    `json:"source_line"`
	At         time.Time `json:"-"`
	Sequence   int64     `json:"-"`
}
type Snapshot struct {
	Timestamp  string   `json:"timestamp"`
	Sequence   *int64   `json:"sequence"`
	SourceLine *int64   `json:"source_line"`
	LongQty    *int     `json:"long_qty"`
	ShortQty   *int     `json:"short_qty"`
	Realized   *float64 `json:"realized_pnl_yen"`
	Unrealized *float64 `json:"unrealized_pnl_yen"`
}
type marketQuote struct {
	At             time.Time
	Line           int64
	Last, Bid, Ask *float64
}
