"""全31及び根説明補足の明示完了後だけ、増玉の損失原因を保存事実から独立検算する。"""

import argparse
import gc
import importlib.util
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
SYMBOLS = ('TOPIX', 'NK225')


def module(path: Path, name: str) -> object:
    """
    機能: 独立選定器又は保存入力読取器をmainなしで接続する。
    引数: path (Path)、name (str) は読込先と一意名。
    返り値: object はモジュール。根の説明・会計・選定関数は呼ばない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def equal(actual: object, expected: object, path: str = '') -> None:
    """
    機能: 独立再計算と保存説明の辞書・配列・数値を順序も含めて照合する。
    引数: actual/expected (object)、path (str) は診断項目。
    返り値: None。不一致なら停止。新しい取引条件の選別はしない。
    """
    if isinstance(expected, dict):
        assert isinstance(actual, dict) and set(actual) == set(expected), path
        for key, value in expected.items():
            equal(actual[key], value, path + '/' + str(key))
    elif isinstance(expected, (list, tuple)):
        assert isinstance(actual, (list, tuple)) and len(actual) == len(expected), path
        for index, value in enumerate(expected):
            equal(actual[index], value, path + '/' + str(index))
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        assert math.isfinite(float(actual)) and math.isfinite(float(expected)), path
        assert math.isclose(float(actual), float(expected), rel_tol=1e-10, abs_tol=1e-6), path
    else:
        assert actual == expected, path


def rows(values: object, columns: list[str]) -> list[dict]:
    """
    機能: 保存診断列を検算可能な数値辞書へ変換する。
    引数: values (ndarray[float])、columns (list[str])。
    返り値: list[dict] は元の順序を保持した事実。値を正答として無検証採用しない。
    """
    assert values.ndim == 2 and values.shape[1] == len(columns)
    return [dict(zip(columns, map(float, value))) for value in values]


def references(ident: str) -> list[str]:
    """
    機能: 宣言済み同初回Q・旧全量・出口の三対照を独立に構成する。
    引数: ident (str) はGx_Qy_Xz。
    返り値: list[str] は重複と自己対照を除いた順序。
    """
    mode, quantity, exit_name = ident.split('_')
    values = ['G0_' + quantity + '_' + exit_name, 'G0_QFULL_' + exit_name,
              mode + '_' + quantity + '_' + ('X3' if exit_name == 'X1' else 'X1')]
    return list(dict.fromkeys(value for value in values if value != ident))


def empty() -> dict:
    """
    機能: 親内負け・追加玉・R0超過の独立累計器を作る。
    引数: なし。
    返り値: dict は未集計の商品別事実。
    """
    return dict(winning_parent_losing_cohorts=dict(losing_cohorts=0, losing_lots=0, loss=0.),
                risk_budget=dict(excess_parents=0, realized_excess_sum=0., maximum_realized_excess=0.,
                                 maximum_observed_excess=0.),
                actual_add_cohorts=0, actual_add_lots=0, actual_add_profit=0., actual_add_loss=0.,
                completed_parents=0, completed_cohorts=0)


# ----------------------------------------


def inspect_account(key: tuple[str, str], ledger: dict, config: dict, material: dict,
                    selection: object, diagnostic: dict) -> tuple[dict, list[dict]]:
    """
    機能: 実注文を再会計し、親の現金予算・清算超過・各追加玉損失を独立検算する。
    引数: key (tuple[str,str])、ledger/config/material/diagnostic (dict)、selection (object)。
    返り値: tuple[dict,list[dict]] は一口座会計と親説明事実。
    全原板清算の重複監査はせず、保存した変化行の清算quoteを原入力へ照合する。
    """
    session, symbol = key
    account = selection.account(ledger, symbol)
    record = material['prices'][key]
    reference = material['metadata']['references']['|'.join(key)]['ref_open']
    assert reference['known_from_i'] == 0
    tick = float(record['tick'])
    width = max(2, math.ceil(float(reference['value']) * float(config['trend_initial_stop_bp'])
                             / 10000. / tick - 1e-10)) * tick
    multiplier = 1000. if symbol == 'TOPIX' else 10.
    parents = rows(ledger['growth_parent_diagnostics'], ledger['growth_parent_columns'])
    cohorts = rows(ledger['growth_cohorts'], ledger['growth_cohort_columns'])
    states = ledger['growth_state_changes']
    positions = {name: index + 1 for index, name in enumerate(ledger['growth_state_columns'])}
    assert states.ndim == 2 and states.shape[1] == 71
    assert int(states[0, 0]) == 0 and int(states[-1, 0]) == len(record['time_s']) - 1
    assert len(parents) == account['campaigns'] and len(cohorts) == account['cohorts']['cohorts']
    assert all(group['entry_kind'] in (0., 1.) for group in cohorts)
    facts = []
    for original in parents:
        ident, side = int(original['parent_id']), int(original['side'])
        members = [group for group in cohorts if int(group['parent_id']) == ident]
        ordered = sorted(members, key=lambda group: (group['entry_row'], group['cohort_id']))
        assert ordered and ordered[0]['entry_kind'] == 0 and all(group['entry_kind'] == 1 for group in ordered[1:])
        first = ordered[0]
        exit_row = int(first['exit_row'])
        quantity = int(sum(group['quantity'] for group in ordered))
        initial = int(first['quantity'])
        risk = initial * width * multiplier + 2 * selection.fee(initial, symbol)
        cash = sum(group['quantity'] * group['entry_price'] for group in ordered) * multiplier
        opening_fee = sum(selection.fee(int(group['quantity']), symbol) for group in ordered)
        closing_fee = selection.fee(quantity, symbol)
        for group in ordered:
            row = int(group['entry_row'])
            assert int(group['entry_seq']) == record['seq'][row]
            assert group['entry_time'] == record['time_s'][row]
            assert group['entry_price'] == record['ask' if side == 1 else 'bid'][row]
            assert group['exit_seq'] == record['seq'][exit_row] and group['exit_time'] == record['time_s'][exit_row]
            assert group['exit_price'] == record['bid' if side == 1 else 'ask'][exit_row]
            assert group['risk_budget'] == risk and group['initial_quantity'] == initial
        gross = side * sum(group['quantity'] * (first['exit_price'] - group['entry_price']) for group in ordered) * multiplier
        net = gross - opening_fee - closing_fee
        realized = max(0., -net - risk)
        observed = realized
        saved_parent_states = states[states[:, positions['parent_id']] == ident]
        held = saved_parent_states[saved_parent_states[:, positions['held_quantity']] > 0]
        assert len(held) > 0
        for state in held:
            row = int(state[0])
            assert int(first['entry_row']) <= row < exit_row
            owned = [group for group in ordered if group['entry_row'] <= row]
            amount = int(sum(group['quantity'] for group in owned))
            own_cash = sum(group['quantity'] * group['entry_price'] for group in owned) * multiplier
            own_fees = sum(selection.fee(int(group['quantity']), symbol) for group in owned) + selection.fee(amount, symbol)
            assert state[positions['held_quantity']] == amount
            assert state[positions['risk_budget']] == risk
            selection.close(state[positions['entry_cash']], own_cash, '変化行の実現金')
            selection.close(state[positions['total_fees']], own_fees, '変化行の全料')
            quote = float(record['bid' if side == 1 else 'ask'][row])
            qok = bool(record['quote_valid'][row]) and math.isfinite(float(record['bid'][row])) \
                and math.isfinite(float(record['ask'][row])) and record['bid'][row] > 0 \
                and record['ask'][row] > record['bid'][row]
            if qok:
                current = side * (amount * quote * multiplier - own_cash) - own_fees
                selection.close(state[positions['liquidation_quote']], quote, '保存変化行の清算quote')
                selection.close(state[positions['current_net']], current, '保存変化行の全量net')
                observed = max(observed, -current - risk)
            else:
                assert math.isnan(float(state[positions['current_net']]))
        last = held[-1]
        parent = dict(parent_id=float(ident), side=float(side), first_fill_row=first['entry_row'],
                      first_fill_time=first['entry_time'], first_fill_price=first['entry_price'],
                      initial_quantity=float(initial), final_quantity=float(quantity), risk_budget=float(risk),
                      entry_cash=float(cash), entry_fees=float(opening_fee), exit_fee=float(closing_fee),
                      weighted_entry=cash / (quantity * multiplier), exit_row=float(exit_row),
                      exit_seq=float(record['seq'][exit_row]), exit_time=float(record['time_s'][exit_row]),
                      exit_price=first['exit_price'], gross=float(gross), net=float(net),
                      realized_budget_excess=float(realized), maximum_observed_budget_excess=float(observed),
                      cohort_count=float(len(ordered)),
                      deadline=first['entry_time'] + float(config['trend_hold_seconds'])
                      if config['trend_hold_seconds'] else 0.,
                      protection_active=float(last[positions['protection_active']]),
                      final_stop=float(last[positions['effective_stop']]))
        equal(original, parent, '親24列独立事実')
        diagnostic['completed_parents'] += 1
        diagnostic['completed_cohorts'] += len(ordered)
        risk_note = diagnostic['risk_budget']
        risk_note['excess_parents'] += int(realized > 1e-5)
        risk_note['realized_excess_sum'] += realized
        risk_note['maximum_realized_excess'] = max(risk_note['maximum_realized_excess'], realized)
        risk_note['maximum_observed_excess'] = max(risk_note['maximum_observed_excess'], observed)
        for group in members:
            if net > 1e-5 and group['net'] < -1e-5:
                note = diagnostic['winning_parent_losing_cohorts']
                note['losing_cohorts'] += 1
                note['losing_lots'] += int(group['quantity'])
                note['loss'] -= group['net']
            if group['entry_kind'] == 1:
                diagnostic['actual_add_cohorts'] += 1
                diagnostic['actual_add_lots'] += int(group['quantity'])
                diagnostic['actual_add_profit'] += max(group['net'], 0.)
                diagnostic['actual_add_loss'] += max(-group['net'], 0.)
        facts.append(dict(session=session, symbol=symbol, parent=parent, cohorts=members))
    return dict(session=session, symbol=symbol, **account), facts


# ----------------------------------------


def period(summary: dict, source_rows: list[dict], symbol: str) -> dict:
    """
    機能: 独立期間会計へ比較に必要な黒字場・赤字場・活動場を足す。
    引数: summary (dict)、source_rows (list[dict])、symbol (str)。
    返り値: dict は根の比較差を検算する元値。
    """
    selected = [row for row in source_rows if row['symbol'] == symbol]
    answer = dict(summary['periods'][symbol])
    answer.update(losing_sessions=sum(row['net'] < -1e-5 for row in selected),
                  positive_sessions=sum(row['net'] > 1e-5 for row in selected),
                  active_sessions=sum(row['campaigns'] > 0 for row in selected))
    return answer


def main() -> None:
    """
    機能: 根の全31・独立全数・説明補足完了後のみ原因事実を新コードで検算する。
    引数: --root-all31-explanation-complete (bool) は根の明示通知受領時だけ指定する。
    返り値: None。独立原因JSONを新規保存し、正式条件・台帳・根説明を変更しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--root-all31-explanation-complete', action='store_true')
    args = parser.parse_args()
    assert args.root_all31_explanation_complete, '全31/独立全数/説明補足完了の明示前は金融結果を読みません'
    selection = module(HERE / 'selection.py', '101原因会計の独立選定器')
    fixed_path = WORK / '事前固定.json'
    fixed = selection.read(fixed_path)
    identifiers = {config['id'] for config in fixed['条件']}
    assert len(identifiers) == 20 and len(fixed['全31']) == 31
    for stage in ('front', 'back'):
        assert {path.stem for path in (WORK / stage / 'results').glob('*.json')} == identifiers
        assert {path.stem for path in (WORK / stage / 'ledgers').glob('*.pkl')} == identifiers
    explanation_path = WORK / 'analysis/説明補足.json'
    account_path = WORK / 'analysis/比較結果.json'
    audit_path = WORK / 'audit/全20全31の増玉注文と親cohort及び全原板会計の独立検算.json'
    assert explanation_path.is_file() and account_path.is_file() and audit_path.is_file()
    explanation, official, audit = map(selection.read, (explanation_path, account_path, audit_path))
    assert explanation['全合格'] and official['全合格'] and audit['合格'] and not audit['人工専用']
    assert audit['検査件数']['口座'] == 1240
    assert audit['SHA256'][str(account_path.relative_to(ROOT))] == selection.digest(account_path)
    assert explanation['根集計SHA256'] == selection.digest(account_path)
    for relative, expected in fixed['SHA256'].items():
        assert selection.digest(ROOT / relative) == expected, relative
    # ----------------------------------------
    # このコードは根helperをimportしない。入力は保存31場、実注文・診断は全数監査済み台帳。
    source = module(WORK / 'data.py', '101原因の不変保存入力')
    material = source.load_inputs(verify=False)
    first_prices = {(session, symbol): float(material['prices'][session, symbol]['price'][0])
                    for session in fixed['全31'] for symbol in SYMBOLS}
    diagnostic_ids = list(dict.fromkeys((official['primary'], official['selected'], 'G0_Q1_X1',
                                        'G0_QFULL_X1', 'G2_Q1_X1', 'G1_Q1_X3')))
    needed = list(dict.fromkeys(diagnostic_ids + [reference for ident in diagnostic_ids for reference in references(ident)]))
    configurations = {config['id']: config for config in fixed['条件']}
    computed, all_rows, facts, diagnostics = {}, {}, {}, {}
    bindings = {str(Path(__file__).relative_to(ROOT)): selection.digest(Path(__file__)),
                str((HERE / 'selection.py').relative_to(ROOT)): selection.digest(HERE / 'selection.py')}
    for ident in needed:
        config = configurations[ident]
        current_rows, current_facts = [], []
        current_diagnostics = {symbol: empty() for symbol in SYMBOLS}
        for stage in ('front', 'back'):
            result_path = WORK / stage / 'results' / (ident + '.json')
            ledger_path = WORK / stage / 'ledgers' / (ident + '.pkl')
            saved = selection.read(result_path)
            assert saved['config'] == config
            assert selection.digest(ledger_path) == saved['ledger_SHA256'] == audit['SHA256'][str(ledger_path.relative_to(ROOT))]
            bindings[str(ledger_path.relative_to(ROOT))] = selection.digest(ledger_path)
            bindings[str(result_path.relative_to(ROOT))] = selection.digest(result_path)
            ledger = selection.read(ledger_path)
            expected_sessions = fixed['前16'] if stage == 'front' else fixed['後15']
            assert set(ledger) == {(session, symbol) for session in expected_sessions for symbol in SYMBOLS}
            for key, stored in ledger.items():
                row, parent_facts = inspect_account(key, stored, config, material, selection, current_diagnostics[key[1]])
                current_rows.append(row)
                current_facts.extend(parent_facts)
            del ledger
            gc.collect()
        summary = selection.summarize(config, current_rows, fixed['全31'], first_prices)
        for symbol in SYMBOLS:
            value = period(summary, current_rows, symbol)
            saved_value = official['results'][ident]['periods']['全31'][symbol]
            for name in ('profit', 'loss', 'net', 'gross', 'fees', 'campaigns', 'active_sessions',
                         'positive_sessions', 'losing_sessions', 'winning_lots', 'losing_lots', 'flat_lots',
                         'lots', 'profit_share', 'payoff'):
                equal(saved_value[name], value[name], ident + '/' + symbol + '/' + name)
            equal(saved_value['cohorts'], value['cohorts'], ident + '/' + symbol + '/建玉群')
            for name, amount in summary['stability'][symbol].items():
                equal(official['results'][ident]['stability']['全31'][symbol][name], amount,
                      ident + '/' + symbol + '/安定性/' + name)
        computed[ident], all_rows[ident], facts[ident], diagnostics[ident] = summary, current_rows, current_facts, current_diagnostics
    # ----------------------------------------
    # 根派生JSONの三部分を、上の実注文会計と親状態から独立に作り直す。
    report_diagnostics = {ident: diagnostics[ident] for ident in diagnostic_ids}
    equal(explanation['report_diagnostics'], report_diagnostics, 'report_diagnostics')
    comparisons = {}
    for ident in diagnostic_ids:
        comparisons[ident] = {}
        assert official['comparison_pairs'][ident] == references(ident)
        for reference in references(ident):
            comparisons[ident][reference] = {}
            for symbol in SYMBOLS:
                value = period(computed[ident], all_rows[ident], symbol)
                old = period(computed[reference], all_rows[reference], symbol)
                stable, prior_stable = computed[ident]['stability'][symbol], computed[reference]['stability'][symbol]
                comparisons[ident][reference][symbol] = dict(
                    net_delta=value['net'] - old['net'], cohort_profit_delta=value['cohorts']['profit'] - old['cohorts']['profit'],
                    cohort_loss_delta=value['cohorts']['loss'] - old['cohorts']['loss'], fees_delta=value['fees'] - old['fees'],
                    red_sessions_delta=value['losing_sessions'] - old['losing_sessions'],
                    black_sessions_delta=value['positive_sessions'] - old['positive_sessions'],
                    active_sessions_delta=value['active_sessions'] - old['active_sessions'],
                    maximum_red_delta=stable['worst_session_loss_yen'] - prior_stable['worst_session_loss_yen'])
    equal(explanation['comparisons'], comparisons, 'comparisons')
    worst = {}
    for ident in dict.fromkeys((official['primary'], official['selected'])):
        worst[ident] = {}
        for symbol in SYMBOLS:
            red = sorted((row for row in all_rows[ident] if row['symbol'] == symbol and row['net'] < -1e-5),
                         key=lambda row: (row['net'], row['session']))[:3]
            worst[ident][symbol] = [dict(session=row['session'], net=row['net'],
                                       parents=[fact for fact in facts[ident]
                                                if fact['symbol'] == symbol and fact['session'] == row['session']])
                                    for row in red]
    equal(explanation['worst_sessions'], worst, 'worst_sessions')
    # ----------------------------------------
    # 相関した結果差を機構の一原因と断言しない。数量・建値・追加費用・線・再参加を分ける。
    small, full = 'G0_Q1_X1', 'G0_QFULL_X1'
    quantity_notes = {}
    for symbol in SYMBOLS:
        value, reference = computed[small]['stability'][symbol], computed[full]['stability'][symbol]
        quantity_notes[symbol] = dict(小Q黒字率=value['positive_session_rate'], 全量黒字率=reference['positive_session_rate'],
                                     小Q赤字場=value['losing_sessions'], 全量赤字場=reference['losing_sessions'],
                                     小Q最大赤字=value['worst_session_loss_yen'], 全量最大赤字=reference['worst_session_loss_yen'],
                                     判定='同じ黒字頻度の損失額低下は数量効果。異なる場合は丸め料等の差も確認し、予測改善へ一般化しない。')
    notes = [
        '追加時の全量net非負は、その時の保有利益が費用を賄うという状態条件。次の継続又は実返済黒字を保証しない。',
        '追加でweighted建値と全量停止線が変わる。追加玉自身の損失、先行玉利益の返却、料金増加、停止後の新規連鎖を同時に変え得るので、合計差だけで一原因を断定しない。',
        '現金R0を固定しても、次正常気配で約定するため実損失は超過し得る。超過事実と、R0以内でも累積する負けは別問題。',
        '親黒字に含まれる負cohortは計上済み。親netと追加cohort相殺前G/Lの両方で評価し、追加玉の収益性を親勝率から逆算しない。',
        '観測超過は全数原板監査済みの台帳に結び、当コードでは保存変化行を独立清算した範囲。真受信時計・二市場の真順・未来の利益は認定しない。',
        '全31既知の結果後分析。参考又は事後順位を未知性能の成功として扱わず、無取引・少枚数の低RMSだけを安定した黒字とは呼ばない。']
    for path in (fixed_path, account_path, explanation_path, audit_path, WORK / 'analysis/explain.py'):
        bindings[str(path.relative_to(ROOT))] = selection.digest(path)
    for path in material['paths']:
        bindings[str(Path(path).relative_to(ROOT))] = selection.digest(Path(path))
    proof = dict(全合格=True, 検査条件=needed, 根説明対象=diagnostic_ids,
                 検査口座数=len(needed) * 62, report_diagnostics=report_diagnostics,
                 comparisons=comparisons, worst_sessions=worst, 数量効果の独立対比=quantity_notes,
                 原因解釈の敵対的留保=notes,
                 scope='実注文/親/建玉群及び保存growth状態変化行の清算からの独立再計算。全原板清算の重複監査は行わずauditの全1240口座証跡へbind。',
                 根explain及びaccounting及びscore呼出=0, 売買及び固定既存資料変更=0,
                 全31既知=True, 新未見確認場数=0, 新売買実行=0, API取得=0, 実注文=0, SHA256=bindings)
    output_path = HERE / '根説明補足の親内損失と増玉及び予算超過と最悪場の独立反証.json'
    assert not output_path.exists()
    output_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 条件数=len(needed), 検査口座数=len(needed) * 62,
                         独立原因検査=output_path.name, SHA256=selection.digest(output_path)), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
