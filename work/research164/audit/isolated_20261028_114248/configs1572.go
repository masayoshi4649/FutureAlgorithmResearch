package main

// configs157 は観測だけの対照23と少量15・固定量2を事前固定します。
//
// 引数: なし。返り値: []Policy157。元SourceとC00は変更しません。
func configs157() []Policy157 {
	values := firstConfigs157()
	for i := range values {
		if values[i].ID == "C00" {
			continue
		}
		values[i].ID = "V_" + values[i].ID
		if values[i].Control != "C00" {
			values[i].Control = "V_" + values[i].Control
		}
		values[i].Description = "観測修正／" + values[i].Description
	}
	for i := 1; i <= 15; i++ {
		p := Policy157{Quantum: 1, Power: 1, Minimum: 10}
		p.ID = []string{"J01", "J02", "J03", "J04", "J05", "J06", "J07", "J08", "J09", "J10", "J11", "J12", "J13", "J14", "J15"}[i-1]
		if i <= 3 || i == 15 {
			p.OldExit = true
		}
		if i == 1 || i == 4 {
			p.Minimum = 5
		}
		if i == 3 || i == 6 {
			p.Minimum = 20
		}
		if i >= 7 && i <= 14 {
			p.GoodGap = 40
		}
		if i >= 8 && i <= 14 {
			p.Cover = true
		}
		if i >= 9 && i <= 14 {
			p.AdverseGap = 40
			p.AdverseMax = 25
		}
		if i == 9 {
			p.AdverseGap = 20
		}
		if i == 11 {
			p.AdverseGap = 60
		}
		if i == 12 {
			p.Hedge = true
		}
		if i == 13 {
			p.SessionSave = true
		}
		if i == 14 {
			p.AdverseMax = 50
		}
		if i == 15 {
			p.Power = 2
		}
		p.Control = map[int]string{1: "J02", 2: "K01", 3: "J02", 4: "J05", 5: "J02", 6: "J05", 7: "J05", 8: "J07", 9: "J08", 10: "J09", 11: "J10", 12: "J10", 13: "J10", 14: "J10", 15: "J02"}[i]
		p.Description = map[int]string{1: "全Source初回採用・旧出口・最低5micro", 2: "全Source初回採用・旧出口・最低10micro", 3: "全Source初回採用・旧出口・最低20micro", 4: "新共通出口・最低5micro", 5: "新共通出口・最低10micro", 6: "新共通出口・最低20micro", 7: "最低10＋順行40追加", 8: "最低10＋順行40＋カバー", 9: "最低10＋逆行20回復・累計25", 10: "最低10＋逆行40回復・累計25", 11: "最低10＋逆行60回復・累計25", 12: "J10と同Canonical・両建て実保有", 13: "J10＋場開始比赤字抑制", 14: "J10の逆行累計上限50micro", 15: "旧出口・最低10・支持量の二乗抑制"}[i]
		values = append(values, p)
	}
	values = append(values, Policy157{ID: "K01", Description: "全Source初回10micro固定・追加比例・旧出口", Control: "C00", OldExit: true, Quantum: 1, Power: 1, InitialFixed: 10}, Policy157{ID: "K02", Description: "全Source初回10micro固定・追加比例・新出口", Control: "K01", Quantum: 1, Power: 1, InitialFixed: 10})
	return values
}
