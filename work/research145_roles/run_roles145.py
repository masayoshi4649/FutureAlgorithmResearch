"""事前登録済みの八構成で独立した保存注文を合成する。新たな市場判断は生成しない。"""

import argparse
import hashlib
import json
from pathlib import Path
import pickle
import sys
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path[:0]=[str(ROOT/'work/research145_residual'),str(ROOT/'work/research145_engine')]
import run_residual145 as saved
import account145


def assemble(core, addon, secondary):
    """独立した三担当の約定を親ID空間を分離して合成する。

    引数: core/addon/secondary(ndarray)は基本・追加・別入口の保存済み十列約定。
    返り値: ndarrayは約定原行順の合成注文。入力配列や注文内容は変更しない。
    """
    return saved.shared.merge(core,addon,secondary)


def run(registration):
    """登録受領と固定入力を検証し、八構成の会計だけを実施する。

    引数: registration(Path)は登録完了受領書。
    返り値: None。新たな売買再生、条件探索、API呼出しは行わない。
    """
    registration=registration.resolve()
    receipt=json.loads(registration.read_text(encoding='utf-8-sig'))
    assert receipt.get('returncode')==0,'事前登録の完了受領が必要'
    for path in (Path(__file__).resolve(),HERE/'役割別構成145.json',HERE/'保存入力145.json'):
        item=saved.ref(path)
        assert receipt['implementation'][item['path']]==item['sha256'],'登録済み実装・仕様・入力のSHA不一致'
    specification=json.loads((HERE/'役割別構成145.json').read_text(encoding='utf-8'))
    manifest=json.loads((HERE/'保存入力145.json').read_text(encoding='utf-8'))
    assert specification['fee']==0 and specification['maximum_per_side']==10
    assert specification['role_caps']=={'CG':5,'A':3,'CS':2}
    configs=specification['configs']
    assert [x['id'] for x in configs]==['D01','D02','D03','D04','D05','D06','D07','D08']
    supplemental_path=HERE/'new_addon_manifest145.json'
    supplemental=json.loads(supplemental_path.read_text(encoding='utf-8'))
    assert supplemental['registration']==saved.ref(registration),'追加V16/V17が同じ登録で生成されたことを確認する'
    extra={item['session']:item for item in supplemental['sessions']}
    assert set(extra)=={item['session'] for item in manifest['sessions']}
    allrows,checks,sources=[],[],[]
    for item in manifest['sessions']:
        scene=item['session'];kind=scene.split('_')[1]
        target=HERE/'results'/f'{scene}.json'
        assert not target.exists(),'完了済み会計を黙って再計算しない'
        for part in ('residual','addon','cache'):
            assert saved.ref(ROOT/item[part]['path'])==item[part],'入力のSHA不一致'
        newref=extra[scene]['orders']
        assert saved.ref(ROOT/newref['path'])==newref,'追加V16/V17の保存入力SHA不一致'
        with (ROOT/item['cache']['path']).open('rb') as stream:
            packet,data,raw,baseline,label=pickle.load(stream)
        accounts,arrays,scenechecks=[],{},[]
        with np.load(ROOT/item['residual']['path']) as residual, np.load(ROOT/item['addon']['path']) as addon, np.load(ROOT/newref['path']) as newaddon:
            for cfg in configs:
                name=cfg['id'];selected=cfg[kind]
                core=residual['CG_'+selected['CG']]
                secondary=residual['CS_'+selected['CS']]
                additional=(newaddon if selected['A'] in ('V16','V17') else addon)['A_'+selected['A']]
                for role,orders in [('CG',core),('A',additional),('CS',secondary)]:
                    verification=saved.verify(data,orders,specification['role_caps'][role])
                    verification.update(session=scene,method=name,role=role)
                    scenechecks.append(verification)
                combined=assemble(core,additional,secondary)
                check=saved.verify(data,combined,10)
                check.update(session=scene,method=name,role='全体')
                scenechecks.append(check)
                account=account145.account(combined,packet,name,label)
                cash=float(np.sum(-combined[:,3]*combined[:,4]*combined[:,5]*100.-combined[:,9]))
                assert abs(account['net']-cash)<1e-7
                account.update(roles=selected,split='既知開発50場・第二段階役割分離',fees_policy='手数料0、気配差は計上')
                accounts.append(account);arrays[name]=combined
        output=HERE/'orders'/f'{scene}.npz';output.parent.mkdir(parents=True,exist_ok=True)
        np.savez_compressed(output,**arrays)
        record=dict(session=scene,rows=accounts,checks=scenechecks,input=item,new_addon_input=newref,orders=saved.ref(output))
        saved.save(target,record)
        allrows.extend(accounts);checks.extend(scenechecks);sources.append(record['orders'])
        print(scene+' 役割別8構成 完了',flush=True)
    assert len(allrows)==400 and len(checks)==1600
    saved.save(HERE/'役割分離の全場結果145.json',dict(rows=allrows,checks=checks,configs=configs,
        sources=sources,registration=saved.ref(registration),specification=saved.ref(HERE/'役割別構成145.json'),
        input_manifest=saved.ref(HERE/'保存入力145.json'),implementation=saved.ref(Path(__file__).resolve()),
        new_addon_manifest=saved.ref(supplemental_path),
        input_note='V16/V17は同じ事前登録の別生成工程で新たに再生・保存した入力。この合成工程は市場判断を生成しない。',
        financial_accounts=len(allrows),market_replays=0,new_market_decisions=0,API=0,real_orders=0))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--registration',required=True,type=Path)
    run(parser.parse_args().registration)
