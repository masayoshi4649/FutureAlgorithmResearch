"""金融未実行eの空guardを、同じ経済源の非空runtimeへ差し替えた独立接続監査。"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys


HERE=Path(__file__).resolve().parent
OWNER=HERE.parent
ROOT=OWNER.parents[1]
OLD=OWNER/'recovery_e'
NEW=OWNER/'recovery_e1'
ENGINE_SHA='5fcecd4aa8061ce4be46291e90bfd7d912b11dbd0c1f7f7e3e535b34f346830a'
CATALOG_SHA='509ffee62ecd2aa9ab1685b2c2066daaec17d477debeb140a6b7d9323d99dcf6'


def digest(path: Path) -> str:
    """
    機能: 数値解析せず閉鎖source又は小目録の同bytes指紋を返す。
    引数: path(Path)はsource又はメタJSON。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """
    機能: 経済源同bytes・十八仕様同値・六つの非空runtimeを金融前に追加拘束する。
    引数: なし。
    返り値: None。市場・実NPZ・実損益・巨大登録台帳を読まない。
    """
    assert os.environ.get('NUMBA_BOUNDSCHECK')!='0','既知の環境上書きは人工開始前に拒否する'
    assert (NEW/'engine120e1.py').read_bytes()==(OLD/'engine120e.py').read_bytes()
    assert (NEW/'catalog120e1.py').read_bytes()==(OLD/'catalog120e.py').read_bytes()
    assert digest(NEW/'engine120e1.py')==ENGINE_SHA and digest(NEW/'catalog120e1.py')==CATALOG_SHA
    assert (NEW/'入力目録.json').read_bytes()==(OLD/'入力目録.json').read_bytes()
    sys.path.insert(0,str(OWNER));sys.path.insert(0,str(NEW))
    loader=importlib.util.spec_from_file_location('audit120e1_nonempty_runtime',NEW/'runtime120e1.py')
    runtime=importlib.util.module_from_spec(loader);sys.modules[loader.name]=runtime;loader.loader.exec_module(runtime)
    result=runtime.verify()
    assert result['passed'] is True and result['comparisons']==6
    assert len(result['cases'])==6 and all(v['entries']>0 and v['entries']==v['closed'] for v in result['cases'])
    assert {(v['mode'],v['cap']) for v in result['cases']}=={(m,c) for m in range(3) for c in (2,20)}
    assert result['engine_sha256']==ENGINE_SHA and result['financial_accounts']==result['original_market_reads']==0
    import catalog120e1
    specs=catalog120e1.specifications();assert len(specs)==18 and {s['mode'] for s in specs}=={0,1,2}
    assert Path(runtime.E.__file__).resolve()==(NEW/'engine120e1.py').resolve()
    primary=HERE/'e全十八条件の独立人工と全返済境界の最終拘束.json'
    original=json.loads(primary.read_text(encoding='utf8'))
    assert original['passed'] is True and original['engine_sha256']==ENGINE_SHA
    sources={(NEW/name).relative_to(ROOT).as_posix():digest(NEW/name) for name in ('engine120e1.py','catalog120e1.py','runtime120e1.py','run120e1.py','register120e1.py')}
    sources[(OWNER/'catalog120.py').relative_to(ROOT).as_posix()]=digest(OWNER/'catalog120.py')
    sources[(OWNER/'prepare120e1.py').relative_to(ROOT).as_posix()]=digest(OWNER/'prepare120e1.py')
    target=HERE/'e1非空runtimeと十八経済条件同bytesの独立拘束.json';assert not target.exists()
    proof=dict(passed=True,engine_sha256=ENGINE_SHA,source_SHA256=sources,audit_source_sha256=digest(Path(__file__)),primary_audit_sha256=digest(primary),input_manifest_sha256=digest(NEW/'入力目録.json'),runtime=result,original_market_reads=0,NPZ_reads=0,result_reads=0,financial_replay=0,registry_changes=0,source_changes=0,留保='eは登録後に空runtimeを発見し金融未実行で停止。e1は人工guardを非空化し同じ十八経済条件を再固定する対照。初回極値修正・具体入口・全組/個別/RESCUEの独立人工を同bytes源へ委譲。')
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,engine_sha256=ENGINE_SHA,sha256=digest(target),cases=result['cases']),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
