"""固定済み売買の待ち時間・価格経路・機会の違いを事後分析する。"""

from __future__ import annotations

import json
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd

import analyze


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(BASE))
from replay import REASONS


def distribution(values: list | np.ndarray | pd.Series) -> dict:
    """機能: 有限値の平均と分位点をまとめる。

    引数: values(list|ndarray|Series)。返り値: 分布(dict)。
    """
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    return dict(n=len(x), mean=float(x.mean()) if len(x) else None,
                q10=float(np.quantile(x, .1)) if len(x) else None,
                q25=float(np.quantile(x, .25)) if len(x) else None,
                median=float(np.median(x)) if len(x) else None,
                q75=float(np.quantile(x, .75)) if len(x) else None,
                q90=float(np.quantile(x, .9)) if len(x) else None,
                positive=float(np.mean(x > 0)) if len(x) else None)


def event_sources(ready: dict, obs: pd.DataFrame, method: str, calibration: dict) -> tuple:
    """機能: 固定済みP01/C03のイベント起点を復元し、元信号と照合する。

    引数: ready(dict)、obs(DataFrame)、method(str)、calibration(dict)。
    返り値: 判断行から起点への対応と方向配列(tuple)。売買規則は変更しない。
    """
    by_time = {float(r.time_s): r for r in obs.itertuples()}
    q = calibration[ready['symbol']]
    event = None
    last_index = -1
    sources, decisions = {}, []
    for origin in np.arange(ready['start'] + 1200., ready['limit'], 60.):
        index = int(np.searchsorted(ready['time_s'], origin, side='left'))
        if index >= len(ready['time_s']):
            break
        if index <= last_index or ready['time_s'][index] - origin > 60.:
            event = None
            continue
        last_index = index
        row = by_time.get(float(origin))
        signal = 0
        if row is None:
            event = None
        else:
            valid = np.isfinite(row.execution) and np.isfinite(row.unknown_fraction) and row.unknown_fraction < 1.
            if method == 'P01' and not valid:
                event = None
            if event is not None and origin - event['origin'] > 300.:
                event = None
            ended = event is not None and (method == 'C03' or (valid and event['direction'] * row.execution <= 0))
            turned = event is not None and event['direction'] * row.r1 < 0
            if ended and turned:
                signal = -event['direction']
                sources[int(ready['seq'][index])] = dict(**event, confirmation=origin,
                    confirmation_mid=float(row.mid), confirmation_seq=int(ready['seq'][index]))
                event = None
            if method == 'P01':
                d = int(np.sign(row.execution)) if valid else 0
                strong = valid and d != 0 and abs(row.execution) >= q['execution'] and d * row.r1 > 0
            else:
                d = int(np.sign(row.r1))
                strong = d != 0 and abs(row.r1) >= q['r1']
            if strong and (event is None or event['direction'] != d):
                event = dict(origin=float(origin), index=index, seq=int(ready['seq'][index]),
                    direction=d, mid=float(row.mid), atr=float(row.atr),
                    execution=float(row.execution) if np.isfinite(row.execution) else None, r1=float(row.r1))
        decisions.append([index, signal])
    return sources, np.asarray(decisions, dtype=float).reshape(-1, 2)


