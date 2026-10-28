package main

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"sync"
	"testing"
	"time"
)

// testQuote は現在までの人工気配を一行作ります。
//
// 引数: index(int64)、at/bid/ask(float64)。返り値: Quoteです。
func testQuote(index int64, at, bid, ask float64) Quote {
	return Quote{Index: index, Line: index + 1, Time: at, Bid: bid, Ask: ask}
}

// TestSerialParallelSame153 は人工原板に対する単独・4並列の全保存結果一致を検査します。
//
// 引数: t(*testing.T)。返り値: なし。金融原資料や既存期待損益は読みません。
func TestSerialParallelSame153(t *testing.T) {
	directory := t.TempDir()
	start := time.Date(2026, 1, 5, 0, 0, 0, 0, time.UTC)
	path := filepath.Join(directory, "人工板.jsonl")
	file, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 1000; i++ {
		at := start.Add(time.Duration(i) * time.Second).Format(time.RFC3339)
		mid := 10000. + float64(i)/10
		_, err = fmt.Fprintf(file, "{\"CurrentPriceTime\":%q,\"Buy1\":{\"Price\":%.3f},\"Sell1\":{\"Price\":%.3f}}\n", at, mid-.5, mid+.5)
		if err != nil {
			t.Fatal(err)
		}
	}
	_ = file.Close()
	scene := Scene{Session: "人工_Day", Kind: "Day", Start: float64(start.Unix()), ForceClose: float64(start.Unix()) + 900, End: float64(start.Unix()) + 1000, Books: map[string]string{"NK225": path, "TOPIX": path}}
	jobs := []Job{{scene, "NK225"}, {scene, "TOPIX"}}
	other := scene
	other.Session = "別人工_Day"
	jobs = append(jobs, Job{other, "NK225"}, Job{other, "TOPIX"})
	var configs []Config
	if err = readJSON("../configs153r2.json", &configs); err != nil {
		t.Fatal(err)
	}
	collect := func(workers int) map[string]string {
		var mutex sync.Mutex
		result := map[string]string{}
		err := runJobs(jobs, configs, workers, func(saved Saved) error {
			raw, err := json.Marshal(saved)
			if err != nil {
				return err
			}
			mutex.Lock()
			result[saved.Scene.Session+saved.Symbol] = string(raw)
			mutex.Unlock()
			return nil
		})
		if err != nil {
			t.Fatal(err)
		}
		return result
	}
	if !reflect.DeepEqual(collect(1), collect(4)) {
		t.Fatal("並列化で売買又は会計が変化しました")
	}
}

// testCase は金融原資料を使わず単独条件を生成します。
//
// 引数: allocation/exit(string)。返り値: *Resultです。
func testCase(allocation, exit string) *Result {
	return newResult(Scene{Session: "人工_Day", Kind: "Day", Start: 100, ForceClose: 900, End: 1000}, "NK225", Config{"人工", 180, 30, allocation, exit})
}

// testStep は人工入力を一行進め、異常時は試験を停止します。
//
// 引数: t(*testing.T)、c(*Result)、q(Quote)、slope(float64)。返り値: なし。
func testStep(t *testing.T, c *Result, q Quote, slope float64) {
	t.Helper()
	if err := step(c, q, Feature{Known: true, MA: 10000, Previous: 9999, Slope: slope}); err != nil {
		t.Fatal(err)
	}
}

// TestProportional153 は弱い方向が1枚、急な方向が10枚になる境界を確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestProportional153(t *testing.T) {
	for _, v := range []struct {
		speed float64
		want  int
	}{{-4, 1}, {0, 1}, {.25, 1}, {.5, 2}, {1, 4}, {2.5, 10}, {10, 10}} {
		if got := proportional(v.speed); got != v.want {
			t.Fatal(v, got)
		}
	}
}

// TestTimeWeightedAverage153 は件数でなく経過時間の面積を平均します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestTimeWeightedAverage153(t *testing.T) {
	a := Average{}
	for i, v := range []struct{ at, mid float64 }{{0, 100}, {30, 200}, {60, 300}, {90, 400}} {
		if err := a.Add(testQuote(int64(i), v.at, v.mid-.5, v.mid+.5)); err != nil {
			t.Fatal(err)
		}
	}
	f := a.Get(60, 30)
	want := 10000 * (250./150. - 1) * 2
	if !f.Known || f.MA != 250 || f.Previous != 150 || math.Abs(f.Slope-want) > 1e-8 {
		t.Fatal(f, want)
	}
}

