// 152はP05移植の同値検査だけを行います。通信と実注文の機能はありません。
package main

import (
	"bufio"
	"encoding/csv"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"futurealgorithm/sessiontrader/internal/rules"
	"futurealgorithm/sessiontrader/internal/strategy"
	"io"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strconv"
	"strings"
	"time"
)

type Scene struct {
	Session    string                       `json:"session"`
	Start      float64                      `json:"start"`
	USOpen     float64                      `json:"us_open"`
	ForceClose float64                      `json:"force_close"`
	End        float64                      `json:"end"`
	Cutoff     float64                      `json:"cutoff"`
	Partial    bool                         `json:"partial"`
	Books      map[string]string            `json:"books"`
	Candles    map[string]map[string]string `json:"candles"`
}

type rawLevel struct{ Price, Qty float64 }
type rawBook struct {
	CurrentPriceTime                                                      *string
	CurrentPrice                                                          float64
	Buy1, Buy2, Buy3, Buy4, Buy5, Buy6, Buy7, Buy8, Buy9, Buy10           rawLevel
	Sell1, Sell2, Sell3, Sell4, Sell5, Sell6, Sell7, Sell8, Sell9, Sell10 rawLevel
}

// readJSON は研究入力を読み取り、指定した型へ復元します。
//
// 引数: path(string)、target(any)は位置と復元先です。
// 返り値: errorは読取又はJSONの不整合です。
func readJSON(path string, target any) error {
	raw, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	return json.Unmarshal(raw, target)
}

// stamp はISO形式の明示時計を小数UNIX秒へ変換します。
//
// 引数: value(string)。返り値: float64は秒、errorは不正時計です。
func stamp(value string) (float64, error) {
	t, e := time.Parse(time.RFC3339Nano, value)
	return float64(t.UnixNano()) / 1e9, e
}

// loadBoards は各市場の原行順を維持して時刻で安定結合します。
//
// 引数: scene(Scene)。返り値: []strategy.Boardと除外数map、errorです。
// 同一時計の市場間参照は特徴量器が厳密過去に制限します。約定時刻nullで板を捨てません。
func loadBoards(scene Scene) ([]strategy.Board, map[string]int, error) {
	all := []strategy.Board{}
	counts := map[string]int{}
	for _, ref := range []string{"TOPIX", "NK225"} {
		f, err := os.Open(scene.Books[ref])
		if err != nil {
			return nil, nil, err
		}
		sc := bufio.NewScanner(f)
		sc.Buffer(make([]byte, 65536), 8*1024*1024)
		previous := scene.Start
		for sc.Scan() {
			counts[ref+"_原行"]++
			var b rawBook
			if err = json.Unmarshal(sc.Bytes(), &b); err != nil {
				f.Close()
				return nil, nil, err
			}
			if b.CurrentPriceTime == nil {
				counts[ref+"_時計欠測"]++
				continue
			}
			at, e := stamp(*b.CurrentPriceTime)
			if e != nil {
				counts[ref+"_時計欠測"]++
				continue
			}
			if at < scene.Start || at > scene.End || (scene.Cutoff > 0 && at >= scene.Cutoff) {
				counts[ref+"_範囲外"]++
				continue
			}
			if at < previous {
				counts[ref+"_逆行"]++
				continue
			}
			if b.CurrentPrice <= 0 || math.IsNaN(b.CurrentPrice) || math.IsInf(b.CurrentPrice, 0) {
				counts[ref+"_Last欠測"]++
				continue
			}
			previous = at
			board := strategy.Board{Reference: ref, Time: at, Received: at, Last: b.CurrentPrice, Bid: b.Buy1.Price, Ask: b.Sell1.Price, BidQuantity: b.Buy1.Qty, AskQuantity: b.Sell1.Qty}
			buys := []rawLevel{b.Buy1, b.Buy2, b.Buy3, b.Buy4, b.Buy5, b.Buy6, b.Buy7, b.Buy8, b.Buy9, b.Buy10}
			sells := []rawLevel{b.Sell1, b.Sell2, b.Sell3, b.Sell4, b.Sell5, b.Sell6, b.Sell7, b.Sell8, b.Sell9, b.Sell10}
			for k := range buys {
				board.BidLevels[k] = strategy.ResearchLevel{Price: buys[k].Price, Quantity: buys[k].Qty}
				board.AskLevels[k] = strategy.ResearchLevel{Price: sells[k].Price, Quantity: sells[k].Qty}
			}
			all = append(all, board)
			counts[ref+"_採用"]++
		}
		err = sc.Err()
		f.Close()
		if err != nil {
			return nil, nil, err
		}
	}
	sort.SliceStable(all, func(i, j int) bool { return all[i].Time < all[j].Time })
	return all, counts, nil
}