def metrics(part: pd.DataFrame) -> dict:
    """機能: 同一数量の取引群を実現損益・時間・順行到達・出口理由へ分解する。

    引数: part(DataFrame)。返り値: 取引群の統計(dict)。
    """
    wins, losses = part.loc[part.pnl > 0, 'pnl'], part.loc[part.pnl < 0, 'pnl']
    out = dict(n=len(part), net=float(part.pnl.sum()), profit=float(wins.sum()), loss=float(-losses.sum()),
        wins=len(wins), losses=len(losses), flat=int((part.pnl == 0).sum()),
        win_rate=float((part.pnl > 0).mean()) if len(part) else None,
        mean_win=float(wins.mean()) if len(wins) else None, mean_loss=float(-losses.mean()) if len(losses) else None,
        expectancy=float(part.pnl.mean()) if len(part) else None,
        realized_atr=distribution(part.realized_atr), mfe_atr=distribution(part.mfe),
        hold_seconds=distribution(part.hold_seconds),
        origin_to_fill_seconds=distribution(part.origin_to_fill),
        decision_to_fill_seconds=distribution(part.decision_to_fill),
        confirmation_wait_seconds=distribution(part.confirmation_wait),
        mfe_reached={str(level): float((part.mfe >= level).mean()) if len(part) else None for level in (.25, .5, 1.)})
    out['reasons'] = [dict(reason=REASONS[int(reason)], n=len(item), net=float(item.pnl.sum()),
        mean_pnl=float(item.pnl.mean()), mean_mfe=float(item.mfe.mean()),
        mfe_ge1=float((item.mfe >= 1.).mean()), mean_hold=float(item.hold_seconds.mean()))
        for reason, item in part.groupby('reason')]
    return out


def entry_decomposition(table: pd.DataFrame, symbol: str, other: str) -> dict:
    """機能: 入口が完全一致する部分と片方だけの入口の収支に分解する。

    引数: table(DataFrame)、symbol/other(str)。返り値: 差額の会計分解(dict)。
    共通入口でも後の反対信号が異なるため、出口損益は異なり得る。
    """
    a = table.loc[(table.symbol == symbol) & (table.method == 'P01')]
    b = table.loc[(table.symbol == symbol) & (table.method == other)]
    mapping_a = {(r.session, r.entry_decision_seq, r.side): r for r in a.itertuples()}
    mapping_b = {(r.session, r.entry_decision_seq, r.side): r for r in b.itertuples()}
    common = mapping_a.keys() & mapping_b.keys()
    only_a, only_b = mapping_a.keys() - common, mapping_b.keys() - common
    common_a, common_b = sum(mapping_a[k].pnl for k in common), sum(mapping_b[k].pnl for k in common)
    aonly, bonly = sum(mapping_a[k].pnl for k in only_a), sum(mapping_b[k].pnl for k in only_b)
    total_difference = float(b.pnl.sum() - a.pnl.sum())
    assert abs((common_b - common_a) + bonly - aonly - total_difference) < 1e-7
    changed = []
    for mode in ('同じ返済行', '対照が先に返済', '対照が後に返済'):
        keys = [k for k in common if (mapping_b[k].exit_seq == mapping_a[k].exit_seq if mode == '同じ返済行' else
            mapping_b[k].exit_seq < mapping_a[k].exit_seq if mode == '対照が先に返済' else mapping_b[k].exit_seq > mapping_a[k].exit_seq)]
        changed.append(dict(type=mode, n=len(keys), p01_net=sum(mapping_a[k].pnl for k in keys),
            comparator_net=sum(mapping_b[k].pnl for k in keys),
            difference=sum(mapping_b[k].pnl-mapping_a[k].pnl for k in keys)))
    return dict(symbol=symbol, comparator=other, difference=total_difference,
        identical_entry=dict(n=len(common), p01_net=common_a, comparator_net=common_b, difference=common_b-common_a),
        p01_only=dict(n=len(only_a), net=aonly), comparator_only=dict(n=len(only_b), net=bonly), common_exit_changes=changed)


