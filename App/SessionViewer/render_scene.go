package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"path/filepath"
	"strconv"
	"strings"
	"time"
	"unicode"
)

const (
	chartBackground = "#0c1520"
	chartCard       = "#111e2b"
	chartPlot       = "#0d1925"
	chartGrid       = "#24384b"
	chartZero       = "#698097"
	chartText       = "#e0eaf3"
	chartMuted      = "#9cafc1"
	chartPrice      = "#78c8f0"
	chartShort      = "#ee9baf"
	chartLong       = "#76d6ce"
	chartRealized   = "#b5a5f2"
	chartUnrealized = "#e9c17d"
)

type chartPoint struct{ X, Y float64 }
type chartBox struct{ X, Y, W, H float64 }
type chartValue struct {
	T float64
	V *float64
}
type chartCandle struct {
	Start, End             float64
	Open, High, Low, Close *float64
}
type chartPrimitive struct {
	Kind, Color, Role, Text, Anchor string
	Pane                            int
	Box                             chartBox
	Points                          []chartPoint
	Stroke, Size                    float64
	Clip                            bool
}
type chartPane struct {
	Name, Label, Color string
	Card, Plot         chartBox
	Low, High, ZeroY   float64
	Points             []chartValue
	Segments           [][]chartPoint
	Single             []chartPoint
}
type chartScene struct {
	Width, Height int
	Title         string
	Metadata      []byte
	From, To      float64
	Panes         []chartPane
	Ops           []chartPrimitive
}

// validateChartDimensions はメモリを確保する前に画像寸法の上限を確認します。
//
// 引数: width/height(int)。返り値: error。PNGとSVGで同じ制約です。
func validateChartDimensions(width, height int) error {
	if width < 800 || width > 2400 || height < 700 || height > 2400 {
		return fmt.Errorf("画像寸法は幅800〜2400・高さ700〜2400です")
	}
	return nil
}

// chartClean は画像の一行ラベルを制御文字と無効XML文字から守ります。
//
// 引数: value(string)。返り値: string。元のメタデータJSONは変更しません。
func chartClean(value string) string {
	return strings.Map(func(r rune) rune {
		if unicode.IsControl(r) || r == 0xfffe || r == 0xffff {
			return ' '
		}
		return r
	}, value)
}

// chartFit は和文と欧文の幅を見積もり、ラベルを描画幅に収めます。
//
// 引数: value(string)、width/size(float64)。返り値: string。長いラベルは省略記号付きです。
func chartFit(value string, width, size float64) string {
	value = chartClean(value)
	used := 0.0
	out := []rune{}
	for _, r := range value {
		advance := size
		if r < 128 {
			advance = size * 0.58
		}
		if used+advance > width-size {
			return string(out) + "…"
		}
		out = append(out, r)
		used += advance
	}
	return string(out)
}

// chartNumber は軸の値を読みやすい桁区切りと小数で表します。
//
// 引数: value(float64)。返り値: string。極端な値は指数表記にします。
func chartNumber(value float64) string {
	if !finite(value) {
		return "不明"
	}
	if math.Abs(value) < 1e-9 {
		return "0"
	}
	if math.Abs(value) > 1e9 || math.Abs(value) < 0.01 {
		return strconv.FormatFloat(value, 'g', 3, 64)
	}
	s := strconv.FormatFloat(value, 'f', 2, 64)
	s = strings.TrimRight(strings.TrimRight(s, "0"), ".")
	parts := strings.SplitN(s, ".", 2)
	a := parts[0]
	sign := ""
	if strings.HasPrefix(a, "-") {
		sign = "-"
		a = a[1:]
	}
	for i := len(a) - 3; i > 0; i -= 3 {
		a = a[:i] + "," + a[i:]
	}
	if len(parts) > 1 {
		a += "." + parts[1]
	}
	return sign + a
}

// chartStamp は絶対時計をJSTの月日・時刻として描画します。
//
// 引数: value(float64、ミリ秒)、short(bool)。返り値: string。
func chartStamp(value float64, short bool) string {
	t := time.UnixMilli(int64(value)).In(japan)
	if short {
		return t.Format("01/02 15:04:05")
	}
	return t.Format("2006/01/02 15:04:05.000")
}

