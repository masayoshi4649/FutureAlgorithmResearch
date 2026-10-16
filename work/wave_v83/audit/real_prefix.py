"""固定代表の実原板について、同一行即時約定の因果順を検証する。"""

from accounts import load,data
from context import *
from prefix import compare_prefix


def main() -> None:
    """機能: 実原本を切断し、未来価格を変えても既知の注文が変わらないか調べる。

    引数: なし。返り値: なし(None)。結果で代表を変える処理はしない。
    """
    inputs=data.load_data();selection=load(WORK/'前半選定.json');base=WORK/'final/delay0'
    counts=dict(代表数=0,口座数=0,切断地点数=0,配列照合数=0,保有中切断=0,両建て中切断=0,予約中切断=0)
    records=[]
    for name in selection['selected']:
        packet=load(base/'results'/f'{name}.json');saved=load(base/'ledgers'/f'{name}.pkl')
        c=packet['config'];keys=set()
        for symbol in ['TOPIX','NK225']:
            rows=[r for r in packet['rows'] if r['symbol']==symbol]
            for sorting in [lambda r:r['orders'],lambda r:r['net'],lambda r:-r['net'],lambda r:r['cancellations']]:
                r=max(rows,key=sorting);keys.add((r['session'],symbol))
        for key in sorted(keys):
            raw=data.as_tuple(inputs[key]);args=arguments(raw,c['family'],width=c['width_ticks'],variant=c['variant'],symbol=key[1])
            full=engine.run(*args);old=saved[key]
            for part,column in [(0,'orders'),(1,'trades'),(3,'stats'),(4,'events')]:
                np.testing.assert_array_equal(full[part],old[column])
            assert hashlib.sha256(full[2].tobytes()).hexdigest()==old['curve_hash']
            n=len(raw[0]);locations={max(1,n//3),max(1,2*n//3)}
            for o in np.r_[full[0][:3],full[0][-2:]]:
                locations.update([int(o[0]),int(o[0])+1,int(o[1])+1])
            for e in full[4][full[4][:,3]==3][:2]:locations.update([int(e[0]),int(e[0])+1])
            local=0
            for cut in sorted(v for v in locations if 0<v<n):
                short=tuple(v[:cut] if i<8 else v for i,v in enumerate(raw))
                before=engine.run(*arguments(short,c['family'],width=c['width_ticks'],variant=c['variant'],symbol=key[1]))
                counts['配列照合数']+=compare_prefix(full,before,cut,raw[0][cut-1])
                future=list(raw)
                for column in [1,2,3]:
                    future[column]=raw[column].copy();future[column][cut:]+=raw[8]*1000.
                changed=engine.run(*arguments(tuple(future),c['family'],width=c['width_ticks'],variant=c['variant'],symbol=key[1]))
                counts['配列照合数']+=compare_prefix(changed,before,cut,raw[0][cut-1])
                counts['切断地点数']+=1;local+=1
                counts['保有中切断']+=int(before[3][4]+before[3][5]>0)
                counts['両建て中切断']+=int(before[3][4]>0 and before[3][5]>0)
                counts['予約中切断']+=int(before[3][6]+before[3][7]>0)
            counts['口座数']+=1;records.append(dict(ID=name,商品=key[1],セッション=key[0],切断数=local))
        counts['代表数']+=1;print(f'実原本未来監査 {counts["代表数"]}/{len(selection["selected"])} {name}',flush=True)
    result=dict(合格=True,**counts,全地点=records,エンジンSHA256=digest(WORK/'engine.py'),
        制約='CurrentPriceTimeと保存順のモデル上の因果性。真の受信時刻や同時刻内の実経過を保証しない。')
    save('全代表の実原本未来切断監査.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='全地点'},ensure_ascii=False))


if __name__=='__main__':main()
