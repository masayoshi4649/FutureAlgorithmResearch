"""長時間の波と板の動きを比較する、セッション内完結の検知研究。"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import itertools
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
SESSIONS = ("2026-09-21_Day", "2026-09-21_Night", "2026-09-22_Day")
SYMBOLS = ("NK225", "TOPIX")
TICKS = {"NK225": 10.0, "TOPIX": 0.5}
FAMILIES = {
    1: "価格・５分対30分移動平均", 2: "価格・10分対60分移動平均", 3: "価格・30分回帰",
    4: "価格・30分方向効率", 5: "価格・30分価格帯位置", 6: "価格・60分中心からの変位",
    7: "価格・累積VWAP方向", 8: "価格・30分RSI", 9: "価格・両指数の方向一致",
    10: "価格・傾きと方向効率の合成", 11: "板・最良気配中心の傾き", 12: "板・数量加重気配の傾き",
    13: "板・最良気配の注文フロー", 14: "板・最良数量の偏り", 15: "板・５段数量の偏り",
    16: "板・約定方向推定出来高", 17: "板・売買気配の更新方向", 18: "価格と注文フローの一致",
    19: "気配中心と更新方向の一致", 20: "価格と板情報の合成",
    21: "価格・20分と40分の方向一致", 22: "価格・５分足方向指数",
    23: "方向指数で開始・60分回帰で反転確認",
    24: "短期方向・長期回帰・他指数確認で持続",
}


@dataclass(frozen=True)
class Config:
    """機能: 比較設定を保持する。引数: 宣言された各型。返り値: Config。"""

    family: int
    threshold: float
    confirm: int
    trail: float
    exit_multiplier: int = 3

    @property
    def key(self) -> str:
        """機能: 再現可能な設定識別子を作る。

        引数: self (Config)。返り値: 識別子 (str)。
        """
        return f"{self.family:02d}_{self.threshold:.2f}_{self.confirm}_{self.trail:g}_{self.exit_multiplier}"


def save_json(path: Path, data: object) -> None:
    """機能: 日本語の結果を保存する。

    引数: path (Path)、data (object)。返り値: なし (None)。
    """
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8")


def read_candle(path: Path) -> pd.DataFrame:
    """機能: 確定済み保存足を時刻順に読み込む。

    引数: path (Path)。返り値: 足 (DataFrame)。
    """
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df.time)
    df = df[df.closed.astype(str).str.lower().eq("true")].set_index("time").sort_index()
    if df.index.duplicated().any():
        raise ValueError("保存足の時刻が重複しています")
    return df


def price_features(one: pd.DataFrame, five: pd.DataFrame, tick: float) -> pd.DataFrame:
    """機能: 過去の確定価格から１分刻みの特徴量を作る。

    引数: one/five (DataFrame)、tick (float)。返り値: 特徴量 (DataFrame)。
    無約定分は既知終値を持ち越すが、実在足と経過時間を区別して保持する。
    """
    index = pd.date_range(one.index[0], one.index[-1], freq="min")
    z = one.reindex(index)
    z["observed"] = z.close.notna()
    c = z.close.ffill()
    z["close"] = c
    z["volume"] = z.volume.fillna(0)
    seen = pd.Series(pd.NaT, index=index, dtype=index.dtype)
    seen.loc[one.index] = one.index
    z["stale_minutes"] = (index.to_series()-seen.ffill()).dt.total_seconds()/60
    tr = pd.concat([five.high-five.low, (five.high-five.close.shift()).abs(),
                    (five.low-five.close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/12, adjust=False, min_periods=3).mean().clip(lower=2*tick)
    # ５分足の開始時刻から４分目の１分足が確定した時に初めて使用可能。
    atr.index += pd.Timedelta(minutes=4)
    z["atr"] = atr.reindex(index, method="ffill")
    for n in (5, 10, 15, 20, 30, 60):
        z[f"ema{n}"] = c.ewm(span=n, adjust=False, min_periods=min(n, 20)).mean()
    z["gap30"] = (z.ema5-z.ema30)/z.atr
    z["gap60"] = (z.ema10-z.ema60)/z.atr
    z["move30"] = (c-c.shift(30))/z.atr
    z["move20"] = (c-c.shift(20))/z.atr
    z["move40"] = (c-c.shift(40))/z.atr
    z["er30"] = (c-c.shift(30)).abs()/c.diff().abs().rolling(30).sum().replace(0, np.nan)
    x = np.arange(30, dtype=float)-14.5
    z["reg30"] = c.rolling(30).apply(lambda a: np.dot(x, a)/np.dot(x, x)*29, raw=True)/z.atr
    z["r2"] = c.rolling(30).apply(lambda a: np.dot(x, a-a.mean())**2/
                (np.dot(x, x)*np.dot(a-a.mean(), a-a.mean())) if np.ptp(a) else 0.0, raw=True)
    x60 = np.arange(60, dtype=float)-29.5
    z["reg60"] = c.rolling(60).apply(lambda a: np.dot(x60, a)/np.dot(x60, x60)*59, raw=True)/z.atr
    z["r2_60"] = c.rolling(60).apply(lambda a: np.dot(x60, a-a.mean())**2/
                (np.dot(x60, x60)*np.dot(a-a.mean(), a-a.mean())) if np.ptp(a) else 0.0, raw=True)
    upper, lower = c.rolling(30).max(), c.rolling(30).min()
    z["range30"] = 2*(c-lower)/(upper-lower).replace(0, np.nan)-1
    gain = c.diff().clip(lower=0).ewm(alpha=1/30, adjust=False).mean()
    loss = -c.diff().clip(upper=0).ewm(alpha=1/30, adjust=False).mean()
    z["rsi30"] = 100*gain/(gain+loss).replace(0, np.nan)
    z["vwap"] = (c*z.volume).cumsum()/z.volume.cumsum().replace(0, np.nan)
    z["age"] = np.arange(len(z))
    up, down = five.high.diff(), -five.low.diff()
    plus = up.where((up>down)&(up>0), 0).ewm(span=8, adjust=False).mean()
    minus = down.where((down>up)&(down>0), 0).ewm(span=8, adjust=False).mean()
    di = (plus-minus)/(plus+minus).replace(0, np.nan)
    di.index += pd.Timedelta(minutes=4)
    z["di40"] = di.reindex(index, method="ffill")
    return z


def attach_book(z: pd.DataFrame, path: Path) -> pd.DataFrame:
    """機能: 利用可能時刻を守って板特徴量を価格特徴へ付加する。

    引数: z (DataFrame)、path (Path)。返り値: 板特徴追加後 (DataFrame)。
    """
    if not path.exists():
        return z
    b = pd.read_csv(path)
    b["time"] = pd.to_datetime(b.time)
    b = b.set_index("time").sort_index()
    # 板の time は利用可能イベントの属する１分足開始時刻。使用は同分末確定後。
    b = b.reindex(z.index)
    for col in ("book_mid_last", "microprice_last"):
        value = b[col].ffill(limit=10)
        z[f"{col}_gap"] = (value.ewm(span=5, adjust=False, min_periods=5).mean()-
                            value.ewm(span=30, adjust=False, min_periods=20).mean())/z.atr
    z["flow"] = b.ofi_sum.fillna(0).rolling(20, min_periods=10).sum()/b.ofi_abs_sum.fillna(0).rolling(20, min_periods=10).sum().replace(0, np.nan)
    z["imbalance1"] = b.imbalance1_mean.rolling(15, min_periods=8).mean()
    z["imbalance5"] = b.imbalance5_mean.rolling(15, min_periods=8).mean()
    z["signed_flow"] = b.signed_volume.fillna(0).rolling(20, min_periods=10).sum()/b.volume_delta.fillna(0).rolling(20, min_periods=10).sum().replace(0, np.nan)
    ups = b.bid_up.fillna(0)+b.ask_up.fillna(0)
    downs = b.bid_down.fillna(0)+b.ask_down.fillna(0)
    z["quote_flow"] = (ups-downs).rolling(15, min_periods=8).sum()/(ups+downs).rolling(15, min_periods=8).sum().replace(0, np.nan)
    z["book_present"] = b.event_count.fillna(0).rolling(5).sum().gt(0)
    return z


def persistent_direction(z: pd.DataFrame, threshold: float) -> pd.Series:
    """機能: 短期方向指数で開始し、長期回帰の反転確認まで同じ波を保持する。

    引数: z (DataFrame)、threshold (float)。返り値: 因果的な方向状態 (Series)。
    """
    side = 0
    result = np.zeros(len(z))
    for i, row in enumerate(z.itertuples()):
        if i>=30 and (i+1)%5==0 and np.isfinite(row.atr) and row.stale_minutes<=10:
            candidate = int(np.sign(row.di40)) if abs(row.di40)>=0.6*threshold and row.di40*row.move20>0 else 0
            if side==0 and candidate:
                side = candidate
            elif candidate==-side and row.reg60*candidate>=2*threshold and row.r2_60>=0.2:
                side = candidate
        result[i] = side
    return pd.Series(result, index=z.index)


def peer_persistent_direction(z: pd.DataFrame, peer: pd.DataFrame, threshold: float) -> pd.Series:
    """機能: 自指数の長短方向と他指数の長期方向が一致した波だけを開始する。

    引数: z/peer (DataFrame)、threshold (float)。返り値: 中立を含む持続方向 (Series)。
    返済は自指数の反転だけで行い、他指数が揃わない反転先への新規は待機する。
    """
    p = peer.reindex(z.index)
    side = 0
    result = np.zeros(len(z))
    for i, (row, other) in enumerate(zip(z.itertuples(), p.itertuples())):
        if i>=30 and (i+1)%5==0 and np.isfinite(row.atr) and row.stale_minutes<=10:
            candidate = int(np.sign(row.di40)) if abs(row.di40)>=0.6*threshold and row.di40*row.move20>0 else 0
            own = candidate!=0 and row.reg60*candidate>=2*threshold and row.r2_60>=0.2
            matched = candidate*other.reg60>0 and other.r2_60>=0.2 and other.stale_minutes<=10
            if side and candidate==-side and own:
                side = 0
            if side==0 and own and matched:
                side = candidate
        result[i] = side
    return pd.Series(result, index=z.index)


def score(z: pd.DataFrame, peer: pd.DataFrame, family: int, threshold: float = 0.25) -> pd.Series:
    """機能: 各価格・板仮説の符号付き方向強度を返す。

    引数: z/peer (DataFrame)、family (int)、threshold (float)。返り値: 方向強度 (Series)。
    """
    if family==1:
        s = z.gap30
    elif family==2:
        s = z.gap60
    elif family==3:
        s = (z.reg30/2).where(z.r2>=0.2, 0)
    elif family==4:
        s = (z.move30/2).where(z.er30>=0.15, 0)
    elif family==5:
        s = z.range30.where(z.range30*z.move30>0, 0)
    elif family==6:
        s = (z.close-z.ema60)/z.atr/2
    elif family==7:
        s = ((z.close-z.vwap)/z.atr/2).where((z.close-z.vwap)*z.vwap.diff(10)>0, 0)
    elif family==8:
        s = (z.rsi30-50)/20
    elif family==9:
        p = peer.gap30.reindex(z.index)
        s = z.gap30.where(z.gap30*p>0, 0)
    elif family==10:
        s = (z.gap30+z.reg30/2+z.move30/2)/3
    elif family==21:
        s = np.sign(z.move20)*pd.concat([z.move20.abs()/0.5, z.move40.abs()/0.8], axis=1).min(axis=1)*0.25
        s = s.where(z.move20*z.move40>0, 0)
    elif family==22:
        s = (z.di40/0.6).where(z.di40*z.move20>0, 0)
    elif family==23:
        s = persistent_direction(z, threshold)
    elif family==24:
        s = peer_persistent_direction(z, peer, threshold)
    elif "book_present" not in z:
        return pd.Series(0.0, index=z.index)
    elif family==11:
        s = z.book_mid_last_gap
    elif family==12:
        s = z.microprice_last_gap
    elif family==13:
        s = z.flow/0.10
    elif family==14:
        s = 2*z.imbalance1
    elif family==15:
        s = 2*z.imbalance5
    elif family==16:
        s = 2*z.signed_flow
    elif family==17:
        s = z.quote_flow/0.10
    elif family==18:
        s = z.gap30.where(z.gap30*z.flow>=0, 0)
    elif family==19:
        s = z.book_mid_last_gap.where(z.book_mid_last_gap*z.quote_flow>=0, 0)
    elif family==20:
        s = 0.7*z.gap30+0.15*z.quote_flow/0.10+0.15*z.signed_flow
    else:
        raise ValueError("未知の仮説")
    valid = z.age.ge(30)&z.atr.notna()&z.stale_minutes.le(10)
    if 11<=family<=20:
        valid &= z.book_present
    return s.replace([np.inf, -np.inf], np.nan).fillna(0).where(valid, 0)


def deadline(index: pd.DatetimeIndex) -> pd.Timestamp:
    """機能: セッション内の強制返済時刻を定める。

    引数: index (DatetimeIndex)。返り値: 強制返済時刻 (Timestamp)。
    """
    start = index[0]
    if start.hour>=16:
        return start.normalize()+pd.Timedelta(days=1, hours=5, minutes=50)
    if start.hour<7:
        return start.normalize()+pd.Timedelta(hours=5, minutes=50)
    return start.normalize()+pd.Timedelta(hours=15, minutes=35)


def simulate(one: pd.DataFrame, z: pd.DataFrame, strength: pd.Series, cfg: Config,
             symbol: str, session: str) -> list[dict]:
    """機能: 遅延検知、反対方向の継続確認、広い追跡と時刻返済を再生する。

    引数: one/z (DataFrame)、strength (Series)、cfg (Config)、symbol/session (str)。
    返り値: 波・仮想取引の一覧 (list[dict])。セッション外へは引き継がない。
    """
    limit = deadline(one.index)
    if one.index[-1]>=limit+pd.Timedelta(minutes=5):
        raise ValueError("セッション外の価格が混入しています。別セッションの価格では返済しません。")
    ready = z.index+pd.Timedelta(minutes=2)
    raw = np.where(strength>=cfg.threshold, 1, np.where(strength<=-cfg.threshold, -1, 0))
    schedule = dict(zip(ready, zip(raw, z.atr, z.stale_minutes)))
    times = list(schedule)
    cursor, last, streak = 0, 0, 0
    decision, atr, stale, signal_time = 0, np.nan, 0, None
    active = None
    trades = []
    next_allowed = one.index[0]
    blocked_side = 0
    tick = TICKS[symbol]
    for row in one.itertuples():
        now, op, high, low, close = row.Index, row.open, row.high, row.low, row.close
        while cursor<len(times) and times[cursor]<=now:
            t = times[cursor]
            side, a, st = schedule[t]
            streak = streak+1 if side==last and side else (1 if side else 0)
            last = side
            decision, atr, stale, signal_time = side, a, st, t-pd.Timedelta(minutes=1)
            if blocked_side and side==-blocked_side:
                blocked_side = 0
            cursor += 1

        # ----------------------------------------
        # 建玉が存在する足では、前足終了時までに固定した価格条件を先に判定する。
        if active is not None:
            side, stop = active["side"], active["stop"]
            reason, px = None, None
            if now>=limit:
                reason, px = "セッション内の時刻返済", op
            elif cfg.family==24 and decision==0:
                reason, px = "自指数が反転・相手未確認", op
            elif decision==-side and streak>=cfg.confirm*cfg.exit_multiplier:
                reason, px = "反対方向が継続", op
            elif side==1 and low<=stop:
                reason, px = "保護・追跡返済", min(op, stop)
            elif side==-1 and high>=stop:
                reason, px = "保護・追跡返済", max(op, stop)
            if reason:
                active.update(exit_time=now, exit_price=float(px), closed=True, reason=reason,
                              duration_min=(now-active["entry_time"]).total_seconds()/60,
                              gross_points=side*(px-active["entry_price"]))
                trades.append(active)
                active = None
                if reason in ("反対方向が継続", "自指数が反転・相手未確認"):
                    next_allowed = now
                else:
                    next_allowed = now+pd.Timedelta(minutes=5)
                    if reason=="保護・追跡返済":
                        blocked_side = side
            else:
                active["peak"] = max(active["peak"], side*close)
                proposed = side*(active["peak"]-cfg.trail*max(active["atr"], float(atr) if np.isfinite(atr) else active["atr"]))
                proposed = math.floor(proposed/tick)*tick if side==1 else math.ceil(proposed/tick)*tick
                active["stop"] = max(stop, proposed) if side==1 else min(stop, proposed)

        # ----------------------------------------
        # 返済時刻３０分前に新規を停止し、実在する次の価格でのみ新規を再生する。
        if active is None and now>=next_allowed and now<limit-pd.Timedelta(minutes=30):
            fresh = signal_time is not None and now-signal_time<=pd.Timedelta(minutes=3)
            if decision and decision!=blocked_side and streak>=cfg.confirm and fresh and stale<=10 and np.isfinite(atr):
                side = int(decision)
                stop = op-side*3*atr
                stop = math.floor(stop/tick)*tick if side==1 else math.ceil(stop/tick)*tick
                active = dict(symbol=symbol, session=session, config=cfg.key, side=side, signal_time=signal_time,
                              entry_time=now, entry_price=float(op), atr=float(atr), stop=stop, peak=side*op,
                              exit_time=None, exit_price=None, closed=False, duration_min=None,
                              gross_points=None, reason="セッション途中の観測終了")
                if (side==1 and low<=stop) or (side==-1 and high>=stop):
                    px = min(op, stop) if side==1 else max(op, stop)
                    active.update(exit_time=now, exit_price=float(px), closed=True, reason="約定足の保護返済",
                                  duration_min=0.0, gross_points=side*(px-op))
                    trades.append(active)
                    active = None
                    next_allowed = now+pd.Timedelta(minutes=5)
                    blocked_side = side
                else:
                    active["peak"] = max(active["peak"], side*close)
                    proposed = side*(active["peak"]-cfg.trail*active["atr"])
                    proposed = math.floor(proposed/tick)*tick if side==1 else math.ceil(proposed/tick)*tick
                    active["stop"] = max(stop, proposed) if side==1 else min(stop, proposed)
    if active is not None:
        if one.index[-1]>=limit:
            raise AssertionError("完了セッションに未返済の建玉があります")
        trades.append(active)
    for trade in trades:
        if trade["closed"]:
            trade["net_points"] = trade["gross_points"]-2*tick
            trade["stress_points"] = trade["gross_points"]-4*tick
            trade["net_atr"] = trade["net_points"]/trade["atr"]
        trade.pop("peak", None)
        trade.pop("stop", None)
    return trades


def target_metrics(one: pd.DataFrame, trades: list[dict], symbol: str, session: str) -> list[dict]:
    """機能: ユーザー指定の波を時刻ラベルとして捕捉量を評価する。

    引数: one (DataFrame)、trades (list[dict])、symbol/session (str)。
    返り値: 検知遅延・時間捕捉・区間内価格差の採点 (list[dict])。検知器からは呼ばない。
    """
    if session not in ("2026-09-21_Day", "2026-09-22_Day"):
        return []
    date = session[:10]
    begin = pd.Timestamp(f"{date}T{'10:45' if date=='2026-09-21' else '09:20'}:00+09:00")
    end = pd.Timestamp(f"{date}T{'15:40' if date=='2026-09-21' else '11:45'}:00+09:00")
    side = 1 if date=="2026-09-21" else -1
    window = one[(one.index>=begin)&(one.index<end)]
    ref = side*(float(window.close.iloc[-1])-float(window.open.iloc[0]))
    minutes = (end-begin).total_seconds()/60
    correct, opposite, captured, hits = 0.0, 0.0, 0.0, []
    for trade in trades:
        t0, t1 = trade["entry_time"], trade["exit_time"] or one.index[-1]+pd.Timedelta(minutes=1)
        left, right = max(t0, begin), min(t1, end)
        if right<=left:
            continue
        duration = (right-left).total_seconds()/60
        if trade["side"]!=side:
            opposite += duration
            continue
        correct += duration
        segment = one[(one.index>=left)&(one.index<right)]
        if len(segment):
            start_price = trade["entry_price"] if left==t0 else float(segment.open.iloc[0])
            final_price = trade["exit_price"] if right==t1 else float(segment.close.iloc[-1])
            captured += side*(final_price-start_price)-2*TICKS[symbol]
        if duration>=20:
            hits.append(left)
    lag = min((t-begin).total_seconds()/60 for t in hits) if hits else None
    capture_ratio = captured/ref if ref>0 else 0.0
    passed = lag is not None and lag<=60 and correct/minutes>=0.6 and capture_ratio>=0.4
    return [dict(symbol=symbol, session=session, target_side=side, begin=begin, end=end,
                 reference_points=ref, detection_delay_min=lag, correct_coverage=correct/minutes,
                 opposite_coverage=opposite/minutes, captured_points=captured, capture_ratio=capture_ratio, passed=passed)]


def load_data(with_book: bool = True) -> dict:
    """機能: 保存済み３セッションを同じ形式で読み込む。

    引数: with_book (bool)。返り値: 足と特徴量の対応表 (dict)。
    """
    data = {}
    for session, symbol in itertools.product(SESSIONS, SYMBOLS):
        one = read_candle(ROOT/"candle_1min"/symbol/f"{session}.csv")
        five = read_candle(ROOT/"candle_5min"/symbol/f"{session}.csv")
        z = price_features(one, five, TICKS[symbol])
        if with_book:
            z = attach_book(z, OUT/f"板特徴_{symbol}_{session}.csv")
        data[(session, symbol)] = (one, z)
    return data


def evaluate(data: dict, cfg: Config) -> tuple[list, list, list]:
    """機能: 全セッションを再生し、指定波と全取引を分けて集計する。

    引数: data (dict)、cfg (Config)。返り値: 取引・指定波・セル集計 (tuple)。
    """
    all_trades, targets, cells = [], [], []
    for (session, symbol), (one, z) in data.items():
        peer = data[(session, "TOPIX" if symbol=="NK225" else "NK225")][1]
        trades = simulate(one, z, score(z, peer, cfg.family, cfg.threshold), cfg, symbol, session)
        all_trades.extend(trades)
        targets.extend(target_metrics(one, trades, symbol, session))
        closed = [t for t in trades if t["closed"]]
        pnl = [t["net_points"] for t in closed]
        equity = np.r_[0, np.cumsum(pnl)]
        cells.append(dict(config=cfg.key, session=session, symbol=symbol, count=len(trades),
                          closed=len(closed), net_points=sum(pnl), stress_points=sum(t["stress_points"] for t in closed),
                          net_atr=sum(t["net_atr"] for t in closed),
                          win_rate=sum(p>0 for p in pnl)/len(pnl) if pnl else None,
                          max_drawdown_points=float((np.maximum.accumulate(equity)-equity).max())))
    return all_trades, targets, cells


def search(price_only: bool = False) -> None:
    """機能: 価格と板の24系統864条件を比較し、指定波を満たす共通設定を選ぶ。

    引数: price_only (bool) は板抽出待ちの価格予備探索。返り値: なし (None)。
    """
    data = load_data(not price_only)
    families = list(range(1, 11))+[21, 22, 23, 24] if price_only else list(range(1, 25))
    if not price_only and any("book_present" not in z for _, z in data.values()):
        raise RuntimeError("板特徴量が６セッション分そろっていません")
    results, cell_rows, target_rows = [], [], []
    for family, threshold, confirm, trail, exit_multiplier in itertools.product(families, (0.25, 0.5, 0.75), (1, 3, 6), (4.0, 6.0), (1, 3)):
        cfg = Config(family, threshold, confirm, trail, exit_multiplier)
        trades, targets, cells = evaluate(data, cfg)
        good = sum(t["passed"] for t in targets)
        frequencies = [c["count"] for c in cells]
        worst_capture = min(t["capture_ratio"] for t in targets)
        worst_coverage = min(t["correct_coverage"] for t in targets)
        score_value = (2*good+min(worst_capture, 1)+worst_coverage+
                       0.03*np.mean([np.clip(c["net_atr"], -10, 10) for c in cells])-
                       0.08*np.mean([max(0, n-6)+max(0, 1-n) for n in frequencies]))
        results.append(dict(config=cfg.key, name=FAMILIES[family], **asdict(cfg), target_pass=good,
                            min_capture=worst_capture, min_coverage=worst_coverage,
                            max_opposite_coverage=max(t["opposite_coverage"] for t in targets),
                            min_count=min(frequencies), max_count=max(frequencies),
                            frequency_ok=all(1<=n<=6 for n in frequencies), count=len(trades), score=score_value))
        cell_rows.extend(cells)
        target_rows.extend(dict(config=cfg.key, **t) for t in targets)
    table = pd.DataFrame(results)
    table["neighborhood_median"] = table.groupby("family").score.transform("median")
    table["robust_score"] = 0.85*table.score+0.15*table.neighborhood_median
    table = table.sort_values(["target_pass", "frequency_ok", "max_opposite_coverage", "robust_score", "config"],
                              ascending=[False, False, True, False, True])
    prefix = "予備価格" if price_only else "比較"
    table.to_csv(OUT/f"{prefix}_全条件.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(cell_rows).to_csv(OUT/f"{prefix}_全セル.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(target_rows).to_csv(OUT/f"{prefix}_指定波.csv", index=False, encoding="utf-8-sig")
    best = table.iloc[0]
    cfg = Config(int(best.family), float(best.threshold), int(best.confirm), float(best.trail), int(best.exit_multiplier))
    trades, targets, cells = evaluate(data, cfg)
    for suffix, value in (("取引", trades), ("指定波", targets), ("集計", cells)):
        save_json(OUT/f"{prefix}_採用{suffix}.json", value)
    if not price_only:
        save_json(OUT/"固定設定.json", dict(config=asdict(cfg), name=FAMILIES[cfg.family],
                   fixed_at=pd.Timestamp.now(tz="Asia/Tokyo").isoformat(),
                   code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   note="指定された４波を含む全保存データで開発。未使用データ検証とは呼ばない。",
                   selection="４波合格数、全セル１〜６件、指定区間の逆方向保有率最小、近傍安定性込み得点の順。",
                   input_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in [*ROOT.glob('candle_1min/*/*.csv'), *ROOT.glob('candle_5min/*/*.csv'), *OUT.glob('板特徴_*.csv')]}))
    print(json.dumps(dict(設定=asdict(cfg), 指定波=targets, セッション=cells), ensure_ascii=False, default=str))


def main() -> None:
    """機能: 価格予備探索または価格・板の統合探索を実行する。

    引数: コマンドライン引数 (list[str])。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser(description="長時間波の価格・板比較")
    parser.add_argument("mode", choices=("price", "search"))
    args = parser.parse_args()
    search(args.mode=="price")


if __name__ == "__main__":
    main()
