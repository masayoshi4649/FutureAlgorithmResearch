// 研究149は保存原板だけを読む独立再生器です。通信・実注文の機能は含みません。
package main

import (
	"bufio"
	"encoding/csv"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"futurealgorithm/sessiontrader/internal/rules"
	"futurealgorithm/sessiontrader/internal/strategy"
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

type StudyConfig struct {
	ID                 string   `json:"id"`
	Description        string   `json:"description"`
	CoreHour           float64  `json:"core_hour"`
	ExtraHour          float64  `json:"extra_hour"`
	Owners             []string `json:"owners"`
	Reset              bool     `json:"reset"`
	CloseBeforeMinutes float64  `json:"close_before_minutes"`
	RestartWaitMinutes float64  `json:"restart_wait_minutes"`
	KeepFeatures       bool     `json:"keep_features"`
	PostOriginalClocks bool     `json:"post_original_clocks"`
}

type rawLevel struct{ Price, Qty float64 }
type rawBook struct {
	CurrentPriceTime                                                      *string
	CurrentPrice                                                          float64
	Buy1, Buy2, Buy3, Buy4, Buy5, Buy6, Buy7, Buy8, Buy9, Buy10           rawLevel
	Sell1, Sell2, Sell3, Sell4, Sell5, Sell6, Sell7, Sell8, Sell9, Sell10 rawLevel
}

type Event struct {
	Phase         string          `json:"phase"`
	DecisionIndex int64           `json:"decision_index"`
	FillIndex     int64           `json:"fill_index"`
	Signal        strategy.Signal `json:"signal"`
	Fill          strategy.Fill   `json:"fill"`
	Gross         float64         `json:"gross"`
}

type Lot struct {
	Side, Quantity int
	Price          float64
	Owner, Parent  string
}
type Case struct {
	Config                          StudyConfig               `json:"config"`
	Events                          []Event                   `json:"events"`
	Diagnostics                     map[string]map[string]int `json:"diagnostics"`
	FirstFeatureKnown               map[string]float64        `json:"first_feature_known"`
	CancelledNew                    int                       `json:"cancelled_new"`
	MaxPerSide                      int                       `json:"max_per_side"`
	Gross, Profit, Loss, Unrealized float64
	Parents                         map[string]float64   `json:"parents"`
	Positions                       map[string]Lot       `json:"positions"`
	FinalPending                    []strategy.Signal    `json:"final_pending"`
	PostStarted                     float64              `json:"post_started"`
	PreFlatAt                       float64              `json:"pre_flat_at"`
	P                               *strategy.Portfolio  `json:"-"`
	Pending                         []strategy.Signal    `json:"-"`
	Phase                           string               `json:"-"`
	Last                            strategy.Observation `json:"-"`
	EntryFrom                       float64              `json:"-"`
	End                             float64              `json:"-"`
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

// newPortfolio は共通のD07を生成し、時計と対象担当だけ差し替えます。
//
// 引数: scene(Scene)、c(StudyConfig)、post(bool)、expressions(map[string]string)。
// 返り値: *strategy.Portfolio、最早新規秒、終了秒(float64)、errorです。
func newPortfolio(scene Scene, c StudyConfig, post bool, expressions map[string]string) (*strategy.Portfolio, float64, float64, error) {
	start, end := scene.Start, scene.ForceClose
	coreAt, extraAt := 0., 0.
	owners := c.Owners
	if c.CoreHour > 0 {
		coreAt = scene.Start + (c.CoreHour-17)*3600
	}
	if c.ExtraHour > 0 {
		extraAt = scene.Start + (c.ExtraHour-17)*3600
	}
	entryFrom := start
	if c.Reset && !post {
		end = scene.USOpen - c.CloseBeforeMinutes*60
	}
	if post {
		start = scene.USOpen
		entryFrom = start + c.RestartWaitMinutes*60
		coreAt = entryFrom
		extraAt = entryFrom
		if c.PostOriginalClocks {
			coreAt, extraAt = scene.USOpen+1320, scene.USOpen+1800
		}
		owners = nil
	}
	session := makeSession(scene, start, end)
	if c.Reset {
		session.StudyQuietOverride = true
		session.StudyQuietBefore = c.CloseBeforeMinutes * 60
		session.StudyQuietAfter = c.RestartWaitMinutes * 60
	}
	params, e := strategy.ParametersForMethod("NK225", "Night", "D07")
	if e != nil {
		return nil, 0, 0, e
	}
	p, e := strategy.New(strategy.Config{Reference: "NK225", Product: "NK225mini", Cap: 10, CoreQuantity: 5, ExtraMaxQuantity: 5, LargeTick: 10, PointValue: 100, Parameters: params, RuleExpressions: expressions}, session)
	if e != nil {
		return nil, 0, 0, e
	}
	p.StudyConfigure149(coreAt, extraAt, owners)
	return p, entryFrom, end, nil
}

// flat は当研究運転の実玉と未確定注文が全てゼロか確認します。
//
// 引数: p(*strategy.Portfolio)。返り値: boolは清算済みです。
func flat(p *strategy.Portfolio) bool {
	s := p.Status()
	if len(s.Pending) > 0 {
		return false
	}
	for _, q := range s.Positions {
		if q.Quantity > 0 {
			return false
		}
	}
	return true
}

// quoteOK は正常BBOだけを仮想約定の対象にします。
//
// 引数: o(strategy.Observation)。返り値: boolは正の買値より売値が高いことです。
func quoteOK(o strategy.Observation) bool {
	return o.QuoteOK && o.Bid > 0 && o.Ask > o.Bid && !math.IsInf(o.Ask, 0)
}

// diagnose は価格条件・準備・時計を独立した観測件数で記録します。
//
// 引数: c(*Case)、o(strategy.Observation)。返り値: なし。
func diagnose(c *Case, o strategy.Observation) {
	known := true
	for i := 0; i < 24; i++ {
		known = known && o.Research.Known[i]
	}
	if known && c.FirstFeatureKnown[c.Phase] == 0 {
		c.FirstFeatureKnown[c.Phase] = o.Time
	}
	for _, s := range c.P.Research.Sleeves {
		name := c.Phase + "/" + s.Name
		d := c.Diagnostics[name]
		if d == nil {
			d = map[string]int{}
			c.Diagnostics[name] = d
		}
		d["観測"]++
		if !quoteOK(o) {
			d["異常気配"]++
		}
		if !known {
			d["24列の一部未知"]++
		}
		if s.Source.Legacy != nil {
			if o.Time < c.P.Session.USOpen+s.Source.Legacy.Config.Parameters.Night.PostOpenPrepareSeconds {
				d["主担当時計禁止"]++
			}
		}
		if s.Source.Active != nil && s.Source.Active.Arm != 0 {
			d["入口準備中"]++
		}
		if s.Source.Active145 != nil && s.Source.Active145.Arm != 0 {
			d["入口準備中"]++
		}
	}
}

// process は前行の予約を次正常BBOで約定し、新しい判断を予約します。
//
// 引数: c(*Case)、o(strategy.Observation)。返り値: errorは上限・会計・時系列の破綻です。
func process(c *Case, o strategy.Observation) error {
	if quoteOK(o) {
		for _, sig := range c.Pending {
			if o.Index <= sig.SourceIndex {
				return errors.New("同原行約定")
			}
			price := o.Bid
			if sig.Side > 0 {
				price = o.Ask
			}
			hold := c.Phase + "/" + sig.ID
			fill := strategy.Fill{SignalID: sig.ID, ExecutionID: hold, HoldID: hold, Quantity: sig.Quantity, Price: price, Time: o.Time, Closed: sig.Targets, Fee: 0}
			gross := 0.
			parent := fmt.Sprintf("%s/%s/%d", c.Phase, sig.Owner, sig.Campaign)
			if sig.Action == "new" {
				c.Positions[hold] = Lot{Side: sig.Side, Quantity: sig.Quantity, Price: price, Owner: sig.Owner, Parent: parent}
			} else {
				closed := 0
				for _, target := range sig.Targets {
					lot, ok := c.Positions[target.ID]
					if !ok || lot.Quantity < target.Quantity || lot.Side != -sig.Side {
						return fmt.Errorf("所有玉不整合: %s", target.ID)
					}
					gain := float64(lot.Side*target.Quantity) * (price - lot.Price) * 100
					gross += gain
					c.Parents[lot.Parent] += gain
					lot.Quantity -= target.Quantity
					c.Positions[target.ID] = lot
					closed += target.Quantity
				}
				if closed != sig.Quantity {
					return errors.New("返済数量不整合")
				}
			}
			if e := c.P.OnFill(fill); e != nil {
				return e
			}
			if e := c.P.OnOrderDone(sig.ID); e != nil {
				return e
			}
			c.Gross += gross
			if gross > 0 {
				c.Profit += gross
			} else {
				c.Loss -= gross
			}
			c.Events = append(c.Events, Event{Phase: c.Phase, DecisionIndex: sig.SourceIndex, FillIndex: o.Index, Signal: sig, Fill: fill, Gross: gross})
		}
		c.Pending = nil
	}
	// ----------------------------------------
	// 既送信成行は境界後でも次正常気配で約定。現在行で返済判断して次正常行で返します。
	diagnose(c, o)
	signals, e := c.P.Observe(o, o.Time >= c.EntryFrom && o.Time < c.End)
	if e != nil {
		return e
	}
	c.Pending = append(c.Pending, signals...)
	long, short := 0, 0
	for _, p := range c.Positions {
		if p.Side > 0 {
			long += p.Quantity
		} else {
			short += p.Quantity
		}
	}
	c.MaxPerSide = max(c.MaxPerSide, long, short)
	if long > 10 || short > 10 {
		return errors.New("片側10枚超過")
	}
	if quoteOK(o) {
		c.Last = o
	}
	return nil
}

// selectObservation149 は後半へ渡す特徴履歴だけを事前固定条件で選びます。
//
// 引数: c(*Case)、full/reset(strategy.Observation)は二つの開始定義による当時観測です。
// 返り値: strategy.Observation。時刻・数量・売買状態の選択は行いません。
func selectObservation149(c *Case, full, reset strategy.Observation) strategy.Observation {
	if c.Phase == "後半" && !c.Config.KeepFeatures {
		return reset
	}
	return full
}

// runScene は二組の独立した特徴状態を全条件へ共用し、全売買状態を分離します。
//
// 引数: scene(Scene)、configs([]StudyConfig)、expressions(map[string]string)。
// 返り値: []*Case、原行件数map、error。KeepFeatures=falseのUS後だけUS前の板・足を除外します。
func runScene(scene Scene, configs []StudyConfig, expressions map[string]string) ([]*Case, map[string]int, error) {
	boards, counts, e := loadBoards(scene)
	if e != nil {
		return nil, nil, e
	}
	full, e := newFeatures(scene, scene.Start)
	if e != nil {
		return nil, nil, e
	}
	reset, e := newFeatures(scene, scene.USOpen)
	if e != nil {
		return nil, nil, e
	}
	cases := []*Case{}
	for _, cfg := range configs {
		p, from, end, e := newPortfolio(scene, cfg, false, expressions)
		if e != nil {
			return nil, nil, e
		}
		phase := "継続"
		if cfg.Reset {
			phase = "前半"
		}
		cases = append(cases, &Case{Config: cfg, P: p, Phase: phase, EntryFrom: from, End: end, Positions: map[string]Lot{}, Parents: map[string]float64{}, Diagnostics: map[string]map[string]int{}, FirstFeatureKnown: map[string]float64{}})
	}
	for _, board := range boards {
		o, e := full.OnBoard(board)
		if e != nil {
			return nil, nil, e
		}
		var after strategy.Observation
		if board.Time >= scene.USOpen {
			after, e = reset.OnBoard(board)
			if e != nil {
				return nil, nil, e
			}
			after.Index = o.Index
		}
		if board.Reference != "NK225" {
			continue
		}
		for _, c := range cases {
			if c.Config.Reset && c.Phase == "前半" && o.Time >= c.End && flat(c.P) {
				if c.PreFlatAt == 0 {
					c.PreFlatAt = o.Time
				}
			}
			if c.Config.Reset && c.Phase == "前半" && o.Time >= scene.USOpen && flat(c.P) {
				p, from, end, e := newPortfolio(scene, c.Config, true, expressions)
				if e != nil {
					return nil, nil, e
				}
				c.P = p
				c.Phase = "後半"
				c.EntryFrom = from
				c.End = end
				c.Pending = nil
				c.PostStarted = o.Time
			}
			obs := selectObservation149(c, o, after)
			if e = process(c, obs); e != nil {
				return nil, nil, fmt.Errorf("%s/%s: %w", scene.Session, c.Config.ID, e)
			}
			if c.Config.Reset && c.Phase == "前半" && o.Time >= c.End && flat(c.P) && c.PreFlatAt == 0 {
				c.PreFlatAt = o.Time
			}
		}
	}
	for _, c := range cases {
		for id, lot := range c.Positions {
			if lot.Quantity == 0 {
				delete(c.Positions, id)
				continue
			}
			price := c.Last.Bid
			if lot.Side < 0 {
				price = c.Last.Ask
			}
			c.Unrealized += float64(lot.Side*lot.Quantity) * (price - lot.Price) * 100
		}
		c.FinalPending = c.P.Status().Pending
		if !scene.Partial && (!flat(c.P) || len(c.Positions) > 0) {
			return nil, nil, fmt.Errorf("%s/%s: 完了夜に未決済又は予約あり", scene.Session, c.Config.ID)
		}
	}
	return cases, counts, nil
}

// main は登録受領の存在を必須として保存資料の独立研究だけを実行します。
//
// 引数: CLIのmanifest/configs/registration/out/scene。返り値: なし。失敗時は非零終了です。
func main() {
	manifest := flag.String("manifest", "", "原資料一覧")
	configPath := flag.String("configs", "../configs_round2.json", "固定条件")
	registration := flag.String("registration", "", "登録受領")
	output := flag.String("out", "../results_go_round2", "結果先")
	only := flag.String("scene", "", "一場限定")
	flag.Parse()
	if *registration == "" {
		panic("金融再生には登録受領が必要です")
	}
	var receipt map[string]any
	if e := readJSON(*registration, &receipt); e != nil {
		panic(e)
	}
	ok := receipt["returncode"] == float64(0) || receipt["registered"] == true
	if !ok {
		panic("登録完了を確認できません")
	}
	var input struct {
		Sessions []Scene `json:"sessions"`
	}
	if e := readJSON(*manifest, &input); e != nil {
		panic(e)
	}
	var configs []StudyConfig
	if e := readJSON(*configPath, &configs); e != nil {
		panic(e)
	}
	loaded, e := rules.Load("NK225_D07.toml")
	if e != nil {
		panic(e)
	}
	if e = os.MkdirAll(*output, 0755); e != nil {
		panic(e)
	}
	for _, scene := range input.Sessions {
		if *only != "" && *only != scene.Session {
			continue
		}
		target := filepath.Join(*output, scene.Session+".json")
		if _, e = os.Stat(target); e == nil {
			panic("既存結果を再計算しません: " + target)
		}
		started := time.Now()
		cases, counts, e := runScene(scene, configs, loaded.Expressions())
		if e != nil {
			panic(e)
		}
		value := map[string]any{"scene": scene, "cases": cases, "counts": counts, "elapsed_seconds": time.Since(started).Seconds(), "fees": 0, "price": "判断後の次正常ラージBBO代理", "real_orders": 0}
		raw, e := json.MarshalIndent(value, "", "  ")
		if e != nil {
			panic(e)
		}
		if e = os.WriteFile(target, raw, 0644); e != nil {
			panic(e)
		}
		fmt.Println(scene.Session, "完了", time.Since(started))
	}
}
