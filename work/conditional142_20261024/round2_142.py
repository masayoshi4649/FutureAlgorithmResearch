"""方向選択に活動中の再参加を接続し、低い実保有率の構造を検証する。"""

import argparse
import importlib.util
import json
import pickle
from pathlib import Path
import numpy as np
import run142 as first

HERE,ROOT,prior=first.HERE,first.ROOT,first.prior


def register():
    """
    機能: 参加不足と残損失の診断を起点に、第二巡の売買条件を事前登録する。
    引数: なし。
    返り値: None。初巡の源コードと金融結果は書き換えない。
    """
    import patrol_trader142 as patrol
    import night_trader142_v2 as night
    plan=prior.read(HERE/'試行計画142.json')
    plan.update(id='142_第二巡_活動時の早期参加と再参加と方向不一致の数量選択',name='判断層を持つ巡回担当と既存主担当の併用',purpose='条件比較',
        change='保有率の不足を受け40分準備と米国時刻待機を外した短期判断担当12条件。活発時の追従/反発/反転と無動意待機を別選択。旧夜票の短期反証時は小玉にする2条件。',
        repeat_reason='第一巡は方向切替で一部損失を減らしたが日経夜J04の公式780分保有率は平均4.63%。ユーザーは全場平均概ね50%を目安とし、深夜無動意での帳尻保有は不要と訂正。',
        compares_to=['142_状況判断と売買を分離した時間軸原板リスク切替'])
    plan['configs']=dict(patrol=patrol.configurations(),night=[c for c in night.configurations() if c['id'] in ('Z06','Z07')])
    plan['spec']['entry']['第二巡']='巡回担当は40分文脈が未公開でも正常原板の二市場30/120秒を用い、公開後は中期支持/反対/混在で判断。活動資格は自己相手とも直近300秒幅がmax(4呼値,3気配差)以上。'
    plan['spec']['management']['第二巡']='注文・保有状態は巡回売買層、入口/保有/反転指示は巡回判断層。閉じた後も新しい合意があれば再参加。50%を満たすための強制保有や未来の無動意除外はしない。'
    plan['spec']['management']['併用第二巡']='日経はB5主担当5枚と巡回5枚を独立枠で併用。夜はZ04とZ06の基準を比較。TOPIXは前回M1の先着主担当最大5枚と巡回5枚を独立併用。片方向最大10。'
    plan['spec']['exit']['第二巡']='巡回は停止・追尾・短期否定・中期否定・反対方向合意を政策別に判定。返済完了後にのみ反転新規を予約、同一行の反転約定はしない。場末limit次正常原行で全清算。'
    plan['spec']['allocation']['第二巡']='巡回初回2枚又は中期支持時3枚、保護後最大5枚。基準と合わせ片方向最大10。補完の短期反証時半減は元リスク枚数を決定してからfloor半分・最低1。'
    plan['spec']['data']['活動率']='公式Day420分/Night780分を分母とする建玉が1枚以上の時間。各商品全50場の率の単純平均を主値とし、昼夜内訳・実保有枚数・時間加重率を併記。概ね50%は目安で、無動意を無理に保有しない。'
    plan['spec']['data']['input_manifests'].append(prior.ref(HERE/'結果142.json'))
    for name in ('round2_142.py','patrol_features142.py','patrol_selector142.py','patrol_trader142.py','night_selector142_v2.py','night_trader142_v2.py'):
        ref=prior.ref(HERE/name);plan['spec']['implementation'][ref['path']]=ref['sha256']
    plan=json.loads(json.dumps(plan,ensure_ascii=False));prior.save(HERE/'第二巡計画142.json',plan)
    manager=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
    spec=importlib.util.spec_from_file_location('manager142second',manager);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    checked=mod.check(plan);prior.save(HERE/'第二巡照合142.json',dict(proposal_complete=checked['proposal_complete'],issues=checked['提案不完全理由'],matches=[{k:v for k,v in x.items() if k in ('id','kind','name')} for x in checked['matches']]))
    assert checked['proposal_complete'];mod.check=lambda proposal:checked
    saved=mod.store_trial(plan);prior.save(HERE/'第二巡登録142.json',dict(returncode=0,id=saved['id'],plan=prior.ref(HERE/'第二巡計画142.json')))
    print('第二巡の事前登録完了',flush=True)


