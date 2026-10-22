"""c又はdの所有完成結果と小さな登録証跡だけを独立照合する。"""

import argparse
import hashlib
import json
from pathlib import Path


HERE=Path(__file__).resolve().parent
OWNER=HERE.parent
ROOT=OWNER.parents[1]


def read(path: Path) -> tuple[dict,str]:
    """
    機能: 所有結果又は小メタデータを読み指紋と内容を分けて返す。
    引数: path(Path)はJSON。原市場・NPZは含めない。
    返り値: tuple[dict,str]は内容とSHA256。
    """
    payload=path.read_bytes()
    return json.loads(payload.decode('utf8')),hashlib.sha256(payload).hexdigest()


def main() -> None:
    """
    機能: 既許可の結果所有copyから、登録実体・源・目録・実行時人工の拘束だけを検査する。
    引数: CLI --variant(str:c又はd)、--sha256(str)は根指定完成指紋。
    返り値: None。巨大登録台帳・金融原結果・NPZは再読せず新規証跡へ保存する。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--variant',choices=('c','d'),required=True);parser.add_argument('--sha256',required=True);args=parser.parse_args()
    owner=OWNER/f'audit_result120{args.variant}';base=OWNER/f'recovery_{args.variant}'
    data,digest=read(owner/'owned'/'完成結果.json');assert digest==args.sha256
    fixed,fixed_sha=read(base/'固定計画.json');meta,meta_sha=read(base/'入力目録.json');proposal,proposal_sha=read(base/'試行計画.json')
    reg,_=read(base/'正式登録の全出力.json');pre,_=read(base/'事前照合の全出力.json')
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
    actual_engine=[p for p in fixed['sources'] if p.endswith(f'/engine120{args.variant}.py')]
    assert len(actual_engine)==1 and fixed['sources'][actual_engine[0]]==proof['engine_sha256']
    runtime,runtime_sha=read(base/'実行時の通常高速全配列同値.json')
    assert runtime['passed'] is True and runtime['engine_sha256']==proof['engine_sha256']
    assert runtime['comparisons']==24 and runtime['financial_accounts']==0 and runtime['original_market_reads']==0
    target=owner/'登録実体と八十入力参照及び実行時人工の独立拘束.json';assert not target.exists()
    result=dict(passed=True,variant=args.variant,result_sha256=digest,fixed_sha256=fixed_sha,proposal_sha256=proposal_sha,input_manifest_sha256=meta_sha,artificial_sha256=proof_sha,runtime_sha256=runtime_sha,source_SHA256=fixed['sources'],input_references=80,financial_accounts=1920,original_result_additional_reads=0,original_market_reads=0,original119_cache_reads=0,financial_replay=0,registry_changes=0,留保='小メタデータを照合し既知40場の新有効性標本にしない。実登録stdoutは固定計画と一致、巨大台帳本文の再読は零。')
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,sha256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
