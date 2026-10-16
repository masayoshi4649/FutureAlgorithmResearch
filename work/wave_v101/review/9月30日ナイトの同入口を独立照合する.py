"""許可済み正式台帳の同初回約定を少数だけ照合し、増玉で変わった実経路を示す。"""

import argparse
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]


def module(path: Path, name: str) -> object:
    """
    機能: 独立会計と時刻表示のコードをmainなしで接続する。
    引数: path (Path)、name (str) は対象と一意名。
    返り値: object はモジュール。根の説明関数及び売買を呼ばない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def main() -> None:
    """
    機能: 9月30日TOPIXナイトの実在する二策略の同初回約定を独立照合する。
    引数: --root-all31-explanation-complete (bool) は根の明示完了後だけ指定する。
    返り値: None。原因例JSON。未来を見て選んだ仮約定又は新策略収支へ置換しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--root-all31-explanation-complete', action='store_true')
    args = parser.parse_args()
    assert args.root_all31_explanation_complete
    selection = module(HERE / 'selection.py', '101同入口の独立会計')
    growth = module(HERE / 'growth_cause_check.py', '101同入口の時刻表示')
    cause_path = HERE / '根説明補足の親内損失と増玉及び予算超過と最悪場の独立反証.json'
    growth_path = HERE / '赤字親の初回利益と追加後停止距離及び予算内反復負けの独立原因.json'
    proof = selection.read(cause_path)
    assert proof['全合格'] and selection.read(growth_path)['全合格']
    key = ('2026-09-30_Night', 'TOPIX')
    answers, binding = {}, {}
    for ident in ('G1_Q1_X1', 'G0_Q1_X1'):
        path = WORK / 'front/ledgers' / (ident + '.pkl')
        binding[str(path.relative_to(ROOT))] = proof['SHA256'][str(path.relative_to(ROOT))]
        ledger = selection.read(path)[key]
        groups = growth.dictionaries(ledger['growth_cohorts'], ledger['growth_cohort_columns'])
        matches = [group for group in groups if group['entry_kind'] == 0
                   and group['entry_row'] == 73340 and group['entry_price'] == 4128 and group['side'] == -1]
        assert len(matches) == 1
        initial = matches[0]
        ident_parent = initial['parent_id']
        selected = ledger['growth_cohorts'][ledger['growth_cohorts'][:, 0] == ident_parent]
        orders = ledger['orders'][ledger['orders'][:, 2] == ident_parent]
        trades = ledger['trades'][ledger['trades'][:, 0] == ident_parent]
        account = selection.account(dict(orders=orders, trades=trades, growth_cohorts=selected,
                                        growth_cohort_columns=ledger['growth_cohort_columns']), 'TOPIX')
        parents = growth.dictionaries(ledger['growth_parent_diagnostics'], ledger['growth_parent_columns'])
        parent = next(value for value in parents if value['parent_id'] == ident_parent)
        events = growth.dictionaries(ledger['growth_events'], ledger['growth_event_columns'], clean=True)
        additions = [event for event in events if event['parent_id'] == ident_parent and event['code'] == 3]
        answers[ident] = dict(parent=parent,
            first=dict(row=int(initial['entry_row']), seq=int(initial['entry_seq']), clock=growth.clock(initial['entry_time']),
                       price=initial['entry_price'], side=int(initial['side']), quantity=int(initial['quantity'])),
            cohorts=[dict(quantity=int(group['quantity']), entry_price=group['entry_price'],
                          entry_row=int(group['entry_row']), entry_seq=int(group['entry_seq']),
                          clock=growth.clock(group['entry_time']), net=group['net'])
                     for group in growth.dictionaries(selected, ledger['growth_cohort_columns'])],
            exit=dict(row=int(parent['exit_row']), seq=int(parent['exit_seq']), clock=growth.clock(parent['exit_time']),
                      price=parent['exit_price'], quantity=int(parent['final_quantity'])),
            net=account['net'], realized_excess=parent['realized_budget_excess'],
            additions=[dict(row=int(event['row']), quantity=int(event['quantity']),
                            liquidation_quote=event['liquidation_quote'], stop=event['effective_stop'],
                            distance=parent['side'] * (event['liquidation_quote'] - event['effective_stop']))
                       for event in additions])
        del ledger
    assert answers['G1_Q1_X1']['first'] == answers['G0_Q1_X1']['first']
    assert answers['G1_Q1_X1']['net'] == -2832 and answers['G0_Q1_X1']['net'] == 13918
    assert [group['net'] for group in answers['G1_Q1_X1']['cohorts']] == [1417, -1083, -3166]
    assert answers['G1_Q1_X1']['realized_excess'] == 0
    assert answers['G1_Q1_X1']['additions'][-1]['distance'] == .5
    for path in (Path(__file__), cause_path, growth_path):
        binding[str(path.relative_to(ROOT))] = selection.digest(path)
    result = dict(全合格=True, session=key[0], symbol=key[1], 同一初回約定=True, 実在する二策略の結果=answers,
                  解釈='増玉後の全量停止線が少しの反対変動で返済を決め、初回利益を追加玉損失が超えた実例。同初回のG0は実際に別出口へ進んだ対照で、後から仮約定した反実仮想ではない。',
                  限定='この一例から全損失の原因又は次候補の勝ちを保証しない。表示時計は現在値由来の代理時計で、同clockの別seqは真受信同時刻を証明しない。',
                  検査scope='既監査済みfrontの二台帳から該当一親ずつの注文・建玉群・追加イベントのみ再会計。全参照の二重hashなし。',
                  売買及び固定金融変更=0, API取得=0, 実注文=0, SHA256=binding)
    output = HERE / '9月30日ナイトの同初回約定と異なる実出口の独立対照.json'
    assert not output.exists()
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 初回=result['実在する二策略の結果']['G1_Q1_X1']['first'],
                         主=-2832, 同Q増玉無し=13918, SHA256=selection.digest(output)), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
