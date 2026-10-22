"""停止・未実行・完成を区別し、今回の七試行だけを台帳へ反映する。"""

import argparse
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def helpers():
    """
    機能: 既監査の一読・原子的保存部品だけを再利用する。
    引数: なし。
    返り値: moduleは119終了反映の補助関数群。119の終了処理自体は呼ばない。
    """
    path=ROOT/'work/stability119_20261017/finalize119.py'
    spec=importlib.util.spec_from_file_location('_helpers120',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(manifest_path: Path) -> None:
    """
    機能: 根が指定する七試行の根拠と実登録を確認して正本・ビューを同期する。
    引数: manifest_path(Path)は公開後の完成根拠目録。
    返り値: None。過去の試行・金融・原市場を再実行しない。
    """
    F=helpers()
    manifest=F.small_json(manifest_path.resolve())
    assert manifest['root_checked'] is True
    records=manifest['trials']
    assert len(records)==7 and len({r['id'] for r in records})==7
    expected={'120_動く極値の段階追尾新規と利益玉の部分回転',
        '120a_段階追尾の停止した一場の現金会計を独立診断',
        '120b_段階追尾の建玉保存反例を修正した境界検査付き再測定',
        '120c_小試行と含み益で支える追加及び方向別の合計停止',
        '120d_段階追尾の極値を中値から最終約定値へ変えた対照',
        '120e_逆側カバーを外さず組全体回収まで維持する段階追尾',
        '120e1_十八条件の実行時人工を非空にして金融前に再固定'}
    assert {r['id'] for r in records}==expected
    expected_states={
        '120':('会計不整合で中断',None,2),
        '120a':('実データ実行前に中止',0,0),
        '120b':('検証完了',3840,80),
        '120c':('検証完了',1920,80),
        '120d':('検証完了',1920,80),'120e':('実データ実行前に中止',0,0),
        '120e1':('検証完了',1440,80)}
    prepared={}
    for item in records:
        prefix=item['id'].split('_',1)[0]
        status,accounts,inputs=expected_states[prefix]
        assert item['status']==status
        assert item['accounting']['financial_accounts']==accounts
        assert item['accounting']['stored_price_inputs']==inputs
        assert item['accounting']['raw_market_reads']==0
        if prefix=='120':
            assert item['accounting']['saved_unvalidated_accounts']==48
            assert item['accounting']['additional_unsaved_accounts_range']==[1,48]
        if prefix in ('120b','120c','120d','120e1'):
            assert item['accounting']['unclosed_lots']==0
        proposal=F.small_json(F.local(item['proposal']))
        fixed=F.small_json(F.local(item['fixed']))
        assert proposal['id']==item['id'] and proposal['spec']['implementation']==fixed['sources']
        for path,sha in fixed['sources'].items():
            assert F.digest(F.local(path))==sha
        result=F.reference(item['result'],'完成会計又は停止・未実行の保存記録。')
        audits=[F.reference(a,'独立会計又は人工反例と実行整合の確認。') for a in item['audits']]
        assert audits
        for key in ('readme','report'):
            assert F.local(item[key]).is_file()
        prepared[item['id']]=dict(item=item,proposal=proposal,fixed=fixed,result=result,audits=audits)
    # ----------------------------------------
    # 台帳は一回だけ意味解析し、今回の七行以外の内容指紋を保持する。
    manager=F.manager_module()
    data,originals,stamps=F.capture_load(manager)
    table=data['trials']
    unchanged={row['id']:F.sha_bytes(F.encoded(row)) for row in table['trials'] if row['id'] not in prepared}
    for identity,value in prepared.items():
        item=value['item']
        found=[r for r in table['trials'] if r['id']==identity]
        assert len(found)==1
        row=found[0]
        assert row['status']=='未実行' and row['spec']==value['proposal']['spec']
        old_attempts=copy.deepcopy(row.get('execution_attempts',[]))
        row['status']=item['status']
        row['completed_result']=value['result']
        row['completed_audits']=value['audits']
        row['completed_registered_sources']=value['fixed']['sources']
        row['completed_fixed']=dict(path=item['fixed'],sha256=F.digest(F.local(item['fixed'])))
        row['completion_accounting']=item['accounting']
        row['result']=item['text']
        row['readme'],row['report']=item['readme'],item['report']
        row['completion_limitations']='同じ既知40場。停止を損益0へ置かず、無取引・未返済を勝ちへ数えない。実小型板・真受信順・待ち順位は未観測。検証終了と安定黒字の目標達成は別。'
        row.setdefault('evidence',[])
        for evidence in [value['result'],*value['audits'],row['completed_fixed']]:
            F.append_unique(row['evidence'],evidence)
        row.setdefault('execution_attempts',[])
        row['execution_attempts'].append(dict(status=item['status'],result=value['result'],
            accounting=item['accounting'],independent_evidence=False,completion_marker='00120の停止と四段階検証を終了反映'))
        assert row['execution_attempts'][:len(old_attempts)]==old_attempts
    assert all(F.sha_bytes(F.encoded(r))==unchanged[r['id']] for r in table['trials'] if r['id'] in unchanged)
    manager.validate(data,deep=True)
    table['updated_at']=datetime.now(timezone(timedelta(hours=9))).isoformat()
    target=(manager.DATA/'trials.json').resolve()
    old=originals[target]
    old_sha=F.sha_bytes(old)
    payload=F.encoded(table)
    new_sha=F.sha_bytes(payload)
    data['source_sha256']['trials.json']=new_sha
    view_payload=manager.bundle(data).encode('utf-8')
    history=manager.DATA/'history'/('trials_'+old_sha+'.json')
    if history.exists():
        assert F.digest(history)==old_sha
    else:
        F.stage_write(history,old)
    staged=manager.DATA/'trials120_finalization.tmp'
    staged_view=manager.DATA/'view120_finalization.tmp'
    F.stage_write(staged,payload)
    F.stage_write(staged_view,view_payload)
    assert F.digest(staged)==new_sha
    for path,stamp in stamps.items():
        now=path.stat()
        assert (now.st_size,now.st_mtime_ns)==stamp
    view=manager.DATA/'view-data.js'
    old_view=view.read_bytes()
    replaced=False
    try:
        staged.replace(target)
        replaced=True
        staged_view.replace(view)
        assert F.digest(target)==new_sha and view.read_bytes()==view_payload
        manager.validate(data,deep=True)
    except BaseException:
        if replaced:
            target.write_bytes(old)
            view.write_bytes(old_view)
        raise
    F.stage_write(HERE/'七試行の終了とビュー同期.json',F.encoded(dict(passed=True,
        manifest_sha256=F.digest(manifest_path),source_sha256=F.digest(Path(__file__)),
        statuses={r['id']:r['status'] for r in records},old_sha256=old_sha,new_sha256=new_sha,
        view_sha256=F.sha_bytes(view_payload),unrelated_unchanged=True,registry_parse=1,
        history=history.relative_to(ROOT).as_posix(),deep=True,financial_replay=0,
        目標達成の宣言=False)))
    print('七試行の停止・未実行・検証終了を台帳とビューへ同期しました。',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--manifest',type=Path,required=True)
    main(parser.parse_args().manifest)
