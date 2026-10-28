package main

// Policy157 は支持と出口を共通に保つ数量政策の固定因子です。
type Policy157 struct {
	ID                            string `json:"id"`
	Description                   string `json:"description"`
	Control                       string `json:"control"`
	Exact, OldExit, Fixed, Filter bool
	Quantum                       int
	Power                         int
	GoodGap, AdverseGap           float64
	AdverseMax                    int
	Cover, Hedge, SessionSave     bool
	Minimum                       int     `json:"minimum,omitempty"`
	InitialFixed                  int     `json:"initial_fixed,omitempty"`
	ManagementEnabled             bool    `json:"management_enabled,omitempty"`
	CoverTrail                    bool    `json:"cover_trail,omitempty"`
	SeparateCollapse              bool    `json:"separate_collapse,omitempty"`
	PhaseSelection                string  `json:"phase_selection,omitempty"`
	InverseSupport                bool    `json:"inverse_support,omitempty"`
	ReselectAdd                   bool    `json:"reselect_add,omitempty"`
	SaveDeceleration              bool    `json:"save_deceleration,omitempty"`
	ProtectionStart               float64 `json:"protection_start,omitempty"`
	ProtectionTrail               float64 `json:"protection_trail,omitempty"`
	ProtectionPhase               string  `json:"protection_phase,omitempty"`
	LossGuard                     bool    `json:"loss_guard,omitempty"`
}

// configs159 は結果を見る前に固定する夜間十二条件を返します。
//
// 引数: なし。返り値: []Policy157。全条件は片側100micro相当で手数料0です。
func configs159() []Policy157 {
	v := []Policy157{}
	ids := []string{"N00", "N01", "N02", "N03", "N04", "N05", "N06", "N07", "N08", "N09", "N10", "N11"}
	names := []string{"現行P05前半とD07後半の数量を厳密換算", "全初回10micro固定の量対照", "J02型の支持連動数量を全夜へ", "前半だけJ02型数量", "後半だけJ02型数量", "支持量を二乗して増枚を抑制", "逆支持数量の反証対照", "後続Source追加も現在支持で抑制", "短期失速では初回最低量", "後半全玉40pt起動40pt追尾", "後半全玉20pt起動20pt追尾", "前半80pt逆行と反対支持5秒で返済"}
	for i, id := range ids {
		p := Policy157{ID: id, Description: names[i], Control: "N02", OldExit: true, Hedge: true, Quantum: 1, Power: 1, Minimum: 10}
		switch i {
		case 0:
			p.Exact = true
			p.Fixed = true
			p.Quantum = 10
			p.Control = "現行夜間"
		case 1:
			p.InitialFixed = 10
			p.Control = "N00"
		case 2:
			p.Control = "N00"
		case 3:
			p.PhaseSelection = "前半"
			p.Control = "N00"
		case 4:
			p.PhaseSelection = "後半"
			p.Control = "N00"
		case 5:
			p.Power = 2
		case 6:
			p.InverseSupport = true
		case 7:
			p.ReselectAdd = true
		case 8:
			p.SaveDeceleration = true
		case 9:
			p.ProtectionStart = 40
			p.ProtectionTrail = 40
			p.ProtectionPhase = "後半"
		case 10:
			p.ProtectionStart = 20
			p.ProtectionTrail = 20
			p.ProtectionPhase = "後半"
		case 11:
			p.LossGuard = true
		}
		v = append(v, p)
	}
	return v
}
