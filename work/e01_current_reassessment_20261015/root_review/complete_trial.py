"""一回完了した113を未達のまま試行履歴へ確定し、元の登録を保全する。"""

from datetime import datetime, timezone, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
TRIAL=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合'
PUBLIC=ROOT/'アルゴリズム調査/00113_現在の注文活動と再進行から波の中間に参加'
ID='113_E01に依存しない現在確認とquote再進行の九対照'


def main() -> None:
    """
    機能: 登録内容・経済sourceを保持し、結果と監査への根拠だけを追記する。
    引数: なし。
    返り値: None。新金融・原入力・実台帳の読取はしない。
    """
    proof=HERE/'試行完了の登録.json'
    assert not proof.exists()
    ms=importlib.util.spec_from_file_location('試行照合の完了記録',TRIAL/'manage.py')
    manager=importlib.util.module_from_spec(ms)
    ms.loader.exec_module(manager)
    all_data=manager.load()
    table=all_data['trials']
    found=[r for r in table['trials'] if r['id']==ID]
    assert len(found)==1 and found[0]['status']=='未実行'
    row=found[0]
    plan=json.loads((HERE/'試行計画.json').read_text(encoding='utf-8'))
    assert row['spec']==plan['spec']
    for name,digest in plan['spec']['implementation'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest
    title=PUBLIC/'現在の活動と再進行から参加する手法と全セッション損益.html'
    account=PUBLIC/'現在の活動と再進行の公開会計.json'
    source=[title,account,PUBLIC/'損失の原因と未検証の改善.md',
            HERE.parent/'audit_finance/九条件594会計と全完結親及び全期間の独立監査.json',
            HERE.parent/'diagnosis/方向逆行とコスト及び次の一部品の小結.md']
    row.update(status='検証済み',result='9新条件は両商品で全て合計赤字。主目標達成0。反対活動確認で損失は減るが、中値変化と横断・料を合わせると赤字。',
        readme=(PUBLIC/'README.md').relative_to(ROOT).as_posix(),report=title.relative_to(ROOT).as_posix(),
        evidence=[dict(path=p.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in source],
        result_scope=dict(旧既知セッション=33,新経済条件=9,新金融口座=594,保存基準会計=66,保存基準再金融=0,
                          新二場金融=0,原板追加読取=0,NPZ追加読取=0,API=0,目標達成商品条件=0))
    table['updated_at']=datetime.now(timezone(timedelta(hours=9))).isoformat()
    all_data['trials']=table
    manager.validate(all_data,deep=True)
    target=TRIAL/'data/trials.json'
    previous=target.read_bytes()
    oldhash=hashlib.sha256(previous).hexdigest()
    archive=TRIAL/'data/history'/('trials_'+oldhash+'.json')
    if archive.exists():
        assert archive.read_bytes()==previous
    else:
        archive.write_bytes(previous)
    raw=(json.dumps(table,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')
    all_data['source_sha256']['trials.json']=hashlib.sha256(raw).hexdigest()
    temporary=target.with_name('trials_113_completed.tmp')
    view=TRIAL/'data/view-data.js'
    staged=view.with_name('view-data_113_completed.tmp')
    assert not temporary.exists() and not staged.exists()
    temporary.write_bytes(raw)
    staged.write_text(manager.bundle(all_data),encoding='utf-8')
    temporary.replace(target)
    staged.replace(view)
    proof.write_text(json.dumps(dict(全合格=True,id=ID,状態='検証済み・目標未達',元登録保全SHA256=oldhash,
        完成台帳SHA256=hashlib.sha256(raw).hexdigest(),経済source17不変=True,金融追加=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('113を検証済み・目標未達で記録。元登録保全、17経済源不変、追加金融0。')


if __name__=='__main__':
    main()
