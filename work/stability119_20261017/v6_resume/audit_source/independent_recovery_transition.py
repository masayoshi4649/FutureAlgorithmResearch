"""場内staleと無効Last後の高水位差について、原44列のunknownを独立確認する。"""

from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path

import numpy as np

from independent_clock_contract import module,correction


def main() -> None:
    """
    機能: v1が誤って使用可能とした復帰直後を旧v2が抑止することを確認する。
    引数: なし。
    返り値: None。人工証跡のみ保存し原本・stage・金融は使用しない。
    """
    here=Path(__file__).resolve().parent;v6=here.parent;root=v6.parents[2];mirror=v6/'legacy_root'
    paths=[v6/'clock_adapter.py',mirror/'work/wave_v103/input/core.py',mirror/'work/wave_v103/input_v2/correction.py']
    sources={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    clock=module(paths[0],'_h_transition_clock');core=module(paths[1],'_h_transition_raw');correct=correction(paths[2])
    base=datetime(2026,10,14,4,tzinfo=timezone(timedelta(hours=9)));start=(base-timedelta(hours=11)).timestamp();end=(base+timedelta(hours=1,minutes=55)).timestamp()
    rows=[]
    for i,second in enumerate((-60,0,-1,0,1)):
        raw={'Symbol':'TEST','SymbolName':'人工','Exchange':2,'CurrentPriceTime':(base+timedelta(seconds=second)).isoformat(),'CurrentPrice':4000.,'TradingVolume':100+i,'TradingVolumeTime':(base-timedelta(seconds=60)).isoformat()}
        for level in range(1,11):
            raw['Buy'+str(level)]={'Price':4000.-level*.5,'Qty':10.};raw['Sell'+str(level)]={'Price':4000.+(level-1)*.5,'Qty':10.}
        rows.append(raw)
    view,reasons=clock.transform(rows,start,end)
    assert reasons==[0,0,8,0,0]
    raw,_=core.extract_rows(enumerate(rows),start,end)
    revised,_=correct(raw)
    assert raw['volume_delta_usable'][3] and not revised['volume_delta_usable'][3]
    assert not revised['volume_delta_usable'][2] and revised['price_reset_reason'][2]&8
    assert revised['volume_delta_usable'][4]
    # ----------------------------------------
    # Last無効の未来clockはh水位を汚さない一方、元44列側の保守的unknownは保持する。
    rows[1]['CurrentPrice']=None;rows[1]['CurrentPriceTime']=(base+timedelta(seconds=100)).isoformat()
    view,reasons=clock.transform(rows,start,end)
    assert reasons[1]==2 and reasons[2:]==[0,0,0]
    raw,_=core.extract_rows(enumerate(rows),start,end);revised,_=correct(raw)
    assert np.all((revised['price_reset_reason'][2:]&8)!=0)
    assert not np.any(revised['volume_delta_usable'][2:])
    assert revised['price_time_s'][1]==base.timestamp()+100
    assert revised['last_valid'][1]==False and np.isnan(revised['last'][1])
    assert sources=={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    proof={'全合格':True,'確認':['場内staleは理由8','元v1の復帰直後usableをv2で禁止','stale当行は出来高不適格','正常隣接後だけ復帰','無効Last未来clockはh水位不更新','原44側の高水位resetとunknownは保守的に保持','未来clockと欠測Lastの原観測を不変更'],'source_SHA256':sources,'原本読取':0,'stage本文読取':0,'金融':0,'登録':0}
    target=here/'場内stale復帰と無効Last後の出来高unknown補足.json';assert not target.exists()
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(hashlib.sha256(target.read_bytes()).hexdigest())


if __name__=='__main__':main()
