"""一回取得後の台帳だけを読み、既知境界・追加区間・残玉を独立会計する。"""

import hashlib
import json
import pickle
from pathlib import Path

import numpy as np

HERE=Path(__file__).resolve().parent
LIVE=HERE.parent/'live'


def digest(path: Path) -> str:
    """機能: 保存された証跡の同一性を確認する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    h=hashlib.sha256()
    with path.open('rb') as f:
        while block:=f.read(4*1024*1024):h.update(block)
    return h.hexdigest()


def state(account: dict, branch: str, ready: dict, quote: dict, count: int) -> dict:
    """機能: 指定原本行までに約定した注文だけで費用・現金・残玉を別計算する。

    引数: account/ready/quote(dict)、branch(str)、count(int)。返り値: 境界の独立会計(dict)。
    """
    width=16 if branch=='directional' else 20
    orders=np.asarray(account['orders'],float).reshape(-1,width)
    value,fee=(1000.,418) if account['symbol']=='TOPIX' else (10.,110)
    position={};cash=fees=gross=0.
    if branch=='directional':
        fills=np.searchsorted(ready['seq'],orders[:,3]);decisions=np.searchsorted(ready['seq'],orders[:,2])
        side_col,qty_col,price_col,fee_col=5,6,7,9
    else:
        fills=orders[:,2].astype(int);decisions=orders[:,1].astype(int)
        side_col,qty_col,price_col,fee_col=10,11,12,13
    assert np.all(fills==decisions+1)
    mode=account['price_mode']
    prices=quote['mid'][fills] if mode=='mid' else np.where(orders[:,side_col]>0,quote['ask'][fills],quote['bid'][fills])
    np.testing.assert_array_equal(orders[:,price_col],prices)
    np.testing.assert_array_equal(orders[:,fee_col],orders[:,qty_col].astype(int)*fee//10)
    if branch=='inventory':trades=np.asarray(account['trades'],float).reshape(-1,23)
    for number,order in enumerate(orders):
        if fills[number]>=count:continue
        side,qty,price=int(order[side_col]),int(order[qty_col]),order[price_col]
        paid=order[fee_col];fees+=paid;cash-=side*qty*price*value+paid
        action=int(order[4] if branch=='directional' else order[9])
        if action!=2:
            position[number]=(side,qty,price)
        elif branch=='directional':
            assert sum(v[1] for v in position.values())==qty
            for s,q,p in position.values():gross+=s*q*(price-p)*value
            position={}
        else:
            selected=trades[trades[:,6]==order[0]]
            assert selected[:,4].sum()==qty
            for trade in selected:
                s,q,p=position.pop(int(trade[5]));gross+=s*q*(price-p)*value
    long=sum(q for s,q,p in position.values() if s>0)
    short=sum(q for s,q,p in position.values() if s<0)
    floating=0.;liquidation=cash
    if count:
        for side,qty,price in position.values():
            mark=quote['mid'][count-1] if mode=='mid' else quote['bid' if side>0 else 'ask'][count-1]
            floating+=side*qty*(mark-price)*value
            liquidation+=side*qty*mark*value
    assert abs(liquidation-(gross-fees+floating))<1e-5
    return dict(gross_realized=gross,fees=fees,cash=cash,unrealized=floating,net=liquidation,long_qty=long,short_qty=short,
                realized_after_incurred_fees=gross-fees)


def main() -> None:
    """機能: 保存済み8口座の全体・既知境界・追加区間を検算し、追加取得を行わない。

    引数: なし。返り値: なし(None)。保存資料を読むだけで売買の判断は再実行しない。
    """
    inputs=pickle.loads((LIVE/'inputs.pkl').read_bytes());quotes=pickle.loads((LIVE/'quotes.pkl').read_bytes())
    acquisition=json.loads((LIVE/'取得記録.json').read_text(encoding='utf-8'))
    assert len(acquisition['requests'])==3 and acquisition['全応答成功'] and not acquisition['再試行'] and acquisition['実注文']==0
    for request in acquisition['requests']:
        assert request['成功'] and request['status']==200
        assert (LIVE/request['file']).stat().st_size==request['bytes']
        if request['file'].endswith('.jsonl'):
            assert request['trailers']['X-History-Complete']==['true']
            assert request['headers']['X-History-Session-Id']==['2026-10-07_Night']
            old=HERE.parent.parent/'wave_v60/live'/request['file']
            with (LIVE/request['file']).open('rb') as f:
                prefix=hashlib.sha256(f.read(old.stat().st_size)).hexdigest()
            assert prefix==digest(old),'既知原本の前半バイトが一致しません'
    selection=json.loads((LIVE/'候補固定.json').read_text(encoding='utf-8'))
    before=json.loads((LIVE/'取得直前照合.json').read_text(encoding='utf-8'))
    assert digest(LIVE/'候補固定.json')==before['候補SHA']
    count=0;records=[]
    for branch,name in [('directional','現在方向性の途中損益.json'),('inventory','現在在庫の途中損益.json')]:
        result=json.loads((LIVE/name).read_text(encoding='utf-8'))
        assert selection['sources'][branch]==digest(HERE.parent/branch/'集計結果.json')
        for a in result['accounts']:
            key=(a['session'],a['symbol']);ready=inputs[key];quote=quotes[key]
            known=a['既知有効行数']
            states={field:state(a,branch,ready,quote,size) for field,size in [('セッション期首',0),('既知境界',known),('現在末尾',len(ready['seq']))]}
            for field,calculated in states.items():
                for metric,value in calculated.items():
                    assert abs(a[field][metric]-value)<1e-5,(branch,key,field,metric)
            for metric in ('gross_realized','fees','cash','unrealized','net','realized_after_incurred_fees'):
                expected=states['現在末尾'][metric]-states['既知境界'][metric]
                assert abs(a['追加区間'][metric]-expected)<1e-5,(branch,key,metric)
            assert abs(a['net']-states['現在末尾']['net'])<1e-5
            count+=1
            records.append(dict(枝=branch,銘柄=a['symbol'],価格=a['price_mode'],既知行数=known,
                追加行数=len(ready['seq'])-known,全体純益=states['現在末尾']['net'],追加区間純変化=a['追加区間']['net'],
                残買=states['現在末尾']['long_qty'],残売=states['現在末尾']['short_qty']))
    evidence=dict(合格=True,口座数=count,境界数=count*3,追加ネット取得=0,記録上の取得数=3,
                  共通取得上限=acquisition['共通to'],以前原本の前半SHA一致=True,保存台帳独立会計=True,
                  会計=records,資料SHA={name:digest(LIVE/name) for name in ['現在方向性の途中損益.json','現在在庫の途中損益.json','候補固定.json']})
    (HERE/'現在8口座の独立監査.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
