"""増玉後の停止余裕と初回玉の返却損失を、正式説明完了後の保存事実だけで独立に調べる。"""

import argparse
from datetime import datetime, timedelta, timezone
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
    機能: 独立検算器をmainなしで接続する。
    引数: path (Path)、name (str) は対象と一意名。
    返り値: object はモジュール。根の売買・説明関数は呼ばない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    answer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(answer)
    return answer


def dictionaries(array: object, columns: list[str], clean: bool = False) -> list[dict]:
    """
    機能: 保存列から数値辞書を作り、要求時だけ非有限診断をnullにする。
    引数: array (ndarray[float])、columns (list[str])、clean (bool)。
    返り値: list[dict] は順序を保つ行。nullをFalse又は支持成立へ置換しない。
    """
    assert array.ndim == 2 and array.shape[1] == len(columns)
    answer = []
    for row in array:
        values = [float(value) for value in row]
        if clean:
            values = [value if math.isfinite(value) else None for value in values]
        answer.append(dict(zip(columns, values)))
    return answer


def clock(stamp: float) -> str:
    """
    機能: 原本由来の価格代理時計を日本時間の表示に変換する。
    引数: stamp (float) は保存されたepoch秒。
    返り値: str はISO時刻。真受信時計又は二市場の共通受信順とは主張しない。
    """
    return datetime.fromtimestamp(stamp, timezone(timedelta(hours=9))).isoformat(timespec='milliseconds')


def distribution(values: list[float], selection: object) -> dict:
    """
    機能: 追加後の停止余裕を少数集約する。
    引数: values (list[float])、selection (object) は独立分位計算器。
    返り値: dict は件数・最小・q25・中央値・最大。空の場合は不明。
    """
    return dict(count=len(values), minimum=min(values) if values else None,
                q25=selection.quantile(values, .25), median=selection.quantile(values, .5),
                maximum=max(values) if values else None)


