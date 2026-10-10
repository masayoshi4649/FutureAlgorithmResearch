"""新しい接続器を切断・未来変更して、過去の注文列が変わらないことを確かめる。"""

from pathlib import Path
import hashlib
import numpy as np

import replay
import study

HERE = Path(__file__).resolve().parent


def clipped(ready: dict, count: int) -> dict:
    """機能: 時刻・価格・指標の原本行配列を同じ位置で切断する。

    引数: ready(dict)、count(int)。返り値: 切断入力(dict)。
    """
    n = len(ready['last'])
    return {k: v[:count].copy() if isinstance(v, np.ndarray) and v.ndim and len(v) == n else v
        for k, v in ready.items()}


def prefix(a: tuple, b: tuple, count: int) -> None:
    """機能: 当該行より前に確定した取引と各行後の状態を照合する。

    引数: a/b(tuple)、count(int)。返り値: なし(None)。
    """
    for left, right in ((a[0], b[0]), (a[0]['shadow'], b[0]['shadow']), (a[3], b[3])):
        for name, col in (('orders', 0), ('trades', 7), ('cycles', 2), ('prepare_events', 1), ('entry_preparations', 1)):
            x, y = left[name], right[name]
            np.testing.assert_array_equal(x[x[:, col] < count], y[y[:, col] < count])
        for name in ('curve', 'atr_curve', 'plans', 'execution_plans'):
            if name in left:
                np.testing.assert_array_equal(left[name][:count], right[name][:count])
    for left, right in zip(a[1], b[1]):
        np.testing.assert_array_equal(left[:count], right[:count])


def main() -> None:
    """機能: 十六条件・二価格モデルを、新規追加ナイトで因果検査する。

    引数: なし。返り値: なし(None)。
    """
    replay.integration.reference.initialize()
    inputs, _, _ = study.load_inputs()
    models = {k: replay.gate.model(v) for k, v in inputs.items()}
    records = []
    for observed in (False, True):
        for variant in replay.catalog():
            key = ('2026-10-07_Night', 'TOPIX')
            ready = inputs[key]
            columns, valid = study.columns_for(variant, key, ready, models)
            actual = replay.play(variant, ready, columns, valid, observed=observed)
            n = len(ready['last'])
            cut, change = int(n * .37), int(n * .73)
            partial = replay.play(variant, clipped(ready, cut), tuple(v[:cut].copy() for v in columns), valid[:cut].copy(), observed=observed)
            prefix(actual, partial, cut)
            del partial
            edited = clipped(ready, n)
            edited['last'][change:] += ready['tick'] * (37 + np.arange(n - change))
            edited['atr'][change:] *= 3
            altered = [v.copy() for v in columns]
            for i in (0, 1, 3, 6):
                altered[i][change:] = np.where(altered[i][change:] == 1, -1, 1)
            for i in (2, 4, 7):
                altered[i][change:] = np.arange(change, n)
            changed = replay.play(variant, edited, tuple(altered), valid.copy(), observed=observed)
            prefix(actual, changed, change)
            records.append(dict(方式=variant['id'], 観測価格=observed, 対象=list(key), 切断一致=True, 未来変更一致=True))
            del actual, changed
        print('観測価格' if observed else '指定価格', '16条件の因果検査完了', flush=True)
    deps = [HERE / 'engine_shadow.py', HERE / 'engine_partial.py', Path(replay.gate.__file__),
        Path(replay.integration.reference.gate.__file__)]
    study.save(HERE / '実装追加照合.json', dict(記録時点='経済再生開始後の追加照合。事前固定の実装一覧を上書きしない。',
        元実装コピー一致={name: (HERE / local).read_bytes() == (study.ROOT / original).read_bytes()
            for name, local, original in [('影', 'engine_shadow.py', 'work/wave_v38/engine_shadow_plan.py'),
                ('枠', 'engine_partial.py', 'work/wave_v47/exit_partial_integrated.py')]},
        SHA256={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in deps}))
    study.save(HERE / '接続器の因果検査.json', dict(全合格=True, 検査数=len(records), 検査=records,
        指標生成='追加5場は元生成器の切断・未来変更・反射・同秒順を別途全件検査済み。今回検査は改修後の接続器と注文生成。'))


if __name__ == '__main__':
    main()
