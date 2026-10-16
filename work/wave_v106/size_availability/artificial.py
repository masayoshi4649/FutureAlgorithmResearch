"""予定リスクの単一式を実相場なしの境界で確認する。"""

import math

import common
import risk


def run() -> None:
    """
    機能: 注文料・整数量・境界・単調性・未知と元門の純人工を検査する。
    引数: なし。
    返り値: None。所有域へ小証跡を保存するだけで大型入力は読まない。
    """
    checks = []
    assert risk.fee(1, 'TOPIX') == 41 and 2*risk.fee(1, 'TOPIX') == 82
    assert risk.fee(5, 'TOPIX') == 209
    assert risk.fee(2, 'TOPIX')+risk.fee(3, 'TOPIX') == 208
    assert risk.fee(10, 'NK225') == 110
    checks.append('一枚TOP82円・新規209円・分割返済83円125円を合算丸めしない')
    for symbol in ('TOPIX', 'NK225'):
        bid, ask = (100., 100.5) if symbol == 'TOPIX' else (10000., 10010.)
        spread = ask-bid
        one_boundary = (risk.BUDGET[symbol]-2*risk.fee(1, symbol))/risk.VALUE[symbol]-spread
        assert one_boundary > 0
        equal = risk.measure(one_boundary, bid, ask, symbol)
        assert equal['known'] and equal['proposed_quantity'] == 1
        below = risk.measure(math.nextafter(one_boundary, -math.inf), bid, ask, symbol)
        above = risk.measure(one_boundary+1e-7, bid, ask, symbol)
        assert below['known'] and below['proposed_quantity'] >= 1
        assert above['known'] and above['proposed_quantity'] == 0
        checks.append(symbol+':最小一枚の予算境界を含み、超過はq0')
        lots = [risk.measure(a, bid, ask, symbol)['proposed_quantity'] for a in (.1, 1., 5., 10., 100.)]
        assert lots == sorted(lots, reverse=True)
        old = risk.measure(1., bid, ask, symbol)
        wider = risk.measure(1., bid, ask+spread, symbol)
        assert wider['proposed_quantity'] <= old['proposed_quantity']
        amounts = [v['planned_risk_yen'] for v in old['risk_by_quantity']]
        assert amounts == sorted(amounts)
        assert old['proposed_quantity'] <= risk.CAP[symbol]
        checks.append(symbol+':ATR/気配差/枚数の単調性と元初回上限')
        for a, b, c in ((math.nan, bid, ask), (0., bid, ask), (-1., bid, ask),
                        (1., math.nan, ask), (1., bid, bid), (1., ask, bid),
                        (1e308, bid, ask)):
            value = risk.measure(a, b, c, symbol)
            assert not value['known'] and value['proposed_quantity'] is None
        checks.append(symbol+':不明/ゼロ/不正/overflowをq0へ補完しない')
    # ----------------------------------------
    # 元公開の情報不足と反対票は数量診断と独立に保持する。
    for mode in ('VETO', 'CONFIRM', 'KNOWN_VETO'):
        unknown = dict(known=False, reason=16, direction_votes=None, balance=None)
        low = dict(known=True, reason=0, direction_votes=1, balance=1.)
        opposed = dict(known=True, reason=0, direction_votes=2, balance=-.25)
        neutral = dict(known=True, reason=0, direction_votes=2, balance=0.)
        aligned = dict(known=True, reason=0, direction_votes=2, balance=.25)
        assert risk.gate(unknown, mode)[0] == (mode == 'VETO')
        assert risk.gate(low, mode)[0] == (mode == 'VETO')
        assert not risk.gate(opposed, mode)[0]
        assert risk.gate(neutral, mode)[0] == (mode != 'CONFIRM')
        assert risk.gate(aligned, mode)[0]
        checks.append(mode+':情報不足/二票/方向釣合いの元真偽を維持')
    common.write(common.HERE/'公開予定リスクの純算術人工.json', dict(
        全合格=True, 確認項目=checks, source_SHA256=common.sources(),
        計算='q*(公開ATR+公開spread)*商品倍率+2floor(q*片道料)',
        予算=risk.BUDGET, 元上限=risk.CAP, 紙上停止係数=risk.PAPER_STOP_ATR,
        大型入力=0, 原板=0, NPZ=0, 新金融=0, API=0))
    print('公開予定リスクの純算術人工合格、金融0、大型入力0', flush=True)


if __name__ == '__main__':
    run()
