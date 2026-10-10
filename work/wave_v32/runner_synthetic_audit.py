"""集計と保存の接続を、無取引・部分利確・切替の合成口座で確認する。"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import engine_selector_audit as fixtures
import selection_runner as runner


def main() -> None:
    """機能: 枝別損益を注文イベントから別集計し、表示用集計と照合する。

    引数: なし。返り値: なし (None)。実相場の損益は生成しない。
    """
    definitions = [
        ('無取引', [100., 100., 100.], [1, 2, 2], [[0, 0]] * 3, None),
        ('整数半分の利確', [100., 101., 109., 110., 107., 103.], [1] * 6, [[1, -1]] * 6, None),
        ('同方向切替と再準備', [100., 100., 100., 101., 96., 100., 99., 103.],
         [1, 2, 2, 2, 1, 1, 1, 1], [[1, 1]] * 8, [0., 1., 2., 3., 4., 310., 311., 312.]),
    ]
    checked = []
    for name, prices, request, states, times in definitions:
        ready, state, requested, config = fixtures.fixture(prices, request, states, times)
        result = runner.engine_selector.run(ready, state, requested, config, detail=True)
        actual = runner.selection_summary(result, ready, 1000.)
        events = result['selection_events']
        # ----------------------------------------
        # 保存曲線に依存せず、新規イベントの組番号から全返済の実入口源を照合する。
        columns = {k: i for i, k in enumerate(runner.engine_selector.EVENT_COLUMNS)}
        origins = {int(row[columns['campaign']]): int(row[columns['entry_source_id']])
                   for row in events if row[columns['event']] == 7}
        expected = {'T': 0., 'R': 0.}
        for row in result['trades']:
            expected['T' if origins[int(row[0])] == 1 else 'R'] += row[2] * row[3] * (row[5] - row[4]) * 1000.
        assert actual['branch_net_yen'] == expected
        clean = events.astype(object)
        clean[np.isnan(events)] = None
        payload = json.dumps(clean.tolist(), allow_nan=False)
        restored = np.asarray(json.loads(payload), dtype=float).reshape((-1, len(columns)))
        np.testing.assert_allclose(restored, events, rtol=0, atol=0, equal_nan=True)
        checked.append({'対象': name, '注文から枝損益一致': True, '未定義価格の有限JSON往復': True})
    evidence = {'合成のみ': True, '全件合格': True, '検査': checked,
                '参照SHA256': {str(HERE / filename): sha256((HERE / filename).read_bytes()).hexdigest()
                               for filename in ('selection_runner.py', 'engine_selector.py', 'runner_synthetic_audit.py')},
                '実相場損益参照': False, 'API取得数': 0}
    (HERE / 'runner_synthetic_audit.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'全件合格': True, '合成ケース数': len(checked)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
