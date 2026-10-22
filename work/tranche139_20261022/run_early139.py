"""朝と米国前の早期参加を、既存担当との競合まで含めて固定比較する。"""

import argparse
import copy
import pickle
import subprocess
import sys
from pathlib import Path
import numpy as np
from common139 import HERE,ROOT,OLD,read,save,ref,base_config,product,account,force_parent
import early139
import engine139_native

MANAGER=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'


def settings():
    """
    機能: 四つの早期入口・二支持閾値・二枚数配分を固定する。
    引数: なし。
    返り値: list[dict]は16条件。各々を早期単独・B5併用・C04併用で採点する。
    """
    result=[]
    for mechanism in ('support','ema38','ema520','retest'):
        for strength in (1,2):
            for size in (3,5):
                management=base_config()
                management.update(initial=1 if size==3 else 2,target=size,increments=[1,1] if size==3 else [1,1,1],
                    steps=[.25,.5] if size==3 else [.25,.5,.75],stop_width=[1.5,1.],exit_activation=[2.,1.5],
                    exit_width=[1.5,1.,.75,.5],tighten_at=[3.,2.],tight_width=[.75,.5,.375,.25],source_style='早期独立出口')
                result.append(dict(id=f'E{len(result)+1:02d}',name=f'{mechanism}・支持{strength}・最大{size}枚',
                    entry=dict(mechanism=mechanism,threshold30=.05*strength,threshold120=.2*strength,hold=15.,cooldown=600.),
                    management=management))
    return result


def joined(base,candidates,ready,management,symbol):
    """
    機能: 新規判断の順に早期と通常の親を選び、保有中の後続候補を見送る。
    引数: base/candidates(ndarray)、ready/management(dict)、symbol(str)は固定通知と早期特徴。
    返り値: tuple[ndarray,list[dict]]は全約定と見送り。将来の通常入口を見て早期返済しない。
    """
    c=copy.deepcopy(management);c.update(product(symbol));queue=[];parts=[];skips=[];last=-1
    for pid in np.unique(base[:,2]) if len(base) else []:
        rows=base[base[:,2]==pid];queue.append((int(rows[0,1]),'通常',rows))
    for first in candidates:
        row=first.copy();row[2]+=20000;queue.append((int(row[1]),'早期',row.reshape(1,-1)))
    for decision,kind,rows in sorted(queue,key=lambda x:(x[0],0 if x[1]=='通常' else 1)):
        if decision<last:
            skips.append(dict(parent=int(rows[0,2]),kind=kind,decision=decision,active_until=last));continue
        if kind=='通常':orders=rows
        else:
            source=force_parent(rows[0],ready['time_s'],ready['quotes'],ready['window_end'])
            orders=engine139_native.replay(ready['time_s'],ready['quotes'],ready['atr'],ready['market'],ready['phase'],source,c)
        if len(orders):last=int(orders[-1,0]);parts.append(orders)
    out=np.concatenate(parts) if parts else np.empty((0,10))
    return out[np.argsort(out[:,0],kind='stable')] if len(out) else out,skips


