"""方向性各ラウンドの全口座を、旧独立会計と全flat組集計で照合する。"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
COMMON = HERE.parent.parent / 'wave_v60'
spec = importlib.util.spec_from_file_location('独立方向性会計', HERE.parent.parent / 'wave_v61/review/check_directional_accounts.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
spec2 = importlib.util.spec_from_file_location('指値独立会計', HERE / 'directional_passive_accounting.py')
passive_helper = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(passive_helper)


def group_statistics(groups: np.ndarray) -> dict:
    """機能: 全flat組から費用後勝率と金額の平均勝負比を計算する。

    引数: groups(ndarray)。返り値: 集計(dict)。同値も分母へ含める。
    """
    positive, negative = groups[groups > 0], groups[groups < 0]
    mean_win = float(positive.mean()) if len(positive) else None
    mean_loss = float(-negative.mean()) if len(negative) else None
    return dict(cycles=len(groups), group_wins=len(positive), group_losses=len(negative),
        group_profit=float(positive.sum()), group_loss=float(-negative.sum()),
        group_win_rate=float(np.mean(groups > 0)) if len(groups) else None,
        group_mean_win=mean_win, group_mean_loss=mean_loss,
        group_pf=float(-positive.sum() / negative.sum()) if len(negative) else None,
        group_payoff=mean_win / mean_loss if mean_win is not None and mean_loss else None)


def check_value(actual: object, expected: object, label: str) -> None:
    """機能: 未定義値と有限値を区別して表示集計を検算する。

    引数: actual/expected(object)、label(str)。返り値: なし(None)。
    """
    if expected is None:
        assert actual is None, label
    else:
        helper.equal(actual, expected, label)


def main() -> None:
    """機能: 固定済みラウンドの全注文・資産曲線・組指標・週集計を検算する。

    引数: --round(str)。返り値: なし(None)。売買を再生せず保存台帳だけを読む。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--round', default='round1')
    args = parser.parse_args()
    source = HERE.parent / 'directional' / args.round
    target = source / '集計結果.json'
    result = json.loads(target.read_text(encoding='utf-8'))
    frozen = json.loads((source / '実行前固定.json').read_text(encoding='utf-8'))
    fixed = frozen.get('固定', frozen)
    for name, expected in fixed.get('コードSHA256', fixed.get('コード', {})).items():
        assert hashlib.sha256((source / 'code' / name).read_bytes()).hexdigest() == expected
    for name, expected in fixed.get('入力SHA256', fixed.get('入力', {})).items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == expected
    inputs = pickle.loads((COMMON / 'inputs.pkl').read_bytes())
    quotes = pickle.loads((COMMON / 'quotes.pkl').read_bytes())
    total = dict(accounts=0, orders=0, trades=0, cycles=0, raw_rows=0, summaries=0)
    for method in result['methods']:
        payload = (source / method['ledger']).read_bytes()
        if 'ledger_sha256' in method:
            assert hashlib.sha256(payload).hexdigest() == method['ledger_sha256']
        ledgers = pickle.loads(payload)
        group_values = {}
        for account in method['accounts']:
            key = (account['session'], account['symbol'])
            ledger = ledgers[tuple(account['ledger_key'])]
            checked = (passive_helper if args.round != 'round1' else helper).audit(account, ledger, inputs[key], quotes[key], method['config'])
            total['accounts'] += 1
            for name, value in checked.items():
                total[name] += value
            trades = ledger['trades']
            groups = np.array([trades[trades[:, 21] == gid, 8].sum() for gid in np.unique(trades[:, 21])])
            for name, value in group_statistics(groups).items():
                if name in account:
                    check_value(account[name], value, name)
            group_values[key] = groups
        for symbol in ('TOPIX', 'NK225'):
            aa = [a for a in method['accounts'] if a['symbol'] == symbol]
            periods = [(method['summary'][symbol], aa)]
            periods += [(value, [a for a in aa if a['week'] == week]) for week, value in method['weeks'][symbol].items()]
            for summary, accounts in periods:
                groups = np.concatenate([group_values[(a['session'], symbol)] for a in accounts])
                for name, value in group_statistics(groups).items():
                    check_value(summary[name], value, name)
                for name in ('net', 'fees', 'profit', 'loss', 'gross_pnl', 'win_qty', 'loss_qty'):
                    helper.equal(summary[name], sum(a[name] for a in accounts), name)
                helper.equal(summary['without_best'], sum(a['net'] for a in accounts) - max(0, max(a['net'] for a in accounts)), '最大黒字場除外')
                total['summaries'] += 1
    assert total['accounts'] == len(result['methods']) * 50
    record = dict(合格=True, ラウンド=args.round, 件数=total, 凍結コードと入力一致=True,
        待機済指値又は次行気配と数量上限と場内返済=True, 全行資産独立照合=True, 費用の整数注文別配賦=True,
        全flat組勝率PF平均勝負比=True, 同値組も勝率分母へ含む=True,
        結果SHA256=hashlib.sha256(target.read_bytes()).hexdigest())
    (HERE / (args.round + '_方向性全台帳の独立監査.json')).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(record, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
