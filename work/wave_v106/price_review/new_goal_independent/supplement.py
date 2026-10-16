"""初版の cases 抽出を保持し、旧 E01 の results schema とトップ config を補う。"""

import hashlib
import json
from pathlib import Path

import inventory


def run() -> None:
    """
    機能: 既抜粋を変更せず、二つの別schema資料の会計・条件を追補する。
    引数: なし。原資料は保存小会計JSONだけ。
    返り値: None。第二の統一抜粋と、初版の対応不足の履歴を保存する。
    """
    original_path=inventory.HERE/'会計行の一読抜粋.json'; original_bytes=original_path.read_bytes(); original=json.loads(original_bytes)
    candidates=original['candidates']; files=original['files']
    main_path=inventory.PUBLIC/'公開会計.json'; main_bytes=main_path.read_bytes(); main=json.loads(main_bytes)
    main_sha=hashlib.sha256(main_bytes).hexdigest()
    old_main=next(i for i in files if i['path']==main_path.relative_to(inventory.ROOT).as_posix()); assert old_main['SHA256']==main_sha
    configs={c['id']:c for c in main['configs']}; assert set(configs)==set(main['cases'])
    for c in candidates:
        if c['file']==main_path.name: c['meta']['config']=configs[c['id']]
    path=inventory.PUBLIC/'E01公開会計.json'; saved=path.read_bytes(); payload=json.loads(saved); sha=hashlib.sha256(saved).hexdigest()
    first=next(f for f in files if f['path']==path.relative_to(inventory.ROOT).as_posix()); assert first['SHA256']==sha
    assert payload['全合格'] and payload['sessions']==main['sessions'] and isinstance(payload['results'],dict)
    first.update(対象=True,case_count=len(payload['results']),case_schema={},追加schema='results/rows:日本語実親会計')
    for cid,c in payload['results'].items():
        rows=c['rows'];assert len(rows)==66
        normal=[dict(session=r['session'],symbol=r['symbol'],profit=r['利益'],loss=r['損失'],net=r['収支'],
            campaigns=r['親数'],winning_campaigns=r['勝ち親'],losing_campaigns=r['負け親'],flat_campaigns=r.get('零親',0),
            winning_lots=r['勝ち枚数'],losing_lots=r['負け枚数'],fees=r['費用'],new_lots=r['新規枚数']) for r in rows]
        meta={k:v for k,v in c.items() if k not in ('rows','symbols','ledgers')}
        if cid=='L_D20_PRICE': meta['config']=dict(execution='PRICE',quantity={'TOPIX':5,'NK225':10},cap={'TOPIX':10,'NK225':20})
        else:
            meta['config']=dict(meta.get('case',{})); meta['config'].setdefault('quantity',{'TOPIX':5,'NK225':10})
            meta['config'].setdefault('cap',{'TOPIX':10,'NK225':20})
        first['case_schema'][cid]=dict(keys=list(c),row_keys=list(rows[0]),config=meta['config'])
        candidates.append(dict(id=cid,file=path.name,source_path=first['path'],source_SHA256=sha,sessions=payload['sessions'],
            meta=meta,rows=normal,reported_summary=c.get('symbols'),reported_summary_schema='日本語'))
    sources={'work/wave_v106/e01_report.py':hashlib.sha256((inventory.ROOT/'work/wave_v106/e01_report.py').read_bytes()).hexdigest()}
    result=dict(files=files,candidates=candidates,元資料読取件数=dict(初版11資料=11,追加二資料=2),
        追加読取理由='E01のresults日本語rowsと、176条件のトップconfigsのschema対応。市場データ再読ではない。',
        同一bytes確認=True,元抜粋SHA256=hashlib.sha256(original_bytes).hexdigest(),補足仕様source=sources,
        金融再生=0,原板=0,原NPZ=0,API=0)
    out=inventory.HERE/'全schema統一会計行.json';assert not out.exists()
    data=(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8');out.write_bytes(data)
    evidence=inventory.HERE/'初版schema対応不足の履歴と補完.json';assert not evidence.exists()
    evidence.write_text(json.dumps(dict(初版全候補網羅=False,初版cases形式候補=330,
        理由='casesを持たないE01 results形式を表示根拠と判断した。mainのトップconfigも初版未収録。',
        初版資料SHA256=hashlib.sha256(original_bytes).hexdigest(),補完後全表示候補=len(candidates),
        補完SHA256=hashlib.sha256(data).hexdigest(),新金融=0,実装条件変更=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print('E01追補 '+str(len(payload['results']))+' 全表示 '+str(len(candidates)),flush=True)
    for cid,v in first['case_schema'].items():print(cid,v['config'],flush=True)
    print('SHA '+hashlib.sha256(data).hexdigest(),flush=True)


if __name__=='__main__':run()
