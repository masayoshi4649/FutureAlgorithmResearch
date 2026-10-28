package main

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"futurealgorithm/sessiontrader/internal/strategy"
	"io"
	"math"
	"os"
	"path/filepath"
	"sort"
	"sync"
	"time"
)

type Quantiles165 struct {
	Count                                        int `json:"count"`
	Minimum, Q25, Median, Q75, Q90, Q95, Maximum float64
}
type FeatureReport165 struct {
	Session, Split, Path, SHA256 string
	Counts                       map[string]int
	Values                       map[string]Quantiles165
	SourceBefore, SourceAfter    int64
	SizeBefore, SizeAfter        int64
}

// quantile165 は並べた標本の線形補間分位を返します。
//
// 引数: sorted([]float64)、q(float64)。返り値: float64。
func quantile165(sorted []float64, q float64) float64 {
	if len(sorted) == 0 {
		return 0
	}
	pos := q * float64(len(sorted)-1)
	a := int(math.Floor(pos))
	b := int(math.Ceil(pos))
	return sorted[a] + (sorted[b]-sorted[a])*(pos-float64(a))
}

// summarize165 はラベルを持たない特徴標本だけを要約します。
//
// 引数: values([]float64)。返り値: Quantiles165。
func summarize165(values []float64) Quantiles165 {
	sort.Float64s(values)
	if len(values) == 0 {
		return Quantiles165{}
	}
	return Quantiles165{len(values), values[0], quantile165(values, .25), quantile165(values, .5), quantile165(values, .75), quantile165(values, .9), quantile165(values, .95), values[len(values)-1]}
}

// measureWindow165 は価格更新時の窓特徴を分布へ加えます。
//
// 引数: name(string)、b(Band165)、values(map[string][]float64)、counts(map[string]int)。返り値: なし。
func measureWindow165(name string, b Band165, values map[string][]float64, counts map[string]int) {
	if !b.Known {
		counts[name+"_未知"]++
		return
	}
	counts[name+"_既知"]++
	metrics := map[string]float64{"実経過秒": b.Elapsed, "価格遷移数": float64(b.Events), "気配差": b.Spread, "両気配同方向移動絶対幅": math.Max(0, math.Max(math.Min(b.BidMove, b.AskMove), math.Min(-b.BidMove, -b.AskMove))), "中値変化絶対幅": math.Abs(b.MidMove), "全価格更新幅": b.GrossPriceMove, "方向集中": math.Max(b.UpFraction, 1-b.UpFraction), "片側だけ上値移動回数": b.AskOnlyUp, "片側だけ下値移動回数": b.BidOnlyDown, "数量更新数": float64(b.QuantityEvents), "共通深板数量更新数": float64(b.CommonDepthEvents)}
	if b.QuantityKnown {
		metrics["買同価格回復"] = b.BidRefill
		metrics["売同価格回復"] = b.AskRefill
		metrics["買同価格減少"] = b.BidDeplete
		metrics["売同価格減少"] = b.AskDeplete
	} else {
		counts[name+"_数量未知"]++
	}
	if b.CommonDepthEvents > 0 {
		metrics["共通買板回復"] = b.CommonBidUp
		metrics["共通売板回復"] = b.CommonAskUp
	}
	for key, v := range metrics {
		if finite165(v) {
			values[name+"/"+key] = append(values[name+"/"+key], v)
		}
	}
	for _, d := range []float64{1, -1} {
		counts[name+"_方向側分母"]++
		shift := math.Min(d*b.BidMove, d*b.AskMove)
		fraction := b.UpFraction
		if d < 0 {
			fraction = 1 - fraction
		}
		if shift >= 10 {
			counts[name+"_両側10円"]++
		}
		if shift >= 20 {
			counts[name+"_両側20円"]++
			if fraction >= .625 {
				counts[name+"_両側20円かつ集中0.625"]++
			}
		}
	}
}

