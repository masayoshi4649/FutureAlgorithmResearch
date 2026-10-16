"""105の部品切替・固定R・損失帯・session停止を実データなしで確認する。"""

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import time
import traceback

import numpy as np

import interface


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
COUNTS={}
ARRAYS=('orders','trades','growth_cohorts','events','stats','curve','source_curve','target_trace',
        'judgments','candidate_diagnostics','stale_equity')
NEW_ARRAYS=('control_judgments','control_events','control_integer_events','candidate_controls',
            'candidate_integer_keys','control_stats')


def check(name: str, condition: bool) -> None:
    """
    機能: 人工の独立期待条件を確認し件数を記録する。
    引数: name(str)は検査名、condition(bool)は期待一致。
    返り値: None。不一致は停止して元source/Falseを保存する。
    """
    assert condition,name
    COUNTS[name]=COUNTS.get(name,0)+1


def config(kind: str='B4', **parts: object) -> dict:
    """
    機能: 人工専用の旧共通設定と部品設定を作る。
    引数: kind(str)は旧B/T、parts(dict)は人工の部品指定。
    返り値: dictは人工条件。正式catalogの採択及び最適化はしない。
    """
    value=dict(id='人工_'+kind,support_ticks=int(kind[1]),profit_trail=kind.startswith('T'),
        initial_stop_fraction=.001,cooldown_seconds=30.,start_offset=300.,cut_offset=300.,force_offset=60.,
        r_profit=False,alpha=2.,beta=1.,reentry_band=False,session_brake=False,session_budget_multiple=1.)
    value.update(parts)
    return value


def fixture(symbol: str, side: int=1, sequence_base: int=1000) -> tuple[dict,dict]:
    """
    機能: 正常自己気配と一候補の原行対応を持つ人工素材を作る。
    引数: symbol(str)、side(int)、sequence_base(int)は商品/方向/整数seq起点。
    返り値: tuple[dict,dict]はpreparedとnormal。原本/旧cache/APIは読まない。
    """
    opening,tick=(4000.,.5) if symbol=='TOPIX' else (50000.,10.)
    n=1250
    times=np.arange(n,dtype=np.float64)
    seq=np.arange(n,dtype=np.int64)+sequence_base
    bid,ask=np.full(n,opening),np.full(n,opening+tick)
    record=dict(symbol=symbol,session='人工',time_s=times,seq=seq,bid=bid,ask=ask,price=(bid+ask)/2.,
        quote_valid=np.ones(n,bool),price_valid=np.ones(n,bool),tick=tick,start=0.,limit=1200.,end=1250.,人工素材=True)
    prepared=dict(record=record,signal=dict(trend_width=max(2,math.ceil(opening*.004/tick-1e-10))*tick),reference_open=opening)
    case=dict(entry_id='C_OWN',event=np.zeros(n,np.int8),support_price=np.full(n,np.nan),
        entry_quality=np.ones(n,bool),entry_reset=np.zeros(n,bool),execution_to_raw_index=np.arange(n,dtype=np.int64),decisions=[])
    set_event(prepared,case,330,side,opening if side==1 else opening+tick,328)
    return prepared,case


def set_event(prepared: dict, case: dict, row: int, side: int, support: float,
              anchor_row: int, second_anchor_row: int | None=None) -> None:
    """
    機能: 当時候補と選択支持根拠を、同normal/raw原行へ一致させる。
    引数: prepared/case(dict)、row/side/anchor_row(int)、support(float)、second_anchor_row(int | None)はU同値根拠。
    返り値: None。人工だけを変更し、将来anchorを候補へ渡さない。
    """
    record=prepared['record']
    case['event'][row],case['support_price'][row]=side,support
    roots=[dict(family='C',anchor_raw_seq=int(record['seq'][anchor_row]),support_price=support)]
    if second_anchor_row is not None:
        roots.append(dict(family='R',anchor_raw_seq=int(record['seq'][second_anchor_row]),support_price=support))
    values=dict(row=row,normal_row=row,raw_row=int(case['execution_to_raw_index'][row]),raw_seq=int(record['seq'][row]),
        side=side,support_price=support,self_lineages=deepcopy(roots),selected_support_roots=roots)
    case['decisions']=[value for value in case['decisions'] if value['row']!=row]+[values]
    case['decisions'].sort(key=lambda value:value['row'])


