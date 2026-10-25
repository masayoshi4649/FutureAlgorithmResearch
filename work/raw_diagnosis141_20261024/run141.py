"""全原板の観測から固定した改善を、既知50場へ昼夜別に適用する。"""

import argparse
import importlib.util
import json
import pickle
import sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT/'work/aggressive140_20261024'
sys.path.insert(0,str(OLD))
import run140_v2 as prior
import active140_v2 as original
import round2_140
import active141
import evidence141
import supplemental141
import exit141


def material():
    """
    機能: 保存50場と会計・原注文の参照を一度だけ作る。
    引数: なし。
    返り値: tuple[list,dict,dict]はpacket目録、基準注文、前回追加注文。
    """
    packets = []
    bases, additions = {}, {}
    for split,manifest in (('known','known_manifest140.json'),('new','inputs/input_manifest.json')):
        packets.extend(prior.read(OLD/manifest)['packets'])
        ledger = prior.read(OLD/split/('結果140_表示訂正版.json' if split=='known' else '結果140.json'))
        bases.update({(x['session'],x['symbol']):x for x in ledger['cache']})
        ledger = prior.read(OLD/f'round2_{split}'/'結果140.json')
        additions.update({(x['session'],x['symbol']):x for x in ledger['cache']})
    return packets,bases,additions


def register():
    """
    機能: 入口・保有・出口・費用・全資料と実装指紋を金融再生前に照合登録する。
    引数: なし。
    返り値: None。元の巨大台帳を既存管理関数で更新する。
    """
    packets,_,_ = material()
    previous = prior.read(OLD/'第二巡計画140.json')
    implementation = dict(previous['spec']['implementation'])
    for path in (Path(__file__),HERE/'active141.py',HERE/'evidence141.py',HERE/'raw141.py',HERE/'raw141_initial141.py',HERE/'supplemental141.py',HERE/'exit141.py'):
        ref = prior.ref(path);implementation[ref['path']] = ref['sha256']
    manifests = [OLD/'known_manifest140.json',OLD/'inputs/input_manifest.json',OLD/'moved_materials140.json',
                 HERE/'coverage_all141.json',OLD/'known/結果140_表示訂正版.json',OLD/'new/結果140.json',
                 OLD/'round2_known/結果140.json',OLD/'round2_new/結果140.json']
    plan = dict(id='141_原板全行の転換診断と入口追撃補完の機構別修正',name='全原板診断に基づく昼夜別の改善比較',purpose='条件比較',
        question='低効率帯の小戻り、追撃予算の増大、始値票と直近反転の矛盾を修正して損失を抑えられるか。',
        change='00140の追加3場を全原行走査。元A33/A36を基に入口構造、原板支持、実リスク予算、保護後追撃、途中退出の12条件を対照比較。夜補完は始値票の保留・直近20分合議・二市場退出の3条件。',
        repeat_reason='今回の損失親を全件突き合わせて失敗機構を特定。40分逆向き禁止は勝ちも消す反証を含める。追撃の当初予算固定と、補完時点の時間軸競合を個別検証する。',
        compares_to=['140_先着損失の診断と独立枠と整数ペア'],
        configs=dict(active=evidence141.configurations(),supplement=supplemental141.configurations(),
            core_exit={'X01':'元主担当に二市場価格逆行15秒退出','X02':'元主担当に二市場価格と板逆行15秒退出',
                       'Y01':'X01にG10の追加担当を併用','Y02':'X02にG11の追加担当を併用'}),
        spec=dict(entry={'変更':evidence141.configurations(),'夜補完':supplemental141.configurations(),
            '基準':'日経B5は昼T06/夜U06、TOPIX B5は昼T06/夜T04。追加は日経A36・TOPIX A33を対照とする。',
            '原板':'全原行のOFI正規化値と距離加重数量、直近30秒平均は原価格時計上。相手の同時刻行・自己の後続原行は不使用。',
            '構造':'0.25R戻り→0.125R押し→前極値より2tick以上有利な再極値→0.125R再進行。両市場120秒支持を要求。'},
            management={'変更':'追撃を初回約定枚数×停止R以内へ拘束、利益保護前の追撃禁止を別比較。',
                '併用':'日経はB5と追加を別枠で同時運転、TOPIXは判断時に空いている先着親だけ採用。元00140と同じ。',
                '昼夜':'Gの機構比較は昼夜共通の対照だが各25場で別採否。Nは夜間だけ変更し昼B5はそのまま。合算だけで採用しない。'},
            exit={'変更':'両市場30秒が0.1R以上逆行、120秒も逆行を15秒持続で退出。板版は双方OFI逆向きも必要。',
                '夜補完':'新たな約定時点から元幅の停止追尾を再計算。旧返済価格の置換ではない。',
                '主担当X':'元入口通知固定。原行の逆行15秒確認で残玉を早期返済。旧予約済み返済は優先、返済後の新規は元通知のみ。Yは修正主担当とG追加を同じ併用規則で合成。',
                '場末':'既存limitで判断し次正常原行約定。未清算は失敗。'},
            allocation={'商品':['NK225mini','TOPIXmini'],'片方向上限':10,'B5基準':5,'日経追加':'初回2枚、最大5枚','TOPIX追加':'初回最大2枚、最大2枚'},
            costs=previous['spec']['costs'],execution=previous['spec']['execution'],
            data={'sessions':[p['session'] for p in packets],'input_manifests':[prior.ref(p) for p in manifests],
                '標本':'追加3場も既に見た診断開発標本。旧47場は副作用対照、全50場は既知で未見成績と呼ばない。',
                '検査':'修正なし同値、未来改変、価格鏡像、次原行約定、上限と無残玉を独立検査。'},implementation=implementation),
        evidence=[prior.ref(HERE/'全損失親と価格転換141.json'),prior.ref(HERE/'補完方向照合141.json')])
    plan = json.loads(json.dumps(plan,ensure_ascii=False))
    prior.save(HERE/'試行計画141.json',plan)
    manager = ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
    spec = importlib.util.spec_from_file_location('manager141',manager)
    mod = importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    checked = mod.check(plan)
    prior.save(HERE/'照合141.json',dict(proposal_complete=checked['proposal_complete'],issues=checked['提案不完全理由'],
        matches=[{k:v for k,v in x.items() if k in ('id','kind','name')} for x in checked['matches']]))
    assert checked['proposal_complete']
    mod.check=lambda proposal:checked
    registered=mod.store_trial(plan)
    prior.save(HERE/'登録141.json',dict(returncode=0,id=registered['id'],plan=prior.ref(HERE/'試行計画141.json')))
    print('00141登録完了',flush=True)


