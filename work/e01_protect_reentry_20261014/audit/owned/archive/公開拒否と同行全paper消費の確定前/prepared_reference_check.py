"""所有実装未読の純モデルから、現在票・再参加・実玉局所会計の期待を固定する。"""

import copy
import hashlib
import json
import math
from pathlib import Path
import traceback
from price_vote_reference import Point, Geometry, window, peer, supports, spread_admission
from protect_state_reference import Row, Reference

HERE = Path(__file__).resolve().parent
COUNTS = {'票境界': 0, '形状境界': 0, '小口座': 0, '接頭': 0}
EXAMPLES = []


def check(value: bool, category: str, label: str) -> None:
    """
    機能: 仕様から先に作った期待を純モデルへ照合する。
    引数: value(bool)、category/label(str) は成立可否/分類/論点。
    返り値: None。後の実装結果へ期待を書き換えて合格させない。
    """
    assert value, label
    COUNTS[category] += 1
    EXAMPLES.append(label)


def flow(balance: float = 1., count: int = 4, known: bool = True) -> dict:
    """
    機能: 状態機械用の当時既知/未知の人工票を作る。
    引数: balance(float)、count(int)、known(bool) は人工釣合い/票数/資格。
    返り値: dict は機械の当行票。実観測での精度を表す値ではない。
    """
    return dict(known=known, count=count, balance=balance if known else None)


def vote_tests() -> None:
    """
    機能: 同clock自己上限/peer strict過去/期限/cutoffと買売対称を検査する。
    引数: なし。全て小合成Lastだけを用いる。
    返り値: None。物理的な受信順の証明には転用しない。
    """
    points = [Point(0, 100, True, 10), Point(60, 101, True, 11), Point(60, 102, True, 12), Point(60, 90, True, 13)]
    one, two, future = [window(points, i) for i in (1, 2, 3)]
    check(one['count'] == 1 and two['count'] == 2 and two['balance'] == 1 and future['count'] == 3, '票境界', '自己同clockは当該原行だけ、未来同clockを含めない')
    modified = copy.deepcopy(points); modified[3] = Point(60, 200, True, 13)
    check(window(modified, 2) == two, '票境界', '自己未来suffix値を変えても過去票不変')
    no_base = [Point(1, 100, True, 10), Point(60, 101, True, 11)]
    check(not window(no_base, 1)['known'], '票境界', 'cutoff以前基準無しは未知')
    baseline = [Point(0, 99, True, 1), Point(10, 100, True, 2), Point(60, 101, True, 3), Point(70, 102, True, 4)]
    exact = window(baseline, 3)
    check(exact['reference_row'] == 1 and exact['count'] == 2 and exact['balance'] == 1, '票境界', '<=cutoff最後基準、更新は>cutoff')
    equal = [Point(0, 100, True, 1), Point(60, 100, True, 2), Point(60, 101, True, 3), Point(60, 100, True, 4)]
    value = window(equal, 3)
    check(value['count'] == 2 and value['balance'] == 0, '票境界', 'equalは零票、二方向非零票でbalance0')
    strict = [Point(-60, 99, True, 1), Point(-30, 100, True, 2), Point(0, 101, True, 3), Point(60, 200, True, 4)]
    at = peer(strict, 60)
    check(at['known'] and at['end_row'] == 2 and at['age'] == 60 and at['count'] == 2, '票境界', 'peer同clock除外/age60は含む/peer自身終点窓')
    check(not peer(strict[:3], math.nextafter(60., math.inf))['known'], '票境界', 'peer age60超は未知')
    check(not peer([Point(60, 100, True, 1)], 60)['known'], '票境界', 'peer strict過去終点無しは未知')
    for side in (1, -1):
        mirrored = [Point(p.clock, 300 - p.last if side < 0 else p.last, p.normal, p.raw_seq) for p in points]
        v = window(mirrored, 2)
        check(supports(v, v, side, .75), '票境界', '正常Last票の買売対称' + str(side))
        for count in (0, 1, 2, 4):
            for strength in (.249999, .25, .749999, .75, 1.):
                a = flow(side * strength, count)
                check(supports(a, a, side) == (count >= 2 and strength >= .25), '票境界', '二票/入口.25境界' + str((side, count, strength)))
                check(supports(a, a, side, .75) == (count >= 2 and strength >= .75), '票境界', '二票/許容.75境界' + str((side, count, strength)))
        check(not supports(flow(side), flow(side, known=False), side), '票境界', '片方未知は自己成功へ補完しない' + str(side))
    check(spread_admission(4000.5, 4000, 4000.5, 10, 1000, 836), '票境界', '公開通常spreadは半損失枠内')
    check(not spread_admission(4004, 4000, 4004, 10, 1000, 836), '票境界', '公開拡幅は初期費用で拒否')


