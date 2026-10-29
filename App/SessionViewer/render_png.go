package main

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"hash/crc32"
	"image"
	"image/color"
	"image/draw"
	"image/png"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"golang.org/x/image/font"
	"golang.org/x/image/font/opentype"
	"golang.org/x/image/font/sfnt"
	"golang.org/x/image/math/fixed"
)

// chartFontCandidates はOSが提供する日本語フォントの候補だけを列挙します。
//
// 引数: explicit(string、空なら自動探索)。返り値: []string。コピーやダウンロードは行いません。
func chartFontCandidates(explicit string) []string {
	if explicit != "" {
		return []string{explicit}
	}
	windows := os.Getenv("WINDIR")
	if windows == "" {
		windows = `C:\Windows`
	}
	return []string{filepath.Join(windows, "Fonts", "meiryo.ttc"), filepath.Join(windows, "Fonts", "msgothic.ttc"), filepath.Join(windows, "Fonts", "YuGothR.ttc"), filepath.Join(windows, "Fonts", "YuGothM.ttc"),
		"/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/noto/NotoSansJP-Regular.ttf",
		"/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf", "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf", "/usr/share/fonts/truetype/ipaexg.ttf", "/usr/local/share/fonts/NotoSansCJK-Regular.ttc"}
}

// chartFontCovers は表示文字を欠落グリフのまま成功扱いしないために検査します。
//
// 引数: f(*opentype.Font)、text(string)。返り値: error。
func chartFontCovers(f *opentype.Font, text string) error {
	var buffer sfnt.Buffer
	seen := map[rune]bool{}
	for _, r := range "価格売買保有確定含み損益日本語" + text {
		if seen[r] || r == ' ' {
			continue
		}
		seen[r] = true
		index, err := f.GlyphIndex(&buffer, r)
		if err != nil {
			return err
		}
		if index == 0 {
			return fmt.Errorf("文字U+%04Xを描画できません", r)
		}
	}
	return nil
}

// chartLoadFont はTTF/TTCを読取専用で読み、表示に必要な日本語を確認します。
//
// 引数: explicit(string)、text(string)。返り値: *opentype.Fontとerror。フォントを埋込・保存しません。
func chartLoadFont(explicit, text string) (*opentype.Font, error) {
	var last error
	for _, path := range chartFontCandidates(explicit) {
		info, err := os.Stat(path)
		if err != nil {
			last = err
			continue
		}
		if !info.Mode().IsRegular() || info.Size() > 64*1024*1024 {
			last = fmt.Errorf("フォントが通常ファイルでないか64MBを超えています")
			continue
		}
		data, err := os.ReadFile(path)
		if err != nil {
			last = err
			continue
		}
		collection, err := opentype.ParseCollection(data)
		if err == nil {
			for i := 0; i < collection.NumFonts(); i++ {
				f, e := collection.Font(i)
				if e == nil {
					if e = chartFontCovers(f, text); e == nil {
						return f, nil
					}
				}
				last = e
			}
			continue
		}
		f, err := opentype.Parse(data)
		if err == nil {
			err = chartFontCovers(f, text)
			if err == nil {
				return f, nil
			}
		}
		last = err
	}
	if explicit != "" {
		return nil, fmt.Errorf("指定font_pathで日本語PNGを描画できません: %v", last)
	}
	return nil, fmt.Errorf("PNG用の日本語フォントがありません。font_pathを指定するかSVGを使用してください: %v", last)
}

// chartRGBA はコード内で固定した16進色を画素色へ変換します。
//
// 引数: value(string)。返り値: color.RGBA。
func chartRGBA(value string) color.RGBA {
	var r, g, b uint8
	_, _ = fmt.Sscanf(value, "#%02x%02x%02x", &r, &g, &b)
	return color.RGBA{r, g, b, 255}
}

// chartPixel は範囲を検査し、線の被覆率を既存の暗色画素へ合成します。
//
// 引数: dst(*image.RGBA)、x/y(int)、c(color.RGBA)、coverage(float64)、clip(chartBox)。返り値: なし。
func chartPixel(dst *image.RGBA, x, y int, c color.RGBA, coverage float64, clip chartBox) {
	if x < 0 || y < 0 || x >= dst.Bounds().Dx() || y >= dst.Bounds().Dy() || float64(x)+.5 < clip.X || float64(y)+.5 < clip.Y || float64(x)+.5 > clip.X+clip.W || float64(y)+.5 > clip.Y+clip.H || coverage <= 0 {
		return
	}
	if coverage > 1 {
		coverage = 1
	}
	prior := dst.RGBAAt(x, y)
	mix := func(a, b uint8) uint8 { return uint8(math.Round(float64(a)*(1-coverage) + float64(b)*coverage)) }
	dst.SetRGBA(x, y, color.RGBA{mix(prior.R, c.R), mix(prior.G, c.G), mix(prior.B, c.B), 255})
}

