"""実市場を読まず、八つの固定組設定と核心の保存接口を薄く接続する。"""

from datetime import datetime,timedelta,timezone
from io import BytesIO
import hashlib
import json
from pathlib import Path

import numpy as np

import run_v7 as R


HERE=Path(__file__).resolve().parent
COUNTS={}


def check(value: bool,label: str) -> None:
    """
    機能: 合成だけの期待を項目別に記録する。
    引数: value(bool)は一致条件、label(str)は検査項目。
    返り値: None。不一致は停止する。
    """
    assert value,label
    COUNTS[label]=COUNTS.get(label,0)+1


def material() -> tuple[dict,dict,dict,dict]:
    """
    機能: 過去モデルと二回の相対乖離を含む、完全に架空の二市場を作る。
    引数: なし。
    返り値: tuple[dict,dict,dict,dict]はNK/TOPの足とNK/TOPの正常気配。
    """
    n=80;origin=datetime(2034,1,12,9,tzinfo=timezone(timedelta(hours=9))).timestamp()
    ticks=np.arange(n,dtype=float);clocks=origin+60*ticks
    top=4000*np.exp(.0001*ticks+.0003*np.sin(ticks/7))
    nk=16*top*np.exp(.001*np.sin(ticks/2))
    bars=[];quotes=[]
    for code,price in enumerate((nk,top)):
        bars.append(dict(t_s=clocks.copy(),close=price.copy(),valid=np.ones(n,bool),pub_price_time_s=clocks+60))
        qt=[];last=[]
        for i in range(n):
            point=price[i]
            if code==0 and i in (65,72):point*=1.01
            for offset in (0.,1.+code,20.):qt.append(clocks[i]+60+offset);last.append(point)
        last=np.asarray(last);spread=10. if code==0 else .5
        quotes.append(dict(row=np.arange(len(last),dtype=np.int64),time=np.asarray(qt),last=last,
            bid=last-spread/2,ask=last+spread/2,bq=np.full(len(last),100.),aq=np.full(len(last),100.)))
    return bars[0],bars[1],quotes[0],quotes[1]


def main() -> None:
    """
    機能: 八設定の核心実人工を保存へ接続し、商品脚・列型・未知保存を確認する。
    引数: なし。
    返り値: None。正式金融・原市場・保存実cache・登録は0。
    """
    target=HERE/'相対momentum八設定と二脚保存の接続人工.json';assert not target.exists()
    specs=R.make_specs();check(len(specs)==8 and {(s['method'],s['lookback'],s['exit_mode']) for s in specs}=={(m,l,x) for m in R.METHODS for l in R.LOOKBACKS for x in (0,1)} and all(s['family']=='momentum' for s in specs),'固定八条件一意')
    data=material();folder=HERE/'artificial_connection';assert not folder.exists();folder.mkdir()
    # ----------------------------------------
    # 読取は架空npzだけ。禁止用objectの旧policy列へ触れるとallow_pickle=Falseで失敗する。
    for symbol,bars,quotes in zip(R.SYMBOLS,data[:2],data[2:]):
        arrays={**{'bars__'+k:v for k,v in bars.items()},**{'quotes__'+k:v for k,v in quotes.items()},'policies__触れてはいけない':np.array([object()],dtype=object)}
        memory=BytesIO();np.savez_compressed(memory,**arrays);payload=memory.getvalue();path=folder/(symbol+'.npz');path.write_bytes(payload)
        item=dict(owned_path=path.relative_to(R.ROOT).as_posix(),SHA256=hashlib.sha256(payload).hexdigest(),bytes=len(payload))
        b,q=R.load_market(item)
        check(set(b)==set(bars) and set(q)==set(quotes),'旧policyを読まない足気配だけの射影')
        check(all(np.array_equal(b[k],v) for k,v in bars.items()) and all(np.array_equal(q[k],v) for k,v in quotes.items()),'架空cacheの全列同値')
    packed={};legs={s:{} for s in R.SYMBOLS};details=[]
    for spec in specs:
        config=R.settings('2034-01-12_Day',spec);answer=R.engine_v7.run_pair(*data,config)
        arrays,per_leg=R.pack_answer(spec['id'],answer,'leg',dict(NK225=0,TOPIX=1));packed.update(arrays)
        for symbol in R.SYMBOLS:legs[symbol].update(per_leg[symbol])
        check(set(answer['leg_summary'])==set(R.SYMBOLS),'組と二脚summaryの分離')
        check(abs(sum(v['net'] for v in answer['leg_summary'].values())-answer['summary']['net'])<1e-7,'両脚netと組netの和')
        check(len(answer['orders'])>0 and len(answer['parents'])>0,'接続人工に実fillと親がある')
        for code,symbol in enumerate(R.SYMBOLS):
            raw=answer['orders'][answer['orders'][:,1]==code]
            check(np.array_equal(per_leg[symbol][spec['id']+'__orders'],raw,equal_nan=True),'脚注文の無改変射影')
            check(abs(raw[:,9].sum()-answer['leg_summary'][symbol]['fees'])<1e-7,'複数親も脚料を全数加算')
        diagnosis=R.decompose_parents(answer['parents'])
        if not answer['summary']['unclosed']:
            check(abs(diagnosis['totals']['paired_net']+diagnosis['totals']['single_leg_net']-answer['summary']['net'])<1e-5,'相対共通診断と組netの一致')
        details.append(dict(id=spec['id'],summary=R.clean(answer['summary'])))
    cache=R.store_npz(folder/'PAIR.npz',packed)
    with np.load(folder/'PAIR.npz',allow_pickle=False) as saved:
        check(set(saved.files)==set(packed),'組保存の列数')
        for key,value in packed.items():check(np.array_equal(saved[key],value,equal_nan=True),'組保存のdtype値往復')
    for symbol in R.SYMBOLS:
        R.store_npz(folder/(symbol+'_legs.npz'),legs[symbol])
        with np.load(folder/(symbol+'_legs.npz'),allow_pickle=False) as saved:
            check(len(saved.files)==8 and all(np.array_equal(saved[k],v,equal_nan=True) for k,v in legs[symbol].items()),'商品八条件の保存往復')
    check(R.clean(dict(v=np.int64(2),a=np.float64(3),unknown=np.nan))==dict(v=2,a=3.,unknown=None),'NumPyと未知の標準JSON保存')
    source={p.relative_to(R.ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE/'run_v7.py',HERE/'plan_v7.py',HERE/'engine_v7.py',Path(__file__))}
    proof=dict(passed=True,scope='架空二市場の八設定→実核心→組/脚保存だけ。核心全境界は別独立監査へ委譲。',counts=COUNTS,total_checks=sum(COUNTS.values()),source_SHA256=source,
        details=details,artificial_cache=cache,原市場読取=0,既所有実cache読取=0,正式金融実行=0,API=0,登録変更=0)
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,checks=sum(COUNTS.values()),sha256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':
    main()