def geometry_tests() -> None:
    """
    機能: 固定paper Pの押し/回復/突破と強さ変更だけの再anchor禁止を検査する。
    引数: なし。P4000で正確な1pt/.5pt境界を使う。
    返り値: None。将来の実利幅や極値を利用しない。
    """
    for side in (1, -1):
        price = lambda shift: 4000 + side * shift
        g = Geometry(side, 4000, 0, price(0))
        check(not g.observe(0, price(2), True, 'BREAK', True)['entry'], '形状境界', 'anchor同row再参加無し' + str(side))
        check(not g.observe(1, price(.5), True, 'BREAK', True)['entry'], '形状境界', '突破未満' + str(side))
        check(g.observe(2, price(1), True, 'BREAK', True)['entry'], '形状境界', '突破ちょうど.00025P' + str(side))
        g = Geometry(side, 4000, 0, price(0)); g.observe(1, price(2), True, 'PULL', False)
        check(not g.observe(2, price(1.5), True, 'PULL', False)['entry'], '形状境界', '押し未満' + str(side))
        check(not g.observe(3, price(1), True, 'PULL', False)['entry'], '形状境界', '押しちょうど.00025Pだけで入らない' + str(side))
        check(not g.observe(4, price(1.25), True, 'PULL', False)['entry'], '形状境界', '回復未満' + str(side))
        check(g.observe(5, price(1.5), True, 'PULL', False)['entry'], '形状境界', 'troughから.000125P回復' + str(side))
        g = Geometry(side, 4000, 0, price(0)); result = g.observe(1, price(1), True, 'ADAPTIVE', True)
        check(result['branch'] == 'BREAK' and result['entry'] and g.anchor == price(0), '形状境界', 'ADAPTIVE強支持は現在BREAK/anchor不変' + str(side))
        result = g.observe(2, price(1), True, 'ADAPTIVE', False)
        check(result['branch'] == 'PULL' and not result['entry'] and g.anchor == price(0), '形状境界', '強さ切替だけではshape/anchorを作らない' + str(side))
        g = Geometry(side, 4000, 0, math.nan)
        check(not g.observe(1, price(2), True, 'BREAK', True)['entry'] and g.anchor == price(2), '形状境界', '未知anchor次正常で初期化/同行参加無し' + str(side))
        check(not g.observe(2, price(20), False, 'BREAK', True)['entry'] and g.anchor == price(2), '形状境界', '非正常Lastで極値を進めない' + str(side))


