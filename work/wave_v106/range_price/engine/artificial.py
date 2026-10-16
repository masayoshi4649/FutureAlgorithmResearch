"""新Rの物理注文とC旧経済を、少量人工とコピー対照だけで確認する。"""

from copy import deepcopy
from pathlib import Path
import traceback

import numpy as np

import common

HERE=Path(__file__).resolve().parent
INTERFACE=common.module('106R_PRICEの人工接口',HERE.parent/'interface.py')
CHECKS={}


def check(label: str, value: bool) -> None:
    """
    機能: 独立期待値の成否を名前別に記録する。
    引数: label(str)、value(bool)は検査名と一致。
    返り値: None。不一致で正式金融を開始しない。
    """
    assert value,label;CHECKS[label]=CHECKS.get(label,0)+1


def fixture(symbol: str, side: int, family: int=2, mode: int=1) -> tuple:
    """
    機能: 実数量料と鏡像buy/sellを持つ正常価格の人工候補を作る。
    引数: symbol(str)、side/family/mode(int)は商品・方向・C/R・市場/指値。
    返り値: tuple[dict,dict,dict]はprepared、normal、B4設定。正式cacheを読まない。
    """
    n=1001;tick=.5 if symbol=='TOPIX' else 10.;opening=4000. if symbol=='TOPIX' else 66000.
    bid=np.full(n,opening if side==1 else opening-tick);ask=bid+tick
    record=dict(seq=np.arange(n,dtype=np.int64),time_s=np.arange(n,dtype=np.float64),bid=bid,ask=ask,
        price=(bid+ask)/2,quote_valid=np.ones(n,bool),price_valid=np.ones(n,bool),symbol=symbol,
        start=0.,end=1000.,limit=1000.,tick=tick,人工素材=True)
    p=dict(record=record,reference_open=opening,signal=dict(trend_width=np.ceil(opening*.004/tick-1e-10)*tick))
    normal=dict(entry_id='人工C' if family==1 else '人工R_PRICE',event=np.zeros(n,np.int8),support_price=np.full(n,np.nan),
        entry_quality=np.ones(n,bool),entry_reset=np.zeros(n,bool),execution_to_raw_index=np.arange(n,dtype=np.int64),decisions=[],
        entry_families=np.zeros(n,np.int8),target_prices=np.full(n,np.nan),entry_stop_prices=np.full(n,np.nan),
        entry_limit_prices=np.full(n,np.nan),entry_modes=np.zeros(n,np.int8),range_pending_trend=np.zeros(n,bool),
        quiet=np.zeros(n,bool),quiet_start_s=np.full(n,np.nan))
    cfg=dict(id='人工R_PRICE',support_ticks=4,profit_trail=False,r_profit=False,reentry_band=False,session_brake=False,
        alpha=2.,beta=1.,session_budget_multiple=1.,initial_stop_fraction=.001,cooldown_seconds=30.,start_offset=300.,cut_offset=300.,force_offset=60.)
    add_event(p,normal,330,side,family,mode)
    return p,normal,cfg


def add_event(p: dict, normal: dict, row: int, side: int, family: int, mode: int=1) -> None:
    """
    機能: 当該rowに自己支持又は価格範囲の新候補を一回置く。
    引数: p/normal(dict)、row/side/family/mode(int)は正常原行と意図。
    返り値: None。Rに架空の板支持根拠を作らない。
    """
    record=p['record'];tick=record['tick'];opening=p['reference_open']
    stop=opening-side*4*tick;support=opening if family==1 else stop
    normal['event'][row]=side;normal['support_price'][row]=support;normal['entry_families'][row]=family
    normal['entry_modes'][row]=mode if family==2 else 1
    if family==2:
        normal['entry_stop_prices'][row]=stop;normal['target_prices'][row]=opening+side*12*tick
        if mode==2:normal['entry_limit_prices'][row]=record['bid'][row] if side==1 else record['ask'][row]
    roots=[dict(anchor_raw_seq=row-1,support_price=support)] if family==1 else []
    normal['decisions'].append(dict(row=row,normal_row=row,raw_row=row,raw_seq=row,side=side,support_price=support,
        selected_support_roots=roots,reference_kind='板支持' if family==1 else '純価格範囲外停止'))


def clearing(p: dict, start: int, side: int, value: float, end: int | None=None) -> None:
    """
    機能: 指定期間の清算側quoteを置き、反対側を1呼値差にする。
    引数: p(dict)、start/side(int)、value(float)、end(int|None)は更新区間。
    返り値: None。入力だけの人工変化。
    """
    record=p['record'];target=slice(start,end);tick=record['tick']
    record['bid'][target]=value if side==1 else value-tick
    record['ask'][target]=value+tick if side==1 else value


