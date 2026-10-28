"""保存済みの00145全約定を独立会計する。新規の金融再生は行わない。"""

from collections import defaultdict
import json
from pathlib import Path
import pickle
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ENGINE = ROOT / 'work/research145_engine'
RESIDUAL = ROOT / 'work/research145_residual'


def load(path):
    """
    機能: 保存済みのUTF-8資料を読む。
    引数: path(Path)はJSON。
    返り値: dict又はlistは内容。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def verify(orders, ready, quotes, expected):
    """
    機能: 原行約定、全所有数量、現金収支、親損益、保有時間を独立集計する。
    引数: orders(ndarray)、ready/quotes/expected(dict)は保存約定・原価格・既存集計。
    返り値: dictは検査件数と独立計算の成績。
    """
    assert orders.shape[1] == 10 and np.isfinite(orders).all()
    assert np.all(np.diff(orders[:, 0]) >= 0)
    bid, ask = np.asarray(quotes['bid']), np.asarray(quotes['ask'])
    normal = np.flatnonzero(np.asarray(quotes['quote_valid'], bool) & np.isfinite(bid)
                           & np.isfinite(ask) & (bid > 0) & (ask > bid))
    holdings, parent_cash, parent_side = {}, defaultdict(float), {}
    side_qty, sleeve_qty = defaultdict(int), defaultdict(int)
    maximum = 0
    total = 0
    start = float(ready['start'])
    finish = start + (420 if ready['session'].endswith('_Day') else 600) * 60
    previous_time, held_seconds = start, 0.
    midpoint_cash = 0.
    terminal_rows = []
    terminal_delta = 0.
    terminal_parent_deltas = defaultdict(float)
    for row in orders:
        fill, decision, parent, side, qty, price, reason, new, uid, fee = row
        assert all(value == int(value) for value in (fill, decision, parent, side, qty, reason, new, uid))
        fill, decision, parent, side, qty, new, uid = map(int, (fill, decision, parent, side, qty, new, uid))
        assert side in (-1, 1) and new in (0, 1) and qty > 0 and fee == 0
        assert fill == normal[np.searchsorted(normal, decision, side='right')]
        assert price == (ask[fill] if side > 0 else bid[fill])
        now = float(ready['time_s'][fill])
        assert now >= previous_time
        if total > 0:
            held_seconds += max(0., min(now, finish) - max(previous_time, start))
        previous_time = now
        key = parent, uid
        sleeve = parent // 10_000_000
        assert sleeve in (0, 1, 2)
        if new:
            assert parent not in parent_side or parent_side[parent] == side
            parent_side[parent] = side
            old_side, old_qty = holdings.get(key, (side, 0))
            assert old_side == side
            holdings[key] = side, old_qty + qty
            total += qty
            side_qty[side] += qty
            sleeve_qty[sleeve, side] += qty
        else:
            assert key in holdings
            old_side, old_qty = holdings[key]
            assert old_side == -side and old_qty >= qty
            holdings[key] = old_side, old_qty - qty
            total -= qty
            side_qty[-side] -= qty
            sleeve_qty[sleeve, -side] -= qty
        assert total >= 0 and all(0 <= value <= 10 for value in side_qty.values())
        assert all(0 <= value <= (5, 3, 2)[owner] for (owner, _), value in sleeve_qty.items())
        maximum = max(maximum, *side_qty.values())
        parent_cash[parent] -= side * qty * price * 100.
        midpoint_cash -= side * qty * (ask[fill] + bid[fill]) * 50.
        if reason == 93 and float(ready['time_s'][decision]) < ready['limit']:
            assert not new and ready['session'] in ('2026-09-25_Day', '2026-09-28_Day', '2026-10-05_Day', '2026-10-19_Day')
            corrected_decision = int(np.searchsorted(ready['time_s'], ready['limit'], side='left'))
            corrected_fill = int(normal[np.searchsorted(normal, corrected_decision, side='right')])
            corrected_price = float(ask[corrected_fill] if side > 0 else bid[corrected_fill])
            difference = -side * qty * (corrected_price-price) * 100.
            terminal_delta += difference
            terminal_parent_deltas[parent] += difference
            terminal_rows.append(dict(parent=parent, uid=uid, side=side, quantity=qty,
                old_decision=decision, old_decision_time=float(ready['time_s'][decision]),
                old_fill=fill, old_price=price, corrected_decision=corrected_decision,
                corrected_fill=corrected_fill, corrected_price=corrected_price, difference=difference))
    assert total == 0 and all(qty == 0 for _, qty in holdings.values())
    profit = sum(max(0., value) for value in parent_cash.values())
    loss = -sum(min(0., value) for value in parent_cash.values())
    net = sum(parent_cash.values())
    assert net == expected['gross'] == expected['net']
    assert profit == expected['profit'] and loss == expected['loss'] and expected['fees'] == 0
    assert maximum == expected['max_per_side']
    assert abs(held_seconds / 60 - expected['held_minutes_excluding_03_06']) < 1.e-7
    assert midpoint_cash == expected['midpoint_gross']
    assert len(parent_cash) == expected['parent_count']
    assert {int(row['id']): row['net'] for row in expected['parent_records']} == dict(parent_cash)
    adjusted_parents = {parent: cash + terminal_parent_deltas[parent] for parent, cash in parent_cash.items()}
    return dict(method=expected['method'], session=ready['session'], orders=len(orders),
                parents=len(parent_cash), profit=profit, loss=loss, net=net,
                bbo_drag=midpoint_cash-net, max_per_side=maximum,
                held_minutes=held_seconds/60, all_checks_passed=True,
                legacy_terminal_rows=terminal_rows, terminal_delta=terminal_delta,
                terminal_adjusted_net=net+terminal_delta,
                terminal_adjusted_profit=sum(max(0., value) for value in adjusted_parents.values()),
                terminal_adjusted_loss=-sum(min(0., value) for value in adjusted_parents.values()))


def summary(records):
    """
    機能: 保存約定の独立会計から全場・昼夜の安定性指標を集計する。
    引数: records(list[dict])は監査済みの同一手法。
    返り値: dictは利益損失比と赤字場の深さ。
    """
    net = np.array([row['net'] for row in records])
    loss = -net[net < 0]
    winner = net[net > 0]
    profit_total = sum(row['profit'] for row in records)
    loss_total = sum(row['loss'] for row in records)
    terminal_profit = sum(row['terminal_adjusted_profit'] for row in records)
    terminal_loss = sum(row['terminal_adjusted_loss'] for row in records)
    return dict(sessions=len(records), net=float(net.sum()), profit=profit_total, loss=loss_total,
                pf=profit_total/loss_total if loss_total else None,
                losing_sessions=len(loss), mean_loss=float(loss.mean()) if len(loss) else 0.,
                median_loss=float(np.median(loss)) if len(loss) else 0.,
                max_loss=float(loss.max()) if len(loss) else 0.,
                mean_win=float(winner.mean()) if len(winner) else 0.,
                without_best3=float(net.sum()-np.sort(winner)[-3:].sum()),
                orders=sum(row['orders'] for row in records),
                legacy_terminal_rows=sum(len(row['legacy_terminal_rows']) for row in records),
                terminal_delta=sum(row['terminal_delta'] for row in records),
                terminal_adjusted_net=sum(row['terminal_adjusted_net'] for row in records),
                terminal_adjusted_pf=terminal_profit/terminal_loss if terminal_loss else None,
                terminal_adjusted_losing_sessions=int(sum(row['terminal_adjusted_net'] < 0 for row in records)))


def main():
    """
    機能: 完了50場×32条件の保存約定を読むだけで独立検算する。
    引数: なし。
    返り値: None。新しい売買条件の評価・金融再生は呼ばない。
    """
    engine = load(ENGINE / '結果145.json')
    residual = load(RESIDUAL / '残玉と部分利確後の全場結果145.json')
    index = {(row['session'], row['method']): row for row in engine['rows'] + residual['rows']}
    scenes = sorted({scene for scene, _ in index})
    assert len(scenes) == 50 and len(index) == 50*32
    records = []
    for scene in scenes:
        with (ENGINE / 'cache' / (scene+'.pkl')).open('rb') as stream:
            _, data, _, _, _ = pickle.load(stream)
        with np.load(ENGINE / 'measurement' / ('NK225_'+scene+'.npz')) as va, np.load(RESIDUAL / 'orders' / (scene+'.npz')) as ra:
            assert np.array_equal(va['V00'], ra['R00'])
            methods = sorted(method for session, method in index if session == scene)
            for method in methods:
                rows = va[method] if method.startswith('V') else ra[method]
                records.append(verify(rows, data['ready'], data['quotes'], index[scene, method]))
        print(scene+' 独立約定会計一致', flush=True)
    methods = sorted({row['method'] for row in records})
    groups = []
    for method in methods:
        for kind in ('All', 'Day', 'Night'):
            selected = [row for row in records if row['method'] == method and (kind == 'All' or row['session'].endswith('_'+kind))]
            groups.append(dict(method=method, kind=kind, **summary(selected)))
    report = dict(financial_replays=0, all_passed=True, sessions=50, accounts=len(records),
                  orders=sum(row['orders'] for row in records), baseline_V00_R00_exact=True,
                  limitation='旧源の場末判断が境界直前行に記録された例外を継承する。会計・次原行・数量検査の合格と、全判断の完全因果性を混同しない。終端差額は改善効果ではなく約定模型の感応度。',
                  rows=records, summaries=groups)
    (HERE/'全保存約定の独立監査145.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
