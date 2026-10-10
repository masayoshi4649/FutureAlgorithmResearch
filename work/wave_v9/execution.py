"""転換イベントを一回だけ使い、保存された全気配を追跡する注文再生。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
SESSIONS = ['2026-09-21_Day', '2026-09-21_Night', '2026-09-22_Day', '2026-09-22_Night', '2026-09-23_Day', '2026-09-23_Night']
SYMBOLS = ['NK225', 'TOPIX']
TICKS = {'NK225': 10., 'TOPIX': .5}
MULTIPLIERS = {'NK225': 1000, 'TOPIX': 10000}


def save(path: Path, value: object) -> None:
    """機能: NumPyの数値と非有限値に対応して日本語JSONを保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    def convert(v):
        """機能: 配列や日時をJSON互換値に変換する。

        引数: v (object)。返り値: 変換値 (object)。
        """
        if isinstance(v, dict):
            return {str(k): convert(x) for k, x in v.items()}
        if isinstance(v, (list, tuple, np.ndarray)):
            return [convert(x) for x in v]
        if isinstance(v, np.generic):
            v = v.item()
        if isinstance(v, float) and not np.isfinite(v):
            return None
        if isinstance(v, (pd.Timestamp, Path)):
            return str(v)
        return v
    path.write_text(json.dumps(convert(value), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def bounds(session: str) -> tuple[float, float]:
    """機能: セッション開始と返済開始の代理時計を返す。

    引数: session (str)。返り値: 開始・返済開始のUnix秒 (tuple[float, float])。
    """
    day = pd.Timestamp(session[:10], tz='Asia/Tokyo')
    start = day + pd.Timedelta(hours=17) if session.endswith('Night') else day + pd.Timedelta(hours=8, minutes=45)
    limit = day + pd.Timedelta(days=1, hours=5, minutes=50) if session.endswith('Night') else day + pd.Timedelta(hours=15, minutes=35)
    return start.timestamp(), limit.timestamp()


def atr_at(session: str, symbol: str, times: np.ndarray, cutoff: float | None = None) -> np.ndarray:
    """機能: 確定5分足に追加1分待機を課したATRを各観測へ過去方向で対応付ける。

    引数: session/symbol (str)、times (ndarray)、cutoff (float|None)。
    返り値: 各観測で既知のATR (ndarray)。
    """
    root = ROOT/'work'/'wave_v7'/'live' if session == SESSIONS[-1] else ROOT
    five = pd.read_csv(root/'candle_5min'/symbol/f'{session}.csv')
    five = five[five.closed.astype(str).str.lower().eq('true')].copy()
    five['time'] = pd.to_datetime(five.time)
    five = five.sort_values('time')
    available = five.time.astype('int64').to_numpy() / (1e6 if five.time.dt.unit == 'us' else 1e9) + 360
    if cutoff is not None:
        keep = available <= cutoff
        five, available = five.loc[keep], available[keep]
    result = np.full(len(times), np.nan)
    if five.empty:
        return result
    tr = pd.concat([five.high-five.low, (five.high-five.close.shift()).abs(), (five.low-five.close.shift()).abs()], axis=1).max(axis=1)
    values = tr.ewm(alpha=1/12, adjust=False, min_periods=3).mean().clip(lower=2*TICKS[symbol]).to_numpy()
    positions = np.searchsorted(available, times, side='right') - 1
    valid = positions >= 0
    result[valid] = values[positions[valid]]
    return result


def configs() -> list[dict]:
    """機能: 15入口系統・2発注方式・3出口の90条件を事前定義する。

    引数: なし。返り値: 条件一覧 (list[dict])。
    """
    output = []
    for number in range(15):
        family = f'T{number:02d}'
        group = '価格CUSUM転換' if number == 0 else '移動平均の転換' if number <= 5 else '板の転換' if number <= 11 else '価格と板の転換' if number == 12 else '２銘柄の転換'
        for entry in ['初動逆指値', '追跡0.25ATR']:
            for exit_name in ['追跡1ATR', '追跡2ATR', '順行1ATRで保護']:
                output.append(dict(id=f'{family}_{entry}_{exit_name}', family=family, group=group,
                                   entry=entry, exit=exit_name, warmup=20, cooldown=10, expiry=10))
    return output


def simulate(tape: dict, events: pd.DataFrame, config: dict, session: str, symbol: str,
             delay: str = '次行') -> list[dict]:
    """機能: 転換ごとの新規条件を一回だけ作り、全気配で追跡してセッション内に返済する。

    引数: tape (dict) はseq/time_s/bid/ask/数量/atr配列、events (DataFrame)、
    config (dict)、session/symbol/delay (str)。返り値: 確定・未返済取引 (list[dict])。
    """
    time, seq, bid, ask, atr = (tape[k] for k in ['time_s', 'seq', 'bid', 'ask', 'atr'])
    event_rows = events[events.family.eq(config['family'])].sort_values('seq').to_dict('records') if len(events) else []
    assert not pd.Series([e['seq'] for e in event_rows]).duplicated().any()
    start, limit = bounds(session)
    tick = TICKS[symbol]
    used, trades = set(), []
    pointer, latest = 0, None
    pending = position = queued = None
    last_exit = -np.inf

    def rounded(value, side):
        """機能: 条件価格を買いは上、売りは下の呼値へ丸める。

        引数: value (float)、side (int)。返り値: 呼値価格 (float)。
        """
        return float((np.ceil(value/tick) if side > 0 else np.floor(value/tick))*tick)

    def enqueue(kind, i, payload):
        """機能: 成立した注文を観測後の約定待ちに置く。

        引数: kind (str)、i (int)、payload (dict)。返り値: 注文待機 (dict)。
        """
        return dict(kind=kind, i=i, time=float(time[i]), payload=payload)

    def ready(order, i):
        """機能: 指定した行数・時計の待機が済んだかを調べる。

        引数: order (dict)、i (int)。返り値: 約定可能 (bool)。
        """
        return i >= order['i']+(2 if delay == '２行後' else 1) and (delay != '次時刻' or time[i] > order['time'])

    for i in range(len(seq)):
        now, b, a = float(time[i]), float(bid[i]), float(ask[i])
        while pointer < len(event_rows) and event_rows[pointer]['seq'] <= seq[i]:
            latest = event_rows[pointer]
            pointer += 1
        # ----------------------------------------
        # 受付済みの成立注文は、新しい逆方向の情報でも遡って取り消さない。
        if queued and ready(queued, i):
            if queued['kind'] == '新規':
                p, side = queued['payload'], queued['payload']['side']
                if now < limit-1800 and (tape['ask_qty'][i] if side > 0 else tape['bid_qty'][i]) >= 1:
                    fill = a if side > 0 else b
                    A = p['atr']
                    width = 1. if config['exit'] == '追跡1ATR' else 2.
                    position = dict(side=side, entry_price=fill, entry_time_s=now, entry_seq=int(seq[i]),
                                    atr=A, event_atr=p['event_atr'], event_id=p['event_id'],
                                    signal_time_s=p['signal_time_s'], signal_price=p['signal_price'],
                                    signal_seq=p['signal_seq'], source_last_seq=p['source_last_seq'],
                                    condition_time_s=p['created'], condition_seq=p['created_seq'],
                                    trigger_seq=p['trigger_seq'], reason=p['reason'],
                                    extreme=fill, stop=rounded(fill-side*width*A, -side), max_favorable=0.,
                                    entry_spread=a-b)
                pending, queued = None, None
                continue
            side = position['side']
            fill = b if side > 0 else a
            points = side*(fill-position['entry_price']) - 2*tick
            trades.append(dict(**position, closed=True, exit_time_s=now, exit_seq=int(seq[i]), exit_price=fill,
                               exit_reason=queued['payload']['reason'], exit_trigger_seq=queued['payload']['seq'],
                               net_points=points, stress_points=points-2*tick,
                               duration_min=(now-position['entry_time_s'])/60, exit_spread=a-b,
                               exit_in_session=now < limit+300))
            position, queued, last_exit = None, None, now
            continue
        if queued:
            continue
        # ----------------------------------------
        # 出口は転換判定に依存させず、保有の実行可能気配だけを追跡する。
        if position:
            side, A = position['side'], position['atr']
            quote = b if side > 0 else a
            reason = 'セッション内返済' if now >= limit else '追跡ストップ' if side*(quote-position['stop']) <= 0 else None
            if reason:
                queued = enqueue('返済', i, dict(reason=reason, seq=int(seq[i])))
                continue
            position['extreme'] = max(position['extreme'], quote) if side > 0 else min(position['extreme'], quote)
            favorable = side*(position['extreme']-position['entry_price'])
            position['max_favorable'] = max(position['max_favorable'], favorable)
            width = 1. if config['exit'] == '追跡1ATR' else .5 if config['exit'] == '順行1ATRで保護' and favorable >= A else 2.
            stop = rounded(position['extreme']-side*width*A, -side)
            position['stop'] = max(position['stop'], stop) if side > 0 else min(position['stop'], stop)
            continue
        if now < start+config.get('warmup', 20)*60 or now >= limit-1800 or now-last_exit < config.get('cooldown', 10)*60:
            pending = None
            continue
        # ----------------------------------------
        # 旧条件の同時成立と取消が競合する場合は、旧注文の成立を優先する。
        if pending and now > pending['deadline']:
            pending = None
        if pending and i > pending['created_i']:
            side = pending['side']
            quote = a if side > 0 else b
            if side*(quote-pending['threshold']) >= 0:
                pending['trigger_seq'] = int(seq[i])
                queued = enqueue('新規', i, pending.copy())
                pending = None
                continue
        if pending and latest and latest['side'] == -pending['side'] and latest['seq'] > pending['signal_seq']:
            pending = None
        if pending:
            if config['entry'] == '追跡0.25ATR':
                side = pending['side']
                quote = a if side > 0 else b
                pending['anchor'] = min(pending['anchor'], quote) if side > 0 else max(pending['anchor'], quote)
                pending['threshold'] = rounded(pending['anchor']+side*.25*pending['atr'], side)
            continue
        if latest is None or latest['event_id'] in used or now > latest['deadline_time_s']:
            continue
        if not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        side = int(latest['side'])
        quote, A = (a if side > 0 else b), float(atr[i])
        offset = .25 if config['entry'] == '追跡0.25ATR' else 0.
        event_i = np.searchsorted(seq, latest['seq'])
        assert event_i <= i and seq[event_i] == latest['seq']
        pending = dict(side=side, atr=A, event_atr=float(latest['atr']),
                       event_id=latest['event_id'], created=now, created_i=i, created_seq=int(seq[i]),
                       signal_time_s=float(latest['time_s']), signal_seq=int(latest['seq']),
                       signal_price=float((bid[event_i]+ask[event_i])/2),
                       source_last_seq=int(latest['source_last_seq']), reason=latest.get('reason', ''),
                       deadline=float(latest['deadline_time_s']), anchor=quote,
                       threshold=rounded(quote+side*offset*A, side))
        used.add(latest['event_id'])
    if position:
        side, now = position['side'], float(time[-1])
        quote = float(bid[-1] if side > 0 else ask[-1])
        points = side*(quote-position['entry_price'])-2*tick
        trades.append(dict(**position, closed=False, mark_time_s=now, mark_price=quote,
                           net_points=points, stress_points=points-2*tick,
                           duration_min=(now-position['entry_time_s'])/60,
                           pending_exit=queued['payload']['reason'] if queued and queued['kind'] == '返済' else None))
    assert len({t['event_id'] for t in trades}) == len(trades)
    return trades


def metrics(trades: list[dict], session: str, symbol: str, config: dict, delay: str = '次行') -> dict:
    """機能: 確定取引の利益・損失と未返済評価を分けて集計する。

    引数: trades (list[dict])、session/symbol/delay (str)、config (dict)。返り値: 集計辞書 (dict)。
    """
    closed = [t for t in trades if t['closed']]
    net = np.array([t['net_points']*MULTIPLIERS[symbol] for t in closed])
    return dict(方式=config['id'], 群=config['group'], 系統=config['family'], セッション=session, 銘柄=symbol, 約定遅延=delay,
                取引数=len(closed), 未返済数=len(trades)-len(closed), 勝ち数=int((net>0).sum()),
                利益円=float(net[net>0].sum()), 損失円=float(-net[net<0].sum()), 収支円=float(net.sum()),
                費用倍収支円=float(sum(t['stress_points']*MULTIPLIERS[symbol] for t in closed)),
                費用倍ATR収支=float(sum(t['stress_points']/t['atr'] for t in closed)),
                評価損益円=float(sum(t['net_points']*MULTIPLIERS[symbol] for t in trades if not t['closed'])),
                平均保有分=float(np.mean([t['duration_min'] for t in closed])) if closed else None,
                最大順行からの返却円=float(sum(max(0, t['max_favorable']-t['net_points']-2*TICKS[symbol])*MULTIPLIERS[symbol] for t in closed)))