// chartRasterLine はクリップ済み線の長軸に沿ってだけ反復し、巨大prefixや斜線の面積反復を避けます。
//
// 引数: dst(*image.RGBA)、a/b(chartPoint)、stroke(float64)、c(color.RGBA)、clip(chartBox)。返り値: なし。
func chartRasterLine(dst *image.RGBA, a, b chartPoint, stroke float64, c color.RGBA, clip chartBox) {
	a, b, ok := chartClipBox(a, b, clip)
	if !ok {
		return
	}
	a, b, ok = chartClipBox(a, b, chartBox{0, 0, float64(dst.Bounds().Dx()), float64(dst.Bounds().Dy())})
	if !ok {
		return
	}
	dx, dy := b.X-a.X, b.Y-a.Y
	length := dx*dx + dy*dy
	radius := stroke/2 + .65
	paint := func(x, y int) {
		px, py := float64(x)+.5, float64(y)+.5
		t := 0.0
		if length > 0 {
			t = math.Max(0, math.Min(1, ((px-a.X)*dx+(py-a.Y)*dy)/length))
		}
		distance := math.Hypot(px-a.X-t*dx, py-a.Y-t*dy)
		chartPixel(dst, x, y, c, radius-distance, clip)
	}
	if math.Abs(dx) >= math.Abs(dy) {
		left, right := int(math.Floor(math.Min(a.X, b.X)-radius)), int(math.Ceil(math.Max(a.X, b.X)+radius))
		for x := left; x <= right; x++ {
			t := 0.0
			if dx != 0 {
				t = math.Max(0, math.Min(1, (float64(x)+.5-a.X)/dx))
			}
			center := a.Y + t*dy
			for y := int(math.Floor(center - radius)); y <= int(math.Ceil(center+radius)); y++ {
				paint(x, y)
			}
		}
	} else {
		top, bottom := int(math.Floor(math.Min(a.Y, b.Y)-radius)), int(math.Ceil(math.Max(a.Y, b.Y)+radius))
		for y := top; y <= bottom; y++ {
			t := 0.0
			if dy != 0 {
				t = math.Max(0, math.Min(1, (float64(y)+.5-a.Y)/dy))
			}
			center := a.X + t*dx
			for x := int(math.Floor(center - radius)); x <= int(math.Ceil(center+radius)); x++ {
				paint(x, y)
			}
		}
	}
}

// chartRasterCircle は孤立値又は返済記号を小さな画素範囲内で描画します。
//
// 引数: dst(*image.RGBA)、op(chartPrimitive)、clip(chartBox)。返り値: なし。
func chartRasterCircle(dst *image.RGBA, op chartPrimitive, clip chartBox) {
	r := op.Box.W
	c := chartRGBA(op.Color)
	for y := int(math.Floor(op.Box.Y - r - 1)); y <= int(math.Ceil(op.Box.Y+r+1)); y++ {
		for x := int(math.Floor(op.Box.X - r - 1)); x <= int(math.Ceil(op.Box.X+r+1)); x++ {
			distance := math.Hypot(float64(x)+.5-op.Box.X, float64(y)+.5-op.Box.Y)
			coverage := r + .5 - distance
			if op.Stroke > 0 {
				coverage = op.Stroke/2 + .5 - math.Abs(distance-r)
			}
			chartPixel(dst, x, y, c, coverage, clip)
		}
	}
}

// chartRasterPolygon は新規又は移管の小記号を走査線で塗ります。
//
// 引数: dst(*image.RGBA)、op(chartPrimitive)、clip(chartBox)。返り値: なし。
func chartRasterPolygon(dst *image.RGBA, op chartPrimitive, clip chartBox) {
	if len(op.Points) < 3 {
		return
	}
	low, high := op.Points[0].Y, op.Points[0].Y
	for _, p := range op.Points {
		low = math.Min(low, p.Y)
		high = math.Max(high, p.Y)
	}
	low = math.Max(low, clip.Y)
	high = math.Min(high, clip.Y+clip.H)
	c := chartRGBA(op.Color)
	for y := int(math.Floor(low)); y <= int(math.Ceil(high)); y++ {
		scan := float64(y) + .5
		xs := []float64{}
		for i, a := range op.Points {
			b := op.Points[(i+1)%len(op.Points)]
			if (a.Y <= scan && b.Y > scan) || (b.Y <= scan && a.Y > scan) {
				xs = append(xs, a.X+(scan-a.Y)/(b.Y-a.Y)*(b.X-a.X))
			}
		}
		sort.Float64s(xs)
		for i := 0; i+1 < len(xs); i += 2 {
			left, right := math.Max(xs[i], clip.X), math.Min(xs[i+1], clip.X+clip.W)
			for x := int(math.Floor(left)); x <= int(math.Ceil(right)); x++ {
				chartPixel(dst, x, y, c, 1, clip)
			}
		}
	}
}

