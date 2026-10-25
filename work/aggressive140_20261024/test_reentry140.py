"""利益後再参加の因果性・整数会計・通知競合を人工価格で検証する。"""

import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from reentry140 import REENTRY_PARENT_BASE, defaults, replay


HERE = Path(__file__).resolve().parent
CHECKS = []


def check(condition, label):
    """
    機能: 人工検証の真偽を記録し、不一致なら直ちに止める。
    引数: condition(bool)、label(str)は結果と説明。
    返り値: None。
    """
    assert bool(condition), label
    CHECKS.append(label)


def fixture():
    """
    機能: 通常玉の部分利確・全利確後に押し戻りを作る人工原行を生成する。
    引数: なし。
    返り値: dictは原行・気配・ATR・二市場・基準通知・設定。
    """
    times = np.arange(80, dtype=float)
    mid = np.full(80, 100.)
    mid[4:] = 110.
    mid[8:] = 108.5
    mid[10:] = 109.5
    mid[15:] = 113.
    mid[16:] = 114.5
    mid[19:] = 111.5
    quotes = dict(bid=mid - .1, ask=mid + .1, quote_valid=np.ones(80, dtype=bool))
    market = np.ones((80, 12))
    market[:, 0] = mid
    market[:, 1] = mid
    market[:, 2:4] = 2.
    market[:, 4:8] = .5
    market[:, 8] = times - .1
    config = defaults()
    config.update(quantity=4, cooldown_seconds=2., expiry_seconds=100.,
                  support_hold_seconds=2., entry_cutoff_seconds=0.,
                  risk_floor=1., fee_tenths=385, multiplier=100.)
    data = dict(times=times, quotes=quotes, atr=np.full(80, 2.), market=market,
                end=60., config=config)
    data['base'] = make_base(data, [(1, 0, 1, 1, 5, 1, 0),
                                    (4, 3, 1, -1, 2, 0, 0),
                                    (6, 5, 1, -1, 3, 0, 0)])
    return data