def state_tests() -> None:
    """
    機能: 実装を見ずに紙上一回・再参加・UID・scene/親尺度・料金と接頭を検査する。
    引数: なし。全て人工票/気配だけの小経路。
    返り値: None。純期待を保存し新金融の効能とは呼ばない。
    """
    for symbol in ('TOPIX', 'NK225'):
        base = 4000. if symbol == 'TOPIX' else 65000.; tick = .5 if symbol == 'TOPIX' else 10.
        for side in (1, -1):
            for mode in ('ORIGIN', 'PULL', 'BREAK', 'ADAPTIVE'):
                for exit_id in ('TARGET', 'TIGHT_TRAIL', 'WIDE_TRAIL'):
                    r = Reference(symbol, mode, exit_id)
                    def point(clock: float, shift: float, own: dict | None = None, other: dict | None = None, normal: bool = True, quiet: bool = False) -> Row:
                        """
                        機能: 反射対称の人工気配と当時票を作る。
                        引数: clock/shift(float)、own/other(dict|None)、normal/quiet(bool) は人工時刻/移動/資格。
                        返り値: Row は新規買ask/売bidが対称な観測。
                        """
                        bid = base + side * shift - (tick if side < 0 else 0.)
                        return Row(clock, base + side * shift, bid, bid + tick, normal,
                                   own if own is not None else flow(side), other if other is not None else flow(side), quiet)
                    feed = dict(cid=40, side=side, price=base, q=5 if symbol == 'TOPIX' else 10, new=True)
                    r.step(0, point(0, 0), [])
                    r.step(1, point(300, 0), [feed]); check(r.pending is not None, '小口座', '紙上origin初回審査' + str((symbol, side, mode, exit_id)))
                    r.step(2, point(301, 0), [])
                    check(r.held is not None and r.held['cid'] == 0 and r.held['uid'] == 0 and r.held['paper'] == 40,
                          '小口座', '初fill実CID/UID/paperを分離' + str((symbol, side, mode, exit_id)))
                    frozen_N = r.held['N']; q = r.cap
                    r.step(3, point(302, 0), [dict(cid=40, side=-side, price=base, q=2, new=False)])
                    check(r.held['q'] == q and r.held['N'] == frozen_N and r.queue is None, '小口座', 'paper部分EXITはnative実量/Nを縮めない' + str((symbol, side, mode, exit_id)))
                    r.step(4, point(303, 0, other=flow(-side)), [])
                    check(r.queue is None, '小口座', '片市場反対だけで両反対全退出へしない' + str((symbol, side, mode, exit_id)))
                    r.step(5, point(304, 0, own=flow(-side), other=flow(-side)), [])
                    check(r.queue is not None and r.queue['reason'] == '両市場反対', '小口座', '両反対は時間固定待機なしで返済予約' + str((symbol, side, mode, exit_id)))
                    r.step(6, point(305, 0), [])
                    check(r.held is None and len(r.parents) == 1 and r.paper is not None and r.paper['remaining'] > 0,
                          '小口座', '実完結は紙上未完結でも一親' + str((symbol, side, mode, exit_id)))
                    check(r.orders[-1]['uid'] == -1 and r.orders[-1]['target_uid'] == 0 and r.orders[-1]['source'] == 5,
                          '小口座', '実UID残返済/判断後次正常' + str((symbol, side, mode, exit_id)))
                    check(math.isclose(r.parents[0]['net'], -q * tick * r.mult - 2 * r.charge(q)), '小口座', '全親料込み損失と初期spread' + str((symbol, side, mode, exit_id)))
                    # 返済anchor以後に新geometryが成立し、現在両市場支持が戻るまで再審査しない。
                    shift = math.ceil(base * .00025 / tick) * tick
                    r.step(7, point(306, shift), [])
                    if mode == 'ORIGIN':
                        check(r.pending is None, '小口座', 'ORIGIN後復活なし' + str((symbol, side, exit_id)))
                    elif mode in ('BREAK', 'ADAPTIVE'):
                        check(r.pending is not None and r.pending['cid'] == 1 and r.pending['paper'] == 40,
                              '小口座', '同paperで次実CIDの新shape参加' + str((symbol, side, mode, exit_id)))
                        r.step(8, point(307, shift), [])
                        check(r.held['cid'] == 1 and r.held['uid'] == 1 and float(r.held['base']) == r.parents[0]['net'],
                              '小口座', '前親netを第二親局所目標へ混ぜない' + str((symbol, side, mode, exit_id)))
                    else:
                        r.step(8, point(307, 0), []); r.step(9, point(308, math.ceil(base * .000125 / tick) * tick), [])
                        check(r.pending is not None and r.pending['cid'] == 1, '小口座', 'PULLは押し回復で同paper新CID' + str((symbol, side, exit_id)))
                    COUNTS['小口座'] += 1
        # 未約定失効は費用ゼロで受理CIDを消費し、後quoteで元注文を復活させない。
        r = Reference(symbol, 'BREAK', 'TARGET')
        p = lambda clock, shift=0., normal=True, quiet=False: Row(clock, base + shift, base + shift, base + shift + tick, normal, flow(), flow(), quiet)
        r.step(0, p(0), []); r.step(1, p(300), [dict(cid=0, side=1, price=base, q=5, new=True)])
        r.step(2, p(301, 3 * tick), [])
        check(r.held is None and r.pending is None and r.uid == 0 and r.cid == 1 and r.paid == 0, '小口座', '一回FAK不利で失効/CID欠番/UID料なし' + symbol)
        r.step(3, p(302, 0), [])
        check(r.held is None and not r.orders, '小口座', '後quote有利でも旧FAK復活無し' + symbol)
        # 非正常紙上部分退出の取消はanchor未知を経由し、次正常初期化行で再参加しない。
        r = Reference(symbol, 'BREAK', 'TARGET'); r.step(0, p(0), []); r.step(1, p(300), [dict(cid=0, side=1, price=base, q=5, new=True)])
        r.step(2, p(301, 0, normal=False), [dict(cid=0, side=-1, price=base, q=1, new=False)])
        check(r.pending is None and math.isnan(r.geometry.anchor), '小口座', 'paper部分cancel消費/非normal anchor未知' + symbol)
        r.step(3, p(302, 20 * tick), [])
        check(r.pending is None and r.geometry.anchor == base + 20 * tick, '小口座', 'cancel後次正常初期化/同row参加無し' + symbol)
        # 高い清算でscene利益に当たれば、親target後の同paper再参加を恒久停止する。
        r = Reference(symbol, 'BREAK', 'TARGET'); r.step(0, p(0), []); r.step(1, p(300), [dict(cid=0, side=1, price=base, q=5, new=True)]); r.step(2, p(301), [])
        move = math.ceil(base * .005 / tick) * tick
        r.step(3, p(302, move), []); check(r.scene_block, '小口座', '場純利益停止を親利益再参加より優先' + symbol)
        r.step(4, p(303, move), []); r.step(5, p(304, move + 10 * tick), [])
        check(r.held is None and r.pending is None and len(r.orders) == 2, '小口座', 'scene利益後は残UID返済/新規永久停止' + symbol)
        # 将来suffixだけを変えても当時接頭の予約・実玉・費用は不変。
        for cut in (1, 2, 3, 4, 5):
            a, b = Reference(symbol, 'BREAK', 'TARGET'), Reference(symbol, 'BREAK', 'TARGET')
            points = [p(0), p(300), p(301), p(302, tick), p(303, 2 * tick), p(304, 3 * tick)]
            altered = points[:cut] + [p(9999, 100000 * tick, normal=False, quiet=True)] * (len(points) - cut)
            for index, (ra, rb) in enumerate(zip(points, altered)):
                event = [dict(cid=0, side=1, price=base, q=5, new=True)] if index == 1 else []
                a.step(index, ra, event); b.step(index, rb, event)
            check([o for o in a.orders if o['row'] < cut] == [o for o in b.orders if o['row'] < cut] and
                  a.curve[:cut] == b.curve[:cut] and [o for o in a.publications if o['row'] < cut] == [o for o in b.publications if o['row'] < cut],
                  '接頭', '純状態future suffix不変' + str((symbol, cut)))


