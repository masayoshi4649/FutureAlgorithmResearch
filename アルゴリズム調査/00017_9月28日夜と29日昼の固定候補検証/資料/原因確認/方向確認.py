"""保存済み入力を使い、９月29日デイのM3逆が選んだ方向を確認する。"""

from __future__ import annotations

from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SESSION = '2026-09-29_Day'
JST = ZoneInfo('Asia/Tokyo')
sys.dont_write_bytecode = True


def module(path: Path, name: str):
    """機能: 既存コードを変更せず読み込む。

    引数: path (Path)、name (str)。返り値: 読み込んだモジュール (module)。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def stamp(value: float) -> str:
    """機能: 秒単位時刻を日本時間表示にする。

    引数: value (float)。返り値: 日本時間文字列 (str)。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat()


def changes(times: np.ndarray, values: np.ndarray) -> list[dict]:
    """機能: 状態の変化時刻だけを抽出する。

    引数: times/values (ndarray)。返り値: 時刻と状態の一覧 (list[dict])。
    """
    indices = np.flatnonzero(np.r_[True, values[1:] != values[:-1]])
    return [dict(時刻=stamp(times[i]), 状態=int(values[i])) for i in indices]


def main() -> None:
    """機能: 固定済みM3逆の方向、EMA根拠、転換時刻を保存する。

    引数: なし。返り値: なし (None)。原本と継続損益台帳は変更しない。
    """
    reference = module(ROOT / 'work/wave_v16/reference.py', 'reason_reference_v22')
    reference.previous.OUT = OUT
    signals = module(ROOT / 'work/wave_v17/signals.py', 'reason_signals_v22')
    variants = module(ROOT / 'work/wave_v19/signal_variants.py', 'reason_variants_v22')
    feature_root = ROOT / 'work/wave_v21' / SESSION / 'features'
    inputs = reference.previous.build_inputs([SESSION], allow_holdout=True, roots={SESSION: (ROOT, feature_root)})
    fixed = json.loads((ROOT / 'M3_逆_A00_360分版/固定条件.json').read_text(encoding='utf-8'))
    states = {}
    for key, ready in inputs.items():
        feature = pd.read_csv(feature_root / f'{key[1]}_{SESSION}.csv')
        peer = inputs[(SESSION, 'TOPIX' if key[1] == 'NK225' else 'NK225')]
        states[key] = signals.build_states(ready, peer, features=feature)
    directions = variants.build_one(fixed['信号条件'], inputs, states)
    models = {key: signals.minute_model(ready) for key, ready in inputs.items()}
    trades = json.loads((ROOT / 'work/wave_v21' / SESSION / '再生記録.json').read_text(encoding='utf-8'))['trades']
    result = dict(対象=SESSION, 条件変更=False, 原本変更=False, API取得数=0, 銘柄別={})
    for key, ready in inputs.items():
        symbol = key[1]
        own = models[key]
        peer = models[(SESSION, 'TOPIX' if symbol == 'NK225' else 'NK225')]
        rows = signals.minute_checks(ready)
        times = ready['time_s'][rows]
        own_values = signals.expand_states(own['time_s'], own['states'], times)
        peer_values = signals.expand_states(peer['time_s'] + 60., peer['states'], times)
        agreement = np.where((own_values == peer_values) & (own_values != 0), own_values, 0).astype(np.int8)
        # ----------------------------------------
        # 固定した新規受付・返済時刻と、実際の約定時刻の根拠を抜き出す。
        targets = ['09:23:00', '09:30:00', '14:37:00', '14:43:00', '15:05:00', '15:25:00', '15:35:00']
        targets += [row[field][11:19] for row in trades if row['symbol'] == symbol for field in ('entry_time', 'exit_time')]
        samples = []
        for clock in sorted(set(targets)):
            requested = datetime.fromisoformat(f'2026-09-29T{clock}+09:00').timestamp()
            i = min(int(np.searchsorted(ready['time_s'], requested, side='left')), len(ready['seq']) - 1)
            j = int(np.searchsorted(own['time_s'], ready['time_s'][i], side='right')) - 1
            pj = int(np.searchsorted(peer['time_s'] + 60., ready['time_s'][i], side='right')) - 1
            cj = int(np.searchsorted(times, ready['time_s'][i], side='right')) - 1
            samples.append(dict(要求時刻=clock, 観測時刻=stamp(ready['time_s'][i]),
                価格=float(ready['last'][i]), 自M1=int(own['states'][j]), 自M1候補=int(own['candidates'][j]),
                自EMA間隔ATR=float(own['gap'][j]), 自EMA傾きATR=float(own['slope'][j]),
                自足公開時刻=stamp(own['time_s'][j]), 相手M1追加遅延後=int(peer['states'][pj]),
                相手足公開追加遅延時刻=stamp(peer['time_s'][pj] + 60.),
                直近毎分確認時刻=stamp(times[cj]), 直近両銘柄一致=int(agreement[cj]),
                M3=int(states[key]['M3'][i]), 新規売買方向=int(directions[key][i])))
        minute_rows = []
        for j, t in enumerate(own['time_s']):
            minute_rows.append(dict(時刻=stamp(t), 候補=int(own['candidates'][j]), 主方向=int(own['states'][j]),
                EMA間隔ATR=None if not np.isfinite(own['gap'][j]) else float(own['gap'][j]),
                EMA傾きATR=None if not np.isfinite(own['slope'][j]) else float(own['slope'][j])))
        result['銘柄別'][symbol] = dict(M1変化=changes(own['time_s'], own['states']),
            M1候補変化=changes(own['time_s'], own['candidates']), 両銘柄一致変化=changes(times, agreement),
            M3変化=changes(ready['time_s'], states[key]['M3']), 売買方向変化=changes(ready['time_s'], directions[key]),
            注目時点=samples, M1毎分=minute_rows)
    (OUT / '方向の原因.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({symbol: {name: value for name, value in data.items() if name != 'M1毎分'}
        for symbol, data in result['銘柄別'].items()}, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
