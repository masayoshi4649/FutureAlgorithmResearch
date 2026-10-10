"""学習の全脚から損益を再集計し、選択規則を別計算で照合する。"""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import pickle
import statistics

import numpy as np
import pandas as pd

from audit_exact import close_equal, independent_accounting

OUT = Path(__file__).resolve().parent
MULTIPLIER = {'NK225': 1000., 'TOPIX': 10000.}
ROW_CACHE = {}


def load_json(name: str):
    """機能: 日本語の保存結果を読み込む。

    引数: name (str): 作業先のファイル名。返り値: object: JSON内容。
    """
    return json.loads((OUT/name).read_text(encoding='utf-8'))


def independent_choice(frame: pd.DataFrame, record: dict) -> dict | None:
    """機能: 保存セルの過去だけをPython標準統計で採点する。

    引数: frame (DataFrame): 結果表。record (dict): 対象セッションと銘柄・絞込み。
    返り値: dict | None: 最高得点の方式と値、適格条件がなければNone。
    """
    grouped = defaultdict(list)
    cache_key = id(frame)
    if cache_key not in ROW_CACHE:
        ROW_CACHE[cache_key] = (frame, frame.to_dict('records'))
    for row in ROW_CACHE[cache_key][1]:
        if row['セッション'] not in record['学習'] or row['銘柄'] != record['銘柄']:
            continue
        if any(record.get(key) is not None and row[key] != record[key] for key in ['思想', '新旧', '系統']):
            continue
        grouped[row['方式']].append(row)
    candidates = []
    for method, rows in grouped.items():
        if sum(r['closed_count'] for r in rows) < 3 or sum(r['closed_count'] > 0 for r in rows) < 2:
            continue
        values = [r['net_yen']/r['設定最大枚数'] for r in rows]
        score = (statistics.median(values)+statistics.mean(values)
                 -.25*statistics.mean(r['max_drawdown_yen']/r['設定最大枚数'] for r in rows))
        candidates.append(dict(方式=method, 得点=score))
    if not candidates:
        return None
    return sorted(candidates, key=lambda r: (-r['得点'], r['方式']))[0]


def audit_choices(frame: pd.DataFrame) -> dict:
    """機能: 主候補・代表・時間順選択を独立採点して照合する。

    引数: frame (DataFrame): 全条件結果。返り値: dict: 選択件数と学習分離。
    """
    selection = load_json('最終選択.json')
    walk = load_json('時間順選択.json')
    records = [*selection['主候補'].values(), *selection['思想別代表'].values(), *walk]
    ties = []
    for record in records:
        answer = independent_choice(frame, record)
        actual = record['採用']
        if answer is None or actual is None:
            assert answer is None and actual is None
        else:
            close_equal(answer['得点'], actual['得点'])
            if answer['方式'] != actual['方式']:
                # ----------------------------------------
                # 桁落ちだけの同点は採用得点と全同点の辞書順を確認して明示する。
                original = frame[frame['方式'].eq(actual['方式'])]
                original_score = independent_choice(original, record)
                close_equal(original_score['得点'], answer['得点'])
                ties.append(dict(学習=record['学習'], 銘柄=record['銘柄'], 保存採用=actual['方式'],
                                 独立同点先頭=answer['方式'], 得点差=original_score['得点']-answer['得点']))
        if record in walk:
            assert record['評価'] not in record['学習']
            assert all(s < record['評価'] for s in record['学習'])
    return dict(選択記録数=len(records), 時間順評価数=len(walk), 保留学習混入=False,
                浮動小数同点によるID差=ties)


