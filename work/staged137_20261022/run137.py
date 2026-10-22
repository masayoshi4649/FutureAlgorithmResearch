"""日経ミニの試し玉・追撃・時間帯切替を、事前固定した条件で検証する。"""

import argparse
from datetime import datetime, time
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pickle
import subprocess
import sys
from zoneinfo import ZoneInfo
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANAGER = ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
PUBLIC = ROOT/'アルゴリズム調査/00137_日経ミニの段階投入と時間帯別運用'
os.environ['NUMBA_CACHE_DIR'] = str(HERE/'jit')
sys.path[:0] = [str(HERE), str(ROOT/'work/visual_pdca129_20261020'), str(ROOT/'work/daynight128_20261020')]
import features129
import overlay137


def read(path):
    """
    機能: 保存JSONを読む。
    引数: path(Path)は位置。
    返り値: dict又はlistは内容。
    """
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, value):
    """
    機能: 研究資料を日本語JSONで保存する。
    引数: path(Path)、value(dict又はlist)は位置と内容。
    返り値: None。金融結果の既存保存先は拒否する。
    """
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as f:
        json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False)
        f.write('\n')


def ref(path):
    """
    機能: 内容指紋と相対位置を取得する。
    引数: path(Path)は位置。
    返り値: dict[str,str]は参照。
    """
    with path.open('rb') as f: digest=hashlib.file_digest(f,'sha256').hexdigest()
    return dict(path=path.relative_to(ROOT).as_posix(),sha256=digest)


def configs():
    """
    機能: 金融前に定義した数量・時間帯の対照群を取得する。
    引数: なし。
    返り値: dictは固定通知10条件と時間帯の新造条件。
    """
    overlay=[]
    settings=[('B05',5,0,0.,0.,False),('B02',2,0,0.,0.,False),('B03',3,0,0.,0.,False),
              ('P02a',2,1,.25,0.,False),('P02b',2,1,.5,0.,False),
              ('C02a',2,2,.25,15.,False),('C02b',2,2,.5,15.,False),
              ('C03',3,2,.25,15.,False),('C01',1,2,.25,15.,False),
              ('CT02',2,2,.25,15.,True)]
    for cid,initial,mode,width,hold,adaptive in settings:
        overlay.append(dict(id=cid,initial=initial,mode=mode,width=width,hold=hold,adaptive=adaptive))
    regimes=[]
    for cid,initial,mode,clock,avoid in [('R05',5,0,'uniform',False),('R02',2,0,'uniform',False),
            ('RP02',2,1,'uniform',False),('RC02',2,2,'uniform',False),
            ('RT02',2,2,'time',False),('RA02',2,2,'time',True)]:
        regimes.append(dict(id=cid,initial_qty=initial,target_qty=5,add_mode=mode,
            mode=clock,avoid_shock=avoid,add_width=.25,exit_stop=1.,trail_start=1.,trail_width=.75,
            support_hold=15.,fee_per_contract=38.5,min_risk=20.))
    return dict(overlay=overlay,regime=regimes,
        hybrid=[dict(id='H_'+c['id'],base='B05',early=c['id']) for c in regimes])


def phases(ready):
    """
    機能: 価格を使わず既知市場時計を原行へ対応する。
    引数: ready(dict)は一場入力。
    返り値: ndarray[int64]は十二時間区分。米欧夏時間は地域別に処理する。
    """
    ts=ready['time_s']; date=datetime.fromisoformat(ready['session'].split('_')[0]).date()
    if ready['session'].endswith('_Day'):
        midnight=datetime.combine(date,time(),ZoneInfo('Asia/Tokyo')).timestamp()
        minutes=(ts-midnight)/60.
        return np.select([minutes<540,minutes<690,minutes<750,minutes<930],[0,1,2,3],default=4).astype(np.int64)
    start19=datetime.combine(date,time(19),ZoneInfo('Asia/Tokyo')).timestamp()
    us=ready['us_open']; london=datetime.combine(date,time(16,30),ZoneInfo('Europe/London')).timestamp()
    return np.select([ts<start19,ts<us-4500,ts<us-2700,ts<us-900,ts<us+900,ts<london],
                     [5,6,7,8,9,10],default=11).astype(np.int64)


