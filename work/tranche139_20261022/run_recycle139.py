"""利益を実現した追撃枚数だけの補充を、元親の部分返済後にも検証する。"""

import argparse
import copy
import pickle
import subprocess
import sys
from pathlib import Path
import numpy as np
from common139 import HERE,ROOT,read,save,ref,configs,product,account,supplemental,features129,phases
import recycle139

MANAGER=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'


def settings():
    """
    機能: 固定配分と時計配分に二種の再追加と二上限を組み合わせる。
    引数: なし。
    返り値: list[dict]は8条件。利益確認済みの返済枚数だけ補充する。
    """
    base={c['id']:c for c in configs()};result=[]
    for stem in ('P','C'):
        for mode in ('extreme','pullback'):
            for rounds in (1,3):
                c=copy.deepcopy(base[stem+'04'])
                c.update(id=f'{stem}R{mode[0].upper()}{rounds}',base=stem+'04',recycle_mode=mode,recycle_rounds=rounds,
                    cooldown=60.,retrace_r=.25,recovery_r=.25,
                    name=('2枚先行' if stem=='P' else '時計配分')+'／利益返済分だけ'+('極値更新' if mode=='extreme' else '押し戻り再進行')+f'で再追加{rounds}回')
                result.append(c)
    return result


def prepare():
    """
    機能: 初回比較で再追加がほぼ不発動だった構造を修正する別試行を登録する。
    引数: なし。
    返り値: None。既存登録・会計は変更せず、新数値核を固定する。
    """
    p=copy.deepcopy(read(HERE/'試行計画_v2.json'))
    p.update(id='139_部分利確後の利益枚数再追加',name='部分利確後の実現利益枚数の補充',configs=settings(),
        question='元親途中返済後の追加禁止を、利益確定した追撃枚数だけ解除するとどうなるか。',
        change='再追加信用を費用後プラスの実返済分から作る。初回玉や含み益を信用にしない。',
        repeat_reason='初回46条件の再追加はTOPIX3場だけ、日経0件。発動しない条件から有効性を推定しないため別機構を作る。',
        compares_to=['139_複数追撃と初回待機と再追加'])
    p['spec']['management']={'条件':settings(),'信用':'各追撃返済の実損益から新規費用配賦と返済費用を控除しプラスなら返済枚数を一度だけ加える。約定時だけ消費。',
        '候補':'通常段を全消化していなくても利益返済済みなら補充可能。親の途中返済後は通常段追加を禁止し利益分補充だけを許可。',
        '制限':'初回玉が残り、新しい二市場支持が15秒持続し、利確後60秒経過。最大5枚、親最終返済最優先。',
        '価格':'利確時までの極値から0.25R進行、又は利確値から0.25R戻ってその戻り極値から0.25R再進行。'}
    for name in ('run_recycle139.py','recycle139.py'):
        r=ref(HERE/name);p['spec']['implementation'][r['path']]=r['sha256']
    p['evidence']=[ref(HERE/'recycle_artificial139_v2.json')]
    save(HERE/'再追加計画.json',p)
    for action in ('check','register'):
        r=subprocess.run([sys.executable,'-B','-X','utf8',str(MANAGER),action,'--proposal',str(HERE/'再追加計画.json')],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        save(HERE/f'再追加_{action}.json',dict(returncode=r.returncode,stdout=r.stdout,stderr=r.stderr));assert r.returncode==0,r.stderr[-2000:]
        print(action,'完了',flush=True)


def original(scene,symbol,manifest,extra_manifest):
    """
    機能: 既に保存された因果的な主担当・補完通知を読む。
    引数: scene/symbol(str)、manifest/extra_manifest(dict)は識別子と入力目録。
    返り値: tuple[ndarray,ndarray]は主担当・補完通知。新たに信号を生成しない。
    """
    r=next((x for x in manifest['references'] if x['session']==scene and x['symbol']==symbol),None)
    if r:
        path=Path(r['orders']['path']);assert ref(path)['sha256']==r['orders']['sha256'];prefix='' if r['prefix']=='なし' else r['prefix']
    else:
        r=next((x for x in extra_manifest['existing_orders'] if x['session']==scene and x['symbol']==symbol),None)
        if r:path=Path(r['path']);assert ref(path)['sha256']==r['sha256']
        else:
            r=next(x for x in read(HERE/'extra_results/結果.json')['generated'] if x['session']==scene and x['symbol']==symbol)
            path=ROOT/r['path'];assert ref(path)['sha256']==r['sha256']
        prefix=''
    with np.load(path,allow_pickle=False) as f:return f[prefix+'core_orders'],f[prefix+'extra_orders']


def run():
    """
    機能: 元候補の新規判断順に8条件を全47場で比較する。
    引数: なし。
    返り値: None。補充回数・利益・損失・全注文を別フォルダへ保存する。
    """
    plan=read(HERE/'再追加計画.json');assert read(HERE/'再追加_register.json')['returncode']==0;assert plan['configs']==settings()
    for path,sha in plan['spec']['implementation'].items():assert ref(ROOT/path)['sha256']==sha,path
    manifest=read(HERE/'manifest139.json');extra_manifest=read(HERE/'manifest139_extra.json');rows=[];cache=[];skips=[]
    for p in manifest['packets']+extra_manifest['packets']:
        assert ref(Path(p['path']))['sha256']==p['sha256'];packet=pickle.loads(Path(p['path']).read_bytes());scene=p['session']
        ins=features129.prices_for(packet,'mid');markets=features129.markets(ins)
        for symbol in ('NK225','TOPIX'):
            ready=ins[(scene,symbol)];quote=packet['quotes'][(scene,symbol)];market=markets[(scene,symbol)];phase=phases(ready);ts=ready['time_s']
            core,extra=original(scene,symbol,manifest,extra_manifest);extra=supplemental(extra,symbol);queue=[];arrays={}
            for kind,source in (('主担当',core),('補完',extra)):
                for pid in np.unique(source[:,2]) if len(source) else []:
                    orders=source[source[:,2]==pid];queue.append((int(orders[0,1]),kind,orders))
            for fixed in plan['configs']:
                c=copy.deepcopy(fixed);c.update(product(symbol));parts=[];last=-1
                for decision,kind,source in sorted(queue,key=lambda x:x[0]):
                    if decision<last:
                        skips.append(dict(method=c['id'],session=scene,symbol=symbol,parent=int(source[0,2]),decision=decision,active_until=last));continue
                    orders=source if kind=='補完' else recycle139.replay(ts,quote,ready['atr'],market,phase,source,c)
                    if len(orders):last=int(orders[-1,0]);parts.append(orders)
                orders=np.concatenate(parts) if parts else np.empty((0,10));orders=orders[np.argsort(orders[:,0],kind='stable')] if len(orders) else orders
                arrays[c['id']]=orders;row=account(orders,ts,quote,c['id'],scene,symbol)
                row['recycle_entries']=int(np.sum((orders[:,7]==1)&(orders[:,6]==1393))) if len(orders) else 0;rows.append(row)
            target=HERE/'recycle_results/measurement'/f'{symbol}_{scene}.npz';target.parent.mkdir(parents=True,exist_ok=True);assert not target.exists()
            np.savez_compressed(target,**arrays);cache.append(dict(session=scene,symbol=symbol,**ref(target)))
        print(scene,'利益枚数補充完了',flush=True)
    save(HERE/'recycle_results/結果.json',dict(rows=rows,cache=cache,skips=skips,plan=ref(HERE/'再追加計画.json'),API=0,real_orders=0))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('prepare','run'));args=parser.parse_args()
    {'prepare':prepare,'run':run}[args.stage]()
