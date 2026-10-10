"""当日保存足と原本価格の少数不一致を、時刻・価格差・利用時刻まで記録する。"""

from __future__ import annotations

import json
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd

from audit_day28 import module

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]


def main() -> None:
    """機能: 原本からOHLCを再集計し、保存足との差を当日の最初の新規時刻と比較する。

    引数: なし。返り値: なし (None)。検証入力や原本を書き換えない。
    """
    bundle = pickle.loads((OUT / '再生台帳.pkl').read_bytes())
    results, replacements = [], {}
    for symbol in ['NK225', 'TOPIX']:
        rows = []
        with (ROOT / 'book' / symbol / '2026-09-28_Day.jsonl').open('rb') as source:
            for line in source:
                item = json.loads(line)
                if item.get('CurrentPriceTime') and item.get('CurrentPrice'):
                    rows.append((item['CurrentPriceTime'], item['CurrentPrice']))
        raw = pd.DataFrame(rows, columns=['time', 'price'])
        raw.index = pd.to_datetime(raw.time)
        ready = bundle['inputs'][('2026-09-28_Day', symbol)]
        en = int(bundle['blocks'][('V0800', symbol, 1)]['trades'][0, 6])
        entry_time = ready['time_s'][en]
        for interval in [1, 5]:
            saved = pd.read_csv(ROOT / f'candle_{interval}min' / symbol / '2026-09-28_Day.csv')
            saved.index = pd.to_datetime(saved.time)
            derived = raw.price.resample(f'{interval}min').ohlc().dropna()
            common = saved.index.intersection(derived.index)
            rebuilt = saved.copy()
            rebuilt.loc[common, ['open', 'high', 'low', 'close']] = derived.loc[common, ['open', 'high', 'low', 'close']]
            replacements[(symbol, interval)] = rebuilt.reset_index(drop=True)
            for stamp in common:
                a, b = saved.loc[stamp], derived.loc[stamp]
                differences = {field: dict(保存値=float(a[field]), 原本再集計=float(b[field]), 保存値と原本の差=float(a[field]-b[field]))
                               for field in ['open', 'high', 'low', 'close'] if not np.isclose(a[field], b[field], rtol=0, atol=1e-8)}
                if differences:
                    available = stamp.timestamp() + (interval + 1) * 60
                    results.append(dict(銘柄=symbol, 分足=interval, 足開始時刻=stamp.isoformat(), 差=differences,
                                        指標利用可能時刻=pd.Timestamp(available, unit='s', tz='Asia/Tokyo').isoformat(),
                                        主候補の初回新規より前に利用可能=bool(available <= entry_time)))
    # ----------------------------------------
    # メモリ内の再集計足だけを置換し、凍結済み条件の結果への影響を調べる。
    sys.path.insert(0, str(ROOT / 'work/wave_v19'))
    import engine
    signals = module(ROOT / 'work/wave_v17/signals.py', 'day28_bar_sensitivity_original')
    variants = module(ROOT / 'work/wave_v19/signal_variants.py', 'day28_bar_sensitivity_variants')
    fixed = json.loads((ROOT / 'work/wave_v19/主候補の条件.json').read_text(encoding='utf-8'))
    inputs = {}
    for key, original in bundle['inputs'].items():
        symbol = key[1]
        ready = dict(original)
        bars = replacements[(symbol, 5)]
        bars = bars.loc[bars.closed.astype(str).str.lower().eq('true')]
        times = pd.to_datetime(bars.time).dt.as_unit('ns').astype('int64').to_numpy(float) / 1e9 + 360.
        true_range = pd.concat([bars.high - bars.low, (bars.high - bars.close.shift()).abs(),
                                (bars.low - bars.close.shift()).abs()], axis=1).max(axis=1)
        atr = true_range.ewm(alpha=1/12, adjust=False, min_periods=3).mean().clip(lower=2 * ready['tick']).to_numpy()
        positions = np.searchsorted(times, ready['time_s'], side='right') - 1
        ready['atr'] = np.full(len(positions), np.nan)
        valid = positions >= 0
        ready['atr'][valid] = atr[positions[valid]]
        inputs[key] = ready
    original_read = pd.read_csv

    def changed_read(path, *args, **kwargs):
        """機能: 対象の足読込だけを原本OHLC再集計値に一時置換する。

        引数: path (Path|str)、args/kwargs (tuple/dict)。返り値: 足または元の読込結果 (DataFrame)。
        """
        path = Path(path)
        if path.name == '2026-09-28_Day.csv' and path.parent.name in ['NK225', 'TOPIX'] and path.parent.parent.name in ['candle_1min', 'candle_5min']:
            interval = 1 if path.parent.parent.name == 'candle_1min' else 5
            return replacements[(path.parent.name, interval)].copy()
        return original_read(path, *args, **kwargs)

    pd.read_csv = changed_read
    sensitivity = []
    try:
        states = {}
        for key, ready in inputs.items():
            peer = inputs[(key[0], 'TOPIX' if key[1] == 'NK225' else 'NK225')]
            features = original_read(OUT / 'features' / f'{key[1]}_{key[0]}.csv')
            states[key] = signals.build_states(ready, peer, features=features)
        directions = variants.build_one(fixed['信号条件'], inputs, states)
        for key, ready in inputs.items():
            original = bundle['blocks'][('V0800', key[1], 1)]
            replay = engine.run(ready, directions[key], original['config'])
            multiplier = 10 if key[1] == 'NK225' else 1000
            differences = np.count_nonzero(directions[key] != bundle['directions'][key])
            routes_equal = replay['trades'].shape == original['trades'].shape and np.allclose(replay['trades'], original['trades'], rtol=0, atol=1e-8)
            sensitivity.append(dict(銘柄=key[1], 保存足版収支=float(original['stats'][0] * multiplier),
                                    原本再集計足版収支=float(replay['stats'][0] * multiplier),
                                    売買経路全一致=bool(routes_equal), 信号方向が異なる行数=int(differences),
                                    保存足固定ATR=original['cycles'][:, 5].tolist(), 原本再集計固定ATR=replay['cycles'][:, 5].tolist(),
                                    条件選び直し=False))
    finally:
        pd.read_csv = original_read
    result = dict(不一致=results, 原本変更=False, 保存足変更=False, 主結果は従来通り保存足指標=True,
                  OHLC再集計の補助検証=sensitivity, 補助検証で条件変更なし=True)
    (OUT / 'audit_bars.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
