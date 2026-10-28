"""9時と米国現物開始の前後を、固定した同長窓で記述比較する。"""

import hashlib
import json
import pickle
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
DEFINITION_SHA='2dc1d4771a37cf7fd1a333212acf49dd3d74a61bf6663b99d5af728d305ae7dc'


def finite(value: float) -> float | None:
    """非有限な記述値を欠測へ変換する。

    引数: value (float): 数値。
    返り値: float | None: 有限値または欠測。
    """
    return float(value) if np.isfinite(value) else None


def minute_data(t: np.ndarray,bid: np.ndarray,ask: np.ndarray) -> dict:
    """各分内の最後の正常気配と連続分差を作る。

    引数: t,bid,ask (ndarray): 原順を保った正常気配。
    返り値: dict: 観測分だけの中値・気配差・絶対変化。空分は補完しない。
    """
    keys=np.floor(t/60).astype(np.int64)
    last=np.r_[np.flatnonzero(np.diff(keys)),len(keys)-1]
    m=keys[last];mid=(bid[last]+ask[last])/2
    change=np.r_[np.nan,np.where(np.diff(m)==1,np.abs(np.diff(mid)),np.nan)]
    return dict(time=m*60,mid=mid,spread=ask[last]-bid[last],change=change)


def window_metrics(t: np.ndarray,bid: np.ndarray,ask: np.ndarray,
                   minute: dict,lo: float,hi: float) -> dict:
    """同長の時刻窓について値幅、絶対変化、急変頻度を測る。

    引数: t,bid,ask (ndarray): 正常気配。minute (dict): 分末資料。lo,hi (float): 範囲。
    返り値: dict: 観測数を伴う指標。資料がなければ指標を欠測とする。
    """
    left,right=np.searchsorted(t,[lo,hi],side='left')
    mask=(minute['time']>=lo)&(minute['time']<hi)
    changes=minute['change'][mask]
    changes=changes[np.isfinite(changes)]
    spreads=minute['spread'][mask]
    mids=minute['mid'][mask]
    result=dict(start=lo,end=hi,expected_minutes=int((hi-lo)/60),observed_minutes=int(len(mids)),
                observed_changes=int(len(changes)),raw_rows=int(right-left),
                minute_coverage=len(mids)/((hi-lo)/60))
    for prefix,values in [('abs_change',changes),('spread',spreads)]:
        result.update({prefix+'_mean':float(np.mean(values)) if len(values) else None,
                       prefix+'_median':float(np.median(values)) if len(values) else None,
                       prefix+'_p90':float(np.quantile(values,.9)) if len(values) else None,
                       prefix+'_max':float(np.max(values)) if len(values) else None})
    result['range_mid']=float(np.ptp((bid[left:right]+ask[left:right])/2)) if right>left else None
    result['range_minute_mid']=float(np.ptp(mids)) if len(mids) else None
    result['clock_gaps_over120']=int(np.count_nonzero(np.diff(t[left:right])>120))
    for threshold in (50,100,200):
        count=int(np.count_nonzero(changes>=threshold))
        result[f'jump_{threshold}_count']=count
        result[f'jump_{threshold}_rate']=count/len(changes) if len(changes) else None
    return result


def paired(rows: list,one: str,two: str) -> dict:
    """同じ場の二窓を対にして記述差を集計する。

    引数: rows (list): 同じ昼夜群の場資料。one,two (str): 窓名。
    返り値: dict: 窓平均、差、場単位再標本化95%区間。
    """
    metrics=set().union(*(set(r['windows'].get(one,{})) for r in rows))
    output={}
    rng=np.random.default_rng(150)
    for metric in sorted(metrics-{'start','end'}):
        pairs=[(r['windows'].get(one,{}).get(metric),r['windows'].get(two,{}).get(metric)) for r in rows]
        pairs=[p for p in pairs if all(v is not None for v in p)]
        if not pairs: continue
        values=np.array(pairs,dtype=float);delta=values[:,0]-values[:,1]
        draws=delta[rng.integers(0,len(delta),size=(10000,len(delta)))]
        output[metric]=dict(n=len(delta),event_mean=float(np.mean(values[:,0])),control_mean=float(np.mean(values[:,1])),
            event_median=float(np.median(values[:,0])),control_median=float(np.median(values[:,1])),
            difference_mean=float(np.mean(delta)),difference_median=float(np.median(delta)),
            event_greater=int(np.count_nonzero(delta>0)),equal=int(np.count_nonzero(delta==0)),
            mean_difference_ci95=np.quantile(np.mean(draws,axis=1),[.025,.975]).tolist(),
            median_difference_ci95=np.quantile(np.median(draws,axis=1),[.025,.975]).tolist())
    return dict(one=one,two=two,metrics=output)


