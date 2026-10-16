"""公開済み小会計の元 bytes を一読し、独立検算用の全場行と schema を保存する。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PUBLIC = ROOT/'アルゴリズム調査/00103_往復帯の回避と損失後再参加の統合検証'


def run() -> None:
    """
    機能: 公開 JSON 全ファイルを一読し、cases/rows がある全候補を抽出する。
    引数: なし。既知00103の保存会計だけを対象にする。
    返り値: None。源指紋・表示schema・会計行の私有抜粋を保存する。金融再生はしない。
    """
    files=[]; candidates=[]
    for path in sorted(PUBLIC.glob('*.json')):
        saved=path.read_bytes(); sha=hashlib.sha256(saved).hexdigest(); payload=json.loads(saved)
        item=dict(path=path.relative_to(ROOT).as_posix(),SHA256=sha,bytes=len(saved),top_keys=list(payload))
        case_map=payload.get('cases')
        if not isinstance(case_map,dict):
            item.update(対象=False,理由='cases/rowsの全場会計を持たない表示根拠。')
            files.append(item); continue
        sessions=payload.get('sessions'); assert isinstance(sessions,list) and len(sessions)==33,path
        item.update(対象=True,case_count=len(case_map),sessions=sessions,case_schema={})
        for cid,case in case_map.items():
            assert isinstance(case,dict) and isinstance(case.get('rows'),list),(path,cid)
            rows=case['rows']; assert len(rows)==66 and {(r['session'],r['symbol']) for r in rows}=={(s,y) for s in sessions for y in ('TOPIX','NK225')},(path,cid)
            item['case_schema'][cid]=dict(keys=list(case),row_keys=list(rows[0]),config=case.get('config'),
                kind=case.get('kind'),label=case.get('label'),saved_alias=case.get('saved_alias'),alias_source_id=case.get('alias_source_id'))
            meta={k:v for k,v in case.items() if k not in ('rows','diagnosis','summary')}
            candidates.append(dict(id=cid,file=path.name,source_path=item['path'],source_SHA256=sha,sessions=sessions,
                meta=meta,rows=rows,reported_summary=case.get('summary')))
        files.append(item)
        print(path.name+' 候補'+str(len(case_map))+' / '+str(rows[0]),flush=True)
        print('先頭schema '+str(item['case_schema'][next(iter(case_map))]),flush=True)
    out=HERE/'会計行の一読抜粋.json'; assert not out.exists()
    saved=(json.dumps(dict(files=files,candidates=candidates,元資料一読件数=len(files),金融再生=0,原板=0,原NPZ=0,API=0),ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')
    out.write_bytes(saved)
    proof=dict(全合格=True,source_files=files,表示候補数=len(candidates),抽出source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        抜粋SHA256=hashlib.sha256(saved).hexdigest(),原本変更=0,公開編集=0,共通知見編集=0,新金融=0,原板=0,原NPZ=0,API=0)
    evidence=HERE/'入力schemaと保存資料指紋.json';assert not evidence.exists()
    evidence.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print('全表示候補 '+str(len(candidates))+' 抜粋SHA '+proof['抜粋SHA256'],flush=True)


if __name__=='__main__':run()