def collect(key: tuple[str, str], stored: dict, selection: object, cause: object) -> tuple[dict, list[dict], list[dict]]:
    """
    機能: 実追加イベントと建玉群を対応させ、停止余裕・初回玉・予算以内外を再計算する。
    引数: key (tuple[str,str])、stored (dict)、selection/cause (object) は独立検算器。
    返り値: tuple[dict,list[dict],list[dict]] は会計・親原因・実追加事実。
    実追加を新策略へ置換せず、各玉のnetはこの実出口の事後原因として扱う。
    """
    session, symbol = key
    accounting = selection.account(stored, symbol)
    parents = dictionaries(stored['growth_parent_diagnostics'], stored['growth_parent_columns'])
    cohorts = dictionaries(stored['growth_cohorts'], stored['growth_cohort_columns'])
    events = dictionaries(stored['growth_events'], stored['growth_event_columns'], clean=True)
    assert len(stored['growth_event_columns']) == 74
    tick, multiplier = (.5, 1000.) if symbol == 'TOPIX' else (10., 10.)
    parent_facts, add_facts = [], []
    for parent in parents:
        ident, side = int(parent['parent_id']), int(parent['side'])
        groups = [group for group in cohorts if int(group['parent_id']) == ident]
        firsts = [group for group in groups if group['entry_kind'] == 0]
        additions = [group for group in groups if group['entry_kind'] == 1]
        assert len(firsts) == 1 and len(firsts) + len(additions) == len(groups)
        initial = firsts[0]
        width = (parent['risk_budget'] - 2 * selection.fee(int(initial['quantity']), symbol)) \
            / (initial['quantity'] * multiplier)
        assert width >= 2 * tick
        net = sum(group['net'] for group in groups)
        cause.equal(parent['net'], net, '追加原因の親/建玉群net')
        add_profit = sum(max(group['net'], 0.) for group in additions)
        add_loss = sum(max(-group['net'], 0.) for group in additions)
        cause.equal(initial['net'] + add_profit - add_loss, net, '初回と追加の恒等式')
        realized = max(0., -net - parent['risk_budget'])
        cause.equal(parent['realized_budget_excess'], realized, '追加原因の実予算超過')
        parent_facts.append(dict(session=session, symbol=symbol, parent_id=ident, side=side,
                                 first_entry_row=int(initial['entry_row']), first_entry_seq=int(initial['entry_seq']),
                                 first_entry_clock=clock(initial['entry_time']), exit_row=int(parent['exit_row']),
                                 exit_seq=int(parent['exit_seq']), exit_clock=clock(parent['exit_time']),
                                 initial_quantity=int(initial['quantity']), final_quantity=int(parent['final_quantity']),
                                 parent_net=net, initial_cohort_net=initial['net'],
                                 add_cohorts=len(additions), add_lots=int(sum(group['quantity'] for group in additions)),
                                 add_profit=add_profit, add_loss=add_loss, initial_width=width,
                                 risk_budget=parent['risk_budget'], realized_excess=realized,
                                 red_parent_initial_profitable=net < -1e-5 and initial['net'] > 1e-5,
                                 red_within_budget=net < -1e-5 and realized <= 1e-5))
        for group in additions:
            matches = [event for event in events if event['code'] == 3 and int(event['parent_id']) == ident
                       and int(event['row']) == int(group['entry_row'])]
            reservations = [event for event in events if event['code'] == 2 and int(event['parent_id']) == ident
                            and int(event['row']) == int(group['decision_row'])]
            assert len(matches) == len(reservations) == 1
            actual, planned = matches[0], reservations[0]
            assert actual['quantity'] == group['quantity'] == planned['quantity']
            assert actual['last_fill_row'] == group['entry_row']
            assert planned['proposed_stop'] is not None and planned['effective_stop'] is not None
            cause.equal(abs(initial['entry_price'] - actual['initial_line']), width, '初期幅と固定予算幅')
            known_distance = actual['liquidation_quote'] is not None and actual['effective_stop'] is not None
            distance = side * (actual['liquidation_quote'] - actual['effective_stop']) if known_distance else None
            planned_tightening = side * (planned['proposed_stop'] - planned['effective_stop'])
            actual_tightening = side * (actual['effective_stop'] - planned['effective_stop']) \
                if actual['effective_stop'] is not None else None
            add_facts.append(dict(session=session, symbol=symbol, parent_id=ident, cohort_id=int(group['cohort_id']),
                                  side=side, quantity=int(group['quantity']), decision_row=int(group['decision_row']),
                                  decision_seq=int(group['decision_seq']), decision_clock=clock(group['decision_time']),
                                  fill_row=int(group['entry_row']), fill_seq=int(group['entry_seq']),
                                  fill_clock=clock(group['entry_time']), fill_price=group['entry_price'],
                                  liquidation_quote=actual['liquidation_quote'], effective_stop=actual['effective_stop'],
                                  stop_distance=distance, stop_distance_ticks=distance / tick if distance is not None else None,
                                  stop_distance_initial_widths=distance / width if distance is not None else None,
                                  initial_width=width,
                                  planned_cushion=planned['proposed_cushion'],
                                  planned_cushion_initial_widths=planned['proposed_cushion'] / width,
                                  planned_stop_tightening=planned_tightening,
                                  actual_stop_tightening_from_reservation=actual_tightening,
                                  actual_quantity=int(actual['held_quantity']),
                                  actual_current_net=actual['current_net'], parent_net=net,
                                  initial_cohort_net=initial['net'], add_cohort_net=group['net'],
                                  risk_budget=parent['risk_budget'], realized_excess=realized))
    assert len(add_facts) == accounting['adding_order_count']
    return accounting, parent_facts, add_facts


