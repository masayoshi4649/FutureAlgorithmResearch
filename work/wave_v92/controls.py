"""新しい部品を無効にした9対照で、旧執行と全31場の完全一致を確認する。"""

import hashlib
from pathlib import Path

import numpy as np

import catalog
import data
import research
import strategy

HERE = Path(__file__).resolve().parent


def main() -> None:
    """
    機能: 既存6条件と3つの部品なし対照を旧執行器へ接続して照合する。
    引数: なし。
    返り値: None。9条件558口座の全注文・全有効行を比較する。
    """
    material = data.load_inputs()
    ids = ('J10', 'J8', 'O10', 'O2', 'M82', 'O10_TR', 'A_O', 'O10_F10_TR', 'O10_F15_TR')
    configs = {config['id']: config for config in catalog.catalog()}
    checks = []
    for ident in ids:
        config = configs[ident]
        prepared = strategy.prepare(material, config)
        previous = strategy.LEGACY91.prepare(material, config)
        for key in sorted(prepared):
            output = strategy.play(config, key, prepared)
            old = strategy.LEGACY91.play(config, key, previous)
            for name in ('orders', 'trades', 'events', 'stats', 'slots', 'curve', 'source_curve', 'target_trace'):
                np.testing.assert_array_equal(output[name], old[name])
            checks.append(dict(id=ident, session=key[0], symbol=key[1], 行数=len(output['curve'])))
        print(ident + ' 全31場の旧執行と完全一致', flush=True)
    paths = [Path(__file__), HERE / 'catalog.py', HERE / 'engine.py', HERE / 'strategy.py']
    research.save(HERE / 'audit/九対照の全31注文と全有効行の完全一致.json',
                  dict(全合格=True, 条件数=9, 口座数=len(checks), 各口座=checks,
                       新規部品なしの対照だけ=True, 全31既知=True, API取得=0, 実注文=0,
                       SHA256={str(path.relative_to(research.ROOT)): data.digest(path) for path in paths}))
    assert len(checks) == 558


if __name__ == '__main__':
    main()