def references():
    """
    機能: 旧43場と固定追加2場の原行入力・現行通知を結び付ける。
    引数: なし。
    返り値: list[dict]は同一45場の参照。旧入力を変更しない。
    """
    old=read(ROOT/'work/daynight128_20261020/入力準備.json')['packets']
    new=read(ROOT/'work/update132_20261021/inputs_v1/input_manifest.json')['packets']
    ledgers={folder:read(ROOT/f'work/regime131_20261020/{folder}/全条件の会計.json') for folder in ('round3','round4')}
    newer=read(ROOT/'work/update132_20261021/results/追加セッションの会計.json')
    result=[]
    for p in old+new:
        scene=p['session']; method='T06' if scene.endswith('_Day') else 'U06'; folder='round3' if method=='T06' else 'round4'
        candidates=newer['cache'] if scene in ('2026-10-20_Night','2026-10-21_Day') else ledgers[folder]['cache']
        c=next(x for x in candidates if x['session']==scene and x['symbol']=='NK225')
        result.append(dict(session=scene,input={k:p[k] for k in ('path','sha256')},
            orders={k:c[k] for k in ('path','sha256')},prefix='なし' if candidates is newer['cache'] else method+'__'))
    assert len(result)==45 and len({x['session'] for x in result})==45
    return result


def account(orders, times, bid, ask, label, scene):
    """
    機能: 各脚の注文から親損益と方向別枚数を独立積み上げする。
    引数: orders/times/bid/ask(ndarray)、label/scene(str)は約定と識別子。
    返り値: dictは費用後会計と親・脚別内訳。倍率100円、上限各方向10枚。
    """
    orders=np.asarray(orders); parents={}; tickets={}; longs=shorts=0; maximum=0; entries=0; quantity=0
    for o in orders:
        i,d,cid,side,qty=(int(v) for v in o[:5]); px=o[5]; new=int(o[7]); leg=int(o[8]); paid=int(o[9])
        assert 0<=d<i<len(times) and side in (-1,1) and qty>0 and paid==qty*385//10
        assert abs(px-(ask[i] if side>0 else bid[i]))<1e-7
        p=parents.setdefault(cid,dict(id=cid,gross=0.,fees=0.,side=side,entry=i,exit=i,legs={}))
        q=p['legs'].setdefault(leg,dict(gross=0.,fees=0.,entries=0,quantity=0))
        p['fees']+=paid; q['fees']+=paid;p['exit']=i
        key=(cid,leg)
        if new:
            assert key not in tickets or tickets[key][0]==0
            tickets[key]=[qty,px,side]; entries+=1; quantity+=qty
            q['entries']+=1;q['quantity']+=qty
            if side>0:longs+=qty
            else:shorts+=qty
        else:
            assert key in tickets
            old=tickets[key]; assert old[2]==-side and old[0]>=qty
            gain=old[2]*(px-old[1])*qty*100.
            old[0]-=qty;p['gross']+=gain;q['gross']+=gain
            if side<0:longs-=qty
            else:shorts-=qty
        assert 0<=longs<=10 and 0<=shorts<=10
        maximum=max(maximum,longs,shorts)
    assert longs==shorts==0
    for p in parents.values():
        p['net']=p['gross']-p['fees']
        for q in p['legs'].values():q['net']=q['gross']-q['fees']
    values=np.array([p['net'] for p in parents.values()]); gains=float(values[values>0].sum()); losses=float(-values[values<0].sum())
    return dict(method=label,session=scene,kind=scene.rsplit('_',1)[1],profit=gains,loss=losses,net=gains-losses,
        gross=sum(p['gross'] for p in parents.values()),fees=sum(p['fees'] for p in parents.values()),
        entries=entries,parents=list(parents.values()),max_per_side=maximum,quantity=quantity)


