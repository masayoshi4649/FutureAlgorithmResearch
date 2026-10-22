"""確定足・解放済み板から、事前固定した54条件の機械的方向を生成する。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SYMBOLS = ("NK225", "TOPIX")
_BAR_CACHE: dict = {}
_BOARD_CACHE: dict = {}


def catalog() -> list[dict]:
    """機能: 損益の参照前に固定した条件一覧を返す。

    引数: なし。
    返り値: ID・日本語説明・系統・数値条件を持つ一覧 (list[dict])。
    """
    definitions = [
        ("EMA短期順張り", "移動平均", "EMA5/20の間隔と長期線の傾きが一致した方向へ進む。弱まれば中立に戻す。", {"kind": "ema", "fast": 5, "slow": 20, "gap": .12, "slope": .02}),
        ("EMA中期順張り", "移動平均", "EMA8/30の間隔と長期線の傾きが一致した方向へ進む。弱まれば中立に戻す。", {"kind": "ema", "fast": 8, "slow": 30, "gap": .15, "slope": .03}),
        ("EMA長期順張り", "移動平均", "EMA15/60が示す大きな流れに従い、細かな往復を避ける。", {"kind": "ema", "fast": 15, "slow": 60, "gap": .20, "slope": .02}),
        ("高安突破15分", "高安突破", "直前15本の高安を終値で突破した方向へ進み、帯中央を逆に割ると中立化する。", {"kind": "donchian", "window": 15, "buffer": .05}),
        ("高安突破30分", "高安突破", "直前30本の高安を終値で突破した方向へ進み、帯中央を逆に割ると中立化する。", {"kind": "donchian", "window": 30, "buffer": .05}),
        ("高安突破60分", "高安突破", "直前60本の高安を終値で突破した方向へ進み、帯中央を逆に割ると中立化する。", {"kind": "donchian", "window": 60, "buffer": .05}),
        ("価格差15分順張り", "価格差", "15本前から0.5ATR以上動いた方向へ進む。", {"kind": "momentum", "window": 15, "threshold": .5}),
        ("価格差30分順張り", "価格差", "30本前から0.75ATR以上動いた方向へ進む。", {"kind": "momentum", "window": 30, "threshold": .75}),
        ("価格差60分順張り", "価格差", "60本前から1ATR以上動いた方向へ進む。", {"kind": "momentum", "window": 60, "threshold": 1.0}),
        ("効率比で順張り限定", "相場切替", "30本の効率比が0.30以上なら流れに従い、往復が多ければ新規を止める。", {"kind": "regime", "window": 30, "er_trend": .30, "er_range": .15, "range": False}),
        ("効率比で順逆切替", "相場切替", "効率比0.30以上では順張り、0.15以下ではVWAPから1ATR離れた反転だけ逆張りする。", {"kind": "regime", "window": 30, "er_trend": .30, "er_range": .15, "range": True}),
        ("VWAP方向追随", "出来高平均", "当日VWAPの上下とEMA8/30の方向が一致するときだけ順張りする。", {"kind": "vwap_trend", "deviation": .15}),
        ("VWAP押し戻り", "押し目戻り", "流れとVWAP方向が一致し、EMA8近辺まで戻ってから3本差分が再び順方向になれば入る。", {"kind": "pullback", "distance": .6}),
        ("低効率レンジ回帰", "レンジ回帰", "効率比0.20以下に限定し、VWAPから1ATR離れた後の短期反転を狙う。", {"kind": "range", "window": 30, "er_range": .20, "deviation": 1.0}),
        ("高安突破失敗20分", "突破失敗", "過去20本の外へ出たのに終値が帯内へ戻ったとき、強いトレンドを避けて逆方向を3分候補にする。", {"kind": "failed", "window": 20, "max_er": .40, "ttl": 3}),
        ("高安突破失敗40分", "突破失敗", "過去40本の外へ出たのに終値が帯内へ戻ったとき、強いトレンドを避けて逆方向を3分候補にする。", {"kind": "failed", "window": 40, "max_er": .40, "ttl": 3}),
        ("収縮後の拡大20分", "収縮拡大", "20本標準偏差が過去60本中央値の0.7倍未満へ縮んだ後、10本高安を突破した方向を狙う。", {"kind": "squeeze", "window": 20, "ratio": .7, "ttl": 20}),
        ("収縮後の拡大30分", "収縮拡大", "30本標準偏差が過去60本中央値の0.8倍未満へ縮んだ後、10本高安を突破した方向を狙う。", {"kind": "squeeze", "window": 30, "ratio": .8, "ttl": 30}),
        ("適応平均20分", "適応平均", "効率比で平均線の反応速度を変え、価格位置と平均線の傾きが一致した方向へ進む。", {"kind": "kama", "window": 20, "fast": 2, "slow": 30, "gap": .15}),
        ("適応平均40分", "適応平均", "40本効率比で平均線の反応速度を変え、大きな流れが続く間は順張りする。", {"kind": "kama", "window": 40, "fast": 2, "slow": 40, "gap": .20}),
        ("累積変化1ATR", "累積変化", "毎分の変化から0.05ATRの雑音分を引き、累積1ATRに達した方向を30分間候補にする。", {"kind": "cusum", "threshold": 1.0, "drift": .05, "ttl": 30}),
        ("累積変化2ATR", "累積変化", "毎分の変化から0.05ATRの雑音分を引き、累積2ATRに達した方向を60分間候補にする。", {"kind": "cusum", "threshold": 2.0, "drift": .05, "ttl": 60}),
        ("開始30分レンジ突破", "開始範囲", "開始30分間の高安が確定してから、その外側にいる方向へ順張りする。", {"kind": "opening", "window": 30, "buffer": .05}),
        ("開始60分レンジ突破", "開始範囲", "開始60分間の高安が確定してから、その外側にいる方向へ順張りする。", {"kind": "opening", "window": 60, "buffer": .05}),
        ("両銘柄EMA一致", "両銘柄一致", "自銘柄と60秒遅延した相手のEMA8/30が一致した方向へ進む。不一致では中立に戻す。", {"kind": "dual", "mode": "ema", "peer_delay": 60}),
        ("両銘柄価格差一致", "両銘柄一致", "両銘柄の30本差分が各0.75ATR以上で同方向のときだけ進む。相手は60秒遅延する。", {"kind": "dual", "mode": "momentum", "peer_delay": 60}),
        ("NK先行の追随", "先行銘柄", "60秒前のNKのEMA方向に追随し、自銘柄の3本差分が同方向になってから候補にする。", {"kind": "leader", "leader": "NK225", "peer_delay": 60}),
        ("TOPIX先行の追随", "先行銘柄", "60秒前のTOPIXのEMA方向に追随し、自銘柄の3本差分が同方向になってから候補にする。", {"kind": "leader", "leader": "TOPIX", "peer_delay": 60}),
        ("板OFIと価格2分", "板OFI", "解放済み2分間OFIの偏り0.05以上と気配価格の変化が一致した方向へ進む。", {"kind": "ofi", "seconds": 120, "threshold": .05}),
        ("板OFIと価格5分", "板OFI", "解放済み5分間OFIの偏り0.05以上と気配価格の変化が一致した方向へ進む。", {"kind": "ofi", "seconds": 300, "threshold": .05}),
        ("気配更新の方向", "気配移動", "2分間の気配上下更新の偏り0.10以上と、気配価格の変化が一致した方向へ進む。", {"kind": "quote", "seconds": 120, "threshold": .10}),
        ("板5段の偏り", "板厚み", "2分間平均の5段板偏り0.15以上と、気配価格の変化が一致した方向へ進む。", {"kind": "depth", "seconds": 120, "threshold": .15}),
        ("最良板の加重気配", "加重気配", "2分間平均の最良数量による加重気配偏差0.06以上と価格変化が一致した方向へ進む。論文の学習型micropriceとは異なる。", {"kind": "weighted", "seconds": 120, "threshold": .06}),
        ("板OFIと中期線一致", "板足一致", "5分OFI・気配価格変化・EMA8/30の三つが一致するときだけ進む。", {"kind": "ofi_trend", "seconds": 300, "threshold": .05}),
        ("両銘柄OFI一致", "板銘柄一致", "自銘柄と60秒遅延した相手の5分OFI・価格方向が一致するときだけ進む。", {"kind": "ofi_peer", "seconds": 300, "threshold": .05, "peer_delay": 60}),
        ("三系統の多数決", "複数手法", "EMA8/30、30分価格差、30分高安突破のうち二つ以上が一致した方向へ進む。", {"kind": "ensemble", "votes": 2}),
        ("長期流れ内の短期回帰", "逆張り制限", "EMA15/60の順方向だけ許可し、EMA8/30が一時的に逆方向へ戻った場面の短期反転を拾う。", {"kind": "guarded_reversion", "fast_return": 3}),
        ("長短価格差の一致", "複数時間軸", "15分差分0.5ATRと60分差分1ATRが同方向に揃ったときだけ進む。", {"kind": "multi_momentum", "short": 15, "long": 60, "short_threshold": .5, "long_threshold": 1.0}),
        ("フローの継続追随", "フロー持続", "2分OFIと推定売買が同方向で、60秒前・120秒前から偏りが続くとき、継続方向へ入る。", {"kind": "persistent", "seconds": 120, "threshold": .03, "trade_threshold": .10}),
        ("大フローの吸収反転", "吸収反転", "5分OFIと推定売買が偏っているのに価格進行が0.35ATR以下なら吸収候補とし、30秒の反転を待つ。", {"kind": "absorption", "seconds": 300, "threshold": .08, "trade_threshold": .10, "max_progress": .35}),
        ("板補充による吸収", "補充吸収", "推定買いが多い側の売り板補充、または推定売りが多い側の買い板補充と価格停滞を検知し、反転を待つ。", {"kind": "replenishment", "seconds": 300, "threshold": .10, "max_progress": .35, "refill_ratio": .5}),
        ("フロー応答の鈍化", "価格応答残差", "過去30分の通常の価格応答と比べ、強い5分OFIの価格進行が0.25ATR以上鈍くなり短期反転した方向へ入る。", {"kind": "response", "seconds": 300, "threshold": .08, "residual": .25, "reference_seconds": 1800}),
        ("近い板の変化追随", "距離重み変化", "最良価格からの距離に応じて重みを減らした2分の板数量変化と気配価格が同方向なら入る。", {"kind": "distance_near", "seconds": 120, "threshold": .05}),
        ("遠い板からの先行圧力", "距離別先行", "遠めの板の偏りが続き、近い板も同方向へ変化し始めたが価格進行はまだ小さい場面を拾う。", {"kind": "distance_far", "seconds": 120, "threshold": .05, "max_progress": .35}),
        ("同価格の補充壁", "同価格補充", "直前30秒の減少を埋めた補充が一方へ偏り、その側を背に価格が反発したら入る。", {"kind": "refill_wall", "seconds": 120, "threshold": .20}),
        ("近遠の板圧力差", "板の傾斜", "近い板の偏りが遠い板より0.10以上強く、近い板の変化と価格も同方向なら入る。", {"kind": "pressure_gradient", "seconds": 120, "threshold": .10}),
        ("相手板の先行を追随", "板の銘柄先行", "60秒前の相手の2分OFI・価格方向に対し、自銘柄も3本差分が同方向になった場面を拾う。", {"kind": "board_leader", "seconds": 120, "threshold": .05, "peer_delay": 60}),
        ("蓄積フローの反転", "蓄積解消候補", "直前までの30分推定売買が一方へ偏っていた後、2分の推定売買と価格が反対へ揃う場面を拾う。返済取引とは断定しない。", {"kind": "flow_reversal", "seconds": 120, "threshold": .15, "history_seconds": 1800, "prior_threshold": .20}),
        ("少量で動く板の脆弱性", "流動性脆弱性", "推定売買量当たりの価格進行が過去30分の通常時より1.5倍大きく、OFIも同方向なら薄い側への進行に従う。", {"kind": "fragility", "seconds": 120, "threshold": .03, "impact_ratio": 1.5, "min_progress": .25}),
        ("衝撃後の板回復と反転", "衝撃回復", "60秒で0.75ATR動いた後、最良両側数量が60秒前の1.25倍以上へ戻り、30秒価格が反転した方向を拾う。", {"kind": "shock_recover", "seconds": 120, "threshold": .03, "shock_atr": .75, "depth_ratio": 1.25}),
        ("衝撃後の板不足と継続", "衝撃継続", "60秒で0.75ATR動き、最良両側数量が60秒前の0.8倍以下でOFIも同方向なら継続を狙う。", {"kind": "shock_continue", "seconds": 120, "threshold": .03, "shock_atr": .75, "depth_ratio": .8}),
        ("更新2000回のフロー", "イベント時間", "時計の2分ではなく原本更新約2000回に対応する解放済みブロックでOFIを集計し、価格と一致した方向へ進む。", {"kind": "event_clock", "seconds": 120, "threshold": .05, "events": 2000}),
        ("両市場の売買と板枯渇", "市場共通圧力", "両市場で推定売買とOFIが同方向に続き、反対板の除去・同方向板の追加と価格進行まで一致した側へ進む。売りなら買い板の支えが減る場面。", {"kind": "market_consensus", "seconds": 300, "threshold": .03, "trade_threshold": .10, "supply_threshold": .02, "peer_delay": 60}),
        ("両市場の吸収と方向転換", "市場吸収切替", "片方の売りが吸収され始めたら共通売りを止める。両市場で買いへの転換が揃う、または一方の吸収反転を他方の買い圧力が裏付けた場合だけ買う。売りも対称。", {"kind": "market_absorption", "seconds": 300, "threshold": .03, "trade_threshold": .10, "supply_threshold": .02, "max_progress": .35, "peer_delay": 60}),
    ]
    return [{"id": f"F{i:02d}", "name": name, "family": family, "description": description,
             "params": {**params, "minute_release_seconds": 120, "warmup_minutes": 20}}
            for i, (name, family, description, params) in enumerate(definitions)]


def clear_cache() -> None:
    """機能: 入力変更を伴う監査用に計算済み中間値を解放する。

    引数: なし。
    返り値: なし (None)。
    """
    _BAR_CACHE.clear()
    _BOARD_CACHE.clear()


def _expand(events: np.ndarray, values: np.ndarray, targets: np.ndarray, initial: float = 0) -> np.ndarray:
    """機能: 公開済み最後の値だけを対象時刻または行番号へ展開する。

    引数: events/targets (ndarray)、values (ndarray)、initial (float) は初期値。
    返り値: targets と同じ長さの値列 (ndarray)。
    """
    output = np.full(len(targets), initial, dtype=values.dtype)
    positions = np.searchsorted(events, targets, side="right") - 1
    valid = positions >= 0
    output[valid] = values[positions[valid]]
    return output


def _signed(value: np.ndarray | pd.Series, threshold: float = 0) -> np.ndarray:
    """機能: 正負の対称な閾値を超えた値だけを方向化する。

    引数: value (ndarray|Series)、threshold (float) は絶対値の下限。
    返り値: -1/0/1 の方向列 (ndarray[int8])。欠損値は中立。
    """
    values = np.asarray(value, dtype=float)
    return np.where(values > threshold, 1, np.where(values < -threshold, -1, 0)).astype(np.int8)


def _confirm(candidate: np.ndarray, times: np.ndarray, count: int = 2) -> np.ndarray:
    """機能: 連続した確定足で同方向を確認し、弱まりでは直ちに中立化する。

    引数: candidate (ndarray[int8])、times (ndarray)、count (int) は必要確認数。
    返り値: 確認済み方向列 (ndarray[int8])。
    """
    output = np.zeros(len(candidate), dtype=np.int8)
    previous, run, last = 0, 0, -np.inf
    for i, (direction, stamp) in enumerate(zip(candidate, times)):
        if stamp - last > 90:
            previous, run = 0, 0
        run = run + 1 if direction != 0 and direction == previous else int(direction != 0)
        output[i] = direction if run >= count else 0
        previous, last = direction, stamp
    return output


def _efficiency(close: pd.Series, window: int) -> pd.Series:
    """機能: 純変化を総移動距離で割り、過去窓だけの効率比を計算する。

    引数: close (Series[float])、window (int) は本数。
    返り値: 0〜1の効率比 (Series[float])。初期不足は欠損。
    """
    distance = close.diff().abs().rolling(window, min_periods=window).sum()
    return close.diff(window).abs() / distance.replace(0, np.nan)


def _bars(ready: dict) -> dict:
    """機能: 入力末尾までに公開された確定1分足と基本指標を作る。

    引数: ready (dict) は原本行を途中切断可能な評価入力。
    返り値: 公開時刻・終値・高安・出来高平均・ATRの辞書 (dict)。
    """
    cache_key = (id(ready), id(ready["atr"]), len(ready["seq"]), int(ready["seq"][-1]), float(ready["time_s"][-1]))
    if cache_key in _BAR_CACHE:
        return _BAR_CACHE[cache_key]
    frame = pd.read_csv(ROOT / "candle_1min" / ready["symbol"] / f"{ready['session']}.csv")
    available = pd.to_datetime(frame.time).dt.as_unit("ns").astype("int64").to_numpy(float) / 1e9 + 120
    valid = frame.closed.astype(str).str.lower().eq("true").to_numpy(copy=True)
    valid &= (available >= ready["start"] + 120) & (available <= ready["time_s"][-1])
    frame = frame.loc[valid].reset_index(drop=True)
    available = available[valid]
    if not np.all(np.diff(available) > 0):
        raise ValueError("1分足公開時刻の並びが不正です")
    close = frame.close.astype(float)
    high, low = frame.high.astype(float), frame.low.astype(float)
    volume = frame.volume.astype(float).clip(lower=0)
    if "volume_complete" in frame:
        volume = volume.where(frame.volume_complete.astype(str).str.lower().eq("true"), 0.0)
    numerator = ((high + low + close) / 3 * volume).cumsum()
    vwap = numerator / volume.cumsum().replace(0, np.nan)
    atr = _expand(ready["time_s"], np.asarray(ready["atr"], float), available, np.nan)
    result = {"time_s": available, "close": close, "high": high, "low": low, "volume": volume,
              "vwap": vwap, "atr": atr, "start": ready["start"], "er30": _efficiency(close, 30)}
    _BAR_CACHE[cache_key] = result
    return result


def _ema(model: dict, fast: int = 8, slow: int = 30, gap: float = .15, slope: float = .03) -> np.ndarray:
    """機能: EMA間隔と長期線傾きの同方向を二本確認する。

    引数: model (dict)、fast/slow (int)、gap/slope (float) はATR比閾値。
    返り値: 公開確定足ごとの方向 (ndarray[int8])。
    """
    close, atr = model["close"], model["atr"]
    short = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
    long = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
    d1 = _signed((short - long) / atr, gap)
    d2 = _signed(long.diff(3) / atr, slope)
    return _confirm(np.where(d1 == d2, d1, 0).astype(np.int8), model["time_s"])


def _hold(trigger: np.ndarray, release: np.ndarray | None = None, ttl: int = 0) -> np.ndarray:
    """機能: 発生した方向を失効条件または指定本数まで維持する。

    引数: trigger (ndarray[int8])、release (ndarray|None) は逆符号で解除、ttl (int) は有効本数。
    返り値: 各確定足の方向 (ndarray[int8])。
    """
    output = np.zeros(len(trigger), dtype=np.int8)
    state, age = 0, 0
    for i, value in enumerate(trigger):
        age += 1
        if value:
            state, age = int(value), 0
        elif state and ((ttl and age >= ttl) or (release is not None and release[i] * state < 0)):
            state = 0
        output[i] = state
    return output


def _donchian(model: dict, window: int, buffer: float = .05) -> np.ndarray:
    """機能: 現在足を除く高安突破を検知し、帯中央への逆行で解除する。

    引数: model (dict)、window (int)、buffer (float) は突破余白のATR比。
    返り値: 各確定足の方向 (ndarray[int8])。
    """
    upper = model["high"].shift(1).rolling(window, min_periods=window).max()
    lower = model["low"].shift(1).rolling(window, min_periods=window).min()
    trigger = np.where(model["close"] > upper + buffer * model["atr"], 1,
                       np.where(model["close"] < lower - buffer * model["atr"], -1, 0)).astype(np.int8)
    return _hold(trigger, _signed(model["close"] - (upper + lower) / 2))


def _minute_signal(params: dict, model: dict) -> np.ndarray:
    """機能: 一銘柄の確定足だけから指定思想の候補方向を作る。

    引数: params (dict) は固定数値条件、model (dict) は公開済み足。
    返り値: 確定足各時点の方向 (ndarray[int8])。
    """
    kind = params["kind"]
    close, high, low, atr = model["close"], model["high"], model["low"], model["atr"]
    er, vwap = model["er30"], model["vwap"]
    n = len(close)
    if kind == "ema":
        return _ema(model, params["fast"], params["slow"], params["gap"], params["slope"])
    if kind == "donchian":
        return _donchian(model, params["window"], params["buffer"])
    if kind == "momentum":
        return _signed(close.diff(params["window"]) / atr, params["threshold"])
    if kind in ("regime", "range"):
        er = _efficiency(close, params["window"])
        trend = _signed(close.diff(params["window"]) / atr, .5)
        deviation = _signed((close - vwap) / atr, params.get("deviation", 1.0))
        rebound = _signed(close.diff(3))
        revert = np.where((rebound == -deviation) & (er <= params["er_range"]), rebound, 0)
        if kind == "range":
            return revert.astype(np.int8)
        return np.where(er >= params["er_trend"], trend, revert if params["range"] else 0).astype(np.int8)
    if kind == "vwap_trend":
        trend = _ema(model)
        side = _signed((close - vwap) / atr, params["deviation"])
        return np.where(trend == side, trend, 0).astype(np.int8)
    if kind == "pullback":
        trend = _ema(model)
        ema = close.ewm(span=8, adjust=False, min_periods=8).mean()
        nearby = ((close - ema) / atr).abs() <= params["distance"]
        good = nearby & (_signed(close.diff(3)) == trend) & (_signed(close - vwap) == trend)
        return np.where(good, trend, 0).astype(np.int8)
    if kind == "failed":
        upper = high.shift(1).rolling(params["window"]).max()
        lower = low.shift(1).rolling(params["window"]).min()
        buy = (low < lower) & (close > lower) & (close.diff() > 0)
        sell = (high > upper) & (close < upper) & (close.diff() < 0)
        trigger = np.where((er <= params["max_er"]) & buy, 1,
                           np.where((er <= params["max_er"]) & sell, -1, 0)).astype(np.int8)
        return _hold(trigger, ttl=params["ttl"])
    if kind == "squeeze":
        width = close.rolling(params["window"]).std(ddof=0)
        reference = width.shift(1).rolling(60, min_periods=30).median()
        squeezed = (width < reference * params["ratio"]).shift(1).rolling(10).max().fillna(0) > 0
        upper, lower = high.shift(1).rolling(10).max(), low.shift(1).rolling(10).min()
        trigger = np.where(squeezed & (close > upper + .05 * atr), 1,
                           np.where(squeezed & (close < lower - .05 * atr), -1, 0)).astype(np.int8)
        release = _signed(close - close.ewm(span=20, adjust=False, min_periods=20).mean())
        return _hold(trigger, release, ttl=params["ttl"])
    if kind == "kama":
        efficiency = _efficiency(close, params["window"]).to_numpy(float)
        adaptive = np.full(n, np.nan)
        alpha_fast, alpha_slow = 2 / (params["fast"] + 1), 2 / (params["slow"] + 1)
        last = np.nan
        for i, price in enumerate(close.to_numpy(float)):
            if not np.isfinite(efficiency[i]):
                continue
            alpha = (efficiency[i] * (alpha_fast - alpha_slow) + alpha_slow) ** 2
            last = price if not np.isfinite(last) else last + alpha * (price - last)
            adaptive[i] = last
        direction = _signed((close - adaptive) / atr, params["gap"])
        slope = _signed(pd.Series(adaptive).diff(3) / atr, .02)
        return np.where(direction == slope, direction, 0).astype(np.int8)
    if kind == "cusum":
        trigger = np.zeros(n, dtype=np.int8)
        up, down = 0.0, 0.0
        for i, delta in enumerate((close.diff() / atr).to_numpy(float)):
            if not np.isfinite(delta):
                continue
            up = max(0, up + delta - params["drift"])
            down = min(0, down + delta + params["drift"])
            if up >= params["threshold"]:
                trigger[i], up, down = 1, 0.0, 0.0
            elif down <= -params["threshold"]:
                trigger[i], up, down = -1, 0.0, 0.0
        return _hold(trigger, ttl=params["ttl"])
    if kind == "opening":
        cutoff = model["start"] + params["window"] * 60 + 120
        in_open = model["time_s"] < cutoff
        output = np.zeros(n, dtype=np.int8)
        if in_open.any():
            upper, lower = high[in_open].max(), low[in_open].min()
            allowed = model["time_s"] >= cutoff
            output[allowed & (close > upper + params["buffer"] * atr)] = 1
            output[allowed & (close < lower - params["buffer"] * atr)] = -1
        return output
    if kind == "ensemble":
        pieces = np.stack([_ema(model), _signed(close.diff(30) / atr, .75), _donchian(model, 30)])
        return np.where((pieces == 1).sum(axis=0) >= params["votes"], 1,
                        np.where((pieces == -1).sum(axis=0) >= params["votes"], -1, 0)).astype(np.int8)
    if kind == "guarded_reversion":
        long = _ema(model, 15, 60, .20, .02)
        short = _ema(model)
        good = (short == -long) & (_signed(close.diff(params["fast_return"])) == long)
        return np.where(good, long, 0).astype(np.int8)
    if kind == "multi_momentum":
        short = _signed(close.diff(params["short"]) / atr, params["short_threshold"])
        long = _signed(close.diff(params["long"]) / atr, params["long_threshold"])
        return np.where(short == long, short, 0).astype(np.int8)
    raise ValueError(f"未定義の確定足条件です: {kind}")


def _board(ready: dict, source: pd.DataFrame, seconds: int) -> dict:
    """機能: 原本行以前に解放済みの板特徴だけを過去時間窓で集計する。

    引数: ready (dict)、source (DataFrame) は原本由来の特徴、seconds (int) は窓秒数。
    返り値: 公開行番号・時刻・OFI等の配列を持つ辞書 (dict)。
    """
    key = (id(ready), id(source), len(ready["seq"]), int(ready["seq"][-1]), seconds)
    if key in _BOARD_CACHE:
        return _BOARD_CACHE[key]
    frame = source.loc[(source.seq <= ready["seq"][-1]) & (source.time_s <= ready["time_s"][-1])].copy()
    if not np.all(np.diff(frame.seq) > 0) or not np.all(np.diff(frame.time_s) > 0):
        raise ValueError("板特徴の公開順が不正です")
    if "source_last_seq" in frame and not (frame.source_last_seq < frame.seq).all():
        raise ValueError("未解放の板特徴が混入しています")
    frame.index = pd.to_datetime(frame.time_s, unit="s", utc=True)
    rolled = frame.rolling(f"{seconds}s", min_periods=5)
    signed, absolute = rolled.ofi_signed.sum(), rolled.ofi_abs.sum()
    up, down = rolled.quote_up.sum(), rolled.quote_down.sum()
    t = frame.time_s.to_numpy(float)
    mid = frame.source_mid_last.to_numpy(float)
    old_mid = _expand(t, mid, t - seconds, np.nan)
    change = _signed((mid - old_mid) / ready["tick"], 1.0)
    result = {"time_s": t, "seq": frame.seq.to_numpy(np.int64), "change": change,
              "ofi": (signed / absolute.replace(0, np.nan)).to_numpy(float),
              "quote": ((up - down) / (up + down).replace(0, np.nan)).to_numpy(float),
              "depth": rolled.imb5.mean().to_numpy(float),
              "weighted": rolled.micro_bias.mean().to_numpy(float)}
    atr = _expand(ready["seq"], np.asarray(ready["atr"], float), result["seq"], np.nan)
    result["progress"] = (mid - old_mid) / atr
    result["short_change"] = _signed((mid - _expand(t, mid, t - 30, np.nan)) / ready["tick"], 0)
    positive, negative = rolled.trade_pos.sum(), rolled.trade_neg.sum()
    result["trade"] = ((positive - negative) / (positive + negative).replace(0, np.nan)).to_numpy(float)
    result["trade_pos"], result["trade_neg"] = positive.to_numpy(float), negative.to_numpy(float)
    result["mid"] = mid
    result["atr"] = atr
    result["shock"] = (mid - _expand(t, mid, t - 60, np.nan)) / atr
    depth = (frame.bid_qty + frame.ask_qty).to_numpy(float)
    old_depth = _expand(t, depth, t - 60, np.nan)
    result["depth_ratio"] = np.divide(depth, old_depth, out=np.full_like(depth, np.nan), where=old_depth > 0)
    result["events"] = frame.raw_event_count.to_numpy(float)
    result["raw_ofi"] = frame.ofi_signed.to_numpy(float)
    result["raw_ofi_abs"] = frame.ofi_abs.to_numpy(float)
    for column in ("added_bid", "added_ask", "removed_bid", "removed_ask", "refill_bid", "refill_ask"):
        if column in frame:
            result[column] = rolled[column].sum().to_numpy(float)
    for column in ("dflow_near", "dflow_far", "pressure_near", "pressure_far"):
        if column in frame:
            result[column] = rolled[column].mean().to_numpy(float)
    result["index"] = frame.index
    _BOARD_CACHE[key] = result
    return result


def _board_signal(params: dict, ready: dict, source: pd.DataFrame) -> tuple[dict, np.ndarray]:
    """機能: 板の偏りと解放済み気配価格の同方向変化を確認する。

    引数: params (dict)、ready (dict)、source (DataFrame)。
    返り値: 板集計辞書と各公開行の方向 (tuple[dict, ndarray[int8]])。
    """
    model = _board(ready, source, params["seconds"])
    kind = params["kind"]
    metric = kind if kind in ("quote", "depth", "weighted") else "ofi"
    direction = _signed(model[metric], params["threshold"])
    direction[direction != model["change"]] = 0
    if kind == "persistent":
        flow = _signed(model["ofi"], params["threshold"])
        trade = _signed(model["trade"], params["trade_threshold"])
        prior1 = _expand(model["time_s"], flow, model["time_s"] - 60)
        prior2 = _expand(model["time_s"], flow, model["time_s"] - 120)
        good = (flow == prior1) & (flow == prior2) & (flow == trade) & (flow == model["change"])
        direction = np.where(good, flow, 0).astype(np.int8)
    elif kind == "absorption":
        flow = _signed(model["ofi"], params["threshold"])
        trade = _signed(model["trade"], params["trade_threshold"])
        absorbed = (model["progress"] * flow <= params["max_progress"]) & (flow == trade)
        direction = np.where(absorbed & (model["short_change"] == -flow), -flow, 0).astype(np.int8)
    elif kind == "replenishment":
        trade = _signed(model["trade"], params["threshold"])
        supplied = np.where(trade == 1, model["added_ask"], model["added_bid"])
        consumed = np.where(trade == 1, model["trade_pos"], model["trade_neg"])
        absorbed = (supplied >= consumed * params["refill_ratio"]) & (consumed > 0)
        absorbed &= model["progress"] * trade <= params["max_progress"]
        direction = np.where(absorbed & (model["short_change"] == -trade), -trade, 0).astype(np.int8)
    elif kind == "response":
        progress = pd.Series(model["progress"], index=model["index"])
        flow = pd.Series(model["ofi"], index=model["index"])
        window = f"{params['reference_seconds']}s"
        scale = progress.abs().shift(1).rolling(window, min_periods=100).mean()
        scale /= flow.abs().shift(1).rolling(window, min_periods=100).mean().replace(0, np.nan)
        residual = (progress - flow * scale).to_numpy(float)
        flow_direction = _signed(model["ofi"], params["threshold"])
        good = residual * flow_direction < -params["residual"]
        direction = np.where(good & (model["short_change"] == -flow_direction), -flow_direction, 0).astype(np.int8)
    elif kind in ("distance_near", "distance_far", "pressure_gradient", "refill_wall"):
        needed = ["refill_bid", "refill_ask"] if kind == "refill_wall" else ["dflow_near", "dflow_far", "pressure_near", "pressure_far"]
        if any(column not in model for column in needed):
            raise ValueError(f"距離・補充の追加板特徴が未生成です: {needed}")
        if kind == "distance_near":
            flow = _signed(model["dflow_near"], params["threshold"])
            direction = np.where(flow == model["change"], flow, 0).astype(np.int8)
        elif kind == "distance_far":
            flow = _signed(model["dflow_far"], params["threshold"])
            old = _expand(model["time_s"], flow, model["time_s"] - 60)
            near = _signed(model["dflow_near"], params["threshold"])
            good = (flow == old) & (flow == near) & (np.abs(model["progress"]) <= params["max_progress"])
            direction = np.where(good, flow, 0).astype(np.int8)
        elif kind == "pressure_gradient":
            near = _signed(model["pressure_near"], params["threshold"])
            slope = _signed(model["pressure_near"] - model["pressure_far"], params["threshold"])
            good = (near == slope) & (near == _signed(model["dflow_near"])) & (near == model["change"])
            direction = np.where(good, near, 0).astype(np.int8)
        else:
            total = model["refill_bid"] + model["refill_ask"]
            pressure = np.divide(model["refill_bid"] - model["refill_ask"], total,
                                 out=np.zeros_like(total), where=total > 0)
            wall = _signed(pressure, params["threshold"])
            direction = np.where(wall == model["short_change"], wall, 0).astype(np.int8)
    elif kind == "flow_reversal":
        history = _board(ready, source, params["history_seconds"])
        previous = _expand(history["time_s"], _signed(history["trade"], params["prior_threshold"]), model["time_s"] - params["seconds"])
        recent = _signed(model["trade"], params["threshold"])
        direction = np.where((recent == -previous) & (recent == model["change"]), recent, 0).astype(np.int8)
    elif kind == "fragility":
        volume = model["trade_pos"] + model["trade_neg"]
        impact = np.divide(np.abs(model["progress"]), volume, out=np.full_like(volume, np.nan), where=volume > 0)
        typical = pd.Series(impact, index=model["index"]).shift(1).rolling("1800s", min_periods=100).median().to_numpy(float)
        good = (impact >= params["impact_ratio"] * typical) & (np.abs(model["progress"]) >= params["min_progress"])
        direction = np.where(good, direction, 0).astype(np.int8)
    elif kind in ("shock_recover", "shock_continue"):
        shock = _signed(model["shock"], params["shock_atr"])
        if kind == "shock_recover":
            good = (model["depth_ratio"] >= params["depth_ratio"]) & (model["short_change"] == -shock)
            direction = np.where(good, -shock, 0).astype(np.int8)
        else:
            good = (model["depth_ratio"] <= params["depth_ratio"]) & (_signed(model["ofi"], params["threshold"]) == shock)
            direction = np.where(good, shock, 0).astype(np.int8)
    elif kind == "event_clock":
        events = np.cumsum(model["events"])
        starts = np.searchsorted(events, events - params["events"], side="left")
        sums = np.r_[0.0, np.cumsum(model["raw_ofi"])]
        absolute = np.r_[0.0, np.cumsum(model["raw_ofi_abs"])]
        net = sums[1:] - sums[starts]
        total = absolute[1:] - absolute[starts]
        ratio = np.divide(net, total, out=np.zeros_like(net), where=total > 0)
        event_direction = _signed(ratio, params["threshold"])
        movement = _signed((model["mid"] - model["mid"][starts]) / ready["tick"], 1)
        good = (events >= params["events"]) & (event_direction == movement)
        direction = np.where(good, event_direction, 0).astype(np.int8)
    elif kind in ("market_consensus", "market_absorption"):
        flow = _signed(model["ofi"], params["threshold"])
        trade = _signed(model["trade"], params["trade_threshold"])
        supply_net = model["added_bid"] + model["removed_ask"] - model["added_ask"] - model["removed_bid"]
        supply_total = model["added_bid"] + model["removed_ask"] + model["added_ask"] + model["removed_bid"]
        supply = np.divide(supply_net, supply_total, out=np.zeros_like(supply_net), where=supply_total > 0)
        supply_direction = _signed(supply, params["supply_threshold"])
        direction = np.where((flow == trade) & (flow == model["change"]) & (flow == supply_direction), flow, 0).astype(np.int8)
        absorbed = (model["progress"] * flow <= params.get("max_progress", .35)) & (flow == trade)
        model["absorbed_direction"] = np.where(absorbed & (model["short_change"] == -flow), -flow, 0).astype(np.int8)
    return model, direction


def build(spec: dict, inputs: dict, features: dict) -> dict[tuple[str, str], np.ndarray]:
    """機能: 指定固定条件を両銘柄へ適用し、原本各行で利用できる新規方向を返す。

    引数: spec (dict) は catalog の1件、inputs (dict) は (セッション,銘柄) ごとの ready、
          features (dict) は同じキーの解放済み板特徴 DataFrame。
    返り値: 同じキーで -1/0/1 の方向列を持つ辞書 (dict[tuple[str,str], ndarray[int8]])。
    注意: この行で発見した方向の注文は呼出側で次行以降に有効化する。
    """
    expected = {item["id"]: item for item in catalog()}
    if spec.get("id") not in expected or spec.get("params") != expected[spec["id"]]["params"]:
        raise ValueError("損益参照前に固定した数値条件と一致しません")
    params, output = spec["params"], {}
    kind = params["kind"]
    models = {key: _bars(ready) for key, ready in inputs.items()}
    board_kind = kind in ("ofi", "quote", "depth", "weighted", "ofi_trend", "ofi_peer", "persistent", "absorption", "replenishment", "response", "distance_near", "distance_far", "refill_wall", "pressure_gradient", "board_leader", "flow_reversal", "fragility", "shock_recover", "shock_continue", "event_clock", "market_consensus", "market_absorption")
    board_models = {key: _board_signal(params, ready, features[key]) for key, ready in inputs.items()} if board_kind else {}
    for key, ready in inputs.items():
        model = models[key]
        peer_key = (key[0], SYMBOLS[1 - SYMBOLS.index(key[1])])
        if kind == "dual":
            peer = models[peer_key]
            own_direction = _ema(model) if params["mode"] == "ema" else _signed(model["close"].diff(30) / model["atr"], .75)
            peer_direction = _ema(peer) if params["mode"] == "ema" else _signed(peer["close"].diff(30) / peer["atr"], .75)
            own = _expand(model["time_s"], own_direction, ready["time_s"])
            other = _expand(peer["time_s"] + params["peer_delay"], peer_direction, ready["time_s"])
            direction = np.where(own == other, own, 0).astype(np.int8)
        elif kind == "leader":
            leader = models[(key[0], params["leader"])]
            lead = _expand(leader["time_s"] + params["peer_delay"], _ema(leader), ready["time_s"])
            own = _expand(model["time_s"], _signed(model["close"].diff(3)), ready["time_s"])
            direction = np.where(own == lead, lead, 0).astype(np.int8)
        elif board_kind:
            board_model, board_direction = board_models[key]
            direction = _expand(board_model["seq"], board_direction, ready["seq"])
            if kind == "ofi_trend":
                trend = _expand(model["time_s"], _ema(model), ready["time_s"])
                direction[direction != trend] = 0
            elif kind == "ofi_peer":
                peer_model, peer_direction = board_models[peer_key]
                other = _expand(peer_model["time_s"] + params["peer_delay"], peer_direction, ready["time_s"])
                direction[direction != other] = 0
            elif kind == "board_leader":
                peer_model, peer_direction = board_models[peer_key]
                other = _expand(peer_model["time_s"] + params["peer_delay"], peer_direction, ready["time_s"])
                own = _expand(model["time_s"], _signed(model["close"].diff(3)), ready["time_s"])
                direction = np.where(own == other, other, 0).astype(np.int8)
            elif kind in ("market_consensus", "market_absorption"):
                peer_model, peer_direction = board_models[peer_key]
                other = _expand(peer_model["time_s"] + params["peer_delay"], peer_direction, ready["time_s"])
                own_pressure = direction.copy()
                direction = np.where(direction == other, direction, 0).astype(np.int8)
                if kind == "market_absorption":
                    own_absorbed = _expand(board_model["seq"], board_model["absorbed_direction"], ready["seq"])
                    other_absorbed = _expand(peer_model["time_s"] + params["peer_delay"], peer_model["absorbed_direction"], ready["time_s"])
                    direction[(own_absorbed != 0) | (other_absorbed != 0)] = 0
                    own_turn = (own_absorbed != 0) & ((own_absorbed == other_absorbed) | (own_absorbed == other))
                    other_turn = (other_absorbed != 0) & (other_absorbed == own_pressure)
                    direction[own_turn] = own_absorbed[own_turn]
                    direction[other_turn] = other_absorbed[other_turn]
        else:
            minute_direction = _minute_signal(params, model)
            direction = _expand(model["time_s"], minute_direction, ready["time_s"])
        direction[ready["time_s"] < ready["start"] + params["warmup_minutes"] * 60] = 0
        direction[~np.isfinite(ready["atr"]) | (ready["atr"] <= 0)] = 0
        output[key] = np.asarray(direction, dtype=np.int8)
        if len(direction) != len(ready["seq"]) or not np.isin(direction, [-1, 0, 1]).all():
            raise ValueError("方向列の長さまたは値が不正です")
    return output


if __name__ == "__main__":
    destination = Path(__file__).with_name("探索前の信号条件.json")
    destination.write_text(json.dumps(catalog(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"固定条件を保存しました: {len(catalog())}条件 / {len({item['family'] for item in catalog()})}系統")
