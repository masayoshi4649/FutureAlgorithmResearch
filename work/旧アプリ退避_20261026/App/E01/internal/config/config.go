// Package config は、conf直下のTOMLをファイル名順で結合して読み込みます。
package config

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/BurntSushi/toml"
	"ose-future/e01/internal/strategy"
)

// Config は、接続先・運用・戦略とAPI未提供の商品属性をまとめます。
type Config struct {
	Controller Controller             `toml:"CONTROLLER"`
	Trading    Trading                `toml:"TRADE"`
	Runtime    Runtime                `toml:"RUNTIME"`
	E01        Parameters             `toml:"E01"`
	Features   strategy.FeatureConfig `toml:"FEATURE"`
	Products   map[string]Product     `toml:"PRODUCT"`
	Root       string                 `toml:"-" json:"-"`
}

type Controller struct {
	BaseURL               string
	RequestTimeoutSeconds float64
	CandlePollSeconds     float64
	OrderPollSeconds      float64
	ReconnectSeconds      float64
}

type Trading struct {
	Symbol             string
	MaxPositionPerSide int
	InitialQuantity    int
	DryRun             bool
	FillMode           string
}

type Runtime struct {
	LogDirectory             string
	StateDirectory           string
	MaxPriceAgeSeconds       float64
	StaleSeconds             float64
	ReconnectGraceSeconds    float64
	WarmupSeconds            float64
	ForceCloseBeforeSeconds  float64
	ShutdownTimeoutSeconds   float64
	CheckpointSeconds        float64
	StatusSeconds            float64
	EntryOrderTimeoutSeconds float64
	AccountMaxAgeSeconds     float64
}

type Parameters struct {
	EntryATR             float64
	StopATR              float64
	PartialATR           float64
	TrailStartATR        float64
	TrailWideATR         float64
	TrailTightStartATR   float64
	TrailTightATR        float64
	MaxHoldMinutes       float64
	CooldownMinutes      float64
	SessionWarmupSeconds float64
	EntryCutoffSeconds   float64
	EntryPendingSeconds  float64
	ShadowRiskATR        float64
	ActualRiskATR        float64
}

type Product struct {
	Reference  string
	Tick       float64
	PointValue float64
}

// Defaults は、E01既存値と運用既定値を作ります。
//
// 引数: なし。
// 返り値: Config。銘柄・上限・商品属性はTOMLで必ず指定します。
func Defaults() Config {
	return Config{
		Controller: Controller{BaseURL: "http://10.10.100.1:8080", RequestTimeoutSeconds: 10, CandlePollSeconds: 10, OrderPollSeconds: 2, ReconnectSeconds: 3},
		Trading:    Trading{DryRun: true, FillMode: "observed"},
		Runtime:    Runtime{LogDirectory: "log", StateDirectory: "state", MaxPriceAgeSeconds: 30, StaleSeconds: 60, ReconnectGraceSeconds: 180, WarmupSeconds: 120, ForceCloseBeforeSeconds: 600, ShutdownTimeoutSeconds: 20, CheckpointSeconds: 2, StatusSeconds: 10, EntryOrderTimeoutSeconds: 10, AccountMaxAgeSeconds: 15},
		E01:        Parameters{EntryATR: .25, StopATR: .75, PartialATR: 2, TrailStartATR: 1.5, TrailWideATR: 3, TrailTightStartATR: 3, TrailTightATR: .75, MaxHoldMinutes: 360, CooldownMinutes: 5, SessionWarmupSeconds: 1200, EntryCutoffSeconds: 300, EntryPendingSeconds: 300, ShadowRiskATR: 1, ActualRiskATR: 1},
		Features:   strategy.DefaultFeatureConfig(),
	}
}

// ----------------------------------------

