"""固定配分と現在状態による選択を、親の利益喪失と新しい約定経路に分解する。"""

import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
sys.path.insert(0, str(WORK))
import accounting
import catalog
import data
import research


def read(path: Path) -> object:
    """
    機能: 固定済み結果と明細を読み取る。
    引数: path(Path)。
    返り値: object。保存されたJSON又はpickle。
    """
    if path.suffix == '.pkl':
        with path.open('rb') as stream:
            return pickle.load(stream)
    return json.loads(path.read_text(encoding='utf-8'))


def score(result: dict) -> tuple:
    """
    機能: 前16の悪い側の金額利益割合を優先する固定採点を実行する。
    引数: result(dict)。
    返り値: tuple。昇順で選定する採点と同点解消ID。
    """
    rows = [result['periods']['前16'][s] for s in catalog.SYMBOLS]
    shares = [r['profit_share'] if r['profit_share'] is not None else -1 for r in rows]
    rates = [r['positive_session_rate'] if r['positive_session_rate'] is not None else -1 for r in rows]
    return -min(shares), -min(rates), -sum(shares), result['config']['id']


def select(results: dict) -> dict:
    """
    機能: 前16の固定足切り・採点で参考代表を選び、未見と呼ばない。
    引数: results(dict[str,dict])。
    返り値: dict。候補群、足切り段階、選定IDと固定理論主を明示する。
    """
    pool = list(results.values())
    active = [r for r in pool if all(r['periods']['前16'][s]['campaigns'] >= 20
                                    and r['periods']['前16'][s]['active_sessions'] >= 8
                                    for s in catalog.SYMBOLS)]
    positive = [r for r in active if all(r['periods']['前16'][s]['net'] > 0 for s in catalog.SYMBOLS)]
    good = [r for r in positive if all(r['periods']['前16'][s]['payoff'] is not None
                                      and r['periods']['前16'][s]['payoff'] > 1
                                      for s in catalog.SYMBOLS)]
    choices = good or positive or active or pool
    return dict(id=min(choices, key=score)['config']['id'],
                level=0 if good else 1 if positive else 2 if active else 3,
                eligible_ids=[r['config']['id'] for r in choices],
                scores={r['config']['id']: score(r) for r in choices},
                理論主差替え=False, 全30既知=True)


def parent_key(trade: np.ndarray) -> tuple:
    """
    機能: 源、発注判断、実新規が同じ親だけを比較対象に対応させる。
    引数: trade(ndarray、公開16列の一親)。
    返り値: tuple。将来の返済条件は対応キーへ使わない。
    """
    return tuple(float(trade[i]) for i in (1, 15, 2, 4, 5, 6))


def partition(actual: np.ndarray, base: np.ndarray) -> dict:
    """
    機能: 改善額を消えた損失、消えた利益、同じ新規の出口差、新規経路に分ける。
    引数: actual/base(ndarray、同枠・同商品一場の実決済親)。
    返り値: dict。過去決定へ使わない事後会計の完全な差額分解。
    """
    a = {parent_key(t): t for t in actual}
    b = {parent_key(t): t for t in base}
    assert len(a) == len(actual) and len(b) == len(base)
    matched = set(a) & set(b)
    absent = [b[k] for k in set(b)-matched]
    novel = [a[k] for k in set(a)-matched]
    saved = sum(-t[11] for t in absent if t[11] < 0)
    missed = sum(t[11] for t in absent if t[11] > 0)
    changed = sum(a[k][11]-b[k][11] for k in matched)
    new_profit = sum(t[11] for t in novel if t[11] > 0)
    new_loss = sum(-t[11] for t in novel if t[11] < 0)
    delta = float(actual[:, 11].sum()-base[:, 11].sum())
    assert abs(saved-missed+changed+new_profit-new_loss-delta) < 1e-4
    return dict(saved_loss=float(saved), missed_profit=float(missed),
                changed_exit=float(changed), new_profit=float(new_profit),
                new_loss=float(new_loss), delta=delta, matched=len(matched),
                absent=len(absent), novel=len(novel))


def same_quantity_control(records: dict, mixture: str = 'M82',
                          trend: str = 'J8', reversal: str = 'O2') -> dict:
    """
    機能: 固定8/2配分の注文・価格経路が同量単独と一致するか確認する。
    引数: records(dict[str,dict]、保存済み全明細)、mixture/trend/reversal(str、条件ID)。
    返り値: dict。120源口座の非干渉検査。
    """
    count = 0
    compared = [i for i in range(17) if i not in (2, 16)]
    for key, ledger in records[mixture].items():
        for source, single in [(0, trend), (1, reversal)]:
            actual = ledger['orders'][ledger['orders'][:, 3] == source]
            expected = records[single][key]['orders']
            np.testing.assert_array_equal(actual[:, compared], expected[:, compared])
            assert ledger['source_curve_column_SHA256'][source] == \
                records[single][key]['source_curve_column_SHA256'][source]
            count += 1
    return dict(全合格=True, 源別口座数=count, 注文と価格数量料金完全一致=True,
                全原板源別時価完全一致=True, 同一枚数対照=True)


