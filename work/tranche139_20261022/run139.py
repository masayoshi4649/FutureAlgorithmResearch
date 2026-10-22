"""全条件の事前登録、既知45場と固定追加2場の分離検証を行う。"""

import argparse
import copy
import pickle
import subprocess
import sys
from pathlib import Path
import numpy as np
from common139 import HERE,ROOT,OLD,read,save,ref,configs,account,replay,features129,phases
import prepare_extra139

MANAGER=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'


def prepare():
    """
    機能: 条件・入力・数値源と比較範囲を金融再生前に登録する。
    引数: なし。
    返り値: None。金融再生を行わない。
    """
    known=read(HERE/'manifest139.json');extra=read(HERE/'manifest139_extra.json')
    sources=prepare_extra139.source_fingerprints()
    for path in (HERE/'run139.py',HERE/'common139.py',HERE/'engine139.py',OLD/'run137.py',
                 ROOT/'work/visual_pdca129_20261020/features129.py',ROOT/'work/daynight128_20261020/features128.py'):
        r=ref(path);sources[r['path']]=r['sha256']
    plan=dict(id='139_複数追撃と初回待機と再追加',name='玉別追撃の全因子と両銘柄比較',purpose='条件比較',
        question='段階分割・後玉狭幅・初回待機・利確後再追加は、赤字場と損失の深さを減らすか。初回損切り拡大は独立出口でも有効か。',
        change='00138の一回追加だけの出口比較を、複数段・再追加・初回待機・独立出口・TOPIXへ拡張。',
        repeat_reason='未測だった機構を別因子で確認。00137の狭い追加停止、00138の利益保護、00120の利益玉回転の残在庫失敗を参照。',
        compares_to=['138_追撃の順行後だけ玉別利益追尾'],configs=configs(),
        spec=dict(entry={'主担当':'既存T06日中、TOPIX T04夜、日経U06夜の因果的通知。保有中の候補は判断行で見送り。','追加':'二市場30/120秒支持と段階順行幅。各段以後の新peerと支持を積み直す。'},
            management={'条件':configs(),'初回待機':'元親部分利確のみ初回を維持、全返済は遵守。','再追加':'利益返済済みの追加枚数だけ、新極値と新しい支持を確認。UIDは再利用しない。'},
            exit={'親出口':'旧親の損切り・全返済を維持。玉別利益追尾を重ねる。','独立出口':'元入口だけを使い、各玉独立停止と利益追尾、予定場末全返済。初回1/1.5/2R停止を比較。次入口候補は保有中見送り。'},
            allocation={'銘柄':['NK225mini','TOPIXmini'],'上限':10,'主担当':[5,10],'小口':[1,2],
                '部分返済':'親総残枚数を先に四捨五入し、最大端数・古い玉順に残数を配分。1枚玉で部分返済が消える誤差を防ぐ。'},
            costs={'NK225mini':{'倍率':100,'片道十倍手数料':385},'TOPIXmini':{'倍率':1000,'片道十倍手数料':418},'端数':'注文ごと1円未満切捨て'},
            execution={'約定':'判断後の次正常ラージ気配。買ask/売bid。','初回幅':'判断時ATRと観測2呼値の大きい方、日経20円/TOPIX1pt。','実板':'実mini全期間板なし、約定代理。'},
            data={'sessions':known['sessions']+extra['sessions'],'input_manifests':[ref(HERE/'manifest139.json'),ref(HERE/'manifest139_extra.json')],
                '分離':'45場の比較後に固定46条件を追加2場へ適用。追加場の価格等を以前見たため完全未知とは呼ばない。','参照':known['references']},implementation=sources),
        evidence=[ref(HERE/'人工確認_独立.json'),ref(HERE/'人工確認_adapter.json')])
    for condition in plan['spec']['management']['条件']:
        for key in ('increments','steps'):
            if not condition[key]:condition[key]='追加なし'
    save(HERE/'試行計画_v2.json',plan)
    for action in ('check','register'):
        r=subprocess.run([sys.executable,'-B','-X','utf8',str(MANAGER),action,'--proposal',str(HERE/'試行計画_v2.json')],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        save(HERE/f'{action}_v2.json',dict(returncode=r.returncode,stdout=r.stdout,stderr=r.stderr));assert r.returncode==0,r.stderr[-2000:]
        print(action,'完了',flush=True)


def validated_plan():
    """
    機能: 登録と実装・条件指紋を実行直前に確認する。
    引数: なし。
    返り値: dictは固定計画。
    """
    p=read(HERE/'試行計画_v2.json');assert read(HERE/'register_v2.json')['returncode']==0;assert p['configs']==configs()
    for path,sha in p['spec']['implementation'].items():assert ref(ROOT/path)['sha256']==sha,path
    for r in p['spec']['data']['input_manifests']:assert ref(ROOT/r['path'])==r
    return p


def run(additional=False):
    """
    機能: 全46条件を両商品で運転し、追加2場は旧45場から分離して保存する。
    引数: additional(bool)は追加2場の検証指定。
    返り値: None。旧結果と素材を変更しない。
    """
    plan=validated_plan();manifest=read(HERE/('manifest139_extra.json' if additional else 'manifest139.json'))
    folder=HERE/('extra_results' if additional else 'results');rows=[];cache=[];skips=[];generated=[]
    if additional:
        assert (HERE/'results/結果.json').exists()
        prepare_extra139.authorize_sources(HERE/'試行計画_v2.json',HERE/'register_v2.json')
    for p in manifest['packets']:
        assert ref(Path(p['path']))['sha256']==p['sha256'];packet=pickle.loads(Path(p['path']).read_bytes());scene=p['session']
        ins=features129.prices_for(packet,'mid');markets=features129.markets(ins)
        for symbol in ('NK225','TOPIX'):
            ready=ins[(scene,symbol)];quotes=packet['quotes'][(scene,symbol)];market=markets[(scene,symbol)];clock=phases(ready)
            if additional:
                existing=next((x for x in manifest['existing_orders'] if x['session']==scene and x['symbol']==symbol),None)
                if existing:
                    assert ref(Path(existing['path']))['sha256']==existing['sha256']
                    with np.load(existing['path'],allow_pickle=False) as f:core=f['core_orders'];extra=f['extra_orders']
                else:
                    original=prepare_extra139.source_orders(packet,symbol);core=original['core_orders'];extra=original['extra_orders']
                    sourcepath=folder/'source'/f'{symbol}_{scene}.npz';sourcepath.parent.mkdir(parents=True,exist_ok=True);assert not sourcepath.exists()
                    np.savez_compressed(sourcepath,core_orders=core,extra_orders=extra)
                    generated.append(dict(session=scene,symbol=symbol,**ref(sourcepath),account=original['source_account']))
            else:
                original=next(x for x in manifest['references'] if x['session']==scene and x['symbol']==symbol)
                assert ref(Path(original['orders']['path']))['sha256']==original['orders']['sha256']
                prefix='' if original['prefix']=='なし' else original['prefix']
                with np.load(original['orders']['path'],allow_pickle=False) as f:core=f[prefix+'core_orders'];extra=f[prefix+'extra_orders']
            arrays={}
            for c in plan['configs']:
                if not additional and symbol=='NK225' and c['id'] in ('B5','B2'):
                    with np.load(OLD/'measurement'/f'{scene}.npz',allow_pickle=False) as saved:
                        orders=saved['B05' if c['id']=='B5' else 'B02'].copy()
                    orders[orders[:,8]==2,8]=999;skipped=[]
                else:orders,skipped=replay(ready,quotes,market,clock,core,extra,c,symbol)
                arrays[c['id']]=orders;rows.append(account(orders,ready['time_s'],quotes,c['id'],scene,symbol))
                if skipped:skips.append(dict(method=c['id'],session=scene,symbol=symbol,skipped=skipped))
            target=folder/'measurement'/f'{symbol}_{scene}.npz';target.parent.mkdir(parents=True,exist_ok=True);assert not target.exists()
            np.savez_compressed(target,**arrays);cache.append(dict(session=scene,symbol=symbol,**ref(target)))
        print(scene,'全条件完了',flush=True)
    save(folder/'結果.json',dict(rows=rows,cache=cache,skips=skips,generated=generated,plan=ref(HERE/'試行計画_v2.json'),API=0,real_orders=0,
        reused_accounts=0 if additional else 90,new_source_replays=len(generated)))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=('prepare','run','extra'));args=p.parse_args()
    if args.stage=='prepare':prepare()
    else:run(args.stage=='extra')