def main() -> None:
    """機能: 完了した売買台帳だけを分析し、反証資料を保存する。

    引数: なし。返り値: なし(None)。判断器・再生器・仕様固定を変更しない。
    """
    ready = analyze.load_ready()
    observations = pd.read_pickle(HERE / '観測.pkl')
    ledgers = pickle.loads((BASE / 'ledgers.pkl').read_bytes())
    signals = pickle.loads((BASE / 'signals.pkl').read_bytes())
    spec = json.loads((BASE / '売買仕様固定.json').read_text(encoding='utf8'))
    source_maps, decision_origins, checks = {}, {}, []
    for key, data in sorted(ready.items()):
        obs = observations.loc[(observations.session == key[0]) & (observations.symbol == key[1])]
        origins = {}
        for row in obs.itertuples():
            index = int(np.searchsorted(data['time_s'], row.time_s, side='left'))
            if index < len(data['time_s']) and data['time_s'][index] - row.time_s <= 60:
                origins[int(data['seq'][index])] = float(row.time_s)
        decision_origins[key] = origins
        for method in ('P01', 'C03'):
            mapping, decisions = event_sources(data, obs, method, spec['尺度'])
            np.testing.assert_array_equal(decisions, signals[method][key])
            source_maps[(method, *key)] = mapping
            checks.append(dict(method=method, session=key[0], symbol=key[1], matched_signals=len(decisions)))
    rows = []
    for method, accounts in ledgers.items():
        for key, account in accounts.items():
            openings = [o for o in account['orders'] if o[4] == 1]
            assert len(openings) == len(account['trades'])
            for order, trade in zip(openings, account['trades']):
                assert order[3] == trade[11] and order[7] == trade[4] and order[5] == trade[2]
                quantity, value = (5., 1000.) if key[1] == 'TOPIX' else (10., 10.)
                origin = decision_origins[key].get(int(order[2]), np.nan)
                event = source_maps.get((method, *key), {}).get(int(order[2]))
                rows.append(dict(method=method, session=key[0], symbol=key[1], period=account['period'],
                    side=int(trade[2]), pnl=float(trade[6]), reason=int(trade[7]), entry_atr=float(trade[8]),
                    entry_price=float(trade[4]), exit_price=float(trade[5]), entry_time=float(trade[0]), exit_time=float(trade[1]),
                    entry_decision_time=float(order[0]), entry_decision_seq=int(order[2]), entry_seq=int(trade[11]),
                    exit_seq=int(trade[12]),
                    realized_atr=float(trade[6] / (quantity * value * trade[8])), mfe=float(trade[14]),
                    hold_seconds=float(trade[1]-trade[0]), decision_to_fill=float(order[1]-order[0]),
                    origin_to_fill=float(order[1]-origin),
                    confirmation_wait=float(event['confirmation']-event['origin']) if event else np.nan,
                    event_abs_r1=abs(event['r1']) if event else np.nan,
                    event_abs_execution=abs(event['execution']) if event and event['execution'] is not None else np.nan))
    table = pd.DataFrame(rows)
    table.to_pickle(HERE / '取引分解.pkl')
    stats = []
    for (method, symbol), part in table.groupby(['method', 'symbol']):
        for period in ('全23場', *analyze.PERIODS):
            item = part if period == '全23場' else part.loc[part.period == period]
            stats.append(dict(method=method, symbol=symbol, period=period, **metrics(item)))
    # ----------------------------------------
    # 待った価格変化は、実際にP01が入った同一イベントに限定して評価する。
    event_rows = []
    for trade in table.loc[table.method.isin(['P01', 'C03'])].itertuples():
        key = (trade.session, trade.symbol)
        data = ready[key]
        source = source_maps[(trade.method, *key)][trade.entry_decision_seq]
        initial_index = source['index'] + 1
        fill_index = int(np.searchsorted(data['seq'], trade.entry_seq))
        initial_price = float(data['last'][initial_index])
        event_atr = float(data['atr'][source['index']])
        path = data['last'][initial_index:fill_index+1]
        extreme = float(path.min() if trade.side > 0 else path.max())
        end = trade.entry_time + 300.
        end_index = int(np.searchsorted(data['time_s'], end, side='right')-1)
        complete = end <= data['limit'] and end_index >= fill_index and end-data['time_s'][end_index] <= 60.
        after = data['last'][fill_index:end_index+1]
        gain = trade.side * (after-trade.entry_price) / event_atr
        event_rows.append(dict(method=trade.method, session=trade.session, symbol=trade.symbol, period=trade.period,
            entry_decision_seq=trade.entry_decision_seq, initial_decision_seq=source['seq'],
            side=trade.side, confirmation_wait=source['confirmation']-source['origin'],
            source_to_fill_wait=trade.entry_time-data['time_s'][initial_index],
            event_atr=event_atr, event_abs_r1=abs(source['r1']),
            already_returned=trade.side*(trade.entry_price-initial_price)/event_atr,
            rebound_from_extreme=trade.side*(trade.entry_price-extreme)/event_atr,
            original_extension=trade.side*(initial_price-extreme)/event_atr,
            post5=trade.side*(float(data['last'][end_index])-trade.entry_price)/event_atr if complete else np.nan,
            post5_mfe=float(max(0., gain.max())) if complete else np.nan,
            post5_mae=float(max(0., -gain.min())) if complete else np.nan,
            pnl=trade.pnl, mfe=trade.mfe, reason=trade.reason))
    events = pd.DataFrame(event_rows)
    events.to_pickle(HERE / '同一イベント経路.pkl')
    event_summary = []
    for (method, symbol), part in events.groupby(['method','symbol']):
        for period in ('全23場', *analyze.PERIODS):
            item = part if period == '全23場' else part.loc[part.period == period]
            event_summary.append(dict(method=method, symbol=symbol, period=period, n=len(item),
                **{c: distribution(item[c]) for c in ('confirmation_wait', 'source_to_fill_wait', 'already_returned',
                    'rebound_from_extreme', 'original_extension', 'post5', 'post5_mfe', 'post5_mae', 'event_abs_r1')}))
    # ----------------------------------------
    # 同じ当初イベントでC02が実際に新規した場合だけ、実取引を対応させる。
    c02 = table.loc[table.method == 'C02']
    matched = events.loc[events.method == 'P01'].merge(c02[['session','symbol','entry_decision_seq','side','pnl','mfe','hold_seconds']],
        left_on=['session','symbol','initial_decision_seq','side'],
        right_on=['session','symbol','entry_decision_seq','side'], suffixes=('_p01','_c02'), validate='many_to_one')
    matched_summary = []
    for symbol, item in matched.groupby('symbol'):
        paired_source = set(zip(item.session, item.initial_decision_seq, item.side))
        all_other = c02.loc[c02.symbol == symbol]
        rest = all_other.loc[[key not in paired_source for key in zip(all_other.session,all_other.entry_decision_seq,all_other.side)]]
        assert len(paired_source) == len(item)
        matched_summary.append(dict(symbol=symbol, paired=len(item), p01_net=float(item.pnl_p01.sum()),
            c02_net=float(item.pnl_c02.sum()), difference=float((item.pnl_c02-item.pnl_p01).sum()),
            p01_mfe=distribution(item.mfe_p01), c02_mfe=distribution(item.mfe_c02),
            entry_price_difference_atr=distribution(item.already_returned),
            c02_other_n=len(rest), c02_other_net=float(rest.pnl.sum())))
    output = dict(注意='完了後の反証。条件・売買コードは変更しない。同一イベント対応はP01確認成立を事後に選んだ説明用比較で、実行可能な代替戦略の収支ではない。',
        時刻='秒差はCurrentPriceTime代理時計。判断後の次行約定でも同時刻行なら0秒になるため、ネットワークや取引所の実遅延ではない。',
        信号再構成監査=checks, 手法別=stats, 同一イベント経路=event_summary,
        同一当初イベントの実取引対応=matched_summary,
        入口集合差=[entry_decomposition(table,'TOPIX','C03'),entry_decomposition(table,'NK225','C02'),
                   entry_decomposition(table,'TOPIX','C05'),entry_decomposition(table,'NK225','C05')])
    analyze.save(HERE / '売買後の反証.json', output)
    print(f'{len(table):,}取引を分解。P01/C03 {len(events)}件の元イベントを元信号と完全一致で復元しました。')


if __name__ == '__main__':
    main()
