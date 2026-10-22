package config

import (
	"fmt"
	"regexp"
	"strings"
	"time"

	"github.com/BurntSushi/toml"
)

// Methods は選択商品の昼夜それぞれに適用する公開手法IDです。
// 手法の実在と商品・昼夜の組合せは、戦略生成時に検査します。
type Methods struct {
	Day   string `toml:"day"`
	Night string `toml:"night"`
}

// MethodID は指定した昼夜の手法IDを返し、未指定なら現行の標準手法を補います。
//
// 引数: kind string は Day または Night です。受け手 Config の選択商品を参照します。
// 返り値: string は手法IDです。未知の区分は空文字で、売買を許可するIDにはしません。
func (c Config) MethodID(kind string) string {
	reference, _ := c.Selected()
	if reference == "" && c.Market != nil {
		reference = Reference(c.Market.Product)
	}
	defaults := defaultMethods(reference)
	switch kind {
	case "Day":
		if c.Methods.Day != "" {
			return c.Methods.Day
		}
		return defaults.Day
	case "Night":
		if c.Methods.Night != "" {
			return c.Methods.Night
		}
		return defaults.Night
	}
	return ""
}

// defaultMethods は既存の運転条件に対応する標準IDを返します。
//
// 引数: reference string は判断用ラージの商品名です。
// 返り値: Methods は昼夜の標準IDです。未知商品では空値です。
func defaultMethods(reference string) Methods {
	switch reference {
	case "TOPIX":
		return Methods{Day: "T06", Night: "T04"}
	case "NK225":
		return Methods{Day: "T06", Night: "U06"}
	}
	return Methods{}
}

// standardProducts はAPIにない価格刻み・円換算倍率の標準値を毎回新しい表で返します。
//
// 引数: なし。
// 返り値: map[string]Product は5商品の規格です。明示した旧設定への追加補完には使用しません。
func standardProducts() map[string]Product {
	return map[string]Product{
		"TOPIX": {Tick: .5, PointValue: 10000}, "TOPIXmini": {Tick: .25, PointValue: 1000},
		"NK225": {Tick: 10, PointValue: 1000}, "NK225mini": {Tick: 5, PointValue: 100},
		"NK225micro": {Tick: 5, PointValue: 10},
	}
}

// ----------------------------------------

// normalizeInput は明示キーを確認し、省略した商品規格と日本時間の入力を正規化します。
//
// 引数: meta toml.MetaData は入力に実在したキーの情報です。受け手 Config を更新します。
// 返り値: error は明示した手法IDの空欄、旧時刻との二重指定または時刻書式の不正です。
func (c *Config) normalizeInput(meta toml.MetaData) error {
	for _, field := range []struct{ name, value string }{{"day", c.Methods.Day}, {"night", c.Methods.Night}} {
		if meta.IsDefined("methods", field.name) && strings.TrimSpace(field.value) == "" {
			return fmt.Errorf("methods.%sを明示する場合は空欄にせず手法IDを指定してください", field.name)
		}
	}
	for _, field := range []struct{ old, current, value string }{
		{"day_extra", "day_extra_jst", c.Schedule.DayExtraJST},
		{"us_open", "us_open_jst", c.Schedule.USOpenJST},
		{"london_extra", "london_extra_jst", c.Schedule.LondonExtraJST},
	} {
		if meta.IsDefined("schedule", field.current) {
			if meta.IsDefined("schedule", field.old) {
				return fmt.Errorf("schedule.%sと%sは同時に指定できません", field.old, field.current)
			}
			if field.value == "" {
				return fmt.Errorf("schedule.%sは日本時間のHH:MMを指定してください", field.current)
			}
		}
	}
	if !meta.IsDefined("products") {
		c.Products = standardProducts()
	}
	return c.Schedule.NormalizeJST()
}

// NormalizeJST は冬の日本時間表記を既存の地域時計へ変換し、入力用の別名を消します。
//
// 引数: なし。受け手 Schedule のJST入力を正規化します。旧キーとの重複はLoadで検査します。
// 返り値: error はHH:MMの不正です。正規化後の再呼出しは値を変えません。
// 米国・英国の実際の夏時間と日付は、schedule.Buildが地域別に適用します。
func (s *Schedule) NormalizeJST() error {
	for _, field := range []struct {
		name           string
		input, target  *string
		differenceHour int
	}{
		{"day_extra_jst", &s.DayExtraJST, &s.DayExtra, 0},
		{"us_open_jst", &s.USOpenJST, &s.USOpen, 14},
		{"london_extra_jst", &s.LondonExtraJST, &s.LondonExtra, 9},
	} {
		if *field.input == "" {
			continue
		}
		parsed, err := time.Parse("15:04", *field.input)
		if err != nil || !regexp.MustCompile(`^[0-9]{2}:[0-9]{2}$`).MatchString(*field.input) {
			return fmt.Errorf("schedule.%sは日本時間のHH:MMを指定してください: %s", field.name, *field.input)
		}
		*field.target = parsed.Add(-time.Duration(field.differenceHour) * time.Hour).Format("15:04")
		*field.input = ""
	}
	return nil
}
