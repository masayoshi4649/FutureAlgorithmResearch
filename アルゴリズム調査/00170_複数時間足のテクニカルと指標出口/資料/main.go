package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type resultRow struct {
	SimResult
	ConfigID string `json:"config_id"`
}
type runOutput struct {
	Configs []CandidateConfig `json:"configs"`
	Results []resultRow       `json:"results"`
	Audits  []SessionAudit    `json:"audits"`
}
type frozenPlan struct {
	Implementation map[string]string `json:"implementation"`
	ManifestPath   string            `json:"manifest_path"`
	ManifestSHA256 string            `json:"manifest_sha256"`
}

type inputFile170 struct {
	Symbol  string `json:"symbol"`
	Name    string `json:"session"`
	Path    string `json:"path"`
	Bytes   int64  `json:"bytes"`
	MTimeNS int64  `json:"mtime_ns"`
}

// frozenInputs170 は候補固定時のファイル集合だけを読み、追加資料を黙って混ぜません。
//
// 引数: planPath(string)。返り値: []inputFile170とerror。
func frozenInputs170(planPath string) ([]inputFile170, error) {
	b, e := os.ReadFile(planPath)
	if e != nil {
		return nil, e
	}
	var plan frozenPlan
	if e = json.Unmarshal(b, &plan); e != nil {
		return nil, e
	}
	b, e = os.ReadFile(plan.ManifestPath)
	if e != nil {
		return nil, e
	}
	var manifest struct {
		Files []inputFile170 `json:"files"`
	}
	e = json.Unmarshal(b, &manifest)
	return manifest.Files, e
}

// verifyInput170 は再生前後のサイズ・更新時刻を凍結入力と照合します。
//
// 引数: input(inputFile170)。返り値: error。移動平均の判断へ属性を渡しません。
func verifyInput170(input inputFile170) error {
	info, e := os.Stat(input.Path)
	if e != nil {
		return e
	}
	if info.Size() != input.Bytes || info.ModTime().UnixNano() != input.MTimeNS {
		return fmt.Errorf("凍結後に原板が変化しました: %s", input.Path)
	}
	return nil
}

type selectedGroup struct {
	Symbol             string `json:"symbol"`
	Kind               string `json:"kind"`
	MethodID           string `json:"method_id"`
	ControlID          string `json:"control_id"`
	IndicatorControlID string `json:"indicator_control_id"`
}
type viewerResource170 struct {
	ID         string  `json:"id"`
	Title      string  `json:"title"`
	Symbol     string  `json:"symbol"`
	Session    string  `json:"session"`
	Product    string  `json:"product"`
	MethodID   string  `json:"method_id"`
	PointValue float64 `json:"point_value"`
	PNLFormat  string  `json:"pnl_format"`
	PNLBasis   string  `json:"pnl_basis"`
	PNLPath    string  `json:"pnl_path"`
}

// writeJSON170 は小さい集計・定義を一つのJSONへ保存します。
//
// 引数: path(string)、value(any)。返り値: error。原板をコピーしません。
func writeJSON170(path string, value any) error {
	b, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	if err = os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return err
	}
	return os.WriteFile(path, append(b, '\n'), 0644)
}

// hash170 は小さな実装・入力目録の指紋を計算します。
//
// 引数: path(string)。返り値: stringとerror。巨大原板はfeedで同時監査します。
func hash170(path string) (string, error) {
	b, e := os.ReadFile(path)
	if e != nil {
		return "", e
	}
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:]), nil
}

// verifyPlan170 は結果を見る前に固定した実装と入力目録の一致を確認します。
//
// 引数: path(string)。返り値: error。差分を同一手法として実行しません。
func verifyPlan170(path string) error {
	b, e := os.ReadFile(path)
	if e != nil {
		return e
	}
	var p frozenPlan
	if e = json.Unmarshal(b, &p); e != nil {
		return e
	}
	if len(p.Implementation) == 0 || p.ManifestPath == "" {
		return fmt.Errorf("凍結計画が不完全です")
	}
	for name, want := range p.Implementation {
		got, e := hash170(name)
		if e != nil || got != want {
			return fmt.Errorf("実装指紋が変更されています: %s", name)
		}
	}
	got, e := hash170(p.ManifestPath)
	if e != nil || got != p.ManifestSHA256 {
		return fmt.Errorf("入力目録が変更されています")
	}
	return nil
}

