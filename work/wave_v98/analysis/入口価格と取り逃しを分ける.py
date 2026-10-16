"""同じ元候補で実建値の差と消えた勝負を分け、入口改善を過大評価しない。"""

from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
sys.path.insert(0, str(WORK))
import research
import catalog


def parents(ident: str) -> dict:
    """
    機能: 完結した親だけを元候補行と方向へ対応付ける。
    引数: ident(str)は固定した手法ID。
    返り値: dict。口座ごとの候補を起点とする親会計と実新規診断。
    """
    answer = {}
    for part in ('front', 'back'):
        path = WORK / part / 'ledgers' / (ident + '.pkl')
        ledgers = research.read(path)
        for key, stored in ledgers.items():
            columns = stored['entry_parent_columns']
            rows = {int(row[columns.index('parent_id')]): row
                    for row in stored['entry_parent_diagnostics']}
            values = {}
            for trade in stored['trades']:
                assert int(trade[1]) == 0
                row = rows[int(trade[0])]
                assert int(row[columns.index('market_outcome')]) == 1
                assert row[columns.index('net')] == trade[11]
                candidate = (int(row[columns.index('candidate_row')]), int(trade[4]))
                assert candidate not in values
                values[candidate] = dict(
                    trade=trade,
                    wait_seconds=float(row[columns.index('trigger_time')]
                                       - row[columns.index('candidate_time')]),
                    candidate_quote=float(row[columns.index('candidate_quote')]),
                    trigger_quote=float(row[columns.index('trigger_quote')]),
                    phase_row=int(row[columns.index('phase_row')]))
            answer[key] = values
    return answer


def compare(old: dict, new: dict, symbol: str) -> dict:
    """
    機能: 同候補の建値変化・返済変化と、片側だけの実親を分離する。
    引数: old/new(dict)は口座集合、symbol(str)は同じ比較商品。
    返り値: dict。価格改善は方向付き円額、利益損失は完結親の費用後金額。
    """
    value = 1000. if symbol == 'TOPIX' else 10.
    entries, exits, fees, waits, common_nets, lost_old, extra_new = [], [], [], [], [], [], []
    transitions, examples = {}, []
    for key in sorted(old):
        if key[1] != symbol:
            continue
        a, b = old[key], new[key]
        for candidate in sorted(set(a) & set(b)):
            ta, tb = a[candidate]['trade'], b[candidate]['trade']
            assert ta[4] == tb[4] and ta[5] == tb[5]
            quantity, side = int(tb[5]), int(tb[4])
            entry = side * (ta[6] - tb[6]) * quantity * value
            exit_change = side * (tb[7] - ta[7]) * quantity * value
            fee_change = float(ta[8] + ta[9] - tb[8] - tb[9])
            delta = tb[11] - ta[11]
            assert abs(entry + exit_change + fee_change - delta) < 1e-5
            entries.append(float(entry)); exits.append(float(exit_change)); fees.append(fee_change)
            waits.append(b[candidate]['wait_seconds']); common_nets.append(float(delta))
            names = [('利益' if trade[11] > 1e-5 else '損失' if trade[11] < -1e-5 else '同額')
                     for trade in (ta, tb)]
            label = '→'.join(names)
            transitions.setdefault(label, dict(親=0, 収支差=0.))
            transitions[label]['親'] += 1
            transitions[label]['収支差'] += float(delta)
            examples.append(dict(session=key[0], candidate_row=candidate[0], side=side,
                old_entry_row=int(ta[2]), new_entry_row=int(tb[2]),
                old_exit_row=int(ta[3]), new_exit_row=int(tb[3]),
                old_entry_price=float(ta[6]), new_entry_price=float(tb[6]),
                old_net=float(ta[11]), new_net=float(tb[11]),
                entry_price_change_yen=float(entry), exit_change_yen=float(exit_change),
                fee_change_yen=fee_change,
                net_change_yen=float(delta), wait_seconds=b[candidate]['wait_seconds']))
        lost_old += [float(a[c]['trade'][11]) for c in set(a) - set(b)]
        extra_new += [float(b[c]['trade'][11]) for c in set(b) - set(a)]
    old_net = sum(float(p['trade'][11]) for k, v in old.items() if k[1] == symbol for p in v.values())
    new_net = sum(float(p['trade'][11]) for k, v in new.items() if k[1] == symbol for p in v.values())
    delta = sum(common_nets) - sum(lost_old) + sum(extra_new)
    assert abs(new_net - old_net - delta) < 1e-5
    return dict(
        old_net=old_net, new_net=new_net, net_change=delta, 同候補親=len(entries),
        有利建値親=sum(e > 1e-5 for e in entries), 不利建値親=sum(e < -1e-5 for e in entries),
        同値親=sum(abs(e) <= 1e-5 for e in entries), 建値改善円=sum(entries),
        返済差円=sum(exits), 費用差円=sum(fees), 同候補収支差=sum(common_nets),
        平均待機秒=float(np.mean(waits)) if waits else None,
        旧固有勝ち親=sum(v > 1e-5 for v in lost_old), 旧固有勝ち円=sum(v for v in lost_old if v > 1e-5),
        旧固有負け親=sum(v < -1e-5 for v in lost_old), 旧固有負け円=-sum(v for v in lost_old if v < -1e-5),
        新固有親=len(extra_new), 新固有収支=sum(extra_new), 同候補符号変化=transitions,
        改善上位例=sorted(examples, key=lambda r: -r['net_change_yen'])[:3],
        悪化上位例=sorted(examples, key=lambda r: r['net_change_yen'])[:3],
        定義='旧固有は新側未成立又は後続保有等による不参加。候補後MFEを新規選択へ使用しない。建値差と返済差は実経路の恒等式で、別々に固定した反実売買の結果ではない。')