def run():
    """
    機能: 短期巡回・基準併用・夜間数量選択を全50場で会計する。
    引数: なし。
    返り値: None。第一巡を再生せず保存済み基準注文を利用する。
    """
    import patrol_features142 as features
    import patrol_trader142 as patrol
    import night_trader142_v2 as night
    plan=prior.read(HERE/'第二巡計画142.json');assert prior.read(HERE/'第二巡登録142.json')['returncode']==0
    for path,sha in plan['spec']['implementation'].items():assert prior.ref(ROOT/path)['sha256']==sha,path
    old=prior.read(HERE/'結果142.json');cache={(r['session'],r['symbol']):r for r in old['cache']}
    packets,_,_=first.first.material();rows=[];files=[]
    for item in packets:
        scene=item['session'];destination=HERE/'round2/results'/f'{scene}.json'
        if destination.exists():
            saved=prior.read(destination);rows.extend(saved['rows']);files.extend(saved['cache']);continue
        path=Path(item['path']);path=path if path.is_absolute() else ROOT/path
        assert prior.ref(path)['sha256']==item['sha256'];packet=pickle.loads(path.read_bytes())
        data,inputs,market,history=first.prepared(packet);early=features.prepare(packet,data)
        scene_rows=[];scene_cache=[]
        for symbol in ('NK225','TOPIX'):
            key=scene,symbol;previous=first.first.load_arrays(cache[key]);base=previous['B5'];arrays={};traces={}
            if symbol=='NK225':
                for config in plan['configs']['night']:
                    if scene.endswith('_Day'):arrays[config['id']]=base.copy()
                    else:
                        arrays[config['id']],notes=night.replay(inputs[key],packet['quotes'][key],history[key],market[key],base[base[:,8]!=999],config,data[symbol]['features'])
                        prior.save(HERE/'round2/notes'/f'{symbol}_{scene}_{config["id"]}.json',notes)
            main=(previous['Z04'] if scene.endswith('_Night') else base) if symbol=='NK225' else previous['M1']
            small=(arrays['Z06'] if scene.endswith('_Night') else base) if symbol=='NK225' else previous['M1']
            for config in plan['configs']['patrol']:
                method=config['id'];orders,_,trace=patrol.replay(early[symbol],config)
                arrays[method]=orders;traces[method]=trace
                arrays['K'+method[1:]]=first.first.round2_140.parallel(main,orders)
                if symbol=='NK225':arrays['L'+method[1:]]=first.first.round2_140.parallel(small,orders)
            for method,orders in arrays.items():scene_rows.append(prior.account(orders,packet,symbol,method,'診断3場' if scene>='2026-10-22_Night' else '対照47場'))
            dest=HERE/'round2/measurement'/f'{symbol}_{scene}.npz';dest.parent.mkdir(parents=True,exist_ok=True);np.savez_compressed(dest,**arrays)
            scene_cache.append(dict(session=scene,symbol=symbol,**prior.ref(dest)))
            dest=HERE/'round2/traces'/f'{symbol}_{scene}.npz';dest.parent.mkdir(parents=True,exist_ok=True);np.savez_compressed(dest,**traces)
        prior.save(destination,dict(rows=scene_rows,cache=scene_cache));rows.extend(scene_rows);files.extend(scene_cache)
        print(scene,'第二巡の再参加検証完了',flush=True)
    prior.save(HERE/'第二巡結果142.json',dict(rows=rows,cache=files,plan=prior.ref(HERE/'第二巡計画142.json')))
    prior.save(HERE/'結果142_二巡統合.json',dict(rows=old['rows']+rows,cache=old['cache']+files,API=0,real_orders=0))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['register','run']);args=parser.parse_args()
    register() if args.stage=='register' else run()
