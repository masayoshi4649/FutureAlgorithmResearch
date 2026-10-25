"""先着占有で消えた旧利益を診断し、独立枠の同時運転と相対価格取引を比較する。"""

import argparse
import importlib.util
import json
import pickle
from pathlib import Path
import numpy as np
import run140_v2 as old
import active140_v2 as active
import reentry140
import pair140

HERE,ROOT=old.HERE,old.ROOT


def prepare():
    """
    機能: 同時運転・独立担当の保存修正・ペア取引を金融前に固定して登録する。
    引数: なし。
    返り値: None。第1巡の原結果・計画は保持する。
    """
    plan=old.read(HERE/'試行計画140_v2.json')
    plan.update(id='140_先着損失の診断と独立枠と整数ペア',name='独立した担当枠と相対価格の再検証',purpose='条件比較',
        question='旧勝ちを奪う占有競合をなくしても活動と安定性を両立できるか。元本差を抑えたペアは別の収益源か。',
        change='第1巡Cは先着親のみ採用。第2巡Sは旧B5最大5枚と新担当最大5枚を独立同時運転し同方向合計10枚まで。ペア9条件を独立口座で追加。',
        repeat_reason='NK C36は追加利益638638円より失った旧利益681626円が大きい。TOPIX C33改善の大半も旧負けの占有除外。独立枠で機会損失と重複損失を分ける。A単独保存キーの誤りも修正し全単独と本来R12を保存。',
        compares_to=['140_商品別の参加拡大と利益後再参加_v2'])
    plan['configs']['pair']=json.loads(json.dumps(pair140.configurations(),ensure_ascii=False))
    plan['spec']['entry']['相対価格']=plan['configs']['pair']
    plan['spec']['management']['同時運転']='B5とAを別の実担当として各々の損益・再準備を管理する。未来の別担当新規で候補を消さない。'
    plan['spec']['allocation']['独立枠']='B5最大5、A最大5。同方向合計10まで、逆方向併存も総建枚数を明示。ペアは別口座で各商品上限10。'
    plan['spec']['execution']['ペア']='判断時に整数元本整合。各脚それぞれの判断後の次正常BBOへ約定し、片脚遅れを記録。'
    plan['spec']['data']['input_manifests'].append(old.ref(HERE/'known/結果140_表示訂正版.json'))
    for path in (Path(__file__),HERE/'pair140.py'):
        item=old.ref(path);plan['spec']['implementation'][item['path']]=item['sha256']
    plan['evidence']=[old.ref(HERE/'オプション保存資格140_v2.json')]
    old.save(HERE/'第二巡計画140.json',plan)
    manager=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
    spec=importlib.util.spec_from_file_location('manager140round2',manager);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    checked=mod.check(plan)
    old.save(HERE/'第二巡照合140.json',dict(proposal_complete=checked['proposal_complete'],issues=checked['提案不完全理由'],matches=[{k:v for k,v in x.items() if k in ('id','kind','name')} for x in checked['matches']]))
    assert checked['proposal_complete']
    mod.check=lambda proposal: checked
    registered=mod.store_trial(plan)
    old.save(HERE/'第二巡登録140.json',dict(returncode=0,id=registered['id'],plan=old.ref(HERE/'第二巡計画140.json')))
    print('第二巡登録完了',flush=True)


def parallel(base, addon):
    """
    機能: 同時運転の独立枠を識別子を分けて時系列合成する。
    引数: base/addon(ndarray)は各5枚以下の約定列。
    返り値: ndarrayは合成列。保有上限は後段の逐次独立会計で検証する。
    """
    extra=addon.copy()
    if len(extra):extra[:,2]+=3_000_000
    result=np.concatenate((base,extra))
    return result[np.argsort(result[:,0],kind='stable')]


def pair_account(result,packet,method,split):
    """
    機能: ペアの完結利益損失と脚ごとの収支を一行にする。
    引数: result/packet(dict)、method/split(str)は保存する比較結果。
    返り値: dictはペア合計と各脚。単独商品の成績へ脚を混入しない。
    """
    s=result['summary'];c=result['campaigns'];o=result['orders'];d=result['prepared']
    return dict(method=method,session=packet['session'],symbol='PAIR',kind=packet['session'].split('_')[1],split=split,
        profit=s['pair_net_profit'],loss=s['pair_net_loss'],net=s['net'],gross=s['gross_profit']-s['gross_loss'],fees=s['fees'],
        entries=s['pairs'],quantity=int(o[o[:,10]==1,7].sum()) if len(o) else 0,max_per_side=int(o[:,7].max()) if len(o) else 0,
        first_minutes=float((c[0,1]-d['start'])/60.) if len(c) else None,held_minutes=float(np.sum(c[:,13]-c[:,1])/60.) if len(c) else 0.,
        nk_net=s['by_symbol']['NK225']['net'],topix_net=s['by_symbol']['TOPIX']['net'],pair_count=s['pairs'],
        mismatch=s['maximum_notional_mismatch'],single_leg_seconds=s['single_leg_seconds'])