def summarize(parent_facts: list[dict], add_facts: list[dict], selection: object) -> dict:
    """
    機能: 赤字親内初回黒字、追加停止余裕、予算以内の反復負けを集計する。
    引数: parent_facts/add_facts (list[dict])、selection (object)。
    返り値: dict は金額・枚数・親数及び代表時刻。取引削減を成功へ数えない。
    """
    red = [fact for fact in parent_facts if fact['parent_net'] < -1e-5]
    red_first_green = [fact for fact in red if fact['red_parent_initial_profitable']]
    excess = [fact for fact in red if fact['realized_excess'] > 1e-5]
    within = [fact for fact in red if fact['red_within_budget']]
    repeated = {}
    for fact in within:
        repeated[fact['session']] = repeated.get(fact['session'], 0) + 1
    repeated = {session: count for session, count in sorted(repeated.items()) if count >= 2}
    measured = [fact for fact in add_facts if fact['stop_distance'] is not None]
    values = [fact['stop_distance_initial_widths'] for fact in measured]
    ratio = distribution(values, selection)
    selected = sorted(measured, key=lambda fact: (fact['stop_distance_initial_widths'], fact['session'], fact['fill_row']))[:3]
    initial_examples = sorted(red_first_green, key=lambda fact: (-fact['add_loss'], fact['session'], fact['first_entry_row']))[:3]
    return dict(completed_parents=len(parent_facts), red_parents=len(red),
                red_parent_initial_profitable=dict(parents=len(red_first_green),
                    initial_cohort_profit=sum(fact['initial_cohort_net'] for fact in red_first_green),
                    add_cohorts=sum(fact['add_cohorts'] for fact in red_first_green),
                    add_lots=sum(fact['add_lots'] for fact in red_first_green),
                    add_profit=sum(fact['add_profit'] for fact in red_first_green),
                    add_loss=sum(fact['add_loss'] for fact in red_first_green), examples=initial_examples),
                actual_add=dict(cohorts=len(add_facts), lots=sum(fact['quantity'] for fact in add_facts),
                    profit=sum(max(fact['add_cohort_net'], 0.) for fact in add_facts),
                    loss=sum(max(-fact['add_cohort_net'], 0.) for fact in add_facts)),
                added_stop=dict(initial_width_ratio=ratio,
                    ticks=distribution([fact['stop_distance_ticks'] for fact in measured], selection),
                    unavailable_add_fills=len(add_facts) - len(measured),
                    less_than_initial_width=sum(fact['stop_distance_initial_widths'] < 1 for fact in measured),
                    at_or_beyond_stop=sum(fact['stop_distance'] <= 0 for fact in measured),
                    planned_stop_tightened=sum(fact['planned_stop_tightening'] > 1e-8 for fact in add_facts),
                    actual_stop_tightened=sum(fact['actual_stop_tightening_from_reservation'] is not None
                        and fact['actual_stop_tightening_from_reservation'] > 1e-8 for fact in add_facts),
                    examples=selected),
                risk=dict(excess_parents=len(excess), excess_parent_loss=sum(-fact['parent_net'] for fact in excess),
                    excess_amount=sum(fact['realized_excess'] for fact in excess),
                    within_budget_red_parents=len(within), within_budget_loss=sum(-fact['parent_net'] for fact in within),
                    repeated_within_budget_loss_sessions=repeated))


# ----------------------------------------


