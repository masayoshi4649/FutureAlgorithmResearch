"""予兆探索の実測完了を、売買アルゴリズムの完成と区別して台帳へ記録する。"""

import argparse
from datetime import datetime,timedelta,timezone
import hashlib
import importlib.util
import json
from pathlib import Path

import plan


def main() -> None:
    """
    機能: 実測・独立集計・公開と表示の証跡を結び、旧正式台帳を保全して更新する。
    引数: CLI --audit/--view(Path) は完成済みの独立集計と実画像目視接続。
    返り値: None。金融・再測定0、利益目標の達成を主張しない。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--audit',type=Path,required=True);parser.add_argument('--view',type=Path,required=True)
    args=parser.parse_args()
    assert not (plan.HERE/'非金融の予兆探索の完了登録.json').exists()
    report=plan.read(plan.HERE/'四十四条件と全三十七場の公開射影.json')
    assert report['全合格'] and report['金融'] is False
    assert report['結果SHA256']==plan.digest(plan.HERE/'measurement/十ポイント予兆の結果.json')
    assert plan.sources()==plan.read(plan.HERE/'正式固定.json')['source_SHA256']
    for item in report['outputs']:assert plan.digest(plan.ROOT/item['path'])==item['SHA256']
    assert plan.read(args.audit)['全合格'] and plan.read(args.view)['全合格']
    directory=plan.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合'
    module_spec=importlib.util.spec_from_file_location('十ポイント予兆の完了登録',directory/'manage.py')
    manager=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(manager)
    data=manager.load();table=data['trials']
    rows=[row for row in table['trials'] if row['id']==plan.TRIAL]
    assert len(rows)==1 and rows[0]['status']=='未実行'
    assert rows[0]['spec']==plan.read(plan.HERE/'試行計画.json')['spec']
    paths=[plan.HERE/'measurement/十ポイント予兆の結果.json',plan.HERE/'四十四条件と全三十七場の公開射影.json',
        args.audit.resolve(),args.view.resolve(),plan.PUBLIC/'README.md',
        plan.PUBLIC/'十ポイント方向予兆の候補と全セッション結果.html',plan.PUBLIC/'十ポイント予兆の公開採点.json',
        plan.PUBLIC/'事後に残った予兆候補S03.md',plan.PUBLIC/'S03の値幅と方向の条件別診断.md',
        plan.HERE/'s03_context/S03既158予兆の四分類と因果二対照の集計.json',
        plan.HERE/'report_check/context_final/四分類MDと既158予兆の分母及び事後限定の最終整合.json',
        plan.HERE/'条件別診断の文書接続と共通知見追記の検査.json']
    assert plan.read(paths[-2])['全合格']
    rows[0].update(status='検証済み',
        result='TOPIX判断後10pt対逆行2.5/5/10ptの観測Last先着を44条件・37場で非金融採点。過去21場学習、次6場選択、後6+追加4の別枠評価。正式3は優位維持せず。事後S03は逆10pt先着で別枠24/40・全期間76/158、全期間安定を確認できず。既158予兆の四分類でも前後期差の理由を特定できなかった。実注文・新金融・利益目標達成は0。',
        readme=(plan.PUBLIC/'README.md').relative_to(plan.ROOT).as_posix(),
        report=(plan.PUBLIC/'十ポイント方向予兆の候補と全セッション結果.html').relative_to(plan.ROOT).as_posix(),
        evidence=[dict(path=p.relative_to(plan.ROOT).as_posix(),sha256=plan.digest(p)) for p in paths],
        result_scope=dict(セッション=37,既存33=33,追加4=4,条件=44,入力旧NPZ=66,入力新JSONL=8,
            新金融=0,API=0,目標利益達成=0,留保='入口の観測価格先着。学習内/選択と別枠を分離。真受信時計・全約定テープ・実損益ではない。'))
    table['updated_at']=datetime.now(timezone(timedelta(hours=9))).isoformat()
    manager.validate(data,deep=True)
    target=directory/'data/trials.json';previous=target.read_bytes()
    old_sha=hashlib.sha256(previous).hexdigest();archive=directory/'data/history'/('trials_'+old_sha+'.json')
    if archive.exists():assert archive.read_bytes()==previous
    else:archive.write_bytes(previous)
    raw=(json.dumps(table,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')
    data['source_sha256']['trials.json']=hashlib.sha256(raw).hexdigest()
    temporary=directory/'data/trials_118_completed.tmp';staged=directory/'data/view_118_completed.tmp'
    assert not temporary.exists() and not staged.exists()
    temporary.write_bytes(raw);staged.write_text(manager.bundle(data),encoding='utf-8')
    temporary.replace(target);staged.replace(directory/'data/view-data.js')
    plan.write(plan.HERE/'非金融の予兆探索の完了登録.json',dict(全合格=True,id=plan.TRIAL,
        元台帳保全SHA256=old_sha,十源不変=True,新金融=0,再測定=0,目標利益達成=0))
    print('00118の非金融予兆探索を完了登録。利益目標達成とは区別。')


if __name__=='__main__':main()