// measureScene165 は前半固定期間の原板だけを読み、金融ラベルを開きません。
//
// 引数: scene(Scene)。返り値: FeatureReport165とerror。Source/注文/約定器は呼びません。
func measureScene165(scene Scene) (FeatureReport165, error) {
	r := FeatureReport165{Session: scene.Session, Split: scene.Split, Path: scene.Books["NK225"], Counts: map[string]int{}, Values: map[string]Quantiles165{}}
	if scene.Kind != "Night" || (scene.Split != "train" && scene.Split != "validation") {
		return r, errors.New("前20夜以外の特徴抽出は禁止")
	}
	f, e := os.Open(r.Path)
	if e != nil {
		return r, e
	}
	defer f.Close()
	st, e := f.Stat()
	if e != nil {
		return r, e
	}
	r.SourceBefore = st.ModTime().UnixNano()
	r.SizeBefore = st.Size()
	hash := sha256.New()
	sc := bufio.NewScanner(io.TeeReader(f, hash))
	sc.Buffer(make([]byte, 65536), 8*1024*1024)
	previous := scene.Start
	var index, line int64
	h := &BookFeatures165{}
	eventState, clockState := &Repricing165{}, &Repricing165{Clock: true}
	values := map[string][]float64{}
	clock := math.Inf(-1)
	for sc.Scan() {
		line++
		r.Counts["全物理行"]++
		var raw rawBook
		if e = json.Unmarshal(sc.Bytes(), &raw); e != nil {
			return r, e
		}
		if raw.CurrentPriceTime == nil {
			r.Counts["時計欠測"]++
			continue
		}
		at, err := stamp(*raw.CurrentPriceTime)
		if err != nil {
			r.Counts["時計欠測"]++
			continue
		}
		if at < scene.Start || at > scene.End || (scene.Cutoff > 0 && at >= scene.Cutoff) {
			r.Counts["場外"]++
			continue
		}
		if at < previous {
			r.Counts["巻戻り"]++
			continue
		}
		if raw.CurrentPrice <= 0 || !finite165(raw.CurrentPrice) {
			r.Counts["Last欠測"]++
			continue
		}
		previous = at
		b := strategy.Board{Reference: "NK225", Time: at, Received: at, Last: raw.CurrentPrice, Bid: raw.Buy1.Price, Ask: raw.Sell1.Price, BidQuantity: raw.Buy1.Qty, AskQuantity: raw.Sell1.Qty}
		buys := [10]rawLevel{raw.Buy1, raw.Buy2, raw.Buy3, raw.Buy4, raw.Buy5, raw.Buy6, raw.Buy7, raw.Buy8, raw.Buy9, raw.Buy10}
		sells := [10]rawLevel{raw.Sell1, raw.Sell2, raw.Sell3, raw.Sell4, raw.Sell5, raw.Sell6, raw.Sell7, raw.Sell8, raw.Sell9, raw.Sell10}
		for k := range buys {
			b.BidLevels[k] = strategy.ResearchLevel{Price: buys[k].Price, Quantity: buys[k].Qty}
			b.AskLevels[k] = strategy.ResearchLevel{Price: sells[k].Price, Quantity: sells[k].Qty}
		}
		v := h.add165(b, index, line)
		stateEvent, stateClock := eventState.step165(v, b), clockState.step165(v, b)
		index++
		if at < scene.USOpen+900 || at >= scene.ForceClose {
			continue
		}
		r.Counts["米国後採用原行"]++
		if !validBook165(b) {
			r.Counts["米国後不正板"]++
			continue
		}
		r.Counts["米国後正常板"]++
		if at == clock {
			r.Counts["直前正常と同価格時計"]++
		} else {
			r.Counts["独立価格時計"]++
			clock = at
		}
		if !v.Changed {
			r.Counts["BBO価格不変"]++
			continue
		}
		r.Counts["価格更新観測"]++
		for _, state := range []StateView165{stateEvent, stateClock} {
			key := state.Window + "_状態/"
			if state.Buy.Active {
				r.Counts[key+"上価格帯維持中"]++
			}
			if state.Sell.Active {
				r.Counts[key+"下価格帯維持中"]++
			}
			if state.ConfirmedSide != 0 {
				r.Counts[key+"新価格帯維持成立"]++
				hold := state.Buy
				if state.ConfirmedSide < 0 {
					hold = state.Sell
				}
				if hold.QuantitySupport {
					r.Counts[key+"同価格支持回復あり"]++
				}
				if hold.SupplyPassed {
					r.Counts[key+"反対回復価格通過あり"]++
				}
			}
			if state.RetestSide != 0 {
				r.Counts[key+"価格だけの新押戻り回復"]++
				hold := state.Buy
				if state.RetestSide < 0 {
					hold = state.Sell
				}
				if hold.SupplyPassed {
					r.Counts[key+"反対回復価格通過と新押戻り回復"]++
				}
			}
		}
		measureWindow165("E08", v.Event8, values, r.Counts)
		measureWindow165("E32", v.Event32, values, r.Counts)
		measureWindow165("T15", v.Clock15, values, r.Counts)
	}
	if e = sc.Err(); e != nil {
		return r, e
	}
	r.SHA256 = hex.EncodeToString(hash.Sum(nil))
	r.Counts["全採用原行"] = int(index)
	r.Counts["全不正板"] = h.InvalidRows
	r.Counts["全60秒超空白"] = h.LongGaps
	matched := false
	for _, fp := range scene.Fingerprints {
		if filepath.Clean(fp.Path) == filepath.Clean(r.Path) {
			matched = fp.SHA256 == r.SHA256
			break
		}
	}
	if !matched {
		return r, errors.New("入力目録と原板SHAが一致しません")
	}
	st, e = os.Stat(r.Path)
	if e != nil {
		return r, e
	}
	r.SourceAfter = st.ModTime().UnixNano()
	r.SizeAfter = st.Size()
	if r.SourceBefore != r.SourceAfter || r.SizeBefore != r.SizeAfter {
		return r, errors.New("原板が読取中に変化")
	}
	for key, v := range values {
		r.Values[key] = summarize165(v)
	}
	return r, nil
}