def main() -> None:
    """
    機能: 凍結27条件の全会計を読み、主・参考代表・差額原因を保存する。
    引数: なし。
    返り値: None。注文コードや過去調査の成果は変更しない。
    """
    fixed = read(WORK/'事前固定.json')
    research.validate(fixed)
    conditions = fixed['条件']
    locations = {c['id']: WORK for c in conditions}
    primary = catalog.PRIMARY
    # ----------------------------------------
    # 追加段も完結している場合だけ統合する。悲観価格の対照を参考代表へ混ぜない。
    extra_path = WORK/'round2/事前固定.json'
    extra = read(extra_path) if extra_path.exists() else None
    if extra is not None:
        for relative, expected in extra['SHA256'].items():
            assert data.digest(ROOT/relative) == expected, relative
        assert all((WORK/'round2/results'/f"{c['id']}.json").exists() for c in extra['条件'])
        conditions = conditions+extra['条件']
        locations.update({c['id']: WORK/'round2' for c in extra['条件']})
        primary = extra['主']
    results, records = {}, {}
    for c in conditions:
        ident = c['id']
        results[ident] = read(locations[ident]/'results'/f'{ident}.json')
        assert results[ident]['config'] == c
        ledger_path = locations[ident]/'ledgers'/f'{ident}.pkl'
        assert data.digest(ledger_path) == results[ident]['ledger_SHA256']
        records[ident] = read(ledger_path)
    original_selected = select({ident: r for ident, r in results.items() if locations[ident] == WORK})
    candidate_pool = {ident: r for ident, r in results.items()
                      if r['config'].get('improve_limit')} if extra is not None else results
    selected = select(candidate_pool)
    differences = {}
    for ident in [c['id'] for c in fixed['条件'] if c['selection'] == 'gated_fixed'
                  and c['trend_budget'] == 8 and c['range_budget'] == 2]:
        per_account = {key: partition(records[ident][key]['trades'], records['M82'][key]['trades'])
                       for key in records['M82']}
        differences[ident] = {name: {s: {field: sum(v[field] for key, v in per_account.items()
                                                   if key[0] in sessions and key[1] == s)
                                        for field in next(iter(per_account.values()))}
                                     for s in catalog.SYMBOLS}
                             for name, sessions in [('全30', fixed['全30']), ('前16', fixed['前16']),
                                                    ('後14', fixed['後14'])]}
    if extra is not None:
        for ident in ('G82_C_Q', 'G82_C_A', 'G82_C_QA', 'G82_E_QA', 'G82_X_QA'):
            baseline = 'M82_Q' if results[ident]['config']['improve_limit'] else 'M82'
            per_account = {key: partition(records[ident][key]['trades'], records[baseline][key]['trades'])
                           for key in records[baseline]}
            differences[ident] = {name: {s: {field: sum(v[field] for key, v in per_account.items()
                                                       if key[0] in sessions and key[1] == s)
                                            for field in next(iter(per_account.values()))}
                                         for s in catalog.SYMBOLS}
                                 for name, sessions in [('全30', fixed['全30']), ('前16', fixed['前16']),
                                                        ('後14', fixed['後14'])]}
    both80 = [ident for ident, r in results.items()
              if all(r['periods']['全30'][s]['profit_share'] is not None
                     and r['periods']['全30'][s]['profit_share'] >= .8
                     and r['periods']['全30'][s]['net'] > 0
                     and r['periods']['全30'][s]['campaigns'] >= 20
                     and r['periods']['全30'][s]['active_sessions'] >= 8 for s in catalog.SYMBOLS)]
    strict = [ident for ident, r in results.items()
              if all(r['periods']['全30'][s]['net'] >= results['J10']['periods']['全30'][s]['net']
                     and (r['periods']['全30'][s]['profit_share'] or 0) >=
                         (results['J10']['periods']['全30'][s]['profit_share'] or 0)
                     and r['periods']['全30'][s]['equity_drawdown'] <=
                         results['J10']['periods']['全30'][s]['equity_drawdown']
                     and r['periods']['全30'][s]['positive_sessions'] >=
                         results['J10']['periods']['全30'][s]['positive_sessions']
                     for s in catalog.SYMBOLS)
              and all(any((r['periods']['全30'][s][field] - results['J10']['periods']['全30'][s][field])
                           * direction > 1e-6
                           for field, direction in [('net', 1), ('profit_share', 1),
                                                    ('equity_drawdown', -1), ('positive_sessions', 1)])
                      for s in catalog.SYMBOLS) and ident != 'J10']
    proof = dict(全合格=True, 条件数=len(results), primary=primary, catalog=conditions,
                 selected=selected['id'], selection_proof=selected,
                 original_selection_proof=original_selected,
                 results=results, differences=differences,
                 fixed_noninterference=same_quantity_control(records),
                 fixed_quote_noninterference=same_quantity_control(records, 'M82_Q', 'J8_Q', 'O2_Q')
                     if extra is not None else None,
                 both80=both80, strict_both_improvements=strict,
                 all_sessions_positive=[ident for ident, r in results.items()
                    if all(r['periods']['全30'][s]['all_sessions_profitable'] for s in catalog.SYMBOLS)],
                 全期間既知=True, 現在API取得=0, 実注文=0,
                 結果SHA256={str((locations[ident]/'results'/f'{ident}.json').relative_to(ROOT)):
                            data.digest(locations[ident]/'results'/f'{ident}.json') for ident in results})
    note_path = HERE/'結論.json'
    if note_path.exists():
        note = read(note_path)
        assert note['結果SHA256'] == proof['結果SHA256'], '結論と結果の対応が変わりました'
        proof.update(conclusion=note['conclusion'], cause_notes=note['cause_notes'])
    research.save(HERE/'比較結果.json', proof)
    print(json.dumps(dict(主=primary, 前16代表=selected['id'], 両商品80=both80,
                          全日両黒字=proof['all_sessions_positive'], 厳格改善=strict), ensure_ascii=False))


if __name__ == '__main__':
    main()
