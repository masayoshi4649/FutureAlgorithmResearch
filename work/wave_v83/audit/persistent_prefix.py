"""指値保持の実原板を切断し、待機取消も含めて因果順を監査する。"""
from accounts import load,data
from context import *
from prefix import compare_prefix
from persistent_synthetic import persistent


def main() -> None:
    """機能: 固定3対照を原板再生し、未来変更の過去注文への影響を独立検査する。

    引数: なし。返り値: なし(None)。
    """
    inputs=data.load_data();base=WORK/'persistent'
    fixed=load(base/'固定条件.json')
    for name,h in fixed['実装SHA256'].items():assert digest(WORK/name)==h
    counts=dict(代表数=0,口座数=0,切断地点数=0,配列照合数=0,保有中切断=0,両建て中切断=0,予約中切断=0)
    detail=[]
    for name in fixed['対象']:
        packet=load(base/'results'/f'{name}.json');saved=load(base/'ledgers'/f'{name}.pkl');c=packet['config'];keys=set()
        for symbol in ['TOPIX','NK225']:
            rows=[r for r in packet['rows'] if r['symbol']==symbol]
            for sorting in [lambda r:r['orders'],lambda r:r['net'],lambda r:-r['net'],lambda r:r['cancellations']]:
                selected=max(rows,key=sorting);keys.add((selected['session'],symbol))
        for key in sorted(keys):
            raw=data.as_tuple(inputs[key]);args=arguments(raw,c['family'],c['width_ticks'],c['variant'],key[1])
            full=persistent.run(*args);old=saved[key]
            for part,column in [(0,'orders'),(1,'trades'),(3,'stats'),(4,'events')]:
                np.testing.assert_array_equal(full[part],old[column])
            assert hashlib.sha256(full[2].tobytes()).hexdigest()==old['curve_hash']
            n=len(raw[0]);locations={max(1,n//3),max(1,2*n//3)}
            pending=full[4][full[4][:,3]==1]
            for e in np.r_[pending[:3],pending[-2:]]:locations.add(int(e[0])+1)
            cancels=full[4][full[4][:,3]==6]
            for e in np.r_[cancels[:2],cancels[-1:]]:locations.update([int(e[0]),int(e[0])+1])
            for o in np.r_[full[0][:3],full[0][-2:]]:
                locations.update([int(o[0]),int(o[0])+1,int(o[1])+1])
                if o[6] and o[0]>o[1]:locations.add(int((o[0]+o[1])//2))
            local=0
            for cut in sorted(v for v in locations if 0<v<n):
                short=tuple(v[:cut] if i<8 else v for i,v in enumerate(raw))
                before=persistent.run(*arguments(short,c['family'],c['width_ticks'],c['variant'],key[1]))
                counts['配列照合数']+=compare_prefix(full,before,cut,raw[0][cut-1])
                future=list(raw)
                for column in [1,2,3]:
                    future[column]=raw[column].copy();future[column][cut:]+=raw[8]*1000.
                changed=persistent.run(*arguments(tuple(future),c['family'],c['width_ticks'],c['variant'],key[1]))
                counts['配列照合数']+=compare_prefix(changed,before,cut,raw[0][cut-1])
                counts['切断地点数']+=1;local+=1
                counts['保有中切断']+=int(before[3][4]+before[3][5]>0)
                counts['両建て中切断']+=int(before[3][4]>0 and before[3][5]>0)
                counts['予約中切断']+=int(before[3][6]+before[3][7]>0)
            counts['口座数']+=1;detail.append(dict(ID=name,商品=key[1],セッション=key[0],切断数=local))
        counts['代表数']+=1;print(f'持続指値の未来切断 {name}',flush=True)
    result=dict(合格=True,**counts,各口座=detail,エンジンSHA256=digest(WORK/'persistent_engine.py'),
        制約='現在値時計と保存順の因果性を検査した。実受信順・取引所待ち順位の検証ではない。')
    save('持続指値の実原本未来切断監査.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='各口座'},ensure_ascii=False))


if __name__=='__main__':main()
