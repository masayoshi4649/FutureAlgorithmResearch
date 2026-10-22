"""再試験入口の強逆流拒否を、境界・未知・上下・旧互換の人工で検査する。"""

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
sys.path.insert(0, str(TASK))
from check_retest129 import fixture, alter_price, check_night_account
import night_retest129
import night_retest129b

CHECKS = []


def same(name: str, actual: object, expected: object) -> None:
    """
    機能: 独立した人工期待値との一致を記録する。
    引数: name(str)、actual/expected(object)は名称と比較対象。
    返り値: None。不一致なら停止する。
    """
    np.testing.assert_array_equal(actual, expected, err_msg=name)
    CHECKS.append(name)


def run(args: list, mode: int = 1, compiled: bool = False) -> tuple:
    """
    機能: 人工資料だけを新核へ渡し、全行会計を別計算で確認する。
    引数: args(list)、mode(int)、compiled(bool)は人工引数・再試験指定・JIT指定。
    返り値: tupleは注文・取引・時価。実市場資料は読まない。
    """
    fn = night_retest129b.simulate if compiled else night_retest129b.simulate.py_func
    result = fn(*args, retest_mode=mode)
    check_night_account(tuple(args), result)
    CHECKS.append("人工の独立会計")
    return result


def main() -> None:
    """
    機能: 旧確認0〜4互換、強逆流の厳密境界、未知と予約確定を確認する。
    引数: なし。
    返り値: None。作成者証拠を保存し、金融再生は行わない。
    """
    paths = [TASK/"night_retest129.py", TASK/"night_retest129b.py", Path(__file__),
             HERE/"check_retest129.py", TASK/"run_retest129b.py"]
    hashes = {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    cases = 0
    for quantity in (5,10):
        for reflected in (False,True):
            sign = -1. if reflected else 1.
            for confirm in (0.,1.,2.,3.,4.):
                for mode in ((0,1) if confirm < 4. else (1,)):
                    a = fixture(quantity,reflected,confirm)
                    old = night_retest129.simulate.py_func(*a,retest_mode=mode)
                    new = run(a,mode)
                    for col in range(3):
                        same(f"旧確認全配列_{quantity}_{reflected}_{confirm}_{mode}_{col}",new[col],old[col])
                    cases += 1
            # ----------------------------------------
            # 閾値ちょうどは拒否しない。片側だけの反対、未知・無限は補完しない。
            values = (-1., -.250001, -.25, -.1, 0., .1, np.nan, np.inf, -np.inf)
            for own in values:
                for peer in values:
                    a = fixture(quantity,reflected,5.)
                    a[7][:,5] = sign*own
                    a[7][:,7] = sign*peer
                    blocked = np.isfinite(own) and np.isfinite(peer) and own < -.25 and peer < -.25
                    out = run(a)
                    same(f"強逆流の真理表_{quantity}_{reflected}_{own}_{peer}",len(out[0]),0 if blocked else 2)
                    if not blocked:
                        same(f"入口時刻不変_{quantity}_{reflected}_{own}_{peer}",out[0][0,:2],[6.,5.])
                    cases += 1
            a = fixture(quantity,reflected,5.)
            base = run(a)
            for col,(actual,expected) in enumerate(zip(run(a,1,True),base)):
                same(f"JIT全列_{quantity}_{reflected}_{col}",actual,expected)
            # 判断後の両逆流で、成立済みの新規予約を消さない。
            changed = deepcopy(a)
            changed[7][6:,5] = -sign
            changed[7][6:,7] = -sign
            same(f"発注後不利を取消さない_{quantity}_{reflected}",run(changed)[0][0,:2],[6.,5.])
            # 判断時だけ強逆流、次の原行で片側中立なら準備を保って判断できる。
            changed = deepcopy(a)
            changed[7][5,5] = -sign
            changed[7][5,7] = -sign
            changed[7][6,5] = 0.
            same(f"強逆流解除後に判断_{quantity}_{reflected}",run(changed)[0][0,:2],[7.,6.])
            # 120秒を使わない時も、現在資料・30秒・相手中期の資格は維持。
            for array,col,value in ((7,11,0.),(7,4,np.nan),(7,6,np.nan),
                                    (6,10,np.nan),(6,11,np.nan),(6,10,0.),(6,11,0.)):
                changed = deepcopy(a)
                changed[array][:,col] = value
                same(f"必要情報維持_{quantity}_{reflected}_{array}_{col}_{value}",len(run(changed)[0]),0)
            changed = deepcopy(a)
            changed[1][7:] += 50.
            changed[2][7:] += 50.
            changed[3][7:] += 50.
            changed[6][7:,:] = -1.
            changed[7][7:,:] = np.nan
            poisoned = run(changed)
            same(f"未来毒化の曲線接頭_{quantity}_{reflected}",poisoned[2][:7],base[2][:7])
            same(f"未来毒化の注文接頭_{quantity}_{reflected}",
                 poisoned[0][poisoned[0][:,0]<7],base[0][base[0][:,0]<7])
            # 未知中に固定境界を破れば、従来の取消しをそのまま維持。
            changed = deepcopy(a)
            ps = [101,103,102,101,99,101.5,102,102.5,102,102,102,102]
            alter_price(changed,[220.-p for p in ps] if reflected else ps)
            changed[7][4,11] = 0.
            same(f"未知中の境界破綻_{quantity}_{reflected}",len(run(changed)[0]),0)
    # ----------------------------------------
    # 上下に鏡映した同じ機構と、保有後の元源に変更がないことを確認する。
    for quantity in (5,10):
        a = run(fixture(quantity,False,5.))
        b = run(fixture(quantity,True,5.))
        same(f"上下の時計枚数_{quantity}",a[0][:,[0,1,2,4,6,7]],b[0][:,[0,1,2,4,6,7]])
        same(f"上下の注文方向_{quantity}",a[0][:,3],-b[0][:,3])
        same(f"上下の損益料金_{quantity}",a[1][:,6:],b[1][:,6:])
    old = (TASK/"night_retest129.py").read_text(encoding="utf8")
    new = (TASK/"night_retest129b.py").read_text(encoding="utf8")
    begin = "        if pending and good and i > pending_source:"
    end = "        # ----------------------------------------\n        # 入り直しの条件"
    same("新規約定・全保有出口は同文",new[new.index(begin):new.index(end)],old[old.index(begin):old.index(end)])
    assert hashes == {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    result = dict(passed=True,cases=cases,checks=CHECKS,source_hashes=hashes,
                  financial_replays=0,original_market_reads=0,API=0,
                  note="確認5は両120が有限で各−.25未満だけ拒否。未知をゼロへ代入しない。")
    target = HERE/f"再試験強逆流拒否の作成者人工_{time.time_ns()}.json"
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps(dict(passed=True,cases=cases,checks=len(CHECKS),path=str(target)),ensure_ascii=False))


if __name__ == "__main__":
    main()