// Load は、conf直下の通常TOMLだけを名前順で結合し、不明キーも検出します。
//
// 引数: directory string。設定フォルダ。
// 返り値: Config と error。重複テーブル・型不正・未知設定はエラーです。
func Load(directory string) (Config, error) {
	c := Defaults()
	abs, err := filepath.Abs(directory)
	if err != nil {
		return c, err
	}
	entries, err := os.ReadDir(abs)
	if err != nil {
		return c, fmt.Errorf("設定フォルダを読めません: %w", err)
	}
	names := []string{}
	for _, e := range entries {
		if !e.IsDir() && strings.EqualFold(filepath.Ext(e.Name()), ".toml") {
			names = append(names, e.Name())
		}
	}
	sort.Strings(names)
	if len(names) == 0 {
		return c, fmt.Errorf("conf直下に.tomlがありません")
	}
	var buf strings.Builder
	for _, name := range names {
		b, e := os.ReadFile(filepath.Join(abs, name))
		if e != nil {
			return c, e
		}
		buf.WriteString(strings.TrimPrefix(string(b), "\ufeff"))
		buf.WriteByte('\n')
	}
	md, err := toml.Decode(buf.String(), &c)
	if err != nil {
		return c, fmt.Errorf("TOML設定が不正です: %w", err)
	}
	if u := md.Undecoded(); len(u) > 0 {
		return c, fmt.Errorf("未対応の設定キーがあります: %v", u)
	}
	c.Root = filepath.Dir(abs)
	if err = c.Validate(); err != nil {
		return c, err
	}
	return c, nil
}