// loadCandles は保存確定足を読み、対象開始以前の足を除きます。
//
// 引数: path(string)、interval(int)、start/end(float64)。返り値: []strategy.Candleとerrorです。
// リセットUSを跨ぐ足も除外し、残りの足は名目公開時刻まで利用させません。
func loadCandles(path string, interval int, start, end float64) ([]strategy.Candle, error) {
	out := []strategy.Candle{}
	if strings.HasSuffix(strings.ToLower(path), ".csv") {
		f, e := os.Open(path)
		if e != nil {
			return nil, e
		}
		defer f.Close()
		r := csv.NewReader(f)
		header, e := r.Read()
		if e != nil {
			return nil, e
		}
		cols := map[string]int{}
		for i, name := range header {
			cols[strings.TrimPrefix(name, "\ufeff")] = i
		}
		for {
			row, e := r.Read()
			if e == io.EOF {
				break
			}
			if e != nil {
				return nil, e
			}
			at, e := stamp(row[cols["time"]])
			if e != nil {
				return nil, e
			}
			if at < start || at+float64(interval) > end || row[cols["closed"]] != "true" {
				continue
			}
			v := []float64{}
			for _, name := range []string{"open", "high", "low", "close"} {
				x, e := strconv.ParseFloat(row[cols[name]], 64)
				if e != nil {
					return nil, e
				}
				v = append(v, x)
			}
			out = append(out, strategy.Candle{Time: at, Open: v[0], High: v[1], Low: v[2], Close: v[3], Closed: true})
		}
	} else {
		var saved struct {
			Data []struct {
				Time                   string
				Open, High, Low, Close float64
				Closed                 bool
			}
		}
		if e := readJSON(path, &saved); e != nil {
			return nil, e
		}
		for _, bar := range saved.Data {
			at, e := stamp(bar.Time)
			if e != nil {
				return nil, e
			}
			if !bar.Closed || at < start || at+float64(interval) > end {
				continue
			}
			out = append(out, strategy.Candle{Time: at, Open: bar.Open, High: bar.High, Low: bar.Low, Close: bar.Close, Closed: true})
		}
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].Time < out[j].Time })
	return out, nil
}

// makeSession は原市場時計を保った研究用セッションを生成します。
//
// 引数: scene(Scene)、start/end(float64)。返り値: strategy.Sessionです。
func makeSession(scene Scene, start, end float64) strategy.Session {
	return strategy.Session{ID: scene.Session, Kind: "Night", Start: start, End: scene.End, ForceClose: end, USOpen: scene.USOpen, ExtraAt: scene.USOpen + 1800}
}

// newFeatures は指定開始からだけ指標と始値を作り直します。
//
// 引数: scene(Scene)、start(float64)。返り値: *strategy.Featuresとerrorです。
func newFeatures(scene Scene, start float64) (*strategy.Features, error) {
	params, e := strategy.ParametersForMethod("NK225", "Night", "D07")
	if e != nil {
		return nil, e
	}
	f, e := strategy.NewFeatures(makeSession(scene, start, scene.ForceClose), map[string]float64{"NK225": 10, "TOPIX": .5}, params.Features)
	if e != nil {
		return nil, e
	}
	f.EnableResearch()
	end := scene.End
	if scene.Cutoff > 0 && scene.Cutoff < end {
		end = scene.Cutoff
	}
	for _, ref := range []string{"TOPIX", "NK225"} {
		for _, interval := range []int{60, 300} {
			bars, e := loadCandles(scene.Candles[ref][strconv.Itoa(interval)], interval, start, end)
			if e != nil {
				return nil, e
			}
			for _, bar := range bars {
				if _, e = f.AddCandles(ref, interval, []strategy.Candle{bar}, bar.Time+float64(interval)+params.Features.CandleDelay); e != nil {
					return nil, e
				}
			}
		}
	}
	return f, nil
}

