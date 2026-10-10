"""保存済み先物足から継続波を検証する。外部通信と実注文は行わない。"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
SYMBOLS = ("NK225", "TOPIX")
TICKS = {"NK225": 10.0, "TOPIX": 0.5}
TRAIN = ("2026-09-21_Day", "2026-09-21_Night")
HOLDOUT = ("2026-09-22_Day",)
NAMES = {
    1: "移動平均の配列と傾き", 2: "過去高安値の突破", 3: "回帰傾きと決定係数",
    4: "方向効率と変位", 5: "ADXと方向指数", 6: "MACDと加速",
    7: "ボリンジャーバンド突破", 8: "ATR価格帯突破", 9: "RSIと価格の方向",
    10: "短期と長期の方向一致", 11: "両指数の方向一致", 12: "四条件の多数決",
}


@dataclass(frozen=True)
class Config:
    """機能: 検知設定を保持する。引数: 各フィールドの宣言型。返り値: Config。"""

    family: int
    strength: float
    confirm: int
    trail: float
    timeframe: int = 5
    cooldown: int = 20

    @property
    def key(self) -> str:
        """機能: 設定識別子を作る。

        引数: self (Config)。返り値: 設定識別子 (str)。
        """
        return f"{self.family:02d}_{self.strength:.1f}_{self.confirm}_{self.trail:.1f}_{self.timeframe}_{self.cooldown}"


def read_candles(path: Path) -> pd.DataFrame:
    """機能: 確定済みの足だけを読み込み、時刻順に並べる。

    引数: path (Path) は保存先。返り値: 時刻索引付き足 (DataFrame)。
    """
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"])
    df = df[df.closed.astype(str).str.lower().eq("true")].copy()
    if df.time.duplicated().any():
        raise ValueError(f"時刻重複: {path}")
    return df.set_index("time").sort_index()


def features_one(df: pd.DataFrame) -> pd.DataFrame:
    """機能: 一つの連続区間で過去と現在の確定足から特徴量を計算する。

    引数: df (DataFrame) は５分足。返り値: 特徴量 (DataFrame)。
    """
    c, h, l = df.close, df.high, df.low
    z = df.copy()
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    z["atr"] = tr.ewm(alpha=1/12, adjust=False, min_periods=12).mean()
    for n in (3, 4, 6, 8, 10, 12, 18):
        z[f"ema{n}"] = c.ewm(span=n, adjust=False, min_periods=n).mean()
    z["move6"] = (c-c.shift(6))/z.atr
    z["move12"] = (c-c.shift(12))/z.atr
    z["er"] = (c-c.shift(6)).abs()/c.diff().abs().rolling(6).sum().replace(0, np.nan)
    z["gap"] = (z.ema3-z.ema8)/z.atr
    z["slope"] = (z.ema8-z.ema8.shift(2))/z.atr
    z["hi6"] = h.rolling(6).max().shift()
    z["lo6"] = l.rolling(6).min().shift()
    z["mean12"] = c.rolling(12).mean()
    z["std12"] = c.rolling(12).std(ddof=0)
    x = np.arange(6, dtype=float)-2.5
    z["reg"] = c.rolling(6).apply(lambda a: np.dot(x, a)/np.dot(x, x), raw=True)
    z["r2"] = c.rolling(6).apply(
        lambda a: np.dot(x, a-a.mean())**2/(np.dot(x, x)*np.dot(a-a.mean(), a-a.mean()))
        if np.ptp(a) else 0.0, raw=True)
    up, down = h.diff(), -l.diff()
    plus = up.where((up>down)&(up>0), 0).ewm(alpha=1/12, adjust=False).mean()
    minus = down.where((down>up)&(down>0), 0).ewm(alpha=1/12, adjust=False).mean()
    z["di"] = (plus-minus)/(plus+minus).replace(0, np.nan)
    z["adx"] = (100*z.di.abs()).ewm(alpha=1/12, adjust=False, min_periods=12).mean()
    z["macd"] = (z.ema4-z.ema10)/z.atr
    z["hist"] = z.macd-z.macd.ewm(span=3, adjust=False).mean()
    gain = c.diff().clip(lower=0).ewm(alpha=1/6, adjust=False).mean()
    loss = (-c.diff().clip(upper=0)).ewm(alpha=1/6, adjust=False).mean()
    z["rsi"] = 100*gain/(gain+loss).replace(0, np.nan)
    z["age"] = np.arange(len(z))
    return z


def features(df: pd.DataFrame, timeframe: int = 5) -> pd.DataFrame:
    """機能: 欠測の前後を分離して特徴量を計算する。

    引数: df (DataFrame) は確定足、timeframe (int) は足の分数。返り値: 特徴量 (DataFrame)。
    """
    groups = df.index.to_series().diff().ne(pd.Timedelta(minutes=timeframe)).cumsum()
    return pd.concat([features_one(g) for _, g in df.groupby(groups)]) if len(df) else df.copy()


def signal(z: pd.DataFrame, other: pd.DataFrame, cfg: Config) -> pd.Series:
    """機能: 確定足だけからロング１・中立０・ショート−１を判定する。

    引数: z, other (DataFrame) は両指数の特徴量、cfg (Config) は設定。
    返り値: 売買方向 (Series)。
    """
    q = cfg.strength
    ema = np.sign(z.gap).where((z.gap.abs()>=0.20*q)&(z.slope*np.sign(z.gap)>0.08*q), 0)
    efficiency = np.sign(z.move6).where((z.er>=0.30*q)&(z.move6.abs()>=0.8*q), 0)
    regression = np.sign(z.reg).where((z.r2>=0.40*q)&((z.reg*5/z.atr).abs()>=0.75*q), 0)
    macd = np.sign(z.macd).where((z.macd.abs()>=0.20*q)&(z["hist"]*np.sign(z.macd)>0), 0)
    if cfg.family == 1:
        s = ema
    elif cfg.family == 2:
        s = pd.Series(np.where(z.close>z.hi6+(q-0.8)*0.25*z.atr, 1,
                     np.where(z.close<z.lo6-(q-0.8)*0.25*z.atr, -1, 0)), index=z.index)
    elif cfg.family == 3:
        s = regression
    elif cfg.family == 4:
        s = efficiency
    elif cfg.family == 5:
        s = np.sign(z.di).where((z.adx>=22*q)&(z.di.abs()>=0.15*q)&(z.move6*z.di>0), 0)
    elif cfg.family == 6:
        s = macd
    elif cfg.family == 7:
        distance = (z.close-z.mean12)/z.std12.replace(0, np.nan)
        s = np.sign(distance).where(distance.abs()>=1.3*q, 0)
    elif cfg.family == 8:
        distance = (z.close-z.ema8)/z.atr
        s = np.sign(distance).where((distance.abs()>=0.70*q)&(distance*z.slope>0), 0)
    elif cfg.family == 9:
        s = np.sign(z.rsi-50).where(((z.rsi-50).abs()>=12*q)&((z.rsi-50)*z.gap>0), 0)
    elif cfg.family == 10:
        s = np.sign(z.move6).where((z.move6*z.move12>0)&(z.move6.abs()>=0.70*q)&
                                  (z.move12.abs()>=1.0*q)&(z.er>=0.20*q), 0)
    elif cfg.family == 11:
        peer = other.reindex(z.index)
        s = efficiency.where((peer.move6*z.move6>0)&(peer.er>=0.25*q)&
                             (peer.move6.abs()>=0.6*q), 0)
    elif cfg.family == 12:
        votes = pd.concat([ema, efficiency, regression, macd], axis=1)
        s = pd.Series(np.where(votes.eq(1).sum(axis=1)>=3, 1,
                     np.where(votes.eq(-1).sum(axis=1)>=3, -1, 0)), index=z.index)
    else:
        raise ValueError("未知の検知系統")
    s = s.fillna(0).where((z.age>=17)&z.atr.notna(), 0).astype(int)
    if cfg.confirm == 2:
        s = s.where(s.eq(s.shift()), 0)
    return s


def session_end(index: pd.DatetimeIndex) -> pd.Timestamp:
    """機能: ザラ場終了５分前の固定時刻を返す。

    引数: index (DatetimeIndex) は単一セッション時刻。返り値: 決済期限 (Timestamp)。
    """
    first = index[0]
    if first.hour >= 16:
        return (first.normalize()+pd.Timedelta(days=1, hours=5, minutes=50))
    if first.hour < 7:
        return first.normalize()+pd.Timedelta(hours=5, minutes=50)
    return first.normalize()+pd.Timedelta(hours=15, minutes=35)


def label_wave(df: pd.DataFrame, when: pd.Timestamp, price: float, side: int, atr: float) -> dict:
    """機能: 検知後の持続を評価専用の未来区間で採点する。

    引数: df (DataFrame)、when (Timestamp)、price/atr (float)、side (int)。
    返り値: 30分持続と各時間の方向評価 (dict)。検知処理からは呼ばない。
    """
    result = {}
    for horizon in (5, 10, 20, 30, 60, 120):
        end = when+pd.Timedelta(minutes=horizon-1)
        future = df.loc[when:end]
        if len(future)==0 or df.index[-1]<end:
            result[f"forward{horizon}_atr"] = None
            result[f"wave{horizon}"] = None
            if horizon == 30:
                result.update(wave30=None, favorable_share30=None, mae30_atr=None, mfe30_atr=None)
            continue
        grid = pd.date_range(when, end, freq="min")
        closes = future.close.reindex(grid).ffill(limit=2)
        if closes.isna().any():
            result[f"forward{horizon}_atr"] = None
            result[f"wave{horizon}"] = None
            if horizon == 30:
                result.update(wave30=None, favorable_share30=None, mae30_atr=None, mfe30_atr=None)
            continue
        move = side*(closes-price)/atr
        result[f"forward{horizon}_atr"] = float(move.iloc[-1])
        mae = float(max(0, (price-future.low.min())/atr if side==1 else (future.high.max()-price)/atr))
        share = float((move>0).mean())
        result[f"wave{horizon}"] = bool(move.iloc[-1]>=0.5 and share>=0.6 and mae<=1.0)
        if horizon == 30:
            mfe = float(max(0, (future.high.max()-price)/atr if side==1 else (price-future.low.min())/atr))
            result.update(wave30=bool(move.iloc[-1]>=0.5 and share>=0.6 and mae<=1.0),
                          favorable_share30=share, mae30_atr=mae, mfe30_atr=mfe)
    return result


def backtest(df: pd.DataFrame, z: pd.DataFrame, directions: pd.Series, cfg: Config,
             symbol: str, session: str, labels: bool = True) -> list[dict]:
    """機能: 一分遅延・固定損切り・終値追跡による波イベントを再生する。

    引数: df/z (DataFrame)、directions (Series)、cfg (Config)、symbol/session (str)、labels (bool)。
    返り値: イベントと仮想売買記録 (list[dict])。価格単位の往復コストは後段で控除する。
    """
    # 検知足終了の１分後から次の観測足始値を使う。
    ready = z.index+pd.Timedelta(minutes=cfg.timeframe+1)
    risk_atr = z.risk_atr if "risk_atr" in z else z.atr
    schedule = {t: (int(s), float(a)) for t, s, a in zip(ready, directions, risk_atr)}
    schedule_times = list(schedule)
    cursor = 0
    active = None
    records = []
    latest_side = 0
    latest_atr = np.nan
    latest_time = None
    neutral_count = 0
    armed = {1: True, -1: True}
    cooldown = df.index[0]
    end = session_end(df.index)
    tick = TICKS[symbol]
    previous_time = None
    for row in df.itertuples():
        now, op, hi, lo, cl = row.Index, row.open, row.high, row.low, row.close
        while cursor<len(schedule_times) and schedule_times[cursor]<=now:
            latest_time = schedule_times[cursor]
            latest_side, latest_atr = schedule[latest_time]
            neutral_count = neutral_count+1 if latest_side==0 else 0
            if neutral_count>=2:
                armed = {1: True, -1: True}
            if latest_side!=0:
                armed[-latest_side] = True
            cursor += 1

        # ----------------------------------------
        # 先に存在する建玉を評価し、足内の順序が不明な極値で追跡幅を縮めない。
        if active is not None:
            age = (now-active["entry_time"]).total_seconds()/60
            side, stop = active["side"], active["stop"]
            reason, px = None, None
            if now>=end:
                reason, px = "時刻決済", op
            elif age>=120:
                reason, px = "120分経過", op
            elif latest_side==-side and age>=20:
                reason, px = "反対波", op
            elif previous_time is not None and now-previous_time>pd.Timedelta(minutes=3):
                reason, px = "観測間隔超過", op
            elif side==1 and lo<=stop:
                reason, px = "損切り・追跡", min(op, stop)
            elif side==-1 and hi>=stop:
                reason, px = "損切り・追跡", max(op, stop)
            if reason:
                active.update(exit_time=now, exit_price=float(px), reason=reason,
                              duration_min=age, gross_points=float(side*(px-active["entry_price"])), closed=True)
                records.append(active)
                cooldown = now+pd.Timedelta(minutes=cfg.cooldown)
                active = None
            else:
                active["peak"] = max(active["peak"], side*cl)
                proposed = side*(active["peak"]-cfg.trail*active["atr"])
                proposed = math.floor(proposed/tick)*tick if side==1 else math.ceil(proposed/tick)*tick
                active["stop"] = max(stop, proposed) if side==1 else min(stop, proposed)

        # ----------------------------------------
        # セッション末尾３０分と５分以上古い検知からの新規検知を除く。
        if active is None and now>=cooldown and now<end-pd.Timedelta(minutes=30):
            fresh = latest_time is not None and now-latest_time<=pd.Timedelta(minutes=2)
            if latest_side and armed[latest_side] and fresh and np.isfinite(latest_atr) and latest_atr>0:
                side = latest_side
                stop = op-side*1.5*latest_atr
                stop = math.floor(stop/tick)*tick if side==1 else math.ceil(stop/tick)*tick
                active = dict(symbol=symbol, session=session, config=cfg.key, side=side,
                              signal_time=latest_time-pd.Timedelta(minutes=1), entry_time=now,
                              entry_price=float(op), atr=latest_atr, stop=stop, peak=side*op,
                              closed=False, exit_time=None, exit_price=None, duration_min=None,
                              gross_points=None, reason="観測終了時点で継続中")
                armed[side] = False
                # 新規約定足も、事前に決めた損切りへの到達を確認する。
                hit = lo<=stop if side==1 else hi>=stop
                if hit:
                    px = min(op, stop) if side==1 else max(op, stop)
                    active.update(exit_time=now, exit_price=float(px), reason="約定足で損切り",
                                  duration_min=0.0, gross_points=float(side*(px-op)), closed=True)
                    records.append(active)
                    active = None
                    cooldown = now+pd.Timedelta(minutes=cfg.cooldown)
                else:
                    active["peak"] = max(active["peak"], side*cl)
                    proposed = side*(active["peak"]-cfg.trail*active["atr"])
                    proposed = math.floor(proposed/tick)*tick if side==1 else math.ceil(proposed/tick)*tick
                    active["stop"] = max(stop, proposed) if side==1 else min(stop, proposed)
        previous_time = now
    if active is not None:
        records.append(active)
    for rec in records:
        if labels:
            rec.update(label_wave(df, rec["entry_time"], rec["entry_price"], rec["side"], rec["atr"]))
        if rec["closed"]:
            rec["net_points"] = rec["gross_points"]-2*tick
            rec["stress_points"] = rec["gross_points"]-4*tick
            rec["net_atr"] = rec["net_points"]/rec["atr"]
            rec["stress_atr"] = rec["stress_points"]/rec["atr"]
        rec.pop("stop", None)
        rec.pop("peak", None)
    return records


def summary(records: list[dict]) -> dict:
    """機能: 検知品質とコスト感度を集計する。

    引数: records (list[dict]) はイベント。返り値: 集計値 (dict)。
    """
    if not records:
        return dict(count=0, closed=0, label_count=0, wave_rate=None, mean_net_atr=0.0,
                    mean_stress_atr=0.0, net_points=0.0, stress_points=0.0, win_rate=None,
                    median_duration=None, hold20_rate=None, profit_factor=None, max_drawdown_points=0.0)
    d = pd.DataFrame(records)
    c = d[d.closed]
    w = d.wave30.dropna() if "wave30" in d else pd.Series(dtype=float)
    pnl = c.net_points if len(c) else pd.Series(dtype=float)
    equity = np.r_[0, pnl.cumsum().to_numpy()]
    losses = -pnl[pnl<0].sum()
    result = dict(count=len(d), closed=len(c), label_count=len(w), wave_rate=float(w.mean()) if len(w) else None,
                mean_net_atr=float(c.net_atr.mean()) if len(c) else 0.0,
                mean_stress_atr=float(c.stress_atr.mean()) if len(c) else 0.0,
                net_points=float(pnl.sum()), stress_points=float(c.stress_points.sum()) if len(c) else 0.0,
                win_rate=float((pnl>0).mean()) if len(c) else None,
                median_duration=float(c.duration_min.median()) if len(c) else None,
                hold20_rate=float((c.duration_min>=20).mean()) if len(c) else None,
                profit_factor=float(pnl[pnl>0].sum()/losses) if losses else None,
                max_drawdown_points=float((np.maximum.accumulate(equity)-equity).max()))
    if d.symbol.nunique()>1:
        for key in ("net_points", "stress_points", "profit_factor", "max_drawdown_points"):
            result[key] = None
    return result


def make_bars(one: pd.DataFrame, native_five: pd.DataFrame, timeframe: int) -> pd.DataFrame:
    """機能: 観測のない短い区間のみ直前終値で補完し、指定時間軸を生成する。

    引数: one/native_five (DataFrame)、timeframe (int)。返り値: 確定足 (DataFrame)。
    補完足は特徴量専用であり、約定の再生には渡さない。
    """
    if timeframe==5:
        return native_five.copy()
    grid = pd.date_range(one.index[0], one.index[-1], freq="min")
    expanded = one.reindex(grid)
    filled_close = expanded.close.ffill(limit=2)
    for col in ("open", "high", "low", "close"):
        expanded[col] = expanded[col].fillna(filled_close)
    expanded["volume"] = expanded.volume.fillna(0)
    grouped = expanded.resample(f"{timeframe}min", origin=one.index[0])
    bars = grouped.agg(dict(open="first", high="max", low="min", close="last", volume="sum"))
    counts = grouped.close.count()
    bars = bars[counts.eq(timeframe)]
    bars = bars[bars.index+pd.Timedelta(minutes=timeframe)<=one.index[-1]+pd.Timedelta(minutes=1)]
    bars["closed"] = True
    return bars


def load_sessions(sessions: tuple[str, ...], timeframe: int = 5) -> dict:
    """機能: 指定した保存済みセッションだけを読み込む。

    引数: sessions (tuple[str, ...])、timeframe (int)。返り値: 足と特徴量の対応表 (dict)。
    """
    data = {}
    for session, symbol in itertools.product(sessions, SYMBOLS):
        one = read_candles(ROOT/"candle_1min"/symbol/f"{session}.csv")
        five = read_candles(ROOT/"candle_5min"/symbol/f"{session}.csv")
        bars = make_bars(one, five, timeframe)
        z = features(bars, timeframe)
        reference = features(five).atr.copy()
        reference.index += pd.Timedelta(minutes=5)
        decision_times = z.index+pd.Timedelta(minutes=timeframe)
        z["risk_atr"] = reference.reindex(decision_times, method="ffill", tolerance=pd.Timedelta(minutes=5)).to_numpy()
        data[(session, symbol)] = (one, z)
    return data


def evaluate(data: dict, cfg: Config) -> tuple[list[dict], list[dict]]:
    """機能: 一つの設定を両指数・指定セッションで再生する。

    引数: data (dict) は足、cfg (Config) は設定。返り値: イベントと集計の組 (tuple)。
    """
    records, rows = [], []
    for (session, symbol), (one, z) in data.items():
        peer = "TOPIX" if symbol=="NK225" else "NK225"
        directions = signal(z, data[(session, peer)][1], cfg)
        r = backtest(one, z, directions, cfg, symbol, session)
        records.extend(r)
        rows.append(dict(config=cfg.key, family=cfg.family, name=NAMES[cfg.family],
                         strength=cfg.strength, confirm=cfg.confirm, trail=cfg.trail, timeframe=cfg.timeframe, cooldown=cfg.cooldown,
                         session=session, symbol=symbol, **summary(r)))
    return records, rows


def write_json(path: Path, value: object) -> None:
    """機能: 日本語を保持して検証結果を保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8")


