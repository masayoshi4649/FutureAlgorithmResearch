"""条件選択を売買層へ接続して、登録後だけ全50場を再生する。"""

import argparse
import importlib.util
import json
import pickle
import sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREVIOUS = ROOT/'work/raw_diagnosis141_20261024'
sys.path.insert(0,str(PREVIOUS))
import run141_v2 as first
from policies142 import active_configs, joint_configs, online_config

prior = first.prior


def register():
    """
    機能: 状況選択・売買仕様・対照・全入力・実装指紋を金融再生前に照合登録する。
    引数: なし。
    返り値: None。巨大な旧台帳は管理ツールだけを通して更新する。
    """
    import night_trader142 as night
    plan = prior.read(PREVIOUS/'第二巡計画141.json')
    plan.update(id='142_状況判断と売買を分離した時間軸原板リスク切替',name='一律介入ではなく当時の状態で確認方法と維持半減全返済を選択',purpose='条件比較',
        question='短い押しと方向崩れ、古い始値票と新しい合意を区別して、置換で失った勝ちと追加損失を減らせるか。',
        change='入口判断と保有判断を純粋関数へ分離。反発確認の強さ・全返済か半減か維持か・初回予算内の追撃・夜間補完方向を状態で選び、全保有と後続候補を再生する。',
        repeat_reason='00141の一律変更で悪化した原板付き反例を起点に条件の有効域を検証。過去効率だけの追従回帰や直近利益による選択とは区別する。',
        compares_to=['141_第二巡_待機中の方向変更と全返済後の再参加を修正','141_原板全行の転換診断と入口追撃補完の機構別修正_v2'])
    plan['configs']=dict(active=active_configs(),night=night.configurations(),joint=joint_configs(),online=online_config())
    plan['spec']['entry'].update({'今回':'entry_selector142.choose_entryで反発確認を選択し、各準備中は方式固定。新旧とも条件成立後の次正常原行で新規。',
        '選択変数':'自己相手5/20/40分の公開済み方向、30/120秒の原価格時計差、自己相手の原板OFI30秒平均、追加担当の仮想完了親における直近同方向連敗数。銘柄・日時や将来利益を判定変数にしない。',
        '夜補完':'初回に旧始値票と直近20分合意と5分支持を比較し、旧方向即時・初回方向固定待機・新合意方向の支持待機を選択。準備方向は固定。',
        '対照':'B5、00141のM1（NK昼G02夜G10、TP昼G06夜H02）を保存会計から引用。'})
    plan['spec']['management'].update({'今回':'management_selector142は正常板で二市場短期逆行15秒成立時に0維持/1半減/2全返済を返す。新規・停止・追尾はactive_trader142が管理し、半減後は追加しない。',
        '後続取引':'候補は独立仮想運転し、全返済後は既存の冷却・連敗停止を経て準備。TOPIX先着採用、NK独立枠の親占有規則を維持。実採用しなかった候補親も完了後は仮想連敗に寄与する。実口座の連敗とは区別する。',
        '追加':'add_policyは初回実損失予算内で、利益保護前の追撃を禁止又は二市場5/20分支持時のみ許可。',
        '逐次対照':online_config()})
    plan['spec']['exit']['今回']='固定損切り・追尾・場末清算を優先。状況判断の半減は新しい玉から一度だけ、後で全返済条件になれば残玉全返済。'
    plan['spec']['data']['標本']='全50場は既知開発。過去完了場だけの逐次選択も設計に全資料の知見が入るため真の未見とは呼ばない。'
    plan['spec']['data']['検査']='無変更同値、prefix未来不変、上下反転、次原行BBO、親数量と手数料、場末無残玉、判断関数のみの人工境界を独立検査。'
    for p in (PREVIOUS/'結果141_二巡統合.json',HERE/'既存の状態選択との違い142.md'):
        plan['spec']['data']['input_manifests'].append(prior.ref(p))
    for name in ('run142.py','policies142.py','entry_selector142.py','management_selector142.py','active_trader142.py','night_selector142.py','night_trader142.py','online142.py'):
        ref=prior.ref(HERE/name);plan['spec']['implementation'][ref['path']]=ref['sha256']
    plan=json.loads(json.dumps(plan,ensure_ascii=False))
    prior.save(HERE/'試行計画142.json',plan)
    manager=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
    spec=importlib.util.spec_from_file_location('manager142',manager);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    checked=module.check(plan)
    prior.save(HERE/'照合142.json',dict(proposal_complete=checked['proposal_complete'],issues=checked['提案不完全理由'],matches=[{k:v for k,v in x.items() if k in ('id','kind','name')} for x in checked['matches']]))
    assert checked['proposal_complete']
    module.check=lambda proposal:checked
    registered=module.store_trial(plan)
    prior.save(HERE/'登録142.json',dict(returncode=0,id=registered['id'],plan=prior.ref(HERE/'試行計画142.json')))
    print('条件切替の事前登録完了',flush=True)