def quote_from(prepared: dict, row: int, quote: float, side: int) -> None:
    """
    機能: その行以後の清算気配を同spreadの人工値へ置く。
    引数: prepared(dict)、row/side(int)、quote(float)は当時以後の値。
    返り値: None。人工の原行順は変えない。
    """
    record,tick=prepared['record'],prepared['record']['tick']
    record['bid'][row:]=quote if side==1 else quote-tick
    record['ask'][row:]=quote+tick if side==1 else quote
    record['price'][row:]=(record['bid'][row:]+record['ask'][row:])/2.


def compare(first: dict, second: dict, names: tuple=ARRAYS) -> None:
    """
    機能: 型/形状/値を許容誤差なしで全配列比較する。
    引数: first/second(dict)、names(tuple[str])は比較対象。
    返り値: None。NaN同位置以外を救済しない。
    """
    for name in names:
        assert first[name].dtype==second[name].dtype and first[name].shape==second[name].shape,name
        np.testing.assert_array_equal(first[name],second[name],err_msg=name)


def run(prepared: dict, case: dict, settings: dict, quantity: int=1, finish: bool=True,
        entry_filter: np.ndarray | None=None, filter_reason: np.ndarray | None=None) -> dict:
    """
    機能: 一つの人工経路でPython/JITの全経済及び制御を照合する。
    引数: prepared/case/settings(dict)、quantity(int)、finish(bool)、入口mask/理由(np.ndarray | None)。
    返り値: dictはJIT出力。正式金融又は数値探索はしない。
    """
    python=interface.play(prepared,case,settings,quantity,finish,True,entry_filter,filter_reason)
    native=interface.play(prepared,case,settings,quantity,finish,False,entry_filter,filter_reason)
    compare(python,native,ARRAYS+NEW_ARRAYS)
    check('PythonとJITの経済及び制御全配列一致',True)
    return native


def cut(prepared: dict,case: dict,length: int) -> tuple[dict,dict]:
    """
    機能: 既知場末を変えず人工normal、map及び当時候補を同prefixへ切る。
    引数: prepared/case(dict)、length(int)は接頭長。
    返り値: tuple[dict,dict]は切断素材。端点を場末に代用しない。
    """
    n=len(case['event'])
    record={name:value[:length] if isinstance(value,np.ndarray) and len(value)==n else value for name,value in prepared['record'].items()}
    small={name:value[:length] if isinstance(value,np.ndarray) and len(value)==n else value for name,value in case.items()}
    small['decisions']=[row for row in case['decisions'] if row['row']<length]
    return dict(prepared,record=record),small


