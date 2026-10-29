// 既存の研究結果から約定だけを抽出し、小さいJSONLを作成します。
package main

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"time"
)

type sourceLot struct{ Side int }
type sourcePiece struct {
	ID                 string
	Quantity           int
	Entry, Exit, Gross float64
}
type sourceEvent struct {
	Order struct {
		ID             string
		Side, Quantity int
		Targets        []json.RawMessage
	}
	FillIndex              int64
	FillTime, Price, Gross float64
	HoldID                 string
	Pieces                 []sourcePiece
}
type sourceCase struct {
	Config struct {
		ID string `json:"id"`
	}
	Actual struct {
		Realized float64
		Events   []sourceEvent
		Lots     map[string]sourceLot
	}
}
type sourceScene struct {
	Session, Kind      string
	Start, End, Cutoff float64
	Books              map[string]string
}
type sourceDocument struct {
	Scene sourceScene
	Cases []sourceCase
}
type trade struct {
	ID         string  `json:"id"`
	Timestamp  string  `json:"timestamp"`
	Type       string  `json:"type"`
	PositionID string  `json:"position_id"`
	Price      float64 `json:"price"`
	Qty        int     `json:"qty"`
	MethodID   string  `json:"method_id"`
	SourceLine int64   `json:"source_line"`
}

type sourceQuote struct {
	Line int64
	At   time.Time
}

// rawLines は既存研究と同じ採用条件で約定原行番号を物理行へ対応させます。
//
// 引数: path(string)、scene(sourceScene)、wanted(map[int64][]sourceEvent)。
// 返り値: 原行添字から物理行・原時計への対応(map[int64]sourceQuote)とerror。売買判断は実行しません。
func rawLines(path string, scene sourceScene, wanted map[int64][]sourceEvent) (map[int64]sourceQuote, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	scan := bufio.NewScanner(f)
	scan.Buffer(make([]byte, 65536), 8*1024*1024)
	result := map[int64]sourceQuote{}
	previous := scene.Start
	var line, index int64
	for scan.Scan() {
		line++
		var row struct {
			CurrentPriceTime *string
			CurrentPrice     float64
			Buy1, Sell1      struct{ Price float64 }
		}
		if err = json.Unmarshal(scan.Bytes(), &row); err != nil {
			return nil, fmt.Errorf("原板%d行: %w", line, err)
		}
		if row.CurrentPriceTime == nil {
			continue
		}
		at, e := time.Parse(time.RFC3339Nano, *row.CurrentPriceTime)
		if e != nil {
			continue
		}
		seconds := float64(at.UnixNano()) / 1e9
		if seconds < scene.Start || seconds > scene.End || (scene.Cutoff > 0 && seconds >= scene.Cutoff) || seconds < previous || row.CurrentPrice <= 0 || math.IsNaN(row.CurrentPrice) || math.IsInf(row.CurrentPrice, 0) {
			continue
		}
		previous = seconds
		if events, ok := wanted[index]; ok {
			for _, event := range events {
				price := row.Buy1.Price
				if event.Order.Side > 0 {
					price = row.Sell1.Price
				}
				if event.FillTime != seconds || event.Price != price || row.Buy1.Price <= 0 || row.Sell1.Price <= row.Buy1.Price {
					return nil, fmt.Errorf("保存約定と原板が一致しません: %s・物理%d行", event.Order.ID, line)
				}
			}
			result[index] = sourceQuote{Line: line, At: at}
		}
		index++
	}
	if err = scan.Err(); err != nil {
		return nil, err
	}
	if len(result) != len(wanted) {
		return nil, fmt.Errorf("約定原行が原板に見つかりません: %d/%d", len(result), len(wanted))
	}
	return result, nil
}

