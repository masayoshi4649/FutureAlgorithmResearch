"""追撃の失敗が狭い追加停止から生じたか、元玉の条件を固定して比較する。"""

import argparse
import pickle
import subprocess
import sys
import numpy as np
from run137 import HERE, ROOT, MANAGER, read, save, ref, features129, account, phases
import overlay_wide137


def settings():
    """
    機能: 追加停止幅だけを変更する六対照を固定する。
    引数: なし。
    返り値: list[dict]は0.75R・1R・元返済だけの条件。
    """
    out=[]
    for stem,adaptive in (('W',False),('CW',True)):
        for suffix,stop in (('075',.75),('100',1.),('parent',0.)):
            out.append(dict(id=stem+suffix,initial=2,mode=2,width=.25,hold=15.,adaptive=adaptive,stop_width=stop))
    return out


def prepare():
    """
    機能: 追撃専用停止で切られた具体例に基づく比較を登録する。
    引数: なし。
    返り値: None。金融再生は行わない。
    """
    previous=read(HERE/'試行計画_v3.json');plan=dict(previous)
    paths=[HERE/'round3_137.py',HERE/'run137.py',HERE/'overlay_wide137.py',
        ROOT/'work/visual_pdca129_20261020/features129.py',ROOT/'work/daynight128_20261020/features128.py']
    plan.update(id='137_第三巡_追撃の停止幅を分離',name='追撃玉の停止幅と元玉の維持を分離する比較',
        question='追加玉の0.5R停止が通常の押し戻りを切っていないか。幅を0.75R/1Rへ広げる、又は元親の返済へ合わせると改善するか。',
        change='C02aとCT02の入口・初期枚数・追加判断を保持。追加玉の独立停止だけを変更する。',
        repeat_reason='独立監査でC02a追加39親中31赤字。10月19日10:17の追撃は−45,230円でも初期玉は+73,847円で、0.5R停止の狭さが具体的な失敗候補。',
        compares_to=['137_日経mini段階投入と市場時計'],configs=settings(),sources=[ref(p) for p in paths])
    plan['spec']=dict(previous['spec']);plan['spec']['management']={'固定条件':settings(),'元玉':'停止・通知・再参加の変更なし。'}
    plan['spec']['exit']={'元玉':'第一巡と同一','追撃':{'幅R':[.75,1.,0.],'ゼロ':'追加独自の停止を置かず元親の返済通知で決済'}}
    plan['spec']['implementation']={ref(p)['path']:ref(p)['sha256'] for p in paths}
    plan['evidence']=[ref(HERE/'audit_financial137.json')]
    save(HERE/'第三巡計画.json',plan)
    for action in ('check','register'):
        r=subprocess.run([sys.executable,'-B','-X','utf8',str(MANAGER),action,'--proposal',str(HERE/'第三巡計画.json')],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        save(HERE/f'第三巡_{action}.json',dict(returncode=r.returncode,stdout=r.stdout,stderr=r.stderr))
        assert r.returncode==0,r.stderr[-2000:]
        print(action,'完了',flush=True)


def run():
    """
    機能: 登録した停止幅だけを既知45場で比較する。
    引数: なし。
    返り値: None。源通知と元結果は上書きしない。
    """
    p=read(HERE/'第三巡計画.json');assert read(HERE/'第三巡_register.json')['returncode']==0
    for r in p['sources']:assert ref(ROOT/r['path'])==r
    assert p['configs']==settings();rows=[];cache=[]
    for item in p['inputs']:
        for name in ('input','orders'):assert ref(ROOT/item[name]['path'])==item[name]
        packet=pickle.loads((ROOT/item['input']['path']).read_bytes());scene=item['session'];key=(scene,'NK225')
        ins=features129.prices_for(packet,'mid');m=features129.markets(ins)[key];ready=ins[key];q=packet['quotes'][key]
        prefix='' if item['prefix']=='なし' else item['prefix']
        with np.load(ROOT/item['orders']['path'],allow_pickle=False) as old:
            core=old[prefix+'core_orders'];extra=old[prefix+'extra_orders']
        arrays={}
        for c in p['configs']:
            o=overlay_wide137.replay(ready['time_s'],q,ready['atr'],m,phases(ready),core,extra,c)
            arrays[c['id']]=o;rows.append(account(o,ready['time_s'],q['bid'],q['ask'],c['id'],scene))
        target=HERE/'measurement3'/f'{scene}.npz';target.parent.mkdir(exist_ok=True);assert not target.exists()
        np.savez_compressed(target,**arrays);cache.append(dict(session=scene,**ref(target)))
        print(scene,'第三巡完了',flush=True)
    save(HERE/'結果3.json',dict(rows=rows,cache=cache,plan=ref(HERE/'第三巡計画.json'),API=0,real_orders=0))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=('prepare','run'));args=p.parse_args()
    {'prepare':prepare,'run':run}[args.stage]()