def main() -> None:
    """
    機能: 部品off104同値、R/料/次quote、帯/整数根拠、brake、prefixを人工で確認する。
    引数: なし。
    返り値: None。最終sourceへ人工証跡を結ぶ。正式データ又は金融を読まない。
    """
    target=HERE/'固定Rと損失帯及びsession停止の人工検査.json'
    assert not target.exists()
    paths=[Path(__file__),HERE/'core.py',HERE/'interface.py',HERE/'legacy_snapshot.py']
    start={path.relative_to(ROOT).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    check('104snapshotはexactbytesで新所有source', (HERE/'legacy_snapshot.py').read_bytes()==(ROOT/'work/wave_v104/engine/core.py').read_bytes())
    for symbol in ('TOPIX','NK225'):
        quantities=(1,5,10) if symbol=='TOPIX' else (1,10,20)
        multiplier,fee_unit=(1000.,41.8) if symbol=='TOPIX' else (10.,11.)
        for side in (1,-1):
            for quantity in quantities:
                for kind in ('B1','B2','B4','T2','T4'):
                    prepared,case=fixture(symbol,side)
                    tick=prepared['record']['tick']
                    quote_from(prepared,340,float(case['support_price'][330])-side*int(kind[1])*tick,side)
                    result=run(prepared,case,config(kind),quantity)
                    old=interface.legacy(prepared,case,config(kind),quantity)
                    compare(result,old)
                    check('全部品offの104経済判断exact同値',True)
                    expected_fee=math.floor(quantity*fee_unit+1e-8)
                    check('数量別注文fee floor',np.all(result['orders'][:,9]==expected_fee))
                    check('正常別行の新規と返済',result['orders'][0,0]==331 and result['orders'][0,1]==330
                          and result['orders'][1,0]>result['orders'][1,1])
                # ----------------------------------------
                # Rは初期支持kSと実量料から固定し、利益係数が変わっても交換しない。
                for alpha,beta in ((2.,1.),(3.,2.)):
                    prepared,case=fixture(symbol,side)
                    initial=run(prepared,case,config(r_profit=True,alpha=alpha,beta=beta),quantity)
                    first=initial['control_judgments'][initial['control_judgments'][:,0]==331][0]
                    entry=float(initial['orders'][0,6])
                    stop=float(initial['judgments'][0,17])
                    fee=math.floor(quantity*fee_unit+1e-8)
                    exact_f=2*fee/(quantity*multiplier)
                    risk=math.ceil((side*(entry-stop)+exact_f)/tick-1e-10)*tick
                    f=math.ceil(exact_f/tick-1e-10)*tick
                    check('実fill初期線と実料からRを固定',first[6]==risk and first[11]==exact_f)
                    quote_from(prepared,340,entry+side*(f+alpha*risk),side)
                    quote_from(prepared,344,entry+side*(f+(alpha-beta)*risk),side)
                    quote_from(prepared,345,entry-side*risk,side)
                    result=run(prepared,case,config(r_profit=True,alpha=alpha,beta=beta),quantity)
                    activated=result['judgments'][result['judgments'][:,0]==340][0]
                    check('R発動と独立追尾及び保護床',activated[15]==1 and activated[13]==entry+side*(f+(alpha-beta)*risk)
                          and activated[14]==entry+side*(f+(alpha-beta)*risk))
                    check('床でも次quoteの赤字は残る',result['orders'][1,1]==344 and result['orders'][1,0]==345 and result['trades'][0,11]<0)
                    check('停止線を不利に緩めない',np.all(side*np.diff(result['judgments'][:,17])>=-1e-8))
                    check('Rを保有中に交換しない',np.all(result['control_judgments'][result['control_judgments'][:,3]==1,6][1:]==risk))
            # ----------------------------------------
            # 非正Rと即fill破綻を架空取消にせず、同row予約・別quote返済。
            prepared,case=fixture(symbol,side)
            tick=prepared['record']['tick']
            set_event(prepared,case,330,side,float(case['support_price'][330])+side*20*tick,328)
            result=run(prepared,case,config(r_profit=True,reentry_band=True))
            check('非正Rを不正記録し次quote返済',np.any(result['control_events'][:,4]==2)
                  and result['orders'][1,1]==331 and result['orders'][1,0]==332
                  and not result['control_judgments'][result['control_judgments'][:,0]==331][0,7])
            check('R不存在の損失帯は捏造しない',np.any(result['control_events'][:,4]==11)
                  and not np.any(result['control_events'][:,4]==3))
            # ----------------------------------------
            # 同方向帯→別原行脱出→全選択anchorが新しく帯外のpulseだけで再参加。
            prepared,case=fixture(symbol,side,sequence_base=2**53+100)
            settings=config(reentry_band=True)
            tick=prepared['record']['tick']
            support=float(case['support_price'][330])
            quote_from(prepared,340,support-side*4*tick,side)
            base=run(prepared,case,settings)
            radius=float(base['control_events'][base['control_events'][:,4]==3][0,7])
            set_event(prepared,case,375,side,support,374)
            quote_from(prepared,380,support+side*(radius+2*tick),side)
            set_event(prepared,case,380,side,support+side*(radius+tick),379)
            set_event(prepared,case,385,side,support+side*(radius+tick),379)
            set_event(prepared,case,390,side,support+side*(radius+tick),388,379)
            set_event(prepared,case,395,side,support+side*(radius+tick),394)
            set_event(prepared,case,400,side,support+side*(radius+tick),399)
            mask=np.ones(len(case['event']),bool);mask[395]=False
            reasons=np.zeros(len(mask),np.int32);reasons[395]=17
            result=run(prepared,case,settings,entry_filter=mask,filter_reason=reasons)
            rejected={int(row[0]):int(row[6]) for row in result['candidate_controls']}
            check('同帯と同row脱出及び古いanchorを拒否',all(rejected[row]==9 for row in (375,380,385,390)))
            check('外部filter不合格で帯解除しない',rejected[395]==9 and not np.any((result['control_events'][:,0]==395)&(result['control_events'][:,4]==6)))
            check('全選択新anchor帯外でのみ解除',rejected[400]==0 and np.any((result['control_events'][:,0]==400)&(result['control_events'][:,4]==6)))
            check('2の53乗超のanchorを整数で厳密保持',result['candidate_integer_keys'][result['candidate_integer_keys'][:,0]==390][0,2]
                  ==int(prepared['record']['seq'][379]))
            prepared['record']['quote_valid'][397]=False
            case['entry_reset'][398]=True
            set_event(prepared,case,400,side,support+side*(radius+tick),398)
            result=run(prepared,case,settings,entry_filter=mask,filter_reason=reasons)
            check('不明resetは脱出確認だけを破棄',np.any((result['control_events'][:,0]==397)&(result['control_events'][:,4]==5))
                  and not np.any((result['control_events'][:,0]==400)&(result['control_events'][:,4]==6)))
            # ----------------------------------------
            # 小さいstress予算で保有停止を発火し、次quote超過とsession継続停止を確認。
            prepared,case=fixture(symbol,side)
            settings=config(session_brake=True,session_budget_multiple=.25)
            initial_width=max(2,math.ceil(prepared['reference_open']*.001/tick-1e-10))*tick
            entry=float(prepared['record']['ask'][331] if side==1 else prepared['record']['bid'][331])
            quote_from(prepared,335,entry-side*.25*initial_width,side)
            quote_from(prepared,336,entry-side*2*initial_width,side)
            set_event(prepared,case,375,side,float(case['support_price'][330]),374)
            result=run(prepared,case,settings)
            check('session予算は当時equityと既知S実量',result['control_stats'][2]==1 and result['control_stats'][1]==.25*initial_width*multiplier)
            check('brake判断は次quote返済',result['orders'][1,1]==335 and result['orders'][1,0]==336 and result['orders'][1,8]==7)
            check('予算超過は隠さず停止後再開なし',result['control_stats'][6]>0 and len(result['orders'])==2
                  and result['candidate_controls'][result['candidate_controls'][:,0]==375][0,6]==8)
            # ----------------------------------------
            # fill後のquality/reset悪化で予約取消なし。未返済接頭に未来清算を混ぜない。
            prepared,case=fixture(symbol,side)
            settings=config(r_profit=True,reentry_band=True,session_brake=True)
            case['entry_quality'][331:]=False;case['entry_reset'][331:]=True
            prepared['record']['quote_valid'][331:336]=False
            full=run(prepared,case,settings)
            check('予約後qualification悪化は未来取消なし',full['orders'][0,0]==336)
            small,reduced=cut(prepared,case,400)
            past=run(small,reduced,settings,finish=False)
            check('保有prefixでfuture場末清算なし',len(past['orders'])==1 and not len(past['trades'])
                  and np.array_equal(past['curve'],full['curve'][:400]))
            changed=deepcopy(prepared);future=deepcopy(case)
            changed['record']['bid'][400:]+=100*tick;changed['record']['ask'][400:]+=100*tick
            future['entry_quality'][400:]=True;future['entry_reset'][400:]=False
            small,reduced=cut(changed,future,400)
            alternative=run(small,reduced,settings,finish=False)
            compare(past,alternative,ARRAYS+NEW_ARRAYS)
            check('未来変更のprefix全経済制御不変',True)
    ending={path.relative_to(ROOT).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    check('人工source開始終端一致',start==ending)
    output=dict(全合格=True,人工専用=True,検査件数=COUNTS,source_SHA256=start,開始終端source一致=True,
        正式金融再生=0,正式input読取=0,旧cache読取=0,旧104source変更=0,原本及びNPZ読取=0,API取得=0,実注文=0,
        固定catalogの採択='根が別に固定。人工stress予算及び価格経路は数値探索へ使用しない。',
        限界='単一又は実qtyの腿別brake。配分合計の共有brakeは今回未実装。固定予算単一のpending取消分岐は防御仕様であり、通常経路の到達例と偽装しない。')
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,検査件数=COUNTS),ensure_ascii=False),flush=True)


if __name__=='__main__':
    try:
        main()
    except Exception as error:
        folder=HERE/('人工False_'+time.strftime('%Y%m%d_%H%M%S'))
        folder.mkdir(exist_ok=False)
        hashes={}
        for name in ('core.py','interface.py','artificial.py'):
            saved=(HERE/name).read_bytes();(folder/name).write_bytes(saved)
            hashes[name]=hashlib.sha256(saved).hexdigest()
        (folder/'False.json').write_text(json.dumps(dict(全合格=False,例外型=type(error).__name__,例外=str(error),
            traceback=traceback.format_exc(),原sourceSHA256=hashes,完了検査件数=COUNTS,正式金融再生=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise
