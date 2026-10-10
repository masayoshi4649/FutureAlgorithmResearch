"""ATR 不使用の入口と常時トレーリングを、手作り価格で独立検査する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
sys.path.insert(0, str(TASK))
from engine import execute
from signals import decisions, methods


def prices(values: list, times: list | None = None, limit: float = 10000.) -> dict:
    """機能: 判断行と約定行が分かる原本順の価格を作る。

    引数: values(list)、times(list|None)、limit(float)。返り値: 入力(dict)。
    """
    return dict(last=np.asarray(values, float),
                time_s=np.asarray(times if times is not None else range(len(values)), float),
                seq=np.arange(len(values), dtype=np.int64) + 100, limit=limit,
                start=0., session='合成', symbol='TOPIX', tick=.5)


def features(closes: list) -> pd.DataFrame:
    """機能: 入口だけを切り分ける確定足の表を作る。

    引数: closes(list)。返り値: 特徴表(DataFrame)。
    """
    return pd.DataFrame([dict(bar_start=1200.+i*60, ready_index=i, can_trade=True,
                              close=float(p), session_open=100., mean20=100., std20=1.,
                              prior20_high=101., prior20_low=99., ema8=101., ema21=100.,
                              symbol='TOPIX') for i, p in enumerate(closes)])


def main() -> None:
    """機能: 初回・交差・固定幅・次行約定・場内返済・未来不変を検査する。

    引数: なし。返り値: なし(None)。実成績は読み込まない。
    """
    checks = []
    assert len(methods()) == 20
    f = features([100.2, 100.3, 100., 99.8, 99.7, 100., 100.2])
    s = decisions(f, 'P01', 'W10', .01)
    np.testing.assert_array_equal(s[:, :2], [[0, 1], [3, -1], [6, 1]])
    checks.append('始値比率は初回既成立を一度認め、その後は外向き交差のみ')

    f = features([103., 103., 101., 103.])
    np.testing.assert_array_equal(decisions(f, 'P02', 'S1', .5)[:, :2], [[0, 1], [3, 1]])
    f = features([103., 101., 97., 99.])
    np.testing.assert_array_equal(decisions(f, 'P03', 'S1', .5)[:, :2], [[1, -1], [3, 1]])
    f = features([103., 97.])
    assert len(decisions(f, 'P03', 'S1', .5)) == 0
    checks.append('BB突破と帯内復帰を分離し、上下帯を一気に抜けた足は復帰としない')

    f = features([101., 101.1, 99., 98.9])
    np.testing.assert_array_equal(decisions(f, 'P04', 'W10', .01)[:, :2], [[1, 1], [3, -1]])
    f = features([100.]*5)
    f['ema8'] = [101., 102., 100., 99., 99.]
    np.testing.assert_array_equal(decisions(f, 'P05', 'S1', .5)[:, :2], [[0, 1], [3, -1]])
    checks.append('高安は厳密な越境、EMAは同値を挟む方向交差を判定')

    f = features([100., 100.2, 100.3])
    f.loc[0, 'can_trade'] = False
    np.testing.assert_array_equal(decisions(f, 'P01', 'W10', .01)[:, :2], [[1, 1]])
    f = features([100., 100.2]); f.loc[1, 'bar_start'] += 60
    assert len(decisions(f, 'P01', 'W10', .01)) == 0
    f = features([13000.]); f['session_open'] = 12345.
    assert decisions(f, 'P01', 'W05', .5)[0, 2] == 6.5
    f = features([103.]); f['std20'] = 0.
    assert decisions(f, 'P02', 'S1', .5)[0, 2] == 1.
    checks.append('初回準備時だけ状態参入し、幅は切上げ・2呼値下限、標準偏差ゼロも下限使用')

    f = features([100.2, 103., 101., 97., 99., 103.])
    for method in methods():
        expected = decisions(f, method['family'], method['width'], .5)
        poison = f.assign(atr=np.nan, atr5=1e100, entry_atr=-1., symbol='NK225')
        np.testing.assert_array_equal(decisions(poison, method['family'], method['width'], .5), expected)
        scaled = f.copy()
        for col in ['close', 'session_open', 'mean20', 'std20', 'prior20_high', 'prior20_low', 'ema8', 'ema21']:
            scaled[col] *= 4.
        result = decisions(scaled, method['family'], method['width'], 2.)
        np.testing.assert_array_equal(result[:, :2], expected[:, :2])
        np.testing.assert_allclose(result[:, 2], expected[:, 2]*4.)
    checks.append('全20条件の銘柄名交換・ATR毒入れで同一、価格と呼値4倍で幅だけ4倍')

    # ----------------------------------------
    # 注文器は入口規則から切り離した固定指示で検査する。
    signals = np.array([[0., 1., 2.]])
    ready = prices([100., 100., 101., 99., 98., 100.])
    a = execute(ready, signals, 5, 1000.)
    orders = np.asarray(a['orders'])
    assert len(orders) == 2 and orders[0, 3] == 101 and orders[1, 2] == 103 and orders[1, 3] == 104
    assert a['net'] == -10000. and a['width_groups'][0][7] == .5
    checks.append('1幅も進まない利益からでも常時追跡し、入口・出口は判断の次行で約定')
    reverse = dict(ready, last=200.-ready['last'], symbol='NK225')
    opposite = signals.copy(); opposite[:, 1] *= -1
    b = execute(reverse, opposite, 5, 1000.)
    assert b['net'] == a['net'] and b['width_groups'][0][7:] == a['width_groups'][0][7:]
    np.testing.assert_allclose(b['curve'], a['curve'])
    checks.append('売買と価格を鏡像にした損益・順行逆行・含み損益が一致')

    ready = prices([100., 100., 80., 79.])
    a = execute(ready, signals, 5, 1000.)
    assert a['net'] == -105000. and a['trades'][0][5] == 79.
    assert a['width_groups'][0][8] == 10.5
    ready = prices([100., 100., 101., 102., 101., 100., 99.])
    a = execute(ready, np.array([[0., 1., 2.], [2., -1., 2.]]), 5, 1000.)
    assert a['cycles'] == 1 and a['trades'][0][12] == 106
    checks.append('ギャップは固定線で約定したと装わず次価格で評価、反対信号だけでは返済しない')

    ready = prices([100.]*5, [0., 1., 10000., 20000., 30000.], limit=40000.)
    a = execute(ready, signals, 5, 1000., finish=False)
    assert len(a['orders']) == 1 and not a['trades']
    ready = prices([100., 100., 101., 102., 103.], [0., 1., 999., 1000., 1001.], limit=1000.)
    a = execute(ready, signals, 5, 1000.)
    assert a['orders'][1][2:4] == [103., 104.] and a['orders'][1][9] == 2
    ready = prices([100.]*3, [700., 701., 702.], limit=1000.)
    assert not execute(ready, signals, 5, 1000.)['orders']
    checks.append('場末以外の時間切れなし、終了時刻で次行返済、残り5分の新規なし')

    ready = prices([100., 100., 98., 97., 100., 100., 100., 98., 97.],
                   [0., 1., 2., 3., 62., 63., 64., 65., 66.])
    s = np.array([[0., 1., 2.], [4., 1., 2.], [5., 1., 2.]])
    a = execute(ready, s, 5, 1000.)
    assert a['cycles'] == 2 and a['orders'][2][2] == 105 and a['orders'][2][3] == 106
    checks.append('全返済後59秒は見送り、60秒ちょうどから新しい指示を受け付ける')

    for end in range(2, len(ready['last'])):
        truncated = {key:(value[:end] if isinstance(value, np.ndarray) else value) for key, value in ready.items()}
        prefix = execute(truncated, s[s[:, 0] < end], 5, 1000., finish=False)
        np.testing.assert_array_equal(prefix['orders'], [o for o in a['orders'] if o[3] < ready['seq'][end]])
        np.testing.assert_allclose(prefix['curve'], a['curve'][:end], atol=1e-6)
        np.testing.assert_allclose(prefix['w_curve'], a['w_curve'][:end], atol=1e-9)
        changed = dict(ready, last=ready['last'].copy(), atr=np.full(len(ready['last']), 1e99))
        changed['last'][end:] = 200.+np.arange(len(ready['last'])-end)
        mutated = execute(changed, s, 5, 1000., finish=False)
        np.testing.assert_array_equal(prefix['orders'], [o for o in mutated['orders'] if o[3] < ready['seq'][end]])
        np.testing.assert_allclose(prefix['curve'], mutated['curve'][:end], atol=1e-6)
        np.testing.assert_allclose(prefix['w_curve'], mutated['w_curve'][:end], atol=1e-9)
    checks.append('途中切断・将来価格改変・ATR毒入れ後も既知注文と金額/幅単位曲線が一致')

    try:
        execute(prices([100., 100.]), signals, 5, 1000.)
        raise AssertionError('未返済を通している')
    except ValueError as error:
        assert '場内返済' in str(error)
    checks.append('終了時に未返済玉が残る入力はエラーとして明示')
    result = dict(判定='合格', 検査数=len(checks), 検査=checks,
                  コードSHA256={name:hashlib.sha256((TASK/name).read_bytes()).hexdigest()
                                for name in ['engine.py','signals.py']})
    (HERE/'入口と常時追跡の合成監査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
