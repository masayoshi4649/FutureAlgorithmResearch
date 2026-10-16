"""新しい価格素材だけを人工経路と未来切断で検査し、売買や損益を実行しない。"""

import ast
from collections import deque
from datetime import datetime,timezone,timedelta
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np


sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def module(name: str,path: Path) -> object:
    """機能: 新94の担当ファイルだけをモジュールとして読む。

    引数: name(str)、path(Path)。
    返り値: objectは読込モジュール。旧モジュールをimportせずbytecodeも保存しない。
    """
    assert path.resolve().is_relative_to(HERE)
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);sys.modules[name]=value;spec.loader.exec_module(value)
    return value


def reference() -> object:
    """機能: 原文ASTの純関数だけを隔離環境へ読み、旧importとcache書込みを避ける。

    引数: なし。
    返り値: objectは旧77価格と旧76完全板の対照関数。
    """
    old76=ROOT/'work/wave_v76/inputs/core.py';old77=ROOT/'work/wave_v77/inputs/core.py'
    env76=dict(np=np,math=math)
    tree=ast.parse(old76.read_text(encoding='utf-8'))
    selected=[node for node in tree.body if isinstance(node,ast.FunctionDef)
              or isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='SNAPSHOT_FIELDS' for target in node.targets)]
    exec(compile(ast.Module(body=selected,type_ignores=[]),str(old76),'exec'),env76)
    old=SimpleNamespace(**{key:value for key,value in env76.items() if not key.startswith('__')})
    env77=dict(np=np,deque=deque,LEGACY=old,WINDOWS=(30,60,180,300,600),RANGES=(60,180))
    tree=ast.parse(old77.read_text(encoding='utf-8'))
    selected=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in ('extrema','market_features')]
    exec(compile(ast.Module(body=selected,type_ignores=[]),str(old77),'exec'),env77)
    return SimpleNamespace(price=env77['market_features'],board=old)


def same(actual: object,expected: object) -> int:
    """機能: NaNを含む全列・全配列を厳密比較する。

    引数: actual/expected(object)。
    返り値: intは比較した配列数。
    """
    if isinstance(expected,dict):
        return sum(same(actual[key],value) for key,value in expected.items())
    if isinstance(expected,np.ndarray):
        np.testing.assert_array_equal(actual,expected)
        return 1
    assert actual==expected
    return 0


