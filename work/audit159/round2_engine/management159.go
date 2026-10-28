package main

import (
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
	"strings"
)

// decelerated159 は15秒換算の順行が残る一方、5秒換算の速度が半分未満なら失速とします。
//
// 引数: s(Support157)、side(int)。返り値: bool。観測未知は失速と混同しません。
func decelerated159(s Support157, side int) bool {
	d := float64(side)
	return s.Known && d*s.Own15 > 0 && 3*d*s.Own5 < .5*d*s.Own15
}

// effective159 は時間帯限定案だけ非対象枠を基準の厳密数量に戻します。
//
// 引数: original(Policy157)、phase(string)。返り値: Policy157。指標・元Sourceは変更しません。
func effective159(original Policy157, phase string) Policy157 {
	if original.PhaseSelection != "" && original.PhaseSelection != phase {
		original.Exact = true
		original.Fixed = true
		original.Quantum = 10
	}
	return original
}

// extraRisk159 は元返済通知を優先した後に候補固有の保護だけを追加します。
//
// 引数: r(*PolicyResult157)、o(Observation)、supports(map[int]Support157)。返り値: なし。
func extraRisk159(r *PolicyResult157, o strategy.Observation, supports map[int]Support157) {
	if r.Config.ExcessProtection {
		excessRisk159(r, o, supports)
		return
	}
	if !normal(o) {
		for _, p := range r.Parents {
			p.GuardSince159 = 0
			p.GuardLastObservation159 = 0
		}
		return
	}
	b := r.Canonical
	for _, key := range sortedParents157(r.Parents) {
		p := r.Parents[key]
		s := supports[p.Side]
		a, z := b.position(key, "")
		held := a + z
		if held == 0 {
			continue
		}
		if r.Config.LossGuard && strings.HasPrefix(p.Owner, "前半/") {
			// 当時の反対支持が未知、原板間隔が5秒超、又は条件解除なら継続時計を破棄します。
			if !s.Known || o.Time-p.GuardLastObservation159 > 5 || p.GuardLastObservation159 == 0 {
				p.GuardSince159 = 0
			}
			p.GuardLastObservation159 = o.Time
			bad := s.Known && s.Opp >= .5 && float64(p.Side)*s.Own15 < 0 && float64(p.Side)*s.Own5 <= 0
			ready := elapsed157(&p.GuardSince159, bad, o.Time, 5)
			if ready {
				for _, id := range b.Active {
					l := b.Lots[id]
					if l.Parent != key || b.reservedClose(id) > 0 {
						continue
					}
					mark := o.Bid
					if l.Side < 0 {
						mark = o.Ask
					}
					if float64(l.Side)*(mark-l.Entry) <= -80 {
						b.closeLot(p, o, id, "前半逆行80ptと反対支持5秒", l.Remaining, s)
					}
				}
			}
		}
		if r.Config.ProtectionStart > 0 && strings.HasPrefix(p.Owner, r.Config.ProtectionPhase+"/") {
			for _, id := range b.Active {
				l := b.Lots[id]
				if l.Parent != key || b.reservedClose(id) > 0 {
					continue
				}
				mark := o.Bid
				if l.Side < 0 {
					mark = o.Ask
				}
				gain := float64(l.Side) * (mark - l.Entry)
				if gain >= r.Config.ProtectionStart {
					l.Activated = true
				}
				if l.Activated {
					floor := l.Entry + float64(l.Side)*math.Max(0, l.Best-r.Config.ProtectionTrail)
					if l.Floor == 0 || float64(l.Side)*(floor-l.Floor) > 0 {
						l.Floor = floor
					}
					if float64(l.Side)*(mark-l.Floor) <= 0 {
						b.closeLot(p, o, id, "後半全玉の固定利益追尾", l.Remaining, s)
					}
				}
			}
		}
	}
}
