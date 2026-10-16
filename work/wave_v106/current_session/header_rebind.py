"""HTTP完結境界の修正だけを、旧証跡を保持して現在場の源指紋へ再接続する。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import common
import core
import prepare
import runner


CAPTURE='work/wave_v106/current_capture/capture.py'
PROOF=common.HERE.parent/'current_capture/最後の応答と完結トレーラーのローカル人工検査.json'
ARCHIVE=common.HERE/'取得器境界修正前'


def replace(path: Path, value: dict, changes: dict) -> None:
    """
    機能: 旧exact JSONとSHAを別保存してから、捕捉指紋だけ再束縛した現JSONを保存する。
    引数: path(Path)、value(dict)、changes(dict)は対象、新資料と旧新指紋の記録先。
    返り値: None。親の明示指示による未登録証跡の更新で、数値sourceは変更しない。
    """
    old=path.read_bytes();target=ARCHIVE/path.name;assert not target.exists()
    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(old)
    text=json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n';path.write_text(text,encoding='utf8',newline='\n')
    changes[path.name]=dict(旧SHA256=hashlib.sha256(old).hexdigest(),新SHA256=common.digest(path),
        旧保存先=target.relative_to(common.ROOT).as_posix())


def run() -> None:
    """
    機能: 真の最終200トレーラー3境界を人工確認し、12/20旧検査と経済source不変を明示する。
    引数: なし。
    返り値: None。現在Night/API/入力gzip/金融を読まず、5資料の指紋だけ更新する。
    """
    target=common.HERE/'取得器境界の修正と経済不変更.json';assert not target.exists()
    root=json.loads(PROOF.read_text(encoding='utf8'));assert root['全合格'] and root['市場API取得']==0
    assert common.digest(common.ROOT/CAPTURE)==root['source_SHA256']['capture.py']
    old_input=json.loads(prepare.ARTIFICIAL.read_text(encoding='utf8'));old_sha=old_input['source_SHA256'][CAPTURE]
    new_sha=common.digest(common.ROOT/CAPTURE);assert old_sha!=new_sha
    current=prepare.sources()
    for path,expected in old_input['source_SHA256'].items():
        if path!=CAPTURE:assert current[path]==expected,(path,expected,current[path])
    capture=common.module('106取得境界修正の私有小人工',common.ROOT/CAPTURE)
    header='HTTP/1.1 200 OK\r\nContent-Type: application/x-ndjson\r\nX-History-Session-Id: 2026-10-13_Night\r\nX-History-Generation: fixture\r\nX-History-Code: TOPIX\r\nX-History-As-Of: 2026-10-14T05:20:00+09:00\r\nX-History-Sequence: 1\r\nTrailer: X-History-Complete\r\n'
    variants=[('真の200トレーラー',header+'\r\nX-History-Complete: true\r\n',True),
        ('100後の真の200トレーラー','HTTP/1.1 100 Continue\r\n\r\n'+header+'\r\nX-History-Complete: true\r\n',True),
        ('100後の通常200Complete偽造','HTTP/1.1 100 Continue\r\n\r\n'+header+'X-History-Complete: true\r\n\r\n',False)]
    checks=[]
    for index,(label,text,allowed) in enumerate(variants):
        path=common.HERE/'header_fixture'/f'{index}.txt';assert not path.exists();path.parent.mkdir(exist_ok=True)
        path.write_bytes(text.encode('ascii'))
        try:result=capture.headers(path,'TOPIX');actual=True
        except AssertionError:actual=False
        assert actual==allowed;checks.append(dict(条件=label,期待=allowed,結果=actual))
        if allowed:
            item=dict(curl終了コード=0,HTTP要求回数=1,自動再試行=0,ヘッダー位置=str(path),snapshot=result)
            assert prepare.snapshot(item,'TOPIX')['sequence']==1
    changes={};proof_item=dict(path=PROOF.relative_to(common.ROOT).as_posix(),SHA256=common.digest(PROOF))
    new_input=deepcopy(old_input);new_input['source_SHA256']=current
    new_input.update(取得器境界修正proof=proof_item,再束縛='入力12数学を再生せず旧exact proofへ委譲。capture sourceだけ変更、小境界3検査で補足。',
        旧12人工再実行=0,新金融証拠として加算=False)
    replace(prepare.ARTIFICIAL,new_input,changes)
    spec_path=common.HERE/'現在ナイト接続の確定仕様.json';spec=json.loads(spec_path.read_text(encoding='utf8'))
    spec['source_SHA256']=current;spec['人工SHA256']=common.digest(prepare.ARTIFICIAL);spec['取得器境界修正proof']=proof_item
    replace(spec_path,spec,changes)
    fixed_path=common.HERE/'現在入力の結果前固定.json';fixed=json.loads(fixed_path.read_text(encoding='utf8'))
    fixed['source_SHA256'][CAPTURE]=new_sha;fixed['人工SHA256']=common.digest(prepare.ARTIFICIAL)
    fixed['確定仕様SHA256']=common.digest(spec_path);fixed['取得器境界修正proof']=proof_item
    assert fixed['configs']==core.configs();replace(fixed_path,fixed,changes)
    finance=json.loads(runner.ARTIFICIAL.read_text(encoding='utf8'));old_finance=deepcopy(finance)
    finance['source_SHA256']=runner.sources()
    for path,expected in old_finance['source_SHA256'].items():
        if path!=CAPTURE:assert finance['source_SHA256'][path]==expected,path
    finance.update(取得器境界修正proof=proof_item,旧20人工再実行=0,
        再束縛='独立partial/数量料金/私有engine/三条件source全不変、旧20人工へ委譲。新金融証拠へ加算しない。')
    replace(runner.ARTIFICIAL,finance,changes)
    draft=json.loads(runner.DRAFT.read_text(encoding='utf8'));old_draft=deepcopy(draft)
    draft['spec']['implementation']=runner.sources()
    for item in draft['spec']['data']['input_manifests']:
        if item['path'].endswith('現在入力の結果前固定.json'):item['sha256']=common.digest(fixed_path)
    for item in draft['evidence']:
        if item['path']==runner.ARTIFICIAL.relative_to(common.ROOT).as_posix():item['sha256']=common.digest(runner.ARTIFICIAL)
    draft['evidence'].append(dict(path=proof_item['path'],sha256=proof_item['SHA256']))
    draft['repeat_reason']+=' API取得前のHTTP100→200完結境界修正をsource再束縛。三条件/入力/経済数学は不変更。'
    for key in ('entry','management','exit','allocation','costs','execution'):assert draft['spec'][key]==old_draft['spec'][key],key
    replace(runner.DRAFT,draft,changes)
    common.write(target,dict(全合格=True,修正種別='取得器のHTTPヘッダー/トレーラー境界だけ。不具合修正。',
        capture旧SHA256=old_sha,capture新SHA256=new_sha,根7人工=proof_item,小境界検査=checks,変更JSON=changes,
        全入力経済source不変更=True,三条件不変更=True,旧12_20人工再実行=0,新金融証拠へ加算=False,
        現入力gzip読取=0,現在Night内容読取=0,API取得=0,新正式金融=0))
    print('capture境界修正のみ5JSON再束縛、旧exact保持・新金融0',flush=True)


if __name__=='__main__':run()
