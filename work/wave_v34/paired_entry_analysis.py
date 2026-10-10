"""仮想準備制御の全新規を旧固定方式へ結び、退出差と見送り差を分解する。"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import scheduler_runner as runner

HERE = Path(__file__).resolve().parent


def entries(ledger: dict) -> dict:
    """機能: 新規準備行をキーに注文・取引組を対応づける。

    引数: ledger (dict)。返り値: 準備行別の新規と完結組 (dict)。
    """
    cycles = {int(r[0]): r for r in ledger['cycles']}
    orders = {int(r[2]): r for r in ledger['orders'] if r[7] == 1}
    prepared = {int(r[0]): r for r in ledger['prepare_events']}
    output = {}
    for campaign, fill_row, prep_id, prep_row in ledger['entry_preparations']:
        order, cycle, prep = orders[int(campaign)], cycles[int(campaign)], prepared[int(prep_id)]
        assert order[0] == fill_row and prep[1] == prep_row and int(prep_row) not in output
        output[int(prep_row)] = {'order': order, 'cycle': cycle, 'prepare': prep}
    return output


def decompose(left: dict, right: dict) -> dict:
    """機能: 共通新規の返済差と旧側だけの新規収支を分ける。

    引数: left/right (dict) は固定通常と更新制御の同一入力。返り値: 会計分解 (dict)。
    対応組の条件付き比較であり、将来の回復益や未実行手法の期待利益ではない。
    """
    old, new = entries(left), entries(right)
    assert set(new) <= set(old)
    factor = left['config']['point_value']
    details = []
    for row, actual in new.items():
        baseline = old[row]
        assert actual['prepare'][1:] == baseline['prepare'][1:]
        indices = [0, 1, 3, 4, 5, 6, 7]
        assert [actual['order'][i] for i in indices] == [baseline['order'][i] for i in indices]
        x, y = baseline['cycle'], actual['cycle']
        assert x[4:6] == y[4:6]
        details.append({'prepare_row': row, 'entry_row': int(y[1]), 'direction': int(y[8]),
            'old_exit_row': int(x[2]), 'new_exit_row': int(y[2]),
            'old_yen': x[3] * factor, 'new_yen': y[3] * factor,
            'exit_difference_yen': (y[3] - x[3]) * factor,
            'exit_order': '早い' if y[2] < x[2] else '遅い' if y[2] > x[2] else '同じ'})
    omitted = [{'prepare_row': row, 'entry_row': int(old[row]['cycle'][1]),
                'net_yen': old[row]['cycle'][3] * factor} for row in sorted(set(old) - set(new))]
    exit_difference = sum(r['exit_difference_yen'] for r in details)
    omitted_net = sum(r['net_yen'] for r in omitted)
    old_net = sum(r['cycle'][3] * factor for r in old.values())
    new_net = sum(r['cycle'][3] * factor for r in new.values())
    np.testing.assert_allclose(new_net - old_net, exit_difference - omitted_net, atol=1e-7, rtol=0)
    return {'session': left['session'], 'symbol': left['symbol'],
            '旧新規数': len(old), '制御新規数': len(new), '共通新規数': len(details),
            '見送り旧新規数': len(omitted), '旧収支': old_net, '制御収支': new_net,
            '共通新規の返済差': exit_difference, '見送り旧新規の収支': omitted_net,
            '収支差': new_net - old_net, '共通詳細': details, '見送り詳細': omitted}


def entry_path_difference(left: dict, right: dict) -> dict:
    """機能: 更新通常と更新制御の同じ新規を照合し、参加集合の違いを分解する。

    引数: left/right (dict) は同一入力の更新通常・更新制御。返り値: 新規集合の会計差 (dict)。
    同じ新規の退出は一致を要求。制御で消えた取引だけを都合よく除外しない。
    """
    groups = []
    for ledger in (left, right):
        group = {}
        for entry in entries(ledger).values():
            order, cycle = entry['order'], entry['cycle']
            key = tuple(order[k] for k in (0, 3, 4, 5)) + (cycle[5],)
            assert key not in group
            group[key] = cycle
        groups.append(group)
    old, new = groups
    common = set(old) & set(new)
    for key in common:
        assert old[key][1:] == new[key][1:], '同一新規なのに制御が退出を変更'
        campaign_old, campaign_new = int(old[key][0]), int(new[key][0])
        # campaignと内部玉IDを除き、部分返済を含む全ての約定を照合する。
        old_trades = [r[2:] for r in left['trades'] if int(r[0]) == campaign_old]
        new_trades = [r[2:] for r in right['trades'] if int(r[0]) == campaign_new]
        assert old_trades == new_trades, '共通新規の部分返済又は全返済が異なる'
        old_orders = [r[:2] + r[3:] for r in left['orders'] if int(r[2]) == campaign_old and r[7] == 0]
        new_orders = [r[:2] + r[3:] for r in right['orders'] if int(r[2]) == campaign_new and r[7] == 0]
        assert old_orders == new_orders, '共通新規の返済元行又は返済注文が異なる'
    factor = left['config']['point_value']
    old_only, new_only = set(old) - common, set(new) - common
    old_net = sum(old[key][3] * factor for key in old_only)
    new_net = sum(new[key][3] * factor for key in new_only)
    return {'session': left['session'], 'symbol': left['symbol'], '共通数': len(common),
            '共通収支': sum(old[key][3] * factor for key in common),
            '通常だけ数': len(old_only), '通常だけ収支': old_net,
            '制御だけ数': len(new_only), '制御だけ収支': new_net,
            '制御による収支差': new_net - old_net, '共通退出同値': True}


def main() -> None:
    """機能: 全12入口の主条件について全26入力の分解を保存する。

    引数: なし。返り値: なし (None)。探索や採否の基準は変更しない。
    """
    output, references, paths_analysis = {}, {}, {}
    for signal in runner.design.SIGNAL_IDS:
        paths = [HERE / 'ledgers' / (signal + '__' + mode + '.json.gz')
                 for mode in ('A0__NORMAL__V000', 'AT__SHADOW__V000')]
        references.update({p.relative_to(runner.ROOT).as_posix(): runner.digest(p) for p in paths})
        ledgers = [{(r['session'], r['symbol']): r for r in runner.read(p)} for p in paths]
        rows = [decompose(ledgers[0][key], ledgers[1][key]) for key in ledgers[0]]
        totals = {}
        for symbol in runner.SYMBOLS:
            part = [r for r in rows if r['symbol'] == symbol]
            totals[symbol] = {field: sum(r[field] for r in part) for field in
                ('旧新規数', '制御新規数', '共通新規数', '見送り旧新規数', '旧収支', '制御収支',
                 '共通新規の返済差', '見送り旧新規の収支', '収支差')}
            totals[symbol]['返済順'] = {name: sum(d['exit_order'] == name for r in part for d in r['共通詳細'])
                                       for name in ('早い', '遅い', '同じ')}
        output[signal] = {'銘柄合計': totals, 'セッション': rows}
        normal_path = HERE / 'ledgers' / (signal + '__AT__NORMAL__V000.json.gz')
        references[normal_path.relative_to(runner.ROOT).as_posix()] = runner.digest(normal_path)
        normal = {(r['session'], r['symbol']): r for r in runner.read(normal_path)}
        part = [entry_path_difference(normal[key], ledgers[1][key]) for key in normal]
        path_totals = {symbol: {field: sum(r[field] for r in part if r['symbol'] == symbol)
            for field in ('共通数', '共通収支', '通常だけ数', '通常だけ収支', '制御だけ数', '制御だけ収支', '制御による収支差')}
            for symbol in runner.SYMBOLS}
        paths_analysis[signal] = {'銘柄合計': path_totals, 'セッション': part}
    runner.save(HERE / '共通新規の返済分解.json', {'全比較数': 312, '全件会計一致': True,
        '全入口': output, '更新方式の参加経路差': paths_analysis,
        '台帳SHA256': references, '実装SHA256': runner.digest(Path(__file__)),
        '解釈': '結果後の会計分解。共通組は条件付き集合であり独立な因果推定ではない。新条件や採否変更に使用しない。'})
    (HERE / '共通新規の返済分解.md').write_text('# 退出と見送りの会計分解\n\n更新制御の新規が固定通常の新規の部分集合であることを、準備行・方向・価格・A0・期限・枚数・約定で照合した。全12入口×26入力で「収支差＝共通新規の返済差−見送った旧新規の収支」を確認。これは結果後の条件付き会計分解であり、見送り玉を都合よく復活できることを意味しない。\n\n全件の数値と対応行は [共通新規の返済分解.json](共通新規の返済分解.json) に保存。\n', encoding='utf-8')
    print('全12×26の返済差・見送り差を分解。')


if __name__ == '__main__':
    main()
