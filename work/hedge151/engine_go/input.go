package main

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"sort"
	"time"
)

type sourceSignal struct {
	ID       string  `json:"id"`
	Owner    string  `json:"owner"`
	Action   string  `json:"action"`
	Side     int     `json:"side"`
	Quantity int     `json:"quantity"`
	Time     float64 `json:"time"`
	Index    int64   `json:"source_index"`
	Reason   string  `json:"reason"`
}

// sourceEntryCaseは未来約定を型として取り込まない入口抽出専用型です。
type sourceEntryCase struct {
	Config struct {
		ID string `json:"id"`
	} `json:"config"`
	Events []struct {
		Phase         string       `json:"phase"`
		DecisionIndex int64        `json:"decision_index"`
		Signal        sourceSignal `json:"signal"`
	} `json:"events"`
	FinalPending []sourceSignal `json:"final_pending"`
	CancelledNew int            `json:"cancelled_new"`
}

type SavedEvent struct {
	Phase         string `json:"phase"`
	DecisionIndex int64  `json:"decision_index"`
	FillIndex     int64  `json:"fill_index"`
	Signal        struct {
		ID       string  `json:"id"`
		Owner    string  `json:"owner"`
		Action   string  `json:"action"`
		Side     int     `json:"side"`
		Quantity int     `json:"quantity"`
		Time     float64 `json:"time"`
		Targets  []struct {
			ID       string `json:"id"`
			Quantity int    `json:"quantity"`
		} `json:"targets"`
	} `json:"signal"`
	Fill struct {
		HoldID   string
		Quantity int
		Price    float64
		Time     float64
		Fee      float64
	} `json:"fill"`
	Gross float64 `json:"gross"`
}

// readJSONはUTF-8の保存JSONを型へ復元します。
//
// 引数: path(string)、target(any)。返り値: errorは読取り又は型不整合です。
func readJSON(path string, target any) error {
	raw, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	return json.Unmarshal(raw, target)
}

// writeJSONは新規JSONだけを保存し、既存結果の上書きを拒否します。
//
// 引数: path(string)、value(any)。返り値: errorは既存ファイル又は保存失敗です。
func writeJSON(path string, value any) error {
	raw, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0644)
	if err != nil {
		return err
	}
	_, err = f.Write(raw)
	closeErr := f.Close()
	if err != nil {
		return err
	}
	return closeErr
}

// extractNoticesは保存B04の発注済み新規通知を判断項目だけへ射影します。
//
// 引数: raw([]byte)、scene(Scene)。返り値: []EntryNoticeと不整合errorです。
// 未約定新規も含めます。源実装は全発注を次正常板へ送り、取消分があれば不完全入力として停止します。
func extractNotices(raw []byte, scene Scene) ([]EntryNotice, error) {
	var root struct {
		Cases []sourceEntryCase `json:"cases"`
	}
	if err := json.Unmarshal(raw, &root); err != nil {
		return nil, err
	}
	var selected *sourceEntryCase
	for i := range root.Cases {
		if root.Cases[i].Config.ID == "B04" {
			if selected != nil {
				return nil, errors.New("B04が重複")
			}
			selected = &root.Cases[i]
		}
	}
	if selected == nil || selected.CancelledNew != 0 {
		return nil, errors.New("B04なし又は取消新規を含む入力")
	}
	result := []EntryNotice{}
	seen := map[string]bool{}
	appendSignal := func(phase string, index int64, signal sourceSignal) error {
		if signal.Action != "new" {
			return nil
		}
		key := phase + "/" + signal.ID
		if seen[key] || signal.ID == "" || index != signal.Index || signal.Quantity <= 0 || (signal.Side != 1 && signal.Side != -1) || signal.Time < scene.Start || signal.Time > scene.End {
			return errors.New("新規通知のID・時刻・添字・数量が不正")
		}
		if phase != "前半" && phase != "後半" {
			return errors.New("新規通知の位相が不正")
		}
		seen[key] = true
		result = append(result, EntryNotice{ID: signal.ID, Phase: phase, Owner: signal.Owner, Side: signal.Side, Quantity: signal.Quantity, Time: signal.Time, Index: index, Reason: signal.Reason})
		return nil
	}
	for _, e := range selected.Events {
		if err := appendSignal(e.Phase, e.DecisionIndex, e.Signal); err != nil {
			return nil, err
		}
	}
	for _, p := range selected.FinalPending {
		phase := "前半"
		if p.Time >= scene.USOpen {
			phase = "後半"
		}
		if err := appendSignal(phase, p.Index, p); err != nil {
			return nil, err
		}
	}
	sort.SliceStable(result, func(i, j int) bool { return result[i].Index < result[j].Index })
	return result, nil
}

