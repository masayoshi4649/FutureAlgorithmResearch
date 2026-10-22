"""日付を推定しない高水位資格の因果性と原seq保持を合成だけで確認する。"""

from copy import deepcopy
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import tempfile

import clock_adapter as clock


def run() -> None:
    """
    機能: stale・同clock・無効Last・場外・未来suffixを最小合成で検査する。
    引数: なし。
    返り値: None。原市場・stage本文・金融は読まない。
    """
    base=datetime(2026,10,14,4,0,tzinfo=timezone(timedelta(hours=9)))
    start=(base-timedelta(hours=11)).timestamp();end=(base+timedelta(hours=1,minutes=55)).timestamp()
    row=dict(CurrentPrice=4000.,CurrentPriceTime=base.isoformat(),TradingVolume=100,
        TradingVolumeTime=base.isoformat(),Buy1=dict(Price=3999.5,Qty=10),Sell1=dict(Price=4000.,Qty=20))
    rows=[deepcopy(row) for _ in range(9)]
    offsets=[0,0,-86400, -86340,-1,0,1,2,3]
    for raw,seconds in zip(rows,offsets):raw['CurrentPriceTime']=(base+timedelta(seconds=seconds)).isoformat()
    outputs,reasons=clock.transform(rows,start,end)
    assert reasons==[0,0,12,12,8,0,0,0,0]
    count=1
    for i,(raw,out,reason) in enumerate(zip(rows,outputs,reasons)):
        assert raw['CurrentPriceTime'] is not None
        assert out['CurrentPriceTime']==(None if reason else raw['CurrentPriceTime'])
        assert {k:v for k,v in out.items() if k!='CurrentPriceTime'}=={k:v for k,v in raw.items() if k!='CurrentPriceTime'}
        count+=3
    for cut in range(1,len(rows)+1):
        p,r=clock.transform(rows[:cut],start,end)
        assert p==outputs[:cut] and r==reasons[:cut]
        changed=deepcopy(rows)
        for raw in changed[cut:]:raw['CurrentPriceTime']=(base+timedelta(days=100)).isoformat()
        assert clock.transform(changed,start,end)[0][:cut]==outputs[:cut]
        count+=2
    unknowns=[None,'不正時計',base.replace(tzinfo=None).isoformat()]
    for stamp in unknowns:
        raw=dict(row,CurrentPriceTime=stamp)
        out,water,reason=clock.step(raw,base.timestamp(),start,end)
        assert reason&1 and water==base.timestamp() and out['CurrentPriceTime'] is None
        count+=1
    for last in (None,0.,-1.,True,float('nan'),float('inf')):
        raw=dict(row,CurrentPrice=last,CurrentPriceTime=(base+timedelta(days=1)).isoformat())
        _,water,reason=clock.step(raw,base.timestamp(),start,end)
        assert reason&2 and water==base.timestamp()
        count+=1
    high=float('-inf')
    out,high,reason=clock.step(dict(row,CurrentPriceTime=datetime.fromtimestamp(end,tz=base.tzinfo).isoformat()),high,start,end)
    assert reason&4 and high==float('-inf')
    _,high,reason=clock.step(row,high,start,end)
    assert reason==0 and high==base.timestamp()
    count+=2
    with tempfile.TemporaryDirectory(prefix='人工CSV_',dir=Path(__file__).resolve().parent) as folder:
        path=Path(folder)/'人工.csv'
        stamps=[base.isoformat(),(base+timedelta(minutes=1)).isoformat()]
        path.write_text('time,close\n'+'\n'.join(t+',4000' for t in stamps)+'\n',encoding='utf8')
        assert clock.validate_csv(path,start,end)['rows']==2;count+=1
        cases=[['不明'],[stamps[0],stamps[0]],stamps[::-1],
               [(base-timedelta(days=1)).isoformat()],[(base+timedelta(days=1)).isoformat()],[]]
        for sequence in cases:
            path.write_text('time,close\n'+'\n'.join(t+',4000' for t in sequence)+'\n',encoding='utf8')
            rejected=False
            try:clock.validate_csv(path,start,end)
            except AssertionError:rejected=True
            assert rejected;count+=1
    here=Path(__file__).resolve().parent
    paths=[here/'clock_adapter.py',here/'artificial_clock.py']
    proof=dict(全合格=True,確認項目=count,source_SHA256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        原市場本文読取=0,stage本文読取=0,金融=0,登録=0,
        留保='不適格表示は真時刻の復元ではない。旧33無修正保存引用と追加七場の入力資格差を明記する。')
    target=here/'原時計と原seqを保持する高水位資格の純人工.json'
    assert not target.exists();target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(f'高水位入力資格 {count}合成確認。本文/金融/登録0。',flush=True)


if __name__=='__main__':run()
