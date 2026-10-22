"""強逆流後に旧準備を破棄する入口を人工の段階履歴で確認する。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time
import numpy as np

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = HERE.parents[2]
sys.path.insert(0,str(TASK))
from check_retest129 import fixture, alter_price, check_night_account
import night_retest129b
import night_retest129c

CHECKS = []


def same(name: str, actual: object, expected: object) -> None:
    """
    機能: 人工期待値と実結果の一致を記録する。
    引数: name(str)、actual/expected(object)は名称と比較値。
    返り値: None。不一致なら停止する。
    """
    np.testing.assert_array_equal(actual,expected,err_msg=name)
    CHECKS.append(name)


def run(args: list, mode: int=1, compiled: bool=False) -> tuple:
    """
    機能: 人工だけを確認6対応核へ渡して独立会計も確認する。
    引数: args(list)、mode(int)、compiled(bool)は人工・再試験・JIT指定。
    返り値: tupleは注文・完結親・時価配列。
    """
    fn = night_retest129c.simulate if compiled else night_retest129c.simulate.py_func
    out = fn(*args,retest_mode=mode)
    check_night_account(tuple(args),out)
    CHECKS.append("人工会計")
    return out


def second_cycle(quantity: int, reflected: bool, confirm: float) -> list:
    """
    機能: 最初の候補を拒否後、次行から別の完全再試験を形成する人工を作る。
    引数: quantity(int)、reflected(bool)、confirm(float)は数量・上下・確認番号。
    返り値: listは十六行の人工入力。第9行判断、第10行約定を期待する。
    """
    a = fixture(quantity,reflected,confirm)
    for k in range(8):
        a[k] = np.concatenate([a[k],np.repeat(a[k][-1:],4,axis=0)])
    a[0] = np.arange(16,dtype=float)*30.
    prices = [101,103,102,101,100.5,101.5,101,103,101,102,102,102,102,102,102,102]
    alter_price(a,[220.-p for p in prices] if reflected else prices)
    a[9] = a[0][-2]
    sign = -1. if reflected else 1.
    a[7][5,5] = -sign
    a[7][5,7] = -sign
    return a


def main() -> None:
    """
    機能: 待機と破棄の差、直後の新準備、候補前維持、未知、上下、旧互換を検査する。
    引数: なし。
    返り値: None。作成者人工証拠を保存し、実市場の核実行は行わない。
    """
    paths = [TASK/"night_retest129b.py",TASK/"night_retest129c.py",Path(__file__)]
    hashes = {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    cases = 0
    for quantity in (5,10):
        for reflected in (False,True):
            sign = -1. if reflected else 1.
            for confirm in (0.,1.,2.,3.,4.,5.):
                for mode in ((0,1) if confirm<4. else (1,)):
                    a = fixture(quantity,reflected,confirm)
                    old = night_retest129b.simulate.py_func(*a,retest_mode=mode)
                    new = run(a,mode)
                    for col in range(3):
                        same(f"旧確認互換_{quantity}_{reflected}_{confirm}_{mode}_{col}",new[col],old[col])
                    cases += 1
            a = fixture(quantity,reflected,6.)
            a[7][5,5] = -sign
            a[7][5,7] = -sign
            waiting = deepcopy(a);waiting[-1][10] = 5.
            same(f"待機は旧段階から再発火_{quantity}_{reflected}",run(waiting)[0][0,:2],[7.,6.])
            same(f"破棄は旧段階を持ち越さない_{quantity}_{reflected}",len(run(a)[0]),0)
            # 新しい工程を全て経れば入る。待機方式は古い戻りを使い先に発火する。
            second = second_cycle(quantity,reflected,6.)
            out = run(second)
            same(f"次行で新準備し全工程後に発火_{quantity}_{reflected}",out[0][0,:2],[10.,9.])
            wait_second = deepcopy(second);wait_second[-1][10] = 5.
            same(f"旧準備待機との時刻差_{quantity}_{reflected}",run(wait_second)[0][0,:2],[8.,7.])
            # 新準備から進行・戻り・再進行のどれを欠いても発火しない。
            for name, row, price in (("進行",7,102.),("戻り",8,102.),("再進行",9,101.)):
                changed = deepcopy(second)
                px = changed[1].copy()
                px[row] = 220.-price if reflected else price
                if name == "再進行":
                    px[row:] = 220.-price if reflected else price
                alter_price(changed,px.tolist())
                same(f"新工程の{name}必須_{quantity}_{reflected}",len(run(changed)[0]),0)
            # 候補になる前、気配不適格、相手中期不足では段階を勝手に破棄しない。
            for name,row in (("進行時",1),("戻り時",3)):
                changed = fixture(quantity,reflected,6.)
                changed[7][row,5] = -sign;changed[7][row,7] = -sign
                same(f"候補前は維持_{name}_{quantity}_{reflected}",run(changed)[0][0,:2],[6.,5.])
            for name in ("気配幅不適格","相手中期不足","自己30不足"):
                changed = deepcopy(a)
                if name == "気配幅不適格":
                    changed[2][5] = changed[1][5]-1.
                    changed[3][5] = changed[1][5]+1.
                elif name == "相手中期不足":
                    changed[6][5,10] = 0.
                else:
                    changed[7][5,4] = 0.
                same(f"不完全候補を破棄しない_{name}_{quantity}_{reflected}",run(changed)[0][0,:2],[7.,6.])
            # ----------------------------------------
            # 強逆流の有限判定、厳密境界、片側だけ反対の扱いは確認5と同じ。
            values = (-1.,-.250001,-.25,-.1,0.,.1,np.nan,np.inf,-np.inf)
            for own in values:
                for peer in values:
                    changed = fixture(quantity,reflected,6.)
                    changed[7][:,5] = sign*own;changed[7][:,7] = sign*peer
                    blocked = np.isfinite(own) and np.isfinite(peer) and own<-.25 and peer<-.25
                    same(f"強逆流真理表_{quantity}_{reflected}_{own}_{peer}",len(run(changed)[0]),0 if blocked else 2)
                    cases += 1
            # 成立済みの予約は、その後の強逆流で消さない。
            pending = fixture(quantity,reflected,6.)
            pending[7][6:,5] = -sign;pending[7][6:,7] = -sign
            same(f"発注済み非取消し_{quantity}_{reflected}",run(pending)[0][0,:2],[6.,5.])
            for col,(actual,expected) in enumerate(zip(run(second,1,True),out)):
                same(f"JIT一致_{quantity}_{reflected}_{col}",actual,expected)
            future = deepcopy(second)
            future[1][11:] += 50.;future[2][11:] += 50.;future[3][11:] += 50.
            future[6][11:,:] = -1.;future[7][11:,:] = np.nan
            poison = run(future)
            same(f"未来毒化曲線接頭_{quantity}_{reflected}",poison[2][:11],out[2][:11])
            same(f"未来毒化注文接頭_{quantity}_{reflected}",poison[0][poison[0][:,0]<11],out[0][out[0][:,0]<11])
    for quantity in (5,10):
        a,b = run(second_cycle(quantity,False,6.)),run(second_cycle(quantity,True,6.))
        same(f"上下の時計数量_{quantity}",a[0][:,[0,1,2,4,6,7]],b[0][:,[0,1,2,4,6,7]])
        same(f"上下の損益費用_{quantity}",a[1][:,6:],b[1][:,6:])
    old,new = ((TASK/name).read_text(encoding="utf8") for name in ("night_retest129b.py","night_retest129c.py"))
    begin = "        if pending and good and i > pending_source:"
    end = "        # ----------------------------------------\n        # 入り直しの条件"
    same("約定と全保有出口が旧と同文",new[new.index(begin):new.index(end)],old[old.index(begin):old.index(end)])
    assert hashes == {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    result = dict(passed=True,cases=cases,checks=CHECKS,source_hashes=hashes,
                  financial_replays=0,original_market_reads=0,API=0)
    target = HERE/f"再試験強逆流破棄の作成者人工_{time.time_ns()}.json"
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps(dict(passed=True,cases=cases,checks=len(CHECKS),path=str(target)),ensure_ascii=False))


if __name__=="__main__":
    main()