// chartColumn は列名から位置を探し、省略された契約には既定位置を使います。
//
// 引数: columns([]string)、name(string)、fallback(int)。返り値: int。明示列にない場合は-1です。
func chartColumn(columns []string, name string, fallback int) int {
	if len(columns) == 0 {
		return fallback
	}
	for i, c := range columns {
		if c == name {
			return i
		}
	}
	return -1
}

// chartCell は不足・null・非有限値を未知として読みます。
//
// 引数: row([]any)、index(int)。返り値: *float64。
func chartCell(row []any, index int) *float64 {
	if index < 0 || index >= len(row) {
		return nil
	}
	v, ok := numeric(row[index])
	if !ok {
		return nil
	}
	return &v
}

// chartSeries は可視化済みの列を読み、nullと同時計の原順序を保ちます。
//
// 引数: data(DataResponse)、name(string)。返り値: []chartValueとerror。原板は読みません。
func chartSeries(data DataResponse, name string) ([]chartValue, error) {
	rows, cols := data.States, data.StateColumns
	valueIndex := map[string]int{"short": 4, "long": 3, "realized": 5, "unrealized": 6}[name]
	field := map[string]string{"short": "short_qty", "long": "long_qty", "realized": "realized_pnl_yen", "unrealized": "unrealized_pnl_yen"}[name]
	if name == "price" {
		rows, cols = data.Prices, data.PriceColumns
		field = data.CandlePrice
		if field == "" {
			field = "last"
		}
		valueIndex = map[string]int{"last": 2, "bid": 3, "ask": 4}[field]
	}
	ti, vi := chartColumn(cols, "t", 0), chartColumn(cols, field, valueIndex)
	out := []chartValue{}
	for _, row := range rows {
		at := chartCell(row, ti)
		if at == nil {
			return nil, fmt.Errorf("%sの時刻が不正です", name)
		}
		if len(out) > 0 && *at < out[len(out)-1].T {
			return nil, fmt.Errorf("%sの時刻順が不正です", name)
		}
		value := chartCell(row, vi)
		if name == "price" && field == "mid" {
			bid, ask := chartCell(row, chartColumn(cols, "bid", 3)), chartCell(row, chartColumn(cols, "ask", 4))
			value = nil
			if bid != nil && ask != nil && *bid < *ask {
				v := *bid/2 + *ask/2
				value = &v
			}
		}
		out = append(out, chartValue{*at, value})
	}
	return out, nil
}

// chartCandles はAPIのOHLC列をそのまま取り出し、欠測足を埋めません。
//
// 引数: data(DataResponse)。返り値: []chartCandleとerror。
func chartCandles(data DataResponse) ([]chartCandle, error) {
	out := []chartCandle{}
	names := []string{"t", "end_ms", "open", "high", "low", "close"}
	indices := make([]int, 6)
	for i, n := range names {
		indices[i] = chartColumn(data.CandleColumns, n, i)
	}
	for _, row := range data.Candles {
		start, end := chartCell(row, indices[0]), chartCell(row, indices[1])
		if start == nil || end == nil || *end <= *start {
			return nil, fmt.Errorf("分足の時計範囲が不正です")
		}
		out = append(out, chartCandle{*start, *end, chartCell(row, indices[2]), chartCell(row, indices[3]), chartCell(row, indices[4]), chartCell(row, indices[5])})
	}
	return out, nil
}

// chartClipTime は原時計上で線分を先にクリップし、遠いprefixを巨大画素座標へ変換しません。
//
// 引数: a/b(chartPoint、Xは時計)、from/to(float64)。返り値: chartPoint2個と採用bool。
func chartClipTime(a, b chartPoint, from, to float64) (chartPoint, chartPoint, bool) {
	if a.X > b.X {
		a, b = b, a
	}
	if b.X < from || a.X > to {
		return a, b, false
	}
	originalA, originalB := a, b
	interpolate := func(at float64) chartPoint {
		if originalA.X == originalB.X {
			return chartPoint{at, originalA.Y}
		}
		ratio := (at - originalA.X) / (originalB.X - originalA.X)
		return chartPoint{at, originalA.Y*(1-ratio) + originalB.Y*ratio}
	}
	if a.X < from {
		a = interpolate(from)
	}
	if b.X > to {
		b = interpolate(to)
	}
	return a, b, finite(a.Y) && finite(b.Y)
}

