"""八仕様と実登録guardを小人工目録へ接続し、閉鎖三源へ拘束する。"""

from copy import deepcopy
from datetime import datetime,timedelta,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile


HERE=Path(__file__).resolve().parent
V8=HERE.parent
ROOT=V8.parents[2]


def write(path: Path,value: dict) -> bytes:
    """
    機能: 人工目録を一時所有域へ保存する。
    引数: path(Path)、value(dict)は保存先と人工資料。
    返り値: bytesは保存したUTF-8。
    """
    payload=(json.dumps(value,ensure_ascii=False,allow_nan=False)+'\n').encode('utf-8');path.write_bytes(payload)
    return payload


def main() -> None:
    """
    機能: 八仕様・入力小目録・SOURCE変更拒否を確認し正式金融前の拘束を作る。
    引数: なし。
    返り値: None。原市場/cache/実台帳/金融/登録は使用しない。
    """
    sources={name:hashlib.sha256((V8/name).read_bytes()).hexdigest() for name in ('engine_v8.py','run_v8.py','plan_v8.py')}
    assert sources=={'engine_v8.py':'499d00b4fd88418ee1e3a6894d64eb31fe95b25479403e8f9bb106a51d07b1fc','run_v8.py':'45a10846c384cb66ef6d55b381308748180a679d6b22da57dcf246fbea04675f','plan_v8.py':'05f3d543d693441106718d3b40e6ec6eb0d2148cebc84d9493eb029d7148710e'}
    sys.path.insert(0,str(V8))
    import run_v8 as runner
    specs=runner.make_specs()
    assert len(specs)==len({s['id'] for s in specs})==8
    assert {(s['method'],s['lookback'],s['exit_mode']) for s in specs}=={(m,l,x) for m in ('ratio_mr','ols_mr') for l in (30,60) for x in (0,1)}
    assert {s['family'] for s in specs}=={'confirmed_mr'}
    checks=['比率OLS×30/60×二退出の八仕様','八仕様は同家族として表記']
    for scene,closing in (('2037-01-01_Day',datetime(2037,1,1,15,20,tzinfo=timezone(timedelta(hours=9))).timestamp()),('2037-01-01_Night',datetime(2037,1,2,5,40,tzinfo=timezone(timedelta(hours=9))).timestamp())):
        for spec in specs:
            value=runner.settings(scene,spec)
            assert value==dict(method=spec['method'],lookback=spec['lookback'],exit_mode=spec['exit_mode'],entry_end=closing-1200,close_time=closing)
    checks.append('全八仕様の昼夜締切と設定接続')
    manifest_path=V8/'入力目録.json';payload=manifest_path.read_bytes();manifest=json.loads(payload)
    assert len(manifest['inputs'])==80 and len(set(manifest['sessions']))==40 and manifest['specs']==specs
    old_path=ROOT/manifest['inherited_manifest']['path'];old_payload=old_path.read_bytes()
    assert hashlib.sha256(old_payload).hexdigest()==manifest['inherited_manifest']['sha256']
    old=json.loads(old_payload)
    assert manifest['inputs']==[{k:v[k] for k in ('session','symbol','SHA256','bytes','owned_path')} for v in old['inputs']]
    assert manifest['sessions']==old['sessions'] and manifest['splits']==old['splits']
    checks.append('既所有80入力小目録と固定40場を無変更引用')

    # ----------------------------------------
    # guardは実台帳を使わず、人工登録証跡と人工目録だけで作動を確かめる。
    with tempfile.TemporaryDirectory(dir=HERE) as folder:
        root=Path(folder).resolve();runner.ROOT=root;runner.HERE=root
        (root/'source.py').write_text('人工SOURCE\n',encoding='utf-8')
        mapping={'source.py':hashlib.sha256((root/'source.py').read_bytes()).hexdigest()}
        meta={'sessions':['人工'+str(i) for i in range(40)],'specs':specs}
        meta['inputs']=[{'session':s,'symbol':k} for s in meta['sessions'] for k in ('NK225','TOPIX')]
        data=write(root/'入力目録.json',meta)
        fixed={'sources':mapping,'input_manifest':{'path':'入力目録.json','sha256':hashlib.sha256(data).hexdigest()}}
        proposal={'id':'人工試行','spec':{'implementation':mapping,'data':{'input_manifests':[fixed['input_manifest']],'sessions':meta['sessions']}}}
        write(root/'固定計画.json',fixed);write(root/'試行計画.json',proposal)
        write(root/'正式照合の全出力.json',{'終了コード':0,'stdout':json.dumps({'proposal_complete':True})})
        write(root/'正式登録の全出力.json',{'終了コード':0,'stdout':json.dumps(proposal)})
        assert runner.verify_run_contract()[1]==meta
        checks.append('人工実登録とSOURCE及び目録の完全結合')
        for label,change,restore in (
            ('SOURCE改変拒否',lambda:(root/'source.py').write_text('改変',encoding='utf-8'),lambda:(root/'source.py').write_text('人工SOURCE\n',encoding='utf-8')),
            ('目録改変拒否',lambda:write(root/'入力目録.json',dict(meta,追加=True)),lambda:(root/'入力目録.json').write_bytes(data)),
            ('未完の照合拒否',lambda:write(root/'正式照合の全出力.json',{'終了コード':0,'stdout':json.dumps({'proposal_complete':False})}),lambda:write(root/'正式照合の全出力.json',{'終了コード':0,'stdout':json.dumps({'proposal_complete':True})})),
        ):
            change();rejected=False
            try:runner.verify_run_contract()
            except AssertionError:rejected=True
            assert rejected,label
            restore();checks.append(label)
    pure=HERE/'固定準備と二確認reset及び共同時計の独立人工.json'
    assert json.loads(pure.read_bytes())['passed'] is True
    assert all(hashlib.sha256((V8/name).read_bytes()).hexdigest()==sha for name,sha in sources.items())
    proof={'passed':True,'economic_sources':{(V8/name).relative_to(ROOT).as_posix():sha for name,sha in sources.items()},'checks':checks,'independent_pure':{'path':pure.relative_to(ROOT).as_posix(),'SHA256':hashlib.sha256(pure.read_bytes()).hexdigest()},'input_manifest':{'path':manifest_path.relative_to(ROOT).as_posix(),'SHA256':hashlib.sha256(payload).hexdigest()},'market_reads':0,'cache_reads':0,'registry_reads':0,'formal_financial_replay':0,'registry_changes':0,'source_changes':0}
    target=HERE/'二確認の三源と八仕様及び登録guardの独立拘束.json';assert not target.exists()
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(hashlib.sha256(target.read_bytes()).hexdigest())


if __name__=='__main__':main()
