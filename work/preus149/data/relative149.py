"""判断前の値幅で規格化した先着を、固定仕様の下で記述する。"""

import hashlib
import json
import pickle
from pathlib import Path

import numpy as np

from describe149 import paired

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SHA = '90e1e380e55a67af8f065f28c2ee93a7c01b37132135e0101b0cfec813195f23'


def summarize(events: list) -> dict:
    """方向群ごとに一夜の事象率と観測数を計算する。

    引数: events (list): 相対幅の方向別観測。
    返り値: dict: 群ごとの分母つき記述値。
    """
    result={}
    for cue in ('全方向','傾き方向','反対方向'):
        selected=[e for e in events if cue=='全方向' or e['cue']==cue]
        result[cue+'_n']=len(selected)
        for metric in ('favorable_reached','adverse_reached','favorable_first','adverse_first','neither','threshold','mfe_relative','mae_relative'):
            result[cue+'_'+metric]=float(np.mean([e[metric] for e in selected])) if selected else None
        touched=[e for e in selected if not e['neither']]
        result[cue+'_conditional_favorable_first']=float(np.mean([e['favorable_first'] for e in touched])) if touched else None
    return result


def main() -> None:
    """固定アンカーを再利用して相対幅の記述感度だけを保存する。

    引数: なし。
    返り値: None。金融取引を生成しないJSONを作成する。
    """
    assert hashlib.sha256((OUT/'相対幅感度の観測定義.json').read_bytes()).hexdigest()==SHA
    original=json.loads((OUT/'市場特性149.json').read_text('utf-8'))
    manifest=json.loads((OUT/'原資料一覧149.json').read_text('utf-8'))
    fingerprints={s['session']:s['prepared']['sha256'] for s in manifest['sessions']}
    sessions=[]
    for source in original['sessions']:
        raw=(ROOT/f'work/preus148/inputs/{source["session"]}.pkl').read_bytes()
        assert hashlib.sha256(raw).hexdigest()==fingerprints[source['session']]
        data=pickle.loads(raw)['data']
        q,r=data['quotes'],data['ready']
        valid=q['quote_valid'] & np.isfinite(q['bid']) & np.isfinite(q['ask']) & (q['bid']>0) & (q['ask']>q['bid'])
        t,bid,ask=r['time_s'][valid],q['bid'][valid],q['ask'][valid]
        result=dict(session=source['session'],windows={})
        for window,record in source['windows'].items():
            selected=[e for e in record['events'] if e['slot']>0 and e['barrier']==100]
            events=[]
            missing=[]
            for e in selected:
                index=int(np.searchsorted(t,e['anchor'],side='left'))
                past=int(np.searchsorted(t,t[index]-1200,side='left'))
                if t[past]-(t[index]-1200)>60:
                    missing.append(dict(slot=e['slot'],side=e['side'],reason='基準値幅の先頭資料不足'))
                    continue
                assert t[past]>=record['start']
                width=float(np.ptp((bid[past:index+1]+ask[past:index+1])/2))
                threshold=max(20.,width*.5)
                end=int(np.searchsorted(t,t[index]+1800,side='right'))
                moves=bid[index+1:end]-ask[index] if e['side']==1 else bid[index]-ask[index+1:end]
                good=np.flatnonzero(moves>=threshold)
                bad=np.flatnonzero(moves<=-threshold)
                first_good=int(good[0]) if len(good) else len(moves)
                first_bad=int(bad[0]) if len(bad) else len(moves)
                events.append(dict(slot=e['slot'],anchor=e['anchor'],side=e['side'],cue=e['cue'],
                    threshold=threshold,past_range=width,
                    favorable_reached=bool(len(good)),adverse_reached=bool(len(bad)),
                    favorable_first=first_good<first_bad,adverse_first=first_bad<first_good,
                    neither=first_good==first_bad,mfe_relative=max(0.,float(np.max(moves)))/threshold,
                    mae_relative=max(0.,float(-np.min(moves)))/threshold))
            result['windows'][window]=dict(metrics=summarize(events),events=events,missing=missing)
        sessions.append(result)
    cue_comparisons={}
    for window in ('前','後'):
        converted=[]
        for s in sessions:
            source=s['windows'][window]['metrics']
            converted.append(dict(windows={
                '前':dict(metrics={k.removeprefix('傾き方向_'):v for k,v in source.items() if k.startswith('傾き方向_')}),
                '後':dict(metrics={k.removeprefix('反対方向_'):v for k,v in source.items() if k.startswith('反対方向_')})}))
        cue_comparisons[window]=paired(converted)
    counts={}
    for w in ('前','後'):
        counts[w]=dict(anchors=sum(s['windows'][w]['metrics']['全方向_n']//2 for s in sessions),
            slope_anchors=sum(s['windows'][w]['metrics']['傾き方向_n'] for s in sessions),
            nights_with_slope=sum(s['windows'][w]['metrics']['傾き方向_n']>0 for s in sessions))
    output=dict(definition_sha256=SHA,financial_replays=0,counts=counts,paired=paired(sessions),
                cue_vs_opposite=cue_comparisons,sessions=sessions)
    (OUT/'相対幅の先着149.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),'utf-8')
    print(json.dumps(counts,ensure_ascii=True))


if __name__=='__main__':
    main()