def load_arrays(item):
    """
    機能: 保存注文を指紋確認後に読み取る。
    引数: item(dict)は位置とSHA。
    返り値: dict[str,ndarray]は既存十列注文。
    """
    path=ROOT/item['path'];assert prior.ref(path)['sha256']==item['sha256']
    with np.load(path) as data:
        return {key:data[key].copy() for key in data.files}


def run():
    """
    機能: 固定条件を全50場へ因果順に適用し、昼夜別評価用の注文と独立会計を保存する。
    引数: なし。
    返り値: None。各場中間結果を保存し、再開時は確定した場を再実行しない。
    """
    plan=prior.read(HERE/'試行計画141.json');assert prior.read(HERE/'登録141.json')['returncode']==0
    for path,sha in plan['spec']['implementation'].items():assert prior.ref(ROOT/path)['sha256']==sha,path
    packets,bases,additions=material();rows=[];files=[]
    for item in packets:
        scene=item['session'];per_scene=HERE/'results'/f'{scene}.json'
        if per_scene.exists():
            done=prior.read(per_scene);rows.extend(done['rows']);files.extend(done['cache']);continue
        path=Path(item['path']);path=path if path.is_absolute() else ROOT/path
        assert prior.ref(path)['sha256']==item['sha256']
        packet=pickle.loads(path.read_bytes())
        data=evidence141.attach(packet,original.prepare(packet,40))
        inp,market,history,_=prior.common.features129.build(packet,'mid',0.)
        session_rows=[];session_files=[]
        for symbol in ('NK225','TOPIX'):
            key=scene,symbol;b=load_arrays(bases[key]);extra=load_arrays(additions[key])
            base=b['B5'];old_id='S36' if symbol=='NK225' else 'C33'
            old_orders=extra['S36'] if symbol=='NK225' else b['C33']
            arrays={'B5':base,old_id:old_orders}
            template=original.configurations()[35 if symbol=='NK225' else 32]
            for test in plan['configs']['active']:
                config=dict(template,**test['changes'])
                orders,_=active141.replay(data[symbol],config)
                arrays['A_'+test['id']]=orders
                arrays[test['id']]=round2_140.parallel(base,orders) if symbol=='NK225' else prior.joined(base,orders)
            for config in plan['configs']['supplement']:
                if symbol!='NK225':
                    continue
                method=config['id']
                if scene.endswith('_Day'):
                    arrays[method]=base.copy()
                else:
                    core=base[base[:,8]!=999]
                    arrays[method],notes=supplemental141.replay(inp[key],packet['quotes'][key],history[key],market[key],core,config)
                    prior.save(HERE/'results'/'notes'/f'{symbol}_{scene}_{method}.json',notes)
            for kind in (1,2):
                method=f'X{kind:02d}'
                arrays[method]=exit141.replay(data[symbol],base,kind)
                addon=arrays['A_G10' if kind==1 else 'A_G11']
                arrays[f'Y{kind:02d}']=round2_140.parallel(arrays[method],addon) if symbol=='NK225' else prior.joined(arrays[method],addon)
            for method,orders in arrays.items():
                row=prior.account(orders,packet,symbol,method,'診断3場' if scene>='2026-10-22_Night' else '対照47場')
                session_rows.append(row)
            destination=HERE/'results'/'measurement'/f'{symbol}_{scene}.npz'
            destination.parent.mkdir(parents=True,exist_ok=True);assert not destination.exists()
            np.savez_compressed(destination,**arrays)
            session_files.append(dict(session=scene,symbol=symbol,**prior.ref(destination)))
        prior.save(per_scene,dict(rows=session_rows,cache=session_files))
        rows.extend(session_rows);files.extend(session_files)
        print(scene,'15変更と対照の保存完了',flush=True)
    prior.save(HERE/'結果141.json',dict(rows=rows,cache=files,plan=prior.ref(HERE/'試行計画141.json'),API=0,real_orders=0))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['register','run'])
    args=parser.parse_args()
    register() if args.stage=='register' else run()
