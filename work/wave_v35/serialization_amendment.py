"""保存形式の修正だけで売買成績が変わっていないことを追跡する。"""

import argparse

import conditional_runner as runner

HERE = runner.HERE
ARCHIVE = HERE / 'attempt_01'


def main() -> None:
    """機能: 失敗版と修正版の条件同一性、再実行後の全初期損益バイト一致を記録する。

    引数: --after-replay (bool)。返り値: なし (None)。損益の数値を読まない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--after-replay', action='store_true')
    after = parser.parse_args().after_replay
    before = runner.read(ARCHIVE / '探索条件の固定.json')
    current = runner.read(HERE / '探索条件の固定.json')
    for field in before:
        if field not in ('固定日時', 'SHA256'):
            assert before[field] == current[field]
    assert set(before['SHA256']) == set(current['SHA256'])
    changed = sorted(name for name in before['SHA256'] if before['SHA256'][name] != current['SHA256'][name])
    assert changed == ['work/wave_v35/conditional_runner.py', 'work/wave_v35/runner_synthetic_audit.py']
    archived = list((ARCHIVE / 'training/sessions').glob('*.json.gz'))
    assert len(archived) == 840
    assert not list((ARCHIVE / 'training/summaries').glob('*.json'))
    value = {'保存形式のみ修正': True, '変更実装': changed,
        '売買条件変更': False, '判定変更': False, '入力変更': False,
        '原因': '追跡開始時prior_levelと追加候補なしshort_candidateの仕様上NaNをJSONが拒否。',
        '修正': '保存だけNaN→null。数値配列・損益・指紋は元のまま。指定2列以外の非有限値は拒否。',
        '初回前6計算済条件数': 840, '初回完成集計数': 0, '初回選択': False, '初回後半再生': False,
        '初回結果数値の閲覧': False, '旧探索固定SHA256': runner.digest(ARCHIVE / '探索条件の固定.json'),
        '新探索固定SHA256': runner.digest(HERE / '探索条件の固定.json'),
        '旧実装SHA256': runner.digest(ARCHIVE / 'conditional_runner.py'),
        '新実装SHA256': runner.digest(HERE / 'conditional_runner.py'),
        '旧初期840資料SHA256': {p.name: runner.digest(p) for p in sorted(archived)},
        '再実行後照合': after, '全初期840資料バイト一致': False}
    if after:
        for path in archived:
            assert runner.digest(path) == runner.digest(HERE / 'training/sessions' / path.name)
        value['全初期840資料バイト一致'] = True
    runner.save(HERE / ('保存形式修正の再検算.json' if after else '保存形式修正の記録.json'), value)
    print('保存形式以外は不変。' + ('初期840資料も全バイト一致。' if after else '再実行後に全バイト照合する。'))


if __name__ == '__main__':
    main()
