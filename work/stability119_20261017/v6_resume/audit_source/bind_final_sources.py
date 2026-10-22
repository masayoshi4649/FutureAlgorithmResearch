"""旧独立監査とh時計差分を最終122源・小入力目録へ拘束する。"""

import ast
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import tempfile

from independent_clock_contract import module


HERE=Path(__file__).resolve().parent
H=HERE.parent
F=H.parent/'v6'
ROOT=H.parents[2]


def digest(path: Path) -> str:
    """
    機能: 許可されたSOURCEと小目録だけの内容指紋を得る。
    引数: path(Path)はSOURCE又は小監査資料。
    返り値: strはSHA256。市場・stage本文・金融台帳は対象にしない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def functions(path: Path) -> dict:
    """
    機能: 関数別のASTを位置情報なしで比較可能にする。
    引数: path(Path)はSOURCE。
    返り値: dict[str,str]は関数名と同値比較用AST表現。
    """
    return {v.name:ast.dump(v,include_attributes=False) for v in ast.parse(path.read_text(encoding='utf-8-sig')).body if isinstance(v,ast.FunctionDef)}


def main() -> None:
    """
    機能: f不変・経済同bytes・h差分・CSV拒否・最終指紋を独立に結び付ける。
    引数: なし。
    返り値: None。新証跡を保存し、原本・stage本文・金融・登録は使用しない。
    """
    owner_path=H/'再開sourceの閉鎖と二人工の接続.json'
    assert digest(owner_path)=='94b190b70059f66f63f5a01cc46682e519ea4cb4bf01ef194ce8b4e38db2d755'
    owner=json.loads(owner_path.read_bytes());sources=owner['source_SHA256']
    assert owner['全合格'] is True and len(sources)==122
    assert all(digest(ROOT/name)==sha for name,sha in sources.items())
    old_path=F/'audit_source/旧源全百二十と初期化差分及び入力目録結合の独立監査_v2.json'
    assert digest(old_path)=='fa4c5c28d5545c47150b90b87923451b949cec1c584c6fc05dc6227df50cdb38'
    old=json.loads(old_path.read_bytes())
    assert old['全合格'] is True and len(old['source_SHA256'])==120
    assert all(digest(ROOT/name)==sha for name,sha in old['source_SHA256'].items())
    unchanged=[];changed=[]
    for name,sha in old['source_SHA256'].items():
        target=H/(ROOT/name).relative_to(F)
        (unchanged if digest(target)==sha else changed).append(target.relative_to(H).as_posix())
    assert len(unchanged)==117 and set(changed)=={'plan_v6.py','run_v6.py','adapter_v6.py'}
    expected={str((H/(ROOT/name).relative_to(F)).relative_to(ROOT)).replace('\\','/') for name in old['source_SHA256']}
    expected|={(H/name).relative_to(ROOT).as_posix() for name in ('clock_adapter.py','artificial_clock.py')}
    assert set(sources)==expected
    for proof in owner['proofs']:
        assert digest(ROOT/proof['path'])==proof['SHA256']
        value=json.loads((ROOT/proof['path']).read_bytes())
        assert value['全合格'] is True
        for name,sha in value['source_SHA256'].items():
            matched=name if name in sources else (H/name).relative_to(ROOT).as_posix()
            assert sources[matched]==sha

    # ----------------------------------------
    # h追加CSV関数とimportだけを除けば、既36確認の時計SOURCEに完全一致する。
    clock_path=H/'clock_adapter.py';clock_text=clock_path.read_text(encoding='utf-8')
    tree=ast.parse(clock_text);csv_fn=next(v for v in tree.body if isinstance(v,ast.FunctionDef) and v.name=='validate_csv')
    next_fn=next(v for v in tree.body if isinstance(v,ast.FunctionDef) and v.name=='price_clock')
    lines=clock_text.splitlines(keepends=True);del lines[csv_fn.lineno-1:next_fn.lineno-1]
    reduced=''.join(lines).replace('import csv\n','',1).encode('utf-8')
    prior_path=HERE/'原時計資格とLP出来高reset及び原seq接続の独立人工.json'
    prior=json.loads(prior_path.read_bytes())
    assert prior['全合格'] is True and hashlib.sha256(reduced).hexdigest()==prior['source_SHA256'][clock_path.relative_to(ROOT).as_posix()]
    for name,sha in prior['source_SHA256'].items():
        if name!=clock_path.relative_to(ROOT).as_posix():assert sources[name]==sha
    supplemental=HERE/'場内stale復帰と無効Last後の出来高unknown補足.json'
    assert json.loads(supplemental.read_bytes())['全合格'] is True
    old_adapter,new_adapter=functions(F/'adapter_v6.py'),functions(H/'adapter_v6.py')
    preserved=['primitive','bounds','engine_modules','selected_configs','quote_mapping','account_row','old_rows','metrics']
    assert all(old_adapter[name]==new_adapter[name] for name in preserved)
    old_run,new_run=functions(F/'run_v6.py'),functions(H/'run_v6.py')
    assert all(old_run[name]==new_run[name] for name in ('guard','packet','source_scope_guard','normalize_orders'))
    adapter_tree=ast.parse((H/'adapter_v6.py').read_text(encoding='utf-8'))
    make=next(v for v in adapter_tree.body if isinstance(v,ast.FunctionDef) and v.name=='make_account')
    make_text=ast.unparse(make)
    assert "extract_jsonl(ORIGINAL_STAGE / 'book'" in make_text and "runs[index, 1] == 0" in make_text
    assert "rt['correct_arrays'](raw)" in make_text and "rt['votes'].context(raw)" in make_text
    stage=next(v for v in adapter_tree.body if isinstance(v,ast.FunctionDef) and v.name=='stage_raw')
    stage_text=ast.unparse(stage)
    assert "ROOT / item['staged_path']" in stage_text and 'clock_adapter.write_view' in stage_text and 'clock_adapter.validate_csv' in stage_text
    assert 'original_reads=0' in stage_text and 'csv_clock_guard=csv_clock' in stage_text

    # ----------------------------------------
    # CSV資格は時刻だけを拒否判定し、値や時計を書き換えない。
    clock=module(clock_path,'_final_bound_h_clock')
    base=datetime(2026,10,13,17,tzinfo=timezone(timedelta(hours=9)));start=base.timestamp();end=(base+timedelta(hours=12,minutes=55)).timestamp()
    checks=[]
    with tempfile.TemporaryDirectory(dir=HERE) as folder:
        path=Path(folder)/'synthetic.csv'
        cases=[('正常',[base.isoformat(),(base+timedelta(minutes=1)).isoformat()],True),('重複',[base.isoformat(),base.isoformat()],False),('逆行',[(base+timedelta(minutes=1)).isoformat(),base.isoformat()],False),('場前',[(base-timedelta(seconds=1)).isoformat()],False),('排他終了',[(base+timedelta(hours=12,minutes=55)).isoformat()],False),('timezoneなし',[base.replace(tzinfo=None).isoformat()],False),('不明',['不正'],False),('空足',[],False)]
        for name,times,allowed in cases:
            payload=('time,close\n'+''.join(t+',4000\n' for t in times)).encode('utf-8')
            path.write_bytes(payload);accepted=True
            try:clock.validate_csv(path,start,end)
            except AssertionError:accepted=False
            assert accepted==allowed and path.read_bytes()==payload,name
            checks.append(name)
    metadata_path=H/'入力目録.json';metadata=json.loads(metadata_path.read_bytes())
    assert len(metadata['inputs'])==42 and len({v['path'] for v in metadata['inputs']})==42
    assert len(metadata['new_sessions'])==7 and len(metadata['old_sessions'])==33
    assert all((ROOT/v['staged_path']).resolve().is_relative_to(F/'legacy_root') for v in metadata['inputs'])
    assert metadata['counters']['new_raw_book_reads']==metadata['counters']['new_csv_1min_reads']==metadata['counters']['new_csv_5min_reads']==metadata['counters']['old_financial_rerun']==0
    assert metadata['counters']['new_actual_accounts']==14 and metadata['counters']['old_accounting_reused']==66
    assert metadata['stopped_trial']['new_financial']==0 and metadata['stopped_trial']['original_reads']==42
    assert all(digest(ROOT/name)==sha for name,sha in sources.items())
    proof={'全合格':True,'source_SHA256':sources,'source_end_SHA256':sources,'source_count':122,'f旧120源不変':True,'h同bytes源数':117,'h変更源':changed,'新源':['clock_adapter.py','artificial_clock.py'],'旧437確認の委譲':{'path':old_path.relative_to(ROOT).as_posix(),'SHA256':digest(old_path)},'時計36確認の差分委譲':{'path':prior_path.relative_to(ROOT).as_posix(),'SHA256':digest(prior_path),'CSV追加関数とimportだけを除いた源完全同一':True},'場内staleとLP補足':{'path':supplemental.relative_to(ROOT).as_posix(),'SHA256':digest(supplemental)},'追加CSV確認':checks,'小入力目録':{'path':metadata_path.relative_to(ROOT).as_posix(),'SHA256':digest(metadata_path)},'owner閉鎖':{'path':owner_path.relative_to(ROOT).as_posix(),'SHA256':digest(owner_path)},'原市場本文読取':0,'旧stage本文読取':0,'金融':0,'登録':0,'source変更':0,'留保':'h追加7と旧33保存引用は入力資格が異なり、全40同一時計処理の実測とは呼ばない。'}
    target=HERE/'旧百二十不変と時計CSV差分及び全百二十二源の最終独立拘束.json';assert not target.exists()
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(hashlib.sha256(target.read_bytes()).hexdigest())


if __name__=='__main__':main()
