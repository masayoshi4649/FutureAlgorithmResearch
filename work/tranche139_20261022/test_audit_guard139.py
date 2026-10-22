"""独立監査が部分返済、費用負け、通常保有、累積負け数を区別する人工確認。"""

import copy
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from audit_guard139 import HERE, digest, ledger, selection


def fixture():
    """
    機能: 負け・勝ち・費用だけの負けの順に全返済する人工口座を作る。
    引数: なし。
    返り値: tupleは基準注文、候補、採用注文、見送り、時計、設定、独立会計。
    """
    t0 = datetime(2026, 10, 22, 8, 45, tzinfo=ZoneInfo('Asia/Tokyo')).timestamp()
    times = t0 + np.arange(50, dtype=float)
    bid = np.full(50, 99.5)
    ask = np.full(50, 100.5)
    for row, value in ((5, 101.5), (10, 98.5), (15, 101.5), (20, 100.6), (25, 99.5)):
        bid[row], ask[row] = value, value + 1
    quotes = dict(bid=bid, ask=ask, quote_valid=np.ones(50, dtype=bool))
    ready = dict(time_s=times, quotes=quotes, window_start=t0, window_end=t0 + 45)
    rows = []
    for pid, fill, decision, side, qty, new, uid in (
        (20001, 2, 1, 1, 2, 1, 0), (20001, 5, 4, -1, 1, 0, 0),
        (20001, 10, 9, -1, 1, 0, 0), (20003, 12, 11, 1, 1, 1, 0),
        (20003, 15, 14, -1, 1, 0, 0), (20004, 17, 16, 1, 2, 1, 0),
        (20004, 20, 19, -1, 2, 0, 0), (100, 23, 22, 1, 1, 1, 0),
        (100, 25, 24, -1, 1, 0, 0)):
        price = ask[fill] if side == 1 else bid[fill]
        rows.append([fill, decision, pid, side, qty, price, 13910 if new else 1392, new, uid, qty * 385 // 10])
    orders = np.asarray(rows, dtype=float)
    base = orders[orders[:, 2] == 100]
    candidates = []
    for pid, decision in ((1, 1), (2, 6), (3, 11), (4, 16), (5, 21), (6, 24), (7, 26)):
        fill = decision + 1
        candidates.append([fill, decision, pid, 1, 5, ask[fill], 13910, 1, 0, times[fill], times[decision], 1])
    skips = []
    for pid, decision, end, losses, reason in (
        (20002, 6, 10, 0, '保有中'), (20005, 21, 20, 2, '早期損失回数の上限'),
        (20006, 24, 25, 2, '保有中'), (20007, 26, 25, 2, '早期損失回数の上限')):
        skips.append(dict(parent=pid, decision=decision, kind='早期', active_until=end,
                          early_losses=losses, reason=reason, gap_start=None, gap_end=None))
    policy = dict(max_early_losses=2, event_gap=False)
    independent = ledger(orders, times, bid, ask, quotes['quote_valid'], 385, 100)
    return base, np.asarray(candidates), orders, skips, ready, policy, independent


def main():
    """
    機能: 人工の正解台帳と故意の誤記録を使い、独立監査の検出を確認する。
    引数: なし。
    返り値: None。金融再生せず確認結果をJSON保存する。
    """
    args = fixture()
    result = selection(*args)
    passed = []
    assert result['completed_early_losses'] == 2 and result['fee_only_losses'] == 1
    passed.append('勝ちを挟んでも費用後の累積二敗を維持')
    assert result['counters']['partial_close_not_counted'] == 1
    passed.append('部分返済済みでも未全返済の負け数を加算しない')
    assert result['counters']['accepted_regular'] == 1
    passed.append('二敗停止後も通常担当の親を採用')
    large = copy.deepcopy(args)
    large[0][large[0][:, 2] == 100, 2] = 1010000
    large[2][large[2][:, 2] == 100, 2] = 1010000
    large[6]['parents'][1010000] = large[6]['parents'].pop(100)
    check = selection(*large)
    assert check['counters']['accepted_regular'] == 1 and check['completed_early_losses'] == 2
    passed.append('大きな補完親IDを早期親へ誤分類しない')
    bad = copy.deepcopy(args)
    bad[3][0]['early_losses'] = 1
    try:
        selection(*bad)
    except AssertionError:
        passed.append('将来負け数の混入を検出')
    else:
        raise AssertionError('未来損失を検出できない')
    bad = copy.deepcopy(args)
    bad[3][1]['early_losses'] = 1
    try:
        selection(*bad)
    except AssertionError:
        passed.append('費用負け又は累積負けの数え漏れを検出')
    else:
        raise AssertionError('費用負けを検出できない')
    bad = copy.deepcopy(args)
    bad[3][2]['reason'] = '早期損失回数の上限'
    try:
        selection(*bad)
    except AssertionError:
        passed.append('通常保有中を先に判定する優先順位を確認')
    else:
        raise AssertionError('保有中の優先順位を検出できない')
    bad = copy.deepcopy(args)
    bad[3].pop()
    try:
        selection(*bad)
    except AssertionError:
        passed.append('候補が説明なく欠落する場合を検出')
    else:
        raise AssertionError('候補欠落を検出できない')
    outcome = dict(status='合格', checks=passed, financial_replays=0, API=0,
                   audit_sha256=digest(HERE / 'audit_guard139.py'), test_sha256=digest(Path(__file__)))
    with (HERE / 'audit_guard_人工確認.json').open('w', encoding='utf-8') as handle:
        json.dump(outcome, handle, ensure_ascii=False, indent=2)
    print(json.dumps(outcome, ensure_ascii=False))


if __name__ == '__main__':
    main()
