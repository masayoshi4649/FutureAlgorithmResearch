"""十分伸びない追撃が作った損失に対し、起動と損切りだけを変える。"""

import argparse
import copy
import pickle
import subprocess
import sys
from pathlib import Path
import numpy as np
from common139 import HERE,ROOT,read,save,ref,configs,account,replay,features129,phases
from run_recycle139 import original

MANAGER=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'


def settings():
    """
    機能: 後段の起動を早める案と追撃だけの独立損切りを分離する。
    引数: なし。
    返り値: list[dict]は二配分各4条件。初回玉の出口は変更しない。
    """
    base={c['id']:c for c in configs()};out=[]
    moderate=dict(exit_activation=[0.,1.,.75,.5],exit_width=[1.,.75,.5,.375])
    early=dict(exit_activation=[0.,.75,.5,.25],exit_width=[1.,.5,.375,.125])
    stops=dict(stop_width=[0.,1.,.75,.5])
    for stem in ('P','C'):
        for key,name,change in [('A','後の玉ほど早く保護',moderate),('B','後の玉をさらに早く保護',early),
                ('S','追撃だけ段階的に損切り',stops),('AS','早期保護と追撃損切り',dict(**moderate,**stops))]:
            c=copy.deepcopy(base[stem+'04']);c.update(change);c.update(id=stem+'H'+key,base=stem+'04',name=('2枚先行' if stem=='P' else '時計配分')+'／'+name);out.append(c)
    return out


def prepare():
    """
    機能: 原因分析から導いた保護条件を、再生前に別試行へ登録する。
    引数: なし。
    返り値: None。既知標本を用いる改善であり未知期間検証とはしない。
    """
    p=copy.deepcopy(read(HERE/'試行計画_v2.json'))
    p.update(id='139_伸びない追撃の早期保護',name='利益追尾が起動しなかった追撃の損失対処',configs=settings(),
        question='追撃玉自身が1.5Rに届かず大幅逆行した損失を、後段の早い保護又は独立停止で抑えられるか。',
        change='P04/C04の初回玉・元入口・元親出口を保持。後段の追尾起動と追撃だけの停止を変更。',
        repeat_reason='各商品で最大追撃損失3親、計6親の追加玉はいずれも自身の順行1.5R未達。狭幅化だけでは未起動の損失を防げない。',
        compares_to=['139_複数追撃と初回待機と再追加'])
    p['spec']['management']={'条件':settings(),'変更範囲':'初回は元通り。追撃の起動と停止だけ。二市場支持と枚数・段階はP04/C04同一。'}
    p['spec']['exit']={'通常':'元親返済優先。後段起動1/.75/.5R又は.75/.5/.25R。追撃停止1/.75/.5Rを単独及び併用。','短縮':'2Rに達した後の元短縮は継続。追尾床は逆に緩めない。'}
    for name in ('run_protect139.py','run_recycle139.py','recycle139.py'):
        r=ref(HERE/name);p['spec']['implementation'][r['path']]=r['sha256']
    p['evidence']=[ref(HERE/'金融独立監査.json'),ref(HERE/'金融独立監査_追加.json')]
    save(HERE/'追撃保護計画.json',p)
    for action in ('check','register'):
        r=subprocess.run([sys.executable,'-B','-X','utf8',str(MANAGER),action,'--proposal',str(HERE/'追撃保護計画.json')],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        save(HERE/f'追撃保護_{action}.json',dict(returncode=r.returncode,stdout=r.stdout,stderr=r.stderr));assert r.returncode==0,r.stderr[-2000:]
        print(action,'完了',flush=True)


def run():
    """
    機能: 固定8条件を全47場で再生し、停止で削った利益も含めて保存する。
    引数: なし。
    返り値: None。既存会計と稼働アプリを変更しない。
    """
    plan=read(HERE/'追撃保護計画.json');assert read(HERE/'追撃保護_register.json')['returncode']==0;assert plan['configs']==settings()
    for path,sha in plan['spec']['implementation'].items():assert ref(ROOT/path)['sha256']==sha,path
    manifest=read(HERE/'manifest139.json');extra=read(HERE/'manifest139_extra.json');rows=[];cache=[];skips=[]
    for p in manifest['packets']+extra['packets']:
        assert ref(Path(p['path']))['sha256']==p['sha256'];packet=pickle.loads(Path(p['path']).read_bytes());scene=p['session']
        ins=features129.prices_for(packet,'mid');markets=features129.markets(ins)
        for symbol in ('NK225','TOPIX'):
            ready=ins[(scene,symbol)];quote=packet['quotes'][(scene,symbol)];market=markets[(scene,symbol)];phase=phases(ready)
            core,supplement=original(scene,symbol,manifest,extra);arrays={}
            for c in plan['configs']:
                orders,skipped=replay(ready,quote,market,phase,core,supplement,c,symbol)
                arrays[c['id']]=orders;rows.append(account(orders,ready['time_s'],quote,c['id'],scene,symbol))
                if skipped:skips.append(dict(method=c['id'],session=scene,symbol=symbol,skipped=skipped))
            target=HERE/'protect_results/measurement'/f'{symbol}_{scene}.npz';target.parent.mkdir(parents=True,exist_ok=True);assert not target.exists()
            np.savez_compressed(target,**arrays);cache.append(dict(session=scene,symbol=symbol,**ref(target)))
        print(scene,'追撃保護完了',flush=True)
    save(HERE/'protect_results/結果.json',dict(rows=rows,cache=cache,skips=skips,plan=ref(HERE/'追撃保護計画.json'),API=0,real_orders=0))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=('prepare','run'));args=p.parse_args();{'prepare':prepare,'run':run}[args.stage]()
