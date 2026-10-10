"""板圧力と将来価格の関係を、固定された非重複観測点で調べる。売買は行わない。"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCES = ('work/wave_v47', 'work/wave_v48/update_20260930', 'work/wave_v48/update_20261001',
           'work/wave_v50/update_20261001_day', 'work/wave_v50/update_20261002_two', 'work/wave_v50/update_20261007_added')
JST = timezone(timedelta(hours=9))


def save(name: str, value: object) -> None:
    """機能: 固定条件・観測値・集計を今回の分析領域へ保存する。

    引数: name(str)、value(object)。返り値: なし(None)。
    """
    HERE.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode('utf8')
    path = HERE / name
    path.write_bytes(gzip.compress(data, mtime=0) if path.suffix == '.gz' else data)


def freeze() -> dict:
    """機能: 市場性質の観測条件と品質基準を成績計算前に固定する。

    引数: なし。返り値: dict は固定設計。
    """
    spec = dict(目的='板圧力の価格説明と将来予測を分ける。新売買ルール・ランキング・最適化は行わない。',
                観測間隔秒=900, 初回='各場開始1800秒後', 観測終端='既存強制返済時刻limitの900秒前まで',
                入力窓秒=120, 結果時間秒=[60, 300, 900], 強圧力OFI絶対値=.20,
                OFI='公開済み120秒のofi_signed合計 / ofi_abs合計。絶対和が0なら0。',
                近接変化='公開済み120秒dflow_nearをvalid_event_countで加重平均。連続値で分析し圧力方向との符号一致も分類。',
                板数量偏り='120秒のpressure_nearを同じ有効イベント数で加重平均。',
                圧力と価格応答='圧力方向×直近120秒中値変化/現在ATR>=0.25は進行、絶対変化<=0.10は停滞、それ以外で圧力方向×変化<=-0.25は逆行、残りは中間。',
                価格方向閾値ATR=.10, 同調='自市場の強圧力方向と相手市場の強圧力方向が一致/反対/弱い/品質不足。',
                相手遅延秒=[60, 0], 主結果遅延秒=60,
                品質=dict(最終公開の古さ上限秒=60, 源ブロック古さ上限秒=60, 窓内最低公開数=5,
                          連続性リセットを含む窓=False, 窓内最大無公開間隔秒=60, 直近120秒前の評価価格古さ上限秒=60),
                評価価格='公開特徴行のmid。観測時計以下の最後の公開行だけ。源時刻・公開時刻とも60秒以内。未来補間なし。',
                ATR='現在評価価格の公開原本seq以前で利用可能な既存ready.atr。未来のATRで正規化しない。',
                将来評価='各先の時計以下の最後の公開mid。源時刻/公開時刻60秒以内、かつ観測時計より後の公開行が必要。',
                分割='先頭10場/次9場/既知追加4場/全23場。全データ既読で真正未見ではない。',
                統計='15分間隔で最大15分の結果区間が重ならない。銘柄別/期間別、点平均と場平均・場ごとの正負を併記。p値と独立点前提の信頼区間は出さない。',
                欠測='条件不足の観測は除外し、理由と件数を必ず保存。閾値を結果後に緩めない。',
                限界='板受信時刻がなくCurrentPriceTime由来の代理時計。取消と約定・同一主体の補充は分離できない。吸収は強圧力なのに価格が進まないという観測名に限る。')
    path = HERE / '条件固定.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf8')) == spec
    else:
        save('条件固定.json', spec)
    return spec


def load() -> tuple[dict, dict]:
    """機能: 保存済みの46口座と因果公開済み板特徴を読む。

    引数: なし。返り値: dict2個の組。
    """
    inputs, frames = {}, {}
    for i, source in enumerate(SOURCES):
        prefix = '' if i == 0 else 'new_'
        values = pickle.loads((ROOT / source / (prefix + 'inputs.pkl')).read_bytes())
        assert not set(values).intersection(inputs)
        inputs.update(values)
        frames.update(pickle.loads((ROOT / source / (prefix + 'features_depth.pkl')).read_bytes()))
    assert len(inputs) == len(frames) == 46
    return inputs, frames


def price_at(frame: pd.DataFrame, at: float) -> tuple[float | None, int, str]:
    """機能: その時点以前の品質を満たす最後の公開中値を探す。

    引数: frame(DataFrame)、at(float)。返り値: 中値/公開行位置/除外理由(tuple)。
    """
    i = int(np.searchsorted(frame.time_s.to_numpy(float), at, side='right')) - 1
    if i < 0:
        return None, i, '公開前'
    row = frame.iloc[i]
    if at - row.time_s > 60:
        return None, i, '最終公開60秒超'
    if row.block_delay_seconds > 60 or at - row.source_time_s > 60:
        return None, i, '源ブロック60秒超'
    if not np.isfinite(row.mid) or row.mid <= 0:
        return None, i, '評価中値不正'
    return float(row.mid), i, ''


def state_at(ready: dict, frame: pd.DataFrame, at: float) -> tuple[dict | None, str]:
    """機能: 現在までの公開板から圧力・価格反応を作る。

    引数: ready(dict)、frame(DataFrame)、at(float)。返り値: 状態/除外理由(tuple)。
    """
    price, i, reason = price_at(frame, at)
    if reason:
        return None, reason
    previous, _, reason = price_at(frame, at - 120)
    if reason:
        return None, '過去端点:' + reason
    times = frame.time_s.to_numpy(float)
    left = int(np.searchsorted(times, at - 120, side='right'))
    window = frame.iloc[left:i + 1]
    if len(window) < 5:
        return None, '窓内公開5件未満'
    if np.max(window.block_delay_seconds.to_numpy(float)) > 60:
        return None, '窓内源ブロック60秒超'
    if window.continuity_reset_count.sum() > 0:
        return None, '窓内連続性リセット'
    if np.max(np.diff(np.r_[at - 120, window.time_s.to_numpy(float), at])) > 60:
        return None, '窓内無公開60秒超'
    sequence = int(frame.iloc[i].seq)
    index = int(np.searchsorted(ready['seq'], sequence, side='right')) - 1
    if index < 0 or not np.isfinite(ready['atr'][index]) or ready['atr'][index] <= 0:
        return None, 'ATR未準備'
    atr = float(ready['atr'][index])
    signed = float(window.ofi_signed.sum())
    absolute = float(window.ofi_abs.sum())
    ofi = signed / absolute if absolute > 0 else 0.
    weights = window.valid_event_count.to_numpy(float)
    assert weights.sum() > 0
    near = float(np.average(window.dflow_near.to_numpy(float), weights=weights))
    pressure = float(np.average(window.pressure_near.to_numpy(float), weights=weights))
    response = (price - previous) / atr
    direction = int(np.sign(ofi)) if abs(ofi) >= .20 else 0
    motion = int(np.sign(response)) if abs(response) >= .10 else 0
    phase = '弱圧力'
    if direction:
        if direction * response >= .25:
            phase = '圧力方向へ進行'
        elif abs(response) <= .10:
            phase = '強圧力だが停滞'
        elif direction * response <= -.25:
            phase = '圧力と逆へ進行'
        else:
            phase = '強圧力で中間'
    return dict(at=at, published=float(frame.iloc[i].time_s), source=float(frame.iloc[i].source_time_s),
                source_last_seq=int(frame.iloc[i].source_last_seq), published_seq=sequence,
                price=price, atr=atr, ofi=ofi, near=near, pressure=pressure, response=response,
                direction=direction, motion=motion, phase=phase, window_releases=len(window)), ''


def collect(inputs: dict, frames: dict) -> tuple[list[dict], list[dict]]:
    """機能: 固定した観測時計ごとに現在状態と、その後だけの価格結果を別々に保存する。

    引数: inputs/frames(dict)。返り値: 観測行と品質件数(tuple)。
    """
    output, quality = [], []
    for key, ready in sorted(inputs.items()):
        other = key[0], 'NK225' if key[1] == 'TOPIX' else 'TOPIX'
        reasons = Counter()
        anchors = np.arange(ready['start'] + 1800, ready['limit'] - 900 + .01, 900)
        valid = 0
        for at in anchors:
            state, reason = state_at(ready, frames[key], float(at))
            if reason:
                reasons[reason] += 1
                continue
            valid += 1
            future = {}
            for horizon in (60, 300, 900):
                price, idx, why = price_at(frames[key], at + horizon)
                if not why and frames[key].iloc[idx].time_s <= at:
                    why = '観測後の公開なし'
                future[str(horizon)] = None if why else (price - state['price']) / state['atr']
                if why:
                    reasons[f'結果{horizon}秒:' + why] += 1
            peer = {}
            for delay in (60, 0):
                other_state, why = state_at(inputs[other], frames[other], at - delay)
                if why:
                    peer[str(delay)] = dict(category='品質不足', reason=why)
                else:
                    direction = state['direction']
                    category = '自市場弱圧力' if not direction else '相手弱圧力' if not other_state['direction'] else '同調' if other_state['direction'] == direction else '不一致'
                    peer[str(delay)] = dict(category=category, ofi=other_state['ofi'], near=other_state['near'],
                                            response=other_state['response'], published=other_state['published'])
            output.append(dict(session=key[0], symbol=key[1], time=datetime.fromtimestamp(at, JST).isoformat(),
                               state=state, peer=peer, future=future))
        quality.append(dict(session=key[0], symbol=key[1], anchors=len(anchors), valid=valid, reasons=dict(reasons)))
    return output, quality


def stats(rows: list[dict], horizon: str, direction_field: str = 'direction') -> dict:
    """機能: 将来方向一致と変化を、点平均と場平均に分けて記述する。

    引数: rows(list[dict])、horizon/direction_field(str)。返り値: dict は記述統計。
    """
    values, per_session = [], {}
    sync = []
    for row in rows:
        direction = row['state'][direction_field]
        result = row['future'][horizon]
        if not direction or result is None:
            continue
        value = direction * result
        values.append(value)
        per_session.setdefault(row['session'], []).append(value)
        sync.append(direction * row['state']['response'])
    arr = np.asarray(values, float)
    means = [float(np.mean(v)) for v in per_session.values()]
    positives = int((arr > 0).sum())
    negatives = int((arr < 0).sum())
    return dict(n=len(arr), sessions=len(per_session), positive=positives, negative=negatives,
                flat=int((arr == 0).sum()), hit_rate=positives / len(arr) if len(arr) else None,
                hit_rate_nonflat=positives / (positives + negatives) if positives + negatives else None,
                mean=float(arr.mean()) if len(arr) else None, median=float(np.median(arr)) if len(arr) else None,
                same_window_mean=float(np.mean(sync)) if sync else None,
                equal_session_mean=float(np.mean(means)) if means else None,
                positive_sessions=sum(v > 0 for v in means), negative_sessions=sum(v < 0 for v in means),
                session_means={key: float(np.mean(v)) for key, v in per_session.items()})


def correlate(rows: list[dict], feature: str, horizon: str) -> dict:
    """機能: 現在板特徴と将来変化の相関を銘柄内・期間内で記述する。

    引数: rows(list[dict])、feature/horizon(str)。返り値: dict は相関と観測数。
    """
    pairs = [(r['state'][feature], r['future'][horizon], r['session']) for r in rows if r['future'][horizon] is not None]
    if len(pairs) < 3:
        return dict(n=len(pairs), pearson=None, spearman=None)
    x, y = np.array([p[0] for p in pairs]), np.array([p[1] for p in pairs])
    if x.std() == 0 or y.std() == 0:
        return dict(n=len(pairs), pearson=None, spearman=None)
    return dict(n=len(pairs), pearson=float(np.corrcoef(x, y)[0, 1]),
                spearman=float(np.corrcoef(pd.Series(x).rank().to_numpy(), pd.Series(y).rank().to_numpy())[0, 1]))


def summarize(rows: list[dict], names: list[str]) -> dict:
    """機能: 固定分類の全結果を市場別・期間別に並べ、良い部分だけ選ばない。

    引数: rows(list[dict])、names(list[str])。返り値: dict は全分類の集計。
    """
    groups = dict(先頭10=names[:10], 次9=names[10:19], 既知追加4=names[19:], 全23=names)
    results = []
    correlations = []
    for period, selected in groups.items():
        for symbol in ('TOPIX', 'NK225'):
            current = [r for r in rows if r['session'] in selected and r['symbol'] == symbol]
            strong = [r for r in current if r['state']['direction']]
            classifications = {'強圧力すべて': strong,
                               '圧力方向へ進行': [r for r in strong if r['state']['phase'] == '圧力方向へ進行'],
                               '強圧力だが停滞': [r for r in strong if r['state']['phase'] == '強圧力だが停滞'],
                               '圧力と逆へ進行': [r for r in strong if r['state']['phase'] == '圧力と逆へ進行'],
                               '強圧力で中間': [r for r in strong if r['state']['phase'] == '強圧力で中間'],
                               '近接数量変化も圧力支持': [r for r in strong if r['state']['near'] * r['state']['direction'] > 0],
                               '近接数量変化は圧力と逆': [r for r in strong if r['state']['near'] * r['state']['direction'] < 0]}
            for delay in (60, 0):
                for category in ('同調', '不一致', '相手弱圧力', '品質不足'):
                    classifications[f'相手{delay}秒遅延:{category}'] = [r for r in strong if r['peer'][str(delay)]['category'] == category]
            for name, chosen in classifications.items():
                results.append(dict(period=period, symbol=symbol, category=name, observations=len(chosen),
                                    outcomes={h: stats(chosen, h) for h in ('60', '300', '900')}))
            results.append(dict(period=period, symbol=symbol, category='同じ品質点の直近価格方向のみ', observations=sum(r['state']['motion'] != 0 for r in current),
                                outcomes={h: stats(current, h, 'motion') for h in ('60', '300', '900')}))
            for feature in ('ofi', 'near', 'pressure', 'response'):
                correlations.append(dict(period=period, symbol=symbol, feature=feature,
                                         outcomes={h: correlate(current, feature, h) for h in ('60', '300', '900')}))
    return dict(期間=groups, 分類=results, 連続値の相関=correlations)


def audit(inputs: dict, frames: dict, rows: list[dict]) -> dict:
    """機能: 観測の非重複、将来未参照、源行と公開行の順序を確認する。

    引数: inputs/frames(dict)、rows(list[dict])。返り値: dict は監査結果。
    """
    count = 0
    for key, ready in inputs.items():
        chosen = [r for r in rows if (r['session'], r['symbol']) == key]
        times = [r['state']['at'] for r in chosen]
        assert all(b - a >= 900 for a, b in zip(times, times[1:]))
        for row in chosen:
            assert row['state']['source_last_seq'] < row['state']['published_seq']
        if not chosen:
            continue
        for row in (chosen[len(chosen) // 3], chosen[len(chosen) * 2 // 3]):
            at = row['state']['at']
            frame = frames[key]
            prefix = frame.loc[frame.time_s <= at].copy()
            expected, reason = state_at(ready, frame, at)
            trimmed, trimmed_reason = state_at(ready, prefix, at)
            assert reason == trimmed_reason and expected == trimmed
            changed = frame.copy()
            for column in ('mid', 'ofi_signed', 'ofi_abs', 'dflow_near', 'pressure_near'):
                changed.loc[changed.time_s > at, column] = 987654
            altered, altered_reason = state_at(ready, changed, at)
            assert altered_reason == reason and altered == expected
            count += 1
    return dict(全合格=True, 状態の未来変更接頭辞比較数=count, 結果区間最大900秒と観測間隔900秒で重複なし=True,
                同市場源行公開行順序=True, 注文生成なし=True, 最適化なし=True, API取得数=0)


def main() -> None:
    """機能: 固定観測による板性質分析を実行し、全結果と品質・監査を保存する。

    引数: なし。返り値: なし(None)。
    """
    freeze()
    inputs, frames = load()
    rows, quality = collect(inputs, frames)
    names = sorted({key[0] for key in inputs})
    save('観測点.json.gz', rows)
    save('品質件数.json', quality)
    save('市場性質結果.json', summarize(rows, names))
    save('監査.json', audit(inputs, frames, rows) | dict(実装SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))
    print(json.dumps(dict(観測候補=sum(r['anchors'] for r in quality), 品質有効=sum(r['valid'] for r in quality),
                          市場別={s: sum(r['symbol'] == s for r in rows) for s in ('TOPIX', 'NK225')}), ensure_ascii=False))


if __name__ == '__main__':
    main()