// Validate は、無効な銘柄・上限・計算係数と不整合な時間設定を拒否します。
//
// 引数: なし。受け手 *Config の値を検証し初回枚数0を補完します。
// 返り値: error。不正な場合の説明、正常時nil。
func (c *Config) Validate() error {
	u, e := url.Parse(c.Controller.BaseURL)
	if e != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" || u.User != nil || (u.Path != "" && u.Path != "/") || u.RawQuery != "" || u.Fragment != "" {
		return fmt.Errorf("BaseURLには認証情報を含まないhttp(s)の接続先だけを指定してください")
	}
	c.Controller.BaseURL = strings.TrimRight(c.Controller.BaseURL, "/")
	switch c.Trading.Symbol {
	case "NK225", "NK225mini", "NK225micro", "TOPIX", "TOPIXmini":
	default:
		return fmt.Errorf("未対応の取引銘柄です: %s", c.Trading.Symbol)
	}
	if c.Trading.MaxPositionPerSide < 1 || c.Trading.MaxPositionPerSide > 1000000 {
		return fmt.Errorf("MaxPositionPerSideは1〜1000000枚で指定してください")
	}
	if c.Trading.InitialQuantity == 0 {
		c.Trading.InitialQuantity = max(1, c.Trading.MaxPositionPerSide/2)
	}
	if c.Trading.InitialQuantity < 1 || c.Trading.InitialQuantity > c.Trading.MaxPositionPerSide {
		return fmt.Errorf("初回枚数は1枚以上かつ片方向上限以下です")
	}
	if c.Trading.FillMode != "observed" && c.Trading.FillMode != "specified" {
		return fmt.Errorf("FillModeはobservedまたはspecifiedです")
	}
	if !c.Trading.DryRun && c.Trading.FillMode != "observed" {
		return fmt.Errorf("実注文はFillMode=observedで使用してください")
	}
	for _, code := range []string{c.Trading.Symbol, "NK225", "TOPIX"} {
		p, ok := c.Products[code]
		if !ok || !positive(p.Tick) || !positive(p.PointValue) || (p.Reference != "NK225" && p.Reference != "TOPIX") {
			return fmt.Errorf("PRODUCT.%sの参照銘柄・呼値・倍率が不正です", code)
		}
	}
	if c.Products["NK225"].Reference != "NK225" || c.Products["TOPIX"].Reference != "TOPIX" {
		return fmt.Errorf("大型先物の参照銘柄は自身を指定してください")
	}
	for name, v := range map[string]float64{"要求期限": c.Controller.RequestTimeoutSeconds, "足取得間隔": c.Controller.CandlePollSeconds, "注文確認間隔": c.Controller.OrderPollSeconds, "再接続間隔": c.Controller.ReconnectSeconds, "価格鮮度": c.Runtime.MaxPriceAgeSeconds, "中断判定": c.Runtime.StaleSeconds, "中断猶予": c.Runtime.ReconnectGraceSeconds, "準備時間": c.Runtime.WarmupSeconds, "終了前返済": c.Runtime.ForceCloseBeforeSeconds, "停止猶予": c.Runtime.ShutdownTimeoutSeconds, "状態保存": c.Runtime.CheckpointSeconds, "表示間隔": c.Runtime.StatusSeconds, "新規注文期限": c.Runtime.EntryOrderTimeoutSeconds, "入口ATR": c.E01.EntryATR, "損切ATR": c.E01.StopATR, "部分返済ATR": c.E01.PartialATR, "追跡開始ATR": c.E01.TrailStartATR, "通常追跡ATR": c.E01.TrailWideATR, "短縮開始ATR": c.E01.TrailTightStartATR, "短縮追跡ATR": c.E01.TrailTightATR, "最長保有": c.E01.MaxHoldMinutes, "再入口待機": c.E01.CooldownMinutes} {
		if !positive(v) {
			return fmt.Errorf("%sは正の有限数で指定してください", name)
		}
	}
	if c.Runtime.StaleSeconds < c.Runtime.MaxPriceAgeSeconds || c.Runtime.ReconnectGraceSeconds < c.Runtime.StaleSeconds {
		return fmt.Errorf("価格鮮度 ≤ 中断判定 ≤ 中断猶予にしてください")
	}
	if c.Runtime.ForceCloseBeforeSeconds < 30 {
		return fmt.Errorf("終了前返済の猶予は30秒以上必要です")
	}
	if !positive(c.Runtime.AccountMaxAgeSeconds) {
		return fmt.Errorf("AccountMaxAgeSecondsは正の有限秒数で指定してください")
	}
	if c.Runtime.LogDirectory == "" || c.Runtime.StateDirectory == "" {
		return fmt.Errorf("log/state保存先を指定してください")
	}
	if !positive(c.E01.EntryPendingSeconds) || !positive(c.E01.ShadowRiskATR) || !positive(c.E01.ActualRiskATR) || c.E01.SessionWarmupSeconds < 0 || c.E01.EntryCutoffSeconds < 0 || math.IsNaN(c.E01.SessionWarmupSeconds) || math.IsInf(c.E01.SessionWarmupSeconds, 0) || math.IsNaN(c.E01.EntryCutoffSeconds) || math.IsInf(c.E01.EntryCutoffSeconds, 0) {
		return fmt.Errorf("E01の準備・待機・損失予算設定が不正です")
	}
	if _, err := strategy.NewFeatures("設定検査", 0, map[string]float64{"NK225": c.Products["NK225"].Tick, "TOPIX": c.Products["TOPIX"].Tick}, c.Features); err != nil {
		return err
	}
	return nil
}

// positive は、正で有限の設定値か調べます。
//
// 引数: v float64。検査値。
// 返り値: bool。適切な場合true。
func positive(v float64) bool { return v > 0 && !math.IsNaN(v) && !math.IsInf(v, 0) }

// Path は、設定フォルダの親を基準に保存先を解決します。
//
// 引数: name string。絶対または相対パス。
// 返り値: string。解決後パス。
func (c Config) Path(name string) string {
	if filepath.IsAbs(name) {
		return name
	}
	return filepath.Join(c.Root, name)
}

// Fingerprint は、復旧時に戦略・銘柄・接続先の混在を防ぐ識別子を作ります。
//
// 引数: なし。受け手Configを使用。
// 返り値: string。SHA256識別子。保存先だけの変更は含めません。
func (c Config) Fingerprint() string {
	c.Runtime.LogDirectory = ""
	c.Runtime.StateDirectory = ""
	b, _ := json.Marshal(c)
	h := sha256.Sum256(append([]byte("E01-Go-v1\n"), b...))
	return hex.EncodeToString(h[:])
}
