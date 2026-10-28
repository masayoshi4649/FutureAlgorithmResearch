package main

import (
	"errors"
	"reflect"
)

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
	Minimum                       int  `json:"minimum,omitempty"`
	InitialFixed                  int  `json:"initial_fixed,omitempty"`
	ManagementEnabled             bool `json:"management_enabled,omitempty"`
	CoverTrail                    bool `json:"cover_trail,omitempty"`
	SeparateCollapse              bool `json:"separate_collapse,omitempty"`
}

// firstConfigs157 は初巡23条件を第二巡の観測差だけの対照へ供給します。
//
// 引数: なし。返り値: []Policy157。外部設定の改変は別検査で拒否します。
func firstConfigs157() []Policy157 {
	v := []Policy157{
		{ID: "C00", Description: "旧S01全通知の厳密micro換算", Exact: true, OldExit: true, Fixed: true, Quantum: 10, Power: 1},
		{ID: "C01", Description: "旧数量＋各玉80pt防御/40pt利益開始40pt追尾/親8万円", Control: "C00", Fixed: true, Quantum: 10, Power: 1},
		{ID: "C02", Description: "C01＋初回支持選抜", Control: "C01", Fixed: true, Filter: true, Quantum: 10, Power: 1},
		{ID: "B00", Description: "旧Source出口＋旧数量＋初回支持選抜", Control: "C00", OldExit: true, Fixed: true, Filter: true, Quantum: 10, Power: 1},
		{ID: "B01", Description: "旧Source出口＋初回線形micro量/元追加比例", Control: "B00", OldExit: true, Filter: true, Quantum: 1, Power: 1},
	}
	base := Policy157{Filter: true, Quantum: 1, Power: 1}
	for i := 0; i <= 13; i++ {
		p := base
		p.ID = []string{"Q00", "Q01", "Q02", "Q03", "Q04", "Q05", "Q06", "Q07", "Q08", "Q09", "Q10", "Q11", "Q12", "Q13"}[i]
		switch i {
		case 0:
			p.Quantum = 10
			p.Control = "C02"
			p.Description = "支持初回・10micro刻み・元追加比例"
		case 1:
			p.Control = "Q00"
			p.Description = "支持初回・1micro刻み・元追加比例"
		case 2:
			p.Power = 2
			p.Control = "Q01"
			p.Description = "初回数量式を二乗抑制"
		default:
			p.GoodGap = 40
			if i == 4 || i == 6 || i == 11 {
				p.Power = 2
			}
			if i >= 5 {
				p.Cover = true
			}
			if i >= 7 && i <= 11 {
				p.AdverseGap = 40
				p.AdverseMax = 25
			}
			if i == 7 {
				p.AdverseGap = 20
			}
			if i == 9 {
				p.AdverseGap = 60
			}
			if i == 10 {
				p.AdverseMax = 50
			}
			if i == 12 {
				p.GoodGap = 80
			}
			if i == 13 {
				p.GoodGap = 20
			}
			p.Control = map[int]string{3: "Q01", 4: "Q03", 5: "Q03", 6: "Q05", 7: "Q05", 8: "Q07", 9: "Q08", 10: "Q08", 11: "Q08", 12: "Q05", 13: "Q05"}[i]
			p.Description = map[int]string{3: "順行40ptで支持目標まで追加", 4: "二乗抑制＋順行追加", 5: "順行追加＋短期反対支持でセーブ/復帰", 6: "二乗抑制＋セーブ/復帰", 7: "逆行20pt後20pt回復・累計25micro", 8: "逆行40pt後20pt回復・累計25micro", 9: "逆行60pt後20pt回復・累計25micro", 10: "逆行40pt後20pt回復・累計50micro", 11: "二乗抑制＋逆行40pt/累計25micro", 12: "セーブ有・順行追加80pt", 13: "セーブ有・順行追加20pt"}[i]
		}
		v = append(v, p)
	}
	for _, id := range []string{"Q05", "Q08"} {
		for _, p := range v {
			if p.ID == id {
				h := p
				h.ID = "H" + id[1:]
				h.Control = id
				h.Hedge = true
				h.Description = "同じCanonical判断を両側保有で実行"
				v = append(v, h)
				break
			}
		}
	}
	for _, id := range []string{"Q05", "Q08"} {
		for _, p := range v {
			if p.ID == id {
				d := p
				d.ID = "D" + id[1:]
				d.Control = id
				d.SessionSave = true
				d.Description = "場開始比赤字8～16万円で新規量抑制/16万円停止"
				v = append(v, d)
				break
			}
		}
	}
	return v
}

// validate157 は第三巡の固定12政策の意図しない変更を拒否します。
//
// 引数: v([]Policy157)。返り値: errorは条件不一致です。
func validate157(v []Policy157) error {
	if !reflect.DeepEqual(v, configs157()) {
		return errors.New("157第三巡の固定12政策と一致しません")
	}
	return nil
}
