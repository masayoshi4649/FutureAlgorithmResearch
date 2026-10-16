"""数量応答だけの完了と未測の売買を、試行履歴へ分けて記録する。"""

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json

import plan


def main() -> None:
    """
    機能: 修正版114R2を非金融検証済みとし、実測・公開・独立根拠を接続する。
    引数: なし。
    返り値: None。原NPZ・eventNPZ・金融・APIを追加実行しない。
    """
    proof = plan.HERE / '非金融完了の登録.json'
    assert not proof.exists()
    result = plan.HERE / 'measurement/数量応答の結果.json'
    assert plan.digest(result) == 'aad49e1186468c8bf069a902126c2f70d6f74a311bfe8ae03ef0978d99325d05'
    directory = plan.ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合'
    specification = importlib.util.spec_from_file_location('数量修正版の完了登録', directory / 'manage.py')
    manager = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(manager)
    all_data = manager.load()
    table = all_data['trials']
    rows = [row for row in table['trials'] if row['id'] == plan.TRIAL]
    assert len(rows) == 1 and rows[0]['status'] == '未実行'
    proposal = plan.read(plan.HERE / '試行計画.json')
    assert rows[0]['spec'] == proposal['spec']
    assert rows[0]['spec']['implementation'] == plan.sources()
    evidence = [result, plan.PUBLIC / '表示数量を観測した後の方向応答.html',
        plan.PUBLIC / '数量後の価格応答の公開集計.json', plan.PUBLIC / '結論と未検証の売買.md',
        plan.HERE / 'audit_aggregation/数量公開六十六集計と先着分母及び表示の独立監査.json',
        plan.HERE / 'audit_aggregation/六十六出力の数量分類と終点及び追加欄の独立監査.json',
        plan.HERE / 'public_finish/説明算術と表不変更及び隔離表示の確認.json']
    rows[0].update(status='検証済み',
        result='非金融の1T先着のみ。維持なら反転しやすい仮説は当該定義で未支持。初回活動だけの約80%を数量追加・利益へ転用しない。',
        readme=(plan.PUBLIC / 'README.md').relative_to(plan.ROOT).as_posix(),
        report=(plan.PUBLIC / '表示数量を観測した後の方向応答.html').relative_to(plan.ROOT).as_posix(),
        evidence=[dict(path=path.relative_to(plan.ROOT).as_posix(), sha256=plan.digest(path)) for path in evidence],
        result_scope=dict(種別='非金融の条件付き価格先着', 旧既知セッション=33, 測定口座=66,
                          修正版NPZ本文=66, 初版資格停止NPZ本文=1, 停止時測定口座=0,
                          独立追加標本=False, 新金融=0, 追加二場本文=0, API=0, 経済目標='未測定'))
    table['updated_at'] = datetime.now(timezone(timedelta(hours=9))).isoformat()
    manager.validate(all_data, deep=True)
    target = directory / 'data/trials.json'
    previous = target.read_bytes()
    old_hash = hashlib.sha256(previous).hexdigest()
    archive = directory / 'data/history' / ('trials_' + old_hash + '.json')
    if archive.exists():
        assert archive.read_bytes() == previous
    else:
        archive.write_bytes(previous)
    raw = (json.dumps(table, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    all_data['source_sha256']['trials.json'] = hashlib.sha256(raw).hexdigest()
    temporary = directory / 'data/trials_114_completed.tmp'
    staged = directory / 'data/view-data_114_completed.tmp'
    assert not temporary.exists() and not staged.exists()
    temporary.write_bytes(raw)
    staged.write_text(manager.bundle(all_data), encoding='utf-8')
    temporary.replace(target)
    staged.replace(directory / 'data/view-data.js')
    plan.write(proof, dict(全合格=True, id=plan.TRIAL, 状態='非金融検証済み・売買目標未測',
                          元台帳保全SHA256=old_hash, source五つ不変=True, 新金融=0))
    print('114R2を非金融検証済みで記録。先着率と利益を区別し、停止初版も保持しました。')


if __name__ == '__main__':
    main()
