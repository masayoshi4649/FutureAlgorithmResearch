"""反復売買の気配差負担を診断し、中期の支持状態で保有と再参加を選ぶ。"""

import argparse
import importlib.util
import json
import pickle
from pathlib import Path
import numpy as np
import run142 as first
from portfolio142 import merge_patrol

HERE,ROOT,prior=first.HERE,first.ROOT,first.prior


def register():
    """
    機能: 全親の気配差分解を根拠に、第三巡の状態管理を金融前登録する。
    引数: なし。
    返り値: None。第二巡の実装と結果は保持する。
    """
    import regime_trader142 as trader
    plan=prior.read(HERE/'第二巡計画142_v2.json')
    plan.update(id='142_第三巡_短期往復の費用分解と中期支持状態の維持',name='支持状態の維持と再参加の回復確認',purpose='条件比較',
        change='P04の全親を状態別・中値変化・気配差・手数料に分解。中期合意だけの入口にも優位が見えず、短期合議ごとの反復から、支持水準を維持する状態管理へ変更する。',
        repeat_reason='保有率を増やした第二巡は気配差負担が主因で悪化。時刻による強制保有ではなく、同じ支持状態内の往復を減らし、失敗後の再参加には回復を要求して再検証する。',
        compares_to=['142_第二巡_活動時の早期参加と再参加と方向不一致の数量選択_v2'])
    plan['configs']=dict(regime=trader.configurations())
    plan['spec']['entry']['第三巡']='公開20分支持水準と二市場合意を判断層へ渡す。追従参加、押しからの再進行、失敗後の支持回復を別政策として比較する。'
    plan['spec']['management']['第三巡']='公開支持位置が保たれる間は短期反対だけで反復決済しない。新規/再新規の状態と保有継続を分け、支持位置破綻と保険停止追尾で降りる。'
    plan['spec']['management']['第三巡併用']='日経は昼B5・夜Z04、TOPIXはM1の最大5枚枠に新担当最大5枚を独立合成。新親IDは500万台で衝突を禁止。'
    plan['spec']['data']['input_manifests'].extend([prior.ref(HERE/'第二巡結果142.json'),prior.ref(HERE/'P04全親の状態別と気配差分解142.json')])
    for name in ('round3_142.py','regime_features142.py','regime_selector142.py','regime_trader142.py'):
        item=prior.ref(HERE/name);plan['spec']['implementation'][item['path']]=item['sha256']
    plan=json.loads(json.dumps(plan,ensure_ascii=False));prior.save(HERE/'第三巡計画142.json',plan)
    manager=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
    spec=importlib.util.spec_from_file_location('manager142third',manager);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    checked=mod.check(plan);prior.save(HERE/'第三巡照合142.json',dict(proposal_complete=checked['proposal_complete'],issues=checked['提案不完全理由'],matches=[{k:v for k,v in x.items() if k in ('id','kind','name')} for x in checked['matches']]))
    assert checked['proposal_complete'];mod.check=lambda proposal:checked
    saved=mod.store_trial(plan);prior.save(HERE/'第三巡登録142.json',dict(returncode=0,id=saved['id'],plan=prior.ref(HERE/'第三巡計画142.json')))
    print('第三巡の事前登録完了',flush=True)


def run():
    """
    機能: 中期状態担当と既存担当の単体・併用を全50場で会計する。
    引数: なし。
    返り値: None。全判断理由と全注文を保存する。
    """
    import patrol_features142 as early
    import regime_features142 as features
    import regime_trader142 as trader
    plan=prior.read(HERE/'第三巡計画142.json');assert prior.read(HERE/'第三巡登録142.json')['returncode']==0
    for path,sha in plan['spec']['implementation'].items():assert prior.ref(ROOT/path)['sha256']==sha,path
    origin=prior.read(HERE/'結果142.json');cache={(r['session'],r['symbol']):r for r in origin['cache']}
    previous=prior.read(HERE/'結果142_二巡統合.json');packets,_,_=first.first.material();rows=[];files=[]
    for item in packets:
        scene=item['session'];output=HERE/'round3/results'/f'{scene}.json'
        if output.exists():
            saved=prior.read(output);rows.extend(saved['rows']);files.extend(saved['cache']);continue
        path=Path(item['path']);path=path if path.is_absolute() else ROOT/path
        assert prior.ref(path)['sha256']==item['sha256'];packet=pickle.loads(path.read_bytes())
        data,_,_,history=first.prepared(packet);ready=features.prepare(packet,early.prepare(packet,data),history)
        session_rows=[];session_cache=[]
        for symbol in ('NK225','TOPIX'):
            key=scene,symbol;old=first.first.load_arrays(cache[key]);arrays={};traces={}
            main=(old['Z04'] if scene.endswith('_Night') else old['B5']) if symbol=='NK225' else old['M1']
            for config in plan['configs']['regime']:
                method=config['id'];orders,_,trace=trader.replay(ready[symbol],config)
                arrays[method]=orders;arrays['V'+method[1:]]=merge_patrol(main,orders);traces[method]=trace
            for method,orders in arrays.items():session_rows.append(prior.account(orders,packet,symbol,method,'診断3場' if scene>='2026-10-22_Night' else '対照47場'))
            dest=HERE/'round3/measurement'/f'{symbol}_{scene}.npz';dest.parent.mkdir(parents=True,exist_ok=True);np.savez_compressed(dest,**arrays)
            session_cache.append(dict(session=scene,symbol=symbol,**prior.ref(dest)))
            dest=HERE/'round3/traces'/f'{symbol}_{scene}.npz';dest.parent.mkdir(parents=True,exist_ok=True);np.savez_compressed(dest,**traces)
        prior.save(output,dict(rows=session_rows,cache=session_cache));rows.extend(session_rows);files.extend(session_cache)
        print(scene,'第三巡の支持状態検証完了',flush=True)
    prior.save(HERE/'第三巡結果142.json',dict(rows=rows,cache=files,plan=prior.ref(HERE/'第三巡計画142.json')))
    prior.save(HERE/'結果142_三巡統合.json',dict(rows=previous['rows']+rows,cache=previous['cache']+files,API=0,real_orders=0))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['register','run']);args=parser.parse_args()
    register() if args.stage=='register' else run()
