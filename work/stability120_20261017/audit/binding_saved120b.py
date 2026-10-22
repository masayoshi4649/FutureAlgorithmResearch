"""所有済み結果と小目録だけで、実行源・入力参照・人工証跡を束縛する。"""

import hashlib
import json
from pathlib import Path


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
BASE=HERE.parent/'recovery_b'
OWN=HERE.parent/'audit_result120b'


def read(path: Path) -> tuple[dict,str]:
    """
    機能: 所有済み結果又は小メタデータを一読して指紋も返す。
    引数: path(Path)はcache・原市場以外のJSON。
    返り値: tuple[dict,str]は内容とSHA256。金融再生はしない。
    """
    payload=path.read_bytes()
    return json.loads(payload.decode('utf8')),hashlib.sha256(payload).hexdigest()


def main() -> None:
    """
    機能: 正式b結果の八十入力参照と源・人工・登録実体の一致を独立照合する。
    引数: なし。
    返り値: None。実市場・元119NPZ・金融結果原本の追加読取は零。
    """
    data,digest=read(OWN/'owned'/'完成結果.json')
    assert digest=='c99743d739c9d24a08088f1b5ebdc78af8285b19e9704773965ea05f13890ce1'
    fixed,fixed_sha=read(BASE/'固定計画.json')
    meta,meta_sha=read(BASE/'入力目録.json')
    proposal,proposal_sha=read(BASE/'試行計画.json')
    reg,_=read(BASE/'正式登録の全出力.json');pre,_=read(BASE/'事前照合の全出力.json')
    actual=json.loads(reg['stdout']);checked=json.loads(pre['stdout'])
    assert reg['終了コード']==pre['終了コード']==0 and checked['提案完全'] is True
    assert actual['id']==proposal['id'] and actual['spec']==proposal['spec']
    assert actual['spec']['implementation']==fixed['sources']==data['source_SHA256']
    assert actual['spec']['data']['input_manifests']==[fixed['input_manifest']]
    assert meta_sha==fixed['input_manifest']['sha256']
    index={(x['symbol'],x['session']):(x['path'],x['sha256']) for x in meta['inputs']}
    refs={(x['symbol'],x['session']):(x['input_path'],x['input_sha256']) for x in data['cache']}
    assert len(index)==len(refs)==80 and index==refs
    assert data['sessions']==meta['sessions'] and data['specs']==fixed['specs']
    proof,proof_sha=read(ROOT/fixed['artificial_audit']['path'])
    assert proof_sha==fixed['artificial_audit']['sha256'] and proof['passed'] is True
    actual_engine=[p for p in fixed['sources'] if p.endswith('/engine120b.py')]
    assert len(actual_engine)==1 and fixed['sources'][actual_engine[0]]==proof['engine_sha256']
    target=OWN/'登録実体と八十入力参照及び源人工の独立拘束.json';assert not target.exists()
    result=dict(passed=True,result_sha256=digest,fixed_sha256=fixed_sha,proposal_sha256=proposal_sha,input_manifest_sha256=meta_sha,artificial_sha256=proof_sha,source_SHA256=fixed['sources'],input_references=80,financial_accounts=3840,original_result_additional_reads=0,original_market_reads=0,original119_cache_reads=0,financial_replay=0,registry_changes=0,留保='小メタデータの照合。登録台帳巨大本文は再読せず、実登録stdoutの実体を固定計画と比較する。')
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,sha256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