def train() -> None:
    """機能: 864設定を開発データだけで比較し、共通設定を凍結する。

    引数: なし。返り値: なし (None)。評価用データと現在セッションにはアクセスしない。
    """
    datasets = {t: load_sessions(TRAIN, t) for t in (1, 5, 10)}
    rows, rankings = [], []
    configs = [Config(*v) for v in itertools.product(range(1, 13), (0.8, 1.0, 1.2), (1, 2), (1.5, 2.5), (1, 5, 10), (20, 60))]
    for cfg in configs:
        rec, cells = evaluate(datasets[cfg.timeframe], cfg)
        rows.extend(cells)
        n = [x["count"] for x in cells]
        precision = [(x["wave_rate"] or 0) for x in cells]
        stress = [x["mean_stress_atr"] for x in cells]
        freq_penalty = sum(max(0, 2-k)+max(0, k-6) for k in n)/len(n)
        score = (0.60*np.mean(precision)+0.20*min(precision)+0.20*np.mean(np.clip(stress, -2, 2))
                 -0.12*freq_penalty)
        rankings.append(dict(config=cfg.key, **asdict(cfg), name=NAMES[cfg.family], score=float(score),
                             min_count=min(n), max_count=max(n), frequency_ok=all(2<=k<=6 for k in n),
                             **summary(rec)))
    table = pd.DataFrame(rankings)
    # ----------------------------------------
    # 個別の最高値より、同じ系統の閾値近傍でも崩れにくい設定を優先する。
    table["family_median"] = table.groupby(["family", "timeframe"]).score.transform("median")
    table["robust_score"] = 0.7*table.score+0.3*table.family_median
    feasible = table[table.frequency_ok]
    ranked = (feasible if len(feasible) else table).sort_values(["robust_score", "config"], ascending=[False, True])
    choice = ranked.iloc[0]
    cfg = Config(int(choice.family), float(choice.strength), int(choice.confirm), float(choice.trail), int(choice.timeframe), int(choice.cooldown))
    table.sort_values("robust_score", ascending=False).to_csv(OUT/"開発_全864条件.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(rows).to_csv(OUT/"開発_セッション別.csv", index=False, encoding="utf-8-sig")
    selected_records, selected_rows = evaluate(datasets[cfg.timeframe], cfg)
    write_json(OUT/"開発_採用条件_イベント.json", selected_records)
    write_json(OUT/"開発_採用条件_集計.json", selected_rows)
    family_best = table.sort_values("robust_score", ascending=False).groupby("family", sort=True).head(1)
    family_best.sort_values("family").to_csv(OUT/"開発_12系統代表.csv", index=False, encoding="utf-8-sig")
    time_best = table.sort_values("robust_score", ascending=False).groupby("timeframe", sort=True).head(1)
    time_best.sort_values("timeframe").to_csv(OUT/"開発_時間軸代表.csv", index=False, encoding="utf-8-sig")
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for s, symbol in itertools.product(TRAIN, SYMBOLS)
              for p in [ROOT/"candle_1min"/symbol/f"{s}.csv", ROOT/"candle_5min"/symbol/f"{s}.csv"]}
    write_json(OUT/"凍結設定.json", dict(config=asdict(cfg), name=NAMES[cfg.family],
               train=TRAIN, holdout=HOLDOUT, candidates=len(configs), frequency_feasible=len(feasible),
               frozen_at=pd.Timestamp.now(tz="Asia/Tokyo").isoformat(),
               code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), input_sha256=hashes,
               selection="各銘柄・セッションの検知２〜６件を優先。持続成功率、最悪セル成功率、４ティック控除後ATR損益、頻度逸脱、系統内中央値で選択。",
               label="30分後が0.5ATR以上順行、30分中60%以上の分末終値が順行、最大逆行1ATR以下。",
               entry_delay_minutes=1, roundtrip_ticks=2, stress_roundtrip_ticks=4,
               initial_stop_atr=1.5, max_hold_minutes=120, cooldown_minutes=cfg.cooldown))
    print(json.dumps(dict(採用=asdict(cfg), 名称=NAMES[cfg.family], 頻度条件合致=len(feasible),
                          開発集計=selected_rows), ensure_ascii=False, default=str))