def fixture() -> tuple:
    """機能: 同時計後続の値が異なる、全正常の長い人工板系列を作る。

    引数: なし。
    返り値: tupleはgrid/ready/book/snapshot。
    """
    n=3000;times=np.repeat(np.arange(n//2,dtype=float),2);seq=np.arange(n,dtype=np.int64)
    mid=100.+((np.arange(n)//2)%37-18)*.25+(np.arange(n)%2)*.125
    ready=dict(seq=seq,time_s=times,tick=.5)
    reason=np.zeros(n,np.uint8);reason[0]=1
    book=dict(seq=seq.copy(),time_s=times.copy(),bid=mid-.25,ask=mid+.25,mid=mid,last=mid+.125,
              bid_qty=np.full(n,30.),ask_qty=np.full(n,50.),valid=np.ones(n,bool),reset=reason!=0,
              reset_reason=reason,best_ofi=np.where(np.arange(n)%3==0,2.,-1.))
    snap={field:np.linspace(.1,.2,n) for field in ('best_imbalance','microprice','micro_offset_ticks',
          'weighted_bid_qty','weighted_ask_qty','depth_imbalance','bid_weighted_distance','ask_weighted_distance')}
    snap.update(valid=np.ones(n,bool),seq=seq.copy(),time_s=times.copy())
    return np.arange(610.,1491.,5.),ready,book,snap


def narrowed(value: dict,stop: int,n: int) -> dict:
    """機能: 同じ原行prefixを抽出し、元の場末を補完しない。

    引数: value(dict)、stop/n(int)。
    返り値: dictは切断した入力。
    """
    return {key:item[:stop].copy() if isinstance(item,np.ndarray) and len(item)==n else item
            for key,item in value.items()}


def main() -> None:
    """機能: 価格資格と旧Q/Fの正負境界・原LP分離・未来不変を人工だけで検査する。

    引数: なし。
    返り値: None。担当inputsへ証跡JSONだけ保存し、全62素材や損益は生成しない。
    """
    core=module('価格分離94人工',HERE/'core.py');lp=module('原約定価格94人工',HERE/'last_price.py');old=reference()
    grid,ready,book,snap=fixture();base=core.market_features(grid,1,ready,book,snap)
    pure=core.price_features(grid,1,ready,book)
    assert 'flow' not in pure and 'q_current' not in pure and 'q_valid' not in pure['current']
    same(pure['windows'],base['windows']);same(pure['ranges'],base['ranges'])
    comparisons=same(base['current'],old.price(grid,1,ready,book,snap)['current'])
    comparisons+=same(base['windows'],old.price(grid,1,ready,book,snap)['windows'])
    comparisons+=same(base['ranges'],old.price(grid,1,ready,book,snap)['ranges'])
    comparisons+=same(base['q_current'],old.board.market_features(grid,1,ready,book,snap,windows=(15,30))['current'])
    comparisons+=same(base['flow'],old.board.market_features(grid,1,ready,book,snap,windows=(15,30))['windows'])
    normal=dict(全旧価格列一致=True,全旧Q及びFlow一致=True,比較配列数=comparisons)
    variants=[]
    for scenario in ('遠方数量不正','深板価格順不正','出来高reset','最良数量ゼロ','最良数量欠測',
                     '最良数量負','最良価格欠測','幅異常','原行gap','旧clock逆行旗'):
        r={k:v.copy() if isinstance(v,np.ndarray) else v for k,v in ready.items()}
        b={k:v.copy() if isinstance(v,np.ndarray) else v for k,v in book.items()}
        s={k:v.copy() if isinstance(v,np.ndarray) else v for k,v in snap.items()}
        i=1800
        if scenario in ('遠方数量不正','深板価格順不正'):
            b['valid'][i]=s['valid'][i]=False;b['reset_reason'][i]=4;b['reset_reason'][i+1]=1
        elif scenario=='出来高reset':b['reset_reason'][i]=16
        elif scenario.startswith('最良数量'):
            b['bid_qty'][i]={'最良数量ゼロ':0.,'最良数量欠測':np.nan,'最良数量負':-1.}[scenario]
            b['valid'][i]=s['valid'][i]=False;b['reset_reason'][i]=4;b['reset_reason'][i+1]=1
        elif scenario=='最良価格欠測':
            b['bid'][i]=b['mid'][i]=np.nan;b['valid'][i]=s['valid'][i]=False;b['reset_reason'][i]=4;b['reset_reason'][i+1]=1
        elif scenario=='幅異常':b['ask'][i]=b['bid'][i]+3.*r['tick'];b['mid'][i]=(b['bid'][i]+b['ask'][i])/2.
        elif scenario=='原行gap':r['seq'][i:]+=1;b['seq']=r['seq'].copy();b['reset_reason'][i]=2
        elif scenario=='旧clock逆行旗':b['reset_reason'][i]=8
        b['reset']=b['reset_reason']!=0
        result=core.market_features(grid,1,r,b,s)
        strict=old.board.market_features(grid,1,r,b,s,windows=(15,30))
        q_count=same(result['q_current'],strict['current'])+same(result['flow'],strict['windows'])
        relaxed=scenario in ('遠方数量不正','深板価格順不正','出来高reset')
        if relaxed:
            same(result['windows'],base['windows']);same(result['ranges'],base['ranges'])
            assert result['price_quality']['valid'][i] and not result['price_quality']['reset'][i]
            assert not result['price_quality']['reset'][i+1]
            at=np.flatnonzero(result['current']['index']==i)
            if len(at):assert not result['current']['q_valid'][at].any()
        else:
            assert not result['price_quality']['valid'][i] or result['price_quality']['reset'][i]
            impacted=(grid>ready['time_s'][i]+2)&(grid<ready['time_s'][i]+300)
            assert not result['windows'][300]['source_valid'][impacted].any()
            restored=grid>ready['time_s'][i]+340
            assert result['windows'][300]['source_valid'][restored].all()
            assert np.isfinite(result['windows'][300]['efficiency'][restored]).all()
        variants.append(dict(ケース=scenario,価格継続=relaxed,後続正常全窓復帰=True,旧QFlow全列一致=q_count))
    # ----------------------------------------
    # 代理時計そのものが逆行した入力を並べ替えず拒否する。
    bad={k:v.copy() if isinstance(v,np.ndarray) else v for k,v in ready.items()};bad['time_s'][1800]-=20
    rejected=False
    try:core.market_features(grid,1,bad,book,snap)
    except AssertionError:rejected=True
    assert rejected
    # ----------------------------------------
    # 最新同時計先頭が不正なら後続又は古い正常行へ救済しない。
    qbook={k:v.copy() if isinstance(v,np.ndarray) else v for k,v in book.items()}
    qsnap={k:v.copy() if isinstance(v,np.ndarray) else v for k,v in snap.items()}
    qbook['valid'][1800]=qsnap['valid'][1800]=False;qbook['reset_reason'][1800]=4;qbook['reset']=qbook['reset_reason']!=0
    q=core.market_features(np.array([902.]),1,ready,qbook,qsnap)
    assert q['current']['index'][0]==1800 and q['q_current']['index'][0]==-1
    assert not q['current']['q_valid'][0] and np.isnan(q['current']['best_imbalance'][0])
    invalid={k:v.copy() if isinstance(v,np.ndarray) else v for k,v in book.items()};invalid['bid_qty'][1800]=0
    invalid['valid'][1800]=False;invalid['reset_reason'][1800]=4;invalid['reset']=invalid['reset_reason']!=0
    no_rescue=core.price_features(np.array([902.]),1,ready,invalid)
    assert no_rescue['current']['index'][0]==-1
    flat={k:v.copy() if isinstance(v,np.ndarray) else v for k,v in book.items()}
    flat['bid'][:]=100.;flat['ask'][:]=100.5;flat['mid'][:]=100.25;flat['last'][:]=100.25
    zero=core.price_features(grid,1,ready,flat)
    assert zero['windows'][300]['source_valid'].all() and zero['windows'][300]['zero_variation'].all()
    assert np.isnan(zero['windows'][300]['efficiency']).all()
    prefixes=poisons=0
    for delay in (1,5,15):
        full=core.market_features(grid,delay,ready,book,snap)
        for stop in (1300,1801,2200,2701):
            past=grid-delay<ready['time_s'][stop-1]
            actual=core.market_features(grid[past],delay,narrowed(ready,stop,len(ready['seq'])),narrowed(book,stop,len(ready['seq'])),narrowed(snap,stop,len(ready['seq'])))
            expected={k:{field:{name:arr[past] for name,arr in values.items()} for field,values in full[k].items()} if k in ('windows','ranges','flow') else {name:arr[past] for name,arr in full[k].items()} for k in ('current','q_current','windows','ranges','flow')}
            prefixes+=same(actual,expected)
            b={k:v.copy() if isinstance(v,np.ndarray) else v for k,v in book.items()};s={k:v.copy() if isinstance(v,np.ndarray) else v for k,v in snap.items()}
            for name in ('bid','ask','mid','last','bid_qty','ask_qty','best_ofi'):b[name][stop:]+=5000.
            s['valid'][stop:]=False;b['valid'][stop:]=False;b['reset_reason'][stop:]=4;b['reset'][stop:]=True
            changed=core.market_features(grid[past],delay,ready,b,s)
            poisons+=same(changed,expected)
    # ----------------------------------------
    # LPは正常clockの価格不正を保持し、板だけの不正を参照しない。
    origin=datetime(2026,10,12,8,45,tzinfo=timezone(timedelta(hours=9)));start=origin.timestamp();end=start+1500.
    rows=[]
    for seq in range(3000):
        stamp=origin+timedelta(seconds=seq//2)
        rows.append((seq,dict(CurrentPriceTime=stamp.isoformat(),CurrentPrice=100.+(seq//2%37)*.25+(seq%2)*.125,
                              Buy1=dict(Price=None,Qty=-1),TradingVolume=-100.)))
    record=lp.extract_last_prices(rows,start,end);assert record['valid'].all() and np.array_equal(record['seq'],np.arange(3000))
    lp_grid=start+grid;full=lp.last_price_features(lp_grid,1,record)
    first=np.flatnonzero(np.r_[True,np.diff(record['time_s'])!=0])
    assert set(full['current']['index'][full['current']['valid']]).issubset(set(first))
    assert (full['current']['time_s'][full['current']['valid']]<(lp_grid-1)[full['current']['valid']]).all()
    assert 'flow' not in full and 'q_current' not in full and 'bid' not in full['current']
    outside_rows=[(0,dict(CurrentPriceTime=(origin-timedelta(seconds=1)).isoformat(),CurrentPrice=700.)),
                   (1,dict(CurrentPriceTime=origin.isoformat(),CurrentPrice=101.)),
                   (2,dict(CurrentPriceTime=(origin+timedelta(seconds=1)).isoformat(),CurrentPrice=102.)),
                   (3,dict(CurrentPriceTime=(origin+timedelta(seconds=1500)).isoformat(),CurrentPrice=900.))]
    outside_record=lp.extract_last_prices(outside_rows,start,end)
    assert np.array_equal(outside_record['seq'],[1,2]) and outside_record['diagnostic']['場外']==2
    assert outside_record['reset'][0] and outside_record['last'][0]==101.
    lp_checks=[]
    for scenario in ('LP欠測','clock欠測','clocktimezone欠測','原本未読gap'):
        changed=[(seq,dict(raw)) for seq,raw in rows]
        if scenario=='LP欠測':changed[1800][1]['CurrentPrice']=None
        elif scenario=='clock欠測':changed[1800][1]['CurrentPriceTime']=None
        elif scenario=='clocktimezone欠測':changed[1800][1]['CurrentPriceTime']='2026-10-12T09:00:00'
        else:del changed[1800]
        r=lp.extract_last_prices(changed,start,end);result=lp.last_price_features(lp_grid,1,r)
        affected=(grid>902)&(grid<1200);assert not result['windows'][300]['source_valid'][affected].any()
        restored=grid>1240;assert result['windows'][300]['source_valid'][restored].all()
        if scenario=='LP欠測':assert len(r['seq'])==3000 and not r['valid'][1800]
        else:assert np.any((r['seq']==1801)&r['reset'])
        lp_checks.append(dict(ケース=scenario,不明を補完なし=True,窓断裂と後続復帰=True))
    reversed_rows=[(seq,dict(raw)) for seq,raw in rows];reversed_rows[1800][1]['CurrentPriceTime']=origin.isoformat()
    clock_rejected=False
    try:lp.extract_last_prices(reversed_rows,start,end)
    except AssertionError:clock_rejected=True
    assert clock_rejected
    lp_prefix=lp_poison=0
    for stop in (1300,1801,2200,2701):
        past=lp_grid-1<record['time_s'][stop-1]
        r=lp.extract_last_prices(rows[:stop],start,end);actual=lp.last_price_features(lp_grid[past],1,r)
        expected=dict(source_kind=full['source_kind'],current={k:v[past] for k,v in full['current'].items()},
                      windows={k:{f:v[past] for f,v in w.items()} for k,w in full['windows'].items()},
                      ranges={k:{f:v[past] for f,v in w.items()} for k,w in full['ranges'].items()})
        lp_prefix+=same(actual,expected)
        changed=[(seq,dict(raw)) for seq,raw in rows]
        for seq in range(stop,len(changed)):changed[seq][1]['CurrentPrice']=50000.+seq
        changed_record=lp.extract_last_prices(changed,start,end)
        lp_poison+=same(lp.last_price_features(lp_grid[past],1,changed_record),expected)
    inputs=[ROOT/'work/wave_v76/inputs/core.py',ROOT/'work/wave_v77/inputs/core.py',HERE/'strict_board.py',HERE/'core.py',HERE/'last_price.py',Path(__file__)]
    proof=dict(全人工合格=True,段階='設計と人工のみ。全62新素材生成及び売買計算なし。',正常対照=normal,
               価格資格の正負ケース=variants,価格時計逆行を拒否=True,価格未来切断比較配列数=prefixes,
               価格未来変形比較配列数=poisons,LP正負ケース=lp_checks,LP時計逆行を拒否=True,
               LP未来切断比較配列数=lp_prefix,LP未来変形比較配列数=lp_poison,
               価格資格に旧Qを混ぜない=True,Qと価格の別源を明示=True,同時計先頭不正の救済禁止=True,
               有効平坦窓のERをゼロへ代用しない=True,LP場前場後の価格を持込まない=True,
               旧module_import=0,旧領域書込み=0,全62素材生成=0,売買計算=0,現在API取得=0,実注文=0,
               SHA256={str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs})
    (HERE/'価格資格と原LPの人工正負及び未来不変.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(proof,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
