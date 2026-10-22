"""追撃の利益保護を、入口・初回出口が同じ対照で登録して比較する。"""

import argparse
import copy
from pathlib import Path
import pickle
import subprocess
import sys
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT/'work/staged137_20261022'
sys.path.insert(0, str(OLD))
from run137 import read, save, ref, MANAGER, features129, account
import overlay138


def settings():
    """
    機能: 利益追尾の起動と幅、部分保護を十二条件ずつ固定する。
    引数: なし。
    返り値: list[dict]は固定2枚先行と時計配分の二系列・計24条件。
    """
    choices = []
    for activation in (.5, 1., 1.5, 2.):
        for width in (.25, .5):
            choices.append((f'A{int(activation*100):03d}W{int(width*100):03d}',activation,width,0.,width,0))
    choices.extend([('部分1',1.,.5,0.,.5,1),('部分2',1.,.5,0.,.5,2),
                    ('段階短縮',1.5,1.,2.,.5,0),('段階短縮2',2.,1.,3.,.5,0)])
    return [dict(id=prefix+'_'+name,base=base,activation=a,width=w,tighten_at=t,tight_width=tw,protect=n)
            for prefix,base in (('P','Wparent'),('C','CWparent')) for name,a,w,t,tw,n in choices]


def prepare():
    """
    機能: 元結果の再利用と変更箇所を明記し、再生前に重複照合・登録する。
    引数: なし。
    返り値: None。金融再生を行わない。
    """
    previous = read(OLD/'第三巡計画.json'); plan = copy.deepcopy(previous)
    paths = [HERE/'run138.py', HERE/'overlay138.py', OLD/'run137.py',
             ROOT/'work/visual_pdca129_20261020/features129.py', ROOT/'work/daynight128_20261020/features128.py']
    baseline = read(OLD/'結果3.json')
    plan.update(id='138_追撃の順行後だけ玉別利益追尾',name='初回玉の維持と追撃玉の利益追尾',purpose='条件比較',
        question='追撃直後の狭い損切りではなく、追撃自身が順行してからだけ狭く追尾すると利益返しを減らせるか。',
        change='WparentとCWparentの全新規・初回出口・補完出口を固定。追撃の順行後トレールを追加。',
        repeat_reason='00137は追加0.5R損切りで通常の押しを切った。00128の全玉順行保護とは異なり、後から建てた玉だけを保護する。',
        compares_to=['137_第三巡_追撃の停止幅を分離'],configs=settings(),sources=[ref(p) for p in paths],
        baselines=baseline['cache'], baseline_result=ref(OLD/'結果3.json'))
    plan['spec']['entry']={'元手法':'Wparent/CWparentの保存済み因果的通知。初回・追撃の全新規を維持。',
                          '初回後':'30秒以上後、両市場30秒0.05ATR・120秒0.2ATR支持を15秒維持、0.25R順行で追加。'}
    plan['spec']['management']={'初回玉':'元親の損切り・部分返済・利益追尾を維持。',
        '追撃':'追撃自身の建値から清算側BBOで最高順行を計算。初回判断時R=max(20円,ATR)固定。',
        '固定通知の限界':'決済後の再追加なし。仮想親と後続通知は固定。Goの実ミニ数量状態の完全再生ではない。'}
    plan['spec']['exit']={'条件':settings(),'追撃':'起動前は親出口のみ。起動後は最高順行から幅戻りで次正常行返済。部分保護は一度だけ。元親の返済が同じ行なら優先。',
        '場内':'元親の最終返済で全決済。将来の終了価格は判断へ使わない。','反例':'次気配の飛び越しで利益を保証しない。'}
    plan['spec']['allocation']={'商品':'NK225mini','片方向上限':10,'主担当上限':5,
        '先行':'P系列2枚、C系列は元の時計支持で1/2/5枚','追加':'最大5枚へ一度補充。部分保護は追撃全部又は最大1/2枚。',
        '補完':'00137と同一。全系列の同時実運用ではなく別々の仮想口座。'}
    plan['spec']['implementation']={ref(p)['path']:ref(p)['sha256'] for p in paths}
    plan['spec']['data']['baseline_result']=ref(OLD/'結果3.json')
    plan['spec']['data']['baseline_orders']=baseline['cache']
    plan['evidence']=[ref(HERE/'人工確認.json')]
    save(HERE/'試行計画.json',plan)
    for action in ('check','register'):
        r=subprocess.run([sys.executable,'-B','-X','utf8',str(MANAGER),action,'--proposal',str(HERE/'試行計画.json')],
                         cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        save(HERE/f'{action}.json',dict(returncode=r.returncode,stdout=r.stdout,stderr=r.stderr))
        assert r.returncode==0,r.stderr[-2000:]
        print(action,'完了',flush=True)


def run():
    """
    機能: 登録した24条件を既知45場で比較し、基準と入口・初期玉が同じか検査する。
    引数: なし。
    返り値: None。独立注文列・親会計を新規保存する。API・実注文なし。
    """
    p=read(HERE/'試行計画.json'); assert read(HERE/'register.json')['returncode']==0
    assert p['configs']==settings()
    for source in p['sources']: assert ref(ROOT/source['path'])==source
    assert ref(ROOT/p['baseline_result']['path'])==p['baseline_result']
    cache=[]; rows=[]
    for item in p['inputs']:
        assert ref(ROOT/item['input']['path'])==item['input']
        scene=item['session']; b=next(x for x in p['baselines'] if x['session']==scene)
        assert ref(ROOT/b['path'])=={k:b[k] for k in ('path','sha256')}
        packet=pickle.loads((ROOT/item['input']['path']).read_bytes());key=(scene,'NK225')
        ready=features129.prices_for(packet,'mid')[key];q=packet['quotes'][key];arrays={}
        with np.load(ROOT/b['path'],allow_pickle=False) as old:
            for c in p['configs']:
                original=old[c['base']]
                o=overlay138.replay(ready['time_s'],q,ready['atr'],original,c)
                assert np.array_equal(o[o[:,7]==1],original[original[:,7]==1])
                assert np.array_equal(o[o[:,8]!=1],original[original[:,8]!=1])
                a=account(o,ready['time_s'],q['bid'],q['ask'],c['id'],scene)
                assert abs(a['net']-float(np.sum(-o[:,3]*o[:,4]*o[:,5]*100.)-o[:,9].sum()))<1e-5
                rows.append(a);arrays[c['id']]=o
        target=HERE/'measurement'/f'{scene}.npz';target.parent.mkdir(exist_ok=True);assert not target.exists()
        np.savez_compressed(target,**arrays);cache.append(dict(session=scene,**ref(target)))
        print(scene,'完了',flush=True)
    save(HERE/'結果.json',dict(rows=rows,cache=cache,plan=ref(HERE/'試行計画.json'),API=0,real_orders=0))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('prepare','run'));args=parser.parse_args()
    {'prepare':prepare,'run':run}[args.stage]()
