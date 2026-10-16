"""実金融を開かず、合成Native出力の金額・端点・RLEを監査器へ結ぶ。"""

from copy import deepcopy
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import traceback

import numpy as np

HERE=Path(__file__).resolve().parent
WORK=HERE.parents[1]
sys.path.insert(0,str(WORK))
import artificial
import catalog
import engine


def load(name: str,path: Path) -> object:
    """
    機能: 本実行部を呼ばず、新私有sourceの関数だけを読み込む。
    引数: name(str)、path(Path) は私有module名とsource。
    返り値: object はmodule。元金融結果・入力へアクセスしない。
    """
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def pack(a: np.ndarray) -> dict:
    """
    機能: 合成曲線を隣接全列同値で区切る独立RLEへ変換する。
    引数: a(ndarray) は合成全行曲線。
    返り値: dict は元形状と区間開始・値。finance.pyをimportしない。
    """
    keep=[0]
    for i in range(1,len(a)):
        if not np.all((a[i]==a[i-1])|(np.isnan(a[i])&np.isnan(a[i-1]))):keep.append(i)
    return dict(shape=a.shape,starts=np.asarray(keep,np.int64),values=a[keep].copy())


def diagnose(a: dict,out: dict,symbol: str) -> dict:
    """
    機能: 合成原行の全実脚BBOから金額分解とsnapshotを独立に作る。
    引数: a/out(dict)、symbol(str) は合成入力・出力・商品。
    返り値: dict はroot金融schemaの診断。未来の別成績を作らない。
    """
    def point(row: int) -> dict:
        """
        機能: 合成当行の必要原観測だけを保存形へ写す。
        引数: row(int) は原位置。
        返り値: dict は同位置のseq/clock/BBO/Qty。
        """
        return {k:a[k][row].item() for k in ('raw_seq','price_time_s','bid','ask','bid_qty','ask_qty')}
    breakdown=[];snapshots=[]
    for parent in out['parent']:
        cid=parent['parent'];legs=[l for l in out['actual_legs'] if l['parent']==cid]
        mid=Fraction();cross=Fraction();points=[]
        for l in legs:
            e,x=int(l['entry_row']),int(l['exit_row']);q=int(l['q']);side=int(l['side']);m=catalog.VALUE[symbol]
            mid+=Fraction(str(side*q*m))*((Fraction(str(a['bid'][x]))+Fraction(str(a['ask'][x])))-(Fraction(str(a['bid'][e]))+Fraction(str(a['ask'][e]))))/2
            cross+=Fraction(str(q*m))*((Fraction(str(a['ask'][x]))-Fraction(str(a['bid'][x])))+(Fraction(str(a['ask'][e]))-Fraction(str(a['bid'][e]))))/2
            points.append(dict(q=q,side=side,entry_row=e,exit_row=x,新規=point(e),返済=point(x)))
        breakdown.append(dict(parent=cid,uid=parent['uid'],中値差粗損益=float(mid),気配差負担=float(cross),手数料=parent['fee_yen'],収支=parent['net_yen'],legs=points))
        snapshots.append(dict(parent=cid,uid=parent['uid'],公開=point(parent['publication_row']),新規=point(parent['entry_row']),最終返済=point(parent['exit_row'])))
    return dict(中値差粗損益=sum(v['中値差粗損益'] for v in breakdown),気配差負担=sum(v['気配差負担'] for v in breakdown),
        手数料=out['summary']['費用'],収支=out['summary']['収支'],snapshots=snapshots,parent_breakdown=breakdown)


def main() -> None:
    """
    機能: 合成48口座・792枠schemaだけで金融監査器の保存接続を検査する。
    引数: なし。
    返り値: None。実financeディレクトリ・結果・台帳は開かない。
    """
    target=HERE/'合成Nativeと792枠schemaだけの監査器接続.json'
    assert not target.exists() and not (HERE/'純接続False.json').exists()
    check=load('実金融未読の私有監査器',HERE/'check.py')
    metrics=load('合成会計を生成する新指標',WORK/'metrics/metrics.py')
    source=check.sources();checks=0;count=0;cache={}
    try:
        for symbol in catalog.CAP:
            for side in (1,-1):
                for config in catalog.configs():
                    a,s,t,start,end,tick=artificial.fixture(symbol,side)
                    out=engine.simulate(a,s,symbol,start,end,tick,t,config)
                    session='2026-10-01_Day';row=metrics.account(symbol,session,out);row['case']=config['id']
                    d=diagnose(a,out,symbol)
                    pp=[dict(p,session=session,symbol=symbol,case=config['id']) for p in out['parent']]
                    ll=[dict(l,session=session,symbol=symbol,case=config['id']) for l in out['actual_legs']]
                    checks+=check.account(row,pp,ll,d)
                    kept={k:v for k,v in out.items() if k not in ('curve','price_valid_mask','execution_normal_mask')};kept['curve_rle']=pack(out['curve'])
                    kept['config']=dict(kept['config'],id=check.MAIN)
                    amount,n=check.ledger(kept,row,pp,ll,d);checks+=amount;count+=1
                    if side==1:cache[config['id'],symbol]=row,pp,ll,d
        sessions=[f'2026-10-{i//2+1:02d}_'+('Day' if i%2==0 else 'Night') for i in range(33)]
        data=dict(全合格=True,金融=True,configs=catalog.configs(),sessions=sessions,counts=dict(新金融口座=792),rows=[],parents=[],actual_legs=[],diagnostics=[],ledgers=[],aggregate={})
        for config in catalog.configs():
            cid=config['id'];rr=[];pp=[];ll=[];dd=[]
            for session in sessions:
                for symbol in catalog.CAP:
                    r,p,l,d=deepcopy(cache[cid,symbol])
                    r.update(session=session,symbol=symbol,case=cid)
                    for record in p+l:record.update(session=session,symbol=symbol,case=cid)
                    d.update(session=session,symbol=symbol,case=cid)
                    rr.append(r);pp+=p;ll+=l;dd.append(d)
                    data['ledgers'].append(dict(case=cid,session=session,symbol=symbol))
            data['rows']+=rr;data['parents']+=pp;data['actual_legs']+=ll;data['diagnostics']+=dd
            data['aggregate'][cid]={y:metrics.periods(rr,pp,sessions,y,ll) for y in catalog.CAP}
        amount,*_=check.audit_small(data);checks+=amount
        assert source==check.sources()
        proof=dict(全合格=True,source_SHA256=source,純接続sourceSHA256=check.sha(Path(__file__)),比較数=checks,
            合成Native口座=count,合成集計schema枠=792,実金融口座=0,実結果本文=0,実台帳=0,NPZ=0,cache=0,API=0,
            制約='合成の会計/保存schema確認。実115金融又は過去実績の追加証拠ではない。')
        target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps(dict(全合格=True,比較数=checks,合成Native口座=count,SHA256=check.sha(target)),ensure_ascii=False))
    except BaseException:
        (HERE/'純接続False.json').write_text(json.dumps(dict(全合格=False,source_SHA256=source,比較数=checks,
            原因=traceback.format_exc(),実金融=0,実結果=0,実台帳=0,NPZ=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise


if __name__=='__main__':
    main()