def main() -> None:
    """50場の既存cacheを照合し、金融再生なしで時刻帯を診断する。

    引数: なし。
    返り値: None。新しい150の領域へ記述JSONと目録を保存する。
    """
    definition=OUT/'時刻前後の観測定義150.json'
    assert hashlib.sha256(definition.read_bytes()).hexdigest()==DEFINITION_SHA
    source_path=ROOT/'work/research145_roles/保存入力145.json'
    source=json.loads(source_path.read_text('utf-8'))
    assert len(source['sessions'])==50
    sessions=[];inputs=[]
    for item in source['sessions']:
        ref=item['cache'];path=ROOT/ref['path'];before=path.stat();raw=path.read_bytes()
        digest=hashlib.sha256(raw).hexdigest()
        assert digest==ref['sha256']
        after=path.stat();assert (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns)
        data=pickle.loads(raw)[1];r,q=data['ready'],data['quotes']
        valid=q['quote_valid']&np.isfinite(q['bid'])&np.isfinite(q['ask'])&(q['bid']>0)&(q['ask']>q['bid'])&(r['time_s']>=r['start'])
        t,bid,ask=r['time_s'][valid],q['bid'][valid],q['ask'][valid]
        assert np.all(np.isfinite(t)) and np.all(np.diff(t)>=0)
        day=item['session'].endswith('_Day')
        center=float(r['start']+900 if day else r['us_open'])
        assert np.isfinite(center)
        minute=minute_data(t,bid,ask)
        windows={'イベント30分':(-15,15),'直後対照30分':(15,45),
                 '直前15分':(-15,0),'直後15分':(0,15),'対照15〜30分':(15,30),'対照30〜45分':(30,45)}
        if not day: windows.update({'直前対照30分':(-45,-15),'対照45〜30分前':(-45,-30),'対照30〜15分前':(-30,-15)})
        row=dict(session=item['session'],kind='デイ' if day else 'ナイト',event_time=center,windows={})
        for name,(lo,hi) in windows.items():
            row['windows'][name]=window_metrics(t,bid,ask,minute,center+lo*60,center+hi*60)
        selection=(minute['time']>=center-45*60)&(minute['time']<center+45*60)
        row['observed_minutes']=[dict(time=int(minute['time'][i]),mid=float(minute['mid'][i]),spread=float(minute['spread'][i]),abs_change=finite(minute['change'][i])) for i in np.flatnonzero(selection)]
        sessions.append(row)
        inputs.append(dict(session=item['session'],path=str(path.resolve()),bytes=after.st_size,mtime_ns=after.st_mtime_ns,sha256=digest,matches145=True))
    groups={}
    for kind in ('デイ','ナイト'):
        selected=[r for r in sessions if r['kind']==kind];assert len(selected)==25
        comparisons=[('イベント対直後30分','イベント30分','直後対照30分'),
                     ('開始後15分対次15分','直後15分','対照15〜30分'),
                     ('直前15分対開始後15分','直前15分','直後15分')]
        if kind=='ナイト': comparisons.append(('イベント対直前30分','イベント30分','直前対照30分'))
        groups[kind]={name:paired(selected,one,two) for name,one,two in comparisons}
    output=dict(definition_sha256=DEFINITION_SHA,financial_replays=0,days=25,nights=25,
                independent_unit='同じ場内の窓の組。日と夜は別集計。',groups=groups,sessions=sessions)
    (OUT/'時刻前後の市場診断150.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),'utf-8')
    manifest=dict(definition_sha256=DEFINITION_SHA,cache_files=50,all_sha_match145=True,
                  source=dict(path=str(source_path.resolve()),sha256=hashlib.sha256(source_path.read_bytes()).hexdigest()),inputs=inputs)
    (OUT/'市場診断の入力目録150.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),'utf-8')
    print('既存cache50場のSHA一致。デイ25・ナイト25の記述完了、金融再生0回。')


if __name__=='__main__':
    main()
