"""短期支持だけの往復損失を受け、現行の境界再試験を米国前へ限定接続する。"""

import argparse
import json
import pickle
import subprocess
import sys
import numpy as np
import run137 as shared
from run137 import HERE, ROOT, MANAGER, read, save, ref, features129, overlay137, account, phases
import night_retest129c

PARAMETERS=('mode','stop','trail_start','trail_width','phase','cooldown','entry_bounce',
            'opening_buffer','minimum_efficiency','band_distance','entry_confirm','exit_mode','rearm','maximum_extension')


def settings():
    """
    機能: 現行夜間NV25の価格条件を保持し、参加区間だけを米国前に変える。
    引数: なし。
    返り値: dictは米国前の仮想入口と3数量層、初期枚数だけの対照。
    """
    old=read(ROOT/'work/visual_pdca129_20261020/round7/固定計画.json')
    native=next(dict(c) for c in old['configs'] if c['id']=='NV25')
    native['phase']=2
    return dict(native=native,early=[dict(id='E5',initial=5,mode=0,width=0.,hold=0.,adaptive=False),
        dict(id='E2',initial=2,mode=0,width=0.,hold=0.,adaptive=False),
        dict(id='EC2',initial=2,mode=2,width=.25,hold=15.,adaptive=False)],
        allocation=dict(id='CT00',initial=2,mode=0,width=.25,hold=15.,adaptive=True))


def prepare():
    """
    機能: 第一次の失敗機構と第二次の固定差分を登録する。
    引数: なし。
    返り値: None。金融再生はしない。
    """
    previous=read(HERE/'試行計画_v3.json')
    plan=dict(previous)
    paths=[HERE/'round2_137.py',HERE/'run137.py',HERE/'overlay137.py',
           ROOT/'work/visual_pdca129_20261020/night_retest129c.py',
           ROOT/'work/visual_pdca129_20261020/features129.py',ROOT/'work/daynight128_20261020/features128.py']
    plan.update(id='137_第二巡_米国前の境界再試験と初期減枚',name='米国前の境界再試験と初期減枚の分離',
        question='単なる短期方向で増えた往復取引を、既存の20分価格帯突破・押し戻り再試験で抑えられるか。CT02の効果は追撃か初期配分か。',
        change='第一巡短期支持R系は841以上の新規を作り赤字。米前だけ現行NV25のphase=2・終端を米寄付15分前へ変更。価格帯・支持・出口・5分待機は元のまま。CT00はCT02の追撃だけ停止。',
        repeat_reason='第一巡の短期支持の反復損失を、時刻だけで停止せず価格帯維持の構造確認へ変更する。初期配分と追撃の寄与を分離。',
        compares_to=['137_日経mini段階投入と市場時計'],configs=settings(),sources=[ref(p) for p in paths])
    plan['spec']=dict(previous['spec'])
    plan['spec']['entry']={'native':settings()['native'],'対照':'米前E5/E2/EC2と既存後半B05又はCT02の合算。日中は各基準を再利用。'}
    plan['spec']['management']={'変更':'CT00はCT02の追加をなくす。E5/E2は境界維持確認後5枚又は2枚、EC2は2枚から支持再確認で5枚へ。','spec':settings()}
    plan['spec']['exit']={'米前':'NV25の元出口、米国現物開始15分前で全返済判断。次正常原行約定。','追加':'EC2のみ追加玉0.5R、元玉出口保持。'}
    plan['spec']['implementation']={ref(p)['path']:ref(p)['sha256'] for p in paths}
    plan['evidence']=[ref(HERE/'結果.json')]
    save(HERE/'第二巡計画.json',plan)
    for action in ('check','register'):
        r=subprocess.run([sys.executable,'-B','-X','utf8',str(MANAGER),action,'--proposal',str(HERE/'第二巡計画.json')],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        save(HERE/f'第二巡_{action}.json',dict(returncode=r.returncode,stdout=r.stdout,stderr=r.stderr))
        assert r.returncode==0,r.stderr[-2000:]
        print(action,'完了',flush=True)


def run():
    """
    機能: 登録後に米国前だけを新たに再生し、既存後半の保存注文へ合算する。
    引数: なし。
    返り値: None。旧金融結果・稼働設定を変更しない。
    """
    plan=read(HERE/'第二巡計画.json');assert read(HERE/'第二巡_register.json')['returncode']==0
    for r in plan['sources']:assert ref(ROOT/r['path'])==r
    assert plan['configs']==settings();config=plan['configs'];rows=[];cache=[]
    for item in plan['inputs']:
        assert ref(ROOT/item['input']['path'])==item['input']
        packet=pickle.loads((ROOT/item['input']['path']).read_bytes());scene=item['session'];key=(scene,'NK225')
        ins=features129.prices_for(packet,'mid');market=features129.markets(ins)[key]
        ready=ins[key];q=packet['quotes'][key];ts=ready['time_s'];phase=phases(ready)
        prefix='' if item['prefix']=='なし' else item['prefix']
        with np.load(ROOT/item['orders']['path'],allow_pickle=False) as old:
            core=old[prefix+'core_orders'];extra=old[prefix+'extra_orders']
        ct=overlay137.replay(ts,q,ready['atr'],market,phase,core,extra,config['allocation'])
        arrays={'CT00':ct};rows.append(account(ct,ts,q['bid'],q['ask'],'CT00',scene))
        with np.load(HERE/'measurement'/f'{scene}.npz',allow_pickle=False) as previous:
            bases={'B':previous['B05'],'C':previous['CT02']}
        if scene.endswith('_Night'):
            history=features129.features128.build(dict(inputs=ins))[key]
            native=config['native'];end=ready['us_open']-900.
            seed,_,_=night_retest129c.simulate(ts,ready['last'],q['bid'],q['ask'],q['quote_valid'],
                ready['atr'],history,market,ready['start'],end,ready['us_open'],ready['tick'],10,10.,110,
                np.array([native[k] for k in PARAMETERS],dtype=float),native['retest_mode'])
            arrays['仮想米前通知']=seed
        for c in config['early']:
            early=np.empty((0,10))
            if scene.endswith('_Night'):
                early=overlay137.replay(ts,q,ready['atr'],market,phase,seed,np.empty((0,12)),c)
                early[:,2]+=30000;early[:,8]+=20
                assert len(early)==0 or ts[int(early[-1,0])]<ready['us_open']+1320.
            arrays[c['id']]=early
            for b,base in bases.items():
                cid='N'+b+'_'+c['id'];joined=np.concatenate((base,early));joined=joined[np.argsort(joined[:,0],kind='stable')]
                arrays[cid]=joined;rows.append(account(joined,ts,q['bid'],q['ask'],cid,scene))
        target=HERE/'measurement2'/f'{scene}.npz';target.parent.mkdir(exist_ok=True);assert not target.exists()
        np.savez_compressed(target,**arrays);cache.append(dict(session=scene,**ref(target)))
        print(scene,'第二巡完了',flush=True)
    save(HERE/'結果2.json',dict(rows=rows,cache=cache,plan=ref(HERE/'第二巡計画.json'),API=0,real_orders=0))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=('prepare','run'));args=p.parse_args()
    {'prepare':prepare,'run':run}[args.stage]()
