"""旧6123条件の脚をサイクルへ束ね、円額比較を同一銘柄内に限定して再集計する。"""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd

import metrics

OUT = Path(__file__).resolve().parent
OLD = OUT.parent/'wave_v13'


def main() -> None:
    """機能: 既存原本と計算条件を変更せず、売買全脚だけから新しい評価軸を作る。

    引数: なし。返り値: None: サイクル表・銘柄別指標・全数照合を保存する。
    """
    started = time.monotonic()
    OUT.mkdir(parents=True, exist_ok=True)
    schema = json.loads((OLD/'数値形式.json').read_text(encoding='utf-8'))
    configs = json.loads((OLD/'条件一覧.json').read_text(encoding='utf-8'))
    config_map = {row['id']:row for row in configs}
    raw = np.load(OLD/'全取引数値.npz', allow_pickle=False)['trades']
    side, entry, exit_price, atr, closed = raw[:, 4], raw[:, 10], raw[:, 11], raw[:, 9], raw[:, 16] == 1
    points = side*(exit_price-entry)
    np.testing.assert_allclose(points, raw[:, 17])
    legs = pd.DataFrame(dict(method_index=raw[:, 0].astype(int), cell_index=raw[:, 1].astype(int),
        cycle_id=raw[:, 2].astype(int), leg_id=raw[:, 3].astype(int),
        entry_order=raw[:, 7].astype(int), exit_order=raw[:, 8].astype(int),
        entry_seq=raw[:, 22].astype(int), exit_seq=raw[:, 23].astype(int),
        closed_leg=closed.astype(int), points=points, atr=points/atr,
        closed_points=np.where(closed, points, 0.), open_points=np.where(closed, 0., points),
        closed_atr=np.where(closed, points/atr, 0.), open_atr=np.where(closed, 0., points/atr)))
    cycle_frame = legs.groupby(['method_index', 'cell_index', 'cycle_id'], sort=False).agg(
        legs=('points','size'), closed_legs=('closed_leg','sum'), net_points=('points','sum'),
        closed_points=('closed_points','sum'), open_points=('open_points','sum'), net_atr=('atr','sum'),
        closed_atr=('closed_atr','sum'), open_atr=('open_atr','sum'),
        entry_order=('entry_order','min'), exit_order=('exit_order','max'),
        entry_seq=('entry_seq','min'), exit_seq=('exit_seq','max')).reset_index()
    cycle_frame['method'] = [schema['条件'][i] for i in cycle_frame.method_index]
    cycle_frame['session'] = [schema['セル'][i][0] for i in cycle_frame.cell_index]
    cycle_frame['symbol'] = [schema['セル'][i][1] for i in cycle_frame.cell_index]
    cycle_frame['cap'] = [config_map[m]['max_legs'] for m in cycle_frame.method]
    cycle_frame['open_legs'] = cycle_frame.legs-cycle_frame.closed_legs
    cycle_frame['complete'] = cycle_frame.open_legs.eq(0)
    for name in ['net', 'closed', 'open']:
        cycle_frame[f'{name}_yen'] = cycle_frame[f'{name}_points']*cycle_frame.symbol.map(metrics.MULTIPLIERS)
    cycle_frame.to_csv(OUT/'旧6123_サイクル.csv', index=False, encoding='utf-8-sig')
    print(f'{len(legs):,}脚を{len(cycle_frame):,}サイクルへ集約しました', flush=True)

    # ----------------------------------------
    # サイクル化しても全脚・全評価損益が欠落しないことを旧セル別会計と照合する。
    original = pd.read_csv(OLD/'全条件_セッション集計.csv')
    aggregate = cycle_frame.groupby(['method', 'session', 'symbol'])[['net_yen','closed_yen','open_yen','legs','closed_legs','open_legs']].sum()
    accounting_checks = 0
    pairs = [('net_yen','net_yen'), ('closed_net_yen','closed_yen'), ('open_yen','open_yen'),
             ('entry_count','legs'), ('closed_count','closed_legs'), ('open_count','open_legs')]
    for row in original.to_dict('records'):
        key = (row['方式'], row['セッション'], row['銘柄'])
        other = aggregate.loc[key] if key in aggregate.index else {target:0. for _,target in pairs}
        for source, target in pairs:
            if abs(row[source]-other[target]) > 1e-6:
                raise AssertionError(f'サイクル化で数値不一致: {key} {source}')
            accounting_checks += 1
    buckets = defaultdict(list)
    for row in cycle_frame.to_dict('records'):
        buckets[(row['method'], row['symbol'])].append(row)
    leg_buckets = {key:frame for key,frame in legs.groupby(['method_index','cell_index'], sort=False)}
    sessions = list(dict.fromkeys(cell[0] for cell in schema['セル']))
    rows = []
    for method_index, method in enumerate(schema['条件']):
        config = config_map[method]
        for symbol in ['NK225', 'TOPIX']:
            cycles = buckets[(method, symbol)]
            row = dict(method=method, symbol=symbol, family=config['family'], philosophy=config['philosophy'],
                       origin=config['origin'], cap=config['max_legs'])
            for unit in ['yen','atr_cap']:
                summary = metrics.summarize(cycles, sessions, unit)
                row.update({f'{unit}_{key}':value for key,value in summary.items()
                            if key not in ['method','symbol','unit','sessions','leave_one_out','ratio_note','drawdown_note']})
            all_legs = []
            for cell_index, (session, target_symbol) in enumerate(schema['セル']):
                if target_symbol == symbol and (method_index,cell_index) in leg_buckets:
                    frame = leg_buckets[(method_index,cell_index)]
                    all_legs.extend((frame.loc[frame.closed_leg.eq(1),'points']*metrics.MULTIPLIERS[symbol]).tolist())
            aux = metrics.distribution(all_legs)
            row.update({f'leg_{key}':aux[key] for key in ['count','wins','losses','avg_win','avg_loss','profit_factor','payoff_ratio','win_rate']})
            rows.append(row)
    pd.DataFrame(rows).to_csv(OUT/'旧6123_銘柄別サイクル指標.csv', index=False, encoding='utf-8-sig')
    result = dict(旧条件数=len(configs), 銘柄別指標数=len(rows), 元脚数=len(legs), サイクル数=len(cycle_frame),
                  全数会計照合項目数=accounting_checks, 未完了サイクル数=int((~cycle_frame.complete).sum()),
                  学習セッション=sessions, 現在API取得数=0, 秒=time.monotonic()-started,
                  元取引NPZ_SHA256=hashlib.sha256((OLD/'全取引数値.npz').read_bytes()).hexdigest(),
                  metrics_SHA256=hashlib.sha256((OUT/'metrics.py').read_bytes()).hexdigest(),
                  注意='銘柄ごとに集計する。円額でNK225とTOPIXを順位づけしない。脚指標は補助、主指標は全返済サイクル。')
    (OUT/'旧6123_再集計監査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