type Comparable struct {
	Action, Owner                 string
	Side, Quantity                int
	DecisionIndex, FillIndex      int64
	DecisionTime, FillTime, Price float64
}
type Result struct {
	Session                                        string
	Actual, ExpectedActual, Shadow, ExpectedShadow []Comparable
	ActualEqual, ShadowEqual, Flat                 bool
	Gross, ExpectedGross                           float64
	Counts                                         map[string]int
}

// replay は代表3夜の原観測だけで移植版を進め、期待値を判断へ渡しません。
//
// 引数: scene(Scene)、expressions(map[string]string)。返り値: Resultとerrorです。
func replay(scene Scene, expressions map[string]string) (Result, error) {
	out := Result{Session: scene.Session}
	boards, counts, err := loadBoards(scene)
	if err != nil {
		return out, err
	}
	out.Counts = counts
	features, err := newFeatures(scene, scene.Start)
	if err != nil {
		return out, err
	}
	params, err := strategy.ParametersForMethod("NK225", "Night", "P05")
	if err != nil {
		return out, err
	}
	p, err := strategy.New(strategy.Config{Reference: "NK225", Product: "NK225mini", Cap: 10, CoreQuantity: 5, ExtraMaxQuantity: 5, LargeTick: 10, PointValue: 100, Parameters: params, RuleExpressions: expressions}, makeSession(scene, scene.Start, scene.ForceClose))
	if err != nil {
		return out, err
	}
	var pending []strategy.Signal
	seen := map[string]bool{}
	for _, board := range boards {
		o, err := features.OnBoard(board)
		if err != nil {
			return out, err
		}
		if board.Reference != "NK225" {
			continue
		}
		remaining := []strategy.Signal{}
		for _, s := range pending {
			if !o.QuoteOK || o.Bid <= 0 || o.Ask <= o.Bid || o.Index <= s.SourceIndex {
				remaining = append(remaining, s)
				continue
			}
			price := o.Ask
			if s.Side < 0 {
				price = o.Bid
			}
			f := strategy.Fill{SignalID: s.ID, ExecutionID: s.ID + "-実約定", HoldID: s.ID + "-実玉", Quantity: s.Quantity, Price: price, Time: o.Time}
			if s.Action == "close" {
				f.Closed = append([]strategy.LotTarget(nil), s.Targets...)
			}
			if err = p.OnFill(f); err != nil {
				return out, err
			}
			if err = p.OnOrderDone(s.ID); err != nil {
				return out, err
			}
			out.Actual = append(out.Actual, Comparable{s.Action, s.Owner, s.Side, s.Quantity, s.SourceIndex, o.Index, s.Time, o.Time, price})
		}
		pending = remaining
		signals, err := p.Observe(o, o.Time < scene.USOpen-900)
		if err != nil {
			return out, err
		}
		pending = append(pending, signals...)
		for _, s := range p.P05.ShadowPending {
			if s.Action != "new" || seen[s.ID] {
				continue
			}
			seen[s.ID] = true
			out.Shadow = append(out.Shadow, Comparable{Action: s.Action, Owner: s.Owner, Side: s.Side, Quantity: s.Quantity, DecisionIndex: s.SourceIndex, DecisionTime: s.Time})
		}
	}
	out.Flat = len(pending) == 0
	for _, l := range p.P05.Lots {
		out.Gross += l.Realized
		if l.Quantity != 0 {
			out.Flat = false
		}
	}
	return out, nil
}

