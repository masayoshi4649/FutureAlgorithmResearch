package strategy

// IndependentSeed163 は隔離人工環境だけで通常の新規予約を一つ作ります。
//
// 引数: p(*Portfolio)、o(Observation)、owner(string)、side/quantity(int)。
// 返り値: []Signal。入口精度の検査ではなく、約定から元返済への接続を検査します。
func IndependentSeed163(p *Portfolio, o Observation, owner string, side, quantity int) []Signal {
	if p.P05 != nil {
		s := p.emitP05(o, Signal{ID: "人工の影通知", Owner: owner, Campaign: 1, Action: "new", Side: side, Quantity: quantity}, nil)
		if s != nil {
			return []Signal{*s}
		}
		return nil
	}
	return p.nativeResearch(p.sleeve(owner), o, []ResearchEvent{{Action: "new", Side: side, Quantity: quantity, Campaign: 1, Ticket: 0, Risk: 80}}, true, true)
}