// runFeatureMeasure165 は前20夜の特徴を並列計測し、場同重みの分位を保存します。
//
// 引数: manifest/out(string)、workers(int)。返り値: error。売買条件の採点は一切含みません。
func runFeatureMeasure165(manifest, out string, workers int) error {
	if workers < 1 || workers > 8 {
		return errors.New("並列数は1〜8")
	}
	if _, e := os.Stat(out); e == nil {
		return errors.New("既存診断の上書きは禁止")
	}
	var m struct {
		Sessions []Scene `json:"sessions"`
	}
	if e := readJSON(manifest, &m); e != nil {
		return e
	}
	scenes := []Scene{}
	for _, s := range m.Sessions {
		if s.Split == "train" || s.Split == "validation" {
			scenes = append(scenes, s)
		}
	}
	if len(m.Sessions) != 27 || len(scenes) != 20 {
		return errors.New("固定Night27/前20と一致しません")
	}
	type jobResult struct {
		r FeatureReport165
		e error
	}
	jobs := make(chan Scene)
	answers := make(chan jobResult, len(scenes))
	var wg sync.WaitGroup
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for s := range jobs {
				r, e := measureScene165(s)
				answers <- jobResult{r, e}
			}
		}()
	}
	go func() {
		for _, s := range scenes {
			jobs <- s
		}
		close(jobs)
		wg.Wait()
		close(answers)
	}()
	reports := []FeatureReport165{}
	for a := range answers {
		if a.e != nil {
			return fmt.Errorf("%s:%w", a.r.Session, a.e)
		}
		reports = append(reports, a.r)
		fmt.Printf("特徴のみ完了 %s 価格更新=%d\n", a.r.Session, a.r.Counts["価格更新観測"])
	}
	sort.Slice(reports, func(i, j int) bool { return reports[i].Session < reports[j].Session })
	aggregate := map[string][]float64{}
	for _, r := range reports {
		for k, v := range r.Values {
			if v.Count > 0 {
				aggregate[k+"/場中央値"] = append(aggregate[k+"/場中央値"], v.Median)
				aggregate[k+"/場75分位"] = append(aggregate[k+"/場75分位"], v.Q75)
				aggregate[k+"/場90分位"] = append(aggregate[k+"/場90分位"], v.Q90)
			}
		}
	}
	equal := map[string]Quantiles165{}
	for k, v := range aggregate {
		equal[k] = summarize165(v)
	}
	sha, e := hashFile164(manifest)
	if e != nil {
		return e
	}
	doc := map[string]any{"completed": true, "financial_runs": 0, "labels_read": false, "future_or_us_data": false, "manifest_sha256": sha, "sessions": reports, "equal_session_quantiles": equal, "created_at": time.Now().Format(time.RFC3339), "definitions": map[string]any{"原板": "NK225だけ・元採番・原行順", "採点時間枠": "US+15分以上/force_close未満", "特徴標本": "価格が変化した現在原行。数量のみ・不変原行は価格イベント分母に含めない", "同時計": "順序だけ使用、真の受信秒内と称さない", "量": "同価格の共通可視数量、正負を分離。取消/約定を識別しない", "未知": "不正BBO/60秒超空白で区間破棄。現在からの窓範囲上限60秒、T15端点遅れ15秒", "数量平均": "最良価格又は数量が変わった正常数量原行の数で平均。同一snapshotを反復しても分母は増えない", "分位": "各場内の分位をまず計算し、その20場分の分位分布を示す。金融ラベル・基準結果は未読"}}
	data, e := json.MarshalIndent(doc, "", "  ")
	if e != nil {
		return e
	}
	if e = os.MkdirAll(filepath.Dir(out), 0755); e != nil {
		return e
	}
	return os.WriteFile(out, data, 0644)
}