// chartPaths は線又は階段を既知区間だけで構築し、nullでは別の線へ切断します。
//
// 引数: rows([]chartValue)、step(bool)、from/to(float64)。返り値: 経路([][]chartPoint)、孤立点([]chartPoint)。
func chartPaths(rows []chartValue, step bool, from, to float64) ([][]chartPoint, []chartPoint) {
	paths := [][]chartPoint{}
	single := []chartPoint{}
	current := []chartPoint{}
	flush := func() {
		if len(current) > 1 {
			paths = append(paths, current)
		}
		current = nil
	}
	add := func(a, b chartPoint) {
		a, b, ok := chartClipTime(a, b, from, to)
		if !ok {
			return
		}
		if len(current) == 0 || current[len(current)-1] != a {
			flush()
			current = append(current, a)
		}
		current = append(current, b)
	}
	var previous *chartValue
	for i := range rows {
		r := rows[i]
		if r.V == nil {
			if step && previous != nil {
				add(chartPoint{previous.T, *previous.V}, chartPoint{r.T, *previous.V})
			}
			flush()
			previous = nil
			continue
		}
		if previous != nil {
			a, b := chartPoint{previous.T, *previous.V}, chartPoint{r.T, *r.V}
			if step {
				add(a, chartPoint{r.T, a.Y})
				add(chartPoint{r.T, a.Y}, b)
			} else {
				add(a, b)
			}
		}
		if (i == 0 || rows[i-1].V == nil) && (i == len(rows)-1 || rows[i+1].V == nil) && r.T >= from && r.T <= to {
			single = append(single, chartPoint{r.T, *r.V})
		}
		previous = &r
	}
	flush()
	return paths, single
}

// chartAxis は極端な値でも有限の軸を作り、PLを個別にゼロ中央へ置きます。
//
// 引数: values([]float64)、name(string)。返り値: 最小/最大(float64)。
func chartAxis(values []float64, name string) (float64, float64) {
	low, high := 0.0, 1.0
	if len(values) > 0 {
		low, high = values[0], values[0]
		for _, v := range values {
			low = math.Min(low, v)
			high = math.Max(high, v)
		}
	}
	if name == "realized" || name == "unrealized" {
		extent := math.Max(1, math.Max(math.Abs(low), math.Abs(high)))
		if v := extent * 1.1; finite(v) {
			extent = v
		}
		return -extent, extent
	}
	if name != "price" {
		high = math.Max(1, high)
		if v := math.Ceil(high * 1.1); finite(v) {
			high = v
		}
		return 0, high
	}
	pad := math.Max(1, (high-low)*.08)
	if !finite(pad) {
		pad = 0
	}
	if v := low - pad; finite(v) {
		low = v
	}
	if v := high + pad; finite(v) {
		high = v
	}
	if low == high {
		low *= .99
		if low == high {
			high = low + 1
		}
	}
	return low, high
}

// chartX は範囲内の時計だけを画素へ写します。
//
// 引数: at/from/to(float64)、box(chartBox)。返り値: float64。
func chartX(at, from, to float64, box chartBox) float64 { return box.X + (at-from)/(to-from)*box.W }

// chartY は大振幅でhi-loが溢れないよう正規化して縦位置へ写します。
//
// 引数: value/low/high(float64)、box(chartBox)。返り値: float64。
func chartY(value, low, high float64, box chartBox) float64 {
	scale := math.Max(1, math.Max(math.Abs(low), math.Abs(high)))
	fraction := (value/scale - low/scale) / (high/scale - low/scale)
	return box.Y + (1-fraction)*box.H
}

// chartAddText は同じ位置・文字サイズのラベルを共通描画列へ加えます。
//
// 引数: s(*chartScene)、pane(int)、x/y/size(float64)、text/color/anchor(string)。返り値: なし。
func chartAddText(s *chartScene, pane int, x, y, size float64, text, color, anchor string) {
	s.Ops = append(s.Ops, chartPrimitive{Kind: "text", Pane: pane, Box: chartBox{X: x, Y: y}, Size: size, Text: chartClean(text), Color: color, Anchor: anchor})
}

