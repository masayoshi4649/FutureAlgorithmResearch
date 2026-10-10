"""新損益を見る前に、全主案・対照・実装・検査を固定する。"""

from __future__ import annotations

from pathlib import Path
import sys

import runner

HERE, ROOT = runner.HERE, runner.ROOT


def prepare() -> dict:
    """機能: 旧資料との競合と検査後の変更を拒否して探索を固定する。

    引数: なし。返り値: 全163条件の固定資料(dict)。新戦略の実損益は読まない。
    """
    path = HERE/'探索条件の固定.json'
    if path.exists():
        fixed = runner.read(path)
        assert fixed['conditions'] == runner.design.catalog()
        assert fixed['supplementary'] == runner.design.supplementary()
        runner.verify(fixed['参照資料SHA256'])
        return fixed
    references = {}

    def bind(values: dict) -> None:
        """機能: 複数固定元の指紋を上書きせず結合する。

        引数: values(dict[str,str])。返り値: なし(None)。
        """
        for relative, sha in values.items():
            assert relative not in references or references[relative] == sha, relative
            references[relative] = sha

    corrected = runner.read(HERE.parent/'wave_v41/状態修正の全再生.json')
    assert corrected['全合格'] and corrected['全条件数'] == 974
    bind(runner.read(HERE.parent/'wave_v41/状態修正の固定.json')['参照資料SHA256'])
    gate = runner.read(HERE/'profit_gate_fixed.json')
    assert gate['全合格'] and gate['全入力監査合格']
    assert (gate['全入力数'], gate['入力仕様数'], gate['全セル数']) == (26, 16, 416)
    assert gate['新戦略売買再生'] is False and gate['新損益資料読取'] is False
    for field in ('参照SHA256', '旧入力参照SHA256'):
        bind(gate[field])
    for name in ('check_runner.json', 'check_assessment.json', 'check_complete.json'):
        check = runner.read(HERE/name)
        assert check['全合格'] is True and check['新実相場損益'] is False, name
        bind(check['参照資料SHA256'])
    assessment = runner.read(HERE/'assessment_fixed.json')
    assert assessment['条件'] == runner.design.catalog()+runner.design.supplementary()
    assert assessment['旧関数構文全一致'] is True
    bind(assessment['SHA256'])
    input_audit = runner.read(HERE/'gate_input_audit.json')
    counts = {}
    for row in input_audit['結果']:
        key = row['session']+'|'+row['symbol']
        assert key not in counts or counts[key] == row['原本行数']
        counts[key] = row['原本行数']
    assert len(counts) == 26 and len(input_audit['結果']) == 416
    # ----------------------------------------
    # 旧対照6本の実物も指紋化し、結果後の対照の差し替えを拒否する。
    paths = {HERE/name for name in ('design.py', 'runner.py', 'prepare.py', 'complete.py',
        'profit_gate.py', 'profit_gate_fixed.json', 'check_profit_gate.py', 'check_profit_gate.json',
        'check_gate_inputs.py', 'gate_input_audit.json', '減量開始時点の独立性確認.md',
        'check_runner.py', 'check_runner.json', 'assessment.py', 'check_assessment.py',
        'check_assessment.json', 'assessment_fixed.json', 'check_complete.py', 'check_complete.json',
        '反証設計案.md', '反証計画.md')}
    paths.update((HERE.parent/'wave_v41/状態修正の全再生.json',
                  HERE.parent/'wave_v41/状態修正の固定.json'))
    for spec in runner.design.catalog():
        previous = runner.legacy_id(spec)
        if previous:
            for folder, suffix in (('ledgers', '.json.gz'), ('sessions', '.json.gz'), ('summaries', '.json')):
                paths.add(HERE.parent/'wave_v38'/folder/(previous+suffix))
    for value in tuple(sys.modules.values()):
        name = getattr(value, '__file__', None)
        if name:
            source = Path(name).resolve()
            if source.is_relative_to(ROOT/'work') and source.suffix == '.py':
                paths.add(source)
    bind({p.relative_to(ROOT).as_posix():runner.digest(p) for p in paths})
    runner.verify(references)
    old = runner.read(HERE.parent/'wave_v38/探索条件の固定.json')
    fixed = dict(conditions=runner.design.catalog(), supplementary=runner.design.supplementary(),
        rules=runner.design.rules(), 主条件数=35, 補助条件数=128, 全条件数=163,
        全入力数=4238, 因果入力数=652, 旧単一窓一致入力数=156, 必須出力数=1141,
        原本行数=counts,
        全セッション=old['全セッション'], 後半7セッション=old['後半7セッション'], 指定波=old['指定波'],
        参照資料SHA256=references, 現在API取得数=0, 保存ライブ使用=False,
        新実相場損益確認前=True, 全体目標達成=False)
    runner.save(path, fixed)
    return fixed


if __name__ == '__main__':
    result = prepare()
    print(f"全{result['全条件数']}条件を新損益の前に固定。", flush=True)
