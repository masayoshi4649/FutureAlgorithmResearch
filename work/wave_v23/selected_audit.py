"""凍結済み探索から選ばれた５候補を、全原本行の詳細会計で独立再検算する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

from audit_core import check_accounting, check_execution_prefix
import engine
import managers
import research

OUT = Path(__file__).resolve().parent


def main() -> None:
    """機能: 選択済み５候補×全26入力を再生し、保存台帳と金額・数量を照合する。

    引数: なし。返り値: なし (None)。候補、選定条件、入力、過去成果を変更しない。
    """
    selected = json.loads((OUT / '選択結果.json').read_text(encoding='utf-8'))
    fixed = json.loads((OUT / '探索前の固定記録.json').read_text(encoding='utf-8'))
    items = json.loads((OUT / '全条件一覧.json').read_text(encoding='utf-8'))
    saved_rows = json.loads((OUT / '全条件セッション集計.json').read_text(encoding='utf-8'))
    lookup = {(row['id'], row['session'], row['symbol']): row for row in saved_rows}
    definitions = {item['id']: item for item in items}
    inputs = pickle.loads((OUT / 'inputs.pkl').read_bytes())
    directions = pickle.loads((OUT / 'directions.pkl').read_bytes())
    code_check = {name: hashlib.sha256((OUT / name).read_bytes()).hexdigest() == digest
                  for name, digest in fixed['コードSHA256'].items()}
    assert all(code_check.values()), ('探索後の実装変更', code_check)
    records = []
    assert len(selected['finalists']) == 5
    for identifier in selected['finalists']:
        spec = definitions[identifier]
        with np.load(OUT / 'trades' / f'{identifier}.npz', allow_pickle=False) as ledger:
            for key, ready in inputs.items():
                session, symbol = key
                config = managers.make_config(spec['manager'], symbol, ready)
                direction = directions[spec['signal_id']][key]
                result = engine.run(ready, direction, config, detail=True)
                record = dict(手法ID=identifier, セッション=session, 銘柄=symbol)
                record.update(check_accounting(ready, result, config))
                np.testing.assert_array_equal(result['trades'], ledger[session + '_' + symbol + '_trades'])
                np.testing.assert_array_equal(result['cycles'], ledger[session + '_' + symbol + '_cycles'])
                actual = research.summarize(result, config, symbol, session, identifier)
                expected = lookup[(identifier, session, symbol)]
                assert actual.keys() == expected.keys()
                for name, value in actual.items():
                    if isinstance(value, (int, float)):
                        np.testing.assert_allclose(value, expected[name], rtol=0, atol=.000001,
                                                   err_msg=f'{identifier}/{session}/{symbol}/{name}')
                    else:
                        assert value == expected[name]
                record['保存済み返済と組台帳一致'] = True
                record['保存済み金額と数量集計一致'] = True
                if session in ['2026-09-28_Night', '2026-09-29_Day']:
                    record.update(check_execution_prefix(engine, ready, direction, config, result, fractions=(.31, .67)))
                records.append(record)
        print(f'{identifier}: 26 入力の独立詳細会計に合格', flush=True)
    output = dict(合格=True, 選定後の上位候補=selected['finalists'], 詳細再生件数=len(records),
                  全行検算合計=sum(row['全行検算'] for row in records), 凍結コード一致=code_check,
                  入力または選定条件変更なし=True, 原本と過去成果不変=True, 現在API取得数=0,
                  対象='全て既読の実データ。選定後の再計算整合性と会計監査であり、新たな未見評価ではない。', 結果=records)
    (OUT / 'selected_audit.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