def holdout() -> None:
    """機能: 凍結設定と事前に選んだ12系統代表を未使用データで評価する。

    引数: なし。返り値: なし (None)。結果による設定変更は行わない。
    """
    frozen = json.loads((OUT/"凍結設定.json").read_text(encoding="utf-8"))
    cfg = Config(**frozen["config"])
    datasets = {t: load_sessions(HOLDOUT, t) for t in (1, 5, 10)}
    data = datasets[cfg.timeframe]
    rec, rows = evaluate(data, cfg)
    write_json(OUT/"未使用日_イベント.json", rec)
    write_json(OUT/"未使用日_集計.json", rows)
    other_rows = []
    for r in pd.read_csv(OUT/"開発_12系統代表.csv").itertuples():
        _, cells = evaluate(datasets[r.timeframe], Config(r.family, r.strength, r.confirm, r.trail, r.timeframe, r.cooldown))
        other_rows.extend(cells)
    pd.DataFrame(other_rows).to_csv(OUT/"未使用日_12系統比較.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(rows, ensure_ascii=False, default=str))


def main() -> None:
    """機能: 開発または未使用日の評価を実行する。

    引数: コマンドライン (list[str])。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser(description="保存済み足による継続波の検証")
    parser.add_argument("mode", choices=["train", "holdout"])
    args = parser.parse_args()
    train() if args.mode=="train" else holdout()


if __name__ == "__main__":
    main()