def ordering_and_capacity() -> None:
    """
    機能: quiet/期限/paper取消の先後と同paper八十実親の動的容量期待を検査する。
    引数: なし。当時票配列は人工として別に与え、実相場の票とは呼ばない。
    返り値: None。所有buffer実装の検査は完成sourceへ別に接続する。
    """
    for symbol in ('TOPIX', 'NK225'):
        base = 4000. if symbol == 'TOPIX' else 65000.; tick = .5 if symbol == 'TOPIX' else 10.
        def p(clock: float, shift: float = 0., normal: bool = True, quiet: bool = False, opposite: bool = False) -> Row:
            """
            機能: 同列先後の状態試験用に正常気配と人工票を組み立てる。
            引数: clock/shift(float)、normal/quiet/opposite(bool) は時計/価格移動/状態。
            返り値: Row は人工観測。値動きからの票計算試験とは別範囲。
            """
            v = flow(-1 if opposite else 1)
            return Row(clock, base + shift, base + shift, base + shift + tick, normal, v, v, quiet)
        new = dict(cid=0, side=1, price=base, q=5, new=True)
        part = dict(cid=0, side=-1, price=base, q=1, new=False)
        # 同行最初normalでは実fill先で、paper部分退出が実量を減らさない。
        a = Reference(symbol, 'BREAK', 'TARGET'); a.step(0, p(0), []); a.step(1, p(300), [new]); a.step(2, p(301), [part])
        check(a.held is not None and a.held['q'] == a.cap and not a.events, '小口座', '同行firstnormal fill先/partial無縮小' + symbol)
        # 以前の別row paper退出なら取消先で、次normalは旧FAKを実行しない。
        a = Reference(symbol, 'BREAK', 'TARGET'); a.step(0, p(0), []); a.step(1, p(300), [new]); a.step(2, p(301, normal=False), [part]); a.step(3, p(302), [])
        check(not a.held and not a.orders and a.cid == 1 and a.uid == 0, '小口座', '過去paper部分cancel先/失効旧注文復活無し' + symbol)
        # quietは最初正常FAKより先に拒否/取消し、実保有にはtimerを優先する。
        a = Reference(symbol, 'ORIGIN', 'TARGET'); a.step(0, p(0), []); a.step(1, p(300), [new]); a.step(2, p(301, quiet=True), [])
        check(not a.held and not a.orders, '小口座', 'quiet同行pending取消がFAKに先行' + symbol)
        a = Reference(symbol, 'BREAK', 'TARGET'); a.step(0, p(0), []); a.step(1, p(300), [new]); a.step(2, p(301), []); a.step(3, p(302, quiet=True), [])
        check(len(a.parents) == 1 and a.orders[-1]['reason'] == '静観/期限' and a.orders[-1]['source'] == 2,
              '小口座', '保有quietは前行timer源で当初正常清算' + symbol)
        a = Reference(symbol, 'ORIGIN', 'TARGET'); a.step(0, p(0), []); a.step(1, p(300), [new]); a.step(2, p(301), [])
        a.step(3, p(302, normal=False, quiet=True), [])
        a.step(4, p(303), [dict(cid=0, side=-1, price=base, q=5, new=False),
                           dict(cid=1, side=1, price=base, q=5, new=True)])
        check(not a.held and not a.pending and len(a.parents) == 1, '小口座', 'quiet予約清算初normalは新paperORIGIN受理禁止' + symbol)
        a.step(5, p(304, 100 * tick), [])
        check(not a.pending and len(a.publications) == 1, '小口座', 'quiet初normalで消費したORIGINを後復活しない' + symbol)
        a = Reference(symbol, 'ORIGIN', 'TARGET'); a.step(0, p(0), []); a.step(1, p(299), [new]); a.step(2, p(300), [])
        check(not a.pending and not a.held, '小口座', 'ORIGIN開始五分前の拒否を後復活させない' + symbol)
        a = Reference(symbol, 'ORIGIN', 'TARGET'); a.step(0, p(0), []); a.step(1, p(700), [new])
        check(not a.pending and not a.orders, '小口座', 'limit五分前ちょうどは新規対象外' + symbol)
        # 返済gapで停止線超過を許容する一方、跨場の永久保有は許さない。
        a = Reference(symbol, 'BREAK', 'TARGET'); a.step(0, p(0), []); a.step(1, p(300), [new]); a.step(2, p(301), [])
        loss = -math.ceil(base * .004 / tick) * tick
        a.step(3, p(302, loss), []); check(a.scene_block and a.queue, '小口座', '場net損失firstcrossラッチ' + symbol)
        a.step(4, p(303, loss, normal=False), []); check(a.held is not None, '小口座', '非normalでは未来清算を補完しない' + symbol)
        a.step(5, p(304, 2 * loss), []); check(not a.held and a.parents[0]['net'] < -base * a.cap * a.mult * .0025,
              '小口座', '次正常gapで停止線超過/現実損失を隠さない' + symbol)
        a.step(6, p(305, 0), []); check(not a.pending, '小口座', '損失ラッチ後geometry回復でも新規無し' + symbol)
        # 八十実親・一紙上親。小勝負交互で場線内に保ち、buffer32を超える期待を先に作る。
        a = Reference(symbol, 'BREAK', 'TARGET'); a.step(0, p(0), []); a.step(1, p(300), [new])
        index, clock, shift = 2, 301., 0.
        for cycle in range(80):
            a.step(index, p(clock, shift), []); index += 1; clock += 1
            check(a.held is not None, '小口座', '多数再参加fill' + str((symbol, cycle)))
            shift += 3 * tick if cycle % 2 == 0 else 0.
            a.step(index, p(clock, shift, opposite=True), []); index += 1; clock += 1
            a.step(index, p(clock, shift), []); index += 1; clock += 1
            check(not a.held and not a.scene_block, '小口座', '多数再参加親完結/場線未達' + str((symbol, cycle)))
            if cycle < 79:
                shift += math.ceil(base * .00025 / tick) * tick
                a.step(index, p(clock, shift), []); index += 1; clock += 1
                check(a.pending is not None, '小口座', '多数再参加新shape/実CID予約' + str((symbol, cycle)))
        check(len(a.parents) == 80 and len(a.orders) == 160 and len({v['uid'] for v in a.parents}) == 80 and
              len({v['cid'] for v in a.parents}) == 80 and {v['paper'] for v in a.parents} == {0},
              '小口座', '動的buffer期待:同paper80実親/160注文/UIDCID独立' + symbol)
        check(sum(v['net'] for v in a.parents) == float(a.realized) and a.paid == 160 * a.charge(a.cap),
              '小口座', '80親全量capと全注文料/累積net恒等' + symbol)


