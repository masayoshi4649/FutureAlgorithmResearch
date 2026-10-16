"""追加Dayを再生せず、旧30場の六つの対照だけ完全一致を確認する。"""

import hashlib
from pathlib import Path

import numpy as np

import catalog
import data
import research
import strategy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main() -> None:
    """
    機能: 既知の六対照を旧30口座台帳へ接続し、約定と全行会計を比較する。
    引数: なし。
    返り値: None。新Dayの価格素材は読めても、執行又は損益集計しない。
    """
    material = data.load_inputs()
    names = {'J10': 'J10_Q', 'J8': 'J8_Q', 'O10': 'O10_Q', 'O2': 'O2_Q',
             'M82': 'M82_Q', 'B_QA': 'D_C_QA'}
    configs = {c['id']: c for c in catalog.catalog()}
    proofs, dependencies = [], []
    for ident, previous in names.items():
        path = ROOT/'work/wave_v90/round2/ledgers'/f'{previous}.pkl'
        old = research.read(path)
        prepared = strategy.prepare(material, configs[ident])
        for key in sorted(old):
            assert key[0] != material['metadata']['sessions'][-1]
            output = strategy.play(configs[ident], key, prepared)
            for field in ('orders', 'trades', 'events', 'stats', 'slots'):
                np.testing.assert_array_equal(output[field], old[key][field])
            for field in ('curve', 'source_curve', 'target_trace'):
                assert hashlib.sha256(output[field].tobytes()).hexdigest() == old[key][field+'_SHA256']
            proofs.append(dict(id=ident, session=key[0], symbol=key[1], 行数=len(output['curve'])))
        dependencies.append(path)
    research.save(HERE/'audit/六対照の旧30全注文と全有効行の完全一致.json',
                  dict(全合格=True, 口座数=len(proofs), 条件数=6, 旧30だけ再生=True,
                       新Day執行=0, 新Day損益閲覧=0, 各口座=proofs,
                       SHA256={str(p.relative_to(ROOT)): data.digest(p) for p in
                         [Path(__file__), HERE/'engine.py', HERE/'strategy.py', *dependencies]}))
    print('六対照・360旧口座の注文/親/全行時価が完全一致。追加Day執行0。', flush=True)


if __name__ == '__main__':
    main()
