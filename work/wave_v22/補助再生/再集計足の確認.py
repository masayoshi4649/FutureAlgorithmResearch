"""生板から再集計した足をメモリ内だけに差し替え、固定候補の結果差を確認する。"""

from __future__ import annotations

from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import numba
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SESSIONS = ['2026-09-28_Night', '2026-09-29_Day']
JST = ZoneInfo('Asia/Tokyo')
sys.dont_write_bytecode = True
numba.config.CACHE_DIR = str(OUT / 'numba_cache')


def module(path: Path, name: str):
    """機能: 既存コードを変更せず固有名で読み込む。

    引数: path (Path): ソース。name (str): 固有モジュール名。
    返り値: module: 読み込んだコード。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


def trade_rows(result: dict, ready: dict, symbol: str) -> list[dict]:
    """機能: 取引経路を日時と価格の比較可能な明細にする。

    引数: result (dict): 再生結果。ready (dict): 入力。symbol (str): 銘柄。
    返り値: list[dict]: 注文方向・数量・入口・出口・理由・収支。
    """
    multiplier = 1000 if symbol == 'TOPIX' else 10
    rows = []
    for trade in result['trades']:
        rows.append(dict(売買='買い' if trade[2] > 0 else '売り', 枚数=int(trade[3]),
                         新規時刻=datetime.fromtimestamp(ready['time_s'][int(trade[6])], JST).isoformat(),
                         返済時刻=datetime.fromtimestamp(ready['time_s'][int(trade[7])], JST).isoformat(),
                         新規価格=float(trade[4]), 返済価格=float(trade[5]),
                         理由コード=int(trade[9]), 収支=float(trade[10] * multiplier)))
    return rows


def main() -> None:
    """機能: 足価格だけを差し替えた補助再生を行い、既存の保存足版と比較する。

    引数: なし。
    返り値: None。新規作業フォルダへ補助確認JSONを保存する。
    """
    reference = module(ROOT / 'work/wave_v16/reference.py', 'sensitivity_reference_v22')
    reference.previous.OUT = OUT
    numba.config.CACHE_DIR = str(OUT / 'numba_cache')
    signals = module(ROOT / 'work/wave_v17/signals.py', 'sensitivity_signals_v22')
    variants = module(ROOT / 'work/wave_v19/signal_variants.py', 'sensitivity_variants_v22')
    engine = module(ROOT / 'work/wave_v19/engine.py', 'sensitivity_engine_v22')
    fixed = json.loads((ROOT / 'M3_逆_A00_360分版/固定条件.json').read_text(encoding='utf-8'))
    original_read = pd.read_csv
    sensitivity = []
    for session in SESSIONS:
        print(session, '補助再生開始', flush=True)
        feature_root = ROOT / 'work/wave_v21' / session / 'features'
        original_inputs = reference.previous.build_inputs([session], allow_holdout=True,
                                                          roots={session: (ROOT, feature_root)})
        features = {symbol: original_read(feature_root / f'{symbol}_{session}.csv') for symbol in ('TOPIX', 'NK225')}
        original_states = {key: signals.build_states(ready, original_inputs[(session, 'NK225' if key[1] == 'TOPIX' else 'TOPIX')], features=features[key[1]])
                           for key, ready in original_inputs.items()}
        original_directions = variants.build_one(fixed['信号条件'], original_inputs, original_states)
        originals = {key: engine.run(ready, original_directions[key], fixed['一枚でのエンジン設定'], detail=True)
                     for key, ready in original_inputs.items()}
        persisted = json.loads((ROOT / 'work/wave_v21' / session / '再生記録.json').read_text(encoding='utf-8'))
        for key, result in originals.items():
            rows = trade_rows(result, original_inputs[key], key[1])
            before = [row for row in persisted['trades'] if row['symbol'] == key[1]]
            assert len(rows) == len(before)
            for a, b in zip(rows, before):
                assert a['売買'] == b['side'] and a['枚数'] == b['quantity']
                assert a['新規時刻'] == b['entry_time'] and a['返済時刻'] == b['exit_time']
                assert a['新規価格'] == b['entry_price'] and a['返済価格'] == b['exit_price']
                assert a['収支'] == b['net_yen']
        # ----------------------------------------
        # 生板OHLCは保存足がある時刻に限定して置換し、未生成足を補完しない。
        replacements = {}
        changed_inputs = {}
        for key, ready in original_inputs.items():
            symbol = key[1]
            _, raw = reference.previous.data.scan_book(ROOT / 'book' / symbol / f'{session}.jsonl', collect_prices=True)
            series = pd.Series(raw['last'], index=pd.to_datetime(raw['stamps']))
            series = series.loc[series.index.notna() & series.notna()]
            for interval in (1, 5):
                saved = original_read(ROOT / f'candle_{interval}min' / symbol / f'{session}.csv')
                saved.index = pd.to_datetime(saved.time)
                rebuilt = series.resample(f'{interval}min').ohlc().dropna()
                common = saved.index.intersection(rebuilt.index)
                changed = saved.copy()
                changed.loc[common, ['open', 'high', 'low', 'close']] = rebuilt.loc[common, ['open', 'high', 'low', 'close']]
                replacements[(symbol, interval)] = changed.reset_index(drop=True)
            changed = dict(ready)
            bars = replacements[(symbol, 5)]
            bars = bars.loc[bars.closed.astype(str).str.lower().eq('true')]
            times = pd.to_datetime(bars.time).dt.as_unit('ns').astype('int64').to_numpy(float) / 1e9 + 360.
            true_range = pd.concat([bars.high - bars.low, (bars.high - bars.close.shift()).abs(),
                                    (bars.low - bars.close.shift()).abs()], axis=1).max(axis=1)
            atr = true_range.ewm(alpha=1/12, adjust=False, min_periods=3).mean().clip(lower=2 * ready['tick']).to_numpy()
            positions = np.searchsorted(times, ready['time_s'], side='right') - 1
            changed['atr'] = np.full(len(positions), np.nan)
            valid = positions >= 0
            changed['atr'][valid] = atr[positions[valid]]
            changed_inputs[key] = changed

        def changed_read(path, *args, **kwargs):
            """機能: 対象セッションの足読込だけをメモリ上の再集計値へ差し替える。

            引数: path (Path|str): 読込先。args (tuple)、kwargs (dict): 読込引数。
            返り値: DataFrame: 差し替え足または元の読込結果。
            """
            candidate = Path(path)
            if candidate.name == f'{session}.csv' and candidate.parent.name in ('NK225', 'TOPIX') and candidate.parent.parent.name in ('candle_1min', 'candle_5min'):
                interval = 1 if candidate.parent.parent.name == 'candle_1min' else 5
                return replacements[(candidate.parent.name, interval)].copy()
            return original_read(path, *args, **kwargs)

        pd.read_csv = changed_read
        try:
            changed_states = {key: signals.build_states(ready, changed_inputs[(session, 'NK225' if key[1] == 'TOPIX' else 'TOPIX')], features=features[key[1]])
                              for key, ready in changed_inputs.items()}
            changed_directions = variants.build_one(fixed['信号条件'], changed_inputs, changed_states)
            for key, ready in changed_inputs.items():
                symbol = key[1]
                alternate = engine.run(ready, changed_directions[key], fixed['一枚でのエンジン設定'], detail=True)
                before = trade_rows(originals[key], original_inputs[key], symbol)
                after = trade_rows(alternate, ready, symbol)
                diffs = np.flatnonzero(changed_directions[key] != original_directions[key])
                sensitivity.append(dict(セッション=session, 銘柄=symbol,
                    保存足版収支=sum(row['収支'] for row in before), 原本再集計足版収支=sum(row['収支'] for row in after),
                    売買経路全一致=before == after, 信号方向が異なる行数=len(diffs),
                    信号方向差異の最初=None if not len(diffs) else datetime.fromtimestamp(ready['time_s'][diffs[0]], JST).isoformat(),
                    信号方向差異の最後=None if not len(diffs) else datetime.fromtimestamp(ready['time_s'][diffs[-1]], JST).isoformat(),
                    保存足固定ATR=originals[key]['cycles'][:, 5].tolist(), 原本再集計固定ATR=alternate['cycles'][:, 5].tolist(),
                    保存足明細=before, 原本再集計明細=after, 原再生明細と保存足再生一致=True,
                    条件選び直し=False, 場末未返済枚数=float(alternate['stats'][9])))
        finally:
            pd.read_csv = original_read
        print(session, '補助再生完了', flush=True)
    result = dict(監査日時=datetime.now(JST).isoformat(), 原本変更=False, 保存足変更=False, 継続台帳変更=False,
                  主結果は従来通り保存足指標=True, 未生成足の補完=False, 条件変更なし=True, 行=sensitivity)
    (OUT.parent / '再集計足の補助確認.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps([{key: value for key, value in row.items() if '明細' not in key and 'ATR' not in key} for row in sensitivity], ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
