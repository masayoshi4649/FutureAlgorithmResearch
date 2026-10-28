package main

import (
	"encoding/json"
	"fmt"
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"sync"
)

type Scene struct {
	Session, Kind                          string
	Start, USOpen, ForceClose, End, Cutoff float64
	Partial                                bool
	Books                                  map[string]string
	Candles                                map[string]map[string]string
}
type Saved struct {
	Scene  Scene `json:"scene"`
	Source struct {
		Signals []strategy.Signal `json:"signals"`
	} `json:"source"`
	Cases []struct {
		Config struct {
			ID string `json:"id"`
		} `json:"config"`
		Decisions []struct {
			Parent, Action, Reason string
			Index                  int64
			Time                   float64
			Support                Support157
		} `json:"decisions"`
	} `json:"cases"`
}
type Window struct {
	Name, Reason                                            string
	Seconds, CurrentAt, EndpointAt, EndpointAge, PreviousAt float64
	BadDifference                                           int64
	Value                                                   float64
	InvalidAt, GapAt                                        []float64
}
type Row struct {
	Session, Parent, Owner, Reason  string
	Index                           int64
	Time                            float64
	Side                            int
	SavedSupport, CalculatedSupport Support157
	Windows                         []Window
	OwnCurrent, PeerCurrent         map[string]any
	KnownMatch, AllSupportMatch     bool
}
type Output struct {
	Rows                         []Row
	Counts                       map[string]int
	KnownMismatch, ValueMismatch int
	FinancialReplay              bool
}

// window は売買を作らず各窓の未成立理由と直前時計を調べます。
//
// 引数: name(string)、rows([]supportRow157)、i(int)、seconds/tolerance(float64)。返り値: Window。
func window(name string, rows []supportRow157, i int, seconds, tolerance float64) Window {
	w := Window{Name: name, Seconds: seconds}
	if i < 0 {
		w.Reason = "現在値なし"
		return w
	}
	r := rows[i]
	w.CurrentAt = r.Time
	j := sort.Search(i+1, func(j int) bool { return rows[j].Time > r.Time-seconds }) - 1
	if !r.Valid {
		w.Reason = "現在気配異常"
		return w
	}
	if j < 0 {
		w.Reason = "窓端履歴なし"
		return w
	}
	w.EndpointAt = rows[j].Time
	w.EndpointAge = r.Time - seconds - rows[j].Time
	w.BadDifference = r.Bad - rows[j].Bad
	if j > 0 {
		w.PreviousAt = rows[j-1].Time
	}
	for k := j + 1; k <= i; k++ {
		if !rows[k].Valid {
			w.InvalidAt = append(w.InvalidAt, rows[k].Time)
		}
		if rows[k].Time-rows[k-1].Time > 15 {
			w.GapAt = append(w.GapAt, rows[k].Time)
		}
	}
	if !rows[j].Valid {
		w.Reason = "窓端気配異常"
	} else if w.EndpointAge > tolerance {
		w.Reason = "窓端許容遅れ超過"
	} else if w.BadDifference != 0 {
		w.Reason = "窓内の異常気配又は15秒超空白"
	} else {
		w.Value = 10000 * (r.Mid/rows[j].Mid - 1)
		if math.IsNaN(w.Value) || math.IsInf(w.Value, 0) {
			w.Reason = "非有限"
		} else {
			w.Reason = "成立"
		}
	}
	return w
}

// diagnose は凍結計算器と同じ順序で未知の最初の理由を特定します。
//
// 引数: f(*SupportBuilder157)、at(float64)。返り値: 理由string、窓[]Window、現在時計等map2個。
func diagnose(f *SupportBuilder157, at float64) (string, []Window, map[string]any, map[string]any) {
	own, peer := f.Markets["NK225"], f.Markets["TOPIX"]
	a, b := map[string]any{}, map[string]any{}
	if own == nil || peer == nil || len(own.Rows) == 0 {
		return "二市場履歴なし", nil, a, b
	}
	i := len(own.Rows) - 1
	r := own.Rows[i]
	a = map[string]any{"time": r.Time, "bid": own.Last.Bid, "ask": own.Last.Ask, "bid_quantity": own.Last.BidQuantity, "ask_quantity": own.Last.AskQuantity, "ofi_valid": r.OFIValid}
	j := sort.Search(len(peer.Rows), func(j int) bool { return peer.Rows[j].Time >= at }) - 1
	if j >= 0 {
		b = map[string]any{"time": peer.Rows[j].Time, "age": at - peer.Rows[j].Time}
	}
	ws := []Window{window("自己5秒", own.Rows, i, 5, 2), window("自己15秒", own.Rows, i, 15, 2), window("自己120秒", own.Rows, i, 120, 15), window("自己300秒", own.Rows, i, 300, 15), window("相手120秒", peer.Rows, j, 120, 15)}
	if r.Time != at {
		return "自己現在時計不一致", ws, a, b
	}
	if !r.Valid {
		return "現在気配異常", ws, a, b
	}
	if !r.OFIValid {
		return "現在OFI差分不成立", ws, a, b
	}
	if j < 0 || at-peer.Rows[j].Time > 15 {
		return "相手現在鮮度不足", ws, a, b
	}
	for _, w := range ws {
		if w.Reason != "成立" {
			return w.Name + ":" + w.Reason, ws, a, b
		}
	}
	k := sort.Search(len(own.Rows), func(k int) bool { return own.Rows[k].Time >= at-30 }) - 1
	if k < 0 {
		return "OFI30秒履歴不足", ws, a, b
	}
	if r.Bad != own.Rows[k].Bad {
		return "OFI30秒異常又は空白", ws, a, b
	}
	if r.OFICount-own.Rows[k].OFICount < 2 {
		return "OFI差分2件未満", ws, a, b
	}
	return "支持計算既知", ws, a, b
}

// one は保存Source初回原行だけの支持計算を照合します。売買モデルは呼びません。
//
// 引数: path(string)。返り値: []Row,error。
func one(path string) ([]Row, error) {
	var d Saved
	if e := readJSON(path, &d); e != nil {
		return nil, e
	}
	targets := map[int64][]strategy.Signal{}
	seen := map[string]bool{}
	saved := map[string]Support157{}
	for _, c := range d.Cases {
		if c.Config.ID == "B00" {
			for _, v := range c.Decisions {
				if _, ok := saved[v.Parent]; !ok {
					saved[v.Parent] = v.Support
				}
			}
		}
	}
	for _, s := range d.Source.Signals {
		if s.Action != "new" {
			continue
		}
		key := fmt.Sprintf("%s/%d", s.Owner, s.Campaign)
		if seen[key] {
			continue
		}
		seen[key] = true
		targets[s.SourceIndex] = append(targets[s.SourceIndex], s)
	}
	boards, _, e := loadBoards(d.Scene)
	if e != nil {
		return nil, e
	}
	f := &SupportBuilder157{}
	index := int64(-1)
	out := []Row{}
	for _, b := range boards {
		f.add(b)
		if b.Reference != "NK225" {
			continue
		}
		index++
		for _, sig := range targets[index] {
			key := fmt.Sprintf("%s/%d", sig.Owner, sig.Campaign)
			a := f.get(b.Time, sig.Side)
			prev := saved[key]
			reason, windows, own, peer := diagnose(f, b.Time)
			out = append(out, Row{Session: d.Scene.Session, Parent: key, Owner: sig.Owner, Index: index, Time: b.Time, Side: sig.Side, Reason: reason, SavedSupport: prev, CalculatedSupport: a, Windows: windows, OwnCurrent: own, PeerCurrent: peer, KnownMatch: a.Known == prev.Known, AllSupportMatch: reflect.DeepEqual(a, prev)})
		}
	}
	if len(out) != len(seen) {
		return nil, fmt.Errorf("初回採番照合 %s %d/%d", d.Scene.Session, len(out), len(seen))
	}
	return out, nil
}

// main は登録済み結果を参照して観測可否だけを技術診断します。
//
// 引数: なし。返り値: なし。金融再生・注文・仕様変更はしません。
func main() {
	paths, e := filepath.Glob("../results_go/*.json")
	if e != nil {
		panic(e)
	}
	jobs := make(chan string)
	results := make(chan []Row, len(paths))
	errs := make(chan error, len(paths))
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for p := range jobs {
				v, e := one(p)
				if e != nil {
					errs <- e
				} else {
					results <- v
				}
			}
		}()
	}
	for _, p := range paths {
		jobs <- p
	}
	close(jobs)
	wg.Wait()
	close(results)
	close(errs)
	for e := range errs {
		panic(e)
	}
	out := Output{Counts: map[string]int{}}
	for v := range results {
		out.Rows = append(out.Rows, v...)
	}
	sort.Slice(out.Rows, func(i, j int) bool {
		if out.Rows[i].Time == out.Rows[j].Time {
			return out.Rows[i].Parent < out.Rows[j].Parent
		}
		return out.Rows[i].Time < out.Rows[j].Time
	})
	for _, r := range out.Rows {
		out.Counts[r.Reason]++
		if !r.KnownMatch {
			out.KnownMismatch++
		}
		if !r.AllSupportMatch {
			out.ValueMismatch++
		}
	}
	raw, e := json.MarshalIndent(out, "", "  ")
	if e != nil {
		panic(e)
	}
	if e = os.WriteFile("../支持未知の原行診断157.json", append(raw, '\n'), 0600); e != nil {
		panic(e)
	}
	fmt.Printf("支持診断 %d初回 Known差%d 全値差%d 理由%v\n", len(out.Rows), out.KnownMismatch, out.ValueMismatch, out.Counts)
	if out.KnownMismatch+out.ValueMismatch > 0 {
		os.Exit(1)
	}
}
