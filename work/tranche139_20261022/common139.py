"""複数追撃の固定条件、共通会計、原通知との接続を定義する。"""

import copy
import hashlib
import json
from pathlib import Path
import sys
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OLD=ROOT/'work/staged137_20261022'
PUBLIC=ROOT/'アルゴリズム調査/00139_複数追撃と早期参加の全体検証'
sys.path.insert(0,str(OLD))
from run137 import features129,phases
import engine139


def read(path):
    """
    機能: UTF-8資料を読み込む。
    引数: path(Path)は資料位置。
    返り値: dict/listは内容。
    """
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path,value):
    """
    機能: 検証証跡を新規作成する。
    引数: path(Path)、value(dict/list)は保存先と内容。
    返り値: None。既存結果は上書きしない。
    """
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False)


def ref(path):
    """
    機能: ファイル位置と内容指紋を取得する。
    引数: path(Path)は対象。
    返り値: dict[str,str]は相対パスとSHA256。
    """
    path=Path(path)
    with path.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
    return dict(path=path.relative_to(ROOT).as_posix(),sha256=sha)


def product(symbol):
    """
    機能: 商品別の既知倍率・手数料・観測価格の最低幅を取得する。
    引数: symbol(str)はNK225/TOPIX。
    返り値: dictは商品設定。両商品とも片方向上限10枚。
    """
    return dict(fee_tenths=385,multiplier=100.,risk_floor=20.) if symbol=='NK225' else dict(fee_tenths=418,multiplier=1000.,risk_floor=1.)


def base_config():
    """
    機能: 比較の共通条件を取得する。
    引数: なし。
    返り値: dictは初回2枚・三回追加の設定。
    """
    return dict(initial=2,adaptive=False,target=5,increments=[1,1,1],steps=[.25,.5,.75],fill_last=True,
        support_hold=15.,min_after_initial=30.,add_min_gap=0.,exit_activation=[0.,1.5],exit_width=[1.,1.,.75,.5],
        tighten_at=[0.,2.],tight_width=[1.,.5,.375,.25],stop_width=[0.],profit_take=0,
        recycle_rounds=0,cooldown=30.,recycle_step=.25,initial_wait=False,partial_allocation='total',source_style='親出口')


def configs():
    """
    機能: 段階・幅・支持・配分・初回待機・再追加の比較条件を金融前に固定する。
    引数: なし。
    返り値: list[dict]は46条件。変更因子を明示し、結果を見た後に閾値を足さない。
    """
    out=[]
    for quantity in (5,2):
        c=base_config();c.update(id=f'B{quantity}',name=f'{quantity}枚固定・元の出口',initial=quantity,increments=[],steps=[],exit_activation=[0.],tighten_at=[0.])
        out.append(c)
    for stem,adaptive in (('P',False),('C',True)):
        tests=[('00','一回追加・元出口',dict(increments=[3],steps=[.25],exit_activation=[0.],tighten_at=[0.])),
            ('01','三段追加・元出口',dict(exit_activation=[0.],tighten_at=[0.])),
            ('02','三段追加・同じ幅',dict(exit_width=[1.],tighten_at=[0.])),
            ('03','後の玉ほど狭幅',dict(tighten_at=[0.])),
            ('04','後の玉ほど狭幅＋伸びたら短縮',{}),
            ('05','全追撃を同じ幅で段階短縮',dict(exit_width=[1.],tight_width=[.5])),
            ('06','初回玉の途中利確を待つ',dict(initial_wait=True)),
            ('07','追撃間隔を広げる',dict(steps=[.5,1.,1.5])),
            ('08','追撃間隔を狭める',dict(steps=[.125,.25,.375])),
            ('09','支持5秒で追撃',dict(support_hold=5.)),
            ('10','支持30秒で追撃',dict(support_hold=30.)),
            ('11','追撃間に60秒空ける',dict(add_min_gap=60.)),
            ('12','初回1枚・追加4段',dict(initial=1,increments=[1,1,1,1],steps=[.25,.5,.75,1.])),
            ('13','最大10枚・2枚ずつ追撃',dict(target=10,increments=[2,2,2,2],steps=[.25,.5,.75,1.])),
            ('14','利益返済後に一度再追加',dict(recycle_rounds=1)),
            ('15','利益返済後に二度再追加',dict(recycle_rounds=2)),
            ('16','利益返済後に四度再追加',dict(recycle_rounds=4)),
            ('17','10枚運用で各追撃1枚だけ保護',dict(target=10,increments=[2,2,2,2],steps=[.25,.5,.75,1.],profit_take=1)),
            ('18','初回玉にも広い利益追尾',dict(exit_activation=[2.,1.5],exit_width=[1.5,1.,.75,.5],tighten_at=[3.,2.],tight_width=[.75,.5,.375,.25]))]
        for suffix,label,changes in tests:
            c=base_config();c.update(changes);c.update(id=stem+suffix,name=('時計配分' if adaptive else '2枚先行')+'／'+label,adaptive=adaptive);out.append(c)
        for stop in (1.,1.5,2.):
            c=base_config();c.update(id=stem+'N'+str(int(stop*10)),name=('時計配分' if adaptive else '2枚先行')+f'／自前出口・初回停止{stop:g}R',
                adaptive=adaptive,source_style='独立出口',stop_width=[stop,1.],exit_activation=[2.,1.5],
                exit_width=[1.5,1.,.75,.5],tighten_at=[3.,2.],tight_width=[.75,.5,.375,.25]);out.append(c)
    assert len(out)==46
    return out


