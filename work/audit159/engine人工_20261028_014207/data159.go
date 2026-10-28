package main

import (
	"bufio"
	"encoding/csv"
	"encoding/json"
	"futurealgorithm/sessiontrader/internal/strategy"
	"io"
	"math"
	"os"
	"sort"
	"strconv"
	"strings"
	"time"
)

type Scene struct {
	Kind       string                       `json:"kind"`
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
	extra := scene.USOpen + 1800
	if scene.Kind == "Day" {
		extra = scene.Start + 13500
	}
	return strategy.Session{ID: scene.Session, Kind: scene.Kind, Start: start, End: scene.End, ForceClose: end, USOpen: scene.USOpen, ExtraAt: extra}
}

// newFeatures は指定開始からだけ指標と始値を作り直します。
//
// 引数: scene(Scene)、start(float64)。返り値: *strategy.Featuresとerrorです。
func newFeatures(scene Scene, start float64) (*strategy.Features, error) {
	params, e := strategy.ParametersForMethod("NK225", scene.Kind, "D07")
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
