package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"encoding/xml"
	"image"
	"image/png"
	"io"
	"math"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// renderFixture は上昇下落・null・両建て・移管を画像だけで点検できる独立人工値を作ります。
//
// 引数: なし。返り値: DataResponse。売買や原板読込は実行しません。
func renderFixture() DataResponse {
	start := millis(adversaryTime(0))
	r := DataResponse{Resource: ResourceMeta{ID: "画像人工", Title: "描画人工", Symbol: "NK225", Product: "NK225micro", Session: "2026-10-27_Day", MethodID: "*", PNLBasis: "gross"}, Range: DataRange{StartMS: start, EndMS: start + 60000, FromMS: start, ToMS: start + 60000}, Interval: "raw", CandlePrice: "last", PriceColumns: []string{"t", "line", "last", "bid", "ask"}, StateColumns: []string{"t", "sequence", "source_line", "long_qty", "short_qty", "realized_pnl_yen", "unrealized_pnl_yen"}, Files: DataFiles{Market: "生板/book.jsonl", PNL: "約定/日本語.trades.jsonl"}, Quality: Quality{Warnings: []string{"原時計は受信時計とは異なります。", "管理外移管は返済ではありません。"}}}
	r.Resource.PNLFormat = "trades"
	last := []float64{100, 110, 105, 115, 120, 112}
	long := []int{1, 1, 3, 2, 0, 0}
	short := []int{0, 2, 1, 0, 1, 0}
	real := []float64{0, 100, 200, -100, 50, 150}
	unreal := []any{-20.0, 20.0, nil, -40.0, 60.0, 0.0}
	for i, v := range last {
		at := start + float64(i)*10000
		r.Prices = append(r.Prices, []any{at, i + 1, v, v - 1, v + 1})
		r.States = append(r.States, []any{at, i + 1, i + 1, long[i], short[i], real[i], unreal[i]})
	}
	r.Events = []ViewEvent{{TimestampMS: start, Type: "LongN", Price: 100, Qty: 1}, {TimestampMS: start + 20000, Type: "LongR", Price: 105, Qty: 1}, {TimestampMS: start + 35000, Type: "Detach", Qty: 2}}
	return r
}

// renderCountColor は各ペインに系列色の線が存在するか、PNGの画素だけから検査します。
//
// 引数: img(image.Image)、box(chartBox)、hexColor(string)。返り値: int。
func renderCountColor(img image.Image, box chartBox, hexColor string) int {
	want := chartRGBA(hexColor)
	count := 0
	for y := int(box.Y); y < int(box.Y+box.H); y++ {
		for x := int(box.X); x < int(box.X+box.W); x++ {
			r, g, b, _ := img.At(x, y).RGBA()
			if math.Abs(float64(r>>8)-float64(want.R)) < 28 && math.Abs(float64(g>>8)-float64(want.G)) < 28 && math.Abs(float64(b>>8)-float64(want.B)) < 28 {
				count++
			}
		}
	}
	return count
}

// TestRenderSharedSVGAndPNG は5系列のPNG描画・PL中央・同じ根拠指紋を照合します。
//
// 引数: t(*testing.T)。返り値: なし。目視保存は明示環境変数があるignored workだけです。
func TestRenderSharedSVGAndPNG(t *testing.T) {
	data := renderFixture()
	scene, err := buildChartScene(data, 1600, 1200)
	if err != nil {
		t.Fatal(err)
	}
	for _, p := range scene.Panes[3:] {
		if p.Low != -p.High || math.Abs(p.ZeroY-p.Plot.Y-p.Plot.H/2) > 1e-6 {
			t.Fatalf("損益0が中央ではありません: %+v", p)
		}
	}
	raw, err := RenderChartPNG(data, 1600, 1200, "")
	if err != nil {
		if _, e := os.Stat(`C:\Windows\Fonts\meiryo.ttc`); e == nil {
			t.Fatal(err)
		}
		t.Skipf("PNG日本語フォントのある環境で実行してください: %v", err)
	}
	img, err := png.Decode(bytes.NewReader(raw))
	if err != nil {
		t.Fatal(err)
	}
	if img.Bounds() != image.Rect(0, 0, 1600, 1200) {
		t.Fatal(img.Bounds())
	}
	for _, p := range scene.Panes {
		if n := renderCountColor(img, p.Plot, p.Color); n < 5 {
			t.Fatalf("%sに有色の系列がありません: %d", p.Name, n)
		}
	}
	svg, err := RenderChartSVG(data, 1600, 1200)
	if err != nil {
		t.Fatal(err)
	}
	decoder := xml.NewDecoder(bytes.NewReader(svg))
	var meta map[string]json.RawMessage
	for {
		token, e := decoder.Token()
		if e == io.EOF {
			break
		}
		if e != nil {
			t.Fatal(e)
		}
		if element, ok := token.(xml.StartElement); ok && element.Name.Local == "desc" {
			var text string
			if e = decoder.DecodeElement(&text, &element); e != nil {
				t.Fatal(e)
			}
			if e = json.Unmarshal([]byte(text), &meta); e != nil {
				t.Fatal(e)
			}
		}
	}
	if !bytes.Contains(raw, scene.Metadata) {
		t.Fatal("PNG iTXtに根拠がありません")
	}
	source, _ := json.Marshal(data)
	sum := sha256.Sum256(source)
	var digest string
	if err = json.Unmarshal(meta["data_sha256"], &digest); err != nil || digest != hex.EncodeToString(sum[:]) {
		t.Fatal("画像元のSHAが一致しません", err, digest)
	}
	if output := os.Getenv("VIEWER_RENDER_QA"); output != "" {
		abs, e := filepath.Abs(output)
		if e != nil {
			t.Fatal(e)
		}
		base, e := filepath.Abs("work")
		if e != nil {
			t.Fatal(e)
		}
		rel, e := filepath.Rel(base, abs)
		if e != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(os.PathSeparator)) {
			t.Fatal("目視出力はignored work内へ指定してください")
		}
		if e = os.MkdirAll(filepath.Dir(abs), 0700); e != nil {
			t.Fatal(e)
		}
		if e = os.WriteFile(abs, raw, 0600); e != nil {
			t.Fatal(e)
		}
		t.Log("目視PNG:", abs)
	}
}

