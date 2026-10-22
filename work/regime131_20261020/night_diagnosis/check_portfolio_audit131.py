"""旧核importなしで、合算監査の手計算例と不正保存値の検出を確認する。"""

import copy
from datetime import datetime
import json
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo

import numpy as np

from audit_portfolio131 import audit_one, independent_phases, PHASES, reference

HERE = Path(__file__).resolve().parent


def curve(equity, position, realized, held=False):
    """
    機能: 手計算した三列から表示用の下落幅を付ける。
    引数: equity/position/realized(list)、held(bool)は手計算資料。
    返り値: ndarrayは五列曲線。
    """
    eq = np.asarray(equity, dtype=float)
    dd = np.maximum.accumulate(np.maximum.accumulate(np.maximum(eq, 0.))-eq)
    mode = (np.abs(position) > 0).astype(float) if held else np.zeros(len(eq))
    return np.column_stack((eq, position, realized, dd, mode))


def fixture():
    """
    機能: 同じ行で旧買いと追加売りを建て、旧だけ部分返済する例を作る。
    引数: なし。
    返り値: tupleは監査へ渡す配列・入力・条件・集計・旧原注文。
    """
    start = datetime(2026, 9, 21, 8, 45, tzinfo=ZoneInfo("Asia/Tokyo")).timestamp()
    times = start+2700.+120*np.arange(14)
    bid = np.array([100., 100., 101., np.nan, 102., 103., 104., np.nan,
                    105., 106., 107., 108., 109., 110.])
    ready = dict(start=start, limit=times[12], time_s=times, atr=np.full(14, 4.),
                 symbol="TOPIX", session="2026-09-21_Day", tick=.5)
    quotes = dict(bid=bid, ask=bid+1., quote_valid=np.isfinite(bid))
    phase = independent_phases(ready)
    history = np.zeros((14, 15))
    history[:, [6, 7, 10, 11]] = -1.
    co = np.array([
        [1, 0, 7, 1, 5, 101., 80, 1, 209, times[1], times[0], 5],
        [4, 2, 7, -1, 2, 102., 70, 0, 83, times[4], times[2], 5],
        [8, 6, 7, -1, 3, 105., 70, 0, 125, times[8], times[6], 5],
    ])
    eo = np.array([
        [1, 0, 1000000, -1, 5, 100., 82, 1, 209, times[1], times[0], 5],
        [10, 9, 1000000, 1, 5, 108., 32, 0, 209, times[10], times[9], 5],
    ])
    ct = np.array([[7, 1, 8, 1, 5, 101., 103.8, 14000., 417., 13583.,
                    np.nan, np.nan, np.nan, 5, -1, 80, 70]])
    et = np.array([[1000000, 1, 10, -1, 5, 100., 108., -40000., 418., -40418.,
                    4., 0., -8., 5, 1, 82, 32]])
    longs = np.array([0, 5, 5, 5, 3, 3, 3, 3, 0, 0, 0, 0, 0, 0.])
    shorts = np.array([0, 5, 5, 5, 5, 5, 5, 5, 5, 5, 0, 0, 0, 0.])
    coreeq = [0, -5418, -418, -418, 4583, 7583, 10583, 10583, 13583, 13583, 13583, 13583, 13583, 13583]
    corecash = [0, -209, -209, -209, 1708, 1708, 1708, 1708, 13583, 13583, 13583, 13583, 13583, 13583]
    extraeq = [0, -5418, -10418, -10418, -15418, -20418, -25418, -25418, -30418, -35418, -40418, -40418, -40418, -40418]
    extracash = [0, -209, -209, -209, -209, -209, -209, -209, -209, -209, -40418, -40418, -40418, -40418]
    ec = curve(extraeq, -shorts, extracash, True)
    equity = np.array(coreeq)+extraeq
    realized = np.array(corecash)+extracash
    orders = np.concatenate((co, eo))
    orders = orders[np.argsort(orders[:, 0], kind="stable")]
    arrays = dict(core_orders=co, core_trades=ct, extra_orders=eo, extra_trades=et, extra_curve=ec,
                  orders=orders, trades=np.concatenate((ct, et)),
                  curve=curve(equity, longs-shorts, realized),
                  long_quantity=longs, short_quantity=shorts)
    config = dict(id="合算人工", schedule=0, style=0)
    summary = dict(profit=13583., loss=40418., net=-26835., gross=-26000., fees=835.,
                   entries=2, quantity=10, parent_wins=1, parent_losses=1,
                   max_quantity=5, max_long=5, max_short=5, max_gross_quantity=10,
                   max_drawdown=26835., deadline_entries=1, activation_time=times[0],
                   components={"旧核": dict(entries=1, profit=13583., loss=0., net=13583., gross=14000., fees=417.),
                               "追加": dict(entries=1, profit=0., loss=40418., net=-40418., gross=-40000., fees=418.)},
                   phases={name: dict(entries=2 if i == 5 else 0, net=-26835. if i == 5 else 0.)
                           for i, name in enumerate(PHASES)},
                   phase_equity_changes={name: -26835. if i == 5 else 0. for i, name in enumerate(PHASES)},
                   direction={"買い": dict(entries=1, net=13583.), "売り": dict(entries=1, net=-40418.)})
    return arrays, ready, quotes, history, phase, config, summary, co[:, :8].copy()


def main():
    """
    機能: 合算人工の一致と誤記検出を確認して証拠を新規保存する。
    引数: なし。
    返り値: None。金融核・旧会計核は読み込まない。
    """
    result = audit_one(*fixture())
    assert result["net"] == -26835. and result["maximum_curve_error"] < 1e-6
    records = []
    corruptions = [
        ("部分返済丸めの誤り", "core_orders", (1, 8), 84.),
        ("加重平均返済値の誤り", "core_trades", (0, 6), 105.),
        ("未測定幅を零へ偽装", "core_trades", (0, 10), 0.),
        ("追加が旧親IDへ衝突", "extra_orders", (0, 2), 7.),
        ("両建てを相殺して長側在庫を消す", "long_quantity", (2,), 0.),
        ("異常気配行だけ曲線を書換え", "curve", (3, 0), -10000.),
        ("部分返済後の円会計差を隠す", "curve", (4, 0), -10836.),
        ("追加単独曲線の費用誤り", "extra_curve", (2, 0), -10209.),
    ]
    for label, name, place, value in corruptions:
        args = copy.deepcopy(fixture())
        args[0][name][place] = value
        try:
            audit_one(*args)
        except AssertionError as exc:
            records.append(dict(case=label, detected=str(exc)))
        else:
            raise AssertionError("不正保存値を拒否しなかった:"+label)
    args = copy.deepcopy(fixture())
    args[6]["components"]["追加"]["fees"] = 417.
    try:
        audit_one(*args)
    except AssertionError as exc:
        records.append(dict(case="単独components費用の誤り", detected=str(exc)))
    else:
        raise AssertionError("単独会計の誤りを拒否しなかった")
    forbidden = ("baseline131", "participation131", "engine131", "run_portfolio131")
    assert not any(name in sys.modules for name in forbidden)
    target = HERE / ("合算会計監査の独立手計算_"+str(time.time_ns())+".json")
    proof = dict(passed=True, financial_replays=0, checks=1+len(records), corruptions=records,
                 expected_net=-26835., expected_fees=835.,
                 checker=reference(HERE / "audit_portfolio131.py"),
                 test_source=reference(Path(__file__).resolve()),
                 old_kernel_imports=0, source_changes=0)
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(target.as_posix(), "人工", proof["checks"], "合格", flush=True)


if __name__ == "__main__":
    main()
