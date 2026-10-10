"""原本キャッシュの先頭行と旧 ATR 欠測行の保持を独立に確認する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCES = [
    'work/wave_v47/inputs.pkl',
    'work/wave_v48/update_20260930/new_inputs.pkl',
    'work/wave_v48/update_20261001/new_inputs.pkl',
    'work/wave_v50/update_20261001_day/new_inputs.pkl',
    'work/wave_v50/update_20261002_two/new_inputs.pkl',
    'work/wave_v50/update_20261007_added/new_inputs.pkl',
]


def main() -> None:
    """機能: 各入力の先頭時刻と ATR 欠測行の存在を記録する。

    引数: なし。返り値: なし(None)。旧キャッシュを読取専用で開く。
    """
    rows = []
    seen = set()
    for source in SOURCES:
        path = ROOT / source
        with path.open('rb') as handle:
            data = pickle.load(handle)
        for key, ready in sorted(data.items()):
            assert key not in seen, key
            seen.add(key)
            time = np.asarray(ready['time_s'], float)
            seq = np.asarray(ready['seq'])
            atr = np.asarray(ready['atr'], float)
            assert len(time) == len(seq) == len(atr)
            eligible = np.flatnonzero(time >= ready['start'])
            assert len(eligible), key
            first = int(eligible[0])
            rows.append(dict(
                セッション=key[0], 銘柄=key[1], 入力=source, 行数=len(seq),
                場開始秒=float(ready['start']), 最初の場内観測秒=float(time[first]),
                最初の場内観測の遅延秒=float(time[first]-ready['start']),
                最初の場内行番号=int(seq[first]),
                ATR欠測のまま保持された行数=int(np.count_nonzero(~np.isfinite(atr))),
                最初の場内行のATR欠測=bool(not np.isfinite(atr[first])),
            ))
        del data
    assert len(rows) == 46, len(rows)
    lineage = [
        'work/wave_v8/raw_features.py',
        'work/wave_v10/signals.py',
        'work/wave_v13/exact_engine.py',
    ]
    report = dict(
        判定='合格', 口座数=len(rows),
        行選択の説明='v8有効最良板の全行を保存、v10でATRを後付け、v13では行を削らずコピー。旧コードは実行せず静的確認。',
        源コードSHA256={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in lineage},
        寄付の限定='実際の場開始価格ではなく場内最初の有効観測価格。遅延秒を明示する。',
        ATR欠測のまま保持された全行数=sum(row['ATR欠測のまま保持された行数'] for row in rows),
        全口座=rows,
    )
    target = HERE / '入力系列の独立監査.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key:report[key] for key in ['判定','口座数','ATR欠測のまま保持された全行数']}, ensure_ascii=False))
    print(json.dumps(dict(開始遅延の最大秒=max(row['最初の場内観測の遅延秒'] for row in rows),
                         遅延60秒超=[row for row in rows if row['最初の場内観測の遅延秒']>60]), ensure_ascii=False))


if __name__ == '__main__':
    main()
