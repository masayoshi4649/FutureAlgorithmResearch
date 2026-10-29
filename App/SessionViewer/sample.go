package main

import (
	"math"
	"sort"
)

type sampleRow struct {
	N      int64
	Values []any
}
type bucketSample struct {
	First, Last sampleRow
	Min, Max    []sampleRow
	Low, High   []float64
	Has         []bool
}
type sampler struct {
	From, To          float64
	Width, ValueStart int
	Input             int64
	Current           int
	Bucket            *bucketSample
	Selected          map[int64]sampleRow
	Previous          *sampleRow
	Begun             bool
}

// newSampler は時間桶ごとの先頭・全列極値・末尾を保持する縮約器を作ります。
//
// 引数: from/to(float64)、width/valueStart(int)。返り値: *sampler。
func newSampler(from, to float64, width, valueStart int) *sampler {
	return &sampler{From: from, To: to, Width: width, ValueStart: valueStart, Current: -1, Selected: map[int64]sampleRow{}}
}

// numeric は描画配列の数値だけを比較可能な値へ変換します。
//
// 引数: v(any)。返り値: float64、数値かどうか(bool)。
func numeric(v any) (float64, bool) {
	switch x := v.(type) {
	case float64:
		return x, finite(x)
	case int:
		return float64(x), true
	case int64:
		return float64(x), true
	}
	return 0, false
}

// flush は現在の時間桶の代表行を確定します。
//
// 引数: なし。返り値: なし。
func (s *sampler) flush() {
	b := s.Bucket
	if b == nil {
		return
	}
	s.Selected[b.First.N] = b.First
	s.Selected[b.Last.N] = b.Last
	for i, ok := range b.Has {
		if ok {
			s.Selected[b.Min[i].N] = b.Min[i]
			s.Selected[b.Max[i].N] = b.Max[i]
		}
	}
	s.Bucket = nil
}

// add は原順序の1行を受け取り、null境界と約定前後を省略しません。
//
// 引数: row([]any)、force(bool)は約定など必須保存の印。返り値: なし。
func (s *sampler) add(row []any, force bool) {
	s.Input++
	r := sampleRow{N: s.Input, Values: row}
	t, _ := numeric(row[0])
	if t < s.From {
		s.Previous = &r
		return
	}
	if t > s.To {
		return
	}
	if !s.Begun {
		if s.Previous != nil {
			s.Selected[s.Previous.N] = *s.Previous
		}
		s.Begun = true
	}
	if s.Previous != nil {
		for i := s.ValueStart; i < len(row); i++ {
			if (row[i] == nil) != (s.Previous.Values[i] == nil) {
				s.Selected[s.Previous.N] = *s.Previous
				s.Selected[r.N] = r
				break
			}
		}
	}
	if force {
		s.Selected[r.N] = r
	}
	span := math.Max(1, s.To-s.From)
	idx := int((t - s.From) / span * float64(s.Width))
	if idx >= s.Width {
		idx = s.Width - 1
	}
	if idx != s.Current {
		s.flush()
		s.Current = idx
	}
	if s.Bucket == nil {
		n := len(row)
		s.Bucket = &bucketSample{First: r, Min: make([]sampleRow, n), Max: make([]sampleRow, n), Low: make([]float64, n), High: make([]float64, n), Has: make([]bool, n)}
	}
	b := s.Bucket
	b.Last = r
	for i := s.ValueStart; i < len(row); i++ {
		v, ok := numeric(row[i])
		if !ok {
			continue
		}
		if !b.Has[i] || v < b.Low[i] {
			b.Low[i] = v
			b.Min[i] = r
		}
		if !b.Has[i] || v > b.High[i] {
			b.High[i] = v
			b.Max[i] = r
		}
		b.Has[i] = true
	}
	s.Previous = &r
}

// result は選んだ代表行を元の処理順序へ戻します。
//
// 引数: なし。返り値: [][]any。範囲前の直前状態も保持します。
func (s *sampler) result() [][]any {
	s.flush()
	if !s.Begun && s.Previous != nil {
		s.Selected[s.Previous.N] = *s.Previous
	}
	keys := make([]int64, 0, len(s.Selected))
	for k := range s.Selected {
		keys = append(keys, k)
	}
	sort.Slice(keys, func(i, j int) bool { return keys[i] < keys[j] })
	out := make([][]any, 0, len(keys))
	for _, k := range keys {
		out = append(out, s.Selected[k].Values)
	}
	return out
}
