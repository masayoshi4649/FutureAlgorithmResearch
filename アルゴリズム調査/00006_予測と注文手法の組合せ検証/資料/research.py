"""三つの思想を保存データで比較し、過去だけで選ぶ規則と結果を保存する。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import pickle
import time

import numpy as np
import pandas as pd

import accounting
import catalog
import orders
import signals
import single

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
save = single.save
SYMBOLS = ['NK225', 'TOPIX']
COMPLETE = ['2026-09-21_Day', '2026-09-21_Night', '2026-09-22_Day',
            '2026-09-22_Night', '2026-09-23_Day']
KNOWN_PARTIAL = '2026-09-23_Night'


def prepared_inputs(inputs: dict) -> dict:
    """機能: 生板・信号・確定状態を共通の注文入力にする。

    引数: inputs (dict)。返り値: (session,symbol)キーの実行入力 (dict)。
    """
    return {key: single.prepare(item['tape'], item['events'], key[0], key[1], item['state'])
            for key, item in inputs.items()}


def run_one(ready: dict, config: dict, delay: str = '次行') -> tuple[dict, object, np.ndarray]:
    """機能: 単建玉または複数建玉を再生し、同じ列で結果を返す。

    引数: ready/config (dict)、delay (str)。
    返り値: 集計、実行器固有の数値記録、毎分評価曲線 (tuple)。
    """
    if config['engine'] == 'orders':
        raw = orders.simulate_array(ready, config, delay)
        row = orders.summary(ready, config, delay=delay, raw=raw)
        curve = raw['equity']
    else:
        raw = single.simulate_array(ready, config, delay)
        row, curve = accounting.summarize(ready, config, raw, delay)
    row.update(思想=config['philosophy'], 実行器=config['engine'], 群=config.get('group', config['family']),
               方式=config['id'], 系統=config['family'])
    return row, raw, curve


def trade_records(ready: dict, config: dict, raw: object | None = None,
                  delay: str = '次行') -> list[dict]:
    """機能: 実行器の数値記録を図解と監査用の共通売買記録にする。

    引数: ready/config (dict)、raw (object|None)、delay (str)。
    返り値: 方式・セッション・銘柄を付けた売買一覧 (list[dict])。
    """
    rows = (orders.simulate(ready, config, delay=delay, raw=raw) if config['engine'] == 'orders'
            else single.simulate(ready, config, delay))
    return [dict(方式=config['id'], 思想=config['philosophy'], 群=config.get('group', config['family']),
                 セッション=ready['session'], 銘柄=ready['symbol'], **row) for row in rows]


def choose(frame: pd.DataFrame, conditions: list[dict], train: list[str],
           philosophy: str | None = None, group: str | None = None,
           family: str | None = None, symbol: str | None = None) -> dict:
    """機能: 学習範囲の費用倍収支と含み損込み下落から共通条件を選ぶ。

    引数: frame (DataFrame)、conditions (list[dict])、train (list[str])、
    philosophy/group/family/symbol (str|None)。返り値: 条件と全順位の選択記録 (dict)。
    """
    pool = [c for c in conditions if (philosophy is None or c['philosophy'] == philosophy)
            and (group is None or c.get('group') == group) and (family is None or c['family'] == family)]
    part = frame[frame.セッション.isin(train) & frame.方式.isin([c['id'] for c in pool])].copy()
    target_symbols = [symbol] if symbol else SYMBOLS
    part = part[part.銘柄.isin(target_symbols)]
    part['得点'] = (part['費用倍ATR収支'] - .25 * part['費用倍全行最大下落ATR']) / part['設定最大枚数']
    ranks = []
    for config in pool:
        subset = part[part.方式 == config['id']]
        counts = subset.groupby('銘柄').取引数.sum().reindex(target_symbols, fill_value=0)
        if not (counts >= 1).all():
            continue
        scores = subset.groupby('銘柄').得点.sum().reindex(target_symbols, fill_value=0) / len(train)
        ranks.append(dict(方式=config['id'], 主得点=float(scores.min()), 合計得点=float(scores.sum()),
                          銘柄別得点=scores.to_dict(), 銘柄別取引数=counts.astype(int).to_dict(),
                          学習収支円=float(subset.収支円.sum()), 学習費用倍収支円=float(subset.費用倍収支円.sum())))
    ranks.sort(key=lambda r: (-r['主得点'], -r['合計得点'], r['方式']))
    return dict(思想=philosophy, 群=group, 系統=family, 選択対象銘柄=symbol, 学習=train,
                採用=ranks[0] if ranks else None, 全順位=ranks,
                機会費用の減点=False, 頻度への減点=False)


def prediction_diagnostics(prepared: dict) -> pd.DataFrame:
    """機能: 全公開信号の将来方向と費用込み気配リターンを事後ラベルで測る。

    引数: prepared (dict)。返り値: 系統・時間幅・セッション別集計 (DataFrame)。
    このラベルは信号作成や現在照合の条件調整には戻さない。
    """
    result = []
    for (session, symbol), ready in prepared.items():
        times, bid, ask = ready['time_s'], ready['bid'], ready['ask']
        mid = (bid + ask) / 2
        for family, item in ready['families'].items():
            for horizon in (5, 15, 30, 60):
                i = item['indices']
                target = item['times'] + horizon * 60
                j = np.searchsorted(times, target, side='left')
                valid = (j < len(times)) & (target < ready['limit']) & (i + 1 < len(times))
                i, j = i[valid], j[valid]
                side = item['sides'][valid]
                if len(i):
                    valid_lag = times[j]-target[valid] <= 60
                    i, j, side = i[valid_lag], j[valid_lag], side[valid_lag]
                direction = side * (mid[j] - mid[i])
                entry = np.where(side > 0, ask[i+1], bid[i+1])
                exit_price = np.where(side > 0, bid[j], ask[j])
                net = side * (exit_price-entry) - 2 * ready['tick']
                result.append(dict(セッション=session, 銘柄=symbol, 系統=family, 予測分=horizon,
                                    予測数=len(i), 方向正解=int((direction > 0).sum()),
                                    方向不正解=int((direction < 0).sum()), 同値=int((direction == 0).sum()),
                                    方向正答率=float((direction > 0).sum()/(direction != 0).sum()) if np.any(direction != 0) else None,
                                    費用後黒字予測数=int((net > 0).sum()),
                                    平均費用後円=float(net.mean()*single.MULTIPLIERS[symbol]) if len(i) else None,
                                    平均方向変化=float(direction.mean()) if len(i) else None))
    return pd.DataFrame(result)


def selected_details(prepared: dict, mapping: dict, ids: list[str]) -> None:
    """機能: 選択候補の全取引・曲線・遅延感度を保存する。

    引数: prepared/mapping (dict)、ids (list[str])。返り値: なし (None)。
    """
    trades, curves, sensitivity = [], {}, []
    for key in ids:
        cfg = mapping[key]
        for (session, symbol), ready in prepared.items():
            row, raw, curve = run_one(ready, cfg)
            trades.extend(trade_records(ready, cfg, raw))
            curves[f'{key}|{session}|{symbol}'] = curve
            if session in COMPLETE:
                for delay in ['２行後', '次時刻']:
                    stress, _, _ = run_one(ready, cfg, delay)
                    sensitivity.append(stress)
    save(OUT/'代表候補_全取引.json', trades)
    save(OUT/'代表候補_評価曲線.json', curves)
    pd.DataFrame(sensitivity).to_csv(OUT/'約定遅延感度.csv', index=False, encoding='utf-8-sig')


def selection_outputs(frame: pd.DataFrame, conditions: list[dict]) -> dict:
    """機能: 三段の時間順選択と完全５セッションでの最終選択を固定する。

    引数: frame (DataFrame)、conditions (list[dict])。返り値: 最終選択記録 (dict)。
    """
    walk, walk_rows, final = [], [], {}
    for philosophy in catalog.PHILOSOPHIES:
        for n in [2, 3, 4]:
            choice = choose(frame, conditions, COMPLETE[:n], philosophy)
            choice['評価'] = COMPLETE[n]
            walk.append(choice)
            if choice['採用']:
                key = choice['採用']['方式']
                rows = frame[(frame.方式 == key) & (frame.セッション == COMPLETE[n])]
                walk_rows.extend(dict(**r, 学習セッション数=n) for r in rows.to_dict('records'))
        final[philosophy] = choose(frame, conditions, COMPLETE, philosophy)
    groups = sorted({c['group'] for c in conditions if c['philosophy'] != '注文主導'})
    family_choices = {}
    for philosophy in catalog.PHILOSOPHIES[:2]:
        for group in groups:
            family_choices[f'{philosophy}|{group}'] = choose(frame, conditions, COMPLETE, philosophy, group=group)
    order_families = sorted({c['family'] for c in conditions if c['philosophy'] == '注文主導'})
    for family in order_families:
        family_choices[f'注文主導|{family}'] = choose(frame, conditions, COMPLETE, '注文主導', family=family)
    fixed_ids = ['B_旧T12', 'B_旧S17']
    by_symbol, symbol_walk, symbol_rows = {}, [], []
    for symbol in SYMBOLS:
        by_symbol[symbol] = {}
        for philosophy in catalog.PHILOSOPHIES:
            for n in [2,3,4]:
                choice = choose(frame,conditions,COMPLETE[:n],philosophy,symbol=symbol)
                choice['評価'] = COMPLETE[n]
                symbol_walk.append(choice)
                if choice['採用']:
                    key = choice['採用']['方式']
                    part = frame[(frame.方式==key)&(frame.セッション==COMPLETE[n])&(frame.銘柄==symbol)]
                    symbol_rows.extend(dict(**r,学習セッション数=n) for r in part.to_dict('records'))
            by_symbol[symbol][philosophy] = choose(frame,conditions,COMPLETE,philosophy,symbol=symbol)
    symbol_choices = [r for per in by_symbol.values() for r in per.values()]
    selected = sorted({r['採用']['方式'] for r in list(final.values())+list(family_choices.values())+symbol_choices if r['採用']} | set(fixed_ids))
    value = dict(主選択=final, 群別代表=family_choices, 現在照合ID=selected,
                 銘柄別主選択=by_symbol,
                 銘柄別方針の追加='初回保存データの結果で銘柄差を認め、共通条件の制約が依頼にはないため追加。未読現在データ取得前に固定。共通選択も残す。',
                 固定比較ID=fixed_ids,
                 説明='過去５完全セッションだけで選択。既知部分ナイトは選択対象外。')
    save(OUT/'時間順選択.json', walk)
    pd.DataFrame(walk_rows).to_csv(OUT/'時間順評価.csv', index=False, encoding='utf-8-sig')
    save(OUT/'銘柄別時間順選択.json',symbol_walk)
    pd.DataFrame(symbol_rows).to_csv(OUT/'銘柄別時間順評価.csv',index=False,encoding='utf-8-sig')
    save(OUT/'最終選択.json', value)
    return value


def main() -> None:
    """機能: 事前記録、全条件再生、時間順評価、代表取引の保存を実行する。

    引数: なし。返り値: なし (None)。現在データへのネットワーク通信はしない。
    """
    started = time.monotonic()
    conditions = catalog.configs()
    mapping = {c['id']:c for c in conditions}
    save(OUT/'条件一覧.json', conditions)
    paths = [OUT/p for p in ('signals.py','single.py','orders.py','accounting.py','catalog.py','research.py','検証計画.md')]
    save(OUT/'実行前記録.json', dict(時刻=str(pd.Timestamp.now(tz='Asia/Tokyo')), 条件数=len(conditions),
         予測系統数=len(signals.profiles()), 現在API取得数=0,
         SHA256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}))
    inputs = signals.load_inputs()
    prepared = prepared_inputs(inputs)
    with (OUT/'再生入力.pkl').open('wb') as stream:
        pickle.dump(prepared, stream, protocol=pickle.HIGHEST_PROTOCOL)
    save(OUT/'入力監査.json', {f'{s}|{x}':item['event_audit'] for (s,x),item in inputs.items()})
    cells, singles, multiples = [], [], []
    for cell_i, ((session,symbol), ready) in enumerate(prepared.items()):
        cache = {}
        for config_i, config in enumerate(conditions):
            cache_key = config['id'][:-1] if config['engine']=='single' and '_Z' in config['id'] else config['id']
            if session.endswith('Day') and cache_key in cache:
                previous, raw = cache[cache_key]
                row = dict(previous, 方式=config['id'])
            else:
                row, raw, _ = run_one(ready, config)
                if session.endswith('Day'):
                    cache[cache_key] = (row, raw)
            cells.append(row)
            numeric = raw['trades'] if isinstance(raw,dict) else raw
            if len(numeric):
                block = np.column_stack([np.full(len(numeric),config_i),np.full(len(numeric),cell_i),numeric])
                (multiples if config['engine']=='orders' else singles).append(block)
        print(f'{session} {symbol}: {len(conditions)}条件完了、{time.monotonic()-started:.1f}秒', flush=True)
    frame = pd.DataFrame(cells)
    frame.to_csv(OUT/'全条件_セッション集計.csv', index=False, encoding='utf-8-sig')
    arrays = {}
    if singles:
        arrays['単建玉'] = np.vstack(singles)
    if multiples:
        arrays['複数建玉'] = np.vstack(multiples)
    np.savez_compressed(OUT/'全売買数値.npz', **arrays)
    save(OUT/'数値形式.json', dict(条件=[c['id'] for c in conditions],
         セル=[list(k) for k in prepared], 先頭列=['条件index','セルindex'],
         後続列='単建玉はsingle.pyの21列、複数建玉はorders.pyのRAW_COLUMNSを参照'))
    prediction_diagnostics(prepared).to_csv(OUT/'予測時間別診断.csv', index=False, encoding='utf-8-sig')
    final = selection_outputs(frame, conditions)
    selected_details(prepared, mapping, final['現在照合ID'])
    save(OUT/'実行完了.json', dict(条件数=len(conditions), 集計数=len(frame),
         売買数=sum(len(v) for v in arrays.values()), 代表条件数=len(final['現在照合ID']),
         秒=time.monotonic()-started, 現在API取得数=0))
    print(json.dumps({k:v['採用'] for k,v in final['主選択'].items()},ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
