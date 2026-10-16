"""反転後の原本切断・未来改変で、過去の注文と会計が変わらないことを調べる。"""

from context import *


def event_prefix(events: np.ndarray, cut: int, clock: float) -> np.ndarray:
    """機能: 行と論理発火時計の両方で未来イベントを除外する。

    引数: events(ndarray)、cut(int)、clock(float)。返り値: 既知イベント(ndarray)。
    """
    return events[(events[:,0]<cut)&(events[:,3]<=clock)]


def main() -> None:
    """機能: 全固定元逆ペアの遅延別に、注文待機と保有中を切断する。

    引数: なし。返り値: なし(None)。同時計後続行の改変も対象にする。
    """
    fixed=load(WORK/'事前固定.json');materials=research.previous.material()
    configs={c['id']:c for p in fixed['pairs'] for c in [p['original'],p['reverse']]}
    accounts=cuts=checks=holding=entrywait=exitwait=0;records=[]
    for delay in [0,1,5]:
        for config in configs.values():
            base=WORK/'final'/f'delay{delay}'
            packet=load(base/'results'/f'{config["id"]}.json')
            saved=load(base/'ledgers'/f'{config["id"]}.pkl');keys=set()
            for symbol in ['TOPIX','NK225']:
                rows=[r for r in packet['rows'] if r['symbol']==symbol]
                for sorting in [lambda r:r['trades'],lambda r:r['net'],lambda r:-r['net'],lambda r:r['cancellations']]:
                    r=max(rows,key=sorting);keys.add((r['session'],symbol))
            for key in sorted(keys):
                args=research.arguments(config,key,materials,delay)
                full=engine.simulate(*args);old=saved[key]
                for i,name in [(0,'orders'),(1,'trades'),(3,'stats'),(4,'events')]:
                    np.testing.assert_array_equal(full[i],old[name])
                assert hashlib.sha256(full[2].tobytes()).hexdigest()==old['curve_hash']
                times=args[0];n=len(times);locations={max(1,int(n*.43)),max(1,int(n*.79))}
                orders=full[0]
                for idx in np.r_[np.arange(min(4,len(orders))),np.arange(max(0,len(orders)-2),len(orders))]:
                    o=orders[idx];locations.update([int(o[1])+1,int(o[0]),int(o[0])+1])
                for event in full[4][np.isin(full[4][:,2],[21,24])][:3]:
                    row=int(np.searchsorted(times,event[3],side='left'))
                    locations.update([max(1,row),row+1])
                local=0
                for cut in sorted(c for c in locations if 0<c<n):
                    short=list(args)
                    for i in range(6):short[i]=args[i][:cut]
                    before=engine.simulate(*short)
                    np.testing.assert_array_equal(before[0],full[0][full[0][:,0]<cut])
                    np.testing.assert_array_equal(before[1],full[1][full[1][:,2]<cut])
                    np.testing.assert_array_equal(before[2],full[2][:cut])
                    np.testing.assert_array_equal(before[4],event_prefix(full[4],cut,times[cut-1]))
                    changed=list(args)
                    for i in [1,2]:
                        changed[i]=args[i].copy();changed[i][cut:]+=args[12]*1000.
                    for i in [7,26,32,33]:
                        changed[i]=args[i].copy();changed[i][cut:]*=-1
                    for i in [27,28,34,35]:
                        changed[i]=args[i].copy();changed[i][cut:]=~changed[i][cut:]
                    later=engine.simulate(*changed)
                    np.testing.assert_array_equal(later[0][later[0][:,0]<cut],before[0])
                    np.testing.assert_array_equal(later[1][later[1][:,2]<cut],before[1])
                    np.testing.assert_array_equal(later[2][:cut],before[2])
                    np.testing.assert_array_equal(event_prefix(later[4],cut,times[cut-1]),before[4])
                    cuts+=1;checks+=8;local+=1;holding+=int(before[3][0]!=0)
                    entrywait+=int(before[3][1]!=0);exitwait+=int(before[3][2]!=0)
                accounts+=1;records.append(dict(条件=config['id'],遅延秒=delay,商品=key[1],セッション=key[0],切断地点数=local))
            print(f'実注文未来監査 {delay}秒 {config["id"]}',flush=True)
    result=dict(合格=True,代表元逆条件数=len(configs),遅延水準数=3,実原本口座数=accounts,
        切断地点数=cuts,配列照合数=checks,保有中切断数=holding,新規待ち切断数=entrywait,返済待ち切断数=exitwait,
        全地点=records,事前固定SHA256=digest(WORK/'事前固定.json'),旧エンジンSHA256=digest(OLD/'engine.py'),
        注意='保存時計上の因果順のみ。CurrentPriceTimeの同時計行は真の受信時刻を保証しない。')
    save('全固定元逆ペアと三遅延の実注文未来監査.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='全地点'},ensure_ascii=False))


if __name__=='__main__':main()