// TestDuplicateTimestamp153 は同時刻を何行追加しても時間重みが増えないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestDuplicateTimestamp153(t *testing.T) {
	a, b := Average{}, Average{}
	for i := 0; i <= 100; i++ {
		q := testQuote(int64(i), float64(i), 99+float64(i), 101+float64(i))
		_ = a.Add(q)
		_ = b.Add(q)
		for n := 0; n < 10; n++ {
			_ = b.Add(q)
		}
	}
	if !reflect.DeepEqual(a.Get(60, 30), b.Get(60, 30)) {
		t.Fatal("同時計の重みが増えました")
	}
}

// TestUnknownAndGap153 は異常板と120秒超の空白を架空補間しません。
//
// 引数: t(*testing.T)。返り値: なし。
func TestUnknownAndGap153(t *testing.T) {
	a := Average{}
	_ = a.Add(testQuote(0, 0, 99, 101))
	_ = a.Add(testQuote(1, 121, 99, 101))
	if a.Get(60, 30).Known {
		t.Fatal("120秒超の空白を既知にした")
	}
	_ = a.Add(testQuote(2, 211, 99, 101))
	if !a.Get(60, 30).Known {
		t.Fatal("全窓の復帰を認識しない")
	}
	_ = a.Add(testQuote(3, 212, 102, 101))
	_ = a.Add(testQuote(4, 213, 99, 101))
	if a.Get(60, 30).Known {
		t.Fatal("異常板区間を補間した")
	}
}

// TestPrefixCausality153 は接頭部が同じなら、その後の値動きに関係なく当時の平均が同じことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestPrefixCausality153(t *testing.T) {
	build := func(tail float64) []Feature {
		a := Average{}
		var result []Feature
		for i := 0; i < 300; i++ {
			mid := 100. + float64(i)/100
			if i >= 150 {
				mid = tail
			}
			_ = a.Add(testQuote(int64(i), float64(i), mid-.01, mid+.01))
			if i < 150 {
				result = append(result, a.Get(60, 30))
			}
		}
		return result
	}
	if !reflect.DeepEqual(build(50), build(1000)) {
		t.Fatal("未来が接頭部へ混入")
	}
}

// TestNextValidQuote153 は同原行・異常気配で約定せず、判断後の次正常板を使います。
//
// 引数: t(*testing.T)。返り値: なし。
func TestNextValidQuote153(t *testing.T) {
	c := testCase("entry", "T")
	testStep(t, c, testQuote(0, 100, 9999, 10000), 2.5)
	if len(c.Events) != 0 || c.Pending.Quantity != 10 {
		t.Fatal("当行で約定")
	}
	testStep(t, c, testQuote(1, 101, 10001, 10000), 2.5)
	if len(c.Events) != 0 {
		t.Fatal("交差気配で約定")
	}
	testStep(t, c, testQuote(2, 102, 10009, 10010), 2.5)
	if len(c.Events) != 1 || c.Events[0].Price != 10010 || c.MaxQuantity != 10 {
		t.Fatal("次正常売気配で約定しない")
	}
}

// TestTrailingSymmetryAndAdverseFill153 は利益追尾後の次板赤字も買売対称に計上します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestTrailingSymmetryAndAdverseFill153(t *testing.T) {
	for _, side := range []int{1, -1} {
		c := testCase("entry", "T")
		c.OpeningMid = 10000
		quote := func(i int64, gain float64) Quote {
			mark := 10000 + float64(side)*gain
			if side > 0 {
				return testQuote(i, 100+float64(i), mark, mark+1)
			}
			return testQuote(i, 100+float64(i), mark-1, mark)
		}
		testStep(t, c, quote(0, -1), float64(side))
		testStep(t, c, quote(1, -1), float64(side))
		testStep(t, c, quote(2, 7), float64(side))
		testStep(t, c, quote(3, 3), float64(side))
		if c.Pending == nil || c.Pending.Reason != "利益開始後3bp戻り" {
			t.Fatal("追尾が発火しない")
		}
		testStep(t, c, quote(4, -5), float64(side))
		if c.Gross >= 0 || c.Profit != 0 || c.Loss <= 0 || len(c.Parents) != 1 || c.Parents[0].WorstGain != -5 {
			t.Fatal("次板悪化を消した", c.Gross, c.Parents)
		}
	}
}