def run(additional=False):
    """
    機能: 独立枠とペアを既知場で比較し、追加場では固定候補のみ確認する。
    引数: additional(bool)は保留3場の指定。
    返り値: None。旧結果は再利用し、今回担当の約定を新保存先へ残す。
    """
    plan=old.read(HERE/'第二巡計画140.json');assert old.read(HERE/'第二巡登録140.json')['returncode']==0
    for path,sha in plan['spec']['implementation'].items():assert old.ref(ROOT/path)['sha256']==sha,path
    manifest=old.read(HERE/('inputs/input_manifest.json' if additional else 'known_manifest140.json'))
    first=old.read(HERE/('new/結果140.json' if additional else 'known/結果140_表示訂正版.json'))
    base_cache={(v['session'],v['symbol']):v for v in first['cache']}
    selected=old.read(HERE/'固定候補140.json') if additional else None
    folder=HERE/('round2_new' if additional else 'round2_known');rows=[];pairs=[];files=[]
    for item in manifest['packets']:
        path=Path(item['path']);path=path if path.is_absolute() else ROOT/path
        assert old.ref(path)['sha256']==item['sha256']
        packet=pickle.loads(path.read_bytes());scene=packet['session'];base={};arrays={s:{} for s in ('NK225','TOPIX')}
        for symbol in arrays:
            item_base=base_cache[(scene,symbol)];assert old.ref(ROOT/item_base['path'])['sha256']==item_base['sha256']
            with np.load(ROOT/item_base['path']) as f:base[symbol]=f['B5']
        for window in (10,20,40):
            configs=[c for c in plan['configs']['active'] if c['window']==window]
            if additional and not any(c['id'] in selected[s] or 'S'+c['id'][1:] in selected[s] for c in configs for s in arrays):continue
            prepared=active.prepare(packet,window)
            for c in configs:
                for symbol in arrays:
                    simultaneous='S'+c['id'][1:]
                    if additional and c['id'] not in selected[symbol] and simultaneous not in selected[symbol]:continue
                    orders,_=active.replay(prepared[symbol],c)
                    arrays[symbol][c['id']]=orders
                    arrays[symbol][simultaneous]=parallel(base[symbol],orders)
        if not additional:
            inputs=old.common.features129.prices_for(packet,'mid');market=old.common.features129.markets(inputs)
            config=plan['configs']['reentry'][-1]
            for symbol in arrays:
                key=scene,symbol;r=packet['inputs'][key]
                cfg={k:v for k,v in config.items() if k not in ('id','name')};cfg.update(old.common.product(symbol))
                arrays[symbol]['R12']=reentry140.replay(r['time_s'],packet['quotes'][key],r['atr'],market[key],base[symbol],r['limit'],cfg)[0]
        for symbol,content in arrays.items():
            if additional:content={k:v for k,v in content.items() if k in selected[symbol]}
            if not content:continue
            for method,orders in content.items():rows.append(old.account(orders,packet,symbol,method,'保留3場' if additional else '既知47場'))
            dest=folder/'measurement'/f'{symbol}_{scene}.npz';dest.parent.mkdir(parents=True,exist_ok=True)
            assert not dest.exists();np.savez_compressed(dest,**content);files.append(dict(session=scene,symbol=symbol,**old.ref(dest)))
        prepared_pair={}
        for c in plan['configs']['pair']:
            if additional and c['id'] not in selected.get('PAIR',[]):continue
            if c['window'] not in prepared_pair:prepared_pair[c['window']]=pair140.prepare(packet,c['window'])
            result=pair140.replay(packet,c,prepared_pair[c['window']])
            pairs.append(pair_account(result,packet,c['id'],'保留3場' if additional else '既知47場'))
            dest=folder/'pair'/f"{c['id']}_{scene}.npz";dest.parent.mkdir(parents=True,exist_ok=True)
            assert not dest.exists();np.savez_compressed(dest,orders=result['orders'],campaigns=result['campaigns'])
        print(scene,'第二巡完了',flush=True)
    old.save(folder/'結果140.json',dict(rows=rows,pair_rows=pairs,cache=files,plan=old.ref(HERE/'第二巡計画140.json'),API=0,real_orders=0))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['prepare','known','new']);args=p.parse_args()
    prepare() if args.stage=='prepare' else run(args.stage=='new')