def account(orders,times,quotes,label,scene,symbol):
    """
    機能: 全注文を商品別に会計し、親・玉UIDの費用後損益を集計する。
    引数: orders/times(ndarray)、quotes(dict)、label/scene/symbol(str)。
    返り値: dictは場・親・玉別損益、枚数、参入数。時価残玉は認めない。
    """
    settings=product(symbol);fee=settings['fee_tenths'];mult=settings['multiplier']
    parents={};tickets={};held={1:0,-1:0};maximum=entries=quantity=0
    for o in orders:
        i,d,cid,side,qty=map(int,o[:5]);new=int(o[7]);uid=int(o[8]);paid=int(o[9]);px=float(o[5])
        assert 0<=d<i<len(times) and side in (-1,1) and qty>0 and paid==qty*fee//10
        assert quotes['quote_valid'][i] and abs(px-(quotes['ask'][i] if side>0 else quotes['bid'][i]))<1e-7
        p=parents.setdefault(cid,dict(id=cid,gross=0.,fees=0.,side=side,entry=i,exit=i,legs={}))
        leg=p['legs'].setdefault(str(uid),dict(gross=0.,fees=0.,entries=0,quantity=0));key=(cid,uid)
        p['fees']+=paid;leg['fees']+=paid;p['exit']=i
        if new:
            assert key not in tickets;tickets[key]=[qty,px,side];held[side]+=qty;entries+=1;quantity+=qty
            leg['entries']+=1;leg['quantity']+=qty
        else:
            old=tickets[key];assert old[0]>=qty and old[2]==-side
            gain=old[2]*(px-old[1])*qty*mult;old[0]-=qty;held[-side]-=qty;p['gross']+=gain;leg['gross']+=gain
        assert all(0<=x<=10 for x in held.values());maximum=max(maximum,*held.values())
    assert not any(held.values()) and all(t[0]==0 for t in tickets.values())
    for p in parents.values():
        p['net']=p['gross']-p['fees']
        for leg in p['legs'].values():leg['net']=leg['gross']-leg['fees']
    gains=sum(p['net'] for p in parents.values() if p['net']>0);loss=-sum(p['net'] for p in parents.values() if p['net']<0)
    cash=float(np.sum(-orders[:,3]*orders[:,4]*orders[:,5]*mult-orders[:,9])) if len(orders) else 0.
    assert abs(gains-loss-cash)<1e-5
    return dict(method=label,session=scene,kind=scene.split('_')[1],symbol=symbol,profit=gains,loss=loss,net=gains-loss,
        gross=sum(p['gross'] for p in parents.values()),fees=sum(p['fees'] for p in parents.values()),
        entries=entries,quantity=quantity,max_per_side=maximum,parents=list(parents.values()))


