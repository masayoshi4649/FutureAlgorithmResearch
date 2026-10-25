"""保存した売買会計から状態切替の成績と過去完了場選択を集計する。"""

import json
from pathlib import Path
import sys
import numpy as np
import pickle

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'work/raw_diagnosis141_20261024'))
from analyze141 import aggregate,read
from policies142 import active_configs,joint_configs
from night_selector142 import configurations as night_configs
from online142 import replay_selection
import run142 as runner


def save(name,data):
    """
    機能: 再集計資料をUTF-8で保存する。
    引数: name(str)、data(dict/list)は出力位置と内容。
    返り値: None。
    """
    (HERE/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def holding_metrics(result):
    """
    機能: 注文時刻から重複保有を一度だけ数え、保有枚数を時間加重する。
    引数: result(dict)は金融結果と原注文位置。
    返り値: tuple[dict,dict]は銘柄手法場ごとの保有指標と開始から清算判断時までの価格差。
    """
    packets,_,_=runner.first.material();cache={}
    for item in result['cache']:cache.setdefault(item['session'],[]).append(item)
    metrics={};changes={}
    for info in packets:
        path=Path(info['path']);path=path if path.is_absolute() else ROOT/path
        packet=pickle.loads(path.read_bytes());scene=info['session']
        for symbol in ('NK225','TOPIX'):
            r=packet['inputs'][scene,symbol];q=packet['quotes'][scene,symbol];t=r['time_s']
            good=q['quote_valid']&np.isfinite(q['bid'])&np.isfinite(q['ask'])&(t>=r['start'])&(t<=r['limit'])
            indexes=np.flatnonzero(good);mid=(q['bid']+q['ask'])/2
            changes[symbol,scene]=float(mid[indexes[-1]]-mid[indexes[0]])
        for info2 in cache[scene]:
            symbol=info2['symbol'];r=packet['inputs'][scene,symbol];times=r['time_s'];start=r['start'];duration=(420 if scene.endswith('_Day') else 780)*60.
            with np.load(ROOT/info2['path']) as arrays:
                for method in arrays.files:
                    orders=arrays[method];quantity=0;last=start;elapsed=0.;quantity_seconds=0.
                    for o in orders:
                        now=min(start+duration,max(start,float(times[int(o[0])])));dt=now-last
                        assert dt>=0.
                        if quantity:elapsed+=dt
                        quantity_seconds+=quantity*dt
                        quantity+=int(o[4]) if o[7] else -int(o[4]);last=now
                    assert quantity==0
                    metrics[symbol,method,scene]=dict(holding_ratio=elapsed/duration,avg_held_quantity=quantity_seconds/duration,official_minutes=duration/60.)
    return metrics,changes


def add_group_metrics(summary,parts,rows):
    """
    機能: 同じ統計対象で各場平均保有率と総時間加重率を算出する。
    引数: summary/parts/rows(list[dict])は集計と元会計。
    返り値: None。与えた集計へ保有率と平均保有枚数を追加する。
    """
    for group in summary+parts:
        chosen=[r for r in rows if r['symbol']==group['symbol'] and r['method']==group['method']]
        scope=group['scope']
        chosen=[r for r in chosen if scope=='all' or (r['session']>='2026-10-22_Night')==(scope=='new')]
        if 'group' in group:
            kind=group['group']
            chosen=[r for r in chosen if (r['kind']==kind if kind in ('Day','Night') else r['market_change']*(1 if kind=='上昇' else -1)>0)]
        assert len(chosen)==group['sessions']
        group['mean_holding_ratio']=float(np.mean([r['holding_ratio'] for r in chosen]))
        group['time_weighted_holding_ratio']=sum(r['held_minutes'] for r in chosen)/sum(r['official_minutes'] for r in chosen)
        group['avg_held_quantity']=float(np.mean([r['avg_held_quantity'] for r in chosen]))


def main():
    """
    機能: 全場・昼夜・上昇下落の安定性と、採用条件の差を比較する。
    引数: なし。
    返り値: None。元注文や既存会計は変更しない。
    """
    name='結果142_三巡統合.json' if (HERE/'結果142_三巡統合.json').exists() else ('結果142_二巡統合.json' if (HERE/'結果142_二巡統合.json').exists() else '結果142.json')
    result=read(HERE/name)
    metrics,changes=holding_metrics(result)
    rows=[dict(r,**metrics[r['symbol'],r['method'],r['session']]) for r in result['rows'] if not r['method'].startswith('A_')]
    for r in rows:
        r['original_market_change']=r['market_change'];r['market_change']=changes[r['symbol'],r['session']]
    online,notes=replay_selection(rows);rows.extend(online)
    names={'B5':'従来基準','M1':'00141の昼夜別固定案','W01':'過去完了場だけの逐次選択'}
    for config in active_configs()+joint_configs()+night_configs():names[config['id']]=config['name']
    if (HERE/'第二巡結果142.json').exists():
        second=read(HERE/'第二巡計画142_v2.json')
        for c in second['configs']['night']:names[c['id']]=c['name']
        for c in second['configs']['patrol']:
            names[c['id']]=c['name'];names['K'+c['id'][1:]]='基準併用：'+c['name'];names['L'+c['id'][1:]]='夜小玉基準併用：'+c['name']
    if (HERE/'第三巡結果142.json').exists():
        third=read(HERE/'第三巡計画142.json')
        for c in third['configs']['regime']:
            names[c['id']]=c['name'];names['V'+c['id'][1:]]='中期状態の基準併用：'+c['name']
    summary,parts=aggregate(rows,names)
    add_group_metrics(summary,parts,rows)
    save('比較集計142.json',dict(rows=rows,summary=summary,parts=parts,names=names))
    save('逐次選択142.json',notes)
    for symbol in ('NK225','TOPIX'):
        for kind in ('Day','Night'):
            print(symbol,kind,flush=True)
            part=[r for r in parts if r['symbol']==symbol and r['group']==kind and r['scope']=='all']
            ranked=sorted(part,key=lambda r:(r['flat'],r['losses'],r['avg_loss'],-r['ex_top3']))
            shown=[r for r in part if r['method'] in ('B5','M1','W01')]+ranked[:8]
            for r in shown:print({k:r[k] for k in ('method','net','losses','flat','avg_loss','worst','ex_top3','entries','mean_holding_ratio')},flush=True)
    print('追加3場の統合',flush=True)
    for r in summary:
        if r['scope']=='new' and r['method'] in ('B5','M1','J01','J02','J03','J04','J05','W01'):
            print({k:r[k] for k in ('symbol','method','net','losses','flat')},flush=True)


if __name__=='__main__':
    main()