// buildChartScene は5段の軸・線・足・移管記号を一つの描画列へ固定します。
//
// 引数: data(DataResponse)、width/height(int)。返り値: *chartSceneとerror。ファイルは作りません。
func buildChartScene(data DataResponse, width, height int) (*chartScene, error) {
	if err := validateChartDimensions(width, height); err != nil {
		return nil, err
	}
	from, to := data.Range.FromMS, data.Range.ToMS
	if !finite(from) || !finite(to) || to <= from || !finite(to-from) {
		return nil, fmt.Errorf("画像の表示時刻範囲が不正です")
	}
	mode, err := parseDisplayMode(data.Interval, data.CandlePrice)
	if err != nil {
		return nil, err
	}
	encoded, err := json.Marshal(data)
	if err != nil {
		return nil, fmt.Errorf("画像元データをJSON化できません: %w", err)
	}
	sum := sha256.Sum256(encoded)
	metadata := map[string]any{"resource": data.Resource, "range": data.Range, "interval": mode.Interval, "candle_price": mode.Price, "summary": data.Summary, "summary_at_ms": data.Range.ToMS, "files": data.Files, "sampling": data.Sampling, "quality": data.Quality, "clock": "CurrentPriceTime", "data_sha256": hex.EncodeToString(sum[:])}
	meta, err := json.Marshal(metadata)
	if err != nil {
		return nil, err
	}
	// JSONとしての意味を保持し、XML文字データへ入れられない非文字はJSONのUnicodeエスケープへ移します。
	meta = bytes.ReplaceAll(meta, []byte("\ufffe"), []byte(`\ufffe`))
	meta = bytes.ReplaceAll(meta, []byte("\uffff"), []byte(`\uffff`))
	method := data.Resource.MethodID
	if method == "*" {
		method = "全手法（合計）"
	}
	if method == "" {
		method = "手法ID未指定"
	}
	title := strings.Join([]string{data.Resource.Symbol, data.Resource.Product, data.Resource.Session, method}, " / ")
	s := &chartScene{Width: width, Height: height, Title: chartClean(title), Metadata: meta, From: from, To: to}
	s.Ops = append(s.Ops, chartPrimitive{Kind: "rect", Pane: -1, Box: chartBox{0, 0, float64(width), float64(height)}, Color: chartBackground})
	fontSize := math.Max(12, math.Min(17, float64(width)/105))
	small := math.Max(11, fontSize-2)
	titleSize := fontSize + 5
	compact := height < 950
	margin, gap := 18.0, 9.0
	headerH, footerH := 96.0, 100.0
	if compact {
		margin, gap = 14, 7
		headerH, footerH = 80, 70
	}
	chartAddText(s, -1, margin, margin+titleSize, titleSize, chartFit(title, float64(width)-2*margin, titleSize), chartText, "start")
	interval := "raw（価格線）"
	if mode.Minutes > 0 {
		interval = mode.Interval + "分足（OHLC・保有/PLは区間末）"
	}
	chartAddText(s, -1, margin, margin+titleSize+fontSize+6, fontSize, chartFit("表示: "+interval+" / "+strings.ToUpper(mode.Price)+"　　"+chartStamp(from, false)+" 〜 "+chartStamp(to, false)+" JST", float64(width)-2*margin, fontSize), chartMuted, "start")
	chartAddText(s, -1, margin, margin+titleSize+fontSize+small+12, small, "▲買新規　▼売新規　○返済　◆管理外移管（返済・利確ではない）", chartMuted, "start")
	labels := []string{"価格", "売保有枚数", "買保有枚数", "累積確定損益（円）", "含み損益（円）"}
	names := []string{"price", "short", "long", "realized", "unrealized"}
	colors := []string{chartPrice, chartShort, chartLong, chartRealized, chartUnrealized}
	weights := []float64{.28, .16, .16, .20, .20}
	candles, err := chartCandles(data)
	if err != nil {
		return nil, err
	}
	body := float64(height) - 2*margin - headerH - footerH - 4*gap
	top := margin + headerH
	for i, name := range names {
		h := body * weights[i]
		card := chartBox{margin, top, float64(width) - 2*margin, h}
		plot := chartBox{margin + 76, top + 27, float64(width) - 2*margin - 94, h - 49}
		if plot.W <= 0 || plot.H <= 0 {
			return nil, fmt.Errorf("画像の描画領域が不足しています")
		}
		p := chartPane{Name: name, Label: labels[i], Color: colors[i], Card: card, Plot: plot}
		p.Points, err = chartSeries(data, name)
		if err != nil {
			return nil, err
		}
		p.Segments, p.Single = chartPaths(p.Points, name != "price", from, to)
		values := []float64{}
		for _, line := range p.Segments {
			for _, v := range line {
				values = append(values, v.Y)
			}
		}
		for _, v := range p.Single {
			values = append(values, v.Y)
		}
		if name == "price" && mode.Minutes > 0 {
			values = nil
			for _, c := range candles {
				if c.End <= from || c.Start >= to {
					continue
				}
				for _, v := range []*float64{c.Open, c.High, c.Low, c.Close} {
					if v != nil {
						values = append(values, *v)
					}
				}
			}
		}
		if name == "price" {
			for _, e := range data.Events {
				if e.Type != "Detach" && e.TimestampMS >= from && e.TimestampMS <= to && finite(e.Price) && e.Price > 0 {
					values = append(values, e.Price)
				}
			}
		}
		p.Low, p.High = chartAxis(values, name)
		p.ZeroY = chartY(0, p.Low, p.High, plot)
		s.Panes = append(s.Panes, p)
		s.Ops = append(s.Ops, chartPrimitive{Kind: "rect", Pane: i, Box: card, Color: chartCard}, chartPrimitive{Kind: "rect", Pane: i, Box: plot, Color: chartPlot})
		label := labels[i]
		if i == 0 {
			label += " / " + strings.ToUpper(mode.Price) + " / " + mode.Interval
		}
		chartAddText(s, i, card.X+10, card.Y+18, fontSize, label, chartText, "start")
		ticks := 2
		if i == 0 {
			ticks = 4
		}
		for k := 0; k <= ticks; k++ {
			ratio := float64(k) / float64(ticks)
			v := p.Low*(1-ratio) + p.High*ratio
			if (name == "long" || name == "short") && v != math.Trunc(v) {
				continue
			}
			y := chartY(v, p.Low, p.High, plot)
			color := chartGrid
			if math.Abs(v) < 1e-10 {
				color = chartZero
			}
			s.Ops = append(s.Ops, chartPrimitive{Kind: "path", Pane: i, Points: []chartPoint{{plot.X, y}, {plot.X + plot.W, y}}, Color: color, Stroke: 1, Role: "grid"})
			chartAddText(s, i, plot.X-7, y+small*.35, small, chartNumber(v), chartMuted, "end")
		}
		xTicks := int(plot.W / 165)
		if xTicks < 2 {
			xTicks = 2
		}
		if xTicks > 7 {
			xTicks = 7
		}
		for k := 0; k <= xTicks; k++ {
			ratio := float64(k) / float64(xTicks)
			at := from + (to-from)*ratio
			x := plot.X + plot.W*ratio
			s.Ops = append(s.Ops, chartPrimitive{Kind: "path", Pane: i, Points: []chartPoint{{x, plot.Y}, {x, plot.Y + plot.H}}, Color: chartGrid, Stroke: 1, Role: "grid"})
			anchor := "middle"
			if k == 0 {
				anchor = "start"
			}
			if k == xTicks {
				anchor = "end"
			}
			label := chartStamp(at, true)
			if to-from < 5000 {
				label = chartStamp(at, false)[11:]
			}
			chartAddText(s, i, x, plot.Y+plot.H+16, small, label, chartMuted, anchor)
		}
		if name == "price" && mode.Minutes > 0 {
			for _, c := range candles {
				if c.Start >= to || c.End <= from || c.Open == nil || c.High == nil || c.Low == nil || c.Close == nil {
					continue
				}
				left, right := math.Max(from, c.Start), math.Min(to, c.End)
				x := (chartX(left, from, to, plot) + chartX(right, from, to, plot)) / 2
				color := chartLong
				if *c.Close < *c.Open {
					color = chartShort
				}
				w := math.Max(1, math.Min(16, (right-left)/(to-from)*plot.W*.7))
				s.Ops = append(s.Ops, chartPrimitive{Kind: "path", Pane: i, Points: []chartPoint{{x, chartY(*c.High, p.Low, p.High, plot)}, {x, chartY(*c.Low, p.Low, p.High, plot)}}, Color: color, Stroke: 1.2, Clip: true, Role: "series"})
				y1, y2 := chartY(*c.Open, p.Low, p.High, plot), chartY(*c.Close, p.Low, p.High, plot)
				s.Ops = append(s.Ops, chartPrimitive{Kind: "rect", Pane: i, Box: chartBox{x - w/2, math.Min(y1, y2), w, math.Max(1, math.Abs(y1-y2))}, Color: color, Clip: true, Role: "series"})
			}
		} else {
			for _, line := range p.Segments {
				mapped := make([]chartPoint, len(line))
				for j, v := range line {
					mapped[j] = chartPoint{chartX(v.X, from, to, plot), chartY(v.Y, p.Low, p.High, plot)}
				}
				s.Ops = append(s.Ops, chartPrimitive{Kind: "path", Pane: i, Points: mapped, Color: p.Color, Stroke: 1.5, Clip: true, Role: "series"})
			}
			for _, v := range p.Single {
				s.Ops = append(s.Ops, chartPrimitive{Kind: "circle", Pane: i, Box: chartBox{X: chartX(v.X, from, to, plot), Y: chartY(v.Y, p.Low, p.High, plot), W: 2.5}, Color: p.Color, Clip: true, Role: "series"})
			}
		}
		if len(values) == 0 {
			chartAddText(s, i, plot.X+plot.W/2, plot.Y+plot.H/2, small, "この範囲は未観測", chartMuted, "middle")
		}
		if name == "price" {
			for _, e := range data.Events {
				if e.TimestampMS < from || e.TimestampMS > to || !finite(e.TimestampMS) {
					continue
				}
				x := chartX(e.TimestampMS, from, to, plot)
				if e.Type == "Detach" {
					y := plot.Y + 8
					s.Ops = append(s.Ops, chartPrimitive{Kind: "polygon", Pane: i, Points: []chartPoint{{x, y - 4}, {x + 4, y}, {x, y + 4}, {x - 4, y}}, Color: chartMuted, Clip: true, Role: "event"})
					continue
				}
				if !finite(e.Price) || e.Price <= 0 {
					continue
				}
				y := chartY(e.Price, p.Low, p.High, plot)
				color := chartLong
				if strings.HasPrefix(e.Type, "Short") {
					color = chartShort
				}
				if e.Type == "LongN" || e.Type == "ShortN" {
					dy := -5.0
					if e.Type == "ShortN" {
						dy = 5
					}
					s.Ops = append(s.Ops, chartPrimitive{Kind: "polygon", Pane: i, Points: []chartPoint{{x, y + dy}, {x - 4, y - dy/2}, {x + 4, y - dy/2}}, Color: color, Clip: true, Role: "event"})
				} else {
					s.Ops = append(s.Ops, chartPrimitive{Kind: "circle", Pane: i, Box: chartBox{X: x, Y: y, W: 3}, Color: color, Stroke: 1.2, Clip: true, Role: "event"})
				}
			}
		}
		top += h + gap
	}
	footerY := float64(height) - footerH - margin + small
	basis := "手数料前"
	if data.Resource.PNLBasis == "net" {
		basis = "記録手数料控除後"
	}
	if data.Resource.PNLFormat == "" {
		basis = "損益資料なし（価格のみ）"
	}
	fileLabel := func(path string) string {
		if path == "" {
			return "なし"
		}
		return filepath.Base(path)
	}
	lines := []string{fmt.Sprintf("評価: %s / 時刻: CurrentPriceTime（受信時刻ではない）/ 未知値はnull・区間外へ補完しない", basis), "原板: " + fileLabel(data.Files.Market) + " / 損益: " + fileLabel(data.Files.PNL) + " / 資料SHA256: " + hex.EncodeToString(sum[:])[:16]}
	warnings := []string{}
	// 小さい画像でも管理外玉の消失を利益と誤読させないよう、移管の注意だけは先に表示します。
	for _, w := range data.Quality.Warnings {
		if strings.Contains(w, "管理外移管") {
			warnings = append(warnings, w)
		}
	}
	for _, w := range data.Quality.Warnings {
		if !strings.Contains(w, "管理外移管") {
			warnings = append(warnings, w)
		}
	}
	limit := 3
	if compact {
		limit = 1
	}
	for i, w := range warnings {
		if i >= limit {
			break
		}
		lines = append(lines, "注意: "+w)
	}
	for i, line := range lines {
		color := chartMuted
		if i >= 2 {
			color = chartUnrealized
		}
		chartAddText(s, -1, margin, footerY+float64(i)*(small+4), small, chartFit(line, float64(width)-2*margin, small), color, "start")
	}
	return s, nil
}
