package main

// configs157 は旧元玉出口と独自数量管理を分離する第三巡12案を固定します。
//
// 引数: なし。返り値: []Policy157。O00は第二巡J02のIDと説明だけを変更します。
func configs157() []Policy157 {
	var base Policy157
	for _, p := range secondConfigs157() {
		if p.ID == "J02" {
			base = p
			break
		}
	}
	values := make([]Policy157, 0, 12)
	for i, id := range []string{"O00", "O01", "O02", "O03", "O04", "O05", "O06", "O07", "O08", "O09", "O10", "O11"} {
		p := base
		p.ID = id
		p.Control = []string{"J02", "O00", "O01", "O02", "O03", "O03", "O03", "O05", "O05", "O05", "O03", "O05"}[i]
		p.Description = []string{
			"第二巡J02同値・最低10micro・旧Source出口",
			"旧元玉出口＋順行40pt追加",
			"O01＋短期支持のカバー/復帰",
			"O02＋逆玉だけ40pt利益開始/40pt追尾/建値床",
			"O03＋逆行20pt後20pt回復・累計25micro",
			"O03＋逆行40pt後20pt回復・累計25micro",
			"O03＋逆行60pt後20pt回復・累計25micro",
			"O05の逆行回復追加上限50micro",
			"O05と同Canonical・両側実保有",
			"O05＋場開始比赤字8～16万円で数量抑制/停止",
			"O03＋長期支持0.1未満/短期反対0.5以上15秒で親返済",
			"O05＋長期支持0.1未満/短期反対0.5以上15秒で親返済",
		}[i]
		if i > 0 {
			p.ManagementEnabled = true
			p.GoodGap = 40
		}
		if i >= 2 {
			p.Cover = true
		}
		if i >= 3 {
			p.CoverTrail = true
		}
		if (i >= 4 && i <= 9) || i == 11 {
			p.AdverseGap = 40
			p.AdverseMax = 25
		}
		if i == 4 {
			p.AdverseGap = 20
		}
		if i == 6 {
			p.AdverseGap = 60
		}
		if i == 7 {
			p.AdverseMax = 50
		}
		p.Hedge = i == 8
		p.SessionSave = i == 9
		p.SeparateCollapse = i >= 10
		values = append(values, p)
	}
	return values
}
