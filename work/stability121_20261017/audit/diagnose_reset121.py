"""九月二十四日の固定枠と再起算の違いを、所有済み実注文玉から抜き出す。"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
OWN = HERE / 'result/owned'
JST = timezone(timedelta(hours=9))


def clock(epoch: float) -> str:
    """
    機能: 保存UNIX秒を同日の日本時刻へ整える。
    引数: epoch(float)は保存約定時刻。
    返り値: strはHH:MM:SS。元時計を補正しない。
    """
    return datetime.fromtimestamp(float(epoch), JST).strftime('%H:%M:%S')


def key(lot: np.ndarray) -> tuple:
    """
    機能: 政策を跨ぐUIDの誤対応を避けて同じ実入口を識別する。
    引数: lot(np.ndarray)は十九列の完結玉。
    返り値: tupleは建方向・新規判断原行・実約定原行・実建値。
    """
    return int(lot[1]), int(lot[3]), int(lot[4]), float(lot[6])


def describe(lot: np.ndarray, orders: np.ndarray) -> dict:
    """
    機能: 一枚玉の実入口・返済と直前の同方向利益返済を抜き出す。
    引数: lot(np.ndarray)は完結玉、orders(np.ndarray)は同一政策の十八列。
    返り値: dictは時刻・rank・値幅・費用・円額。取消内部stateは推測しない。
    """
    entry = orders[(orders[:, 0] == lot[0]) & (orders[:, 1] == 1)]
    assert len(entry) == 1
    e = entry[0]
    closed = orders[(orders[:, 1] == 2) & (orders[:, 2] == -lot[1])
                    & (orders[:, 9] == 1) & (orders[:, 16] > 0) & (orders[:, 4] < lot[3])]
    previous = None
    if len(closed):
        latest = np.max(closed[:, 4])
        group = closed[closed[:, 4] == latest]
        previous = dict(raw=int(latest), time=clock(group[0, 6]),
                        uids=group[:, 0].astype(int).tolist(), net=float(group[:, 16].sum()))
    return dict(uid=int(lot[0]), side=int(lot[1]), rank=int(lot[2]),
        entry_decision_row=int(lot[3]), entry_row=int(lot[4]), entry=clock(lot[5]), entry_price=float(lot[6]),
        trigger_price=float(e[17]), exit_row=int(lot[8]), exit=clock(lot[9]), exit_price=float(lot[10]),
        points=float(lot[1]*(lot[10]-lot[6])), gross=float(lot[11]), fees=float(lot[12]), net=float(lot[13]),
        reason=int(lot[14]), previous_same_side_profit_exit=previous)


def compare(a: np.ndarray, b: np.ndarray) -> tuple[list, list, list]:
    """
    機能: 実入口キーの多重集合で共通玉と各政策だけの玉を分ける。
    引数: a/b(np.ndarray)は固定枠版と再起算版の完結玉。
    返り値: tuple[list,list,list]は共通の玉対・固定だけ・再起算だけ。UID自体を共通親としない。
    """
    first, second = defaultdict(list), defaultdict(list)
    for lot in a:
        first[key(lot)].append(lot)
    for lot in b:
        second[key(lot)].append(lot)
    common, only_first, only_second = [], [], []
    for entry in sorted(first.keys() | second.keys()):
        left, right = first[entry], second[entry]
        shared = min(len(left), len(right))
        common.extend(zip(left[:shared], right[:shared]))
        only_first.extend(left[shared:])
        only_second.extend(right[shared:])
    return common, only_first, only_second


def main() -> None:
    """
    機能: 監査所有九月二十四日NPZの注文と玉だけから悪化の会計差を説明する。
    引数: なし。原市場・元measurement・気配列は読まない。
    返り値: None。全経路変更の説明用JSONを保存する。
    """
    result = json.loads((OWN/'完成結果.json').read_text(encoding='utf-8'))
    reference = next(row for row in result['cache'] if row['session'] == '2026-09-24_Day')
    raw = (OWN/'2026-09-24_Day.npz').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == reference['sha256']
    with np.load(BytesIO(raw), allow_pickle=False) as stored:
        all_orders = stored['orders']
        all_lots = stored['lots']
    methods = ('G3_T5_SLOT', 'G3_T5_RESET')
    inventory = {}
    for method in methods:
        policy = next(i for i, spec in enumerate(result['specs']) if spec['id'] == method)
        inventory[method] = (all_orders[all_orders[:, 0] == policy, 1:], all_lots[all_lots[:, 0] == policy, 1:])
    fixed_o, fixed_l = inventory[methods[0]]
    reset_o, reset_l = inventory[methods[1]]
    common, fixed_only, reset_only = compare(fixed_l, reset_l)
    assert all(a[9] == b[9] and a[10] == b[10] and a[13] == b[13] and a[14] == b[14] for a,b in common)
    fixed_force = fixed_l[(fixed_l[:, 1] == 1) & (fixed_l[:, 14] == 9)]
    reset_force = reset_l[(reset_l[:, 1] == 1) & (reset_l[:, 14] == 9)]
    common_force, fixed_only_force, reset_only_force = compare(fixed_force, reset_force)
    assert (len(fixed_force), len(reset_force), len(common_force), len(fixed_only_force), len(reset_only_force)) == (7,10,4,3,6)
    fixed_sum = float(sum(row[13] for row in fixed_only_force))
    reset_sum = float(sum(row[13] for row in reset_only_force))
    assert (fixed_sum,reset_sum,reset_sum-fixed_sum) == (-69746,-133992,-64246)
    summaries = {}
    for method, (orders, lots) in inventory.items():
        summary = next(row for row in result['runs'] if row['session'] == '2026-09-24_Day' and row['method'] == method)
        assert summary['net'] == float(lots[:, 13].sum())
        summaries[method] = dict(net=summary['net'], long_net=summary['long_net'], short_net=summary['short_net'],
            trail_net=summary['trail_net'], forced_loss=summary['forced_loss'], forced_profit=summary['forced_profit'],
            entries=summary['entries'], max_long=summary['max_long'], max_short=summary['max_short'])
    a, b = (summaries[method] for method in methods)
    delta = {name:b[name]-a[name] for name in a}
    assert delta['net'] == -34976 and delta['forced_loss'] == 64246 and delta['trail_net'] == 29270
    for order in reset_o:
        if order[1] == 2 and order[9] == 1 and order[16] > 0:
            assert not np.any((reset_o[:, 1] == 1) & (reset_o[:, 2] == -order[2]) & (reset_o[:, 3] == order[4]))
    proof = dict(passed=True, source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        result_sha256='ade79de8165fefe68d6f6be861b38f991fc650bb6b658e70329cf667b9bacd1c',
        owned_input_sha256=reference['sha256'], summaries=summaries, reset_minus_fixed=delta,
        all_same_actual_entry_count=len(common), fixed_only_entry_count=len(fixed_only), reset_only_entry_count=len(reset_only),
        forced_buy_common_count=len(common_force), fixed_only_forced_buy_net=fixed_sum,
        reset_only_forced_buy_net=reset_sum,
        common_forced_buys=[dict(fixed=describe(x,fixed_o),reset=describe(y,reset_o)) for x,y in common_force],
        fixed_only_forced_buys=[describe(x,fixed_o) for x in sorted(fixed_only_force,key=lambda row:row[4])],
        reset_only_forced_buys=[describe(x,reset_o) for x in sorted(reset_only_force,key=lambda row:row[4])],
        raw_market_reads=0, original_measurement_reads=0, quotes_columns_read=0, financial_replay=0,
        解釈='再起算により同方向の小さいrankから再参加し、当日は場末買いが7枚から10枚へ増えた。共通四玉を除く固定三玉と再起算六玉の損失差は64246円。途中追尾益の29270円改善を超え、全場34976円悪化した。',
        留保='共通性は実入口の方向・判断原行・約定原行・実建値による。UIDやrankを同じ親の識別子にしない。同じ入力の全経路比較であり、追加六玉だけを消せば他の再参加を不変にできるという因果対照ではない。')
    target = HERE/'result/九月二十四日再起算で残った買い玉と固定枠の独立比較.json'
    assert not target.exists()
    payload = (json.dumps(proof,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    target.write_bytes(payload)
    print(json.dumps(dict(passed=True,sha256=hashlib.sha256(payload).hexdigest(),
        summaries=summaries,delta=delta,fixed_only_forced_buys=proof['fixed_only_forced_buys'],
        reset_only_forced_buys=proof['reset_only_forced_buys']),ensure_ascii=False))


if __name__ == '__main__':
    main()
