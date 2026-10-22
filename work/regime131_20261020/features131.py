"""現物休場・昼休み・米国時計を、当時既知の予定として原行へ対応する。"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import sys
import numpy as np
from common131 import BASE, PREV

sys.path.insert(0, str(BASE))
sys.path.insert(0, str(PREV))
import features129

JST = ZoneInfo("Asia/Tokyo")
NY = ZoneInfo("America/New_York")
LONDON = ZoneInfo("Europe/London")
HOLIDAYS = {"2026-09-21", "2026-09-22", "2026-09-23", "2026-10-12"}
PHASES = (
    "日本現物寄付前", "日本現物前場", "日本現物昼休み", "日本現物後場",
    "日本現物引け注文時間以降", "日本現物休場の先物日中",
    "欧州取引中・米国朝前", "米国8時30分以降・寄付前",
    "米国現物寄付後30分", "欧米現物の重複時間", "欧州引け後の米国時間", "米国現物引け前1時間",
    "米国現物終了後",
)


def phases(ready):
    """
    機能: 日付と予定時刻だけから各原行の時間区分を決める。
    引数: ready(dict)は一商品一場の原行入力。
    返り値: ndarray[int64]は13区分番号。価格・将来損益を参照しない。
    """
    times = ready["time_s"]
    date = ready["session"].split("_")[0]
    if ready["session"].endswith("_Day"):
        if date in HOLIDAYS:
            return np.full(len(times), 5, np.int64)
        midnight = datetime.combine(datetime.fromisoformat(date).date(), time(), JST).timestamp()
        minute = (times-midnight)/60.
        return np.select([minute < 540., minute < 690., minute < 750., minute < 925.],
                         [0, 1, 2, 3], default=4).astype(np.int64)
    opening = float(ready["us_open"])
    assert np.isfinite(opening)
    european_close = datetime.combine(datetime.fromisoformat(date).date(), time(16, 30), LONDON).timestamp()
    return np.select([times < opening-3600., times < opening,
                      times < opening+1800., times < european_close, times < opening+19800.,
                      times < opening+23400.],
                     [6, 7, 8, 9, 10, 11], default=12).astype(np.int64)


def build(packet):
    """
    機能: 既存の厳密過去参照を用い、中値・二市場特徴と時計区分を準備する。
    引数: packet(dict)は変更しない保存原板入力。
    返り値: tuple[dict,...]は入力、二市場短期特徴、履歴、時間区分。
    """
    inputs, markets, history, _ = features129.build(packet, "mid", 0.)
    return inputs, markets, history, {key: phases(ready) for key, ready in inputs.items()}
