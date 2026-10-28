package main

import (
	"encoding/json"
	"math"
	"os"
	"path/filepath"
	"testing"

	"futurealgorithm/sessiontrader/internal/rules"
	"futurealgorithm/sessiontrader/internal/strategy"
)

// evidenceCase155 は生板を使用しない通知照合の人工例を作ります。
//
// 引数: なし。返り値: *Caseとstrategy.Signalは独立した保存・現行通知です。
func evidenceCase155() (*Case, strategy.Signal) {
	s := strategy.Signal{ID: "元注文", Owner: "episode", Action: "close", Side: -1, Quantity: 1, Campaign: 2, Ticket: 0, SourceIndex: 3, Time: 1000, Risk: 100, ReasonCode: 15410, Targets: []strategy.LotTarget{{ID: "元玉", Quantity: 1}}, Evidence: json.RawMessage(`{"fixed_r":100,"observation":{"time":1000,"price":65000},"method":"研究"}`)}
	a := s
	a.ID = "現注文"
	a.Targets = []strategy.LotTarget{{ID: "現玉", Quantity: 1}}
	a.Evidence = json.RawMessage(`{"method":"移植","observation":{"price":65000,"time":1000},"fixed_r":100}`)
	return &Case{ID: "S01", Expected: ExpectedCase{Signals: []strategy.Signal{s}}, HoldMapping: map[string]string{"元玉": "現玉"}, SignalMapping: map[string]string{}}, a
}

// TestAudit155SignalCorrespondence は表示差だけを許し、所有対象や原行・価格根拠の差は拒否します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit155SignalCorrespondence(t *testing.T) {
	c, s := evidenceCase155()
	if err := signal155(c, s); err != nil {
		t.Fatal(err)
	}
	if c.SignalMapping["元注文"] != "現注文" || c.Signals != 1 {
		t.Fatal("通知対応が未保存")
	}
	if err := signal155(c, s); err == nil {
		t.Fatal("余分な通知を受理")
	}
	for name, change := range map[string]func(*strategy.Signal){
		"別所有玉": func(s *strategy.Signal) { s.Targets[0].ID = "外部玉" },
		"判断原行": func(s *strategy.Signal) { s.SourceIndex++ },
		"枚数":   func(s *strategy.Signal) { s.Quantity++ },
		"未来根拠": func(s *strategy.Signal) {
			s.Evidence = json.RawMessage(`{"fixed_r":100,"observation":{"time":1001,"price":65000}}`)
		},
		"固定幅": func(s *strategy.Signal) {
			s.Evidence = json.RawMessage(`{"fixed_r":101,"observation":{"time":1000,"price":65000}}`)
		},
		"不正JSON": func(s *strategy.Signal) { s.Evidence = json.RawMessage(`{`) },
	} {
		t.Run(name, func(t *testing.T) {
			c, s := evidenceCase155()
			change(&s)
			if signal155(c, s) == nil {
				t.Fatal("意味の異なる通知を受理")
			}
		})
	}
}

// TestAudit155NormalAndNextQuote は同原行・未知・交差・無限価格を約定へ使用しません。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit155NormalAndNextQuote(t *testing.T) {
	valid := strategy.Observation{Index: 4, Time: 1001, Bid: 65000, Ask: 65010, QuoteOK: true}
	if !normal155(valid) {
		t.Fatal("正常価格を拒否")
	}
	for _, o := range []strategy.Observation{{QuoteOK: false, Bid: 65000, Ask: 65010}, {QuoteOK: true, Bid: 65010, Ask: 65000}, {QuoteOK: true, Bid: 65000, Ask: math.Inf(1)}, {QuoteOK: true, Bid: math.NaN(), Ask: 65010}} {
		if normal155(o) {
			t.Fatal("異常気配を受理")
		}
	}
	c, s := evidenceCase155()
	s.SourceIndex = valid.Index
	if fill155(c, s, valid) == nil {
		t.Fatal("同原行約定を受理")
	}
	s.SourceIndex--
	valid.QuoteOK = false
	if fill155(c, s, valid) == nil {
		t.Fatal("未知価格で約定")
	}
}

// TestAudit155RegistrationGate は未登録・失敗・省略を拒否し明示した成功だけを許します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit155RegistrationGate(t *testing.T) {
	if registration155("") == nil {
		t.Fatal("未指定受領を受理")
	}
	for _, tt := range []struct {
		json  string
		valid bool
	}{{`{}`, false}, {`{"registered":true}`, false}, {`{"registered":true,"returncode":1}`, false}, {`{"registered":false,"returncode":0}`, false}, {`{"registered":true,"returncode":0}`, true}} {
		path := filepath.Join(t.TempDir(), "受領.json")
		if err := os.WriteFile(path, []byte(tt.json), 0600); err != nil {
			t.Fatal(err)
		}
		if (registration155(path) == nil) != tt.valid {
			t.Fatalf("受領判定差: %s", tt.json)
		}
	}
}

// TestAudit155RealRuleFiles は配布用実TOMLを読み、S01共通部が元D07と同じ式であることを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAudit155RealRuleFiles(t *testing.T) {
	d, err := rules.Load("NK225_D07.toml")
	if err != nil {
		t.Fatal(err)
	}
	s, err := rules.LoadFor("NK225_S01.toml", "s01")
	if err != nil {
		t.Fatal(err)
	}
	de, se := d.Expressions(), s.Expressions()
	for key, value := range de {
		if se[key] != value {
			t.Fatalf("共通条件差 %s", key)
		}
	}
	if len(se) != len(de)+3 {
		t.Fatal("専用3条件以外の差", len(de), len(se))
	}
	for _, method := range []string{"D07", "S01"} {
		params, err := strategy.ParametersForMethod("NK225", "Day", method)
		if err != nil {
			t.Fatal(err)
		}
		expressions := de
		if method == "S01" {
			expressions = se
		}
		_, err = strategy.New(strategy.Config{Reference: "NK225", Product: "NK225mini", Cap: 10, CoreQuantity: 5, ExtraMaxQuantity: 5, LargeTick: 10, PointValue: 100, Parameters: params, RuleExpressions: expressions}, strategy.Session{ID: "人工_Day", Kind: "Day", Start: 0, End: 21000, ForceClose: 20000})
		if err != nil {
			t.Fatal(err)
		}
	}
}
