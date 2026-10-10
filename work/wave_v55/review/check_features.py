"""単純な確定足特徴を原本気配から別計算し、ATR 非依存を検証する。"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(TASK))
from features import load_inputs_only, build_features, clean_input, INPUT_KEYS
from signals import decisions, methods


def same(a: object, b: object, tolerance: float = 1e-7) -> None:
    """機能: 独立計算との一致を欠測も含めて検査する。

    引数: a/b(object)、tolerance(float)。返り値: なし(None)。
    """
    np.testing.assert_allclose(a, b, rtol=0, atol=tolerance, equal_nan=True)


def audit_frame(ready: dict, quote: dict, frame: pd.DataFrame) -> int:
    """機能: 各足と過去20分、EMA、準備判定を原本から別の手順で検算する。

    引数: ready/quote(dict)、frame(DataFrame)。返り値: 照合行数(int)。
    """
    t, seq, mid = ready['time_s'], ready['seq'], quote['mid']
    starts, highs, lows, closes = [], [], [], []
    ema8 = ema21 = None
    for i, row in enumerate(frame.to_dict('records')):
        begin = np.searchsorted(t, row['bar_start'], side='left')
        end = np.searchsorted(t, row['bar_start']+60., side='left')
        assert end < len(t) and begin < end
        assert row['ready_index'] == end and row['seq'] == seq[end] and row['time_s'] == t[end]
        assert row['source_last_seq'] == seq[end-1] and row['source_last_time'] == t[end-1]
        assert row['source_count'] == end-begin and row['source_last_seq'] < row['seq']
        o, h, l, c = mid[begin], max(mid[begin:end]), min(mid[begin:end]), mid[end-1]
        same([row[x] for x in ['open', 'high', 'low', 'close']], [o,h,l,c])
        same(row['session_open'], ready['last'][0])
        same([row[x] for x in ['bid','ask','mid','last']], [quote['bid'][end],quote['ask'][end],mid[end],ready['last'][end]])
        starts.append(row['bar_start']); highs.append(h); lows.append(l); closes.append(c)
        ema8 = c if ema8 is None else (2./9.)*c+(7./9.)*ema8
        ema21 = c if ema21 is None else (2./22.)*c+(20./22.)*ema21
        same([row['ema8'], row['ema21']], [ema8,ema21])
        continuous = i>=19 and all(starts[j]-starts[j-1]==60. for j in range(i-18,i+1))
        prior = i>=20 and all(starts[j]-starts[j-1]==60. for j in range(i-19,i+1))
        same(row['mean20'], float(np.mean(closes[-20:])) if continuous else np.nan)
        same(row['std20'], float(np.std(closes[-20:], ddof=0)) if continuous else np.nan, 1e-6)
        same(row['prior20_high'], max(highs[-21:-1]) if prior else np.nan)
        same(row['prior20_low'], min(lows[-21:-1]) if prior else np.nan)
        assert row['can_trade'] == (t[end]-ready['start']>=1200. and continuous and 0.<=t[end]-row['bar_start']-60.<=60.)
    return len(frame)


def main() -> None:
    """機能: 全特徴と全条件の銘柄交換・未来切断・ATR 毒入れを検査する。

    引数: なし。返り値: なし(None)。新しい売買損益は開かない。
    """
    inputs = load_inputs_only()
    quotes = pickle.loads((ROOT/'work/wave_v52/measurement/quotes.pkl').read_bytes())
    frames = pickle.loads((TASK/'特徴.pkl').read_bytes())
    assert set(inputs) == set(quotes) == set(frames)
    feature_rows = signal_sets = prefix_tests = poisoned_tests = 0
    for key in sorted(inputs):
        ready, frame, quote = inputs[key], frames[key], quotes[key]
        assert set(ready) == set(INPUT_KEYS)
        feature_rows += audit_frame(ready, quote, frame)
        poison = dict(ready, atr=np.full(len(ready['last']), 1e100), can_trade=np.zeros(len(ready['last']),bool),
                      families={'未来成績':99999}, entry_atr=np.nan)
        pd.testing.assert_frame_equal(build_features(poison, quote), frame, check_exact=True)
        poisoned_tests += 1
        for method in methods():
            args = method['family'], method['width'], ready['tick']
            original = decisions(frame, *args)
            changed = frame.assign(symbol='交換後', atr=np.nan, atr5=1e100, entry_atr=-999.)
            np.testing.assert_array_equal(decisions(changed, *args), original)
            scaled = frame.copy()
            for col in ['close','session_open','mean20','std20','prior20_high','prior20_low','ema8','ema21']:
                scaled[col] *= 4.
            result = decisions(scaled, args[0], args[1], args[2]*4.)
            np.testing.assert_array_equal(result[:,:2], original[:,:2])
            same(result[:,2], original[:,2]*4.)
            signal_sets += 1
            for ratio in (.35,.75):
                cut = max(1,int(len(frame)*ratio))
                expected = original[original[:,0] <= frame.iloc[cut-1]['ready_index']]
                short = frame.iloc[:cut].copy()
                np.testing.assert_array_equal(decisions(short,*args), expected)
                altered = frame.copy()
                future = altered.index[cut:]
                for col in ['close','session_open','mean20','std20','prior20_high','prior20_low','ema8','ema21']:
                    altered.loc[future,col] *= 1.7
                actual = decisions(altered,*args)
                np.testing.assert_array_equal(actual[actual[:,0]<=frame.iloc[cut-1]['ready_index']], expected)
                prefix_tests += 2
    # ----------------------------------------
    # 実行する計算ソースに ATR という変数・属性名を残していないことも別途確認する。
    identifiers = {}
    for name in ('features.py','signals.py','engine.py'):
        tree = ast.parse((TASK/name).read_text(encoding='utf-8'))
        names = [node.id for node in ast.walk(tree) if isinstance(node,ast.Name)]
        names += [node.attr for node in ast.walk(tree) if isinstance(node,ast.Attribute)]
        identifiers[name] = sorted(set(n for n in names if 'atr' in n.lower()))
        assert not identifiers[name], identifiers[name]
    result = dict(合格=True, 口座数=len(inputs), 原本から独立再計算した特徴行数=feature_rows,
                  銘柄交換と価格倍率の比較条件口座数=signal_sets, 入口途中切断と未来改変比較数=prefix_tests,
                  入力ATR毒入れの特徴完全一致数=poisoned_tests, 計算変数のATR残存=identifiers,
                  コードSHA256={name:hashlib.sha256((TASK/name).read_bytes()).hexdigest()
                                for name in ['features.py','signals.py','engine.py']})
    (HERE/'特徴と入口の独立監査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