def main() -> None:
    """機能: 全数損益と選択、代表条件の原本全行DDを独立照合する。

    引数: なし。返り値: None: 結果監査JSONを保存する。保留・APIは未読。
    """
    frame = pd.read_csv(OUT/'全条件_セッション集計.csv')
    schema = load_json('数値形式.json')
    with (OUT/'学習入力.pkl').open('rb') as stream:
        prepared = pickle.load(stream)
    table = dict(np.load(OUT/'全取引数値.npz', allow_pickle=False))['trades']
    config_ids, cells = schema['条件'], schema['セル']
    count = len(config_ids)*len(cells)
    group = table[:, 0].astype(int)*len(cells)+table[:, 1].astype(int)
    raw = table[:, 2:]
    points = raw[:, 2]*(raw[:, 9]-raw[:, 8])
    close_equal(points, raw[:, 15])
    assert np.all(raw[:, 5] > raw[:, 4])
    closed = raw[:, 14] == 1
    assert np.all(raw[closed, 6] > raw[closed, 5])
    metrics = dict(net_yen=np.zeros(count), closed_net_yen=np.zeros(count), profit_yen=np.zeros(count),
                   loss_yen=np.zeros(count), open_yen=np.zeros(count), net_atr=np.zeros(count),
                   closed_net_atr=np.zeros(count), entry_count=np.zeros(count), closed_count=np.zeros(count),
                   win_count=np.zeros(count), loss_count=np.zeros(count), open_count=np.zeros(count),
                   ideal_entry_gap_count=np.zeros(count), ideal_exit_gap_count=np.zeros(count),
                   ideal_fill_benefit_yen=np.zeros(count))
    for cell_i, (session, symbol) in enumerate(cells):
        assert session != '2026-09-24_Day'
        ready = prepared[(session, symbol)]
        mask = table[:, 1] == cell_i
        rows, keys = raw[mask], group[mask]
        enter, finish = rows[:, 5].astype(int), rows[:, 6].astype(int)
        np.testing.assert_array_equal(rows[:, 20], ready['seq'][enter])
        np.testing.assert_array_equal(rows[:, 21], ready['seq'][finish])
        direction, is_closed = rows[:, 2], rows[:, 14] == 1
        delta = direction*(rows[:, 9]-rows[:, 8])
        multiple = MULTIPLIER[symbol]
        entry_gap = direction*(ready['last'][enter]-rows[:, 8])
        exit_is_threshold = is_closed & np.isin(rows[:, 13], [1, 2])
        exit_gap = np.where(exit_is_threshold, direction*(rows[:, 9]-ready['last'][finish]), 0.)
        values = dict(net_yen=delta*multiple, closed_net_yen=np.where(is_closed, delta*multiple, 0.),
            profit_yen=np.where(is_closed, np.maximum(delta, 0)*multiple, 0.),
            loss_yen=np.where(is_closed, np.minimum(delta, 0)*multiple, 0.),
            open_yen=np.where(is_closed, 0., delta*multiple), net_atr=delta/rows[:, 7],
            closed_net_atr=np.where(is_closed, delta/rows[:, 7], 0.), entry_count=np.ones(len(rows)),
            closed_count=is_closed.astype(float), win_count=(is_closed & (delta > 0)).astype(float),
            loss_count=(is_closed & (delta < 0)).astype(float), open_count=(~is_closed).astype(float),
            ideal_entry_gap_count=(abs(entry_gap) > 1e-6).astype(float),
            ideal_exit_gap_count=(abs(exit_gap) > 1e-6).astype(float),
            ideal_fill_benefit_yen=(entry_gap+exit_gap)*multiple)
        for name, values in values.items():
            np.add.at(metrics[name], keys, values)
    lookup = {(method, session, symbol): method_i*len(cells)+cell_i
              for method_i, method in enumerate(config_ids) for cell_i, (session, symbol) in enumerate(cells)}
    order = np.array([lookup[(r['方式'], r['セッション'], r['銘柄'])] for r in frame.to_dict('records')])
    for name, values in metrics.items():
        close_equal(frame[name].to_numpy(), values[order])
    close_equal(frame['net_yen'].to_numpy(), frame['cap_net_yen'].to_numpy()*frame['設定最大枚数'].to_numpy())
    close_equal(frame['fee_yen'].to_numpy(), 0.)
    close_equal(frame['spread_cost_yen'].to_numpy(), 0.)
    assert frame['open_count'].sum() == 0, '完全保存区間で未返済が残った'

    # ----------------------------------------
    # 代表条件だけは平均的な足に省略せず、原本の全有効行から評価損益を再構成する。
    representatives = pd.read_csv(OUT/'学習代表_セッション集計.csv')
    curves = load_json('学習代表_資産曲線.json')
    detail_checks = 0
    for row in representatives.to_dict('records'):
        session, symbol, method = row['セッション'], row['銘柄'], row['方式']
        index = lookup[(method, session, symbol)]
        result = dict(raw=raw[group == index], summary=row,
                      equity=np.asarray(curves[f'{method}|{session}|{symbol}']))
        detail_checks += independent_accounting(prepared[(session, symbol)], result)
    choices = audit_choices(frame)
    result = dict(成功=True, 条件数=len(config_ids), セッション銘柄数=len(cells), 全集計セル数=len(frame),
                  全脚数=len(raw), 全数照合項目数=len(frame)*(len(metrics)+3),
                  代表の全行会計セル数=len(representatives), 代表会計照合項目数=detail_checks,
                  選択=choices, 最終保留価格参照=False, API取得回数=0,
                  ソースSHA256={name:hashlib.sha256((OUT/name).read_bytes()).hexdigest()
                               for name in ['exact_engine.py', 'research.py', 'catalog.py', 'data.py', 'new_signals.py']})
    (OUT/'全数損益と選択の独立監査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
