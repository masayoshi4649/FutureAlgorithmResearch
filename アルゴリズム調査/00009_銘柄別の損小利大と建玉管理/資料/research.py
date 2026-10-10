"""円建て利益の銘柄横断順位を使わず、サイクルの損小利大を探索する。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import pickle
import time

import numpy as np
import pandas as pd

import metrics
import reference
import risk_guard

OUT, OLD, TRAIN = reference.OUT, reference.OLD, reference.TRAIN


def scalar_metrics(cycles: list[dict], sessions: list[str], config: dict, symbol: str,
                   auxiliary: str = 'atr_cap') -> dict:
    """機能: 同銘柄の円損益比と補助単位による頑健性を、固定した規則で評価する。

    引数: cycles (list[dict])、sessions (list[str])、config (dict)、symbol/auxiliary (str)。
    返り値: 比率・資格・固定得点の辞書 (dict)。
    """
    selected = [c for c in cycles if c['session'] in sessions]
    yen = metrics.summarize(selected, sessions, 'yen')
    scaled = metrics.summarize(selected, sessions, auxiliary)
    result = {k:v for k,v in yen.items() if not isinstance(v, (dict, list))}
    sample = yen['ratio_sample_ok'] and yen['complete_traded_sessions'] >= min(4, len(sessions))
    payoff, pf = yen['payoff_ratio'], yen['profit_factor']
    quality = bool(sample and payoff is not None and payoff > 1 and pf is not None and pf > 1
        and yen['positive_sessions'] > len(sessions)/2 and scaled['net_without_best_session'] is not None
        and scaled['net_without_best_session'] > 0)
    result.update(method=config['id'], symbol=symbol, philosophy=config.get('philosophy', '未分類'),
        family=config.get('family', ''), label=config.get('label', config['id']),
        cap=config.get('max_legs', 1), origin=config.get('origin', '追加'),
        source=config.get('engine', 'single'), train_count=len(sessions), sample_ok=bool(sample),
        qualified=quality, auxiliary_unit=auxiliary, auxiliary_net=scaled['all_net'],
        auxiliary_without_best_session=scaled['net_without_best_session'],
        score=yen['loo_ratio_score'], diagnostic_only=config.get('diagnostic_only', False))
    return result


def evaluate_pool(by_key: dict, configs: list[dict], prefix: str, auxiliary: str = 'atr_cap') -> None:
    """機能: 完全７区間と時間順の先頭３〜６区間を、同じ選択基準で集計する。

    引数: by_key (dict): (方式,銘柄)別サイクル、configs (list[dict])、prefix/auxiliary (str)。
    返り値: None。順位用数値とサイクルを今回の作業フォルダへ保存する。
    """
    mapping = {c['id']:c for c in configs}
    all_rows, prefix_rows = [], []
    started = time.monotonic()
    for number, ((method, symbol), cycles) in enumerate(by_key.items()):
        config = mapping[method]
        all_rows.append(scalar_metrics(cycles, TRAIN, config, symbol, auxiliary))
        for count in [3,4,5,6]:
            prefix_rows.append(scalar_metrics(cycles, TRAIN[:count], config, symbol, auxiliary))
        if number % 1000 == 0:
            print(f'{prefix} 指標 {number}/{len(by_key)}、{time.monotonic()-started:.1f}秒', flush=True)
    pd.DataFrame(all_rows).to_csv(OUT/f'{prefix}_探索集計.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(prefix_rows).to_csv(OUT/f'{prefix}_時間順候補.csv', index=False, encoding='utf-8-sig')
    with (OUT/f'{prefix}_サイクル.pkl').open('wb') as stream:
        pickle.dump(by_key, stream, protocol=pickle.HIGHEST_PROTOCOL)


def raw_blocks() -> tuple[list[dict], list, dict, pd.DataFrame]:
    """機能: 前回の確定６区間売買を再利用し、既知９月24日日中の全条件を追加する。

    引数: なし。返り値: (既存条件,セル一覧,セル方式別raw,既存集計) のtuple。
    """
    configs = json.loads((OLD/'条件一覧.json').read_text(encoding='utf-8'))
    schema = json.loads((OLD/'数値形式.json').read_text(encoding='utf-8'))
    assert schema['条件'] == [c['id'] for c in configs]
    cached = OUT/'既存７区間raw.pkl'
    if cached.exists():
        with cached.open('rb') as stream:
            result = pickle.load(stream)
        return configs, result['cells'], result['blocks'], pd.read_csv(OUT/'既存７区間セッション.csv')
    cells = [tuple(c) for c in schema['セル']]
    all_raw = np.load(OLD/'全取引数値.npz')['trades']
    order = np.lexsort((all_raw[:, 0], all_raw[:, 1]))
    ordered = all_raw[order]
    changes = np.r_[0, np.where(np.any(np.diff(ordered[:, :2], axis=0) != 0, axis=1))[0]+1, len(ordered)]
    blocks = {(int(ordered[a,1]),int(ordered[a,0])):ordered[a:b,2:].copy() for a,b in zip(changes[:-1],changes[1:])}
    frame = pd.read_csv(OLD/'全条件_セッション集計.csv')
    rows = frame.to_dict('records')
    prepared = reference.load_inputs()
    for symbol in reference.SYMBOLS:
        key = ('2026-09-24_Day',symbol); cell = len(cells); cells.append(key)
        ready = prepared[key]; cache = {}
        for index, config in enumerate(configs):
            cache_id = config['id'][:-1] if config['id'].endswith(('_U0','_U1')) else config['id']
            if cache_id not in cache:
                cache[cache_id] = reference.engine.simulate(ready, config['family'], config)
            value = cache[cache_id]
            if len(value['raw']):
                blocks[(cell,index)] = value['raw']
            rows.append(reference.previous.result_row(ready,config,value))
        print(f'既知９月24日日中 {symbol} {len(configs)}条件追加', flush=True)
    with cached.open('wb') as stream:
        pickle.dump(dict(cells=cells,blocks=blocks),stream,protocol=pickle.HIGHEST_PROTOCOL)
    frame = pd.DataFrame(rows)
    frame.to_csv(OUT/'既存７区間セッション.csv',index=False,encoding='utf-8-sig')
    return configs,cells,blocks,frame


def singles() -> None:
    """機能: 基本6,123条件と固定済み新規停止条件を銘柄ごとに再評価する。

    引数: なし。返り値: None。現在通信や旧成果の変更はしない。
    """
    configs,cells,blocks,_ = raw_blocks()
    additions = json.loads((OUT/'既存追加条件_損益前固定.json').read_text(encoding='utf-8'))
    universe = [dict(c,engine='single') for c in [*configs,*additions]]
    reference.save(OUT/'単独条件一覧.json',universe)
    target = OUT/'単独_サイクル.pkl'
    if target.exists():
        with target.open('rb') as stream:
            by_key = pickle.load(stream)
    else:
        prepared = reference.load_inputs()
        by_key = {(c['id'],s):[] for c in universe for s in reference.SYMBOLS}
        empty = np.zeros((0,22)); audits = []
        for cell,(session,symbol) in enumerate(cells):
            times = prepared[(session,symbol)]['time_s']
            for index,config in enumerate(configs):
                raw = blocks.get((cell,index),empty)
                by_key[(config['id'],symbol)].extend(metrics.from_raw(raw,config['id'],symbol,session,config['max_legs'],times))
                for addition in risk_guard.variants(config):
                    kept,audit = risk_guard.filter_raw(raw,addition)
                    by_key[(addition['id'],symbol)].extend(metrics.from_raw(kept,addition['id'],symbol,session,config['max_legs'],times))
                    if audit['stopped']:
                        audits.append(dict(方式=addition['id'],銘柄=symbol,セッション=session,**audit))
            print(f'サイクル化 {session} {symbol}', flush=True)
        reference.save(OUT/'新規停止の発動記録.json',audits)
        with target.open('wb') as stream:
            pickle.dump(by_key,stream,protocol=pickle.HIGHEST_PROTOCOL)
    evaluate_pool(by_key,universe,'単独')


def choose(frame: pd.DataFrame, symbol: str, philosophy: str | None = None) -> dict:
    """機能: 同銘柄の固定資格・比率得点から、採用または参考候補を決める。

    引数: frame (DataFrame)、symbol (str)、philosophy (str|None)。返り値: 選択理由付きdict。
    """
    part = frame[frame.symbol.eq(symbol) & ~frame.diagnostic_only.fillna(False).astype(bool)].copy()
    if philosophy is not None:
        part = part[part.philosophy.eq(philosophy)]
    strict = part[part.qualified.eq(True)]
    status = '損小利大の探索条件を満たす'
    if len(strict):
        part = strict
    else:
        status = '損小利大の探索条件を満たす候補なし・参考選択'
        sampled = part[part.sample_ok.eq(True)]
        part = sampled if len(sampled) else part[part.complete_cycles.gt(0)]
    part = part.sort_values(['score','profit_factor','payoff_ratio','method'],ascending=[False,False,False,True],na_position='last')
    return dict(銘柄=symbol,思想=philosophy,判定=status,候補数=len(part),
                採用=part.iloc[0].to_dict() if len(part) else None,上位=part.head(12).to_dict('records'))


def select_all() -> None:
    """機能: 全思想を同銘柄内で統合し、現在照合前の主・比較候補を固定する。

    引数: なし。返り値: None。結果を見た後の現在用選び直しは許さない。
    """
    frames = [pd.read_csv(p) for p in OUT.glob('*_探索集計.csv') if p.name in ['単独_探索集計.csv','格子_探索集計.csv','NT_探索集計.csv']]
    frame = pd.concat(frames,ignore_index=True)
    frame.to_csv(OUT/'全思想_探索集計.csv',index=False,encoding='utf-8-sig')
    primary = {symbol:choose(frame,symbol) for symbol in sorted(frame.symbol.unique())}
    representatives = {}
    for symbol in sorted(frame.symbol.unique()):
        for philosophy in sorted(frame[frame.symbol.eq(symbol)].philosophy.unique()):
            representatives[f'{symbol}|{philosophy}'] = choose(frame,symbol,philosophy)
    selected = sorted({r['採用']['method'] for r in [*primary.values(),*representatives.values()] if r['採用']})
    selected = sorted(set(selected)|{'N10_R1_E3_X2_U0','P12_R-1_E0_X2_U0','P16_R1_E1_X5_U0'})
    # ----------------------------------------
    # 手動例と枚数診断は成績に関係なく同じ固定照合へ持ち込む。
    selected = sorted(set(selected)|{'G01_T10','G02_T10','G03_T10','G15_T10','G16_A10',
        'NT_ratio_mom_Z1_S0','NT_ratio_mom_Z1_S1','NT_ratio_mom_Z1_S2',
        'NT_ratio_mom_Z1_S3','NT_ratio_mom_Z1_S4','NT_ratio_mom_Z1_S5'})
    walks = []
    for count in [3,4,5,6]:
        pieces = [pd.read_csv(p) for p in OUT.glob('*_時間順候補.csv') if p.name in ['単独_時間順候補.csv','格子_時間順候補.csv','NT_時間順候補.csv']]
        pool = pd.concat(pieces,ignore_index=True)
        pool = pool[pool.train_count.eq(count)]
        for symbol in sorted(pool.symbol.unique()):
            walks.append(dict(学習=TRAIN[:count],評価=TRAIN[count],**choose(pool,symbol)))
    reference.save(OUT/'最終選択.json',dict(主候補=primary,思想別代表=representatives,照合ID=selected,
        円額の銘柄横断比較=False,選択用セッション=TRAIN,既知ナイト前半を選択に使う=False))
    reference.save(OUT/'時間順選択.json',walks)
    print(json.dumps({k:None if v['採用'] is None else dict(方式=v['採用']['method'],PF=v['採用']['profit_factor'],
        損益比=v['採用']['payoff_ratio'],判定=v['判定']) for k,v in primary.items()},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='銘柄別サイクル損益の探索')
    parser.add_argument('--singles',action='store_true')
    parser.add_argument('--select',action='store_true')
    args = parser.parse_args()
    if args.singles:
        singles()
    if args.select:
        select_all()
