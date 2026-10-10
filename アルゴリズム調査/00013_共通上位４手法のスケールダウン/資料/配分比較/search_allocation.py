"""既存４手法の初回・追加枚数だけを変え、同時保有上限内で比較する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle
import sys
import time

import numpy as np

OUT = Path(__file__).resolve().parent
V18 = OUT.parent
V17 = V18.parent / 'wave_v17'
V16 = V18.parent / 'wave_v16'
sys.path.insert(0, str(V17))
sys.path.insert(0, str(V18))
import audit_engine_scaled as engine
import research as metrics

METHODS = ['M3_逆_A03', 'M3_逆_A00', 'M2_逆_A00', 'M2_逆_A01']
SESSIONS = [f'2026-09-{day:02d}_{part}' for day in range(21, 26) for part in ['Day', 'Night']]
CAPS = {'TOPIX': 10, 'NK225': 20}
MULT = {'TOPIX': 1000., 'NK225': 10.}
metrics.MULT = MULT


def save(name: str, value: object) -> None:
    """機能: NumPy型を変換し、日本語JSONを保存する。

    引数: name (str)、value (object)。返り値: なし (None)。
    """
    (OUT / name).write_text(json.dumps(metrics.clean(value), ensure_ascii=False, indent=2), encoding='utf-8')


def hashes() -> dict:
    """機能: 変更を禁止する入力・研究コードのハッシュを取得する。

    引数: なし。返り値: ファイルパスとSHA256の対応 (dict)。
    """
    paths = [V17 / name for name in ['engine.py', 'research.py', '全条件一覧.json', '主方向状態.pkl']]
    paths += [V18 / 'audit_engine_scaled.py', Path(__file__).resolve()]
    paths += [V16 / f'入力_{stage}.pkl' for stage in ['development', 'holdout']]
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def allocations(method: str, symbol: str) -> list[tuple[int, int]]:
    """機能: 上限内で独立した初回・追加枚数の全組合せを列挙する。

    引数: method/symbol (str)。返り値: 初回と追加の組合せ (list[tuple[int,int]])。
    """
    cap = CAPS[symbol]
    if method.endswith('A03'):
        return [(initial, add) for initial in range(1, cap) for add in range(1, cap-initial+1)] + [(cap, 0)]
    return [(initial, 0) for initial in range(1, cap+1)]


def risk_summary(cycles: np.ndarray, symbol: str) -> dict:
    """機能: 各組の初期損失予算を商品倍率で円へ換算する。

    引数: cycles (ndarray)、symbol (str)。返り値: 初期損失予算の分布 (dict)。
    """
    values = cycles[:, 4] * MULT[symbol]
    return dict(count=len(values), min_yen=float(values.min()) if len(values) else 0.,
                median_yen=float(np.median(values)) if len(values) else 0.,
                max_yen=float(values.max()) if len(values) else 0.,
                mean_yen=float(values.mean()) if len(values) else 0.)


def select(candidates: list[dict]) -> tuple[dict | None, dict]:
    """機能: 実行前に固定した資格と順位から代表配分・収支最大配分を選ぶ。

    引数: candidates (list[dict])。返り値: 損小利大代表またはNoneと最大収支配分 (tuple)。
    """
    highest = sorted(candidates, key=lambda r: (-round(r['week']['net_yen'], 6), r['initial_qty'], r['add_qty']))[0]
    eligible = [r for r in candidates if r['selection']['eligible']]
    eligible.sort(key=lambda r: (-round(r['selection']['score'], 10),
                                 -round(r['selection']['recovery'], 10), r['initial_qty'], r['add_qty']))
    return (eligible[0] if eligible else None), highest


def quantity_rule(method: str, initial: int, add: int, cap: int) -> str:
    """機能: 数量設定を保有上限と返済後の再入場を区別して説明する。

    引数: method (str)、initial/add/cap (int)。返り値: 日本語説明 (str)。
    """
    if method.endswith('A03') and add:
        return f'{initial}枚で開始。有利に0.5ATR進むごとに{add}枚を追加し、空き枠が少ないときは残り枠だけ追加。片方向の同時保有は最大{cap}枚。返済後は再エントリーできる。'
    return f'{initial}枚で開始し、追加しない。片方向の同時保有上限は{cap}枚。返済後は再エントリーでき、返済累計枚数には上限を設けない。'


def variant(record: dict, configurations: dict) -> dict:
    """機能: 報告書が使う配分・成績・選択根拠を抽出する。

    引数: record/configurations (dict)。返り値: 報告用配分 (dict)。
    """
    cfg = configurations[record['method_id']]
    return dict(allocation_id=record['allocation_id'],
                config=dict(initial_qty=record['initial_qty'], add_qty=record['add_qty'],
                            position_cap=record['position_cap'], trail_atr=cfg['main_trail'],
                            risk_atr=cfg['stop_atr'], entry_atr=cfg['entry_atr'], add_step_atr=cfg['add_step']),
                quantity_rule=quantity_rule(record['method_id'], record['initial_qty'], record['add_qty'], record['position_cap']),
                week=record['week'], sessions=record['sessions'], risk=record['risk'], selection=record['selection'])


def main() -> None:
    """機能: 数量以外を固定して全配分を再生し、比較結果と監査用台帳を保存する。

    引数: なし。返り値: なし (None)。通信・注文・入力の変更は行わない。
    """
    started = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    source_hashes = hashes()
    configurations = {r['id']: r for r in json.loads((V17 / '全条件一覧.json').read_text(encoding='utf-8'))}
    old = json.loads((V18 / 'scale_data.json').read_text(encoding='utf-8'))
    count = sum(len(allocations(method, symbol)) for method in METHODS for symbol in CAPS)
    assert count == 327
    policy = dict(配分数=count, セッションセル数=count*len(SESSIONS), 対象手法=METHODS,
                  片方向同時保有上限=CAPS, 契約倍率=MULT, 現在API取得数=0, 全期間既読=True,
                  変更する条件=['初回枚数', '追加枚数', '片方向の同時保有上限', '商品倍率'],
                  固定する条件='信号・ATR・価格刻み・時間条件・新規条件・出口条件は変更しない。',
                  配分列挙='A03は初回1〜上限、追加1〜残り枠。初回が上限なら追加0。固定型は初回1〜上限、追加0。追加注文は空き枠まで切り詰める。',
                  週収支最大='週net降順、同値なら初回小→追加小。金額は小数6桁丸め。',
                  損小利大資格='net>0、金額PF>1、１枚平均利益/損失>1、黒字セッション6/10以上、最大利益セッションを除いてもnet>0。',
                  損小利大順位='min(金額PF,１枚平均利益/損失)降順→net/週最大下落降順→初回小→追加小。比率は小数10桁丸め。同等な固定型は初回1枚が代表。',
                  資格未達='該当なしと明記し、週収支最大を参考としてのみ表示する。',
                  注意='同じ既知１週間で配分を選んだ比較探索。未使用データでの再現確認ではない。自己資本・許容損失額は未指定。',
                  ソースSHA256=source_hashes)
    save('探索前の固定記録.json', policy)
    # ----------------------------------------
    # 保存済み入力と既に因果性を監査した状態系列のみを読み込む。
    states = pickle.loads((V17 / '主方向状態.pkl').read_bytes())
    inputs = {}
    for stage in ['development', 'holdout']:
        inputs.update(pickle.loads((V16 / f'入力_{stage}.pkl').read_bytes()))
    directions = {(method, session, symbol): np.ascontiguousarray(
        states[(session, symbol)][configurations[method]['signal']] * configurations[method]['sign'], dtype=np.int8)
        for method in METHODS for session in SESSIONS for symbol in CAPS}
    candidates, weekly_rows, session_rows = [], [], []
    fixed_blocks = {}
    maximum = dict(max_long=0, max_short=0, max_gross=0, cash_error=0., unclosed=0., cap_violations=0)
    for method in METHODS:
        for symbol, cap in CAPS.items():
            for initial, add in allocations(method, symbol):
                config = dict(configurations[method], initial_qty=initial, add_qty=add, audit_cap=cap)
                allocation_id = f'{method}__{symbol}__I{initial:02d}_A{add:02d}'
                rows, cycle_parts = [], []
                for session in SESSIONS:
                    result = engine.run(inputs[(session, symbol)], directions[(method, session, symbol)], config)
                    if not method.endswith('A03'):
                        fixed_blocks[(allocation_id, session, symbol)] = dict(config=config,
                            trades=result['trades'], cycles=result['cycles'], stats=result['stats'], orders=result['orders'])
                    stats = result['stats']
                    assert stats[2] <= cap and stats[3] <= cap, (allocation_id, session, stats)
                    assert stats[9] == 0 and stats[10] == 0 and stats[6] < 1e-5
                    maximum['max_long'] = max(maximum['max_long'], int(stats[2]))
                    maximum['max_short'] = max(maximum['max_short'], int(stats[3]))
                    maximum['max_gross'] = max(maximum['max_gross'], int(stats[4]))
                    maximum['cash_error'] = max(maximum['cash_error'], float(stats[6]))
                    row = metrics.summarize(result, config, symbol, session)
                    row.update(allocation_id=allocation_id, initial_qty=initial, add_qty=add, position_cap=cap,
                               initial_risk=risk_summary(result['cycles'], symbol))
                    rows.append(row)
                    cycle_parts.append(result['cycles'])
                week = metrics.aggregate(rows)
                week.update(allocation_id=allocation_id, initial_qty=initial, add_qty=add, position_cap=cap)
                gp, pay = week['money_ratio'] or 0., week['unit_payoff'] or 0.
                removed = week['net_yen'] - max(r['net_yen'] for r in rows)
                eligible = bool(round(week['net_yen'], 6) > 0 and round(gp, 10) > 1 and round(pay, 10) > 1
                                and week['positive_sessions'] >= 6 and round(removed, 6) > 0)
                selection = dict(eligible=eligible, score=min(gp, pay),
                                 recovery=week['net_yen']/week['drawdown_yen'] if week['drawdown_yen'] else 0.,
                                 best_session_removed_net=removed,
                                 best_session=max(rows, key=lambda r: r['net_yen'])['session'])
                record = dict(allocation_id=allocation_id, method_id=method, symbol=symbol, initial_qty=initial,
                              add_qty=add, position_cap=cap, week=week, sessions=rows,
                              risk=risk_summary(np.concatenate(cycle_parts), symbol), selection=selection)
                candidates.append(record)
                weekly_rows.append(dict(week, selection=selection, initial_risk=record['risk']))
                session_rows.extend(rows)
                if len(candidates) % 20 == 0 or len(candidates) == count:
                    print(f'{len(candidates)}/{count}配分、{len(session_rows)}セル、{time.time()-started:.1f}秒', flush=True)
    save('全配分の週合計.json', weekly_rows)
    save('全配分のセッション集計.json', session_rows)
    with (OUT / '固定型全配分の生台帳.pkl').open('wb') as stream:
        pickle.dump(fixed_blocks, stream, pickle.HIGHEST_PROTOCOL)
    # ----------------------------------------
    # 固定した選択基準から報告用の２案を抽出する。
    selections, report_methods, selected_records = [], [], {}
    for source_method in old['methods']:
        method = source_method['id']
        report_method = {k: source_method[k] for k in ['id', 'rank', 'name', 'signal', 'entry', 'exit']}
        report_method['variants'] = {}
        for symbol in CAPS:
            group = [r for r in candidates if r['method_id'] == method and r['symbol'] == symbol]
            selected, max_net = select(group)
            selection = dict(method_id=method, symbol=symbol, candidate_count=len(group),
                             eligible_count=sum(r['selection']['eligible'] for r in group),
                             selected_id=selected['allocation_id'] if selected else None,
                             max_net_id=max_net['allocation_id'])
            selections.append(selection)
            reference = selected or max_net
            report_method['variants'][symbol] = dict(selected=variant(reference, configurations),
                                                    max_net=variant(max_net, configurations),
                                                    candidate_count=len(group), eligible_count=selection['eligible_count'],
                                                    selected_is_reference=selected is None)
            selected_records[reference['allocation_id']] = reference
            selected_records[max_net['allocation_id']] = max_net
        report_methods.append(report_method)
    save('配分選択.json', selections)
    metadata = dict(period=old['metadata']['period'], date='2026-09-27',
                    candidate_count=count, session_count=len(session_rows), eligible_count=sum(r['selection']['eligible'] for r in candidates),
                    primary_policy='片方向の同時保有上限をTOPIXミニ10枚・NK225マイクロ20枚に固定。初回・追加枚数を上限内で比較した。返済後の再入場と累計返済枚数は制限しない。',
                    selection_rule=policy['損小利大資格']+' '+policy['損小利大順位'],
                    maximum_rule=policy['週収支最大'],
                    fixed_quantity='固定型では枚数を増やすと損益・最大下落が比例する。比率と回復率が同じため、自己資本・許容損失額未指定の代表を初回１枚とし、上限枚数での週収支最大配分を併記する。',
                    calculation='全327配分を保存済み原本順に再生した。数量の比例換算だけではない。信号・ATR・時刻・出口条件は元の４手法と同じ。',
                    data_scope=old['metadata']['data_scope']+' 同一週で配分を選んだ探索であり、未使用期間の検証ではない。',
                    observation=old['metadata']['observation'], cost=old['metadata']['cost'],
                    session_exit=old['metadata']['session_exit'], atr=old['metadata']['atr'],
                    tick=old['metadata']['tick'], units=old['metadata']['units'], budget=old['metadata']['budget'],
                    individual_operation='４手法をそれぞれ単独で運用した場合。４手法同時運用の合計上限を検証したものではない。',
                    initial_risk_difference='上限が同じでも初回枚数が違えば初期損失予算が違う。収支だけで効率・安全性の優劣を判断しない。',
                    original_sources_unchanged=True, hashes=source_hashes)
    save('allocation_report_data.json', dict(metadata=metadata, products=old['products'], methods=report_methods))
    # ----------------------------------------
    # 表示配分の全台帳と入力参照を保存し、独立監査を再現可能にする。
    blocks = {}
    for record in selected_records.values():
        method, symbol = record['method_id'], record['symbol']
        config = dict(configurations[method], initial_qty=record['initial_qty'], add_qty=record['add_qty'], audit_cap=CAPS[symbol])
        for session in SESSIONS:
            result = engine.run(inputs[(session, symbol)], directions[(method, session, symbol)], config)
            blocks[(record['allocation_id'], session, symbol)] = dict(config=config,
                trades=result['trades'], cycles=result['cycles'], stats=result['stats'], orders=result['orders'])
    with (OUT / '表示配分の生台帳.pkl').open('wb') as stream:
        pickle.dump(blocks, stream, pickle.HIGHEST_PROTOCOL)
    save('監査用入力参照.json', dict(inputs=[str(V16 / f'入力_{stage}.pkl') for stage in ['development', 'holdout']],
                                   states=str(V17 / '主方向状態.pkl'), source_hashes=source_hashes,
                                   direction='state[(session,symbol)][config.signal] * config.sign',
                                   result_key='(allocation_id,session,symbol)', selected_allocation_count=len(selected_records)))
    assert hashes() == source_hashes, '実行中に入力または研究コードが変更されました'
    save('探索完了記録.json', dict(合格=True, 配分数=count, セッションセル数=len(session_rows),
                                  選択生台帳セル数=len(blocks), 上限検査=maximum, 現在API取得数=0,
                                  入力原本不変=True, 経過秒=time.time()-started, 配分別選択=selections))
    print(json.dumps(dict(完了=True, 配分数=count, セル数=len(session_rows), 経過秒=time.time()-started,
                         選択=selections), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
