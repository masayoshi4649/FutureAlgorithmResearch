"""原入力を読まず、数量応答の分母・対応・保存を独立した固定値で検査する。"""

import json

import numpy as np

import plan
import run


FIELDS = ['type', 'episode', 'd', 'bid', 'ask', 'opposite_q0',
          'quantity_ratio', 'minimum_quantity_ratio', 'total_volume', 'npositive']

# ----------------------------------------


def main() -> None:
    """
    機能: 各群の全分母と先着・打切、同episode対応、44列資格、保存型を純人工検査する。
    引数: なし。
    返り値: None。原NPZ・金融・原板・APIを読まない。
    """
    proof = plan.HERE / '根の分母と対応及び原始型保存の純人工_v3.json'
    assert not proof.exists()
    checks = 0
    events, outcomes = [], []
    cases = [(.0, 1.2, .8, 1), (1., .5, .5, -1),
             (2., .5, .5, -1), (3., 1., 1., 0), (4., 1.2, .75, 2)]
    for episode, ratio, minimum, code in cases:
        for stage in ((0,) if episode == 1 else (0, 1)):
            events.append([stage, episode, 1, 100, 101, 10, ratio, minimum, 10, 2])
            outcomes.append([code, 20 + episode])
    events, outcomes = np.array(events, float), np.array(outcomes, float)
    summary = run.summarize(events, outcomes, FIELDS, 1)
    expected = dict(type0_all=(5, 1, 2, 1, 1), type0_reached=(4, 1, 1, 1, 1),
                    type1_all=(4, 1, 1, 1, 1), type1_decreased=(1, 0, 1, 0, 0),
                    type1_maintained=(3, 1, 0, 1, 1), type1_never_below=(1, 0, 0, 1, 0),
                    type1_recovered=(2, 1, 0, 0, 1))
    for key, wanted in expected.items():
        actual = summary[key]
        assert tuple(actual[name] for name in ('n', 'plus', 'minus', 'unknown', 'eof')) == wanted
        checks += 5
        assert actual['resolved'] == actual['plus'] + actual['minus']
        checks += 1
    assert summary['type1_all']['rate'] == .5
    assert summary['type0_all']['rate'] == 1 / 3
    assert summary['type1_never_below']['rate'] is None
    checks += 3
    boundary = outcomes.copy()
    boundary[boundary[:, 0] == 0, 0] = 3
    separated = run.summarize(events, boundary, FIELDS, 1)
    assert separated['type1_all']['unknown'] == 0 and separated['type1_all']['window_end'] == 1
    assert separated['type1_all']['n'] == 4 and separated['type1_all']['rate'] == .5
    checks += 4
    empty = run.summarize(np.empty((0, len(FIELDS))), np.empty((0, 2)), FIELDS, 1)
    assert all(empty[key]['n'] == 0 and empty[key]['rate'] is None for key in expected)
    checks += len(expected)
    rows = [dict(session='人工_Day', symbol='TOPIX', groups=summary),
            dict(session='人工_Night', symbol='TOPIX', groups=summary)]
    total = run.aggregate(rows, 'TOPIX')
    for key, wanted in expected.items():
        assert total['all']['groups'][key]['n'] == wanted[0] * 2
        assert total['Day']['groups'][key]['n'] == total['Night']['groups'][key]['n'] == wanted[0]
        checks += 3
    wrong = outcomes.copy()
    wrong[-1, 0] = -1
    try:
        run.summarize(events, wrong, FIELDS, 1)
    except AssertionError:
        checks += 1
    else:
        raise AssertionError('同episodeの先着差を検出できない')
    for value in (np.bool_(True), np.int64(5), np.float64(.5), dict(値=np.array([1, 2]))):
        json.dumps(run.primitive(value), ensure_ascii=False, allow_nan=False)
        checks += 1
    for value in (float('nan'), np.float64(float('inf'))):
        try:
            run.primitive(dict(値=value))
        except AssertionError:
            checks += 1
        else:
            raise AssertionError('非有限数値が保存された')
    fixed = plan.read(plan.HERE / '入力と観測の小固定.json')
    arrays = {}
    n, m = 6, 3
    for name, wanted in fixed['schema'].items():
        shape = tuple(n if size == 'N' else m if size == 'M' else size for size in wanted['shape'])
        arrays[name] = np.zeros(shape, np.dtype(wanted['dtype']))
    arrays['raw_seq'][:] = np.arange(n)
    arrays['normal_execution_row'][[0, 2, 4]] = True
    arrays['execution_to_raw_index'][:] = [0, 2, 4]
    run.validate(arrays, fixed['schema'])
    assert not any(value.flags.writeable for value in arrays.values())
    checks += 45
    corrupted = {name: value.copy() for name, value in arrays.items()}
    corrupted['execution_to_raw_index'][1] = 3
    try:
        run.validate(corrupted, fixed['schema'])
    except AssertionError:
        checks += 1
    else:
        raise AssertionError('正常行map不一致を検出できない')
    plan.write(proof, dict(全合格=True, 検査数=checks, source_SHA256=plan.sources(),
                          測定NPZ=0, 元金融=0, 原板=0, API=0, 新金融=0))
    print(json.dumps(dict(全合格=True, 検査数=checks), ensure_ascii=False))


if __name__ == '__main__':
    main()
