"""旧33の44列目録と追加2のstatだけを射影し、数量本体を開かない。"""

import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode=True
sys.stdout.reconfigure(encoding='utf-8')
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def read_small(path: Path) -> tuple[dict,dict]:
    """
    機能: 指定済み小schema/目録だけを一読し、同bytesの指紋と内容を返す。
    引数: path(Path)はmetadata又は私有stat JSON。
    返り値: tuple[dict,dict]は内容と読取証跡。NPZ/原本へ呼び出さない。
    """
    allowed=[ROOT/'work/wave_v103/input_v2/metadata.json',ROOT/'work/wave_v104/holdout_input/metadata.json',
        HERE.parent/'holdout_schema/旧三十三場外の追加二場の未読stat固定.json']
    assert path in allowed and path.stat().st_size<400000
    raw=path.read_bytes()
    return json.loads(raw.decode('utf-8')),dict(path=path.relative_to(ROOT).as_posix(),bytes=len(raw),SHA256=hashlib.sha256(raw).hexdigest(),本文一読=1)


def stat(path: Path) -> dict:
    """
    機能: ファイル名とstatだけを返し、原本/NPZの先頭やzip内部を開かない。
    引数: path(Path)は保存NPZ又はbook。
    返り値: dictは存在・bytes・mtime_ns。
    """
    if not path.exists():return dict(path=path.relative_to(ROOT).as_posix(),exists=False)
    value=path.stat()
    return dict(path=path.relative_to(ROOT).as_posix(),exists=True,bytes=value.st_size,mtime_ns=value.st_mtime_ns)


def main() -> None:
    """
    機能: 小目録2＋私有新2stat1だけを射影し、44列の保存位置と限定可用性を固定する。
    引数: なし。
    返り値: None。数量統計/金融/API/原本/NPZ読取は0。
    """
    out=HERE/'旧33の44列保存位置と新2の未読可用性.json';assert not out.exists()
    metadata=[];reads=[]
    for p in (ROOT/'work/wave_v103/input_v2/metadata.json',ROOT/'work/wave_v104/holdout_input/metadata.json'):
        value,proof=read_small(p);metadata.append(value);reads.append(proof)
    first,extra=metadata
    assert first['全合格'] and extra['全合格'] and len(first['accounts'])==64 and len(extra['accounts'])==2
    assert len(first['schema']['columns'])==len(extra['schema']['columns'])==44
    assert first['schema']['columns']==extra['schema']['columns']
    sessions=first['sessions']+extra['sessions'];assert len(sessions)==len(set(sessions))==33
    accounts=[]
    for group,value in zip(('103v2既32','104追加Day1'),metadata):
        for key,item in sorted(value['accounts'].items()):
            session,symbol=key.split('|');npz=ROOT/item['出力位置']
            accounts.append(dict(session=session,symbol=symbol,由来=group,NPZ=stat(npz),
                目録に記録された出力SHA256=item['出力SHA256'],現在bytesSHA再検算=False,
                book=stat(ROOT/'book'/symbol/(session+'.jsonl'))))
    assert len(accounts)==66 and all(a['NPZ']['exists'] and a['book']['exists'] for a in accounts)
    holdout,proof=read_small(HERE.parent/'holdout_schema/旧三十三場外の追加二場の未読stat固定.json');reads.append(proof)
    new_sessions=['2026-10-13_Night','2026-10-14_Day'];assert not set(new_sessions)&set(sessions)
    new=[]
    for session in new_sessions:
        for symbol in ('TOPIX','NK225'):
            new.append(dict(session=session,symbol=symbol,book=stat(ROOT/'book'/symbol/(session+'.jsonl')),
                旧103v2既保存位置=stat(ROOT/'work/wave_v103/input_v2/raw'/symbol/(session+'.npz')),
                旧104追加Day既保存位置=stat(ROOT/'work/wave_v104/holdout_input/raw'/symbol/(session+'.npz')),
                原本頭部未読=True,四十四列schemaを当場で未確認=True))
    source_paths=[ROOT/s for s in ('work/wave_v103/input/core.py','work/wave_v103/input_v2/correction.py',
        'work/wave_v103/input_v2/data.py','work/wave_v104/holdout_input/core.py','work/wave_v104/holdout_input/data.py',
        'work/wave_v106/e01_trade_gate/prepare.py','work/wave_v106/e01_trade_exit/prepare.py',
        'work/wave_v52/measurement/extract.py','work/wave_v56/measurement/display_changes.py','work/wave_v57/features.py',
        'work/wave_v106/e01_absorption_gate/feature.py')]
    value=dict(全合格=True,旧対象場数=33,旧保存口座数=66,保存列数=44,columns=first['schema']['columns'],sessions=sessions,旧保存=accounts,
        新二場=new,新場可用性='指定二つの既44列保存位置は未生成。全projectの他領域の未生成を証明するものではない。bookはstatのみ、schema/正常行/44列生成は未測。',
        小目録の各一読=reads,source_SHA256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths},
        原本本文=0,NPZ本体=0,価格数量値保存=0,新金融=0,API=0)
    out.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,proof_SHA256=hashlib.sha256(out.read_bytes()).hexdigest(),旧33=66,列数=44,新場stat=4,原本本文=0,NPZ=0),ensure_ascii=False))


if __name__=='__main__':main()
