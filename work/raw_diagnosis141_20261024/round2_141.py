"""修正の副作用を再診断し、方向固定待機と残玉を持つ部分退出を比較する。"""

import argparse
import importlib.util
import json
import pickle
from pathlib import Path
import numpy as np
import run141_v2 as first
import supplemental141_v3 as supplement
import active141_v3 as active

HERE,ROOT,prior=first.HERE,first.ROOT,first.prior


def active_configs():
    """
    機能: 全返済による再入場の副作用に対する部分返済を2条件に固定する。
    引数: なし。
    返り値: list[dict]は元入口と再進行入口の部分返済条件。
    """
    return [dict(id='H01',name='逆行で半減し元の停止追尾を残す',changes=dict(exit_guard=1,partial_exit=True)),
            dict(id='H02',name='再進行確認・追撃保護と逆行半減',changes=dict(entry_guard=2,add_guard=2,exit_guard=1,partial_exit=True))]


def register():
    """
    機能: 具体的な悪化診断と5追加条件を金融再生前に照合登録する。
    引数: なし。
    返り値: None。第一巡の実装・入力・結果は保持する。
    """
    plan=prior.read(HERE/'試行計画141_v2.json')
    plan.update(id='141_第二巡_待機中の方向変更と全返済後の再参加を修正',name='待機方向固定と逆行部分返済',purpose='条件比較',
        change='Q01の待機中の再採点が高値買いへ変わった3場、G06全返済がB5大玉負けを新採用した3場を原板から診断。準備方向固定3条件と半減退出2条件を追加。',
        repeat_reason='追加3場に合う補完置換が旧47場で悪化した原因を分解し、短期押しを転換とみなす全返済と再参加規則を切り分ける。',
        compares_to=['141_原板全行の転換診断と入口追撃補完の機構別修正_v2'])
    plan['configs']=dict(active=active_configs(),supplement=[c for c in supplement.configurations() if c['id'] in ('Q04','Q05','Q06')])
    assert len(plan['configs']['supplement'])==3
    plan['spec']['entry']['第二巡補完']=plan['configs']['supplement']
    plan['spec']['management']['第二巡']='補完は初回候補方向を一度固定して支持待機。主担当が判断したら優先。追加担当は逆行15秒で一度だけ半数切捨返済、1枚の場合は半減せず旧停止追尾を継続。半減後は追撃しない。'
    plan['spec']['exit']['第二巡']='半減は新しい追撃玉から返済。残玉は当初の停止線と利益追尾で管理し、残玉がある限りTOPIXの他親は元の先着規則で見送り。'
    plan['spec']['data']['input_manifests'].append(prior.ref(HERE/'結果141.json'))
    for path in (Path(__file__),HERE/'supplemental141_v3.py',HERE/'active141_v3.py'):
        ref=prior.ref(path);plan['spec']['implementation'][ref['path']]=ref['sha256']
    plan['evidence']=[prior.ref(HERE/'補完悪化上位3場の原板監査141.json'),prior.ref(HERE/'G06悪化三場の寄与分解141.json')]
    prior.save(HERE/'第二巡計画141.json',plan)
    manager=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
    spec=importlib.util.spec_from_file_location('manager141second',manager);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    checked=mod.check(plan)
    prior.save(HERE/'第二巡照合141.json',dict(proposal_complete=checked['proposal_complete'],issues=checked['提案不完全理由'],matches=[{k:v for k,v in x.items() if k in ('id','kind','name')} for x in checked['matches']]))
    assert checked['proposal_complete']
    mod.check=lambda proposal:checked
    registered=mod.store_trial(plan)
    prior.save(HERE/'第二巡登録141.json',dict(returncode=0,id=registered['id'],plan=prior.ref(HERE/'第二巡計画141.json')))
    print('第二巡登録完了',flush=True)


def run():
    """
    機能: 新5条件のみを全50場に計算し、第一巡の保存会計と重複なく結合する。
    引数: なし。
    返り値: None。既存の同一条件を再実行せず、原会計を書き換えない。
    """
    plan=prior.read(HERE/'第二巡計画141.json');assert prior.read(HERE/'第二巡登録141.json')['returncode']==0
    for path,sha in plan['spec']['implementation'].items():assert prior.ref(ROOT/path)['sha256']==sha,path
    packets,_,_=first.material();old=prior.read(HERE/'結果141.json')
    cache={(r['session'],r['symbol']):r for r in old['cache']}
    rows=[];files=[]
    for item in packets:
        scene=item['session'];path=Path(item['path']);path=path if path.is_absolute() else ROOT/path
        assert prior.ref(path)['sha256']==item['sha256'];packet=pickle.loads(path.read_bytes())
        data=first.evidence141.attach(packet,first.original.prepare(packet,40))
        inp,market,history,_=prior.common.features129.build(packet,'mid',0.)
        for symbol in ('NK225','TOPIX'):
            key=scene,symbol;base=first.load_arrays(cache[key])['B5'];arrays={}
            template=first.original.configurations()[35 if symbol=='NK225' else 32]
            for test in plan['configs']['active']:
                orders,_=active.replay(data[symbol],dict(template,**test['changes']))
                arrays['A_'+test['id']]=orders
                arrays[test['id']]=first.round2_140.parallel(base,orders) if symbol=='NK225' else prior.joined(base,orders)
            if symbol=='NK225':
                for config in plan['configs']['supplement']:
                    if scene.endswith('_Day'):arrays[config['id']]=base.copy()
                    else:
                        arrays[config['id']],notes=supplement.replay(inp[key],packet['quotes'][key],history[key],market[key],base[base[:,8]!=999],config)
                        prior.save(HERE/'round2'/'notes'/f'{symbol}_{scene}_{config["id"]}.json',notes)
            for method,orders in arrays.items():rows.append(prior.account(orders,packet,symbol,method,'診断3場' if scene>='2026-10-22_Night' else '対照47場'))
            dest=HERE/'round2'/'measurement'/f'{symbol}_{scene}.npz';dest.parent.mkdir(parents=True,exist_ok=True);assert not dest.exists()
            np.savez_compressed(dest,**arrays);files.append(dict(session=scene,symbol=symbol,**prior.ref(dest)))
        print(scene,'第二巡完了',flush=True)
    prior.save(HERE/'第二巡結果141.json',dict(rows=rows,cache=files,plan=prior.ref(HERE/'第二巡計画141.json'),API=0,real_orders=0))
    prior.save(HERE/'結果141_二巡統合.json',dict(rows=old['rows']+rows,cache=old['cache']+files,plan=prior.ref(HERE/'第二巡計画141.json'),API=0,real_orders=0))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['register','run']);args=parser.parse_args()
    register() if args.stage=='register' else run()
