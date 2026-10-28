package main

// reentryRequired は第二巡で冷却後の再参加を必須とする条件を識別します。
//
// 引数: id(string)は固定候補ID。返り値: bool。人工の旧対照IDでは無効です。
func reentryRequired(id string) bool {
	switch id {
	case "R01", "R02", "R03", "R04", "R05", "R06", "R07", "R08":
		return true
	}
	return false
}

// alignmentRequired は中値と短期傾きの方向一致を新規に要求します。
//
// 引数: id(string)。返り値: bool。保有後の防御や追加にはこの入口条件を転用しません。
func alignmentRequired(id string) bool {
	switch id {
	case "R02", "R03", "R04", "R06", "R07", "R08":
		return true
	}
	return false
}

// guardedAllocation は追加の価格品質と2枚以上の増減幅を要求します。
//
// 引数: id(string)。返り値: bool。
func guardedAllocation(id string) bool {
	return id == "R04" || id == "R08"
}

// refreshArms は現在までに観測した方向別の冷却だけを記録します。
//
// 引数: c(*Result)、q(Quote)、f(Feature)。返り値: なし。
// 全返済の約定行では同方向を再準備せず、次の原行以降だけを許します。
func refreshArms(c *Result, q Quote, f Feature) {
	if !reentryRequired(c.Config.ID) || !f.Known || !quoteOK(q) {
		return
	}
	for _, side := range []int{-1, 1} {
		if q.Index > c.ArmResetIndex[side] && float64(side)*f.Slope <= .125 {
			c.Armed[side] = true
		}
	}
}

// entryAligned は新規方向で中値が基準平均より先にあり、短期傾きも同符号かを調べます。
//
// 引数: c(*Result)、q(Quote)、f(Feature)、side(int)。返り値: bool。
// 拒否の計数は原行数であり、独立した売買機会数ではありません。
func entryAligned(c *Result, q Quote, f Feature, side int) bool {
	if !c.ShortCurrent.Known {
		c.Rejections["短期傾き未知"]++
		return false
	}
	if float64(side)*((q.Bid+q.Ask)/2-f.MA) <= 0 {
		c.Rejections["現在中値と平均の不一致"]++
		return false
	}
	if float64(side)*c.ShortCurrent.Slope <= 0 {
		c.Rejections["短期傾きの不一致"]++
		return false
	}
	return true
}

// allocationAllowed は2枚以上の調整幅と追加時だけの順行条件を判定します。
//
// 引数: c(*Result)、q(Quote)、target(int)。返り値: bool。
// 買いはBid、売りはAskを返済可能価格とし、減量に含み益条件を課しません。
func allocationAllowed(c *Result, q Quote, target int) bool {
	difference := target - c.Quantity
	if difference > -2 && difference < 2 {
		if difference != 0 {
			c.Rejections["調整差1枚"]++
		}
		return false
	}
	if difference < 0 {
		return true
	}
	price := q.Bid
	if c.Side < 0 {
		price = q.Ask
	}
	if float64(c.Side)*(price-c.Current.Anchor) <= 0 {
		c.Rejections["初回建値からの含み益なし"]++
		return false
	}
	if float64(c.Side)*(price-c.LastNewPrice) < q.Ask-q.Bid {
		c.Rejections["直前追加から気配差以上の順行なし"]++
		return false
	}
	return true
}