// chartPNGMetadata はUTF-8の画像根拠を標準iTXtチャンクへメモリ内で追加します。
//
// 引数: raw/meta([]byte)。返り値: []byte。フォント・原板本文は埋め込みません。
func chartPNGMetadata(raw, meta []byte) []byte {
	if len(raw) < 12 {
		return raw
	}
	payload := append([]byte{'D', 'e', 's', 'c', 'r', 'i', 'p', 't', 'i', 'o', 'n', 0, 0, 0, 0, 0}, meta...)
	chunk := make([]byte, len(payload)+12)
	binary.BigEndian.PutUint32(chunk[:4], uint32(len(payload)))
	copy(chunk[4:8], "iTXt")
	copy(chunk[8:], payload)
	binary.BigEndian.PutUint32(chunk[len(chunk)-4:], crc32.ChecksumIEEE(chunk[4:len(chunk)-4]))
	out := make([]byte, 0, len(raw)+len(chunk))
	out = append(out, raw[:len(raw)-12]...)
	out = append(out, chunk...)
	out = append(out, raw[len(raw)-12:]...)
	return out
}

// RenderChartPNG はブラウザやCGOを使わず、SVGと同じ共通描画列をPNGへ変換します。
//
// 引数: data(DataResponse)、width/height(int)、fontPath(string、空ならOS日本語フォント探索)。
// 返り値: PNG([]byte)とerror。画像・フォントのコピーやDB保存は行いません。
func RenderChartPNG(data DataResponse, width, height int, fontPath string) ([]byte, error) {
	s, err := buildChartScene(data, width, height)
	if err != nil {
		return nil, err
	}
	var labels strings.Builder
	for _, op := range s.Ops {
		if op.Kind == "text" {
			labels.WriteString(op.Text)
		}
	}
	f, err := chartLoadFont(fontPath, labels.String())
	if err != nil {
		return nil, err
	}
	faces := map[float64]font.Face{}
	defer func() {
		for _, face := range faces {
			_ = face.Close()
		}
	}()
	dst := image.NewRGBA(image.Rect(0, 0, width, height))
	canvas := chartBox{0, 0, float64(width), float64(height)}
	for _, op := range s.Ops {
		clip := canvas
		if op.Clip && op.Pane >= 0 {
			clip = s.Panes[op.Pane].Plot
		}
		c := chartRGBA(op.Color)
		switch op.Kind {
		case "rect":
			left, top := math.Max(op.Box.X, clip.X), math.Max(op.Box.Y, clip.Y)
			right, bottom := math.Min(op.Box.X+op.Box.W, clip.X+clip.W), math.Min(op.Box.Y+op.Box.H, clip.Y+clip.H)
			if right > left && bottom > top {
				box := image.Rect(int(math.Floor(left)), int(math.Floor(top)), int(math.Ceil(right)), int(math.Ceil(bottom))).Intersect(dst.Bounds())
				draw.Draw(dst, box, image.NewUniform(c), image.Point{}, draw.Src)
			}
		case "path":
			for i := 1; i < len(op.Points); i++ {
				chartRasterLine(dst, op.Points[i-1], op.Points[i], op.Stroke, c, clip)
			}
		case "circle":
			chartRasterCircle(dst, op, clip)
		case "polygon":
			chartRasterPolygon(dst, op, clip)
		case "text":
			face := faces[op.Size]
			if face == nil {
				face, err = opentype.NewFace(f, &opentype.FaceOptions{Size: op.Size, DPI: 72, Hinting: font.HintingFull})
				if err != nil {
					return nil, err
				}
				faces[op.Size] = face
			}
			d := font.Drawer{Dst: dst, Src: image.NewUniform(c), Face: face}
			x := op.Box.X
			advance := float64(font.MeasureString(face, op.Text)) / 64
			if op.Anchor == "end" {
				x -= advance
			}
			if op.Anchor == "middle" {
				x -= advance / 2
			}
			d.Dot = fixed.Point26_6{X: fixed.Int26_6(math.Round(x * 64)), Y: fixed.Int26_6(math.Round(op.Box.Y * 64))}
			d.DrawString(op.Text)
		}
	}
	var out bytes.Buffer
	encoder := png.Encoder{CompressionLevel: png.BestSpeed}
	if err = encoder.Encode(&out, dst); err != nil {
		return nil, err
	}
	return chartPNGMetadata(out.Bytes(), s.Metadata), nil
}