def prepare():
    """
    機能: 早期特徴・入口・数量・出口・通常担当との接続を再生前に登録する。
    引数: なし。
    返り値: None。金融再生を行わない。
    """
    previous=read(HERE/'試行計画_v2.json');p=copy.deepcopy(previous)
    paths=[HERE/n for n in ('run_early139.py','early139.py','engine139_native.py','engine139.py','common139.py')]
    sources=dict(previous['spec']['implementation'])
    for path in paths:r=ref(path);sources[r['path']]=r['sha256']
    p.update(id='139_朝と米国前の早期参加',name='待機帯を短指標と少量で補完する比較',
        question='朝63確定足・夜US+22分を待たず、短指標と少量先行なら往復損失を抑えながら機会を取れるか。',
        change='早期の二市場確定足特徴を新造。4入口×2閾値×2配分を早期単独とB5/C04併用で比較。',
        repeat_reason='00137の米前短期支持と旧NV25の延長は赤字。今回は朝も含め、確定3足の短ATR・短EMA・戻り確認と複数追撃の自前出口を組み合わせる。',
        compares_to=['139_複数追撃と初回待機と再追加','137_日経mini段階投入と市場時計'],configs=settings())
    p['spec']['entry']={'条件':settings(),'方向':'原板から当時確定済みの1分足のみ。3足でATR、EMA3/8は8足、EMA5/20は20足。相手同時刻は参照しない。',
        '開始':'朝08:45、夜17:00。指標が実際に準備できてから候補。','終了':'新判断は09:45/米現物20分前、発注済みは早期終了まで次正常気配で約定。'}
    p['spec']['management']={'枚数':'最初1→最大3枚、最初2→最大5枚。二市場支持を各段で確認。','追尾':'初回は広め、後玉ほど狭く、十分伸びてからさらに短縮。',
        '競合':'保有中に判断された通常/早期の新規候補を見送る。返済後に新しく出た候補だけ参加。通常入口時刻を事後に見て早期玉を強制返済しない。'}
    p['spec']['exit']={'独立':'初回1.5R停止、追加1R停止、玉別利益追尾。早期は09:50/米現物15分前に必ず返済判断。',
        '通常':'既知46条件のB5又はC04の元親注文。双方別口座の比較。','短絡':'独立親が全玉返済済みなら、その後の空ループだけ打切る。同値人工を確認。'}
    p['spec']['implementation']=sources
    p['evidence']=[ref(HERE/'早期入口_人工確認.json'),ref(HERE/'独立出口短絡_人工確認.json'),ref(HERE/'早期接続_人工確認.json')]
    save(HERE/'早期計画.json',p)
    for action in ('check','register'):
        r=subprocess.run([sys.executable,'-B','-X','utf8',str(MANAGER),action,'--proposal',str(HERE/'早期計画.json')],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        save(HERE/f'早期_{action}.json',dict(returncode=r.returncode,stdout=r.stdout,stderr=r.stderr));assert r.returncode==0,r.stderr[-2000:]
        print(action,'完了',flush=True)


def run():
    """
    機能: 同じ固定早期条件を45場と追加2場で検証する。
    引数: なし。
    返り値: None。早期単独と併用は別会計。通常担当の保存結果は変更しない。
    """
    plan=read(HERE/'早期計画.json');assert read(HERE/'早期_register.json')['returncode']==0;assert plan['configs']==settings()
    for path,sha in plan['spec']['implementation'].items():assert ref(ROOT/path)['sha256']==sha,path
    results=[read(HERE/f'{folder}/結果.json') for folder in ('results','extra_results')]
    baseline={ (r['session'],r['symbol']):r for d in results for r in d['cache'] }
    packets=read(HERE/'manifest139.json')['packets']+read(HERE/'manifest139_extra.json')['packets']
    rows=[];cache=[];skips=[];coverage=[]
    for p in packets:
        assert ref(Path(p['path']))['sha256']==p['sha256'];packet=pickle.loads(Path(p['path']).read_bytes());scene=p['session']
        prepared=early139.prepare(packet);arrays={s:{} for s in ('NK225','TOPIX')}
        saved={}
        for symbol in arrays:
            r=baseline[(scene,symbol)];assert ref(ROOT/r['path'])['sha256']==r['sha256']
            with np.load(ROOT/r['path'],allow_pickle=False) as f:saved[symbol]={key:f[key] for key in ('B5','C04')}
        for c in plan['configs']:
            candidates=early139.candidates(prepared,c['entry'])
            for symbol,ready in candidates.items():
                ts=ready['time_s'];quote=ready['quotes']
                for basekey in ('単独','B5','C04'):
                    key=c['id'] if basekey=='単独' else basekey+'_'+c['id']
                    base=np.empty((0,10)) if basekey=='単独' else saved[symbol][basekey]
                    orders,skipped=joined(base,ready['core_candidates'],ready,c['management'],symbol)
                    arrays[symbol][key]=orders;row=account(orders,ts,quote,key,scene,symbol)
                    row['early_entries']=int(np.sum((orders[:,7]==1)&(orders[:,8]==0)&(orders[:,2]>=20000))) if len(orders) else 0
                    rows.append(row)
                    if skipped:skips.append(dict(method=key,session=scene,symbol=symbol,skipped=skipped))
                coverage.append(dict(method=c['id'],session=scene,symbol=symbol,candidates=len(ready['core_candidates']),
                    first_candidate_time=float(ts[int(ready['core_candidates'][0,1])]) if len(ready['core_candidates']) else None))
        for symbol,content in arrays.items():
            target=HERE/'early_results/measurement'/f'{symbol}_{scene}.npz';target.parent.mkdir(parents=True,exist_ok=True);assert not target.exists()
            np.savez_compressed(target,**content);cache.append(dict(session=scene,symbol=symbol,**ref(target)))
        print(scene,'早期と併用完了',flush=True)
    save(HERE/'early_results/結果.json',dict(rows=rows,cache=cache,skips=skips,coverage=coverage,plan=ref(HERE/'早期計画.json'),API=0,real_orders=0))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=('prepare','run'));args=p.parse_args()
    {'prepare':prepare,'run':run}[args.stage]()