def prepared(packet):
    """
    機能: 原行までの板変化と公開済み20分差を既存28特徴へ追加する。
    引数: packet(dict)は一場二市場の凍結資料。
    返り値: tuple[dict,dict,dict,dict]は追加担当資料・元入力・二市場特徴・公開履歴。
    """
    data=first.evidence141.attach(packet,first.original.prepare(packet,40))
    inputs,market,history,_=prior.common.features129.build(packet,'mid',0.)
    for symbol,d in data.items():
        h=history[packet['session'],symbol]
        d['features']=np.column_stack((d['features'],h[:,7],h[:,11]))
    return data,inputs,market,history


def merge(base,addon,symbol):
    """
    機能: 因果順の親採用規則に従い基準担当と追加担当を併用する。
    引数: base/addon(ndarray)、symbol(str)は親ごとの実約定。
    返り値: ndarrayはNK独立枠又はTOPIX先着採用の全注文。
    """
    return first.round2_140.parallel(base,addon) if symbol=='NK225' else prior.joined(base,addon)


def run():
    """
    機能: 固定した各選択機構を全場実行し、判断理由と原注文と会計を保存する。
    引数: なし。
    返り値: None。確定場は再計算せず、以前の会計は書き換えない。
    """
    import active_trader142 as active
    import night_trader142 as night
    plan=prior.read(HERE/'試行計画142.json');assert prior.read(HERE/'登録142.json')['returncode']==0
    for path,sha in plan['spec']['implementation'].items():assert prior.ref(ROOT/path)['sha256']==sha,path
    packets,bases,_=first.material()
    old=prior.read(PREVIOUS/'結果141_二巡統合.json')
    old_cache={}
    for item in old['cache']:old_cache.setdefault((item['session'],item['symbol']),[]).append(item)
    rows=[];files=[]
    for item in packets:
        scene=item['session'];dest=HERE/'results'/f'{scene}.json'
        if dest.exists():
            saved=prior.read(dest);rows.extend(saved['rows']);files.extend(saved['cache']);continue
        path=Path(item['path']);path=path if path.is_absolute() else ROOT/path
        assert prior.ref(path)['sha256']==item['sha256'];packet=pickle.loads(path.read_bytes())
        data,inputs,market,history=prepared(packet)
        scene_rows=[];scene_cache=[]
        for symbol in ('NK225','TOPIX'):
            key=scene,symbol;base=first.load_arrays(bases[key])['B5']
            old_arrays={}
            for c in old_cache[key]:old_arrays.update(first.load_arrays(c))
            m1=('G02' if scene.endswith('_Day') else 'G10') if symbol=='NK225' else ('G06' if scene.endswith('_Day') else 'H02')
            arrays={'B5':base,'M1':old_arrays[m1]};traces={};extra={}
            template=first.original.configurations()[35 if symbol=='NK225' else 32]
            for test in plan['configs']['active']:
                orders,_,trace=active.replay(data[symbol],dict(template,**test['changes']))
                extra[test['id']]=orders
                arrays[test['id']]=merge(base,orders,symbol)
                arrays['A_'+test['id']]=orders
                traces[test['id']]=trace
            if symbol=='NK225':
                for config in plan['configs']['night']:
                    if scene.endswith('_Day'):arrays[config['id']]=base.copy()
                    else:
                        arrays[config['id']],notes=night.replay(inputs[key],packet['quotes'][key],history[key],market[key],base[base[:,8]!=999],config,data[symbol]['features'])
                        prior.save(HERE/'notes'/f'{symbol}_{scene}_{config["id"]}.json',notes)
            for config in plan['configs']['joint']:
                route=config['day' if scene.endswith('_Day') else 'night']
                chosen_base=arrays[config['supplement']] if symbol=='NK225' and scene.endswith('_Night') else base
                arrays[config['id']]=merge(chosen_base,extra[route],symbol)
            for method,orders in arrays.items():
                scene_rows.append(prior.account(orders,packet,symbol,method,'診断3場' if scene>='2026-10-22_Night' else '対照47場'))
            file=HERE/'measurement'/f'{symbol}_{scene}.npz';file.parent.mkdir(parents=True,exist_ok=True)
            np.savez_compressed(file,**arrays);scene_cache.append(dict(session=scene,symbol=symbol,**prior.ref(file)))
            target=HERE/'traces'/f'{symbol}_{scene}.npz';target.parent.mkdir(parents=True,exist_ok=True);np.savez_compressed(target,**traces)
        prior.save(dest,dict(rows=scene_rows,cache=scene_cache));rows.extend(scene_rows);files.extend(scene_cache)
        print(scene,'条件切替の再生完了',flush=True)
    prior.save(HERE/'結果142.json',dict(rows=rows,cache=files,plan=prior.ref(HERE/'試行計画142.json'),API=0,real_orders=0))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['register','run']);args=parser.parse_args()
    register() if args.stage=='register' else run()
