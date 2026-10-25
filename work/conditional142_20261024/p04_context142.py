"""保存済みP04親の入口追跡幅・出口中期支持・反復損失を診断する。"""

import json
import pickle
import numpy as np
import run142
import patrol_features142 as features
from patrol_selector142 import medium_direction
from p04_decompose142 import summarize
from loss_raw141 import clean
from implementation_audit141 import stamp

HERE,ROOT=run142.HERE,run142.ROOT


def group(rows,label,**where):
    """
    機能: 条件に属する保存親の会計とMFE・MAEを集計する。
    引数: rows(list[dict])、label(str)、where(dict)は保存親と分類名。
    返り値: dictは集計。条件だけ残した新戦略の損益とは扱わない。
    """
    out=dict(label=label,**where,**summarize(rows))
    if rows:
        for k in ('entry_own5_r','entry_peer5_r','mfe_r','mae_r','entry_spread_r'):
            v=np.array([r[k] for r in rows],float)
            out['median_'+k]=float(np.nanmedian(v));out['mean_'+k]=float(np.nanmean(v))
        out['mfe_positive']=sum(r['mfe_points']>0 for r in rows)
        out['mfe_half_r']=sum(r['mfe_r']>=.5 for r in rows)
        out['mfe_two_r']=sum(r['mfe_r']>=2. for r in rows)
    return out


def main():
    """
    機能: 全50場の保存取引に当時特徴を接続し、見送りや売買の再生をせず分解する。
    引数: なし。
    返り値: None。診断JSONを新規保存する。
    """
    source=json.loads((HERE/'P04全親の状態別と気配差分解142.json').read_text(encoding='utf8'))
    records=source['records'];packets,_,_=run142.first.material()
    for item in packets:
        scene=item['session'];packet=pickle.loads((ROOT/item['path']).read_bytes())
        original,_,_,_=run142.prepared(packet);data=features.prepare(packet,original)
        for symbol,d in data.items():
            r,q,a=d['ready'],d['quotes'],d['features'];t=r['time_s']
            with np.load(HERE/'round2/measurement'/f'{symbol}_{scene}.npz') as z:orders=z['P04']
            chosen=sorted((p for p in records if p['session']==scene and p['symbol']==symbol),key=lambda p:p['entry_row'])
            previous=None;chain=0
            for p in chosen:
                side=p['side'];risk=p['risk'];i=p['decision_row'];lo=p['entry_row'];hi=p['exit_row']
                saved=orders[orders[:,2]==p['parent']];j=int(saved[-1,1]);valid=q['quote_valid'][lo:hi+1]
                liquidate=q['bid'][lo:hi+1] if side>0 else q['ask'][lo:hi+1]
                gain=side*(liquidate[valid]-p['entry_price'])
                med=int(medium_direction(a[j]));em=int(medium_direction(a[i]))
                p.update(entry_display=stamp(p['entry_time']),exit_display=stamp(p['exit_time']),
                    exit_decision_row=j,exit_decision_seq=int(r['seq'][j]),
                    entry_own5_r=float(side*a[i,3]/risk),entry_peer5_r=float(side*a[i,14]/a[i,18]),
                    entry_spread_r=float((q['ask'][i]-q['bid'][i])/risk),
                    entry_medium=em,exit_medium=med,exit_medium_support=med==side,
                    exit20_support=bool(np.isfinite(a[j,28:30]).all() and side*a[j,28]>0 and side*a[j,29]>0),
                    exit5_support=bool(side*a[j,3]>0 and side*a[j,14]>0),
                    exit_short_adverse=bool(side*a[j,13]<=-.1 and side*a[j,21]<=-.1),
                    entry_own20=float(a[i,28]),entry_peer20=float(a[i,29]),
                    exit_own20=float(a[j,28]),exit_peer20=float(a[j,29]),
                    exit_own5=float(a[j,3]),exit_peer5=float(a[j,14]),
                    entry_own120_r=float(side*a[i,13]),entry_peer120_r=float(side*a[i,21]),
                    entry_own_ofi=float(side*a[i,24]),entry_peer_ofi=float(side*a[i,26]),
                    mfe_points=float(gain.max()),mae_points=float(gain.min()),
                    mfe_r=float(gain.max()/risk),mae_r=float(gain.min()/risk))
                p['entry_chase_bin']='未公開又は欠測' if not np.isfinite(p['entry_own5_r']) else ('非順行' if p['entry_own5_r']<=0 else ('0〜0.5R' if p['entry_own5_r']<.5 else ('0.5〜1R' if p['entry_own5_r']<1 else '1R以上')))
                p['prior_same_side']=bool(previous and previous['side']==side)
                p['prior_gap_seconds']=p['entry_time']-previous['exit_time'] if previous else None
                p['prior_loss']=bool(previous and previous['net']<0)
                p['repeat_same_120']=bool(p['prior_same_side'] and p['prior_gap_seconds']<=120.)
                if not p['repeat_same_120']:chain+=1
                p['chain']=chain
                previous=p
        print(scene,'当時特徴接続',flush=True)
    groups=[]
    for symbol in ('NK225','TOPIX'):
        allrows=[p for p in records if p['symbol']==symbol]
        for regime in (0,1,2,3):
            rows=[p for p in allrows if regime==0 or p['regime']==regime]
            for flag in (False,True):
                groups.append(group([p for p in rows if p['exit20_support']==flag],'出口公開20分支持',symbol=symbol,regime=regime,support=flag))
            for chase in ('未公開又は欠測','非順行','0〜0.5R','0.5〜1R','1R以上'):
                groups.append(group([p for p in rows if p['entry_chase_bin']==chase],'入口5分進行幅',symbol=symbol,regime=regime,chase=chase))
        for label,filter_key in (('同方向120秒内再参加','repeat_same_120'),('前親損失','prior_loss')):
            for flag in (False,True):groups.append(group([p for p in allrows if p[filter_key]==flag],label,symbol=symbol,value=flag))
        for reason in sorted({p['exit_reason'] for p in allrows}):
            groups.append(group([p for p in allrows if p['exit_reason']==reason],'返済理由',symbol=symbol,reason=reason))
    chains=[]
    for key in sorted({(p['symbol'],p['session'],p['chain']) for p in records}):
        rows=[p for p in records if (p['symbol'],p['session'],p['chain'])==key]
        if len(rows)>=2:chains.append(dict(symbol=key[0],session=key[1],chain=key[2],side=rows[0]['side'],parents_ids=[p['parent'] for p in rows],**summarize(rows)))
    out=dict(financial_replays=0,records=records,groups=groups,chains=sorted(chains,key=lambda p:p['net']),
        limitations=['保存親の条件付き集計。親を見送ると将来の新規時刻と方向は変わるため、抽出後収支を新手法の成績と呼ばない。',
            '中値代理会計・MFEは事後診断に限る。価格時計は共通受信時計を意味しない。'])
    with (HERE/'P04追いかけ出口中期支持と反復損失142_v2.json').open('x',encoding='utf8') as f:json.dump(clean(out),f,ensure_ascii=False,indent=2,allow_nan=False)
    for r in groups:
        if r.get('regime',0) in (0,1):print(r,flush=True)


if __name__=='__main__':main()
