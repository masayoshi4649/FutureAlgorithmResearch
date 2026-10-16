"""既存33入力目録と旧選択小会計だけを、規模検証の新目的へ射影する。"""

import hashlib
import json
import common


def project() -> None:
    """
    機能: 根が許可した小metadata目的の一読で、33cache指紋と旧二条件の小会計を保存する。
    引数: なし。CLIの根許可flagでだけ実行する。
    返り値: None。input/台帳本文・原板・金融を再生しない。
    """
    previous=common.ROOT/'work/e01_adaptive_price_20261014/engine'
    target=common.HERE/'旧選択小会計と三十三入力の目録.json';assert not target.exists()
    raw=(previous/'finance/結果.json').read_bytes();digest=hashlib.sha256(raw).hexdigest()
    assert digest=='13f534a10b081db94944d723171214a2132829b66b70f177e0d3055b27116944'
    result=json.loads(raw.decode('utf-8-sig'));assert result['全合格'] and result['source開始終端一致']
    fixed_raw=(previous/'金融事前固定.json').read_bytes();fixed=json.loads(fixed_raw.decode('utf-8-sig'))
    assert fixed['全合格'] and fixed['source_SHA256']==result['source_SHA256'] and fixed['case_SHA256']==result['case_SHA256']
    configs={c['id']:c for c in result['configs']};reused={}
    for cid in ('E01_ADAPT_G50_ADAPT75_P1','E01_ADAPT_G25_ADAPT100_P1'):
        entry=result['results'][cid]
        assert len(entry['rows'])==66
        reused[cid]=dict(**{k:v for k,v in entry.items() if k!='ledgers'},config=configs[cid],
            source=(previous/'finance/結果.json').relative_to(common.ROOT).as_posix(),SHA256=digest,
            reuse_scope='旧小数量P1の保存会計引用だけ。新全量/長出口の金融へ流用しない。')
    assert len(fixed['sessions'])==len(fixed['input_cache'])==33
    common.write(target.name,dict(全合格=True,sessions=fixed['sessions'],input_cache=fixed['input_cache'],reused_results=reused,
        source_finance=dict(path=(previous/'finance/結果.json').relative_to(common.ROOT).as_posix(),SHA256=digest),
        source_fixed=dict(path=(previous/'金融事前固定.json').relative_to(common.ROOT).as_posix(),SHA256=hashlib.sha256(fixed_raw).hexdigest()),
        目的='00107の旧選択引用と同33cache目録固定。以後このmetadataだけ再利用。',この目的旧結果読取=1,
        台帳本文=0,大型input=0,金融=0,原板=0,NPZ=0,API=0))
    print('規模検証の小目録を一目的一読で保存',flush=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--root-small-metadata-permitted',action='store_true',required=True)
    parser.parse_args();project()
