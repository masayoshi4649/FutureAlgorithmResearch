"""限定改訂の旧固定・新固定・人工反例を再起動前に結びつける。"""

from pathlib import Path
import adaptive_cash_revision_guard as revision


def main() -> None:
    """機能: 変更範囲を検証し、全974の再計算へ進める証跡を保存する。

    引数: なし。返り値: なし (None)。旧158との比較は再計算後にも要求する。
    """
    runner=revision.runner;here=runner.HERE
    revision.legacy()
    applied=runner.read(here/'adaptive_cash_revision_applied.json')
    assert applied['適用完了'] and applied['境界2領域以外本文同一']
    for field in ('売買変更','入力変更','損益算術変更','採否変更','対象変更'):assert applied[field] is False
    assert runner.digest(here/'adaptive_cash_reconstruction.py')==applied['新会計SHA256']
    old=runner.read(here/'cash_revision_v1/起動前監査.json')
    allowed={'work/wave_v38/'+name for name in ('adaptive_cash_reconstruction.py','adaptive_runner_synthetic.json',
        'random_path_audit.json','adaptive_accounting_fixed.json')}
    changed={name for name,sha in old['SHA256'].items() if runner.digest(runner.ROOT/name)!=sha}
    assert changed==allowed,changed
    previous=runner.read(here/'cash_revision_v1/探索条件の固定.json')
    current=runner.prepare()
    for field in ('conditions','supplementary_conditions','manager','全セッション','後半7セッション','指定波','主仮説'):
        assert previous[field]==current[field],field
    initial={name for name,sha in previous['SHA256'].items() if runner.digest(runner.ROOT/name)!=sha}
    assert initial=={'work/wave_v38/adaptive_cash_reconstruction.py'}
    startup=runner.read(here/'起動前監査.json')
    assert startup['実行可能'] and startup['探索固定SHA256']==runner.digest(here/'探索条件の固定.json')
    sources={name:sha for name,sha in startup['SHA256'].items()}
    for name in ('adaptive_cash_revision_plan.json','adaptive_cash_revision_failure_v1.json',
            'adaptive_cash_revision_checks.py','adaptive_cash_revision_checks.json','adaptive_close_boundary_review.json',
            'adaptive_cash_revision_applied.json','adaptive_cash_reconstruction_v2_candidate.py',
            'adaptive_runner_synthetic_v2.py','build_runner_synthetic_v2.py','adaptive_cash_revision_guard.py',
            'apply_cash_revision.py','探索条件の固定.json','起動前監査.json'):
        path=here/name;sources[path.relative_to(runner.ROOT).as_posix()]=runner.digest(path)
    for name,sha in sources.items():assert runner.digest(runner.ROOT/name)==sha,name
    proof=dict(再起動可能=True,主条件数=206,補助条件数=768,元158再照合必須=True,
        旧固定から変更した検査資料=sorted(changed),全売買条件不変=True,損益算術不変=True,
        主再生中断後の限定改訂=True,同一試行の結果前固定と偽らない=True,現在API取得数=0,
        ガードSHA256=runner.digest(Path(__file__)),参照SHA256=sources)
    runner.save(here/'adaptive_cash_revision_ready.json',proof)
    print('境界改訂・全人工再試験・新固定を結合。974条件を同一規則で再起動可能。')


if __name__=='__main__':main()