// TestUnknownSlopeStillStops153 は傾き未知でも既知気配の防御を止めません。
//
// 引数: t(*testing.T)。返り値: なし。
func TestUnknownSlopeStillStops153(t *testing.T) {
	c := testCase("dynamic", "D")
	testStep(t, c, testQuote(0, 100, 9999, 10000), 1)
	testStep(t, c, testQuote(1, 101, 9999, 10000), 1)
	if err := step(c, testQuote(2, 102, 9980, 9981), Feature{}); err != nil {
		t.Fatal(err)
	}
	if c.Pending == nil || c.Pending.Reason != "初期逆行12bp" {
		t.Fatal("未知角度で価格防御を停止")
	}
}

// TestDecelerationRequiresStrengthening153 は入口の2倍未達の単純半減ではD退出しません。
//
// 引数: t(*testing.T)。返り値: なし。
func TestDecelerationRequiresStrengthening153(t *testing.T) {
	c := testCase("entry", "D")
	testStep(t, c, testQuote(0, 100, 9999, 10000), 1)
	testStep(t, c, testQuote(1, 101, 9999, 10000), 1)
	testStep(t, c, testQuote(2, 102, 10000, 10001), 1.8)
	testStep(t, c, testQuote(3, 103, 10000, 10001), .7)
	if c.Pending != nil {
		t.Fatal("2倍未達で半減退出")
	}
	testStep(t, c, testQuote(4, 104, 10000, 10001), 2.2)
	testStep(t, c, testQuote(5, 105, 10000, 10001), 1.1)
	if c.Pending == nil || c.Pending.Reason != "2倍へ増勢後に傾き半減" {
		t.Fatal("増勢後半減を検出しない")
	}
}

// TestDynamicAnchorAndFIFO153 は追加でも価格停止線を緩めず、縮小を古い玉から返済します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestDynamicAnchorAndFIFO153(t *testing.T) {
	c := testCase("dynamic", "T")
	testStep(t, c, testQuote(0, 100, 9999, 10000), 1)
	testStep(t, c, testQuote(1, 101, 9999, 10000), 1)
	testStep(t, c, testQuote(2, 110, 10001, 10002), 2.5)
	if c.Pending != nil {
		t.Fatal("10秒より早く増玉")
	}
	testStep(t, c, testQuote(3, 111, 10001, 10002), 2.5)
	testStep(t, c, testQuote(4, 112, 10001, 10002), 2.5)
	if c.Quantity != 10 || c.Current.Anchor != 10000 || c.Current.EntrySlope != 1 {
		t.Fatal("追加で親基準を変えた")
	}
	testStep(t, c, testQuote(5, 122, 10002, 10003), .1)
	if c.Pending == nil || c.Pending.Quantity != 9 {
		t.Fatal("弱化で1枚へ縮小しない")
	}
	testStep(t, c, testQuote(6, 123, 10003, 10004), .1)
	last := c.Events[len(c.Events)-1]
	if c.Quantity != 1 || len(last.Closed) != 2 || last.Closed[0].LotID != 1 || last.Closed[0].Quantity != 4 || last.Closed[1].LotID != 2 || last.Closed[1].Quantity != 5 || c.Gross != 1700 {
		t.Fatal("FIFO又は会計が異なる", last, c.Gross)
	}
}

// TestOppositeDirectionFlatFirst153 はZの反転を先に全返済し、10秒待った後だけ逆側へ入ります。
//
// 引数: t(*testing.T)。返り値: なし。
func TestOppositeDirectionFlatFirst153(t *testing.T) {
	c := testCase("dynamic", "Z")
	testStep(t, c, testQuote(0, 100, 9999, 10000), 1)
	testStep(t, c, testQuote(1, 101, 9999, 10000), 1)
	testStep(t, c, testQuote(2, 102, 10000, 10001), -2)
	if c.Pending == nil || c.Pending.Action != "close" || c.Pending.Quantity != 4 {
		t.Fatal("反転で縮小又は両建て")
	}
	testStep(t, c, testQuote(3, 103, 10000, 10001), -2)
	if c.Quantity != 0 || c.Pending != nil {
		t.Fatal("返済行で即反対注文")
	}
	testStep(t, c, testQuote(4, 112, 10000, 10001), -2)
	if c.Pending != nil {
		t.Fatal("10秒前に再参加")
	}
	testStep(t, c, testQuote(5, 113, 10000, 10001), -2)
	if c.Pending == nil || c.Pending.Action != "new" || c.Pending.Side != -1 {
		t.Fatal("待機後に逆側へ再参加しない")
	}
}

