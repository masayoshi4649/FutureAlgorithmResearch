"""固定候補の全脚図解と、既知境界を差し引いた未知部分を評価する。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd

import grid_engine
import metrics
import pair_engine
import reference
import risk_guard

OUT = reference.OUT


def selection() -> tuple[list[dict], dict]:
    """機能: 選択済みIDだけを保存済みの全条件から読み出す。

    引数: なし。返り値: 選択設定一覧と選択記録 (tuple[list[dict],dict])。
    """
    record = json.loads((OUT/'最終選択.json').read_text(encoding='utf-8'))
    configs = json.loads((OUT/'全条件一覧.json').read_text(encoding='utf-8'))
    mapping = {c['id']:c for c in configs}
    return [mapping[i] for i in record['照合ID']], record


def metric_columns(cycles: list[dict], session: str, prefix: str = 'cycle_') -> dict:
    """機能: 脚単位の実現損益とは別に、完了サイクルの平均勝敗と比率を付ける。

    引数: cycles (list[dict])、session/prefix (str)。返り値: scalar指標dict。
    """
    result = metrics.summarize(cycles,[session],'yen')
    return {prefix+k:v for k,v in result.items() if not isinstance(v,(dict,list)) and k not in ('method','symbol')}


def single_result(ready: dict, cfg: dict) -> tuple[dict,list[dict]]:
    """機能: 単独・停止付き・格子を同じ明細形式へ変換する。

    引数: ready/cfg (dict)。返り値: 再生結果と全サイクル (tuple[dict,list[dict]])。
    """
    if cfg['engine'] == 'grid':
        result = grid_engine.simulate(ready,cfg,detail=True)
    elif 'guard' in cfg:
        result = risk_guard.simulate(ready,cfg,detail=True)
    else:
        result = reference.engine.simulate(ready,cfg['family'],cfg,detail=True)
    cycles = metrics.from_raw(result['raw'],cfg['id'],ready['symbol'],ready['session'],cfg['max_legs'],
                              ready['time_s'],incomplete_cycle_ids=result.get('incomplete_cycle_ids'))
    return result,cycles


def split_single(ready: dict, result: dict, cycles: list[dict], cfg: dict, boundary: float) -> tuple:
    """機能: 境界前からの建玉を境界直前時価へ付け替え、未知部分の損益だけを求める。

    引数: ready/result/cfg (dict)、cycles (list[dict])、boundary (float)。
    返り値: 未知部分の結果、サイクル、境界診断 (tuple)。売買条件を再実行・変更しない。
    """
    times = ready['time_s']; before = int(np.searchsorted(times,boundary,side='left'))-1
    if before < 0 or before+1 >= len(times):
        raise ValueError('未知境界の前後に有効な価格が必要です')
    first = before+1
    mark = float(ready['last'][before])
    raw = result['raw']; kept = []
    carried = {c['cycle_id']: c['entry_time_s'] < boundary for c in cycles}
    originals = {}
    for original in raw:
        if times[int(original[6])] < boundary:
            continue
        row = original.copy()
        key = (int(row[0]),int(row[1]),int(row[5]))
        originals[key] = dict(price=float(row[8]),time=float(times[int(row[5])]))
        if times[int(row[5])] < boundary:
            row[8],row[5],row[20] = mark,first,ready['seq'][first]
        row[15] = row[2]*(row[9]-row[8])
        row[16] = (times[int(row[6])]-max(boundary,originals[key]['time']))/60
        kept.append(row)
    trimmed = np.array(kept,dtype=float).reshape((-1,22))
    result_after = risk_guard.result_from_raw(ready,trimmed,cfg,detail=True)
    after_cycles = metrics.from_raw(trimmed,cfg['id'],ready['symbol'],ready['session'],cfg['max_legs'],times,
        incomplete_cycle_ids=result.get('incomplete_cycle_ids'))
    for c in after_cycles:
        c['carried'] = bool(carried[c['cycle_id']])
        c['boundary'] = boundary
    for trade,row in zip(result_after['trades'],trimmed):
        matching = next(x for x in raw if int(x[0]) == int(row[0]) and int(x[1]) == int(row[1])
                        and int(x[6]) == int(row[6]) and float(x[9]) == float(row[9]))
        trade['元新規時刻'] = float(times[int(matching[5])]); trade['元新規価格'] = float(matching[8])
        trade['継続サイクル'] = bool(carried[int(row[0])])
        if cfg['engine'] == 'grid':
            trade['返済理由'] = grid_engine.REASONS.get(int(row[13]),'格子返済')
    full_values = risk_guard.account_arrays(raw,ready['last'])
    multiplier = reference.engine.MULTIPLIERS[ready['symbol']]
    baseline = float(full_values[0][before]*multiplier)
    suffix = full_values[0][first:]*multiplier-baseline
    np.testing.assert_allclose(result_after['summary']['net_yen'],suffix[-1],atol=1e-5)
    peak = np.maximum.accumulate(np.r_[0.,suffix])[1:]
    suffix_dd = float((peak-suffix).max()) if len(suffix) else 0.
    np.testing.assert_allclose(result_after['summary']['max_drawdown_yen'],suffix_dd,atol=1e-5)
    result_after['equity'] = [r for r in result_after['equity'] if r[0] >= boundary]
    result_after['equity'].insert(0,[boundary,-1,0.,0.,float(full_values[2][before]),0.,0.])
    return result_after,after_cycles,dict(boundary=boundary,baseline_equity_yen=baseline,boundary_price=mark,
        new_period_net_yen=float(suffix[-1]),carried_cycles=sum(c['carried'] for c in after_cycles))


def pair_trades(legs: list[dict], method: str, carried: bool = False) -> list[dict]:
    """機能: NTの２脚を銘柄別ローソク足へ描ける共通明細にする。

    引数: legs (list[dict])、method (str)、carried (bool)。返り値: list[dict]。
    """
    rows = []
    for leg in legs:
        row = dict(方式=method,銘柄=leg['symbol'],セッション=leg['session'],サイクル番号=leg['cycle_id'],
            方向=leg['side'],枚数=leg['quantity'],倍率=leg['multiplier'],新規時刻=leg['entry_time'],
            返済評価時刻=leg['exit_time'],新規価格=leg['entry_price'],返済評価価格=leg['exit_price'],
            返済済み=int(leg['complete']),収支円=leg['net_yen'],返済理由=leg['reason'],
            固定ATR=None,脚番号=0 if leg['symbol']=='NK225' else 1,
            保有分=(leg['exit_time']-leg['entry_time'])/60)
        if carried:
            row.update(元新規時刻=leg.get('original_entry_time',leg['entry_time']),
                       元新規価格=leg.get('original_entry_price',leg['entry_price']),継続サイクル=leg.get('carried',False))
        rows.append(row)
    return rows


def normalize_pair_curve(curve: list) -> list:
    """機能: NTの全玉評価を共通７列の表示用形式へ変換する。

    引数: curve (list): 時刻/確定/含み/全評価/下落/総枚数/種別/行。
    返り値: list: 時刻/原本行/全評価/補助値/総枚数/確定/下落。
    """
    return [[r[0],r[7],r[3],0.,r[5],r[1],r[4]] for r in curve]


def evaluate(prepared: dict, prefix: str, boundary: float | None = None) -> None:
    """機能: 固定候補を既知期間または保存済み現在データで再生し、図解と会計を保存する。

    引数: prepared (dict)、prefix (str)、boundary (float|None)。返り値: None。通信・再選択なし。
    """
    configs,_ = selection()
    rows,trades,cycles,curves = [],[],[],{}
    after_rows,after_trades,after_cycles,after_curves,audits = [],[],[],{},[]
    pair_prepared = {}
    for session in dict.fromkeys(s for s,k in prepared):
        pair_prepared[session] = pair_engine.prepare_session(session,tapes=[prepared[(session,k)] for k in reference.SYMBOLS])
    for number,cfg in enumerate(configs):
        method = cfg['id']
        if cfg['engine'] == 'pair':
            for session,ready in pair_prepared.items():
                result = pair_engine.run(ready,cfg,detail=True)
                meta = dict(方式=method,銘柄='NT',セッション=session,思想=cfg['philosophy'],設定最大枚数=cfg['max_legs'],engine='pair')
                rows.append(dict(meta,**result['summary'],**metric_columns(result['cycles'],session)))
                cycles.extend(result['cycles']); trades.extend(pair_trades(result['legs'],method))
                curves[f'{method}|{session}|NT'] = normalize_pair_curve(result['curve'])
                if boundary is not None:
                    after = pair_engine.split_at_boundary(result,ready,boundary)
                    cs = after['cycles']; fresh = [c for c in cs if not c['carried']]
                    closed = sum(c['closed_yen'] for c in cs); opened = sum(c['open_yen'] for c in cs)
                    ar = dict(meta,net_yen=after['net_yen'],closed_net_yen=closed,open_yen=opened,
                        profit_yen=sum(x['net_yen'] for x in after['legs'] if x['complete'] and x['net_yen']>0),
                        loss_yen=sum(x['net_yen'] for x in after['legs'] if x['complete'] and x['net_yen']<0),
                        max_drawdown_yen=after['max_drawdown_yen'],open_count=sum(c['open_legs'] for c in cs),
                        closed_count=sum(c['closed_legs'] for c in cs),carried_cycles=sum(c['carried'] for c in cs),
                        baseline_equity_yen=after['baseline_equity_yen'],
                        **metric_columns(cs,session),**metric_columns(fresh,session,'fresh_'))
                    after_rows.append(ar); after_cycles.extend(cs); after_trades.extend(pair_trades(after['legs'],method,True))
                    full = after['curve']; minute = np.floor(full[:,0]/60)
                    idx = np.unique(np.r_[0,np.where(np.diff(minute)!=0)[0]+1,len(minute)-1]) if len(minute) else []
                    after_curves[f'{method}|{session}|NT'] = [[boundary,-1,0.,0.,0.,0.,0.]]+[[full[i,0],-1,full[i,1],0.,0.,0.,0.] for i in idx]
                    audits.append(dict(方式=method,銘柄='NT',セッション=session,境界時価=after['boundary_prices'],
                        境界評価円=after['baseline_equity_yen'],未知増分円=after['net_yen']))
        else:
            for (session,symbol),ready in prepared.items():
                result,cs = single_result(ready,cfg)
                meta = dict(方式=method,銘柄=symbol,セッション=session,思想=cfg['philosophy'],設定最大枚数=cfg['max_legs'],engine=cfg['engine'])
                rows.append(dict(meta,**result['summary'],**metric_columns(cs,session)))
                cycles.extend(cs); trades.extend(dict(方式=method,枚数=1,**t) for t in result['trades'])
                curves[f'{method}|{session}|{symbol}'] = result['equity']
                if boundary is not None:
                    after,ac,audit = split_single(ready,result,cs,cfg,boundary)
                    fresh = [c for c in ac if not c['carried']]
                    after_rows.append(dict(meta,**after['summary'],carried_cycles=audit['carried_cycles'],
                        baseline_equity_yen=audit['baseline_equity_yen'],**metric_columns(ac,session),**metric_columns(fresh,session,'fresh_')))
                    after_cycles.extend(ac); after_trades.extend(dict(方式=method,枚数=1,**t) for t in after['trades'])
                    after_curves[f'{method}|{session}|{symbol}'] = after['equity']
                    audits.append(dict(方式=method,銘柄=symbol,セッション=session,**audit))
        print(f'{prefix} {number+1}/{len(configs)} {method}',flush=True)
    # ----------------------------------------
    pd.DataFrame(rows).to_csv(OUT/f'{prefix}_セッション集計.csv',index=False,encoding='utf-8-sig')
    reference.save(OUT/f'{prefix}_全取引.json',trades); reference.save(OUT/f'{prefix}_サイクル.json',cycles)
    reference.save(OUT/f'{prefix}_資産曲線.json',curves)
    if boundary is not None:
        pd.DataFrame(after_rows).to_csv(OUT/'現在後半_セッション集計.csv',index=False,encoding='utf-8-sig')
        reference.save(OUT/'現在後半_全取引.json',after_trades); reference.save(OUT/'現在後半_サイクル.json',after_cycles)
        reference.save(OUT/'現在後半_資産曲線.json',after_curves); reference.save(OUT/'現在後半_境界監査.json',audits)


def walk_results() -> None:
    """機能: 過去だけで選んだ条件を次セッションに適用した成績をまとめる。

    引数: なし。返り値: None。現在データは使用しない。
    """
    selections = json.loads((OUT/'時間順選択.json').read_text(encoding='utf-8'))
    cycles = {}
    for name in ['単独','格子','NT']:
        with (OUT/f'{name}_サイクル.pkl').open('rb') as stream:
            cycles.update(pickle.load(stream))
    rows,combined = [],{}
    for record in selections:
        if record['採用'] is None:
            continue
        cfg = record['採用']; symbol = record['銘柄']; session = record['評価']
        cs = [c for c in cycles[(cfg['method'],symbol)] if c['session'] == session]
        rows.append(dict(銘柄=symbol,方式=cfg['method'],評価=session,学習数=len(record['学習']),判定=record['判定'],**metric_columns(cs,session)))
        combined.setdefault(symbol,[]).extend(dict(c,method='過去選択方針') for c in cs)
    pd.DataFrame(rows).to_csv(OUT/'時間順の実評価.csv',index=False,encoding='utf-8-sig')
    reference.save(OUT/'時間順の合計指標.json',{s:metrics.summarize(cs,reference.TRAIN[3:],'yen') for s,cs in combined.items()})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='固定候補の既知・未知増分明細')
    parser.add_argument('--known',action='store_true')
    parser.add_argument('--current',action='store_true')
    args = parser.parse_args()
    if args.known:
        evaluate(reference.load_inputs(),'既知代表')
        walk_results()
    if args.current:
        import current_check
        frozen = current_check.freeze_check()
        with (OUT/'現在入力.pkl').open('rb') as stream:
            prepared = pickle.load(stream)
        boundary = pd.Timestamp(reference.KNOWN_CUTOFF).timestamp() if frozen['session']==reference.KNOWN_NIGHT else None
        evaluate(prepared,'現在全体',boundary)
        current_check.freeze_check()
