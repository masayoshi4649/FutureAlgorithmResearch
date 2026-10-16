"""保存原板を未来で切断し、再参加判定と取引が過去だけで確定することを監査する。"""

import hashlib
import pickle
import sys
import numpy as np
from boundaries import load, module
from diagnose import ROOT, HERE, save
from support import clip, compare_prefix


def hashes():
    """
    機能: 再参加実装の全ソース指紋を保存する。
    引数: なし。
    返り値: dict[str,str]。
    """
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((ROOT/'work/wave_v87/round1').glob('*.py'))}


def event_rules(result,ready,config):
    """
    機能: 再参加証跡から公開元・前保有極値・新準備・消費の条件を独立照合する。
    引数: result/ready/config (dict)。
    返り値: intの確認イベント数。
    """
    events=result['restart_events'];seen=set();count=0
    for e in events:
        i,kind,previous,side=int(e[0]),int(e[1]),int(e[2]),int(e[3])
        assert previous<=i and e[6]<=i and e[7]<=i
        if kind==1:
            cycle=next(c for c in result['cycles'] if int(c[2])==i)
            start=int(cycle[1]);path=ready['last'][start:i+1]
            extreme=np.nanmax(path) if side>0 else np.nanmin(path)
            assert e[4]==extreme
        elif kind==2:
            assert e[5]==i and e[6]>previous and e[7]>previous and i>previous
            seen.add(previous)
        elif kind==3 and e[8]==side:
            if config['reentry_filter'] & 1:
                assert previous in seen and e[5]>=0 and e[6]>previous and e[7]>previous
            if config['reentry_filter'] & 2:
                assert side*(e[9]-(e[4]+side*ready['tick']))>=-1e-8
        elif kind==4:
            assert i>previous
        count+=1
    return count


def main():
    """
    機能: 日夜両商品・両約定モデルで再参加3機構の過去配列を独立検査する。
    引数: なし。
    返り値: None。全場成績や新条件の選抜を行わない。
    """
    strategy,configs=load();before=hashes()
    sessions=('2026-09-25_Day','2026-09-28_Night')
    inputs=pickle.loads((ROOT/'work/wave_v67/prepared/old23/new_inputs.pkl').read_bytes())
    inputs={k:v for k,v in inputs.items() if k[0] in sessions}
    signals=pickle.loads((ROOT/'work/wave_v67/prepared/old23/signals.pkl').read_bytes())
    signals={name:{k:v for k,v in values.items() if k in inputs} for name,values in signals.items()}
    features=strategy.initialize(inputs,signals)
    import numba
    numba.config.CACHE_DIR=str(HERE/'cache')
    records=[]
    for key in sorted(inputs):
        ready=inputs[key];feature=features[key];n=len(ready['last'])
        for observed in (False,True):
            for ident in ('R1_S75','R2_S50','R3_S25'):
                full,_=strategy.play(configs[ident],ready,feature,observed=observed)
                verified=event_rules(full,ready,configs[ident])
                cuts={int(n*.37),int(n*.78)}
                for kind in (1,2,3,4):
                    events=full['restart_events'];selected=events[events[:,1]==kind]
                    for event in selected[:2]:
                        i=int(event[0]);cuts.update((max(2,i),min(n-1,i+1),min(n-1,i+2)))
                checks=0
                for count in sorted(cuts):
                    part,_=strategy.play(configs[ident],clip(ready,count,n),clip(feature,count,n),observed=observed)
                    checks+=compare_prefix(full,part,count)
                    for name in ('profit_reentry_events','restart_events'):
                        a,b=full[name],part[name]
                        np.testing.assert_array_equal(a[a[:,0]<count],b[b[:,0]<count],err_msg=name)
                        checks+=1
                records.append(dict(セッション=key[0],商品=key[1],条件=ident,観測約定=observed,
                    切断地点=len(cuts),過去配列一致数=checks,再参加公開元と前組極値照合イベント数=verified,合格=True))
                print(key,ident,observed,len(cuts),checks,'一致',flush=True)
    assert before==hashes()
    save('再参加条件と初期止めの未来切断.json',dict(全合格=True,条件口座数=len(records),
        切断地点=sum(r['切断地点'] for r in records),配列一致数=sum(r['過去配列一致数'] for r in records),
        検査=records,実装SHA256=before,
        限界='既に因果生成された特徴も同じ地点で切断し、注文と極値保存が将来行を参照しないことを検査。EMA抽出器自体の因果性は旧v85の切断監査に依拠する。'))
    print('全合格',len(records),flush=True)


if __name__=='__main__':
    main()
