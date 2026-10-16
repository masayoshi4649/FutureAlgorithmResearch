"""金融計算と独立会計の完了だけを、目標達否と区別して正式台帳へ記す。"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

import catalog
import plan


def main() -> None:
    """
    機能: 完成成果物と独立証拠を接続し、旧台帳bytesを履歴へ保存する。
    引数: コマンドラインのaudit/view(Path) は独立会計と表示検査の完成証跡。
    返り値: None。原NPZ・event・金融の再生は0。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--view', type=Path, required=True)
    args = parser.parse_args()
    proof = plan.HERE / '金融完了と目標達否の登録.json'
    assert not proof.exists()
    report = plan.read(plan.HERE / '全十二条件と全三十三場の公開射影.json')
    assert report['全合格'] is True
    assert plan.digest(plan.HERE / 'finance/結果.json') == report['結果SHA256']
    frozen = plan.read(plan.HERE / '金融前の正式固定.json')
    assert plan.sources() == frozen['source_SHA256']
    audit, view = plan.read(args.audit), plan.read(args.view)
    assert audit['全合格'] is True and view['全合格'] is True
    directory = plan.ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合'
    spec = importlib.util.spec_from_file_location('短期売買の完了登録', directory / 'manage.py')
    manager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manager)
    data = manager.load()
    table = data['trials']
    matches = [row for row in table['trials'] if row['id'] == catalog.TRIAL_ID]
    assert len(matches) == 1 and matches[0]['status'] == '未実行'
    proposal = plan.read(plan.HERE / '試行計画.json')
    assert matches[0]['spec'] == proposal['spec']
    items = [plan.HERE / 'finance/結果.json', plan.PUBLIC / '短期の方向性と実約定による全セッション損益.html',
        plan.PUBLIC / '短期方向性の公開会計.json', plan.PUBLIC / '損失の具体例と次の改善.md',
        args.audit.resolve(), args.view.resolve(), plan.HERE / '全十二条件と全三十三場の公開射影.json',
        plan.HERE / 'diagnosis/主候補の赤字六場と実脚及び費用の小診断.json']
    both = report['同時主目標合格']
    matches[0].update(status='検証済み',
        result=f'次rawの市場新規・後正常行返済と各注文料で十二対照を全33場再生。両商品主目標合格{both}/12。既知期間の探索で未知成績の証明ではない。',
        readme=(plan.PUBLIC/'README.md').relative_to(plan.ROOT).as_posix(),
        report=(plan.PUBLIC/'短期の方向性と実約定による全セッション損益.html').relative_to(plan.ROOT).as_posix(),
        evidence=[dict(path=p.relative_to(plan.ROOT).as_posix(),sha256=plan.digest(p)) for p in items],
        result_scope=dict(既知セッション=33, 条件=12, 新金融=792, 原NPZ=66, 保存eventNPZ=66,
            原板=0, API=0, 追加二場=0, 同時主目標合格=both,
            登録準備の停止='空の静観窓を共通照合が空構造として拒否。経済不変の表示だけ修正し、旧版保全。'))
    table['updated_at'] = datetime.now(timezone(timedelta(hours=9))).isoformat()
    manager.validate(data, deep=True)
    target = directory / 'data/trials.json'
    previous = target.read_bytes()
    old_sha = hashlib.sha256(previous).hexdigest()
    archive = directory / 'data/history' / ('trials_' + old_sha + '.json')
    if archive.exists():
        assert archive.read_bytes() == previous
    else:
        archive.write_bytes(previous)
    raw = (json.dumps(table,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')
    data['source_sha256']['trials.json'] = hashlib.sha256(raw).hexdigest()
    temporary, staged = directory/'data/trials_115_completed.tmp', directory/'data/view_115_completed.tmp'
    assert not temporary.exists() and not staged.exists()
    temporary.write_bytes(raw)
    staged.write_text(manager.bundle(data),encoding='utf-8')
    temporary.replace(target)
    staged.replace(directory/'data/view-data.js')
    plan.write(proof,dict(全合格=True,id=catalog.TRIAL_ID,同時主目標合格=both,
        元台帳保全SHA256=old_sha,source九つ不変=True,金融再生=0,原NPZ=0))
    print('115を金融検証済みで記録。目標達否は別に保持しました。')


if __name__ == '__main__':
    main()
