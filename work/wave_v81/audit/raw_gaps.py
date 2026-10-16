"""既存準備行の間から除外された原本行を読み、方向履歴を切る根拠を確認する。"""

from collections import Counter
from datetime import datetime
import json
import math
from pathlib import Path
import pickle

import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def load_inputs() -> tuple:
    """機能: 売買損益を読まず、既存の原本対応配列のみ読み込む。

    引数: なし。返り値: 原価格・旧特徴(dict,dict)。
    """
    meta=json.loads((ROOT/'work/wave_v77/inputs/metadata.json').read_text(encoding='utf8'))
    ready={};books={}
    for kind,dest,extra in [('ready',ready,'extra_inputs.pkl'),('features',books,'extra_features.pkl')]:
        for filename in meta['input_paths'][kind]:
            with (ROOT/filename).open('rb') as stream:dest.update(pickle.load(stream))
        with (ROOT/'work/wave_v77/inputs'/extra).open('rb') as stream:dest.update(pickle.load(stream))
    return ready,books


def classify(raw: dict, start: float, end: float) -> tuple:
    """機能: 除外行の時計・最良気配・数量だけを順に判定する。

    引数: raw(dict)、start/end(float)。返り値: 理由と具体値(tuple)。
    """
    text=raw.get('CurrentPriceTime')
    if not text:return '時計欠測',None
    try:stamp=datetime.fromisoformat(text).timestamp()
    except (TypeError,ValueError):return '時計不正',text
    if stamp<start or stamp>=end:return '場外時計',text
    try:bid,ask,bq,aq=[float(x) for x in (raw['Buy1']['Price'],raw['Sell1']['Price'],raw['Buy1']['Qty'],raw['Sell1']['Qty'])]
    except (KeyError,TypeError,ValueError):return '最良値欠測',None
    values=[bid,ask,bq,aq]
    if not all(math.isfinite(x) for x in values) or min(bid,ask)<=0:return '最良値不正',values
    if bid==ask:return '売買同値',values
    if bid>ask:return '売買逆転',values
    if min(bq,aq)<=0:return '最良数量不正',values
    return '最良正常だが除外',values


def main() -> None:
    """機能: 全60口座の内部欠落行を原本で分類し、結果だけ監査範囲へ保存する。

    引数: なし。返り値: なし(None)。売買損益・ネットワークは参照しない。
    """
    ready,books=load_inputs();details=[];totals=Counter();examples={}
    for key,r in sorted(ready.items()):
        seq=r['seq'];jumps=np.flatnonzero(np.diff(seq)>1)
        wanted={i for j in jumps for i in range(int(seq[j])+1,int(seq[j+1]))}
        counts=Counter();seen=0
        if wanted:
            last=max(wanted);path=ROOT/'book'/key[1]/f'{key[0]}.jsonl'
            with path.open('rb') as stream:
                for i,line in enumerate(stream):
                    if i>last:break
                    if i not in wanted:continue
                    raw=json.loads(line);reason,values=classify(raw,float(r['time_s'][0]),float(r['time_s'][-1])+1.)
                    counts[reason]+=1;seen+=1
                    if len(examples.setdefault(reason,[]))<5:
                        examples[reason].append(dict(session=key[0],symbol=key[1],seq=i,time=raw.get('CurrentPriceTime'),values=values))
        assert seen==len(wanted)
        counts['内部欠落行']=seen;counts['行飛び回数']=len(jumps)
        f=books[key]
        counts['旧reset行']=int(f['reset'].sum())
        if 'reset_reason' in f:
            for bit,name in [(1,'初期比較なし'),(2,'原本行不連続'),(4,'不正10段'),(8,'時計逆行'),(16,'出来高減少')]:
                counts['旧reset_'+name]=int(np.sum((f['reset_reason']&bit)!=0))
        totals.update(counts)
        details.append(dict(session=key[0],symbol=key[1],counts=dict(counts)))
        if len(details)%10==0:print(f'原本欠落監査 {len(details)}/60',flush=True)
    result=dict(全口座=len(details),売買損益閲覧=False,現在API取得=0,原本変更=False,合計=dict(totals),例=examples,口座別=details,
        解釈='最良無効行を飛び越すOFI差分は未知更新を1イベントへ押し込むため、再開行で比較元だけ置換する。価格方向は最後に観測した極値を保持し、再開後の実中値から判定する。観測されなかった途中極値は補完しない。')
    (HERE/'準備から除外された原本行の原因.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('口座別','例')},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
