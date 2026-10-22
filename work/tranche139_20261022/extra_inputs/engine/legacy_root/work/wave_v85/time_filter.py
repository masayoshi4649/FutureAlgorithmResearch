"""寄付き回避を、価格や後日の損益によらない現地時刻から作る。"""
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
import numpy as np

TOKYO = ZoneInfo('Asia/Tokyo')
NEW_YORK = ZoneInfo('America/New_York')
SOURCE = 'https://www.nyse.com/markets/hours-calendars'
HOLIDAYS = {2026: frozenset(date.fromisoformat(x) for x in (
    '2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03', '2026-05-25',
    '2026-06-19', '2026-07-03', '2026-09-07', '2026-11-26', '2026-12-25'))}


def windows(day, mode):
    """
    機能: 日本の暦日から、事前に分かる寄付き静観窓を作る。
    引数: day(date)、mode(str)は空/J/U/JU。
    返り値: list[tuple[float,float,str]]。開始秒、終了秒、理由。
    """
    result = []
    if 'J' in mode:
        result.append((datetime.combine(day, time(8, 45), TOKYO).timestamp(),
                       datetime.combine(day, time(9, 15), TOKYO).timestamp(), 'J'))
    if 'U' in mode:
        if day.year not in HOLIDAYS:
            raise ValueError('NYSE休場日が未定義の年です。公式日程の追加が必要です')
        if day.weekday() < 5 and day not in HOLIDAYS[day.year]:
            opening = datetime.combine(day, time(9, 30), NEW_YORK)
            result.append(((opening-timedelta(minutes=15)).timestamp(),
                           (opening+timedelta(minutes=15)).timestamp(), 'U'))
    return sorted(result)


def features(ready, mode):
    """
    機能: 各保存行の取引禁止・予定返済・再開可能な準備時刻を作る。
    引数: ready(dict)はtime_s/last、mode(str)。
    返り値: dict。bool配列2本、float配列1本、窓の事前予定。
    """
    stamps, prices = ready['time_s'], ready['last']
    active = np.zeros(len(stamps), bool)
    force = np.zeros(len(stamps), bool)
    not_before = np.full(len(stamps), -np.inf)
    plans = []
    if not mode:
        return dict(active=active, force=force, not_before=not_before, windows=plans)
    day = datetime.fromtimestamp(stamps[0], TOKYO).date()
    last_day = datetime.fromtimestamp(stamps[-1], TOKYO).date()
    valid = np.flatnonzero(np.isfinite(prices) & (prices > 0))
    while day <= last_day:
        for start, end, reason in windows(day, mode):
            # ----------------------------------------
            # 窓全体が原本の範囲外なら、前日の古い準備を誤って制限しない。
            if end <= stamps[0] or start > stamps[-1]:
                continue
            active |= (stamps >= start) & (stamps < end)
            not_before[stamps >= start] = np.maximum(not_before[stamps >= start], end)
            index = np.searchsorted(stamps[valid], start, side='left')
            row = int(valid[index]) if index < len(valid) else -1
            if row >= 0:
                force[row] = True
            plans.append(dict(reason=reason, start=start, end=end, first_valid_row=row,
                開始=datetime.fromtimestamp(start, TOKYO).isoformat(),
                終了=datetime.fromtimestamp(end, TOKYO).isoformat(),
                最初の有効観測=None if row < 0 else datetime.fromtimestamp(stamps[row], TOKYO).isoformat(),
                窓終了後の初観測=bool(row >= 0 and stamps[row] >= end)))
        day += timedelta(days=1)
    return dict(active=active, force=force, not_before=not_before, windows=plans)
