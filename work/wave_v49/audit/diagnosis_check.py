"""原因説明のEMAと両市場方向をCSVから別式で確認する。"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import pickle

import numpy as np

from independent_audit import ROOT, read, same, save, sha


SESSION = '2026-09-30_Night'
JST = timezone(timedelta(hours=9))


def model(ready: dict) -> dict:
    """機能: 確定足を標準CSV読取と逐次EMAから独立計算する。

    引数: ready (dict) は時刻・ATR入力。返り値: 各足の公開指標 (dict)。
    """
    path = ROOT / 'candle_1min' / ready['symbol'] / (ready['session'] + '.csv')
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = [row for row in csv.DictReader(stream) if row['closed'].lower() == 'true']
    result = dict(time_s=[], close=[], gap=[], slope=[], fast_slope=[], direction=[], atr=[])
    fast = slow = None
    slow_history, fast_history = [], []
    state = 0
    for row in rows:
        stamp = datetime.fromisoformat(row['time']).timestamp() + 120
        if not ready['start'] + 120 <= stamp <= ready['time_s'][-1]:
            continue
        close = float(row['close'])
        index = np.searchsorted(ready['time_s'], stamp, side='right') - 1
        atr = ready['atr'][index] if index >= 0 else np.nan
        fast = close if fast is None else fast + (close - fast) * (2 / 16)
        slow = close if slow is None else slow + (close - slow) * (2 / 61)
        slow_history.append(slow)
        fast_history.append(fast)
        count = len(slow_history)
        gap = (fast - slow) / atr if count >= 60 else np.nan
        slope = (slow - slow_history[-4]) / atr if count >= 63 else np.nan
        fast_slope = (fast - fast_history[-4]) / atr if count >= 18 else np.nan
        if not np.isfinite(gap):
            state = 0
        elif state and state * gap < 0:
            state = 0
        arm = 1 if gap > .15 and slope > .02 else -1 if gap < -.15 and slope < -.02 else 0
        if arm:
            state = arm
        for name, value in (('time_s', stamp), ('close', close), ('gap', gap),
                            ('slope', slope), ('fast_slope', fast_slope), ('direction', state), ('atr', atr)):
            result[name].append(value)
    return {key: np.asarray(value) for key, value in result.items()}


def check() -> dict:
    """機能: 全18組の準備・更新・直前・約定の説明値を照合する。

    引数: なし。返り値: 216市場時点の独立一致証跡 (dict)。
    """
    path = ROOT / 'work/wave_v49/diagnosis/原因の証拠.json'
    data = read(path)
    inputs = pickle.loads((ROOT / 'work/wave_v48/update_20261001/new_inputs.pkl').read_bytes())
    models = {symbol: model(ready) for (_, symbol), ready in inputs.items()}
    checked = 0
    for campaign in data['調査対象組']:
        symbol = campaign['銘柄']
        peer = 'TOPIX' if symbol == 'NK225' else 'NK225'
        direction = 1 if campaign['方向'] == '買い' else -1
        for event in campaign['エントリー状況'].values():
            stamp = datetime.strptime(event['時刻'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=JST).timestamp()
            ready = inputs[SESSION, symbol]
            same(ready['time_s'][event['原本行']], stamp, '観測時刻')
            assert event['共通入口方向'] == direction
            for name, selected, delay in (('自銘柄', symbol, 0), ('相手銘柄', peer, 60),
                                         ('相手追加遅延なし参考', peer, 0)):
                saved = event[name]
                m = models[selected]
                index = np.searchsorted(m['time_s'] + delay, stamp, side='right') - 1
                assert index >= 0 and m['time_s'][index] + delay <= stamp
                for field, item in (('EMA間隔ATR比', 'gap'), ('長期EMA直近3本傾きATR比', 'slope'),
                                    ('ATR', 'atr'), ('終値', 'close'), ('主方向', 'direction')):
                    same(saved[field], m[item][index], field)
                arm = 1 if m['gap'][index] > .15 and m['slope'][index] > .02 else -1 if m['gap'][index] < -.15 and m['slope'][index] < -.02 else 0
                assert arm == saved['現在新規主方向条件']
                for window in (5, 15, 30):
                    old = np.searchsorted(m['time_s'], m['time_s'][index] - window * 60, side='right') - 1
                    assert old >= 0
                    change = m['close'][index] - m['close'][old]
                    same(change, saved[f'直近{window}分変化'], '実時間価格変化')
                checked += 1
            assert event['自銘柄']['主方向'] == event['相手銘柄']['主方向'] == direction
    assert checked == 216
    result = dict(全合格=True, 確認市場時点数=checked, 主方向全一致=True,
                  EMA逐次別式一致=True, 実時間窓と説明価格変化一致=True,
                  参照資料SHA256=sha(path), 注意='両市場の現在価格変化は逆向きでも、保持中のEMA方向は同じになり得る。')
    save('原因数値の独立確認.json', result)
    return result


if __name__ == '__main__':
    print(check())
