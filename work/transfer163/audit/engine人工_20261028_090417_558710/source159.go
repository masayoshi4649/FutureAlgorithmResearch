package main

import (
	"errors"
	"fmt"
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
)

type SourceLot159 struct {
	ID, Owner                           string
	Campaign, Side, Quantity, Remaining int
	Entry, At, Gross, Best, Worst       float64
}
type SourceEvent159 struct {
	Phase                  string
	Signal                 strategy.Signal
	FillIndex              int64
	FillTime, Price, Gross float64
}
type Initial159 struct {
	Phase, Parent, Owner string
	Side, Quantity       int
	Time                 float64
	Index                int64
	Support              Support157
}
type SourceState159 struct {
	CampaignCorrections int
	Phase, Method       string
	P                   *strategy.Portfolio `json:"-"`
	Pending             []strategy.Signal
	Lots                map[string]*SourceLot159
	Events              []SourceEvent159
	Signals             []strategy.Signal
	SeenParents         map[string]bool
	Initials            []Initial159
	Gross               float64
}

// markSource159 は約定直後も返済側気配で源の残玉を評価します。
//
// 引数: o(strategy.Observation)。返り値: なし。売買条件へこの診断値は渡しません。
func (s *SourceState159) markSource159(o strategy.Observation) {
	if !normal(o) {
		return
	}
	for _, l := range s.Lots {
		if l.Remaining > 0 {
			mark := o.Bid
			if l.Side < 0 {
				mark = o.Ask
			}
			gain := float64(l.Side) * (mark - l.Entry)
			l.Best = math.Max(l.Best, gain)
			l.Worst = math.Min(l.Worst, gain)
		}
	}
}

// policySignal159 は返済対象IDから元親を復元し、数量政策向け通知だけを補完します。
//
// 引数: sig(strategy.Signal)。返り値: strategy.Signalとerror。native Sourceへの元通知は変更しません。
func (s *SourceState159) policySignal159(sig strategy.Signal) (strategy.Signal, error) {
	if sig.Action != "close" {
		return sig, nil
	}
	owner := ""
	campaign := 0
	for _, t := range sig.Targets {
		lot := s.Lots[t.ID]
		if lot == nil {
			return sig, fmt.Errorf("政策返済の元所有IDがありません:%s", t.ID)
		}
		if owner == "" {
			owner, campaign = lot.Owner, lot.Campaign
		} else if owner != lot.Owner || campaign != lot.Campaign {
			return sig, errors.New("一返済通知が異なる元親へ跨がっています")
		}
	}
	if owner == "" {
		return sig, errors.New("政策返済対象が空です")
	}
	sig.Owner, sig.Campaign = owner, campaign
	return sig, nil
}

// normal は約定に使える現在ラージ気配だけを認めます。
//
// 引数: o(strategy.Observation)。返り値: boolは有限で正順の気配です。
func normal(o strategy.Observation) bool {
	return o.QuoteOK && o.Bid > 0 && o.Ask > o.Bid && !math.IsNaN(o.Bid) && !math.IsInf(o.Ask, 0)
}

// newSource159 は時間帯の売買状態だけを初期化します。
//
// 引数: scene(Scene)、phase/method(string)、expressions(map[string]string)。返り値: *SourceState159とerror。
func newSource159(scene Scene, phase, method string, expressions map[string]string) (*SourceState159, error) {
	params, e := strategy.ParametersForMethod("NK225", scene.Kind, method)
	if e != nil {
		return nil, e
	}
	p, e := strategy.New(strategy.Config{Reference: "NK225", Product: "NK225mini", Cap: 10, CoreQuantity: 5, ExtraMaxQuantity: 5, LargeTick: 10, PointValue: 100, Parameters: params, RuleExpressions: expressions}, makeSession(scene, scene.Start, scene.ForceClose))
	if e != nil {
		return nil, e
	}
	return &SourceState159{Phase: phase, Method: method, P: p, Lots: map[string]*SourceLot159{}, SeenParents: map[string]bool{}}, nil
}

