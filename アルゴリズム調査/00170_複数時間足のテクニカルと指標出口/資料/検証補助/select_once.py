"""実成績の構造を検査し、初回選定の指紋を確認成績の閲覧前に固定する。"""
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def digest(path):
    """
    機能: 集計資料を指紋化。引数:path(Path)。返り値:str。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    """
    機能: 一度だけ候補選定を実行。引数:なし。返り値:None。
    """
    here=Path(__file__).resolve().parent;study=here.parents[1]/'アルゴリズム調査/00170_複数時間足のテクニカルと指標出口'
    source=here/'summary.json';selection=here/'rootselection.json';seal=study/'選定固定.json'
    if seal.exists() or selection.exists():raise RuntimeError('選定済み資料を上書きしません')
    data=json.loads(source.read_text(encoding='utf-8'));manifest=json.loads((study/'入力目録.json').read_text(encoding='utf-8'))
    inputs={(f['symbol'],f['session']) for f in manifest['files']};audits={(a['symbol'],a['session']) for a in data['audits']}
    assert inputs==audits and len(audits)==len(data['audits'])==114
    configs={c['id'] for c in data['configs']};assert len(configs)==72
    keys=set()
    for r in data['results']:
        key=(r['symbol'],r['session'],r['config_id']);assert key not in keys;keys.add(key)
        assert r['method_id']==r['symbol']+'_T170_'+r['config_id']
        assert abs(r['gross_profit_yen']-r['gross_loss_yen']-r['realized_yen'])<0.001
        assert abs(r['final_equity_yen']-r['realized_yen']-r['unrealized_yen'])<0.001
        if r['complete']:
            assert r['final_position']['Qty']==0 and r['unrealized_yen']==0
            assert r['new_qty']==r['closed_qty']
    assert keys=={(symbol,session,c) for symbol,session in inputs for c in configs}
    subprocess.run([sys.executable,'-X','utf8','analyze.py','select'],cwd=here,check=True)
    # ----------------------------------------
    # 確認成績の集計前に選択と元集計の指紋を永続化します。
    obj={'fixed_at':datetime.now().astimezone().isoformat(),'source_sha256':digest(source),'selection_sha256':digest(selection),'selection':json.loads(selection.read_text(encoding='utf-8')),'preselection_checks':'全72×114件、会計、ID、入力集合、終端確認場の残玉ゼロが一致','note':'後半確認成績による選び直しは禁止。選択はanalyze.py内の検討区間だけ。'}
    seal.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'選定固定':obj['selection_sha256']},ensure_ascii=False))


if __name__=='__main__':main()
