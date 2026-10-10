"""独立枠監査の全設計人工ケースと、保存証拠の破損拒否を検査する。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
import urllib.request
import numpy as np

import adaptive_design as design
import adaptive_slot_audit as audit
import engine_audit as fixtures

HERE=Path(__file__).resolve().parent


def curves(ready: dict,result: dict) -> dict:
    """機能: 実台帳だけから現金・実現・買売数量を再構成する。

    引数: ready/result(dict)。返り値: 独立曲線(dict[str,ndarray])。
    """
    n=len(ready['last']);cash=np.zeros(n);long=np.zeros(n);short=np.zeros(n);realized=np.zeros(n)
    for row in result['orders']:
        i=int(row[0]);side,qty,price,opening=row[[3,4,5,7]];cash[i]-=side*qty*price
        position=side if opening else -side;change=qty if opening else -qty
        (long if position>0 else short)[i]+=change
    for row in result['trades']:realized[int(row[7])]+=row[2]*row[3]*(row[5]-row[4])
    cash=np.cumsum(cash);long=np.cumsum(long);short=np.cumsum(short);realized=np.cumsum(realized)
    return dict(cash=cash,long=long,short=short,realized=realized,equity=cash+(long-short)*ready['last'])


def fixture(spec: dict,symbol: str,quiet: bool=False) -> tuple:
    """機能: 条件の数量・遅延・分岐を活動又は無取引の人工入力へ適用する。

    引数: spec(dict)、symbol(str)、quiet(bool)。返り値: run引数とkeyword(tuple)。
    """
    args=list(fixtures.fixture([100,101,103,100,103,104,100,99,101,104,100,109,110,95],(2,6,10),(4,8),spacing=20.))
    args[2]=fixtures.helpers.config(symbol,args[0]);n=len(args[1])
    if quiet:args[1][:]=0
    if spec.get('bad_seed') is not None:args[3]*=1 if spec['bad_seed']%2 else -1
    if spec.get('good_seed') is not None:args[5]*=1 if spec['good_seed']%2 else -1
    kwargs=dict(good_valid=np.ones(n,np.bool_),budget_enabled=spec['budget_enabled'],
        min_delay_seconds=spec['min_delay_seconds'],observed_fill=spec['observed_fill'],
        branch_mode=spec['branch_mode'])
    if spec['branch_mode']!='fixed':
        kwargs.update(branch_direction=np.full(n,-1,np.int8),branch_source=np.arange(n,dtype=np.int64),
                      branch_valid=np.ones(n,np.bool_))
    if spec['branch_mode']=='random':
        kwargs.update(branch_seed=spec['branch_seed'],branch_choice=(np.arange(n)%2).astype(np.int8))
    return tuple(args),kwargs


def verify(args: tuple,spec: dict,kwargs: dict,result: dict) -> dict:
    """機能: 公開APIだけで独立枠・影計画検査へ接続する。

    引数: args(tuple)、spec/kwargs/result(dict)。返り値: 独立監査結果(dict)。
    """
    options=dict(kwargs);valid=options.pop('good_valid')
    return audit.audit(args[0],result,args[2],spec['policy'],*args[3:],valid,curves(args[0],result),state=args[1],**options)


def main() -> dict:
    """機能: 主全条件と補助全条件の人工検査・破損拒否を保存する。

    引数: なし。返り値: 監査要約(dict)。新実相場データを読まない。
    """
    socket.socket.connect=fixtures.reject;socket.create_connection=fixtures.reject;urllib.request.urlopen=fixtures.reject
    count=0
    for spec in design.catalog():
        for symbol in ('TOPIX','NK225'):
            for quiet in (False,True):
                args,kwargs=fixture(spec,symbol,quiet)
                result=fixtures.engine.run(*args,spec['policy'],**kwargs)
                verify(args,spec,kwargs,result);count+=1
    additional=0
    for spec in design.supplementary():
        args,kwargs=fixture(spec,'TOPIX');result=fixtures.engine.run(*args,spec['policy'],**kwargs)
        verify(args,spec,kwargs,result);additional+=1
    # ----------------------------------------
    # 各破損は単独に作り、元結果・入力を変更しない。
    target=next(s for s in design.catalog() if s['id']==design.PRIMARY_ID)
    args,kwargs=fixture(target,'TOPIX');result=fixtures.engine.run(*args,target['policy'],**kwargs)
    corruptions=[]
    def reject(name: str,field: str,index: tuple,value: float) -> None:
        """機能: 一箇所の記録破損を監査が拒否することを確認する。

        引数: name/field(str)、index(tuple)、value(float)。返り値: なし(None)。
        """
        broken=deepcopy(result);obj=broken
        parts=field.split('/')
        for part in parts[:-1]:obj=obj[part]
        obj[parts[-1]][index]=value
        try:verify(args,target,kwargs,broken)
        except (AssertionError,IndexError,ValueError):corruptions.append(name)
        else:raise AssertionError('破損を拒否しませんでした: '+name)
    reject('公開停止線変更','shadow/plans',(1,12),99.)
    reject('成熟元未来化','shadow/execution_plans',(2,33),2.)
    reject('成熟線無限値','shadow/execution_plans',(2,12),np.inf)
    reject('元注文価格変更','shadow/orders',(0,5),105.)
    reject('枠保有二重化','slot_curve',(3,0),3.)
    reject('分岐source未来化','branch_events',(0,5),999.)
    reject('分岐方式変更','branch_events',(0,3),2.)
    reject('分岐保持変更','branch_curve',(4,0),2.)
    reject('予算無視状態','control_curve',(2,13),1.)
    reject('予約保持改変','control_curve',(2,8),1.)
    reject('減量回数改変','adjustment_events',(0,9),99.)
    reject('同時行約定','slot_events',(0,1),1.)
    # 追加R無効なのに予約を残す対照も拒否する。
    repeat=next(s for s in design.catalog() if s['policy']['id']=='B00_T120_F25_N3' and s['variant_id']=='V000' and not s['budget_enabled'])
    ra,rk=fixture(repeat,'TOPIX');rr=fixtures.engine.run(*ra,repeat['policy'],**rk)
    rr['budget_events']=np.asarray([[2,0,1,2,20,-20,0,0]],float)
    try:verify(ra,repeat,rk,rr)
    except (AssertionError,IndexError,ValueError):corruptions.append('R無効で追加予約')
    else:raise AssertionError('R無効の追加予約を拒否しませんでした')
    record=dict(全合格=True,主人工数=count,補助人工数=additional,破損拒否数=len(corruptions),破損拒否=corruptions,
        新実相場損益=False,API取得数=0,
        SHA256={str(HERE/f):hashlib.sha256((HERE/f).read_bytes()).hexdigest() for f in
            ('adaptive_slot_audit.py','adaptive_shadow_oracle.py','adaptive_slot_selftest.py','engine_partial_restore.py','engine_shadow_plan.py')})
    (HERE/'adaptive_slot_selftest.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS',count,additional,len(corruptions),flush=True)
    return record


if __name__=='__main__':main()
