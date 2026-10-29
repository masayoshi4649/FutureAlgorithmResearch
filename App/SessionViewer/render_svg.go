package main

import (
	"bytes"
	"encoding/xml"
	"fmt"
	"math"
	"strconv"
)

// chartClipBox は画素反復より前に線分を描画矩形へ切り詰めます。
//
// 引数: a/b(chartPoint)、box(chartBox)。返り値: 端点2個、採用bool。範囲外prefixで巨大ループしません。
func chartClipBox(a, b chartPoint, box chartBox) (chartPoint, chartPoint, bool) {
	if !finite(a.X) || !finite(a.Y) || !finite(b.X) || !finite(b.Y) {
		return a, b, false
	}
	dx, dy := b.X-a.X, b.Y-a.Y
	if !finite(dx) || !finite(dy) {
		return a, b, false
	}
	left, right := 0.0, 1.0
	ps := []float64{-dx, dx, -dy, dy}
	qs := []float64{a.X - box.X, box.X + box.W - a.X, a.Y - box.Y, box.Y + box.H - a.Y}
	for i, p := range ps {
		q := qs[i]
		if p == 0 {
			if q < 0 {
				return a, b, false
			}
			continue
		}
		r := q / p
		if p < 0 {
			if r > right {
				return a, b, false
			}
			left = math.Max(left, r)
		} else {
			if r < left {
				return a, b, false
			}
			right = math.Min(right, r)
		}
	}
	return chartPoint{a.X + dx*left, a.Y + dy*left}, chartPoint{a.X + dx*right, a.Y + dy*right}, true
}

// chartClippedPaths は矩形を外れる線を再接続せず、SVGとPNGで同じ短い経路にします。
//
// 引数: points([]chartPoint)、box(chartBox)。返り値: [][]chartPoint。
func chartClippedPaths(points []chartPoint, box chartBox) [][]chartPoint {
	out := [][]chartPoint{}
	line := []chartPoint{}
	flush := func() {
		if len(line) > 1 {
			out = append(out, line)
		}
		line = nil
	}
	for i := 1; i < len(points); i++ {
		a, b, ok := chartClipBox(points[i-1], points[i], box)
		if !ok {
			flush()
			continue
		}
		if len(line) == 0 || line[len(line)-1] != a {
			flush()
			line = append(line, a)
		}
		line = append(line, b)
	}
	flush()
	return out
}

// chartEscape はSVGテキストをXMLとして厳密にエスケープします。
//
// 引数: value(string)。返り値: string。外部リンクやマークアップには変換しません。
func chartEscape(value string) string {
	var b bytes.Buffer
	_ = xml.EscapeText(&b, []byte(value))
	return b.String()
}

// chartCoord は有限の描画座標を小数2桁へ整形します。
//
// 引数: value(float64)。返り値: string。数値根拠のmetadataは丸めません。
func chartCoord(value float64) string { return strconv.FormatFloat(value, 'f', 2, 64) }

// RenderChartSVG は5段共通の描画列から外部参照を含まないSVGをメモリ生成します。
//
// 引数: data(DataResponse)、width/height(int)。返り値: SVG([]byte)とerror。原資料やフォントを再読込・保存しません。
func RenderChartSVG(data DataResponse, width, height int) ([]byte, error) {
	s, err := buildChartScene(data, width, height)
	if err != nil {
		return nil, err
	}
	var b bytes.Buffer
	fmt.Fprintf(&b, `<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img" aria-labelledby="chart-title chart-description">`, width, height, width, height)
	fmt.Fprintf(&b, "<title id=\"chart-title\">%s</title><desc id=\"chart-description\">%s</desc>", chartEscape(s.Title), chartEscape(string(s.Metadata)))
	b.WriteString("<defs>")
	for i, p := range s.Panes {
		fmt.Fprintf(&b, `<clipPath id="plot-%d"><rect x="%s" y="%s" width="%s" height="%s"/></clipPath>`, i, chartCoord(p.Plot.X), chartCoord(p.Plot.Y), chartCoord(p.Plot.W), chartCoord(p.Plot.H))
	}
	b.WriteString(`</defs><g font-family="Meiryo, Noto Sans CJK JP, Yu Gothic, sans-serif">`)
	active := -1
	for _, op := range s.Ops {
		if op.Pane != active {
			if active >= 0 {
				b.WriteString("</g>")
			}
			active = op.Pane
			if active >= 0 {
				p := s.Panes[active]
				fmt.Fprintf(&b, `<g data-series="%s" data-min="%s" data-max="%s" data-zero-y="%s" data-plot-x="%s" data-plot-y="%s" data-plot-width="%s" data-plot-height="%s">`, p.Name, strconv.FormatFloat(p.Low, 'g', -1, 64), strconv.FormatFloat(p.High, 'g', -1, 64), chartCoord(p.ZeroY), chartCoord(p.Plot.X), chartCoord(p.Plot.Y), chartCoord(p.Plot.W), chartCoord(p.Plot.H))
			}
		}
		attributes := ""
		if op.Role != "" {
			attributes += ` data-role="` + op.Role + `"`
		}
		if op.Clip && op.Pane >= 0 {
			attributes += fmt.Sprintf(` clip-path="url(#plot-%d)"`, op.Pane)
		}
		switch op.Kind {
		case "rect":
			fmt.Fprintf(&b, `<rect x="%s" y="%s" width="%s" height="%s" fill="%s"%s/>`, chartCoord(op.Box.X), chartCoord(op.Box.Y), chartCoord(op.Box.W), chartCoord(op.Box.H), op.Color, attributes)
		case "text":
			fmt.Fprintf(&b, `<text x="%s" y="%s" font-size="%s" text-anchor="%s" fill="%s">%s</text>`, chartCoord(op.Box.X), chartCoord(op.Box.Y), chartCoord(op.Size), op.Anchor, op.Color, chartEscape(op.Text))
		case "path":
			paths := [][]chartPoint{op.Points}
			if op.Clip && op.Pane >= 0 {
				paths = chartClippedPaths(op.Points, s.Panes[op.Pane].Plot)
			}
			for _, line := range paths {
				if len(line) < 2 {
					continue
				}
				b.WriteString(`<path d="`)
				for i, p := range line {
					if i == 0 {
						b.WriteString("M")
					} else {
						b.WriteString("L")
					}
					b.WriteString(chartCoord(p.X) + " " + chartCoord(p.Y) + " ")
				}
				fmt.Fprintf(&b, `" fill="none" stroke="%s" stroke-width="%s" stroke-linejoin="round" stroke-linecap="round"%s/>`, op.Color, chartCoord(op.Stroke), attributes)
			}
		case "circle":
			fill, stroke := op.Color, "none"
			if op.Stroke > 0 {
				fill, stroke = "none", op.Color
			}
			fmt.Fprintf(&b, `<circle cx="%s" cy="%s" r="%s" fill="%s" stroke="%s" stroke-width="%s"%s/>`, chartCoord(op.Box.X), chartCoord(op.Box.Y), chartCoord(op.Box.W), fill, stroke, chartCoord(op.Stroke), attributes)
		case "polygon":
			b.WriteString(`<polygon points="`)
			for _, p := range op.Points {
				b.WriteString(chartCoord(p.X) + "," + chartCoord(p.Y) + " ")
			}
			fmt.Fprintf(&b, `" fill="%s"%s/>`, op.Color, attributes)
		}
	}
	if active >= 0 {
		b.WriteString("</g>")
	}
	b.WriteString("</g></svg>")
	return b.Bytes(), nil
}