def main() -> None:
    """
    機能: 所有source完成前に独立純期待の境界と指紋を保存する。
    引数: なし。指定3純sourceと固定人工だけで検査する。
    返り値: None。金融/packet/板/台帳/旧107結果を読み出さない。
    """
    target = HERE / '所有実装未読の現在票と再参加及び実親分離の純期待_v4.json'
    assert not target.exists()
    source = {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest() for name in
              ('price_vote_reference.py', 'protect_state_reference.py', 'prepared_reference_check.py')}
    try:
        vote_tests(); geometry_tests(); state_tests(); ordering_and_capacity()
        value = dict(全合格=True,純参照source_SHA256=source,検査=COUNTS,確認観点=EXAMPLES,
                     状態='owner source未読/未importの純参照。完成source/実装結合は別検査。',
                     初版False='peer終点0のageを調べる人工に、新自己時計ならstrict過去になるpeer60点も置いていた。新終点の採用は正しいため、stale境界人工だけ末尾点を除外。純モデルsourceは不変更。',
                     v4理由='rootがquiet既予約を清算する初normal行の新規禁止を確定したため、その行全体のblockedを独立状態へ追加した。v3/source3をarchiveへ保全。所有実装のimport無し。',
                     確定境界=['cutoff基準<=、票対象>cutoff。自己同clockは当該rawrowまで。',
                               'peer strict過去/age60以内を自身end窓へ。価格代理モデルで実受信順証明は無し。',
                               '紙上部分cancelでもgeometry消費。非normalなら次正常anchor初期化、同行参加無し。',
                               '受理毎実CID消費、fill毎UID、失効に費用無し。ORIGIN初回一回のみ。'],
                     未結合=['所有動的bufferのサイズ/配列最大値', 'timerと親/場triggerの同row優先詳細',
                             '完成sourceの正常資格配列との接続', '実際の注文到着/部分FAK/板厚'],
                     新金融=0,保存packet=0,原板=0,台帳本文=0,旧107結果=0,API=0)
    except BaseException:
        value = dict(全合格=False,純参照source_SHA256=source,検査=COUNTS,原因=traceback.format_exc(),
                     新金融=0,保存packet=0,原板=0,台帳本文=0,旧107結果=0,API=0)
        target.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        raise
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('独立純期待合格 ' + str(COUNTS) + ' SHA ' + hashlib.sha256(target.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