def supplemental(original,symbol):
    """
    機能: 既存補完注文をmini数量とUID形式に写す。
    引数: original(ndarray)、symbol(str)は元補完と商品。
    返り値: ndarrayは十列注文。TOPIXの元数量は半減しない。
    """
    parts=[];fee=product(symbol)['fee_tenths']
    for pid in np.unique(original[:,2]) if len(original) else []:
        rows=original[original[:,2]==pid];full=int(rows[0,4]);qty=max(1,full//2) if symbol=='NK225' else full
        held=qty;virtual=full
        for o in rows:
            if o[7]:take=qty
            else:
                virtual-=int(o[4]);remain=int(np.floor(qty*virtual/full+.5));take=held-remain;held=remain
            if take:parts.append([o[0],o[1],pid+10000,o[3],take,o[5],o[6],o[7],999,take*fee//10])
        assert held==0
    return np.asarray(parts,dtype=float).reshape(-1,10)


def force_parent(first,times,quotes,end):
    """
    機能: 因果的な入口と予定時刻の強制返済だけを独立出口へ渡す。
    引数: first(ndarray)は入口通知、times(ndarray)、quotes(dict)、end(float)は予定時刻。
    返り値: ndarrayは二行の元通知。終端気配はその行に到達するまで判断に使わない。
    """
    decision=int(np.searchsorted(times,end,side='left'));normal=np.flatnonzero(quotes['quote_valid'] & np.isfinite(quotes['bid']) & np.isfinite(quotes['ask']) & (quotes['bid']>0) & (quotes['bid']<quotes['ask']))
    k=np.searchsorted(normal,decision,side='right');assert k<len(normal),'予定終端後の約定気配が不足'
    fill=int(normal[k]);side=-int(first[3]);last=np.zeros_like(first)
    last[:8]=[fill,decision,first[2],side,first[4],quotes['ask'][fill] if side>0 else quotes['bid'][fill],1399.,0.]
    assert fill>decision>first[0]
    return np.vstack((first,last))


def replay(ready,quotes,market,clock,core,extra,config,symbol):
    """
    機能: 元親又は独立出口を運用し、先行保有中の後続新規を見送る。
    引数: ready/quotes/config(dict)、market/clock/core/extra(ndarray)、symbol(str)。
    返り値: tuple[ndarray,list[dict]]は全約定と保有中に見送った親。
    """
    c=copy.deepcopy(config);c.update(product(symbol));ts=ready['time_s'];candidates=[]
    for pid in np.unique(core[:,2]) if len(core) else []:
        rows=core[core[:,2]==pid];candidates.append((int(rows[0,0]),'主担当',rows))
    oldextra=supplemental(extra,symbol)
    for pid in np.unique(oldextra[:,2]) if len(oldextra) else []:
        rows=oldextra[oldextra[:,2]==pid];candidates.append((int(rows[0,0]),'補完',rows))
    output=[];skipped=[];last=-1
    for i,kind,rows in sorted(candidates,key=lambda x:x[0]):
        if int(rows[0,1])<last:
            skipped.append(dict(parent=int(rows[0,2]),kind=kind,entry=i,decision=int(rows[0,1]),active_until=last));continue
        if kind=='補完':result=rows
        else:
            source=force_parent(rows[0],ts,quotes,ready['limit']) if c['source_style']=='独立出口' else rows
            result=engine139.replay(ts,quotes,ready['atr'],market,clock,source,c)
        if len(result):last=int(result[-1,0]);output.append(result)
    orders=np.concatenate(output) if output else np.empty((0,10))
    return orders[np.argsort(orders[:,0],kind='stable')] if len(orders) else orders,skipped