// TestRenderNarrowRangeAndHugeAmplitude は遠いprefixを画素反復へ渡さず巨大なPLも有限軸へ保つことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。過去数時間と100ms範囲の共存を反例にします。
func TestRenderNarrowRangeAndHugeAmplitude(t *testing.T) {
	data := renderFixture()
	from := data.Range.FromMS + 3*3600000
	data.Range.FromMS, data.Range.ToMS = from, from+100
	data.States = [][]any{{from - 3*3600000, 1, nil, 1, 0, 1.7e308, -1.7e308}, {from + 100, 2, nil, 1, 0, -1.7e308, 1.7e308}}
	data.Prices = [][]any{{from - 3600000, 1, 100.0, 99.0, 101.0}, {from + 100, 2, 110.0, 109.0, 111.0}}
	data.Events = nil
	start := time.Now()
	svg, err := RenderChartSVG(data, 800, 700)
	if err != nil {
		t.Fatal(err)
	}
	if time.Since(start) > time.Second {
		t.Fatal("狭い表示が遠いprefixの距離に比例しました")
	}
	if bytes.Contains(svg, []byte("NaN")) || bytes.Contains(svg, []byte("+Inf")) {
		t.Fatal("非有限座標が入りました")
	}
	scene, err := buildChartScene(data, 800, 700)
	if err != nil {
		t.Fatal(err)
	}
	for _, op := range scene.Ops {
		if op.Kind != "path" || !op.Clip {
			continue
		}
		for _, p := range op.Points {
			if !finite(p.X) || !finite(p.Y) || p.X < 0 || p.X > 800 || p.Y < 0 || p.Y > 700 {
				t.Fatalf("範囲外巨大座標です: %+v", p)
			}
		}
	}
	if _, err = RenderChartPNG(data, 800, 700, ""); err != nil && !strings.Contains(err.Error(), "フォント") {
		t.Fatal(err)
	}
	if time.Since(start) > 5*time.Second {
		t.Fatal("PNG反復が画素範囲を超えました")
	}
}

// TestRenderNullAndMaliciousText は欠測を0にせず、任意の文字列をSVG要素へ昇格させないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。XML非文字もJSON根拠内では元の意味を保持します。
func TestRenderNullAndMaliciousText(t *testing.T) {
	data := renderFixture()
	data.Resource.MethodID = "手法 </text><script>壊す</script> & \"引用\"\x00\ufffe"
	data.Resource.Title = "題名\uffff"
	data.States = [][]any{{data.Range.FromMS, 1, nil, 0, 0, nil, nil}, {data.Range.ToMS, 2, nil, 0, 0, nil, nil}}
	svg, err := RenderChartSVG(data, 800, 700)
	if err != nil {
		t.Fatal(err)
	}
	d := xml.NewDecoder(bytes.NewReader(svg))
	groups := map[string]int{}
	pane := ""
	var meta map[string]json.RawMessage
	for {
		token, e := d.Token()
		if e == io.EOF {
			break
		}
		if e != nil {
			t.Fatal(e)
		}
		if element, ok := token.(xml.StartElement); ok {
			if element.Name.Local == "script" || element.Name.Local == "image" || element.Name.Local == "foreignObject" {
				t.Fatal("能動要素を生成しました")
			}
			attrs := map[string]string{}
			for _, a := range element.Attr {
				attrs[a.Name.Local] = a.Value
			}
			if attrs["data-series"] != "" {
				pane = attrs["data-series"]
			}
			if attrs["data-role"] == "series" {
				groups[pane]++
			}
			if element.Name.Local == "desc" {
				var text string
				if e = d.DecodeElement(&text, &element); e != nil {
					t.Fatal(e)
				}
				if e = json.Unmarshal([]byte(text), &meta); e != nil {
					t.Fatal(e)
				}
			}
		}
	}
	if groups["realized"] != 0 || groups["unrealized"] != 0 {
		t.Fatal("未知を損益0の線へ描きました", groups)
	}
	var resource ResourceMeta
	if err = json.Unmarshal(meta["resource"], &resource); err != nil || resource.Title != data.Resource.Title || resource.MethodID != data.Resource.MethodID {
		t.Fatal("元の文字列根拠を失いました", err)
	}
	if _, err = RenderChartPNG(renderFixture(), 800, 700, filepath.Join(t.TempDir(), "missing-font.ttf")); err == nil || !strings.Contains(err.Error(), "font_path") {
		t.Fatal("指定フォント欠損を成功にしました", err)
	}
	for _, dims := range [][2]int{{799, 700}, {800, 699}, {2401, 1200}, {1600, 2401}} {
		if _, err = RenderChartSVG(data, dims[0], dims[1]); err == nil {
			t.Fatal("過大又は過小画像を受けました", dims)
		}
	}
}
