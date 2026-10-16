"""根が許可した別目的の一読で、旧24小会計と固定比較八条件の目録だけを射影する。"""

import hashlib
import json
import common
import catalog


def project() -> None:
    """
    機能: 00105結果をこの目的で一回読み、以後準備/固定へ使う永続小metadataを保存する。
    引数: なし。CLI --root-metadata-projection-permitted の明示だけで呼ぶ。
    返り値: None。input/台帳本文・原板・新金融を読まない。
    """
    target=common.HERE/'旧二十四小会計と八比較の目録.json';assert not target.exists()
    previous=common.ROOT/'work/e01_improve_20261014/engine'
    source_path=previous/'finance/結果.json';raw=source_path.read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    assert digest=='bc50b5db84cb3f9afe329c9966863a302b0b11a8722e050207cc49c1862860b6'
    result=json.loads(raw.decode('utf-8-sig'));assert result['全合格'] and result['source開始終端一致']
    fixed_raw=(previous/'金融事前固定.json').read_bytes();fixed=json.loads(fixed_raw.decode('utf-8-sig'))
    assert fixed['全合格'] and fixed['source_SHA256']==result['source_SHA256'] and fixed['case_SHA256']==result['case_SHA256']
    configs={c['id']:c for c in result['configs']};reused={};references={};mapping={}
    for cid,entry in result['results'].items():
        reused[cid]=dict(**{k:v for k,v in entry.items() if k!='ledgers'},config=configs[cid],
            source=source_path.relative_to(common.ROOT).as_posix(),SHA256=digest,
            reuse_scope='00105保存小会計引用。新00106の有効性標本へ数えない。')
    for cid,entry in result['reused_results'].items():
        assert cid not in reused;reused[cid]=entry
    assert len(reused)==24
    sessions=result['sessions'];keys={(s,t) for s in sessions for t in catalog.QUANTITY}
    for gate in catalog.GATES:
        for execution in ('FAK0','FAK1'):
            for target_id in ('P1','ATR25'):
                cid=catalog.reference_id(gate,execution,target_id);entry=result['results'][cid]
                assert len(entry['rows'])==len(entry['ledgers'])==66 and {(r['session'],r['symbol']) for r in entry['rows']}==keys
                references[cid]={r['session']+'|'+r['symbol']:r for r in entry['ledgers']}
                assert len(references[cid])==66
                mapping[gate+'|'+execution+'|'+target_id]=cid
    assert len(sessions)==33 and len(references)==8 and set(fixed['input_cache'])==set(sessions)
    common.write(target.name,dict(全合格=True,sessions=sessions,input_cache=fixed['input_cache'],
        references=references,reference_mapping=mapping,reused_results=reused,
        source_finance=dict(path=source_path.relative_to(common.ROOT).as_posix(),SHA256=digest),
        source_fixed=dict(path=(previous/'金融事前固定.json').relative_to(common.ROOT).as_posix(),SHA256=hashlib.sha256(fixed_raw).hexdigest()),
        source_SHA256=result['source_SHA256'],case_SHA256=result['case_SHA256'],
        読取目的='00106計画の旧24小会計/8台帳目録/条件取得。原因診断の1読とは別目的。以後このmetadataを再利用。',
        旧結果この目的読取数=1,旧結果原因診断読取数=1,大型input=0,台帳本文=0,新金融=0,原板=0,NPZ=0,API=0))
    print('旧24小会計と八比較目録を別目的1読で保存',flush=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--root-metadata-projection-permitted',action='store_true',required=True)
    parser.parse_args();project()
