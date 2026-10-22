"""金融計算前の実行キャッシュ不整合を保全し、同源を隔離キャッシュへ接続する。"""

import hashlib
import importlib.util
import json
import os
import numpy as np

import plan119 as plan
import engine119


def main() -> None:
    """
    機能: '<dynamic>'のNumbaキャッシュ読込失敗を保全し、試行台帳へ再開理由を記録する。
    引数: なし。NUMBA_CACHE_DIRは本実行専用の新規領域を要求する。
    返り値: None。同じ経済源を使い、空配列の初期化検査以外の金融再生をしない。
    """
    assert plan.sources() == plan.read(plan.HERE / '正式固定.json')['source_SHA256']
    cache_path = plan.HERE / 'numba_actual119'
    assert os.environ.get('NUMBA_CACHE_DIR') == str(cache_path)
    measurement = plan.HERE / 'measurement'
    archived = plan.HERE / 'measurement_attempt1_initialization_failed'
    assert measurement.is_dir() and not archived.exists()
    raw = (measurement / '入力読取.jsonl').read_text(encoding='utf-8').splitlines()
    assert len(raw) == 2 and len(list(measurement.iterdir())) == 1
    measurement.rename(archived)
    failure = plan.HERE / '初期化停止と同源再開の記録.json'
    plan.write(failure, dict(全合格=True, 原因="Numba共有コンパイルcacheのpickleが'<dynamic>'を要求し、最初の政策を実行する前に停止。",
        初回入力読取=2, 初回計算済み金融政策=0, 初回金融台帳=0,
        保存=archived.relative_to(plan.ROOT).as_posix(), 経済七源不変=True,
        再開差分='経済sourceとパラメータは不変。NUMBA_CACHE_DIRを当実行専用へ隔離。完成80入力の前に同じ既知2入力を再読する。',
        完成予定入力80=80, 初回停止込み予定入力82=82, 有効性標本を追加しない=True, source_SHA256=plan.sources()))

    # ----------------------------------------
    # 市場へ戻る前に、通常module名で本番と同じ数値型の空配列をコンパイルする。
    i = np.empty(0, np.int64)
    f = np.empty(0, np.float64)
    b = np.empty(0, np.bool_)
    d = np.empty(0, np.int8)
    result = engine119.replay(d, i, i, f, f, f, i, f, d, b, b, f, b, f,
        10, 1000., 41.8, 0, 0, 0, 100., 200., .25)
    assert len(result[0]) == 0 and result[3] == 0 and result[5] == 0

    # ----------------------------------------
    # 既登録行へ初期化停止を追記。旧正本を保全し、データ再読の理由を事前に残す。
    directory = plan.ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合'
    spec = importlib.util.spec_from_file_location('_registry119_recovery', directory / 'manage.py')
    manager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manager)
    data = manager.load()
    table = data['trials']
    found = [r for r in table['trials'] if r['id'] == plan.TRIAL]
    assert len(found) == 1 and found[0]['status'] == '未実行'
    found[0]['execution_attempts'] = [dict(status='金融計算前の初期化停止', raw_reads=2, financial_rows=0,
        evidence=dict(path=failure.relative_to(plan.ROOT).as_posix(), sha256=plan.digest(failure))),
        dict(status='同源・隔離キャッシュで再開予定', expected_raw_reads=80, independent_evidence=False)]
    manager.validate(data, deep=True)
    target = directory / 'data/trials.json'
    previous = target.read_bytes()
    old_sha = hashlib.sha256(previous).hexdigest()
    history = directory / 'data/history' / ('trials_' + old_sha + '.json')
    if not history.exists():
        history.write_bytes(previous)
    payload = (json.dumps(table, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    data['source_sha256']['trials.json'] = hashlib.sha256(payload).hexdigest()
    temporary = directory / 'data/trials119_recovery.tmp'
    staged = directory / 'data/view119_recovery.tmp'
    assert not temporary.exists() and not staged.exists()
    temporary.write_bytes(payload)
    staged.write_text(manager.bundle(data), encoding='utf-8')
    temporary.replace(target)
    staged.replace(directory / 'data/view-data.js')
    plan.write(plan.HERE / '同源再開の台帳記録.json', dict(全合格=True, 経済七源不変=True,
        元台帳保全SHA256=old_sha, 初回市場読取=2, 初回金融計算=0, 空初期化検査=True))
    print('初期化停止を保全・台帳記録。通常module名の隔離キャッシュ初期化に合格。', flush=True)


if __name__ == '__main__':
    main()