def prepare():
    """
    機能: 全入力・条件・数値実装を固定して重複照合用計画を作る。
    引数: なし。
    返り値: None。金融再生はしない。
    """
    paths=[Path(__file__),HERE/'overlay137.py',HERE/'regime_engine137.py',
           ROOT/'work/visual_pdca129_20261020/features129.py',ROOT/'work/daynight128_20261020/features128.py']
    plan=dict(id='137_日経mini段階投入と市場時計',name='日経ミニの段階投入と時間帯別運用',purpose='条件比較',
        question='一括投入を少量先行と支持再確認の追加に変えると損失と赤字場を減らせるか。米国前も参加する時計切替は有効か。',
        change='日経mini上限10へ変更。既存因果通知の5枚対照と少量・追撃の数量層を比較し、独立した共通支持の時間帯モデルと米前追加を比較する。',
        repeat_reason='00128の弱支持減枚、00129の順行増玉では勝ちも削った。今回は追加玉独立停止、現行通知固定の数量分解と市場時計を分離する。',
        compares_to=['132_v2_採用条件の追加2場検証'],configs=configs(),inputs=references(),sources=[ref(p) for p in paths],
        spec=dict(entry={'固定通知':'00132の主担当と補完。既存因果的通知を仮想層で保持し、当時発生した行だけ読み込む。','新造':'両市場120秒支持と30秒逆流なし。具体条件は実装・configsを固定。'},
            management={'追加':'順行だけと、30秒以上後の新観測から支持を確認する対照。追加玉0.5R停止。','既存影':'数量変更が仮想判断へ影響しない制御比較で、Goのmini状態の完全再現ではない。'},
            exit={'固定通知':'元の実返済通知を維持、各脚比例整数返済。追撃専用停止。','新造':'1R停止、1R順行後0.75R追尾、二市場反転持続、場内返済。'},
            allocation={'product':'NK225mini','cap':10,'primary':5,'probe':[1,2,3],'追加担当':'従来micro数量を半分・整数化し最大5。','hybrid':'米前専用は現物開始15分前に全返済。主担当開始後と重複しない。'},
            costs={'multiplier':100,'fee':38.5,'rounding':'注文ごと1円未満切捨て'},
            execution={'fill':'判断後の次正常原行ラージBBO代理','slippage':'5秒最悪約定は今回は加えない','clock':'原価格時計・相手同秒以後は不参照'},
            data={'sessions':[r['session'] for r in references()],
                  'input_manifests':[ref(ROOT/'work/daynight128_20261020/入力準備.json'),ref(ROOT/'work/update132_20261021/inputs_v1/input_manifest.json')],
                  'input_references':references(),'未知':'既知標本内比較で将来成績保証や確度の校正とはしない。'},
            implementation={ref(p)['path']:ref(p)['sha256'] for p in paths}))
    save(HERE/'試行計画_v3.json',plan)
    for action in ('check','register'):
        r=subprocess.run([sys.executable,'-B','-X','utf8',str(MANAGER),action,'--proposal',str(HERE/'試行計画_v3.json')],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        save(HERE/f'{action}_v3.json',dict(returncode=r.returncode,stdout=r.stdout,stderr=r.stderr))
        assert r.returncode==0,r.stderr[-2000:]
        print(action,'完了',flush=True)


def run():
    """
    機能: 登録済み条件を全45場で実行する。
    引数: なし。
    返り値: None。注文配列と全場会計を新規保存し、実注文・API接続はしない。
    """
    import regime_engine137
    p=read(HERE/'試行計画_v3.json'); assert read(HERE/'register_v3.json')['returncode']==0
    assert p['configs']==configs()
    for x in p['sources']:assert ref(ROOT/x['path'])==x
    assert not (HERE/'結果.json').exists()
    rows=[]; cache=[]
    for item in p['inputs']:
        for typ in ('input','orders'):assert ref(ROOT/item[typ]['path'])==item[typ]
        packet=pickle.loads((ROOT/item['input']['path']).read_bytes()); scene=item['session']; key=(scene,'NK225')
        ins=features129.prices_for(packet,'mid'); market=features129.markets(ins)[key]
        ready=ins[key]; q=packet['quotes'][key]; ts=ready['time_s']; phase=phases(ready)
        prefix='' if item['prefix']=='なし' else item['prefix']
        with np.load(ROOT/item['orders']['path'],allow_pickle=False) as old:
            core=old[prefix+'core_orders'];extra=old[prefix+'extra_orders']
        arrays={}; byid={}
        for c in p['configs']['overlay']:
            o=overlay137.replay(ts,q,ready['atr'],market,phase,core,extra,c)
            byid[c['id']]=o;arrays[c['id']]=o
            rows.append(account(o,ts,q['bid'],q['ask'],c['id'],scene))
        for c in p['configs']['regime']:
            o,e=regime_engine137.simulate(ts,q['bid'],q['ask'],q['quote_valid'],ready['atr'],market,phase,
                ready['start'],ready['limit'],ready['us_open'],c)
            arrays[c['id']]=o;arrays[c['id']+'_events']=e
            rows.append(account(o,ts,q['bid'],q['ask'],c['id'],scene))
            if scene.endswith('_Night'):
                early,ee=regime_engine137.simulate(ts,q['bid'],q['ask'],q['quote_valid'],ready['atr'],market,phase,
                    ready['start'],ready['us_open']-900.,ready['us_open'],c)
                early=early.copy();early[:,2]+=20000;early[:,8]+=10
                joined=np.concatenate((byid['B05'],early));joined=joined[np.argsort(joined[:,0],kind='stable')]
            else:
                early=np.empty((0,10));joined=byid['B05'].copy()
            cid='H_'+c['id'];arrays[cid]=joined;arrays[cid+'_early']=early
            rows.append(account(joined,ts,q['bid'],q['ask'],cid,scene))
        path=HERE/'measurement'/f'{scene}.npz';path.parent.mkdir(exist_ok=True)
        assert not path.exists();np.savez_compressed(path,**arrays)
        cache.append(dict(session=scene,**ref(path)))
        print(scene,'完了',flush=True)
    save(HERE/'結果.json',dict(rows=rows,cache=cache,plan=ref(HERE/'試行計画_v3.json'),API=0,real_orders=0))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('prepare','run'))
    args=parser.parse_args();{'prepare':prepare,'run':run}[args.stage]()
