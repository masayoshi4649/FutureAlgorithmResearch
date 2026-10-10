"""損益前構造監査と、実際の再生器が読む保存C/S配列の一致を接続する。"""

from __future__ import annotations

import pickle

import numpy as np

import context_structure_audit as audit


def main() -> None:
    """機能: 凍結済みrunner入力を全再生成し、損益前の実行許可記録を保存する。

    引数: なし。返り値: なし (None)。売買再生や損益資料の読み込みは行わない。
    """
    report = audit.read(audit.HERE / 'context_structure_audit.json')
    assert report['構造検査合格'] and not report['売買再生'] and not report['損益ファイル読取']
    fixed = audit.read(audit.HERE / '探索条件の固定.json')
    for relative, expected in fixed['SHA256'].items():
        assert audit.digest(audit.HERE.parent / relative) == expected
    inputs = pickle.loads((audit.OLD / 'inputs.pkl').read_bytes())
    audit.SIGNALS.set_root(audit.ROOT)
    count = 0
    for spec, own in audit.paired_specs():
        assert fixed['own_signals'][spec['id']] == own
        assert next(value for value in fixed['signals'] if value['id'] == spec['id']) == spec
        for source in (spec, own):
            generated = audit.SIGNALS.main_directions(source, inputs)
            with np.load(audit.V28 / 'contexts' / f'{source["id"]}.npz') as archive:
                assert set(archive.files) == {'|'.join(key) for key in inputs}
                for key in inputs:
                    np.testing.assert_array_equal(generated[key], archive['|'.join(key)])
                    count += 1
    record = dict(report, 実際の保存C_S配列一致数=count, 探索仕様SHA256=audit.digest(audit.HERE / '探索条件の固定.json'),
                  元構造監査SHA256=audit.digest(audit.HERE / 'context_structure_audit.json'),
                  保存列確認コードSHA256=audit.digest(audit.HERE / 'context_saved_alignment.py'),
                  損益前監査完了=True)
    audit.save(audit.HERE / 'context_structure_before_pnl.json', record)
    print(f'保存C/Sの{count}配列が再生成と完全一致。損益前記録を保存。', flush=True)


if __name__ == '__main__':
    main()