// fullID170 は銘柄と研究番号を含む実手法の固定IDを返します。
//
// 引数: symbol/id(string)。返り値: string。
func fullID170(symbol, id string) string { return symbol + "_T170_" + id }

// processSession170 は一度の原板streamへ複数候補を接続します。
//
// 引数: session(Session)、configs([]CandidateConfig)、details(bool)。
// 返り値: []resultRow、SessionAudit、error。保護は毎原行、指標判断は確定足だけです。
func processSession170(session Session, configs []CandidateConfig, details bool) ([]resultRow, SessionAudit, error) {
	shared := newTechnicalEngine()
	strategies := make([]*TechnicalStrategy, len(configs))
	sims := make([]*Simulator, len(configs))
	for i, c := range configs {
		strategies[i] = NewTechnicalStrategy(c, 0)
		strategies[i].engine = shared
		sims[i] = NewSimulator(fullID170(session.Symbol, c.ID), session, details)
	}
	builder := MinuteBuilder{Session: session}
	audit, err := ReadSession(session, func(q Quote) error {
		for _, sim := range sims {
			if q.TimeNS >= session.EndNS-int64(10*time.Minute) {
				sim.RestrictNewEntries()
			}
			sim.Advance(q)
		}
		bars := builder.Add(q)
		prepared := false
		for _, bar := range bars {
			if shared.push(bar) {
				prepared = true
			}
		}
		for i, sim := range sims {
			p := sim.Position()
			signal := strategies[i].OnQuote(q, p)
			if prepared {
				for _, bar := range bars {
					v := strategies[i].OnPreparedBar(bar, p)
					if signal == nil {
						if q.TimeNS-bar.EndNS <= int64(time.Minute) || v == nil || v.Target == 0 {
							signal = v
						} else if p.Qty > 0 && v.Target*p.Side < 0 {
							signal = &Signal{Target: 0, Reason: "古い確定足の反対支持で返済のみ"}
						}
					}
				}
			}
			// ----------------------------------------
			// 予定時計だけで場内返済を予約し、最後のデータ時刻を入口へ使いません。
			if q.TimeNS >= session.EndNS-int64(6*time.Minute) {
				signal = &Signal{Target: 0, Reason: "予定終了6分前の全返済"}
			} else if q.TimeNS >= session.EndNS-int64(10*time.Minute) && signal != nil && signal.Target != 0 {
				if p.Qty > 0 && signal.Target*p.Side < 0 {
					signal = &Signal{Target: 0, Reason: "新規締切後の反対支持で返済のみ"}
				} else {
					signal = nil
				}
			}
			if e := sim.Decide(q, signal); e != nil {
				return e
			}
		}
		return nil
	})
	if err != nil {
		return nil, audit, err
	}
	rows := make([]resultRow, len(sims))
	for i, sim := range sims {
		rows[i] = resultRow{SimResult: sim.Finalize(audit), ConfigID: configs[i].ID}
	}
	return rows, audit, nil
}

// exportTrades170 は選択した候補の全約定だけをViewer形式へ保存します。
//
// 引数: study(string)、row(resultRow)。返り値: viewerResource170とerror。毎tick状態は保存しません。
func exportTrades170(study string, row resultRow) (viewerResource170, error) {
	filename := row.Symbol + "_" + row.Session + "_" + row.ConfigID + ".trades.jsonl"
	relative := filepath.Join("data", filename)
	path := filepath.Join(study, relative)
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return viewerResource170{}, err
	}
	f, err := os.Create(path)
	if err != nil {
		return viewerResource170{}, err
	}
	enc := json.NewEncoder(f)
	enc.SetEscapeHTML(false)
	for _, trade := range row.Trades {
		if err = enc.Encode(trade); err != nil {
			_ = f.Close()
			return viewerResource170{}, err
		}
	}
	if err = f.Close(); err != nil {
		return viewerResource170{}, err
	}
	product, point := "NK225mini", 100.0
	if row.Symbol == "TOPIX" {
		product, point = "TOPIXmini", 1000
	}
	return viewerResource170{ID: row.Symbol + "/" + row.Session + "/" + row.ConfigID, Title: row.MethodID, Symbol: row.Symbol, Session: row.Session, Product: product, MethodID: row.MethodID, PointValue: point, PNLFormat: "trades", PNLBasis: "gross", PNLPath: filepath.ToSlash(relative)}, nil
}

// execute170 は凍結した方式の比較又は選択済み方式の詳細再生を実行します。
//
// 引数: mode/output/plan/selection/study(string)。返り値: error。
func execute170(mode, output, plan, selection, study string) error {
	configs := CandidateConfigs()
	if mode == "definitions" {
		return writeJSON170(output, configs)
	}
	if err := verifyPlan170(plan); err != nil {
		return err
	}
	inputs, err := frozenInputs170(plan)
	if err != nil {
		return err
	}
	var selected struct {
		Selected []selectedGroup `json:"selected"`
	}
	if mode == "details" {
		b, e := os.ReadFile(selection)
		if e != nil {
			return e
		}
		if e = json.Unmarshal(b, &selected); e != nil {
			return e
		}
	}
	out := runOutput{Configs: configs, Results: []resultRow{}, Audits: []SessionAudit{}}
	resources := []viewerResource170{}
	for n, input := range inputs {
		if err = verifyInput170(input); err != nil {
			return err
		}
		session, e := ParseSession(input.Symbol, input.Name, input.Path)
		if e != nil {
			return e
		}
		active := configs
		if mode == "details" {
			active = nil
			kind := strings.Split(session.Name, "_")[1]
			wanted := map[string]bool{}
			for _, g := range selected.Selected {
				if g.Symbol == session.Symbol && g.Kind == kind {
					wanted[g.MethodID] = true
					wanted[g.ControlID] = true
					wanted[g.IndicatorControlID] = true
				}
			}
			for _, c := range configs {
				if wanted[c.ID] {
					active = append(active, c)
				}
			}
			if len(active) == 0 {
				continue
			}
		}
		rows, audit, e := processSession170(session, active, mode == "details")
		if e != nil {
			return fmt.Errorf("%s/%s: %w", session.Symbol, session.Name, e)
		}
		if e = verifyInput170(input); e != nil {
			return e
		}
		if mode == "details" {
			for i := range rows {
				r, e := exportTrades170(study, rows[i])
				if e != nil {
					return e
				}
				resources = append(resources, r)
				rows[i].Trades = nil
			}
		}
		out.Results = append(out.Results, rows...)
		out.Audits = append(out.Audits, audit)
		fmt.Printf("%d/%d %s %s 完了=%t 候補=%d 原行=%d\n", n+1, len(inputs), session.Symbol, session.Name, audit.Complete, len(active), audit.Rows)
	}
	if err = writeJSON170(output, out); err != nil {
		return err
	}
	if mode == "details" {
		abs, e := filepath.Abs(study)
		if e != nil {
			return e
		}
		return writeJSON170(filepath.Join(study, "比較.resources.json"), map[string]any{"schema_version": 1, "path_base": "catalog", "base_dir": abs, "resources": resources})
	}
	return writeJSON170(filepath.Join(study, "データ監査.json"), out.Audits)
}

// main は研究用の定義出力・全候補比較・詳細出力を受け付けます。
//
// 引数: CLI指定。返り値: なし。実口座APIへ接続しません。
func main() {
	mode := flag.String("mode", "run", "definitions/run/details")
	output := flag.String("output", "summary.json", "小さい集計JSON")
	study := flag.String("study", "../../アルゴリズム調査/00170_複数時間足のテクニカルと指標出口", "成果先")
	plan := flag.String("plan", "../../アルゴリズム調査/00170_複数時間足のテクニカルと指標出口/計画.json", "凍結計画")
	selection := flag.String("selection", "rootselection.json", "検討区間だけで固定した候補")
	flag.Parse()
	if *mode != "run" && *mode != "details" && *mode != "definitions" {
		fmt.Fprintln(os.Stderr, "実行形式が不正です")
		os.Exit(1)
	}
	if err := execute170(*mode, *output, *plan, *selection, *study); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