// TestTReverseOnlyShrinks153 はTだけなら逆向きの角度を新規反転へ流用しません。
//
// 引数: t(*testing.T)。返り値: なし。
func TestTReverseOnlyShrinks153(t *testing.T) {
	c := testCase("dynamic", "T")
	testStep(t, c, testQuote(0, 100, 9999, 10000), 2.5)
	testStep(t, c, testQuote(1, 101, 9999, 10000), 2.5)
	testStep(t, c, testQuote(2, 111, 10000, 10001), -3)
	if c.Pending == nil || c.Pending.Action != "close" || c.Pending.Quantity != 9 || c.Pending.Reason != "比例枚数へ縮小" {
		t.Fatal("Tが反転全返済又は逆新規した")
	}
}

// TestBoundaryPending153 は境界前に判断済みの新規を勝手に取消さず、約定後に返済します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestBoundaryPending153(t *testing.T) {
	c := testCase("entry", "T")
	testStep(t, c, testQuote(0, 899, 9999, 10000), 2.5)
	testStep(t, c, testQuote(1, 900, 10001, 10000), 2.5)
	if c.Pending.Action != "new" {
		t.Fatal("判断済み新規を取消した")
	}
	testStep(t, c, testQuote(2, 901, 10009, 10010), 2.5)
	if c.Quantity != 10 || c.Pending == nil || c.Pending.Action != "close" {
		t.Fatal("境界後約定を返済しない")
	}
	testStep(t, c, testQuote(3, 902, 10000, 10001), 2.5)
	if err := finish(c); err != nil {
		t.Fatal(err)
	}
}

// TestFixedQuantityPaths153 は初回比例固定と1枚・10枚対照の価格経路が枚数以外同じことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestFixedQuantityPaths153(t *testing.T) {
	var baseline []Order
	for _, allocation := range []string{"entry", "fixed1", "fixed10"} {
		c := testCase(allocation, "D")
		for i, v := range []struct{ at, bid, slope float64 }{{100, 9999, 1}, {101, 9999, 1}, {102, 10001, 2.2}, {103, 10001, 1}, {104, 10002, 1}, {120, 10000, -1}, {121, 10000, -1}, {900, 9990, -1}, {901, 9990, -1}} {
			testStep(t, c, testQuote(int64(i), v.at, v.bid, v.bid+1), v.slope)
		}
		var orders []Order
		for _, event := range c.Events {
			o := event.Order
			o.Quantity = 0
			orders = append(orders, o)
		}
		if baseline == nil {
			baseline = orders
		} else if !reflect.DeepEqual(baseline, orders) {
			t.Fatal("固定数量で経路が変化", allocation)
		}
	}
}

// TestPartialSessionNoInventedClose153 は途中末尾を架空返済せず含みを残します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestPartialSessionNoInventedClose153(t *testing.T) {
	c := testCase("entry", "T")
	c.Partial = true
	testStep(t, c, testQuote(0, 100, 9999, 10000), 1)
	testStep(t, c, testQuote(1, 101, 9999, 10000), 1)
	if err := finish(c); err != nil {
		t.Fatal(err)
	}
	if c.Quantity != 4 || c.Gross != 0 || c.Unrealized != -400 {
		t.Fatal("途中玉の含み会計が不正")
	}
}

// TestConfigAndRegistration153 は8条件と受領両成功を金融前に固定します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestConfigAndRegistration153(t *testing.T) {
	var configs []Config
	if err := readJSON("../configs153r2.json", &configs); err != nil {
		t.Fatal(err)
	}
	if err := validateConfigs(configs); err != nil {
		t.Fatal(err)
	}
	configs[0].Window = 61
	if validateConfigs(configs) == nil {
		t.Fatal("固定条件変更を許可")
	}
	for _, v := range []struct {
		raw  string
		okay bool
	}{{`{"registered":true,"returncode":0}`, true}, {`{"registered":false,"returncode":0}`, false}, {`{"registered":true,"returncode":1}`, false}, {`{"registered":true}`, false}} {
		path := filepath.Join(t.TempDir(), "受領.json")
		_ = os.WriteFile(path, []byte(v.raw), 0600)
		if (registrationOK(path) == nil) != v.okay {
			t.Fatal("登録受領のANDが不正")
		}
	}
}
