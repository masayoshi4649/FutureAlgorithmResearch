"""C00分岐地点のGo特徴と保存145特徴を比較する非金融診断。"""

from pathlib import Path
import json
import pickle
import numpy as np
from datetime import datetime
import argparse

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def main():
    """9月28日別入口の分岐直前を原行・時計・特徴の順で照合する。

    引数: なし。返り値: None。売買シグナルは生成しない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--scene',default='2026-09-28_Night');parser.add_argument('--tag',default='0928');args=parser.parse_args()
    _,data,_,_,_=pickle.loads((ROOT/'work/research145_engine/cache'/f'{args.scene}.pkl').read_bytes())
    old=data['features'];t=data['ready']['time_s'];found=[];counts=np.zeros(30,int);maxdiff=np.zeros(30,float)
    indices={int(seq):i for i,seq in enumerate(data['ready']['seq'])}
    accepted=[];previous=float(data['ready']['start'])
    rawpath=ROOT.parent/'JP_OSE_Data/future/NK225'/args.scene/'book.jsonl'
    for seq,line in enumerate(rawpath.open(encoding='utf-8')):
        b=json.loads(line)
        try:at=datetime.fromisoformat(b['CurrentPriceTime']).timestamp()
        except (TypeError,ValueError,KeyError):continue
        if at<data['ready']['start'] or at>data['ready']['start']+46800 or at<previous or not (b.get('CurrentPrice') or 0)>0:continue
        accepted.append(seq);previous=at
    added=[]
    for line in (HERE/f'engine特徴{args.tag}.jsonl').open(encoding='utf-8'):
        o=json.loads(line);seq=accepted[o['Index']]
        if seq not in indices:
            added.append(dict(index=o['Index'],seq=seq,time=o['Time'],bid=o['Bid'],ask=o['Ask'],quote=o['QuoteOK']))
            continue
        i=indices[seq];a=np.array(o['Research']['Values']);known=np.array(o['Research']['Known'])
        assert t[i]==o['Time'],(i,t[i],o['Time'])
        a[~known]=np.nan;b=old[i,:30]
        delta=np.isfinite(a)!=np.isfinite(b)
        both=np.isfinite(a)&np.isfinite(b);delta[both]|=np.abs(a[both]-b[both])>1e-7
        counts+=delta
        maxdiff[both]=np.maximum(maxdiff[both],np.abs(a[both]-b[both]))
        if delta[:24].any() or i in (86940,86941,86942):
            values=[]
            for col in np.flatnonzero(delta):
                values.append(dict(col=int(col),old=float(b[col]) if np.isfinite(b[col]) else None,current=float(a[col]) if np.isfinite(a[col]) else None))
            found.append(dict(index=i,time=o['Time'],differences=values,old24=[float(v) if np.isfinite(v) else None for v in b[:24]],current24=[float(v) if np.isfinite(v) else None for v in a[:24]]))
    result=dict(counts=counts.tolist(),max_abs=maxdiff.tolist(),differences=found,added_abnormal_rows=added,financial_replays=0)
    (HERE/f'engine特徴差{args.tag}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('差件数',counts.tolist(),'最大差',maxdiff.tolist(),'詳細',len(found))
    for row in found[-10:]:print(row['index'],row['time'],row['differences'])


if __name__=='__main__':main()