def make_base(data, records):
    """
    機能: 指定原行の気配から通常担当の人工通知を作る。
    引数: data(dict)、records(list[tuple])は約定行・判断行・親・方向・枚数・新規・UID。
    返り値: ndarrayは既存十列形式の通常通知。
    """
    result = []
    for row, source, parent, side, qty, new, uid in records:
        price = data['quotes']['ask' if side > 0 else 'bid'][row]
        result.append([row, source, parent, side, qty, price, 1 if new else 2,
                       new, uid, qty * data['config']['fee_tenths'] // 10])
    return np.array(result, dtype=float).reshape(-1, 10)


def run(data, **changes):
    """
    機能: 人工入力に設定差分を適用し、原行再生と独立会計を実行する。
    引数: data(dict)、changes(dict)は設定差分。
    返り値: tuple[ndarray,dict,dict]は約定・診断・親別差引損益。
    """
    config = dict(data['config'], **changes)
    orders, diagnostic = replay(data['times'], data['quotes'], data['atr'], data['market'],
                                data['base'], data['end'], config)
    tickets = {}
    parents = {}
    held = {-1: 0, 1: 0}
    cash = 0.
    for o in orders:
        row, source, pid, side, qty = map(int, o[:5])
        new, uid, fee = map(int, o[7:])
        check(row > source, '発注判断より後の原行でのみ約定')
        check(data['quotes']['quote_valid'][row], '正常気配だけで約定')
        check(fee == qty * config['fee_tenths'] // 10, '各注文で手数料の円未満を切捨て')
        px = float(o[5])
        check(abs(px - data['quotes']['ask' if side > 0 else 'bid'][row]) < 1.e-8, '売買側BBOで約定')
        parents[pid] = parents.get(pid, 0.) - fee
        cash += -side * qty * px * config['multiplier'] - fee
        key = (pid, uid)
        if new:
            check(key not in tickets, '玉IDは再利用しない')
            tickets[key] = [qty, side, px]
            held[side] += qty
        else:
            q, d, entry = tickets[key]
            check(q >= qty and d == -side, '返済方向と実保有枚数が一致')
            parents[pid] += d * (px - entry) * qty * config['multiplier']
            tickets[key][0] -= qty
            held[-side] -= qty
        check(all(0 <= q <= config['cap'] for q in held.values()), '片方向上限を各約定で拘束')
    check(not any(held.values()), '全玉を場内返済')
    check(abs(cash - sum(parents.values())) < 1.e-6, '原価と親会計と現金収支が一致')
    for event in diagnostic['events']:
        if int(event[1]) in (3, 7):
            check(abs(event[6] - parents[int(event[2])]) < 1.e-6, '再参加権利に使う内部損益も独立会計と一致')
    return orders, diagnostic, parents


def main():
    """
    機能: 利確資格・支持・未来差替え・上下対称・競合・終端を人工価格で確かめる。
    引数: なし。
    返り値: None。実装指紋付き確認JSONを保存する。実市場の金融再生は行わない。
    """
    d = fixture()
    baseline, _, _ = run(d, enabled=False)
    check(np.array_equal(baseline, d['base']), '再参加無効なら通常通知と完全同値')
    orders, diag, net = run(d)
    new = orders[(orders[:, 2] >= REENTRY_PARENT_BASE) & (orders[:, 7] == 1)]
    check(len(new) == 1 and new[0, 1] == 12 and new[0, 0] == 13, '押戻りと再進行と支持持続を経て一回再参加')
    check(np.array_equal(orders[orders[:, 2] < REENTRY_PARENT_BASE], d['base']), '新判断に競合しない通常約定は不変')
    check(np.all(diag['events'][diag['events'][:, 1] == 4, 0] >= 6), '部分利確だけでは再参加権利を作らない')
    check(np.any(orders[:, 6] == 1405), '再参加玉を整数枚数で部分利確')
    check(all(value > 0. for value in net.values()), '人工の通常親と再参加親は手数料後で黒字')

    # ----------------------------------------
    # 同じ保有枠の通常親は、その新規判断が実際に到来した時だけ見送る。
    busy = copy.deepcopy(d)
    busy['base'] = np.vstack((d['base'], make_base(d, [(15, 14, 2, 1, 5, 1, 0), (30, 29, 2, -1, 5, 0, 0)])))
    busy_orders, busy_diag, _ = run(busy)
    check(np.array_equal(busy_orders, orders), '後の通常入口が来ても再参加玉の出口を前倒ししない')
    check(len(busy_diag['skipped_baseline']) == 1 and busy_diag['skipped_baseline'][0, 0] == 14, '通常親の判断時点でのみ見送りを記録')
    simultaneous = copy.deepcopy(d)
    simultaneous['base'] = np.vstack((d['base'], make_base(d, [(13, 12, 2, 1, 5, 1, 0), (30, 29, 2, -1, 5, 0, 0)])))
    simultaneous_orders, _, _ = run(simultaneous, max_reentries=1)
    check(not np.any((simultaneous_orders[:, 2] >= REENTRY_PARENT_BASE) & (simultaneous_orders[:, 1] == 12)), '同一判断行では通常親の新規を優先')

    # ----------------------------------------
    # 一部が利益でも全体が赤字、未参加補完、相手の同時刻、相手不明では権利を作らない。
    losing = copy.deepcopy(d)
    losing['quotes']['bid'][6] = 90.
    losing['quotes']['ask'][6] = 90.2
    losing['base'][2, 5] = 90.
    no, _, pn = run(losing, entry_mode='delay')
    check(pn[1] < 0 and len(no) == len(d['base']), '初期部分利確でなく全体損益を使う')
    extra = copy.deepcopy(d)
    extra['base'][:, 8] = 999
    no, _, _ = run(extra)
    check(len(no) == len(d['base']), '未参加補完を通常主担当の利確と混同しない')
    for case in ('同時刻', '不明'):
        unknown = copy.deepcopy(d)
        if case == '同時刻':
            unknown['market'][:, 8] = unknown['times']
        else:
            unknown['market'][:, 11] = 0.
        no, _, _ = run(unknown)
        check(len(no) == len(d['base']), case + 'の相手市場で支持を捏造しない')

    # ----------------------------------------
    # 注文後の不都合は取消さず、次に使える正常気配へ送る。
    missing = copy.deepcopy(d)
    missing['quotes']['quote_valid'][13:15] = False
    delayed, _, _ = run(missing)
    got = delayed[(delayed[:, 2] >= REENTRY_PARENT_BASE) & (delayed[:, 7] == 1)]
    check(len(got) == 1 and got[0, 1] == 12 and got[0, 0] == 15, '判断後の欠測を越えて次正常行で約定')
    timed, _, _ = run(d, entry_mode='delay')
    got = timed[(timed[:, 2] >= REENTRY_PARENT_BASE) & (timed[:, 7] == 1)]
    check(got[0, 1] == 8, '単純時間解除は押戻りと支持の対照になる')

    # ----------------------------------------
    # 先の通常親の勝敗と価格を書き換えても、過去の注文・採否を変えない。
    future = copy.deepcopy(d)
    future['base'] = np.vstack((d['base'], make_base(d, [(45, 44, 2, 1, 5, 1, 0), (55, 54, 2, -1, 5, 0, 0)])))
    old, _, _ = run(future)
    future['quotes']['bid'][50:] -= 8.
    future['quotes']['ask'][50:] -= 8.
    future['base'][-1, 5] = future['quotes']['bid'][55]
    changed, _, _ = run(future)
    check(np.array_equal(old[old[:, 0] < 50], changed[changed[:, 0] < 50]), '未来価格と未来親損益の差替えで注文接頭が不変')
    mirror = copy.deepcopy(d)
    mirror['quotes']['bid'] = 200. - d['quotes']['ask']
    mirror['quotes']['ask'] = 200. - d['quotes']['bid']
    mirror['market'][:, 0:2] = 200. - d['market'][:, 0:2]
    mirror['market'][:, 4:8] *= -1.
    mirror['base'][:, 3] *= -1.
    mirror['base'][:, 5] = 200. - d['base'][:, 5]
    reflected, _, reflected_net = run(mirror)
    check(np.array_equal(orders[:, [0, 1, 2, 4, 6, 7, 8, 9]], reflected[:, [0, 1, 2, 4, 6, 7, 8, 9]]), '上下反転で時刻・枚数・理由が一致')
    check(np.array_equal(orders[:, 3], -reflected[:, 3]), '上下反転で方向のみ反転')
    check(all(abs(net[p] - reflected_net[p]) < 1.e-6 for p in net), '上下反転で費用後損益が一致')

    terminal = copy.deepcopy(d)
    terminal['quotes']['bid'][14:] = 109.4
    terminal['quotes']['ask'][14:] = 109.6
    terminal['end'] = 40.
    finished, _, _ = run(terminal)
    tail = finished[finished[:, 2] >= REENTRY_PARENT_BASE]
    check(tail[-1, 1] == 40 and tail[-1, 0] == 41 and tail[-1, 6] == 1409, '場末に判断して次正常行で全返済')
    many, _, _ = run(d, quantity=10)
    check(np.max(many[many[:, 7] == 1, 4]) == 10, '再参加十枚でも上限を超えない')
    run(d, quantity=1)
    run(d, quantity=3)
    twice = copy.deepcopy(d)
    for row, value in ((22, 112.5), (24, 110.5), (26, 111.5), (31, 117.), (32, 119.), (35, 116.)):
        twice['quotes']['bid'][row:] = value - .1
        twice['quotes']['ask'][row:] = value + .1
    twice_orders, _, _ = run(twice, max_reentries=2)
    check(np.sum((twice_orders[:, 2] >= REENTRY_PARENT_BASE) & (twice_orders[:, 7] == 1)) == 2,
          '一回目の再参加も実利益なら二回目まで許し上限で止める')
    first_loss = copy.deepcopy(twice)
    first_loss['quotes']['bid'][17:22] = 99.9
    first_loss['quotes']['ask'][17:22] = 100.1
    loss_orders, _, loss_net = run(first_loss, max_reentries=2)
    added = loss_orders[(loss_orders[:, 2] >= REENTRY_PARENT_BASE) & (loss_orders[:, 7] == 1)]
    check(len(added) == 1 and loss_net[int(added[0, 2])] < 0., '再参加が赤字なら残回数があっても連続再試行しない')
    results = dict(結果='全件合格', 確認数=len(CHECKS), 確認=CHECKS, 金融再生=0, API=0, 実注文=0,
                   実装SHA256=hashlib.sha256((HERE / 'reentry140.py').read_bytes()).hexdigest())
    (HERE / '再参加_人工確認.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(結果='全件合格', 確認数=len(CHECKS)), ensure_ascii=False))


if __name__ == '__main__':
    main()
