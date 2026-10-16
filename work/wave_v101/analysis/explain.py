"""独立会計の後で、実玉の損失と固定予算超過を売買に還流せず説明する。"""

import argparse
from datetime import datetime, timedelta, timezone
import gc
import hashlib
import json
import math
from pathlib import Path
import pickle

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
SYMBOLS = ('TOPIX', 'NK225')


def read(path: Path) -> dict:
    """
    機能: 保存した会計又は独立検査を読み込む。
    引数: path(Path)は信頼された作業資料。
    返り値: dict。JSON資料。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 説明の根拠を正式結果へ結び付ける。
    引数: path(Path)は既存ファイル。
    返り値: str。SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def objects(values, columns: list[str]) -> list[dict]:
    """
    機能: 保存列名を使って親又は実新規玉群を辞書へ変換する。
    引数: values(ndarray)、columns(list[str])。
    返り値: list[dict]。原数値を保った行。
    """
    return [{name: float(value) for name, value in zip(columns, row)} for row in values]


def empty_diagnostic() -> dict:
    """
    機能: 親内損失と予算超過の報告用集計を用意する。
    引数: なし。
    返り値: dict。まだ観測を足していない集計。
    """
    return dict(winning_parent_losing_cohorts=dict(losing_cohorts=0, losing_lots=0, loss=0.),
                risk_budget=dict(excess_parents=0, realized_excess_sum=0.,
                                 maximum_realized_excess=0., maximum_observed_excess=0.),
                actual_add_cohorts=0, actual_add_lots=0, actual_add_profit=0., actual_add_loss=0.,
                completed_parents=0, completed_cohorts=0)


def collect(ledgers: dict, diagnostics: dict, event_facts: list[dict]) -> list[dict]:
    """
    機能: 実返済した玉だけから親内損失、増玉損益、予算超過を集計する。
    引数: ledgers(dict、保存口座)、diagnostics(dict、商品別累計)、event_facts(list[dict]、イベント追記先)。
    返り値: list[dict]。親ごとの説明用事実。新しい売買は計算しない。
    """
    facts = []
    for (session, symbol), ledger in ledgers.items():
        parents = objects(ledger['growth_parent_diagnostics'], ledger['growth_parent_columns'])
        cohorts = objects(ledger['growth_cohorts'], ledger['growth_cohort_columns'])
        events = [{name: value if math.isfinite(value) else None for name, value in row.items()}
                  for row in objects(ledger['growth_events'], ledger['growth_event_columns'])]
        event_facts.append(dict(session=session, symbol=symbol, events=events))
        current = diagnostics[symbol]
        by_parent = {int(row['parent_id']): row for row in parents}
        assert all(row['exit_row'] >= 0 for row in parents + cohorts)
        assert abs(sum(row['net'] for row in parents) - sum(row['net'] for row in cohorts)) < 1e-5
        current['completed_parents'] += len(parents)
        current['completed_cohorts'] += len(cohorts)
        for cohort in cohorts:
            parent = by_parent[int(cohort['parent_id'])]
            if parent['net'] > 1e-5 and cohort['net'] < -1e-5:
                item = current['winning_parent_losing_cohorts']
                item['losing_cohorts'] += 1
                item['losing_lots'] += int(cohort['quantity'])
                item['loss'] -= cohort['net']
            if cohort['entry_kind'] != 0:
                current['actual_add_cohorts'] += 1
                current['actual_add_lots'] += int(cohort['quantity'])
                current['actual_add_profit'] += max(cohort['net'], 0.)
                current['actual_add_loss'] += max(-cohort['net'], 0.)
        for parent in parents:
            excess = max(parent['realized_budget_excess'], 0.)
            risk = current['risk_budget']
            risk['excess_parents'] += int(excess > 1e-5)
            risk['realized_excess_sum'] += excess
            risk['maximum_realized_excess'] = max(risk['maximum_realized_excess'], excess)
            risk['maximum_observed_excess'] = max(risk['maximum_observed_excess'], parent['maximum_observed_budget_excess'])
            members = [row for row in cohorts if int(row['parent_id']) == int(parent['parent_id'])]
            assert len(members) == int(parent['cohort_count'])
            facts.append(dict(session=session, symbol=symbol, parent=parent, cohorts=members))
    return facts


def causal_summary(ident: str, diagnostics: dict, facts: list[dict], packets: list[dict]) -> dict:
    """
    機能: 初回益の相殺と増玉後停止距離を事後の原因事実として集計する。
    引数: ident(str)、diagnostics(dict)、facts/packets(list[dict])は当該条件の保存事実。
    返り値: dict。時間を巻き戻して仮の約定利益へ置換しない集計。
    """
    output = {}
    for symbol in SYMBOLS:
        selected = [fact for fact in facts if fact['symbol'] == symbol]
        losing = [fact for fact in selected if fact['parent']['net'] < -1e-5]
        initial_winners = [fact for fact in losing if fact['cohorts'][0]['net'] > 1e-5]
        ratios, distances, unavailable = [], [], 0
        by_parent = {(fact['session'], int(fact['parent']['parent_id'])): fact for fact in selected}
        multiplier = 1000. if symbol == 'TOPIX' else 10.
        for packet in packets:
            if packet['symbol'] != symbol:
                continue
            for event in packet['events']:
                if event['code'] != 3:
                    continue
                values = (event['parent_id'], event['liquidation_quote'], event['effective_stop'])
                if any(value is None for value in values):
                    unavailable += 1
                    continue
                fact = by_parent[packet['session'], int(event['parent_id'])]
                parent, initial = fact['parent'], fact['cohorts'][0]
                width = (parent['risk_budget'] - 2. * initial['entry_fee']) / (initial['quantity'] * multiplier)
                assert width > 0
                distance = parent['side'] * (event['liquidation_quote'] - event['effective_stop'])
                distances.append(distance)
                ratios.append(distance / width)
        ordered = sorted(ratios)
        median = ((ordered[(len(ordered)-1)//2] + ordered[len(ordered)//2]) / 2.) if ordered else None
        excess = diagnostics[symbol]['risk_budget']['excess_parents']
        assert excess <= len(losing)
        output[symbol] = dict(condition=ident, losing_parents=len(losing),
            losing_parents_with_profitable_initial=len(initial_winners),
            initial_profit_in_losing_parents=sum(fact['cohorts'][0]['net'] for fact in initial_winners),
            budget_excess_losing_parents=excess, within_budget_losing_parents=len(losing)-excess,
            measured_add_fills=len(ratios), unavailable_add_fills=unavailable,
            median_stop_distance_initial_widths=median,
            below_one_initial_width_add_fills=sum(value < 1.-1e-8 for value in ratios),
            already_at_stop_add_fills=sum(value <= 1e-8 for value in distances))
    return output


# ----------------------------------------


def main() -> None:
    """
    機能: 全31の独立会計合格後に主・対照の差と残る損失を保存する。
    引数: --root-all31-independent-complete(bool)は根の明示許可。
    返り値: None。説明補足JSONだけを書き、条件と正式結果を変更しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--root-all31-independent-complete', action='store_true')
    args = parser.parse_args()
    assert args.root_all31_independent_complete
    target = HERE / '説明補足.json'
    assert not target.exists()
    account_path = HERE / '比較結果.json'
    audit_path = WORK / 'audit/全20全31の増玉注文と親cohort及び全原板会計の独立検算.json'
    account, audit = read(account_path), read(audit_path)
    assert account['全合格'] and audit['合格'] and not audit['人工専用']
    assert audit['検査件数']['口座'] == 1240
    assert audit['SHA256'][str(account_path.relative_to(ROOT))] == digest(account_path)
    ids = list(dict.fromkeys((account['primary'], account['selected'], 'G0_Q1_X1',
                             'G0_QFULL_X1', 'G2_Q1_X1', 'G1_Q1_X3')))
    diagnostics, parent_facts, event_facts, binding = {}, {}, {}, {}
    for ident in ids:
        diagnostics[ident] = {symbol: empty_diagnostic() for symbol in SYMBOLS}
        parent_facts[ident] = []
        event_facts[ident] = []
        for part in ('front', 'back'):
            path = WORK / part / 'ledgers' / (ident + '.pkl')
            result = read(WORK / part / 'results' / (ident + '.json'))
            expected = result['ledger_SHA256']
            assert digest(path) == expected == audit['SHA256'][str(path.relative_to(ROOT))]
            binding[str(path.relative_to(ROOT))] = expected
            with path.open('rb') as stream:
                ledgers = pickle.load(stream)
            parent_facts[ident].extend(collect(ledgers, diagnostics[ident], event_facts[ident]))
            del ledgers
            gc.collect()
        for symbol in SYMBOLS:
            total = account['results'][ident]['periods']['全31'][symbol]
            assert diagnostics[ident][symbol]['completed_parents'] == total['campaigns']
            assert diagnostics[ident][symbol]['completed_cohorts'] == total['cohorts']['cohorts']
    comparisons = {}
    for ident in ids:
        comparisons[ident] = {}
        for reference in account['comparison_pairs'][ident]:
            comparisons[ident][reference] = {}
            for symbol in SYMBOLS:
                value = account['results'][ident]
                old = account['results'][reference]
                total, prior = value['periods']['全31'][symbol], old['periods']['全31'][symbol]
                stable, old_stable = value['stability']['全31'][symbol], old['stability']['全31'][symbol]
                comparisons[ident][reference][symbol] = dict(
                    net_delta=total['net']-prior['net'],
                    cohort_profit_delta=total['cohorts']['profit']-prior['cohorts']['profit'],
                    cohort_loss_delta=total['cohorts']['loss']-prior['cohorts']['loss'],
                    fees_delta=total['fees']-prior['fees'],
                    red_sessions_delta=total['losing_sessions']-prior['losing_sessions'],
                    black_sessions_delta=total['positive_sessions']-prior['positive_sessions'],
                    active_sessions_delta=total['active_sessions']-prior['active_sessions'],
                    maximum_red_delta=stable['worst_session_loss_yen']-old_stable['worst_session_loss_yen'])
    worst = {}
    for ident in (account['primary'], account['selected']):
        worst[ident] = {}
        for symbol in SYMBOLS:
            rows = [row for row in account['results'][ident]['rows'] if row['symbol'] == symbol and row['net'] < -1e-5]
            rows = sorted(rows, key=lambda row: (row['net'], row['session']))[:3]
            worst[ident][symbol] = [dict(session=row['session'], net=row['net'],
                parents=[fact for fact in parent_facts[ident] if fact['symbol'] == symbol and fact['session'] == row['session']])
                for row in rows]
    main_id, reference_id = account['primary'], account['selected']
    main_values = account['results'][main_id]['periods']['全31']
    reference_values = account['results'][reference_id]['periods']['全31']
    small_values = account['results']['G0_Q1_X1']['periods']['全31']
    stable_candidates = account['活動充足の両80']
    main_better = all(main_values[symbol]['net'] > small_values[symbol]['net']
                      and main_values[symbol]['losing_sessions'] < small_values[symbol]['losing_sessions']
                      for symbol in SYMBOLS)
    conclusion = [
        ('両商品の金額利益80%と活動基準を満たす条件はありません。今回の増玉案を、毎セッション安定して稼ぐ解としては採用しません。'
         if not stable_candidates else
         f'両商品の金額利益80%と活動基準を満たすのは{len(stable_candidates)}条件。赤字場と最大赤字も下表で確認します。'),
        f'事前主 {main_id} の黒字場は、TOPIX {main_values["TOPIX"]["positive_sessions"]}/{main_values["TOPIX"]["active_sessions"]}、'
        f'日経 {main_values["NK225"]["positive_sessions"]}/{main_values["NK225"]["active_sessions"]}。'
        + ('同じ初回枚数の増玉なしより、両商品の収支と赤字場数が改善しました。' if main_better else
           '同じ初回枚数の増玉なしに対して、両商品の収支と赤字場数を同時には改善できませんでした。'),
        f'前16の参考 {reference_id} は全31でTOPIX {reference_values["TOPIX"]["net"]:+,.0f}円、'
        f'日経 {reference_values["NK225"]["net"]:+,.0f}円。少枚数による損失額の縮小と、黒字確度の改善を区別します。'
    ]
    causal = {ident: causal_summary(ident, diagnostics[ident], parent_facts[ident], event_facts[ident]) for ident in ids}
    notes = dict(account['cause_notes'])
    notes['追加玉の実損益'] = '・'.join(
        f'{symbol}の主の追加玉は利益{diagnostics[main_id][symbol]["actual_add_profit"]:,.0f}円、'
        f'損失{diagnostics[main_id][symbol]["actual_add_loss"]:,.0f}円' for symbol in SYMBOLS) + '。初回玉の利益と相殺する前の手数料後金額です。'
    notes['初回益を追加で返した事実'] = '・'.join(
        f'{symbol}の赤字{causal[main_id][symbol]["losing_parents"]}親中、初回玉自体は実返済時に黒字だったのが'
        f'{causal[main_id][symbol]["losing_parents_with_profitable_initial"]}親' for symbol in SYMBOLS) + '。増玉無しなら同じ出口になったとは仮定しません。'
    notes['予算内でも累積する負け'] = '・'.join(
        f'{symbol}の主の赤字親でR0を超えたのは{causal[main_id][symbol]["budget_excess_losing_parents"]}親、'
        f'予算内の赤字は{causal[main_id][symbol]["within_budget_losing_parents"]}親' for symbol in SYMBOLS) + '。成行超過をなくすだけでは反復負けの解決になりません。'
    example = next(fact for fact in parent_facts[main_id] if fact['session'] == '2026-09-30_Night'
                   and fact['symbol'] == 'TOPIX' and int(fact['parent']['first_fill_row']) == 73340)
    counterpart = next(fact for fact in parent_facts['G0_Q1_X1'] if fact['session'] == example['session']
                       and fact['symbol'] == example['symbol']
                       and fact['parent']['first_fill_row'] == example['parent']['first_fill_row']
                       and fact['parent']['side'] == example['parent']['side'])
    assert example['parent']['first_fill_price'] == counterpart['parent']['first_fill_price']
    stamps = [datetime.fromtimestamp(fact['parent']['exit_time'], timezone(timedelta(hours=9))).strftime('%H:%M:%S')
              for fact in (example, counterpart)]
    notes['同じ入口の具体例'] = (
        f'9/30ナイトTOPIXは、同じ原行73340の4128売りから、増玉ありは{stamps[0]}に4枚4126.5返済、'
        f'{example["parent"]["net"]:+,.0f}円。1枚固定は{stamps[1]}に4114返済、'
        f'{counterpart["parent"]["net"]:+,.0f}円でした。増玉ありの初回玉は黒字でも追加玉が損失を生み、'
        '停止線の短縮で下落の継続を手放した実経路です。時刻は保存価格時計の日本時間換算です。')
    new_session = next(row for row in account['results'][main_id]['rows']
                       if row['session'] == example['session'] and row['symbol'] == 'TOPIX')
    old_session = next(row for row in account['results']['G0_Q1_X1']['rows']
                       if row['session'] == example['session'] and row['symbol'] == 'TOPIX')
    notes['同日の費用と再参加'] = (
        f'同日のTOPIX全体では、1枚固定{old_session["net"]:+,.0f}円に対し増玉{new_session["net"]:+,.0f}円。'
        f'悪化額{old_session["net"]-new_session["net"]:,.0f}円のうち追加手数料は'
        f'{new_session["fees"]-old_session["fees"]:,.0f}円で、費用だけが原因ではありません。'
        '早い返済が後続の新規判断も変えたため、後続の負けだけを都合よく除く改善はできません。')
    binding.update({str(path.relative_to(ROOT)): digest(path) for path in (account_path, audit_path, Path(__file__))})
    output = dict(全合格=True, 正式全範囲独立検算完了=True,
                  独立原因検査完了=False, 根集計SHA256=digest(account_path), 根拠SHA256=binding,
                  売買及び会計の変更=0, report_diagnostics=diagnostics,
                  comparisons=comparisons, worst_sessions=worst,
                  growth_event_facts=event_facts,
                  causal_summary=causal,
                  conclusion=conclusion, cause_notes=notes,
                  注記='独立会計へ照合した保存事実の派生。原因の独立解釈は別資料で確認する。',
                  全31既知=True, 新未見確認場数=0, API取得=0, 実注文=0)
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('親内損失・増玉の実損益・予算超過と主対照の差を保存しました。', flush=True)


if __name__ == '__main__':
    main()