def main() -> None:
    """
    機能: 全31・独立原因・説明補足の明示完了後に追加原因を別新資料へ保存する。
    引数: --root-all31-explanation-complete (bool) は根が当該通知をした場合だけ指定する。
    返り値: None。イベントと親原因の派生資料だけを保存し、新しい売買は行わない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--root-all31-explanation-complete', action='store_true')
    args = parser.parse_args()
    assert args.root_all31_explanation_complete, '全31/説明補足完了の明示前は新金融結果を読みません'
    selection = module(HERE / 'selection.py', '101増玉原因の独立会計')
    cause = module(HERE / 'cause_check.py', '101増玉原因の独立照合')
    explanation_path = WORK / 'analysis/説明補足.json'
    cause_path = HERE / '根説明補足の親内損失と増玉及び予算超過と最悪場の独立反証.json'
    assert explanation_path.is_file() and cause_path.is_file()
    explanation, prior = selection.read(explanation_path), selection.read(cause_path)
    assert prior['全合格'] and explanation['全合格']
    assert prior['SHA256'][str(explanation_path.relative_to(ROOT))] == selection.digest(explanation_path)
    ids = list(explanation['growth_event_facts'])
    results, causal_summary, bindings, accounts = {}, {}, {}, 0
    for ident in ids:
        all_parents, all_adds, observed_events = [], [], []
        for stage in ('front', 'back'):
            path = WORK / stage / 'ledgers' / (ident + '.pkl')
            assert prior['SHA256'][str(path.relative_to(ROOT))] == selection.digest(path)
            bindings[str(path.relative_to(ROOT))] = selection.digest(path)
            ledgers = selection.read(path)
            for key, stored in ledgers.items():
                accounting, parents, adds = collect(key, stored, selection, cause)
                assert accounting['campaigns'] == len(parents)
                all_parents.extend(parents)
                all_adds.extend(adds)
                observed_events.append(dict(session=key[0], symbol=key[1],
                    events=dictionaries(stored['growth_events'], stored['growth_event_columns'], clean=True)))
                accounts += 1
            del ledgers
        cause.equal(explanation['growth_event_facts'][ident], observed_events, 'growth_event_facts/' + ident)
        results[ident], causal_summary[ident] = {}, {}
        for symbol in SYMBOLS:
            parent_subset = [fact for fact in all_parents if fact['symbol'] == symbol]
            add_subset = [fact for fact in all_adds if fact['symbol'] == symbol]
            results[ident][symbol] = summarize(parent_subset, add_subset, selection)
            measured = [fact for fact in add_subset if fact['stop_distance'] is not None]
            red = [fact for fact in parent_subset if fact['parent_net'] < -1e-5]
            first_green = [fact for fact in red if fact['initial_cohort_net'] > 1e-5]
            excess = [fact for fact in red if fact['realized_excess'] > 1e-5]
            causal_summary[ident][symbol] = dict(condition=ident, losing_parents=len(red),
                losing_parents_with_profitable_initial=len(first_green),
                initial_profit_in_losing_parents=sum(fact['initial_cohort_net'] for fact in first_green),
                budget_excess_losing_parents=len(excess), within_budget_losing_parents=len(red) - len(excess),
                measured_add_fills=len(measured), unavailable_add_fills=len(add_subset) - len(measured),
                median_stop_distance_initial_widths=selection.quantile(
                    [fact['stop_distance_initial_widths'] for fact in measured], .5),
                below_one_initial_width_add_fills=sum(fact['stop_distance_initial_widths'] < 1. - 1e-8 for fact in measured),
                already_at_stop_add_fills=sum(fact['stop_distance'] <= 1e-8 for fact in measured))
            root = explanation['report_diagnostics'][ident][symbol]
            calculated = results[ident][symbol]['actual_add']
            cause.equal(root['actual_add_cohorts'], calculated['cohorts'], '追加数')
            cause.equal(root['actual_add_lots'], calculated['lots'], '追加枚数')
            cause.equal(root['actual_add_profit'], calculated['profit'], '追加利益')
            cause.equal(root['actual_add_loss'], calculated['loss'], '追加損失')
    cause.equal(explanation['causal_summary'], causal_summary, 'causal_summary')
    # ----------------------------------------
    # 次候補は未測定。下記は同じR0と停止線据置を両立するための必要条件である。
    hypotheses = dict(
        停止線据置=dict(状態='未採用・未再生',
            必要条件='追加後の全玉を既存effective_stopで清算した費用後net>=−R0。満たさなければstop据置とR0固定は両立しない。',
            恒等式='旧停止線での追加後net = 旧停止線での追加前net + d×δQ×(旧停止値−追加価格)×倍率 − 増分の新規料及び全量返済料。',
            反例='買いの停止値が追加価格より下なら追加分の停止損失が増える。既存利益があっても予算余剰を超えれば不合格。',
            対照='同Q/同出口のG0と現G1/G2を保持し、追加可否・逃した勝ち・後続新規連鎖・金額損益を全場で比べる。'),
        初期幅で余裕測定=dict(状態='未採用・未再生',
            意味='追加後統合停止線までのside付き清算気配距離を、呼値1/2ではなく初回固定Sの倍数で要求する別ゲート。',
            留保='活動を減らす選択で、継続予測の改善ではない。実追加fill悪化と次返済までの変動は防げず、見送った勝ちも含める。',
            交絡回避='stop据置と幅gateを同時に変えず一軸比較。赤字額だけでなく黒字率・活動・親/cohort割合・最大日除外を示す。'))
    for path in (Path(__file__), HERE / 'selection.py', HERE / 'cause_check.py', explanation_path, cause_path):
        bindings[str(path.relative_to(ROOT))] = selection.digest(path)
    proof = dict(全合格=True, 検査口座数=accounts, 原因結果=results, 独立causal_summary=causal_summary,
                 次仮説の敵対的検討=hypotheses,
                 限定='各cohortはこの新規連鎖と実出口時点の事実。初回cohort黒字を増玉無し策略の反実仮想損益へ置換しない。',
                 時刻='原本由来のCurrentPriceTime代理時計と実seq。真受信時計又は二市場共通受信順を証明しない。',
                 正式条件及び既存成果変更=0, 新戦略実行=0, 新未見確認場数=0, API取得=0, 実注文=0, SHA256=bindings)
    path = HERE / '赤字親の初回利益と追加後停止距離及び予算内反復負けの独立原因.json'
    assert not path.exists()
    path.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 口座数=accounts, SHA256=selection.digest(path)), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
