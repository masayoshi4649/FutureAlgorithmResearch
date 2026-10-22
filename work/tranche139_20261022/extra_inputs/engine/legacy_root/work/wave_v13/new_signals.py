"""持続波・状態推定・流動性・２銘柄の新仮説18系統を過去情報だけから生成する。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
_spec = importlib.util.spec_from_file_location('追加研究_既存信号', ROOT/'work/wave_v11/signals.py')
BASE = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(BASE)
EVENT_COLUMNS = BASE.EVENT_COLUMNS
SOURCES = {
    '局所推定': 'https://www.nber.org/papers/w7613',
    '状態推定': 'https://doi.org/10.1115/1.3662552',
    '適応平均': 'https://www.metatrader5.com/en/terminal/help/indicators/trend_indicators/ama',
    '分散比': 'https://www.nber.org/papers/w2168',
    '方向変化': 'https://arxiv.org/abs/0809.1040',
    'オンライン回帰': 'https://arxiv.org/abs/0910.4683',
    '近傍学習': 'https://arxiv.org/abs/0712.1624',
    '継続': 'https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum',
    '微小価格': 'https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2970694',
    'フロー': 'https://arxiv.org/abs/1011.6402',
    '先行遅行': 'https://arxiv.org/abs/1111.7103',
    '平均回帰': 'https://arxiv.org/abs/1411.5062',
}


def configure(base: ModuleType) -> None:
    """機能: 読取先が設定済みの既存信号モジュールを共有する。

    引数: base (ModuleType)。返り値: なし (None)。
    """
    global BASE
    BASE = base


def profiles() -> list[dict]:
    """機能: 新規18系統の思想・数値条件・出典を返す。

    引数: なし。返り値: 日本語の信号定義一覧 (list[dict])。
    """
    definitions = [
        ('N01', '局所回帰で滑らかな持続方向を追う', '状態と持続波', '確定終値30本の直線回帰。決定係数0.45以上、15分相当の傾きが0.6ATR以上、現在値が回帰線から0.8ATR以内なら傾き方向。', '局所推定'),
        ('N02', 'カルマン状態推定の速度を追う', '状態と持続波', '水準・速度の２状態カルマン推定。観測分散=(0.5ATR)^2、状態分散=(0.08ATR)^2/(0.008ATR)^2。10分予測変位が0.5ATR以上、観測残差が1ATR以内なら速度方向。', '状態推定'),
        ('N03', '効率比で反応を変える適応平均', '状態と持続波', '効率比ER10=10分変位絶対値/１分変位絶対値合計。ERが0.35以上、適応平均KAMA(10,2,30)の５分傾きが0.2ATR以上で、価格も平均の同方向側。', '適応平均'),
        ('N04', '分散比による順張り逆張り切替', '状態と持続波', '過去60本でVR5=５分変化分散/(5×１分変化分散)。VR>=1.15なら５分変位0.4ATR以上の方向。VR<=0.8なら20分z値±1.2以上かつ１分反発を確認して平均方向。', '分散比'),
        ('N05', '時間によらない方向変化イベント', '状態と持続波', '確定終値の追跡極値から0.8ATR反転した時だけ反転方向を通知。幅は追跡極値の更新時ATRで固定。将来の頂点・底を使わない。', '方向変化'),
        ('N06', '寄り30分レンジ突破後の再確認', '価格構造と反転', '初めの30分高安を固定。0.1ATR超えて抜けた後20分以内に境界±0.25ATRへ再接近し、突破方向へ終値が戻り１分変化も同方向なら通知。', '局所推定'),
        ('N07', '過去滞在帯の外への逸脱と戻り', '価格構造と反転', '直前60終値の20%/80%分位帯。１本前終値が帯外に0.2ATR以上逸脱し、今回終値が帯内へ戻れば中央値方向。出来高の不完全性に依存しない滞在時間帯。', '平均回帰'),
        ('N08', '静穏から変動拡大への切替', '価格構造と反転', '１分変化の10本標準偏差が直前60本の0.65倍以下だった後５分以内に1.2倍以上へ拡大。５分変位0.5ATR以上ならその方向。', '継続'),
        ('N09', '中央値からの過度な逸脱の反発', '価格構造と反転', '直前30終値の中央値とMADを使用。1.4826×MADを１呼値で下限化。そこから2倍以上逸脱し、２本連続で中央値方向へ反発した方向。', '平均回帰'),
        ('N10', '確定した正解だけを使う逐次回帰', '逐次学習', '１/５/15分変位・20分偏差・ER10・定数を入力、10分後ATR変位を逐次ridge学習。正解が既知の例のみ、忘却0.995、初期正則化10、40例以上、予測変位±0.35ATR以上で通知。', 'オンライン回帰'),
        ('N11', '似た過去の道筋から次を推定', '逐次学習', '過去15分を５本ずつの３区間変位/ATRへ変換。10分後正解が既知の直近180候補から近い10例を等重み。30候補以上、平均予測±0.4ATR以上なら通知。', '近傍学習'),
        ('N12', '複数時間幅の持続方向の合意', '状態と持続波', '５/15/30分変位が同方向で各0.2/0.5/0.8ATR以上、直近15本の上昇比率>=0.6なら買い、下落比率>=0.6なら売り。', '継続'),
        ('N13', '数量加重価格の先行と気配の追随', '板の応答と流動性', '解放済み数量加重中値バイアス/スプレッドの60秒平均が±0.08以上、15秒気配中値変化が同方向に0.5呼値以上、60秒OFIも同方向0.05以上。２解放ブロック確認。', '微小価格'),
        ('N14', '消費後の板補充の左右差', '板の応答と流動性', '60秒の買い板追加/除去と売り板追加/除去から補充比率差を作る。±0.12以上、同方向の板追加・反対板除去合計が逆側の1.4倍以上、５分価格方向も一致。２ブロック確認。', 'フロー'),
        ('N15', '注文フローに対する価格応答の遅れ', '板の応答と流動性', '過去30分の１分OFI/絶対OFIと同時１分変位/ATRの回帰で価格応答を推定。直近OFI±0.15以上、推定変位−実変位が同方向0.15ATR以上なら未反映方向。回帰は現在１分を除外。', 'フロー'),
        ('N16', 'スプレッド拡大の収束と価格移動', '板の応答と流動性', '直前60秒平均スプレッドが２呼値以上で、現在が過去60秒平均の0.75倍以下へ縮小。60秒中値変化±0.3ATR以上かつ気配更新偏り同方向なら通知。', '微小価格'),
        ('N17', '２銘柄の局所ベータ残差の回帰', '２銘柄の推定', '他銘柄を60秒以上遅らせた１分系列で、過去90分の終値を回帰。水準相関>=0.5、beta>0、現在残差が学習残差の±1.5標準偏差以上、直近１分が残差を埋める方向なら通知。片銘柄売買。', '先行遅行'),
        ('N18', '先行遅行の強さを逐次学習する', '２銘柄の推定', '遅延他銘柄５分変位・自５分変位・定数から自10分後変位/ATRを逐次ridge学習。40確定例以上、予測±0.4ATR以上、他銘柄５分変位0.25ATR以上で通知。', 'オンライン回帰'),
    ]
    return [dict(id=k, family=k, name=n, label=n, group=g, rules=r, description=r,
                 source=SOURCES[s], source_name=s,
                 research_note='研究の着想を用いた独自仮説。論文の結果・閾値の再現ではない。')
            for k, n, g, r, s in definitions]


def _ridge_forecast(x: np.ndarray, close: np.ndarray, atr: np.ndarray,
                    horizon: int = 10) -> tuple[np.ndarray, np.ndarray]:
    """機能: 正解が既に確定した入力だけで忘却付き回帰を更新する。

    引数: x/close/atr (ndarray)、horizon (int)。返り値: 予測と学習数 (tuple[ndarray, ndarray])。
    """
    n, dim = x.shape
    forecast, counts = np.full(n, np.nan), np.zeros(n, dtype=int)
    gram, rhs, count = np.eye(dim)*10., np.zeros(dim), 0
    for i in range(n):
        j = i-horizon
        if j >= 0 and np.isfinite(x[j]).all() and np.isfinite(atr[j]) and np.isfinite(close[i]):
            outcome = np.clip((close[i]-close[j])/atr[j], -8., 8.)
            gram = .995*gram + np.outer(x[j], x[j]) + .005*10*np.eye(dim)
            rhs = .995*rhs + x[j]*outcome
            count += 1
        counts[i] = count
        if count >= 40 and np.isfinite(x[i]).all():
            forecast[i] = float(x[i] @ np.linalg.solve(gram, rhs))
    return forecast, counts


def minute_features(z: pd.DataFrame, tick: float) -> pd.DataFrame:
    """機能: 確定１分足から新しい状態・道筋・逐次学習の特徴を作る。

    引数: z (DataFrame)、tick (float)。返り値: 過去方向の特徴を追加した表 (DataFrame)。
    """
    z = z.copy()
    c, a = z.close, z.atr
    values, atr = c.to_numpy(float), a.to_numpy(float)
    n = len(z)
    z['efficiency10'] = c.diff(10).abs()/c.diff().abs().rolling(10).sum().replace(0, np.nan)
    z['variance_ratio'] = c.diff(5).rolling(60).var(ddof=0)/(5*c.diff().rolling(60).var(ddof=0)).replace(0, np.nan)
    slopes, fits, residuals = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
    xx = np.arange(30, dtype=float)-14.5
    for i in range(29, n):
        yy = values[i-29:i+1]
        if np.isfinite(yy).all():
            slope = float(xx @ yy/(xx @ xx))
            fitted = yy.mean()+slope*xx
            total = np.sum((yy-yy.mean())**2)
            slopes[i], fits[i], residuals[i] = slope, 1-np.sum((yy-fitted)**2)/max(total, tick*tick), yy[-1]-fitted[-1]
    z['reg_slope'], z['reg_r2'], z['reg_residual'] = slopes, fits, residuals

    # ----------------------------------------
    # 平滑化はフィルタだけを使い、将来値を参照する後方平滑化を行わない。
    level, velocity, innovation = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
    state, covariance = None, None
    transition = np.array([[1., 1.], [0., 1.]])
    kama = np.full(n, np.nan)
    efficiency = z.efficiency10.to_numpy(float)
    for i in range(n):
        if not np.isfinite(values[i]):
            continue
        if i == 0 or not np.isfinite(kama[i-1]):
            kama[i] = values[i]
        else:
            er = efficiency[i] if np.isfinite(efficiency[i]) else 0.
            weight = (er*(2/3-2/31)+2/31)**2
            kama[i] = kama[i-1]+weight*(values[i]-kama[i-1])
        if not np.isfinite(atr[i]):
            continue
        if state is None:
            state, covariance = np.array([values[i], 0.]), np.diag([atr[i]**2, (.1*atr[i])**2])
        prediction = transition @ state
        pred_cov = transition @ covariance @ transition.T + np.diag([(.08*atr[i])**2, (.008*atr[i])**2])
        error = values[i]-prediction[0]
        gain = pred_cov[:, 0]/(pred_cov[0, 0]+(.5*atr[i])**2)
        state = prediction+gain*error
        covariance = pred_cov-np.outer(gain, pred_cov[0, :])
        level[i], velocity[i], innovation[i] = state[0], state[1], error
    z['kalman_level'], z['kalman_velocity'], z['kalman_innovation'] = level, velocity, innovation
    z['kama'], z['kama_change5'] = kama, pd.Series(kama, index=z.index).diff(5)
    z['lower_value'] = c.shift().rolling(60).quantile(.2)
    z['upper_value'] = c.shift().rolling(60).quantile(.8)
    z['volatility_ratio'] = c.diff().rolling(10).std(ddof=0)/c.diff().shift().rolling(60).std(ddof=0).replace(0, np.nan)
    medians, mads = np.full(n, np.nan), np.full(n, np.nan)
    for i in range(30, n):
        history = values[i-30:i]
        if np.isfinite(history).all():
            medians[i] = np.median(history)
            mads[i] = max(tick, 1.4826*np.median(np.abs(history-medians[i])))
    z['robust_z'] = (values-medians)/mads
    x = np.column_stack([np.ones(n), c.diff().to_numpy()/atr, c.diff(5).to_numpy()/atr,
                         c.diff(15).to_numpy()/atr, z.z20, z.efficiency10])
    x = np.clip(x, -5., 5.)
    z['ridge_prediction'], z['ridge_count'] = _ridge_forecast(x, values, atr)

    # ----------------------------------------
    # 類似例の10分後が現在以前に確定していることを添字で制限する。
    paths = np.column_stack([c.diff(5).shift(10)/a, c.diff(5).shift(5)/a, c.diff(5)/a])
    forecasts, examples = np.full(n, np.nan), np.zeros(n, dtype=int)
    for i in range(40, n):
        candidates = np.arange(max(15, i-189), i-9)
        ok = np.isfinite(paths[candidates]).all(axis=1) & np.isfinite(atr[candidates]) & np.isfinite(values[candidates+10])
        candidates = candidates[ok]
        examples[i] = len(candidates)
        if len(candidates) >= 30 and np.isfinite(paths[i]).all():
            distance = np.sum((paths[candidates]-paths[i])**2, axis=1)
            chosen = candidates[np.argsort(distance, kind='stable')[:10]]
            forecasts[i] = np.mean((values[chosen+10]-values[chosen])/atr[chosen])
    z['nearest_prediction'], z['nearest_count'] = forecasts, examples
    return z


def minute_conditions(z: pd.DataFrame) -> dict[str, np.ndarray]:
    """機能: 新規12個の分足仮説を判定する。

    引数: z (DataFrame)。返り値: 各系統の方向配列 (dict[str, ndarray])。
    """
    signed = BASE.signed_condition
    c, a, d = z.close, z.atr, z.close.diff()
    common = (z.reg_r2 >= .45) & (z.reg_residual.abs() <= .8*a)
    result = {'N01': signed(common & (15*z.reg_slope >= .6*a), common & (15*z.reg_slope <= -.6*a))}
    common = z.kalman_innovation.abs() <= a
    result['N02'] = signed(common & (10*z.kalman_velocity >= .5*a), common & (10*z.kalman_velocity <= -.5*a))
    common = z.efficiency10 >= .35
    result['N03'] = signed(common & (z.kama_change5 >= .2*a) & (c > z.kama), common & (z.kama_change5 <= -.2*a) & (c < z.kama))
    result['N04'] = signed(((z.variance_ratio >= 1.15) & (c.diff(5) >= .4*a)) | ((z.variance_ratio <= .8) & (z.z20 <= -1.2) & (d > 0)),
                          ((z.variance_ratio >= 1.15) & (c.diff(5) <= -.4*a)) | ((z.variance_ratio <= .8) & (z.z20 >= 1.2) & (d < 0)))
    result['N05'] = np.zeros(len(z), dtype=np.int8)
    direction, extreme, width = 0, np.nan, np.nan
    for i, row in enumerate(z.itertuples()):
        if not np.isfinite(row.atr) or row.stale_minutes > 1:
            continue
        if not np.isfinite(extreme):
            extreme, width = row.close, .8*row.atr
        if direction == 0:
            if row.close >= extreme+width:
                direction, extreme, width = 1, row.close, .8*row.atr
                result['N05'][i] = 1
            elif row.close <= extreme-width:
                direction, extreme, width = -1, row.close, .8*row.atr
                result['N05'][i] = -1
        elif direction > 0:
            if row.close > extreme:
                extreme, width = row.close, .8*row.atr
            elif row.close <= extreme-width:
                direction, extreme, width = -1, row.close, .8*row.atr
                result['N05'][i] = -1
        else:
            if row.close < extreme:
                extreme, width = row.close, .8*row.atr
            elif row.close >= extreme+width:
                direction, extreme, width = 1, row.close, .8*row.atr
                result['N05'][i] = 1
    result['N06'] = np.zeros(len(z), dtype=np.int8)
    if len(z) >= 30 and z.high.iloc[:30].notna().all() and z.low.iloc[:30].notna().all():
        top, bottom = float(z.high.iloc[:30].max()), float(z.low.iloc[:30].min())
        pending, first = 0, -100
        for i in range(30, len(z)):
            if not np.isfinite(a.iloc[i]):
                continue
            if pending and i-first > 20:
                pending = 0
            if pending == 1 and i > first and z.low.iloc[i] <= top+.25*a.iloc[i] and c.iloc[i] >= top and d.iloc[i] > 0:
                result['N06'][i], pending = 1, 0
            elif pending == -1 and i > first and z.high.iloc[i] >= bottom-.25*a.iloc[i] and c.iloc[i] <= bottom and d.iloc[i] < 0:
                result['N06'][i], pending = -1, 0
            elif not pending:
                if c.iloc[i] > top+.1*a.iloc[i] and c.iloc[i-1] <= top+.1*a.iloc[i-1]:
                    pending, first = 1, i
                elif c.iloc[i] < bottom-.1*a.iloc[i] and c.iloc[i-1] >= bottom-.1*a.iloc[i-1]:
                    pending, first = -1, i
    result['N07'] = signed((c.shift() <= z.lower_value-.2*a) & (c >= z.lower_value),
                          (c.shift() >= z.upper_value+.2*a) & (c <= z.upper_value))
    quiet = z.volatility_ratio.shift().rolling(5).min() <= .65
    result['N08'] = signed(quiet & (z.volatility_ratio >= 1.2) & (c.diff(5) >= .5*a),
                          quiet & (z.volatility_ratio >= 1.2) & (c.diff(5) <= -.5*a))
    result['N09'] = signed((z.robust_z <= -2) & (d > 0) & (d.shift() > 0), (z.robust_z >= 2) & (d < 0) & (d.shift() < 0))
    result['N10'] = signed(z.ridge_prediction >= .35, z.ridge_prediction <= -.35)
    result['N11'] = signed(z.nearest_prediction >= .4, z.nearest_prediction <= -.4)
    positive = d.gt(0).rolling(15).mean() >= .6
    negative = d.lt(0).rolling(15).mean() >= .6
    result['N12'] = signed(positive & (c.diff(5) >= .2*a) & (c.diff(15) >= .5*a) & (c.diff(30) >= .8*a),
                          negative & (c.diff(5) <= -.2*a) & (c.diff(15) <= -.5*a) & (c.diff(30) <= -.8*a))
    return result


def board_conditions(f: pd.DataFrame, atr: np.ndarray, tick: float) -> tuple[dict[str, np.ndarray], pd.DataFrame]:
    """機能: 封印解除された板から流動性と価格応答の４仮説を判定する。

    引数: f (DataFrame)、atr (ndarray)、tick (float)。返り値: 方向配列と根拠値 (tuple[dict, DataFrame])。
    """
    v = BASE.board_extended(f, atr)
    numeric = f.select_dtypes(include='number').copy()
    numeric.index = pd.to_datetime(f.time_s.to_numpy(), unit='s', utc=True)
    numeric.loc[f.block_delay_seconds.to_numpy() > 60, :] = np.nan
    roll = numeric.rolling('60s', min_periods=5)
    sums = roll.sum()
    micro = (numeric.micro_bias*numeric.valid_event_count).rolling('60s', min_periods=5).sum()/sums.valid_event_count.replace(0, np.nan)
    v['micro60'] = micro.to_numpy()
    bid_fill = sums.added_bid/(sums.added_bid+sums.removed_bid).replace(0, np.nan)
    ask_fill = sums.added_ask/(sums.added_ask+sums.removed_ask).replace(0, np.nan)
    v['replenishment_difference'] = (bid_fill-ask_fill).to_numpy()
    v['flow_ratio'] = ((sums.added_bid+sums.removed_ask)/(sums.added_ask+sums.removed_bid).replace(0, np.nan)).to_numpy()
    v['spread60'] = roll.spread_ticks.mean().to_numpy()
    v['current_spread'] = f.spread_ticks.to_numpy(float)
    signed = BASE.signed_condition
    change15_ticks = v.mid_change15_atr.to_numpy()*atr/tick
    result = {
        'N13': signed((v.micro60 >= .08) & (change15_ticks >= .5) & (v.ofi60 >= .05),
                      (v.micro60 <= -.08) & (change15_ticks <= -.5) & (v.ofi60 <= -.05)),
        'N14': signed((v.replenishment_difference >= .12) & (v.flow_ratio >= 1.4),
                      (v.replenishment_difference <= -.12) & (v.flow_ratio <= 1/1.4)),
        'N16': signed((v.spread60.shift() >= 2) & (v.current_spread <= .75*v.spread60) & (v.mid_change60_atr >= .3) & (v.quote60 > 0),
                      (v.spread60.shift() >= 2) & (v.current_spread <= .75*v.spread60) & (v.mid_change60_atr <= -.3) & (v.quote60 < 0)),
    }

    # ----------------------------------------
    # １分の板集計はバケット末尾を過ぎてから利用し、回帰には更に１本前までを使う。
    grouped = pd.DataFrame({'ofi': numeric.ofi_signed, 'absolute': numeric.ofi_abs,
                            'mid': numeric.source_mid_last, 'atr': atr}).resample('1min', label='right', closed='left').agg(
                                {'ofi': 'sum', 'absolute': 'sum', 'mid': 'last', 'atr': 'last'})
    x = grouped.ofi/grouped.absolute.replace(0, np.nan)
    y = grouped.mid.diff()/grouped.atr
    xx, yy = x.shift(), y.shift()
    slope = xx.rolling(30, min_periods=20).cov(yy)/xx.rolling(30, min_periods=20).var().replace(0, np.nan)
    predicted = yy.rolling(30, min_periods=20).mean()+slope*(x-xx.rolling(30, min_periods=20).mean())
    residual = predicted-y
    stamps = grouped.index.as_unit('ns').asi8/1e9
    times = f.time_s.to_numpy(float)
    pos = np.searchsorted(stamps, times, side='right')-1
    ix = np.maximum(pos, 0)
    valid = (pos >= 0) & (times-stamps[ix] <= 120)
    v['impact_residual'] = np.where(valid, residual.to_numpy()[ix], np.nan)
    v['impact_ofi'] = np.where(valid, x.to_numpy()[ix], np.nan)
    result['N15'] = signed((v.impact_ofi >= .15) & (v.impact_residual >= .15),
                          (v.impact_ofi <= -.15) & (v.impact_residual <= -.15))
    times = f.time_s.to_numpy(float)
    old = np.searchsorted(times, times-300, side='right')-1
    delta = f.source_mid_last.to_numpy()-f.source_mid_last.to_numpy()[np.maximum(old, 0)]
    result['N14'] = np.where((old >= 0) & (result['N14']*delta > 0), result['N14'], 0).astype(np.int8)
    return result, v


def pair_conditions(z: pd.DataFrame, pz: pd.DataFrame, lag: int) -> tuple[dict[str, np.ndarray], pd.DataFrame]:
    """機能: 他銘柄の価格を明示的に遅延させ、局所ベータと逐次先行遅行を判定する。

    引数: z/pz (DataFrame)、lag (int)。返り値: 方向と根拠表 (tuple[dict, DataFrame])。
    """
    times, ptimes = z.available_time_s.to_numpy(float), pz.available_time_s.to_numpy(float)
    pos = np.searchsorted(ptimes+lag, times, side='right')-1
    ix = np.maximum(pos, 0)
    fresh = (pos >= 0) & (times-ptimes[ix] <= 180) & (pz.stale_minutes.to_numpy()[ix] <= 1)
    peer_close = pd.Series(np.where(fresh, pz.close.to_numpy()[ix], np.nan), index=z.index)
    own = z.close
    corr = peer_close.shift().rolling(90, min_periods=60).corr(own.shift())
    # 過去価格回帰の残差をその時点の係数で計算し、現在値は推定から除く。
    means_x, means_y = peer_close.shift().rolling(90, min_periods=60).mean(), own.shift().rolling(90, min_periods=60).mean()
    level_beta = peer_close.shift().rolling(90, min_periods=60).cov(own.shift())/peer_close.shift().rolling(90, min_periods=60).var().replace(0, np.nan)
    beta = level_beta
    residual = own-means_y-level_beta*(peer_close-means_x)
    var_y = own.shift().rolling(90, min_periods=60).var(ddof=0)
    var_x = peer_close.shift().rolling(90, min_periods=60).var(ddof=0)
    cov = peer_close.shift().rolling(90, min_periods=60).cov(own.shift(), ddof=0)
    error_scale = np.sqrt((var_y+level_beta**2*var_x-2*level_beta*cov).clip(lower=0)).clip(lower=1e-9)
    rz = residual/error_scale
    peer_atr = pz.atr.to_numpy()[ix]
    peer_return = peer_close.diff(5)/peer_atr
    own_return = own.diff(5)/z.atr
    features = np.clip(np.column_stack([np.ones(len(z)), peer_return, own_return]), -5., 5.)
    forecast, count = _ridge_forecast(features, own.to_numpy(float), z.atr.to_numpy(float))
    common = fresh & (corr >= .5) & (beta > 0) & (level_beta > 0)
    result = {
        'N17': BASE.signed_condition(common & (rz <= -1.5) & (own.diff() > 0), common & (rz >= 1.5) & (own.diff() < 0)),
        'N18': BASE.signed_condition(fresh & (forecast >= .4) & (peer_return.abs() >= .25),
                                    fresh & (forecast <= -.4) & (peer_return.abs() >= .25)),
    }
    detail = pd.DataFrame(dict(pair_residual_z=rz, pair_beta=beta, pair_level_beta=level_beta,
                              pair_correlation=corr, pair_prediction=forecast, pair_count=count,
                              peer_minute_available_time_s=ptimes[ix], peer_return5_atr=peer_return), index=z.index)
    return result, detail


def build_events(session: str, symbol: str, features: pd.DataFrame,
                 peer_features: pd.DataFrame | None = None, cutoff: float | None = None,
                 peer_lag: int = 60) -> tuple[pd.DataFrame, dict]:
    """機能: 新しい18信号を解放済み板行へ対応し、機械的注文器へ渡す。

    引数: session/symbol (str)、features/peer_features (DataFrame|None)、cutoff (float|None)、peer_lag (int)。
    返り値: 既存互換イベント表と因果監査値 (tuple[DataFrame, dict])。
    """
    if peer_lag < 60:
        raise ValueError('他銘柄の待機は60秒以上が必要です')
    f = features.loc[features.time_s <= cutoff].copy() if cutoff is not None else features.copy()
    f = f.reset_index(drop=True)
    if f.empty:
        return pd.DataFrame(columns=EVENT_COLUMNS), {'イベント数': 0}
    if np.any(np.diff(f.seq) <= 0) or np.any(np.diff(f.time_s) <= 0) or not (f.source_last_seq < f.seq).all():
        raise ValueError('板の未解放行・逆順を検出しました')
    times, seqs = f.time_s.to_numpy(float), f.seq.to_numpy(int)
    atr = BASE.atr_at(session, symbol, times)
    fresh = (f.block_delay_seconds.to_numpy() <= 60) & np.isfinite(atr)
    z = BASE.price_grid(session, symbol, float(times[-1]))
    if z.empty:
        return pd.DataFrame(columns=EVENT_COLUMNS), {'イベント数': 0}
    z = minute_features(z, BASE.TICKS[symbol])
    minute_times = z.available_time_s.to_numpy(float)
    minute_fresh = z.stale_minutes.le(1).to_numpy() & np.isfinite(z.atr.to_numpy())
    rows = {}
    peer = peer_features.copy().reset_index(drop=True) if peer_features is not None else pd.DataFrame()
    if not peer.empty:
        peer = peer.loc[peer.time_s+peer_lag <= times[-1]].reset_index(drop=True)

    def add(i: int, family: str, side: int, reason: dict, pi: int = -1) -> None:
        """機能: 素材と発火行を持つ通知を一意に保存する。

        引数: i (int)、family (str)、side (int)、reason (dict)、pi (int)。返り値: なし (None)。
        """
        if not side or not fresh[i]:
            return
        row = dict(event_id=f'{session}:{symbol}:{family}:{seqs[i]}', family=family, seq=int(seqs[i]),
                   time_s=float(times[i]), side=int(side), atr=float(atr[i]), deadline_time_s=float(times[i])+600,
                   source_last_seq=int(f.source_last_seq.iloc[i]), reason=reason,
                   peer_seq=-1, peer_source_last_seq=-1, peer_time_s=np.nan, peer_available_time_s=np.nan)
        if pi >= 0:
            p = peer.iloc[pi]
            row.update(peer_seq=int(p.seq), peer_source_last_seq=int(p.source_last_seq),
                       peer_time_s=float(p.time_s), peer_available_time_s=float(p.time_s)+peer_lag)
        rows[(family, i)] = row

    # ----------------------------------------
    # 元足開始から２分待った条件を、その後の最初の解放済み板行へ対応する。
    for family, raw in minute_conditions(z).items():
        signals = raw if family in ['N05', 'N06'] else BASE.sampled_events(raw, minute_times, minute_fresh)
        for j in np.flatnonzero(signals):
            i = int(np.searchsorted(times, minute_times[j], side='left'))
            if i < len(f) and times[i]-minute_times[j] <= 60 and minute_fresh[j]:
                reason = {key: float(z.iloc[j][key]) for key in ['close', 'atr', 'reg_slope', 'reg_r2', 'kalman_velocity',
                           'efficiency10', 'variance_ratio', 'ridge_prediction', 'ridge_count', 'nearest_prediction']}
                reason['minute_available_time_s'] = float(minute_times[j])
                add(i, family, int(signals[j]), reason)
    candidates, details = board_conditions(f, atr, BASE.TICKS[symbol])
    for family, raw in candidates.items():
        for i in np.flatnonzero(signals := BASE.sampled_events(raw, times, fresh, 2)):
            add(int(i), family, int(signals[i]), {key: float(value) for key, value in details.iloc[i].items()})

    # ----------------------------------------
    # 他銘柄の足と板の両方に60秒待機を要求する。古い他銘柄は180秒で破棄する。
    if not peer.empty:
        if np.any(np.diff(peer.seq) <= 0) or np.any(np.diff(peer.time_s) <= 0) or not (peer.source_last_seq < peer.seq).all():
            raise ValueError('他銘柄の板に未解放行・逆順があります')
        peer_symbol = BASE.SYMBOLS[1-BASE.SYMBOLS.index(symbol)]
        pz = BASE.price_grid(session, peer_symbol, float(peer.time_s.iloc[-1]))
        if not pz.empty:
            pair, detail = pair_conditions(z, pz, peer_lag)
            peer_times = peer.time_s.to_numpy(float)
            for family, raw in pair.items():
                for j in np.flatnonzero(signals := BASE.sampled_events(raw, minute_times, minute_fresh)):
                    i = int(np.searchsorted(times, minute_times[j], side='left'))
                    if i >= len(f) or times[i]-minute_times[j] > 60:
                        continue
                    pi = int(np.searchsorted(peer_times+peer_lag, times[i], side='right')-1)
                    if pi < 0 or times[i]-peer_times[pi] > 180 or peer.block_delay_seconds.iloc[pi] > 60:
                        continue
                    reason = {key: float(value) for key, value in detail.iloc[j].items()}
                    reason['minute_available_time_s'] = float(minute_times[j])
                    reason['peer_lag_seconds'] = peer_lag
                    add(i, family, int(signals[j]), reason, pi)
    output = pd.DataFrame(list(rows.values()), columns=EVENT_COLUMNS).sort_values(['seq', 'family']).reset_index(drop=True)
    audit = dict(イベント数=len(output), 系統別={p['id']: int(output.family.eq(p['id']).sum()) for p in profiles()},
                 足の利用='開始＋２分、ATRは５分足開始＋６分', 板='同一時刻ブロックを次時刻まで封印、未封印行禁止',
                 学習='当該セッション内で10分後が既に確定した例だけを使う。セッション間の学習状態は持ち越さない。',
                 他銘柄='追加60秒以上待機、素材180秒以内。注文は対象１銘柄。', API取得回数=0)
    return output, audit


if __name__ == '__main__':
    (OUT/'新規信号条件一覧.json').write_text(json.dumps(profiles(), ensure_ascii=False, indent=2), encoding='utf-8')
    print('新規18信号の定義を書き出しました。価格と損益は未参照です。')
