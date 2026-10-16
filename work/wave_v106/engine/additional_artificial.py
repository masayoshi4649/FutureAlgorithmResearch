"""全量brake、呼値丸め、初期Rゼロ、cut/timerと制御prefixを補完する。"""

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import time
import traceback

import numpy as np

import artificial as factory
import interface


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
COUNTS={}


def check(name: str, condition: bool) -> None:
    """
    機能: 追加人工の独立期待条件を確認し記録する。
    引数: name(str)は検査名、condition(bool)は期待一致。
    返り値: None。失敗時はsourceとFalseを別保持する。
    """
    assert condition,name
    COUNTS[name]=COUNTS.get(name,0)+1


def simulate(prepared: dict,case: dict,config: dict,quantity: int,finish: bool=True,
             mask: np.ndarray | None=None) -> dict:
    """
    機能: 追加人工の同じ経路をPython/JITで比較する。
    引数: prepared/case/config(dict)、quantity(int)、finish(bool)、mask(np.ndarray | None)。
    返り値: dictは新所有JITの出力。実入力又は金融成果へ接続しない。
    """
    first=interface.play(prepared,case,config,quantity,finish,True,mask)
    second=interface.play(prepared,case,config,quantity,finish,False,mask)
    factory.compare(first,second,factory.ARRAYS+factory.NEW_ARRAYS)
    check('追加人工PythonとJIT全配列一致',True)
    return second