// compare は再生完了後だけ保存期待注文を読み、全時刻・原行・方向・数量・価格を照合します。
//
// 引数: out(*Result)、old150/old151(string)。返り値: errorは期待資料の欠落です。
func compare(out *Result, old150, old151 string) error {
	var before struct {
		Cases []struct {
			Config struct {
				ID string `json:"id"`
			}
			Events []struct {
				Phase  string
				Signal strategy.Signal
			}
		}
	}
	if err := readJSON(filepath.Join(old150, out.Session+".json"), &before); err != nil {
		return err
	}
	for _, c := range before.Cases {
		if c.Config.ID != "B04" {
			continue
		}
		for _, e := range c.Events {
			s := e.Signal
			if e.Phase == "前半" && s.Action == "new" {
				out.ExpectedShadow = append(out.ExpectedShadow, Comparable{Action: s.Action, Owner: s.Owner, Side: s.Side, Quantity: s.Quantity, DecisionIndex: s.SourceIndex, DecisionTime: s.Time})
			}
		}
	}
	var prior struct {
		Cases []struct {
			Config struct {
				ID string `json:"id"`
			}
			Gross  float64
			Events []struct {
				Order struct {
					Action         string
					Side, Quantity int
					DecisionIndex  int64   `json:"decision_index"`
					DecisionTime   float64 `json:"decision_time"`
					Source         struct{ Owner string }
				}
				FillIndex int64   `json:"fill_index"`
				FillTime  float64 `json:"fill_time"`
				Price     float64
			}
		}
	}
	if err := readJSON(filepath.Join(old151, out.Session+".json"), &prior); err != nil {
		return err
	}
	found := false
	for _, c := range prior.Cases {
		if c.Config.ID != "P05" {
			continue
		}
		found = true
		out.ExpectedGross = c.Gross
		for _, e := range c.Events {
			s := e.Order
			out.ExpectedActual = append(out.ExpectedActual, Comparable{s.Action, s.Source.Owner, s.Side, s.Quantity, s.DecisionIndex, e.FillIndex, s.DecisionTime, e.FillTime, e.Price})
		}
	}
	if !found {
		return errors.New("P05保存期待がありません")
	}
	out.ActualEqual = reflect.DeepEqual(out.Actual, out.ExpectedActual) && out.Gross == out.ExpectedGross
	out.ShadowEqual = reflect.DeepEqual(out.Shadow, out.ExpectedShadow)
	return nil
}

// registrationOK は登録成功の二条件が揃うまで金融再生を拒否します。
//
// 引数: path(string)。返り値: errorは未登録又は失敗受領です。
func registrationOK(path string) error {
	if path == "" {
		return errors.New("金融再生には登録受領の明示指定が必要です")
	}
	var r struct {
		Registered bool
		Returncode *int
	}
	if err := readJSON(path, &r); err != nil {
		return err
	}
	if !r.Registered || r.Returncode == nil || *r.Returncode != 0 {
		return errors.New("登録成功が確認できません")
	}
	return nil
}

// main は固定代表3夜を登録後に限って一度だけ同値検査します。
//
// 引数: OS引数。返り値: なし。不一致又は上書き要求では失敗します。
func main() {
	registration := flag.String("registration", "", "登録受領JSON")
	manifest := flag.String("manifest", "../../preus149/data/原資料一覧149.json", "原入力目録")
	output := flag.String("out", "../results", "新規出力フォルダ")
	flag.Parse()
	if err := registrationOK(*registration); err != nil {
		panic(err)
	}
	set, err := rules.LoadFor("rules/NK225_P05.toml", "p05")
	if err != nil {
		panic(err)
	}
	var manifestData struct{ Sessions []Scene }
	if err = readJSON(*manifest, &manifestData); err != nil {
		panic(err)
	}
	selected := map[string]bool{"2026-09-30_Night": true, "2026-10-01_Night": true, "2026-10-21_Night": true}
	if err = os.MkdirAll(*output, 0755); err != nil {
		panic(err)
	}
	for _, s := range manifestData.Sessions {
		if !selected[s.Session] {
			continue
		}
		path := filepath.Join(*output, s.Session+".json")
		if _, err = os.Stat(path); !os.IsNotExist(err) {
			panic("既存結果の上書きはしません: " + path)
		}
	}
	failed, completed := false, 0
	for _, s := range manifestData.Sessions {
		if !selected[s.Session] {
			continue
		}
		result, err := replay(s, set.Expressions())
		if err != nil {
			panic(err)
		}
		if err = compare(&result, "../../preus150/results_round2", "../../hedge151/results_go"); err != nil {
			panic(err)
		}
		raw, err := json.MarshalIndent(result, "", "  ")
		if err != nil {
			panic(err)
		}
		if err = os.WriteFile(filepath.Join(*output, s.Session+".json"), raw, 0644); err != nil {
			panic(err)
		}
		fmt.Printf("%s 実玉一致=%t 影入口一致=%t 全返済=%t\n", s.Session, result.ActualEqual, result.ShadowEqual, result.Flat)
		failed = failed || !result.ActualEqual || !result.ShadowEqual || !result.Flat
		completed++
	}
	if completed != 3 || failed {
		os.Exit(1)
	}
}