// records は保存約定の対象IDを保ち、返済配賦ごとの最小記録を生成します。
//
// 引数: c(sourceCase)、lines(map[int64]sourceQuote)、pointValue(float64)。
// 返り値: []tradeとerror。元の確定損益に一致しなければ保存しません。
func records(c sourceCase, lines map[int64]sourceQuote, pointValue float64) ([]trade, error) {
	result := []trade{}
	zone := time.FixedZone("JST", 9*60*60)
	total := 0.0
	for _, e := range c.Actual.Events {
		quote, ok := lines[e.FillIndex]
		if !ok {
			return nil, fmt.Errorf("原行の対応がありません: %s", e.Order.ID)
		}
		at := quote.At.In(zone).Format(time.RFC3339Nano)
		if len(e.Order.Targets) == 0 {
			kind := "LongN"
			if e.Order.Side < 0 {
				kind = "ShortN"
			}
			if e.HoldID == "" || e.Order.Quantity <= 0 {
				return nil, fmt.Errorf("保存新規のID又は枚数が不正です")
			}
			result = append(result, trade{ID: e.Order.ID, Timestamp: at, Type: kind, PositionID: e.HoldID, Price: e.Price, Qty: e.Order.Quantity, MethodID: c.Config.ID, SourceLine: quote.Line})
			continue
		}
		gross := 0.0
		for i, p := range e.Pieces {
			lot, ok := c.Actual.Lots[p.ID]
			if !ok || p.Quantity <= 0 {
				return nil, fmt.Errorf("保存返済の対象又は枚数が不正です")
			}
			expected := float64(lot.Side*p.Quantity) * (p.Exit - p.Entry) * pointValue
			if math.Abs(expected-p.Gross) > 1e-5 || p.Exit != e.Price {
				return nil, fmt.Errorf("返済配賦の損益が商品倍率と一致しません: %s", p.ID)
			}
			kind := "LongR"
			if lot.Side < 0 {
				kind = "ShortR"
			}
			result = append(result, trade{ID: fmt.Sprintf("%s/%d", e.Order.ID, i+1), Timestamp: at, Type: kind, PositionID: p.ID, Price: e.Price, Qty: p.Quantity, MethodID: c.Config.ID, SourceLine: quote.Line})
			gross += p.Gross
		}
		if math.Abs(gross-e.Gross) > 1e-5 {
			return nil, fmt.Errorf("返済配賦と約定合計が不一致です")
		}
		total += gross
	}
	if math.Abs(total-c.Actual.Realized) > 1e-5 {
		return nil, fmt.Errorf("保存確定損益と抽出合計が不一致です")
	}
	return result, nil
}

// writeNew は生成済み約定だけを新しいJSONLへ保存します。
//
// 引数: path(string)、rows([]trade)。返り値: error。原板や既存出力を上書きしません。
func writeNew(path string, rows []trade) error {
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return err
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	defer f.Close()
	out := bufio.NewWriter(f)
	encoder := json.NewEncoder(out)
	encoder.SetEscapeHTML(false)
	for _, row := range rows {
		if err = encoder.Encode(row); err != nil {
			return err
		}
	}
	if err = out.Flush(); err != nil {
		return err
	}
	return f.Sync()
}

// run は保存結果を選び、売買を再実行せずに可視化用の記録へ変換します。
//
// 引数: input/method/output/book(string)、pointValue(float64)。返り値: error。
func run(input, method, output, book string, pointValue float64) error {
	if input == "" || method == "" || output == "" || pointValue <= 0 {
		return fmt.Errorf("input/method/output/point-valueを指定してください")
	}
	raw, err := os.ReadFile(input)
	if err != nil {
		return err
	}
	var doc sourceDocument
	if err = json.Unmarshal(raw, &doc); err != nil {
		return err
	}
	var selected *sourceCase
	for i := range doc.Cases {
		if doc.Cases[i].Config.ID == method {
			selected = &doc.Cases[i]
			break
		}
	}
	if selected == nil {
		return fmt.Errorf("指定IDが保存結果にありません: %s", method)
	}
	if book == "" {
		book = doc.Scene.Books["NK225"]
	}
	wanted := map[int64][]sourceEvent{}
	for _, e := range selected.Actual.Events {
		wanted[e.FillIndex] = append(wanted[e.FillIndex], e)
	}
	lines, err := rawLines(book, doc.Scene, wanted)
	if err != nil {
		return err
	}
	rows, err := records(*selected, lines, pointValue)
	if err != nil {
		return err
	}
	if err = writeNew(output, rows); err != nil {
		return err
	}
	info, _ := os.Stat(output)
	fmt.Printf("%s: %d約定片・%dバイト・元確定損益%+.0f円と一致\n", output, len(rows), info.Size(), selected.Actual.Realized)
	return nil
}

// main は研究記録の一回限りの変換を受け付けます。
//
// 引数: CLI指定。返り値: なし。表示アプリ本体の起動引数とは別の生成ツールです。
func main() {
	input := flag.String("input", "", "保存結果JSON")
	method := flag.String("method", "", "抽出する手法ID")
	output := flag.String("output", "", "新規約定JSONL")
	book := flag.String("book", "", "原板パスの上書き。省略時は保存結果内の参照")
	point := flag.Float64("point-value", 10, "価格1単位・1枚の円倍率")
	flag.Parse()
	if err := run(*input, *method, *output, *book, *point); err != nil {
		fmt.Fprintln(os.Stderr, "変換できません:", err)
		os.Exit(1)
	}
}
