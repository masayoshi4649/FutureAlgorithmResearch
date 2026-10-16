"""親目標・二追尾・親損失・紙上方向撤回を実装未読の純期待へ分けて固定する。"""

import hashlib
import json
import math
from pathlib import Path
from protect_state_reference import Reference, Row


def point(symbol: str, side: int, clock: float, shift: float = 0., balance: float | None = None) -> Row:
    """
    機能: 両側対称の買ask/売bid気配と独立当行票を作る。
    引数: symbol(str)、side(int)、clock/shift(float)、balance(float|None) は人工商品/側/価格移動/票。
    返り値: Row は正常な小人工。未指定票は当該側の強支持。
    """
    base = 4000. if symbol == 'TOPIX' else 65000.; tick = .5 if symbol == 'TOPIX' else 10.
    bid = base + side * shift - (tick if side < 0 else 0.)
    vote = dict(known=True, count=4, balance=side if balance is None else balance)
    return Row(clock, base + side * shift, bid, bid + tick, True, vote, vote)


def filled(symbol: str, side: int, exit_id: str) -> Reference:
    """
    機能: 正常初回FAKを実fillした独立小口座を生成する。
    引数: symbol/exit_id(str)、side(int) は商品/出口/買売側。
    返り値: Reference は紙上親40と実CID0/UID0が別の保有状態。
    """
    r = Reference(symbol, 'BREAK', exit_id); base = 4000. if symbol == 'TOPIX' else 65000.
    virtual = 5 if symbol == 'TOPIX' else 10
    r.step(0, point(symbol, side, 0), [])
    r.step(1, point(symbol, side, 300), [dict(new=True, cid=40, side=side, q=virtual, price=base)])
    r.step(2, point(symbol, side, 301), [])
    assert r.held is not None
    return r


# ----------------------------------------
def main() -> None:
    """
    機能: 12出口対照の親local/N固定・先着返済と方向撤回を純小気配で検査する。
    引数: なし。所有実装をimportせず、price/feeの独立期待だけを作る。
    返り値: None。小証跡を保存し、金融又は実相場での精度と呼ばない。
    """
    here = Path(__file__).resolve().parent; target = here / '親目標二追尾損失と紙上方向撤回の独立純期待.json'
    assert not target.exists(); observations = []
    for symbol in ('TOPIX', 'NK225'):
        for side in (1, -1):
            tick = .5 if symbol == 'TOPIX' else 10.
            for exit_id in ('TARGET', 'TIGHT_TRAIL', 'WIDE_TRAIL'):
                r = filled(symbol, side, exit_id); N = r.held['N']; entry = r.held['price']
                fractions = {'TARGET': .00125, 'TIGHT_TRAIL': .00075, 'WIDE_TRAIL': .00125}
                arm = float(N) * fractions[exit_id]
                needed = arm / (r.cap * r.mult) + tick + 2 * r.charge(r.cap) / (r.cap * r.mult)
                shift = math.ceil(needed / tick) * tick
                r.step(3, point(symbol, side, 302, shift), [])
                assert r.held['N'] == N
                if exit_id == 'TARGET':
                    assert r.queue and r.queue['reason'] == '親目標'
                    r.step(4, point(symbol, side, 303, shift), [])
                    assert not r.held and r.parents[0]['net'] >= arm and r.orders[-1]['source'] == 3
                    observations.append(dict(symbol=symbol, side=side, exit=exit_id, 当時目標予約=True,同row返済無し=True,net=r.parents[0]['net']))
                else:
                    assert r.held['armed'] and r.queue is None
                    peak = r.held['peak']; draw = .00025 if exit_id == 'TIGHT_TRAIL' else .000375
                    retreat = math.ceil(float(N) * draw / (r.cap * r.mult) / tick) * tick
                    r.step(4, point(symbol, side, 303, shift - retreat), [])
                    assert r.queue and r.queue['reason'] == '親追尾' and r.held['N'] == N
                    r.step(5, point(symbol, side, 304, shift - retreat - tick), [])
                    assert not r.held and r.orders[-1]['source'] == 4 and r.parents[0]['net'] < float(peak)
                    observations.append(dict(symbol=symbol, side=side, exit=exit_id, 高水準逐次=True,追尾時次normal返済=True,
                                             peak=float(peak), net=r.parents[0]['net'],救済ピーク混入=False))
            r = filled(symbol, side, 'TARGET'); N = r.held['N']
            loss = -math.ceil(float(N) * .00075 / (r.cap * r.mult) / tick) * tick
            r.step(3, point(symbol, side, 302, loss), [])
            assert r.queue and r.queue['reason'] == '親損失'
            r.step(4, point(symbol, side, 303, loss - tick), [])
            assert not r.held and r.parents[0]['net'] < -float(N) * .00075
            observations.append(dict(symbol=symbol, side=side, 親停止当時予約=True,返済gap超過を保持=True,net=r.parents[0]['net']))
            r = filled(symbol, side, 'TARGET'); N = r.held['N']; virtual = 5 if symbol == 'TOPIX' else 10
            r.step(3, point(symbol, side, 302), [dict(new=False,cid=40,side=-side,q=virtual,price=4000.),
                                                dict(new=True,cid=41,side=-side,q=virtual,price=5000.)])
            assert r.held['N'] == N and r.held['paper'] == 40 and r.held['side'] == side and r.queue
            assert r.paper['cid'] == 41 and r.paper['side'] == -side and not r.pending
            r.step(4, point(symbol, side, 303), [])
            assert not r.held and r.parents[0]['paper'] == 40 and r.orders[-1]['cid'] == 0 and r.orders[-1]['target_uid'] == 0
            observations.append(dict(symbol=symbol,side=side,紙上反方向でも実親NとUID不変=True,旧実残量全退出=True))
            r = filled(symbol, side, 'TARGET'); p = point(symbol, side, 302)
            unknown = dict(known=False,count=0,balance=None)
            r.step(3, Row(p.clock,p.last,p.bid,p.ask,p.normal,unknown,unknown), [])
            assert r.held and not r.queue
            observations.append(dict(symbol=symbol,side=side,票未知だけでは全退出しない=True))
    result = dict(全合格=True,独立人工境界=len(observations),観測=observations,
                  純参照source_SHA256={n:hashlib.sha256((here/n).read_bytes()).hexdigest() for n in
                    ('price_vote_reference.py','protect_state_reference.py','native_guard_reference_check.py')},
                  仕様='親Nは初actualfill、親localは場清算−entry前完結net。極値実現の救済無し。',
                  所有実装未読=True,金融=0,保存packet=0,台帳=0,旧107結果=0,API=0)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('親出口と方向撤回の独立純境界合格 '+str(len(observations))+' SHA '+hashlib.sha256(target.read_bytes()).hexdigest())


if __name__ == '__main__':main()
