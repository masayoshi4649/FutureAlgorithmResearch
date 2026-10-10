"""新損益の再生前に、入力・全条件・注文器・採否の指紋を固定する。"""

from __future__ import annotations

from pathlib import Path
import sys

import runner

HERE, ROOT = runner.HERE, runner.ROOT


def prepare() -> dict:
    """機能: 完了済みの入力監査と人工監査を確認し、参照の変更を拒否する。

    引数: なし。返り値: 探索固定(dict)。新しい実相場損益を読む処理はない。
    """
    path = HERE/'探索条件の固定.json'
    if path.exists():
        result = runner.read(path)
        assert result['conditions'] == runner.design.catalog()
        runner.verify(result['参照資料SHA256'])
        return result
    references = {}

    def bind(values: dict) -> None:
        """機能: 固定元間の食い違いを上書きせず検出する。

        引数: values(dict[str,str])。返り値: なし(None)。
        """
        for relative, sha in values.items():
            assert relative not in references or references[relative] == sha, relative
            references[relative] = sha

    corrected = runner.read(HERE.parent/'wave_v41/状態修正の全再生.json')
    assert corrected['全合格'] and corrected['全条件数'] == 974
    bind(runner.read(HERE.parent/'wave_v41/状態修正の固定.json')['参照資料SHA256'])
    signal = runner.read(HERE/'signals_fixed.json')
    assert signal['全合格'] and signal['全入力監査合格']
    for field in ('SHA256', '参照資料SHA256', '入口保存列SHA256', '構成窓保存列SHA256', '原本78SHA256'):
        bind(signal[field])
    signal_audit = runner.read(HERE/'signal_audit.json')
    assert signal_audit['全合格']
    assert signal_audit['全方向セル数'] == 312 and signal_audit['旧3倍率完全一致数'] == 78
    for field in ('prefix数', 'future数', 'reflection数', '同時刻切断数'):
        assert signal_audit[field] == 312
    artificial = runner.read(HERE/'check_runner.json')
    assert artificial['全合格'] and artificial['人工入力検査数'] == 128
    bind(artificial['参照資料SHA256'])
    assessment = runner.read(HERE/'check_assessment.json')
    assert assessment['全合格']
    bind(assessment['参照資料SHA256'])
    assessment_fixed = runner.read(HERE/'assessment_fixed.json')
    assert assessment_fixed['条件'] == runner.design.catalog() and assessment_fixed['旧関数構文全一致']
    bind(assessment_fixed['SHA256'])
    # ----------------------------------------
    # 元単一窓6本も出力指紋を事前に固定し、結果後の置換を防ぐ。
    paths = {HERE/name for name in ('design.py', 'runner.py', 'prepare.py', 'complete.py',
        'window_signals.py', 'signals_fixed.json', 'signal_audit.json',
        'check_runner.py', 'check_runner.json', 'assessment.py', 'check_assessment.py',
        'check_assessment.json', 'assessment_fixed.json', '反証計画.md', '時間窓合議の独立性確認.md')}
    paths.update((HERE.parent/'wave_v41/状態修正の全再生.json',
                  HERE.parent/'wave_v41/状態修正の固定.json'))
    for spec in runner.design.catalog():
        previous = runner.legacy_id(spec)
        if previous:
            for folder, suffix in (('ledgers', '.json.gz'), ('sessions', '.json.gz'), ('summaries', '.json')):
                paths.add(HERE.parent/'wave_v38'/folder/(previous+suffix))
    paths.update(HERE/'entries'/(name+'.npz') for name in runner.design.SIGNALS)
    for value in tuple(sys.modules.values()):
        name = getattr(value, '__file__', None)
        if name:
            source = Path(name).resolve()
            if source.is_relative_to(ROOT/'work') and source.suffix == '.py':
                paths.add(source)
    bind({p.relative_to(ROOT).as_posix():runner.digest(p) for p in paths})
    runner.verify(references)
    old_fixed = runner.read(HERE.parent/'wave_v38/探索条件の固定.json')
    result = dict(conditions=runner.design.catalog(), rules=runner.design.rules(),
        全条件数=32, 全入力数=832, 因果入力数=128, 旧単一窓一致入力数=156,
        全セッション=old_fixed['全セッション'], 後半7セッション=old_fixed['後半7セッション'],
        参照資料SHA256=references, 現在API取得数=0, 保存ライブ使用=False,
        新実相場損益確認前=True, 全体目標達成=False)
    runner.save(path, result)
    return result


if __name__ == '__main__':
    value = prepare()
    print(f"{value['全条件数']}条件・{value['全入力数']}入力を新損益の前に固定。", flush=True)
