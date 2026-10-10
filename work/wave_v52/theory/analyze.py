"""価格形成の代理量を先に測り、価格だけの対照と将来関係を比較する。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MEASUREMENT = HERE.parent / 'measurement'
FEATURES = {
    'execution': '前気配に対する執行側の代理',
    'withdrawal': '出来高増分なしの表示減少の偏り',
    'addition': '出来高増分なしの表示追加の偏り',
    'recovery': '回復時に両最良値不変の同価格回復の偏り',
    'supply': '距離加重の近接供給の偏り',
    'repricing': '両気配の値直し方向（価格対照）',
}
PERIODS = ('先頭10場', '次9場', '既知最後4場')
HORIZONS = (60, 300, 900)
CONTROL_NAMES = ('r1', 'r5', 'abs_r1', 'abs_r5', 'rv5', 'log_volume',
                 'spread_atr', 'log_depth', 'night', 'elapsed_fraction')


def save(path: Path, value: object) -> None:
    """機能: 数値結果を日本語JSONとして保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def fixed_spec() -> dict:
    """機能: 損益を見ずに観測分析の時間・比較・除外規則を固定する。

    引数: なし。返り値: 分析仕様(dict)。
    """
    return dict(
        主目的='価格形成代理に直前価格だけを超えた将来関係があるか。利益最大化による選択をしない。',
        起点='各場の開始20分後から60秒間隔。情報は起点以前の公開行だけ。',
        集計='直前60秒に公開したブロックの合計。供給は有効行数で重み付け。',
        起点品質='現在と過去5分の各1分時点の価格鮮度60秒以内。集計する公開ブロックの源時刻も起点60秒前以降、公開2回以上、有効行2以上、源年齢60秒以内、連続性リセットなし。',
        出来高品質='直前60秒の出来高リセット・出来高欠測増分があれば除外。',
        時刻制約='約定時計の代理による公開。実受信時刻は不明。先行遅行を因果と呼ばない。',
        ラベル='起点から1/5/15分後以前最後の公開中値（鮮度60秒）−起点中値、起点ATRで割る。場末越えはラベルのみ欠測。',
        主時間秒=300, 補助時間秒=[60, 900], 非重複対照='場開始20分後から15分刻みの起点。15分ラベルまで重複なし。',
        期間='先頭10場で価格対照回帰と3分位境界を固定、次9場と既知最後4場へ適用。全場既閲覧の研究内比較。',
        機構=FEATURES,
        比較='銘柄別。価格対照は切片と10変数の線形最小二乗。特徴も対照で残差化した部分相関と、先頭10固定の下/中/上群の価格対照残差差。因果を断定しない。',
        対照変数=list(CONTROL_NAMES),
        強弱='先頭10場の非欠測特徴の1/3・2/3分位。取引の損益では選ばない。執行等の母数0は0へ代替せず欠測。',
        状態='6指標の非ゼロ方向×直前1分が同方向進行/不進行（逆向きと横ばいを含む）の12状態。閾値は最適化しない。',
        相手='相手起点は自市場起点−60秒以前の最後の60秒観測。そこからの経過60秒以内。未来補間なし。',
        順行逆行='起点後から各時間内の公開中値の最大/最小を起点ATR正規化。将来ラベル専用。',
        統計集計='観測ごとの平均に加えてセッション均等の平均・符号数。重複観測を独立標本とみなしたp値は出さない。',
        コードSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    )


def load_ready() -> dict:
    """機能: 既存の入力から場開始・場末の既定時刻を取得する。

    引数: なし。返り値: 場と銘柄をキーとする入力辞書(dict)。
    """
    sys.path.insert(0, str(ROOT / 'work/wave_v51/overlay'))
    import research
    return research.load()[0]


def imbalance(up: float, down: float) -> float:
    """機能: 非負二量の方向差を総量で割り、無事象を欠測にする。

    引数: up/down(float)。返り値: 偏りまたはNaN(float)。
    """
    return (up - down) / (up + down) if up + down > 0 else np.nan


