"""固定定義に従い、米国開始前後の気配を夜単位で記述比較する。"""

from __future__ import annotations

import hashlib
import json
import pickle
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
DEFINITION_SHA = 'cfbabb6c2148b15301a1353753880201f630e5b1c94dd8d68d58f639f9c14966'


def finite(value: float) -> float | None:
    """非有限値をJSONで表現できる値へ変換する。

    引数: value (float): 数値。
    返り値: float | None: 有限の数値または欠測。
    """
    return float(value) if np.isfinite(value) else None


def minute_observations(t: np.ndarray, bid: np.ndarray, ask: np.ndarray) -> dict:
    """各分内で最後に観測された正常気配だけを選ぶ。

    引数: t, bid, ask (ndarray): 時間順の正常気配。
    返り値: dict: 分番号と中値、気配差の疎な配列。
    """
    minute = np.floor(t / 60).astype(np.int64)
    last = np.r_[np.flatnonzero(np.diff(minute)), len(minute) - 1]
    return dict(minute=minute[last], mid=(bid[last] + ask[last]) / 2,
                spread=ask[last] - bid[last])


def describe_window(t: np.ndarray, bid: np.ndarray, ask: np.ndarray,
                    lo: float, hi: float) -> dict:
    """一つの時間窓の値幅、方向性、往復、気配差を記述する。

    引数: t, bid, ask (ndarray): 正常気配。lo, hi (float): 窓の開始と排他的終点。
    返り値: dict: 注文を生成しない記述指標。
    """
    left, right = np.searchsorted(t, [lo, hi], side='left')
    tx, bx, ax = t[left:right], bid[left:right], ask[left:right]
    if len(tx) < 2:
        return dict(rows=int(len(tx)), minutes=0)
    mx = (bx + ax) / 2
    minute = minute_observations(tx, bx, ax)
    adjacent = np.diff(minute['minute']) == 1
    dx = np.diff(minute['mid'])
    valid_dx = dx[adjacent]
    path = float(np.sum(np.abs(valid_dx)))
    flips, pairs = 0, 0
    breaks = np.r_[0, np.flatnonzero(~adjacent) + 1, len(minute['mid'])]
    for begin, end in zip(breaks[:-1], breaks[1:]):
        changes = np.diff(minute['mid'][begin:end])
        signs = np.sign(changes[changes != 0])
        if len(signs) > 1:
            pairs += len(signs) - 1
            flips += int(np.count_nonzero(signs[1:] != signs[:-1]))
    width = float(np.ptp(mx))
    hours = (hi - lo) / 3600
    clocks = np.diff(tx)
    return dict(
        rows=int(len(tx)), minutes=int(len(minute['minute'])), expected_minutes=int((hi-lo)/60),
        minute_coverage=len(minute['minute']) / ((hi-lo)/60),
        adjacent_minute_changes=int(np.count_nonzero(adjacent)),
        range_mid=width, range_minute_mid=float(np.ptp(minute['mid'])),
        abs_start_end=float(abs(mx[-1] - mx[0])),
        range_per_hour=width/hours, minute_path_per_hour=path/hours,
        efficiency=abs(float(np.sum(valid_dx)))/path if path else 0,
        reversal_fraction=flips/pairs if pairs else None,
        reversal_pairs=int(pairs), reversal_count=int(flips),
        spread_row_median=float(np.median(ax-bx)), spread_row_p90=float(np.quantile(ax-bx, .9)),
        spread_minute_median=float(np.median(minute['spread'])),
        spread_minute_p90=float(np.quantile(minute['spread'], .9)),
        spread_range_fraction=float(np.median(minute['spread']))/width if width else None,
        rows_per_hour=len(tx)/hours,
        bbo_changes_per_hour=int(np.count_nonzero((np.diff(bx)!=0)|(np.diff(ax)!=0)))/hours,
        clock_updates_per_hour=int(np.count_nonzero(clocks>0))/hours,
        gaps_over120=int(np.count_nonzero(clocks>120)),
        first_observation=float(tx[0]), last_observation=float(tx[-1]))


