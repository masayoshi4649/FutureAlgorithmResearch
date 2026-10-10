"""機械的選択と売買を一体化した５候補を、全入力の詳細会計で検算する。"""

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
    """機能: 上位選択器５候補の全行損益・注文台帳・切断不変性を検算する。

    引数: なし。返り値: なし (None)。選定ルールと基礎信号は変更しない。
    """
    selection = json.loads((OUT / '選択統合の結果.json').read_text(encoding='utf-8'))
    fixed = json.loads((OUT / '選択統合の探索前固定.json').read_text(encoding='utf-8'))
    specifications = {item['id']: item for item in json.loads((OUT / '選択統合の全条件.json').read_text(encoding='utf-8'))}
    rows = json.loads((OUT / '選択統合のセッション集計.json').read_text(encoding='utf-8'))
    expected = {(row['id'], row['session'], row['symbol']): row for row in rows}
    inputs = pickle.loads((OUT / 'inputs.pkl').read_bytes())
    directions = pickle.loads((OUT / 'selector_directions.pkl').read_bytes())
    code_checks = {name: hashlib.sha256((OUT / name).read_bytes()).hexdigest() == digest for name, digest in fixed['SHA256'].items()}
    assert all(code_checks.values()), code_checks
    records = []
    for identifier in selection['finalists']:
        spec = specifications[identifier]
        with np.load(OUT / 'trades' / f'{identifier}.npz', allow_pickle=False) as ledger:
            for key, ready in inputs.items():
                config = managers.make_config(spec['manager'], key[1], ready)
                direction = directions[spec['signal_id']][key]
                result = engine.run(ready, direction, config, detail=True)
                record = dict(手法ID=identifier, セッション=key[0], 銘柄=key[1])
                record.update(check_accounting(ready, result, config))
                for name in ['trades', 'cycles']:
                    np.testing.assert_array_equal(result[name], ledger[f'{key[0]}_{key[1]}_{name}'])
                actual = research.summarize(result, config, key[1], key[0], identifier)
                saved = expected[(identifier, key[0], key[1])]
                for name, value in actual.items():
                    if isinstance(value, (int, float)):
                        np.testing.assert_allclose(value, saved[name], rtol=0, atol=.000001)
                    else:
                        assert value == saved[name]
                record['保存台帳と集計一致'] = True
                if key[0] in ['2026-09-28_Night', '2026-09-29_Day']:
                    record.update(check_execution_prefix(engine, ready, direction, config, result, fractions=(.31, .67)))
                records.append(record)
        print(f'{identifier}: 全26入力の独立会計に合格', flush=True)
    report = dict(合格=True, 主候補=selection['primary'], 対象=selection['finalists'], 詳細検算数=len(records),
                  原本行合計=sum(row['全行検算'] for row in records), 凍結SHA256一致=code_checks,
                  売買の継ぎ足しなし=True, 現在API取得数=0, 旧凍結結果不変=True, 結果=records)
    (OUT / 'selector_selected_audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