def build_account(frame: pd.DataFrame, ready: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """機能: 公開済み観測と将来ラベルを別々に作る。

    引数: frame(DataFrame)、ready(dict)。返り値: 特徴・ラベル・品質集計(tuple)。
    """
    a = {c: frame[c].to_numpy(dtype=float) for c in frame.columns}
    t = a['time_s']
    prefix = {c: np.r_[0., np.cumsum(a[c])] for c in (
        'exec_buy', 'exec_sell', 'exec_unknown', 'source_volume_delta',
        'noexec_ask_remove', 'noexec_bid_remove', 'noexec_bid_add', 'noexec_ask_add',
        'refill_bid_fixed_quote', 'refill_ask_fixed_quote', 'both_up', 'both_down', 'quote_ticks',
        'raw_events', 'valid_events', 'continuity_resets', 'volume_resets', 'unavailable_volume_events',
        'depth_incomplete_events', 'depth_disordered_events', 'depth_duplicate_events')}
    rows, labels = [], []
    quality = dict(起点候補=0, 過去価格不足=0, ATR不足=0, 現在品質不良=0, 採用起点=0,
                   未来ラベル不足={str(h): 0 for h in HORIZONS})
    for origin in np.arange(ready['start'] + 1200., ready['limit'], 60.):
        quality['起点候補'] += 1
        at = np.searchsorted(t, [origin - 300, origin - 60, origin], side='right') - 1
        if min(at) < 0 or any(q - t[ix] > 60. for q, ix in zip([origin - 300, origin - 60, origin], at)):
            quality['過去価格不足'] += 1
            continue
        k5, k1, k = at
        atr = a['atr'][k]
        if not np.isfinite(atr) or atr <= 0:
            quality['ATR不足'] += 1
            continue
        left = max(np.searchsorted(t, origin - 60., side='right'),
                   np.searchsorted(a['source_time_s'], origin - 60., side='left'))
        right = k + 1
        get = lambda name: prefix[name][right] - prefix[name][left]
        if (right - left < 2 or get('valid_events') < 2 or
            a['source_age'][left:right].max(initial=0) > 60 or
            a['source_time_s'][left:right].min(initial=origin) < origin - 60 or
            get('continuity_resets') > 0 or get('volume_resets') > 0 or get('unavailable_volume_events') > 0 or
            get('depth_incomplete_events') > 0 or get('depth_disordered_events') > 0 or get('depth_duplicate_events') > 0):
            quality['現在品質不良'] += 1
            continue
        quality['採用起点'] += 1
        price = a['mid'][k]
        buy, sell, unknown = (get(x) for x in ('exec_buy', 'exec_sell', 'exec_unknown'))
        vol = buy + sell + unknown
        weights = a['valid_events'][left:right]
        near_bid = np.average(a['supply_bid_near'][left:right], weights=weights)
        near_ask = np.average(a['supply_ask_near'][left:right], weights=weights)
        r1, r5 = (price - a['mid'][k1]) / atr, (price - a['mid'][k5]) / atr
        checkpoints = np.arange(origin - 300., origin + .1, 60.)
        cp = np.searchsorted(t, checkpoints, side='right') - 1
        if np.any(checkpoints - t[cp] > 60.):
            quality['採用起点'] -= 1
            quality['過去価格不足'] += 1
            continue
        rv5 = np.sqrt(np.sum(np.diff(a['mid'][cp]) ** 2)) / atr
        row = dict(time_s=float(origin), observed_time=float(t[k]), seq=int(a['seq'][k]),
                   mid=float(price), atr=float(atr), r1=float(r1), r5=float(r5),
                   last_r1=float((a['last'][k] - a['last'][k1]) / atr), quote_ticks_60=float(get('quote_ticks')),
                   abs_r1=abs(r1), abs_r5=abs(r5), rv5=float(rv5), log_volume=float(np.log1p(vol)),
                   spread_atr=float((a['ask'][k] - a['bid'][k]) / atr),
                   log_depth=float(np.log1p(near_bid + near_ask)),
                   night=int('Night' in ready['session']),
                   elapsed_fraction=float((origin - ready['start']) / (ready['limit'] - ready['start'])),
                   execution=(buy - sell) / vol if vol > 0 else np.nan,
                   withdrawal=imbalance(get('noexec_ask_remove'), get('noexec_bid_remove')),
                   addition=imbalance(get('noexec_bid_add'), get('noexec_ask_add')),
                   recovery=imbalance(get('refill_bid_fixed_quote'), get('refill_ask_fixed_quote')),
                   supply=imbalance(near_bid, near_ask), repricing=imbalance(get('both_up'), get('both_down')),
                   volume=float(vol), unknown_fraction=unknown / vol if vol else np.nan,
                   valid_events=int(get('valid_events')), blocks=right - left,
                   source_max_age=float(a['source_age'][left:right].max(initial=0)),
                   nonoverlap=bool(round((origin - ready['start'] - 1200.) / 60.) % 15 == 0))
        rows.append(row)
        lab = dict(time_s=float(origin))
        for horizon in HORIZONS:
            end = origin + horizon
            j = np.searchsorted(t, end, side='right') - 1
            if end > ready['limit'] or j <= k or end - t[j] > 60:
                quality['未来ラベル不足'][str(horizon)] += 1
                lab.update({f'y{horizon}': np.nan, f'up{horizon}': np.nan, f'down{horizon}': np.nan,
                            f'max_gap{horizon}': np.nan})
                continue
            path = a['mid'][k + 1:j + 1]
            lab.update({f'y{horizon}': float((a['mid'][j] - price) / atr),
                        f'up{horizon}': float(max(0., path.max() - price) / atr),
                        f'down{horizon}': float(max(0., price - path.min()) / atr),
                        f'max_gap{horizon}': float(np.diff(np.r_[origin, t[k + 1:j + 1], end]).max(initial=0))})
        labels.append(lab)
    return pd.DataFrame(rows), pd.DataFrame(labels), quality


def correlate(x: np.ndarray, y: np.ndarray) -> float | None:
    """機能: 定数・小標本を欠測にして相関を計算する。

    引数: x/y(ndarray)。返り値: 相関(float|None)。
    """
    return float(np.corrcoef(x, y)[0, 1]) if len(x) >= 5 and np.std(x) > 1e-12 and np.std(y) > 1e-12 else None


def average(x: np.ndarray) -> float | None:
    """機能: 空標本を欠測にして平均を計算する。

    引数: x(ndarray)。返り値: 平均(float|None)。
    """
    return float(np.mean(x)) if len(x) else None


def basic_stat(y: np.ndarray) -> dict:
    """機能: ラベル群の件数・平均・中央値・正負を要約する。

    引数: y(ndarray)。返り値: 統計辞書(dict)。
    """
    return dict(n=len(y), mean=average(y), median=float(np.median(y)) if len(y) else None,
                positive=float(np.mean(y > 0)) if len(y) else None)


def controls(part: pd.DataFrame, mean: np.ndarray, scale: np.ndarray) -> np.ndarray:
    """機能: 先頭期間の尺度で価格対照を作る。

    引数: part(DataFrame)、mean/scale(ndarray)。返り値: 説明行列(ndarray)。
    """
    return np.column_stack([np.ones(len(part)), (part[list(CONTROL_NAMES)].to_numpy() - mean) / scale])


def analyze_joint(observations: pd.DataFrame, labels: pd.DataFrame) -> dict:
    """機能: 先頭期間で固定した対照・分位境界の別期間での関係を測る。

    引数: observations/labels(DataFrame)。返り値: 全指標・場別統計(dict)。
    """
    data = observations.merge(labels, on=['session', 'symbol', 'time_s'], validate='one_to_one')
    report, thresholds, models = [], [], []
    for symbol in ('TOPIX', 'NK225'):
        all_symbol = data.loc[data.symbol == symbol].copy()
        for horizon in HORIZONS:
            group = all_symbol.loc[np.isfinite(all_symbol[f'y{horizon}'])].copy()
            train = group.loc[group.period == PERIODS[0]]
            mean = train[list(CONTROL_NAMES)].mean().to_numpy()
            scale = train[list(CONTROL_NAMES)].std(ddof=0).to_numpy().copy()
            scale[scale < 1e-8] = 1.
            for feature in FEATURES:
                available = group.loc[np.isfinite(group[feature])].copy()
                ftrain = available.loc[available.period == PERIODS[0]]
                q1, q2 = np.quantile(ftrain[feature], [1 / 3, 2 / 3])
                xtrain = controls(ftrain, mean, scale)
                beta_y = np.linalg.lstsq(xtrain, ftrain[f'y{horizon}'].to_numpy(), rcond=None)[0]
                beta_x = np.linalg.lstsq(xtrain, ftrain[feature].to_numpy(), rcond=None)[0]
                available['price_prediction'] = controls(available, mean, scale) @ beta_y
                available['residual_y'] = available[f'y{horizon}'] - available.price_prediction
                available['residual_x'] = available[feature] - controls(available, mean, scale) @ beta_x
                train_residual = available.loc[available.period == PERIODS[0]]
                denominator = np.sum(train_residual.residual_x.to_numpy() ** 2)
                feature_beta = float(np.sum(train_residual.residual_x * train_residual.residual_y) / denominator) if denominator > 1e-12 else 0.
                models.append(dict(symbol=symbol, horizon=horizon, feature=feature, names=['切片', *CONTROL_NAMES],
                                   mean=mean.tolist(), scale=scale.tolist(), beta_y=beta_y.tolist(), feature_beta=feature_beta))
                available['tercile'] = np.where(available[feature] <= q1, '下', np.where(available[feature] >= q2, '上', '中'))
                available['direction'] = np.sign(available[feature])
                available['state'] = np.where(available.direction * available.r1 > 0, '進行', '不進行')
                thresholds.append(dict(symbol=symbol, horizon=horizon, feature=feature, lower=float(q1), upper=float(q2),
                                       collapse=bool(q1 == q2), beta_x=beta_x.tolist(), train_n=len(ftrain)))
                for period in PERIODS:
                    for sampling in ('60秒', '15分非重複'):
                        part = available.loc[(available.period == period) &
                                             (True if sampling == '60秒' else available.nonoverlap)]
                        per_session = []
                        for session, item in part.groupby('session'):
                            low = item.loc[item.tercile == '下', 'residual_y'].to_numpy()
                            high = item.loc[item.tercile == '上', 'residual_y'].to_numpy()
                            per_session.append(dict(session=session, n=len(item),
                                partial_corr=correlate(item.residual_x.to_numpy(), item.residual_y.to_numpy()),
                                upper_minus_lower=average(high) - average(low) if len(high) and len(low) else None,
                                signed_residual=average((item.direction * item.residual_y).to_numpy())))
                        effects = [s['upper_minus_lower'] for s in per_session if s['upper_minus_lower'] is not None]
                        groups = {tag: dict(raw=basic_stat(part.loc[part.tercile == tag, f'y{horizon}'].to_numpy()),
                                            adjusted=basic_stat(part.loc[part.tercile == tag, 'residual_y'].to_numpy()))
                                  for tag in ('下', '中', '上')}
                        states = []
                        for state in ('進行', '不進行'):
                            s = part.loc[(part.direction != 0) & (part.state == state)]
                            direction = s.direction.to_numpy()
                            states.append(dict(state=state, n=len(s),
                                direction_y=basic_stat(direction * s[f'y{horizon}'].to_numpy()),
                                direction_residual=basic_stat(direction * s.residual_y.to_numpy()),
                                favorable=average(np.where(direction > 0, s[f'up{horizon}'], s[f'down{horizon}'])),
                                adverse=average(np.where(direction > 0, s[f'down{horizon}'], s[f'up{horizon}']))))
                        report.append(dict(symbol=symbol, horizon=horizon, feature=feature, name=FEATURES[feature],
                            period=period, sampling=sampling, n=len(part),
                            path_gap_over60=int((part[f'max_gap{horizon}'] > 60).sum()),
                            raw_corr=correlate(part[feature].to_numpy(), part[f'y{horizon}'].to_numpy()),
                            partial_corr=correlate(part.residual_x.to_numpy(), part.residual_y.to_numpy()),
                            mean_square_price=average(part.residual_y.to_numpy() ** 2),
                            mean_square_with_feature=average((part.residual_y.to_numpy() - feature_beta * part.residual_x.to_numpy()) ** 2),
                            groups=groups, states=states, sessions=per_session,
                            session_equal_effect=average(np.asarray(effects)),
                            positive_sessions=sum(v > 0 for v in effects), negative_sessions=sum(v < 0 for v in effects),
                            comparable_sessions=len(effects)))
    return dict(指標別=report, 分位境界=thresholds, 価格対照=models)


def add_peer(observations: pd.DataFrame) -> tuple[pd.DataFrame, list]:
    """機能: 60秒遅れで相手観測を照合し、機構の両市場一致を記録する。

    引数: observations(DataFrame)。返り値: 相手追加表と品質(tuple)。
    """
    parts, audit = [], []
    for (session, symbol), own in observations.groupby(['session', 'symbol'], sort=True):
        peer = observations.loc[(observations.session == session) & (observations.symbol != symbol)]
        pt = peer.time_s.to_numpy()
        ix = np.searchsorted(pt, own.time_s.to_numpy() - 60., side='right') - 1
        valid = ix >= 0
        valid[valid] &= (own.time_s.to_numpy()[valid] - 60. - pt[ix[valid]]) <= 60.
        own = own.copy()
        for feature in FEATURES:
            values = np.full(len(own), np.nan)
            values[valid] = peer[feature].to_numpy()[ix[valid]]
            own[f'peer_{feature}'] = values
        audit.append(dict(session=session, symbol=symbol, n=len(own), peer_valid=int(valid.sum())))
        parts.append(own)
    return pd.concat(parts, ignore_index=True), audit


def analyze_peer(obs: pd.DataFrame, labels: pd.DataFrame) -> list:
    """機能: 自分の機構方向と相手機構の一致別に将来経路を記録する。

    引数: obs/labels(DataFrame)。返り値: 両市場比較(list)。
    相手一致を独立した二票とは扱わず、自己価格を揃えない記述比較と明記する。
    """
    data = obs.merge(labels, on=['session', 'symbol', 'time_s'], validate='one_to_one')
    out = []
    for feature in FEATURES:
        for (symbol, period), part in data.groupby(['symbol', 'period']):
            d, p = np.sign(part[feature].to_numpy()), np.sign(part[f'peer_{feature}'].to_numpy())
            valid = np.isfinite(d) & np.isfinite(p) & (d != 0) & (p != 0) & np.isfinite(part.y300)
            for agreement in (True, False):
                select = valid & ((d == p) == agreement)
                item = part.loc[select]
                signed = d[select] * item.y300.to_numpy()
                out.append(dict(feature=feature, symbol=symbol, period=period,
                                agreement=agreement, **basic_stat(signed)))
    return out


def describe_present(features: dict, observations: pd.DataFrame) -> dict:
    """機能: 同区間で価格形成代理がどう共存したかを将来予測と分けて集計する。

    引数: features(dict)、observations(DataFrame)。返り値: 同区間の記述統計(dict)。
    過去の価格変化が板追加を誘った逆方向の関係を識別したとは解釈しない。
    """
    windows, blocks = [], []
    sessions = sorted({key[0] for key in features})
    for (symbol, period), part in observations.groupby(['symbol', 'period']):
        changed_mid = np.abs(part.r1) > 1e-9
        changed_last = np.abs(part.last_r1) > 1e-9
        price_summary = dict(n=len(part),
            last_only=int((~changed_mid & changed_last).sum()),
            mid_only=int((changed_mid & ~changed_last).sum()),
            both=int((changed_mid & changed_last).sum()),
            neither=int((~changed_mid & ~changed_last).sum()))
        for feature in FEATURES:
            valid = part.loc[np.isfinite(part[feature])]
            states = {}
            for direction, label in ((-1, '下落'), (0, '横ばい'), (1, '上昇')):
                item = valid.loc[np.sign(valid.r1) == direction]
                states[label] = dict(n=len(item), feature_mean=average(item[feature].to_numpy()),
                    same_sign=float(np.mean(np.sign(item[feature]) == direction)) if len(item) else None)
            windows.append(dict(symbol=symbol, period=period, feature=feature,
                corr_with_r1=correlate(valid[feature].to_numpy(), valid.r1.to_numpy()),
                corr_with_source_quote_ticks=correlate(valid[feature].to_numpy(), valid.quote_ticks_60.to_numpy()),
                states=states, price_changes=price_summary))
    for key, frame in sorted(features.items()):
        session, symbol = key
        valid = frame.loc[(frame.source_age <= 60) & (frame.continuity_resets == 0) &
            (frame.volume_resets == 0) & (frame.unavailable_volume_events == 0) &
            (frame.depth_incomplete_events == 0) & (frame.depth_disordered_events == 0) &
            (frame.depth_duplicate_events == 0)]
        q = valid.quote_ticks.to_numpy()
        measurements = dict(
            execution=(valid.exec_buy - valid.exec_sell) / valid.source_volume_delta.replace(0, np.nan),
            withdrawal=(valid.noexec_ask_remove - valid.noexec_bid_remove) /
                       (valid.noexec_ask_remove + valid.noexec_bid_remove).replace(0, np.nan),
            addition=(valid.noexec_bid_add - valid.noexec_ask_add) /
                     (valid.noexec_bid_add + valid.noexec_ask_add).replace(0, np.nan),
            recovery=(valid.refill_bid_fixed_quote - valid.refill_ask_fixed_quote) /
                     (valid.refill_bid_fixed_quote + valid.refill_ask_fixed_quote).replace(0, np.nan),
            supply=(valid.supply_bid_near - valid.supply_ask_near) /
                   (valid.supply_bid_near + valid.supply_ask_near).replace(0, np.nan))
        relations = []
        for feature, value in measurements.items():
            ok = np.isfinite(value.to_numpy())
            relations.append(dict(feature=feature, n=int(ok.sum()),
                                  corr_with_source_quote_ticks=correlate(value.to_numpy()[ok], q[ok])))
        blocks.append(dict(session=session, symbol=symbol,
            period=PERIODS[0 if sessions.index(session) < 10 else 1 if sessions.index(session) < 19 else 2],
            n=len(valid), excluded=len(frame) - len(valid),
            changed_quote=int((np.abs(q) > 1e-9).sum()),
            changed_quote_without_volume=int(((np.abs(q) > 1e-9) & (valid.source_volume_delta.to_numpy() == 0)).sum()),
            no_quote_change_with_volume=int(((np.abs(q) <= 1e-9) & (valid.source_volume_delta.to_numpy() > 0)).sum()),
            relations=relations))
    return dict(説明='同区間の共存関係。価格が先に変わって数量が追随した場合を含む。未来予測力や因果の証拠とは別。',
                六十秒窓=windows, 公開ブロック別=blocks)


def main() -> None:
    """機能: 仕様固定と公開特徴の期間別分析を実行する。

    引数: CLIの--freezeのみ。返り値: なし(None)。売買注文・現在APIを使わない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--freeze', action='store_true')
    args = parser.parse_args()
    spec_path = HERE / '観測解析固定.json'
    if args.freeze:
        if spec_path.exists():
            raise RuntimeError('既存の事前固定を上書きしません。修正理由を残してください。')
        save(spec_path, fixed_spec())
        return
    if not spec_path.exists():
        raise RuntimeError('分析前に --freeze を実行してください。')
    features = pickle.loads((MEASUREMENT / 'features.pkl').read_bytes())
    ready = load_ready()
    sessions = sorted({key[0] for key in features})
    parts, futures, audit = [], [], []
    for key, frame in sorted(features.items()):
        observation, label, check = build_account(frame, ready[key])
        for value in (observation, label):
            value['session'], value['symbol'] = key
        observation['period'] = PERIODS[0 if sessions.index(key[0]) < 10 else 1 if sessions.index(key[0]) < 19 else 2]
        parts.append(observation)
        futures.append(label)
        audit.append(dict(session=key[0], symbol=key[1], **check))
    observations, labels = pd.concat(parts, ignore_index=True), pd.concat(futures, ignore_index=True)
    observations, peer_audit = add_peer(observations)
    observations.to_pickle(HERE / '観測.pkl')
    labels.to_pickle(HERE / '将来ラベル.pkl')
    save(HERE / '品質.json', dict(口座別=audit, 相手照合=peer_audit, 観測数=len(observations), 将来情報を特徴に混入=False))
    result = analyze_joint(observations, labels)
    result['相手比較'] = analyze_peer(observations, labels)
    result['同区間観測'] = describe_present(features, observations)
    result['実行コードSHA256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result['注意'] = '既知データの条件付き関係。partial_corr列は前10場係数を固定した残差間相関で、後期間の価格効果を完全除去した通常の偏相関ではない。因果でも実トレードの利益でもない。'
    save(HERE / '観測結果.json', result)
    for period in PERIODS:
        separated = dict(期間=period, 指標別=[x for x in result['指標別'] if x['period'] == period],
            分位境界=result['分位境界'], 価格対照=result['価格対照'],
            相手比較=[x for x in result['相手比較'] if x['period'] == period],
            同区間観測=dict(説明=result['同区間観測']['説明'],
                六十秒窓=[x for x in result['同区間観測']['六十秒窓'] if x['period'] == period],
                公開ブロック別=[x for x in result['同区間観測']['公開ブロック別'] if x['period'] == period]))
        save(HERE / f'{period}の観測.json', separated)
    print(f'{len(observations):,}起点、{len(result["指標別"]):,}比較を保存しました。')


if __name__ == '__main__':
    main()