def play(p: dict, normal: dict, cfg: dict, quantity: int, finish: bool=True, python: bool=True) -> dict:
    """
    機能: 人工だけを所有域執行へ接続する。
    引数: p/normal/cfg(dict)、quantity(int)、finish/python(bool)は数量と接頭/JIT。
    返り値: dictは物理注文と会計材料。正式金融ではない。
    """
    return INTERFACE.play(p,normal,cfg,quantity=quantity,finish=finish,python=python)


def prefix(p: dict, normal: dict, length: int) -> tuple:
    """
    機能: 同一原行で人工接頭を切り、未来清算へ依存しない素材を作る。
    引数: p/normal(dict)、length(int)は接頭長。
    返り値: tuple[dict,dict]はpreparedとnormal。
    """
    short=deepcopy(p);short['record']={k:v[:length].copy() if isinstance(v,np.ndarray) else v for k,v in p['record'].items()}
    case={k:v[:length].copy() if isinstance(v,np.ndarray) else deepcopy(v) for k,v in normal.items()}
    case['decisions']=[d for d in case['decisions'] if d['row']<length]
    return short,case


def main() -> None:
    """
    機能: C互換、R指値取消優先、gap、低qty料、共有cooldown、接頭/JITを確認する。
    引数: なし。
    返り値: None。正式input/金融/原本/APIは読まない。
    """
    target=HERE/'単一共有位置とR指値の人工検査.json';assert not target.exists()
    paths=[HERE/n for n in ('core.py','legacy_core.py','common.py','artificial.py')]+[HERE.parent/'interface.py']
    before={str(p.relative_to(common.ROOT)):common.digest(p) for p in paths}
    legacy=INTERFACE.module('106R_PRICEの旧regime経済コピー',HERE/'legacy_core.py')
    for symbol in ('TOPIX','NK225'):
        q=5 if symbol=='TOPIX' else 10;unit=41.8 if symbol=='TOPIX' else 11.
        for side in (1,-1):
            p,c,cfg=fixture(symbol,side,1);signal,setting=INTERFACE.connect(p,c,cfg,q)
            signal.update(quiet=c['quiet'],quiet_start_s=c['quiet_start_s'],entry_families=c['entry_families'],target_prices=c['target_prices'])
            old=legacy.execute(p['record'],signal,setting,python=True);new=play(p,c,cfg,q)
            for name in ('orders','trades','growth_cohorts','curve','source_curve','target_trace','judgments','control_events'):
                np.testing.assert_array_equal(old[name],new[name])
            check('Cだけは旧B4同数量の全経済exact',True)
            double=play(p,c,cfg,q*2)
            np.testing.assert_allclose(double['curve']/2,new['curve'],atol=1e-4,rtol=0)
            np.testing.assert_array_equal(double['orders'][:,5]/2,new['orders'][:,5]);np.testing.assert_array_equal(double['orders'][:,9]/2,new['orders'][:,9])
            check('10対5又は20対10のC会計deriveは物理注文と費用も一致',True)
            p,c,cfg=fixture(symbol,side);tick=p['record']['tick'];target_price=c['target_prices'][330]
            clearing(p,340,side,target_price)
            new=play(p,c,cfg,q)
            check('Rmarketは判断後の初normal、target初到達後さらに次quote',new['orders'][:,0].tolist()==[331.,341.] and new['orders'][1,1]==340)
            check('低qtyの注文別料金を実計算',new['orders'][:,9].tolist()==[np.floor(q*unit+1e-8)]*2)
            check('Rに板支持を捏造せず固定stopとfamilyを別記',new['raw_entry_diagnostics'][0]['family']=='R_PRICE' and 'fixed_support_price' not in new['raw_entry_diagnostics'][0])
            p,c,cfg=fixture(symbol,side);c['entry_quality'][:]=False;c['entry_reset'][:]=True;clearing(p,340,side,c['target_prices'][330]);new=play(p,c,cfg,q)
            check('Rに旧Cの数量出来高資格を二重適用しない',len(new['trades'])==1)
            p,c,cfg=fixture(symbol,side);stop=c['entry_stop_prices'][330]
            clearing(p,331,side,stop-side*tick,332);new=play(p,c,cfg,q)
            check('marketgapがstop外でもfillを残し当行判断から次quote返済',new['orders'][:,0].tolist()==[331.,332.] and new['orders'][1,8]==11)
            p,c,cfg=fixture(symbol,side);clearing(p,331,side,c['target_prices'][330]+side*tick,332);new=play(p,c,cfg,q)
            check('marketgapのtarget越えを架空取消せず次quote損失も保存',new['orders'][:,0].tolist()==[331.,332.] and new['trades'][0,11]<0)
            for cancellation in ('UNKNOWN待機','TREND取消','stop外取消','到達fill先'):
                p,c,cfg=fixture(symbol,side,2,2);limit=c['entry_limit_prices'][330];tick=p['record']['tick']
                if cancellation=='UNKNOWN待機':
                    clearing(p,350,side,limit-side*tick)
                    clearing(p,360,side,c['target_prices'][330])
                elif cancellation=='TREND取消':c['range_pending_trend'][340]=True
                elif cancellation=='stop外取消':
                    if side==1:p['record']['bid'][340]=c['entry_stop_prices'][330]-tick
                    else:p['record']['ask'][340]=c['entry_stop_prices'][330]+tick
                else:
                    clearing(p,331,side,limit-side*tick);c['range_pending_trend'][331]=True
                    clearing(p,340,side,c['target_prices'][330])
                new=play(p,c,cfg,q)
                if cancellation=='UNKNOWN待機':check('UNKNOWNをTRENDへ代用せずpending待機',new['orders'][0,0]==350)
                elif cancellation=='到達fill先':check('同行limit到達をTREND取消より先に実fill、modeだけでは退出なし',new['orders'][:,0].tolist()==[331.,341.] and new['raw_entry_diagnostics'][0]['fill_known_trend'])
                else:check(cancellation+'は未fillだけ取消して復活なし',len(new['orders'])==0 and np.any(new['events'][:,3]==6))
            for timer in ('J','cut'):
                p,c,cfg=fixture(symbol,side,2,2);limit=c['entry_limit_prices'][330]
                at=331
                if timer=='J':c['quiet_start_s'][at]=float(at);c['quiet'][at:360]=True
                else:
                    cfg['cut_offset']=669.
                clearing(p,at,side,limit-side*p['record']['tick'])
                new=play(p,c,cfg,q);check('既知'+timer+'取消は同行livefillより先',len(new['orders'])==0)
            p,c,cfg=fixture(symbol,side);clearing(p,340,side,c['target_prices'][330]);add_event(p,c,342,side,1);add_event(p,c,372,side,1)
            new=play(p,c,cfg,q);check('単一位置とR返済後30秒のC共有cooldown',new['orders'][new['orders'][:,7]==1,1].tolist()==[330.,372.])
            check('片方向最大保有と場末flat',new['target_trace'][:,:2].max()<=q and not new['target_trace'][-1].any())
            p,c,cfg=fixture(symbol,side,2,2);clearing(p,350,side,c['entry_limit_prices'][330]-side*p['record']['tick']);clearing(p,400,side,c['target_prices'][330])
            full=play(p,c,cfg,q);small,case=prefix(p,c,390);past=play(small,case,cfg,q,finish=False)
            np.testing.assert_array_equal(past['orders'],full['orders'][full['orders'][:,0]<390]);np.testing.assert_allclose(past['curve'],full['curve'][:390],atol=1e-4,rtol=0)
            check('保有prefixに未来target又は場末清算なし',len(past['orders'])==1 and len(past['trades'])==0)
            altered=deepcopy(p);changed=deepcopy(c);clearing(altered,390,side,p['reference_open']+side*100*p['record']['tick']);changed['range_pending_trend'][390:]=True
            future=play(altered,changed,cfg,q);np.testing.assert_array_equal(future['orders'][future['orders'][:,0]<390],past['orders']);np.testing.assert_allclose(future['curve'][:390],past['curve'],atol=1e-4,rtol=0)
            check('未来quoteとmodeを変えてもpast不変',True)
            common.immutable(p)
            for name in ('entry_quality','entry_reset','execution_to_raw_index'):c[name].flags.writeable=False
            native=play(p,c,cfg,q,python=False)
            for name in ('orders','trades','growth_cohorts','curve','source_curve','target_trace','judgments','control_events','candidate_controls'):
                np.testing.assert_array_equal(native[name],full[name])
            check('readonly正式signatureのPythonJIT同値',True)
    assert before=={p:common.digest(common.ROOT/p) for p in before}
    common.save(target,dict(全合格=True,人工専用=True,検査件数=CHECKS,source_SHA256=before,
        開始終端source一致=True,新金融再生=0,正式input読取=0,原板読取=0,API取得=0))
    print('R_PRICE/共有位置人工 '+str(sum(CHECKS.values()))+'件',flush=True)


if __name__=='__main__':
    try:main()
    except Exception as error:
        folder=HERE/'初回人工False';folder.mkdir(exist_ok=False)
        for p in (Path(__file__),HERE/'core.py',HERE.parent/'interface.py'):(folder/p.name).write_bytes(p.read_bytes())
        common.save(folder/'False.json',dict(全合格=False,例外=str(error),traceback=traceback.format_exc(),完了検査=CHECKS,新金融再生=0))
        raise