// flat159 は未確定通知と実所有の両方がない場合だけ真を返します。
//
// 引数: なし。返り値: boolはSourceの決済完了です。
func (s *SourceState159) flat159() bool {
	if len(s.Pending) > 0 {
		return false
	}
	for _, l := range s.Lots {
		if l.Remaining > 0 {
			return false
		}
	}
	return true
}

// namespace159 は時間帯で元IDと所有者を分離し、状態リセット後の衝突を防ぎます。
//
// 引数: sig(strategy.Signal)、phase(string)。返り値: strategy.Signalは独立コピーです。
func namespace159(sig strategy.Signal, phase string) strategy.Signal {
	sig.ID = phase + "/" + sig.ID
	sig.Owner = phase + "/" + sig.Owner
	old := sig.Targets
	sig.Targets = make([]strategy.LotTarget, len(old))
	for i, t := range old {
		t.ID = phase + "/" + t.ID
		sig.Targets[i] = t
	}
	return sig
}

// step159 は過去に判断した注文を次の正常原行で約定後、当行の新規判断を行います。
//
// 引数: o(Observation)、allow(bool)、supports(map[int]Support157)。返り値: []Signalとerror。
func (s *SourceState159) step159(o strategy.Observation, allow bool, supports map[int]Support157) ([]strategy.Signal, error) {
	if normal(o) {
		s.markSource159(o)
		pending := []strategy.Signal{}
		for _, sig := range s.Pending {
			if o.Index <= sig.SourceIndex {
				pending = append(pending, sig)
				continue
			}
			price := o.Bid
			if sig.Side > 0 {
				price = o.Ask
			}
			f := strategy.Fill{SignalID: sig.ID, ExecutionID: sig.ID + "-約定", HoldID: sig.ID + "-玉", Quantity: sig.Quantity, Price: price, Time: o.Time}
			gross := 0.0
			if sig.Action == "new" {
				if s.Lots[f.HoldID] != nil {
					return nil, errors.New("元SourceのID重複")
				}
				s.Lots[f.HoldID] = &SourceLot159{ID: f.HoldID, Owner: sig.Owner, Campaign: sig.Campaign, Side: sig.Side, Quantity: sig.Quantity, Remaining: sig.Quantity, Entry: price, At: o.Time}
			} else {
				f.Closed = append([]strategy.LotTarget(nil), sig.Targets...)
				n := 0
				for _, t := range sig.Targets {
					l := s.Lots[t.ID]
					if l == nil || l.Remaining < t.Quantity || l.Side != -sig.Side {
						return nil, errors.New("元Sourceの所有返済不整合")
					}
					g := float64(l.Side*t.Quantity) * (price - l.Entry) * 100
					l.Gross += g
					l.Remaining -= t.Quantity
					gross += g
					n += t.Quantity
				}
				if n != sig.Quantity {
					return nil, errors.New("元Source返済配賦の不足")
				}
			}
			if e := s.P.OnFill(f); e != nil {
				return nil, e
			}
			if e := s.P.OnOrderDone(sig.ID); e != nil {
				return nil, e
			}
			s.Gross += gross
			s.Events = append(s.Events, SourceEvent159{Phase: s.Phase, Signal: sig, FillIndex: o.Index, FillTime: o.Time, Price: price, Gross: gross})
			s.markSource159(o)
		}
		s.Pending = pending
	}
	sigs, e := s.P.Observe(o, allow)
	if e != nil {
		return nil, e
	}
	s.Pending = append(s.Pending, sigs...)
	s.Signals = append(s.Signals, sigs...)
	out := []strategy.Signal{}
	for _, sig := range sigs {
		key := fmt.Sprintf("%s/%d", sig.Owner, sig.Campaign)
		if sig.Action == "new" && !s.SeenParents[key] {
			s.SeenParents[key] = true
			s.Initials = append(s.Initials, Initial159{Phase: s.Phase, Parent: key, Owner: sig.Owner, Side: sig.Side, Quantity: sig.Quantity, Time: o.Time, Index: o.Index, Support: supports[sig.Side]})
		}
		mapped, e := s.policySignal159(sig)
		if e != nil {
			return nil, e
		}
		if mapped.Campaign != sig.Campaign || mapped.Owner != sig.Owner {
			s.CampaignCorrections++
		}
		out = append(out, namespace159(mapped, s.Phase))
	}
	return out, nil
}
