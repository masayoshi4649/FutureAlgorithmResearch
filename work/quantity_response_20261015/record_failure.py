"""観測前の入力資格検査停止を試行履歴へ残し、元sourceと根拠を保持する。"""

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json

import plan


def main() -> None:
    """
    機能: 旧114の一読・測定0を記録し、不具合修正試行と区別する。
    引数: なし。
    返り値: None。元NPZ・市場値・金融を読み直さない。
    """
    proof = plan.HERE / '入力資格停止の登録.json'
    assert not proof.exists()
    failure = plan.HERE / 'measurement/False.json'
    saved = plan.read(failure)
    assert not saved['全合格'] and saved['counts']['NPZ本文'] == 1 and saved['counts']['測定口座'] == 0
    directory = plan.ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合'
    specification = importlib.util.spec_from_file_location('数量初版の停止登録', directory / 'manage.py')
    manager = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(manager)
    all_data = manager.load()
    table = all_data['trials']
    selected = [row for row in table['trials'] if row['id'] == plan.TRIAL]
    assert len(selected) == 1 and selected[0]['status'] == '未実行'
    selected[0].update(status='未測定（入力資格検査で中断）',
        result='normal_execution_rowのint32逆写像をboolと誤認した検査で停止。NPZ1読、測定0、金融0。元sourceを保持しR2で訂正する。',
        evidence=[dict(path=failure.relative_to(plan.ROOT).as_posix(), sha256=plan.digest(failure))],
        result_scope=dict(NPZ本文=1, 測定口座=0, 新金融=0, 自動再実行=False))
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
    temporary = directory / 'data/trials_114_failed.tmp'
    staged = directory / 'data/view-data_114_failed.tmp'
    assert not temporary.exists() and not staged.exists()
    temporary.write_bytes(raw)
    staged.write_text(manager.bundle(all_data), encoding='utf-8')
    temporary.replace(target)
    staged.replace(directory / 'data/view-data.js')
    plan.write(proof, dict(全合格=True, 状態='入力資格検査で中断・測定0',
                          旧台帳保全SHA256=old_hash, 本文再読=0, 新金融=0))
    print('初版114はNPZ1読・観測0の資格検査中断として記録しました。')


if __name__ == '__main__':
    main()
