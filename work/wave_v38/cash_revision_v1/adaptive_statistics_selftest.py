"""実相場を使わず、全974条件の独立集計と破損拒否を検査する。"""

from copy import deepcopy
from pathlib import Path
import numpy as np

import adaptive_runner as runner
import adaptive_runner_synthetic as fixture_source
import adaptive_independent_statistics as statistics


def artificial(spec: dict, symbol: str, inactive: bool = False) -> tuple:
    """機能: 新規方式用の人工入力と指定された役割の符号を組み立てる。

    引数: spec (dict)、symbol (str)、inactive (bool)。返り値: ready、10列、config (tuple)。
    """
    ready, state, config, bad, bs, good, gs, valid, branch, source, bv = fixture_source.fixture(symbol)
    if inactive:
        state[:] = 0
    if spec['bad_seed'] is not None:
        bad = bad * (1 - 2 * ((bs + spec['bad_seed']) % 2).astype(np.int8))
    if spec['good_seed'] is not None:
        good = good * (1 - 2 * ((gs + spec['good_seed']) % 2).astype(np.int8))
    choice = np.zeros(len(state), np.int8) if spec['branch_seed'] is None else ((source + spec['branch_seed']) % 2).astype(np.int8)
    return ready, (state, bad, bs, good, gs, valid, branch, source, bv, choice), config


def play(spec: dict, ready: dict, columns: tuple, config: dict) -> dict:
    """機能: 新規損益ではない人工経路へ、全入力と仕様を明示して渡す。

    引数: spec/ready/config (dict)、columns (tuple)。返り値: 人工結果 (dict)。
    """
    state, bad, bs, good, gs, valid, branch, source, bv, choice = columns
    return runner.engine.run(ready, state, config, bad, bs, good, gs, spec['policy'],
        observed_fill=spec['observed_fill'], detail=True, good_valid=valid,
        budget_enabled=spec['budget_enabled'], min_delay_seconds=spec['min_delay_seconds'],
        branch_direction=branch, branch_source=source, branch_valid=bv,
        branch_mode=spec['branch_mode'], branch_seed=spec['branch_seed'], branch_choice=choice)


def run() -> dict:
    """機能: 全仕様のsession/periodを照合し、必須項目欠落と数値改竄を拒否する。

    引数: なし。返り値: 人工検査結果 (dict)。新しい実データへ接続しない。
    """
    specs = runner.design.catalog() + runner.design.supplementary()
    count = 0; rejection = 0; retained = None; retained_period = None
    for spec in specs:
        rows, series = [], {}
        for symbol in runner.SYMBOLS:
            for inactive in (False, True):
                ready, columns, config = artificial(spec, symbol, inactive)
                result = play(spec, ready, columns, config)
                basic, curves = runner.accounting.reconstruct(ready, result, symbol)
                row = statistics.session(spec['id'], ready, result, config, basic, curves, columns, spec)
                saved = runner.session_row(spec['id'], ready, result, config, columns[1], basic, curves)
                statistics.equal(saved, row, '人工session全項目')
                if not inactive:
                    rows.append(row); series[(ready['session'], symbol)] = curves['equity']
                if spec['id'] == runner.design.PRIMARY_ID and symbol == 'TOPIX' and not inactive:
                    retained = row
                count += 1
        expected = runner.period(rows, ['2026-09-21_Day'])
        for symbol in runner.SYMBOLS:
            actual = statistics.period(rows, series, ['2026-09-21_Day'], symbol, runner.base.research.MULT[symbol])
            statistics.equal(expected[symbol], actual, '人工period全項目')
            if spec['id'] == runner.design.PRIMARY_ID and symbol == 'TOPIX':
                retained_period = actual
    assert retained is not None and retained_period is not None
    for label, row in (('session', retained), ('period', retained_period)):
        for field in row:
            changed = deepcopy(row); del changed[field]
            try:
                statistics.equal(changed, row, label + '項目欠落')
            except AssertionError:
                rejection += 1
            else:
                raise AssertionError('必須項目の欠落を受理:' + field)
            if isinstance(row[field], (int, float)) and not isinstance(row[field], bool):
                changed = deepcopy(row); changed[field] += 1
                try:
                    statistics.equal(changed, row, label + '数値改竄')
                except AssertionError:
                    rejection += 1
                else:
                    raise AssertionError('数値の改竄を受理:' + field)
    return dict(全合格=True, 全条件数=len(specs), 人工入力検査数=count,
        破損欠落拒否数=rejection, 全session必須項目数=len(retained), 全period必須項目数=len(retained_period),
        分岐は公開入力と実減量注文から再導出=True, 全組R超過は全返済から再導出=True,
        新実データ損益=False, API取得数=0, 現在保存物使用=False,
        参照SHA256={p.relative_to(runner.ROOT).as_posix(): runner.digest(p) for p in (
            Path(__file__), Path(statistics.__file__), Path(fixture_source.__file__),
            Path(runner.__file__), runner.HERE/'adaptive_design.py',
            runner.HERE/'engine_partial_restore.py', runner.HERE/'engine_shadow_plan.py')})


if __name__ == '__main__':
    result = run()
    runner.save(runner.HERE/'adaptive_statistics_selftest.json', result)
    print(f'独立統計の人工{result["人工入力検査数"]}件と拒否{result["破損欠落拒否数"]}件に合格。', flush=True)
