"""非金融の採点完了を目標達成と区別して正式台帳へ記す。"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

import plan


def main() -> None:
    """
    機能: 方向採点・独立結果監査・表示検査を結び、旧台帳を保全して完了を記録する。
    引数: CLI --audit/--view(Path) は完成証跡。
    返り値: None。新金融0、金融目標の達成は主張しない。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--audit',type=Path,required=True)
    parser.add_argument('--view',type=Path,required=True)
    args=parser.parse_args()
    assert not (plan.HERE/'非金融採点の完了登録.json').exists()
    report=plan.read(plan.HERE/'十八方向採点の公開射影.json')
    frozen=plan.read(plan.HERE/'実測前の正式固定.json')
    assert report['全合格'] and not report['金融'] and plan.sources()==frozen['source_SHA256']
    assert plan.digest(plan.HERE/'measurement/方向予測の採点結果.json')==report['結果SHA256']
    for item in report['outputs']:
        assert plan.digest(plan.ROOT/item['path'])==item['SHA256']
    audit,view=plan.read(args.audit),plan.read(args.view)
    assert audit['全合格'] and view['全合格']
    directory=plan.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合'
    module_spec=importlib.util.spec_from_file_location('方向採点の完了登録',directory/'manage.py')
    manager=importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(manager)
    data=manager.load()
    table=data['trials']
    rows=[row for row in table['trials'] if row['id']==plan.TRIAL]
    assert len(rows)==1 and rows[0]['status']=='未実行'
    assert rows[0]['spec']==plan.read(plan.HERE/'試行計画.json')['spec']
    paths=[plan.HERE/'measurement/方向予測の採点結果.json',plan.HERE/'十八方向採点の公開射影.json',
        args.audit.resolve(),args.view.resolve(),plan.PUBLIC/'方向予測はできているか.html',
        plan.PUBLIC/'方向予測の公開採点.json',plan.PUBLIC/'過去の到達率と先着率の確認.md']
    rows[0].update(status='検証済み',
        result='方向先着の非金融十八条件を旧既知33場・66入力で採点。到達率と対称先着、次行気配評価を分離。新損益の計算・金融目標達成は0。',
        readme=(plan.PUBLIC/'README.md').relative_to(plan.ROOT).as_posix(),
        report=(plan.PUBLIC/'方向予測はできているか.html').relative_to(plan.ROOT).as_posix(),
        evidence=[dict(path=p.relative_to(plan.ROOT).as_posix(),sha256=plan.digest(p)) for p in paths],
        result_scope=dict(既知セッション=33,条件=18,非金融測定口座=66,新金融=0,原NPZ=66,
            保存eventNPZ=66,原板=0,API=0,追加二場=0,金融目標達成=0,
            留保='未決を勝ちに含めない。全候補と非重複・異なる幅の同経路を独立標本に数えない。'))
    table['updated_at']=datetime.now(timezone(timedelta(hours=9))).isoformat()
    manager.validate(data,deep=True)
    target=directory/'data/trials.json'
    previous=target.read_bytes()
    old_sha=hashlib.sha256(previous).hexdigest()
    archive=directory/'data/history'/('trials_'+old_sha+'.json')
    if archive.exists():assert archive.read_bytes()==previous
    else:archive.write_bytes(previous)
    raw=(json.dumps(table,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')
    data['source_sha256']['trials.json']=hashlib.sha256(raw).hexdigest()
    temporary=directory/'data/trials_117_completed.tmp'
    staged=directory/'data/view_117_completed.tmp'
    assert not temporary.exists() and not staged.exists()
    temporary.write_bytes(raw)
    staged.write_text(manager.bundle(data),encoding='utf-8')
    temporary.replace(target)
    staged.replace(directory/'data/view-data.js')
    plan.write(plan.HERE/'非金融採点の完了登録.json',dict(全合格=True,id=plan.TRIAL,
        元台帳保全SHA256=old_sha,八源不変=True,金融目標達成=0,新金融=0,再測定=0,原NPZ=0))
    print('00117を非金融採点の検証済みとして登録。金融目標達成とは区別。')


if __name__=='__main__':main()