def causal_slope(minute: dict, anchor: float, length: int) -> float | None:
    """アンカー時点で確定した連続分末中値のOLS傾きを返す。

    引数: minute (dict): 分末資料。anchor (float): 判断時計。length (int): 本数。
    返り値: float | None: pt/分の傾き、資料不足なら欠測。
    """
    end = np.searchsorted(minute['minute'], int(anchor//60), side='left')
    if end < length:
        return None
    keys = minute['minute'][end-length:end]
    if keys[-1] != int(anchor//60)-1 or np.any(np.diff(keys) != 1):
        return None
    x = np.arange(length, dtype=float) - (length-1)/2
    return float(np.dot(minute['mid'][end-length:end], x/(x@x)))


def anchor_events(t: np.ndarray, bid: np.ndarray, ask: np.ndarray,
                  minute: dict, lo: float) -> tuple[list, list]:
    """固定アンカーで両方向の到達と先着を測る。

    引数: t, bid, ask (ndarray): 気配。minute (dict): 分末資料。lo (float): 窓開始。
    返り値: tuple[list,list]: 完了事象と除外アンカーの記録。
    """
    events, missing = [], []
    for slot in range(10):
        nominal = lo + slot*1800
        index = int(np.searchsorted(t, nominal, side='left'))
        if index >= len(t) or t[index] - nominal > 60:
            missing.append(dict(slot=slot, reason='開始気配なし'))
            continue
        end_time = t[index]+1800
        end = int(np.searchsorted(t, end_time, side='right'))
        if end <= index+1 or end_time-t[end-1] > 60:
            missing.append(dict(slot=slot, reason='終点気配なし'))
            continue
        gap = bool(np.any(np.diff(t[index:end]) > 120))
        slope5 = causal_slope(minute, t[index], 5)
        slope10 = causal_slope(minute, t[index], 10)
        signal = 0
        if slot > 0 and slope5 is not None and slope10 is not None:
            if slope5 >= 4 and slope10 >= 1:
                signal = 1
            elif slope5 <= -4 and slope10 <= -1:
                signal = -1
        for side in (1, -1):
            moves = bid[index+1:end]-ask[index] if side == 1 else bid[index]-ask[index+1:end]
            for barrier in (50, 100, 200):
                good = np.flatnonzero(moves >= barrier)
                bad = np.flatnonzero(moves <= -barrier)
                first_good = int(good[0]) if len(good) else len(moves)
                first_bad = int(bad[0]) if len(bad) else len(moves)
                outcome = '順行先着' if first_good < first_bad else '逆行先着' if first_bad < first_good else '未到達'
                events.append(dict(slot=slot, nominal=float(nominal), anchor=float(t[index]),
                    side=side, barrier=barrier, gap_over120=gap,
                    favorable_reached=bool(len(good)), adverse_reached=bool(len(bad)),
                    favorable_first=outcome=='順行先着', adverse_first=outcome=='逆行先着',
                    neither=outcome=='未到達', mfe=max(0.,float(np.max(moves))),
                    mae=max(0.,float(-np.min(moves))), slope5=slope5, slope10=slope10,
                    signal_side=signal,
                    cue='傾き方向' if signal==side else '反対方向' if signal==-side else '傾き該当なし'))
    return events, missing


def summarize_events(events: list) -> dict:
    """アンカー事象を夜ごとの率へ圧縮する。

    引数: events (list): 一夜一窓の観測事象。
    返り値: dict: 分母つきの指標。欠測を成功または失敗に数えない。
    """
    result = {}
    for cue in ('全方向', '傾き方向', '反対方向'):
        for sensitivity in ('全観測', '空白120秒以下'):
            for barrier in (50, 100, 200):
                selected = [e for e in events if e['barrier']==barrier
                    and (cue=='全方向' or e['cue']==cue)
                    and (sensitivity=='全観測' or not e['gap_over120'])]
                prefix = f'{cue}_{sensitivity}_{barrier}'
                result[prefix+'_n'] = len(selected)
                for metric in ('favorable_reached','adverse_reached','favorable_first','adverse_first','neither','mfe','mae'):
                    result[prefix+'_'+metric] = float(np.mean([e[metric] for e in selected])) if selected else None
                touched = [e for e in selected if not e['neither']]
                result[prefix+'_conditional_favorable_first'] = float(np.mean([e['favorable_first'] for e in touched])) if touched else None
    return result


def paired(sessions: list) -> dict:
    """夜を独立単位として前後差と再標本化区間を求める。

    引数: sessions (list): 全25夜の指標。
    返り値: dict: 各指標の対比較。金融戦略の成績とは解釈しない。
    """
    keys = sorted(set().union(*(set(row['windows']['前']['metrics']) for row in sessions)))
    result = {}
    rng = np.random.default_rng(149)
    excluded = {'first_observation','last_observation'}
    for metric in keys:
        if metric in excluded:
            continue
        observations = [(s['windows']['前']['metrics'].get(metric), s['windows']['後']['metrics'].get(metric)) for s in sessions]
        valid = [(a,b) for a,b in observations if a is not None and b is not None]
        if not valid:
            continue
        values = np.asarray(valid, dtype=float)
        delta = values[:,0] - values[:,1]
        samples = delta[rng.integers(0,len(delta),size=(10000,len(delta)))]
        result[metric] = dict(n=len(delta), pre_mean=float(np.mean(values[:,0])),post_mean=float(np.mean(values[:,1])),
            pre_median=float(np.median(values[:,0])),post_median=float(np.median(values[:,1])),
            difference_mean=float(np.mean(delta)),difference_median=float(np.median(delta)),
            pre_greater=int(np.count_nonzero(delta>0)),equal=int(np.count_nonzero(delta==0)),
            mean_difference_ci95=np.quantile(np.mean(samples,axis=1),[.025,.975]).tolist(),
            median_difference_ci95=np.quantile(np.median(samples,axis=1),[.025,.975]).tolist())
    return result


def main() -> None:
    """定義と指紋を確認して市場記述のみを保存する。

    引数: なし。
    返り値: None。JSONの成果と小さな完了情報を出力する。
    """
    definition = OUT / '観測定義.json'
    assert hashlib.sha256(definition.read_bytes()).hexdigest() == DEFINITION_SHA
    manifest = json.loads((OUT/'原資料一覧149.json').read_text('utf-8'))
    sessions, partials = [], []
    for record in manifest['sessions']:
        path = Path(record['prepared']['path'])
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == record['prepared']['sha256']
        data = pickle.loads(raw)['data']
        ready, quotes = data['ready'], data['quotes']
        valid = quotes['quote_valid'] & np.isfinite(quotes['bid']) & np.isfinite(quotes['ask']) & (quotes['bid']>0) & (quotes['ask']>quotes['bid'])
        t, bid, ask = ready['time_s'][valid], quotes['bid'][valid], quotes['ask'][valid]
        assert np.all(np.diff(t)>=0)
        us, start = ready['us_open'], ready['start']
        minute = minute_observations(t,bid,ask)
        result = dict(session=record['session'], partial=record['partial'], windows={})
        if record['partial']:
            result['metrics'] = describe_window(t,bid,ask,start,record['cutoff'])
            partials.append(result)
            continue
        windows = {'前':(us-330*60,us-15*60),'後':(us+15*60,us+330*60)}
        for name,(lo,hi) in windows.items():
            metrics = describe_window(t,bid,ask,lo,hi)
            events, missing = anchor_events(t,bid,ask,minute,lo)
            metrics.update(summarize_events(events))
            result['windows'][name] = dict(start=lo,end=hi,metrics=metrics,events=events,missing=missing)
        windows_short = {'17〜19':(start,start+7200),'19〜21':(start+7200,start+14400),
            '21〜米国15分前':(start+14400,us-900),'米国15分後〜01':(us+900,start+28800),
            '01〜04':(start+28800,start+39600)}
        result['short_windows'] = {name: describe_window(t,bid,ask,lo,hi) for name,(lo,hi) in windows_short.items()}
        sessions.append(result)
    assert len(sessions)==25 and len(partials)==1
    # ----------------------------------------
    # 同じ固定時点の傾き方向と反対方向を対比較する。夜単位は維持する。
    cue_comparisons = {}
    for window in ('前','後'):
        converted = []
        for session in sessions:
            source = session['windows'][window]['metrics']
            converted.append(dict(windows={
                '前':dict(metrics={k.removeprefix('傾き方向_'):v for k,v in source.items() if k.startswith('傾き方向_')}),
                '後':dict(metrics={k.removeprefix('反対方向_'):v for k,v in source.items() if k.startswith('反対方向_')})}))
        cue_comparisons[window] = paired(converted)
    short_summary = {}
    for window in sessions[0]['short_windows']:
        metrics = sessions[0]['short_windows'][window]
        short_summary[window] = {}
        for metric in metrics:
            if metric in ('first_observation','last_observation'):
                continue
            values = [s['short_windows'][window].get(metric) for s in sessions]
            values = [v for v in values if v is not None]
            short_summary[window][metric] = dict(n=len(values),mean=float(np.mean(values)),median=float(np.median(values)))
    output = dict(definition_sha256=DEFINITION_SHA,financial_replays=0,complete_sessions=25,
        independent_unit='同じ夜の前後組',paired=paired(sessions),cue_vs_opposite=cue_comparisons,
        short_summary=short_summary,sessions=sessions,partial_reference=partials)
    target = OUT/'市場特性149.json'
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),'utf-8')
    print('完了: 25夜の対比較・途中1夜は別集計。金融再生0回。')


if __name__=='__main__':
    main()