// main は特徴診断・定義出力と、登録後の段階再生を分離します。
//
// 引数: CLIフラグ。返り値: なし。金融は許可・全指紋・後半凍結を確認してから開始します。
func main() {
	mode := flag.String("mode", "replay", "features又は登録後replay")
	manifest := flag.String("manifest", "../inputs165.json", "原資料目録")
	out := flag.String("out", "", "保存先")
	workers := flag.Int("workers", 8, "並列数")
	export := flag.String("export-configs", "", "金融0の定義出力先")
	configs := flag.String("configs", "configs165.json", "固定14定義")
	spec := flag.String("spec", "../計画165.md", "事前計画")
	permission := flag.String("registration", "", "段階許可")
	stage := flag.String("stage", "train_validation", "前20又は後7")
	freeze := flag.String("freeze", "", "後半前の選択凍結")
	flag.Parse()
	var e error
	if *export != "" {
		e = saveNew165(*export, configs165())
	} else if *mode == "features" {
		if *out == "" {
			e = fmt.Errorf("特徴の保存先が必要")
		} else {
			e = runFeatureMeasure165(*manifest, *out, *workers)
		}
	} else if *mode == "replay" {
		if *permission == "" || *out == "" {
			e = fmt.Errorf("金融には登録段階許可と新しい保存先が必須")
		} else if e = validateConfigs165(*configs); e == nil {
			var st Stage164
			var sources []Fingerprint164
			st, sources, e = gate165(*stage, *permission, *manifest, *spec, *configs, *freeze)
			if e == nil {
				_, e = execute165(*manifest, *out, *workers, st, sources)
			}
		}
	} else {
		e = fmt.Errorf("未知の実行モード")
	}
	if e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(2)
	}
}