def main() -> None:
    """
    機能: 全34条件を同じ出口の即時入口及び政策一軸の対照と比べる。
    引数: なし。
    返り値: None。保存正式台帳を読み、会計を変えず原因資料だけを保存する。
    """
    fixed = research.read(WORK / '事前固定.json')
    research.validate(fixed)
    result = research.read(HERE / '比較結果.json')
    cache = {}
    def saved(ident: str) -> dict:
        """
        機能: 同じ比較元の親台帳を繰り返し読み込まない。
        引数: ident(str)は正式手法ID。
        返り値: dict。対応する元候補の実親。
        """
        if ident not in cache:
            cache[ident] = parents(ident)
        return cache[ident]
    answers, policy_answers, paths = {}, {}, [Path(__file__), HERE / '比較結果.json']
    for config in fixed['条件']:
        ident = config['id']; exit_name = config['previous_id'].split('_')[-1]
        new = saved(ident)
        answers[ident] = {symbol: compare(saved('A0_'+exit_name), new, symbol) for symbol in catalog.SYMBOLS}
        if config['entry_wait_kind'] and config['entry_clock_policy'] != 'C0':
            policy, entry, exit_part = ident.split('_')
            previous_policy = 'C0' if policy == 'C1' else 'C1'
            previous_id = f'{previous_policy}_{entry}_{exit_part}'
            policy_answers[ident] = dict(対照=previous_id,
                商品別={symbol: compare(saved(previous_id), new, symbol) for symbol in catalog.SYMBOLS})
        for symbol in catalog.SYMBOLS:
            assert answers[ident][symbol]['new_net'] == result['results'][ident]['periods']['全31'][symbol]['net']
        paths += [WORK / part / 'ledgers' / (ident + '.pkl') for part in ('front', 'back')]
    research.save(HERE / '時計政策の実建値差と消えた勝負及び新固有親.json', dict(
        全合格=True, 条件数=34, comparison=answers, policy_comparison=policy_answers,
        再売買実行=0, API取得=0, 実注文=0, 全31既知=True,
        SHA256={str(p.relative_to(research.ROOT)): research.data.digest(p) for p in set(paths)}))
    print('全34の同候補建値・返済・費用差、政策一軸と即時対照の固有親が全正式収支差へ一致。', flush=True)


if __name__ == '__main__':
    main()