def main() -> None:
    """
    機能: 本体不変更で全量料金/brake/丸めと時間境界・保有端点を補完する。
    引数: なし。
    返り値: None。人工証跡のみ保存し、104/105金融・原本を読まない。
    """
    target=HERE/'全量brakeと丸め及びtimer境界の追加人工.json'
    assert not target.exists()
    paths=[Path(__file__),HERE/'core.py',HERE/'interface.py',HERE/'artificial.py',
        HERE/'legacy_snapshot.py',HERE/'固定Rと損失帯及びsession停止の人工検査.json']
    start={path.relative_to(ROOT).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    for symbol,quantity,multiplier,fee_unit in (('TOPIX',10,1000.,41.8),('NK225',20,10.,11.)):
        for side in (1,-1):
            # ----------------------------------------
            # 全量の当時equityで独立budgetを触れ、実次quote超過を全額含める。
            prepared,case=factory.fixture(symbol,side)
            tick=prepared['record']['tick']
            initial=max(2,math.ceil(prepared['reference_open']*.001/tick-1e-10))*tick
            entry=float(prepared['record']['ask'][331] if side==1 else prepared['record']['bid'][331])
            factory.quote_from(prepared,335,entry-side*.25*initial,side)
            factory.quote_from(prepared,336,entry-side*2*initial,side)
            factory.set_event(prepared,case,375,side,float(case['support_price'][330]),374)
            result=simulate(prepared,case,factory.config(session_brake=True,session_budget_multiple=.25),quantity)
            fee=math.floor(quantity*fee_unit+1e-8)
            budget=.25*initial*quantity*multiplier
            expected_loss=2*initial*quantity*multiplier+2*fee
            check('全量q10q20の独立session予算',result['control_stats'][1]==budget and result['control_stats'][2]==1)
            check('全量料金と次quote損失及び超過',result['trades'][0,11]==-expected_loss
                  and result['control_stats'][6]>=expected_loss-budget and np.all(result['orders'][:,9]==fee))
            check('全量保有予約上限と場内flat',np.all(result['target_trace'][:,:4]<=quantity) and not result['target_trace'][-1].any())
            # ----------------------------------------
            # fillのspread/料だけで予算を超えた場合も、約定を消さず次quoteで返済する。
            prepared,case=factory.fixture(symbol,side)
            result=simulate(prepared,case,factory.config(session_brake=True,session_budget_multiple=.05),quantity)
            check('fill行brakeを過去約定取消へ変えない',len(result['orders'])==2 and result['orders'][0,0]==331
                  and result['orders'][1,1]==331 and result['orders'][1,0]==332 and result['orders'][1,8]==7)
            # ----------------------------------------
            # fractional係数はroot採択ではなく、ceil幅と非丸め床の所有者を検査するstress。
            prepared,case=factory.fixture(symbol,side)
            setting=factory.config(r_profit=True,alpha=2.,beta=.75)
            initial_result=simulate(prepared,case,setting,quantity)
            first=initial_result['control_judgments'][initial_result['control_judgments'][:,0]==331][0]
            risk,f=first[6],initial_result['judgments'][0,26]
            width=math.ceil(.75*risk/tick-1e-10)*tick
            expected_floor=f+(2.-.75)*risk
            factory.quote_from(prepared,340,entry+side*(f+2.*risk),side)
            result=simulate(prepared,case,setting,quantity)
            value=result['control_judgments'][result['control_judgments'][:,0]==340][0]
            line=result['judgments'][result['judgments'][:,0]==340][0]
            profit_line=entry+side*(f+2*risk-width)
            floor_line=entry+side*expected_floor
            check('全量R料と利益幅の呼値切上げ',value[12]==width and value[13]==expected_floor)
            check('丸め後の床優先を実有効線に反映',line[17]==(max(line[16],profit_line,floor_line) if side==1 else min(line[16],profit_line,floor_line))
                  and int(line[18])&16!=0)
            # ----------------------------------------
            # 原式が数学的にゼロのRは、丸め誤差を有効なrisk単位へ捏造しない。
            prepared,case=factory.fixture(symbol,side)
            entry=float(prepared['record']['ask'][331] if side==1 else prepared['record']['bid'][331])
            exact_fee=2*fee/(quantity*multiplier)
            support=entry+side*(4*tick+exact_fee)
            factory.set_event(prepared,case,330,side,support,328)
            result=simulate(prepared,case,factory.config(r_profit=True,reentry_band=True),quantity)
            fill=result['control_judgments'][result['control_judgments'][:,0]==331][0]
            check('ゼロR又は丸めゼロを不正として記録',not bool(fill[7]) and np.any(result['control_events'][:,4]==2))
            check('ゼロRも即返済と帯未作成を保持',result['orders'][1,1]==331 and result['orders'][1,0]==332
                  and np.any(result['control_events'][:,4]==11))
            # ----------------------------------------
            # cut取消は現在quoteより先、known timerはその後の最初正常quoteで執行する。
            prepared,case=factory.fixture(symbol,side)
            case['event'][:]=0;case['support_price'][:]=np.nan;case['decisions']=[]
            support=float(prepared['record']['bid'][899] if side==1 else prepared['record']['ask'][899])
            factory.set_event(prepared,case,899,side,support,898)
            result=simulate(prepared,case,factory.config(r_profit=True,reentry_band=True,session_brake=True),quantity)
            check('cut取消が同row新規fillより先',not len(result['orders']) and np.any((result['events'][:,0]==900)&(result['events'][:,3]==6)))
            prepared,case=factory.fixture(symbol,side)
            prepared['record']['quote_valid'][1139:1146]=False
            setting=factory.config(r_profit=True,reentry_band=True,session_brake=True)
            result=simulate(prepared,case,setting,quantity)
            check('timer由来を保存し最初正常quoteで返済',result['orders'][1,8]==6 and result['orders'][1,0]==1146
                  and result['orders'][1,10]==1140. and result['orders'][1,1]==1139)
            check('timer不明quoteを補完しない',result['stale_equity'][1139:1146].all())
            # ----------------------------------------
            # fullと未約定/保有/返済予約のprefixを、未来端点清算なしで比較する。
            for length in (331,400,1143):
                small,reduced=factory.cut(prepared,case,length)
                part=simulate(small,reduced,setting,quantity,finish=False)
                check('全量予約保有返済予約prefixで未来清算なし',np.array_equal(part['curve'],result['curve'][:length])
                      and np.array_equal(part['target_trace'],result['target_trace'][:length])
                      and not len(part['trades']))
                expected_orders=result['orders'][result['orders'][:,0]<length]
                check('全量prefix実注文と元決定row一致',np.array_equal(part['orders'],expected_orders))
            # ----------------------------------------
            # 外部maskで現在候補を消費し、次rowへ持ち越さない。base資格も別に保存。
            prepared,case=factory.fixture(symbol,side)
            mask=np.ones(len(case['event']),bool);mask[330]=False
            result=simulate(prepared,case,factory.config(r_profit=True),quantity,mask=mask)
            check('外部filter拒否を未来正常rowへ移さない',not len(result['orders']) and result['candidate_controls'][0,6]==7)
    end={path.relative_to(ROOT).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    check('追加人工source開始終端一致',start==end)
    target.write_text(json.dumps(dict(全合格=True,人工専用=True,検査件数=COUNTS,source_SHA256=start,
        開始終端source一致=True,正式金融再生=0,正式入力読取=0,原本及びNPZ読取=0,API取得=0,
        旧source変更=0,新本体変更=0,数値チューニング=0,
        制限='fractional係数及び小budgetは算術/優先順のstressのみ。rootの採用catalogへ使用しない。'),
        ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,検査件数=COUNTS),ensure_ascii=False),flush=True)


if __name__=='__main__':
    try:
        main()
    except Exception as error:
        folder=HERE/('追加人工False_'+time.strftime('%Y%m%d_%H%M%S'))
        folder.mkdir(exist_ok=False)
        hashes={}
        for name in ('core.py','interface.py','artificial.py','additional_artificial.py'):
            saved=(HERE/name).read_bytes();(folder/name).write_bytes(saved)
            hashes[name]=hashlib.sha256(saved).hexdigest()
        (folder/'False.json').write_text(json.dumps(dict(全合格=False,例外型=type(error).__name__,例外=str(error),
            traceback=traceback.format_exc(),原sourceSHA256=hashes,完了検査件数=COUNTS,正式金融再生=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise
