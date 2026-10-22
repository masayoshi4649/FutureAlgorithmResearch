"""会計監査が不正な保存値を検出することを、固定手計算例で確認する。"""

import copy
from datetime import datetime
import json
from pathlib import Path
import time
from zoneinfo import ZoneInfo

import numpy as np

from audit_accounts131 import audit_account, independent_phases, PHASES, reference

HERE = Path(__file__).resolve().parent


def fixture():
    """
    機能: 買い・売り各一取引、異常気配一行を含む手計算可能な例を作る。
    引数: なし。
    返り値: tupleは注文・親・曲線・入力・条件・公開集計。
    """
    start = datetime(2026, 9, 21, 8, 45, tzinfo=ZoneInfo("Asia/Tokyo")).timestamp()
    seconds = np.array([2700, 2760, 2820, 2880, 2940, 3000, 3360, 3420, 24840, 24900])
    times = start+seconds
    bid = np.array([99., 99.5, 101., 103., np.nan, 102., 103., 104., 102., 101.])
    quotes = {"bid": bid, "ask": bid+.5, "quote_valid": np.isfinite(bid)}
    ready = {"time_s": times, "symbol": "TOPIX", "session": "2026-09-21_Day",
             "atr": np.full(10, 2.), "tick": .5, "start": start, "limit": times[8]}
    history = np.zeros((10, 15))
    history[:, [6, 7, 10, 11]] = 1.
    history[:, 8] = 100.
    phase = independent_phases(ready)
    orders = np.array([
        [1, 0, 0, 1, 5, 100., 82, 1, 209, times[1], times[0], 5],
        [5, 3, 0, -1, 5, 102., 70, 0, 209, times[5], times[3], 5],
        [7, 6, 1, -1, 5, 104., 80, 1, 209, times[7], times[6], 5],
        [9, 8, 1, 1, 5, 101.5, 93, 0, 209, times[9], times[8], 5],
    ])
    trades = np.array([
        [0, 1, 5, 1, 5, 100., 102., 10000., 418., 9582., 2., 3., -.5, 5, 1, 82, 70],
        [1, 7, 9, -1, 5, 104., 101.5, 12500., 418., 12082., 2., 2.5, -.5, 5, 1, 80, 93],
    ])
    equity = [0., -2918., 4582., 14582., 14582., 9582., 9582., 6664., 16664., 21664.]
    position = [0, 5, 5, 5, 5, 0, 0, -5, -5, 0]
    cash = [0., -209., -209., -209., -209., 9582., 9582., 9373., 9373., 21664.]
    drawdown = [0., 2918., 2918., 2918., 2918., 5000., 5000., 7918., 7918., 7918.]
    curve = np.column_stack((equity, position, cash, drawdown, np.ones(10)))
    config = {"id": "人工", "selector": 0, "per_phase": 2, "conversion": 0,
              "participation_seconds": 2700., "width_mode": 0}
    row = dict(method="人工", session=ready["session"], symbol="TOPIX",
               profit=21664., loss=0., net=21664., gross=22500., fees=836.,
               entries=2, quantity=10, parent_wins=2, parent_losses=0,
               max_quantity=5, max_drawdown=7918., deadline_entries=1,
               phases={name: dict(entries=2 if i == 5 else 0, net=21664. if i == 5 else 0.)
                       for i, name in enumerate(PHASES)},
               phase_equity_changes={name: 21664. if i == 5 else 0. for i, name in enumerate(PHASES)},
               direction={"買い": dict(entries=1, net=9582.), "売り": dict(entries=1, net=12082.)})
    return orders, trades, curve, ready, quotes, history, phase, config, row


def main():
    """
    機能: 正常な手計算例と、故意に壊した保存値の拒否を確認する。
    引数: なし。
    返り値: None。金融核は読み込まず、時刻付き検査証拠を新規保存する。
    """
    result = audit_account(*fixture())
    assert result["net"] == 21664. and result["maximum_curve_error"] == 0.
    cases = [
        ("新規の手数料を過少記録", 0, (0, 8), 208.),
        ("異常行を飛ばした後の約定価格誤り", 0, (1, 5), 103.),
        ("判断行と同一行に約定", 0, (0, 1), 1.),
        ("親番号の重複", 0, (2, 2), 0.),
        ("異常気配中に評価だけ変化", 2, (4, 0), 14000.),
        ("未払返済手数料を値洗いから除去", 2, (2, 0), 4791.),
        ("返済後も保有", 2, (5, 1), 5.),
        ("空売り損益の符号違い", 1, (1, 7), -12500.),
        ("初回参加前の理由を期限参加に改竄", 0, (2, 6), 82.),
        ("新規時区分の誤り", 1, (0, 13), 1.),
    ]
    passed = []
    for name, item, location, value in cases:
        args = copy.deepcopy(fixture())
        args[item][location] = value
        try:
            audit_account(*args)
        except AssertionError as exc:
            passed.append({"case": name, "detected": str(exc)})
        else:
            raise AssertionError("不正値を拒否しなかった:"+name)
    output = {"passed": len(passed) == len(cases), "financial_replays": 0,
              "normal_fixture_net": 21664., "damaged_cases": passed,
              "checker": reference(HERE / "audit_accounts131.py"),
              "test_source": reference(Path(__file__).resolve())}
    target = HERE / ("独立会計監査の人工検査_"+str(time.time_ns())+".json")
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(target.as_posix(), "人工", len(cases)+1, "合格", flush=True)


if __name__ == "__main__":
    main()