// loadPostはS04保存後半の全約定を所有IDで再会計します。
//
// 引数: path(string)。返り値: ReusedPostと不整合errorです。
// この保存会計は新規通知の抽出及び売買判断には使用しません。
func loadPost(path string) (ReusedPost, error) {
	var source struct {
		Cases []struct {
			Config struct {
				ID string `json:"id"`
			} `json:"config"`
			Events []SavedEvent `json:"events"`
		} `json:"cases"`
	}
	if err := readJSON(path, &source); err != nil {
		return ReusedPost{}, err
	}
	post := ReusedPost{Source: path, Events: []SavedEvent{}}
	positions := map[string]struct {
		Side, Quantity int
		Price          float64
	}{}
	found := 0
	for _, c := range source.Cases {
		if c.Config.ID != "S04" {
			continue
		}
		found++
		for _, e := range c.Events {
			if e.Phase != "後半" {
				continue
			}
			if e.Fill.Fee != 0 || e.FillIndex <= e.DecisionIndex || e.Fill.Quantity != e.Signal.Quantity {
				return post, errors.New("保存後半の費用又は約定不整合")
			}
			gross := 0.
			if e.Signal.Action == "new" {
				if _, ok := positions[e.Fill.HoldID]; ok {
					return post, errors.New("保存後半ID重複")
				}
				positions[e.Fill.HoldID] = struct {
					Side, Quantity int
					Price          float64
				}{e.Signal.Side, e.Fill.Quantity, e.Fill.Price}
				post.NewCount++
				if post.FirstNewTime == 0 {
					post.FirstNewTime = e.Signal.Time
				}
			} else {
				qty := 0
				for _, t := range e.Signal.Targets {
					p, ok := positions[t.ID]
					if !ok || p.Quantity < t.Quantity || p.Side != -e.Signal.Side {
						return post, errors.New("保存後半の返済所有ID不整合")
					}
					gross += float64(p.Side*t.Quantity) * (e.Fill.Price - p.Price) * 100
					p.Quantity -= t.Quantity
					positions[t.ID] = p
					qty += t.Quantity
				}
				if qty != e.Fill.Quantity {
					return post, errors.New("保存後半の返済数量不整合")
				}
			}
			if gross != e.Gross {
				return post, errors.New("保存後半の損益不一致")
			}
			post.Gross += gross
			if gross > 0 {
				post.Profit += gross
			} else {
				post.Loss -= gross
			}
			post.Events = append(post.Events, e)
		}
	}
	if found != 1 {
		return post, errors.New("保存S04が一意ではありません")
	}
	for _, p := range positions {
		if p.Quantity != 0 {
			return post, errors.New("保存後半が未完済")
		}
	}
	return post, nil
}

// loadQuotesは149/150のNK225採用列と同じ0始まり添字で原板を読みます。
//
// 引数: scene(Scene)。返り値: []Quote、除外件数map[string]intとerrorです。
// 異常BBOは添字に残します。TradingVolumeTimeは価格時計・気配資格の代用にしません。
func loadQuotes(scene Scene) ([]Quote, map[string]int, error) {
	f, err := os.Open(scene.Books["NK225"])
	if err != nil {
		return nil, nil, err
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 65536), 8*1024*1024)
	quotes := []Quote{}
	counts := map[string]int{}
	previous := scene.Start
	for sc.Scan() {
		counts["原行"]++
		var b struct {
			CurrentPriceTime *string
			CurrentPrice     float64
			Buy1, Sell1      struct{ Price float64 }
		}
		if err := json.Unmarshal(sc.Bytes(), &b); err != nil {
			return nil, counts, err
		}
		if b.CurrentPriceTime == nil {
			counts["時計欠測"]++
			continue
		}
		t, err := time.Parse(time.RFC3339Nano, *b.CurrentPriceTime)
		if err != nil {
			counts["時計欠測"]++
			continue
		}
		at := float64(t.UnixNano()) / 1e9
		if at < scene.Start || at > scene.End || (scene.Cutoff > 0 && at >= scene.Cutoff) {
			counts["範囲外"]++
			continue
		}
		if at < previous {
			counts["逆行"]++
			continue
		}
		if b.CurrentPrice <= 0 || !finite(b.CurrentPrice) {
			counts["Last欠測"]++
			continue
		}
		previous = at
		q := Quote{Index: int64(len(quotes)), Line: int64(counts["原行"]), Time: at, Last: b.CurrentPrice, Bid: b.Buy1.Price, Ask: b.Sell1.Price}
		quotes = append(quotes, q)
		counts["採用"]++
		if !quoteOK(q) {
			counts["異常気配"]++
		}
	}
	if err := sc.Err(); err != nil {
		return nil, counts, fmt.Errorf("原板読取: %w", err)
	}
	return quotes, counts, nil
}
