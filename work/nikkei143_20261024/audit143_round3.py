"""利益で一枚を残す第三巡について、未来不変・鏡像・保存会計を独立確認する。"""

import argparse
import traceback
import numpy as np
import audit143 as base


HERE, ROOT = base.HERE, base.ROOT
SCENES = ('2026-10-22_Day', '2026-10-21_Night')


def reflected_input(data, center):
    """
    機能: 自己気配と現在値だけを、売買方向に対して対称な価格へ反転する。
    引数: data(dict)、center(float)は入力と価格中心。
    返り値: dictは独立配列の鏡像。時計・公開ATR・刻みは変えない。
    """
    result = dict(data, ready=dict(data['ready']), quotes=dict(data['quotes']))
    result['quotes']['bid'] = 2*center-data['quotes']['ask']
    result['quotes']['ask'] = 2*center-data['quotes']['bid']
    if 'last' in data['ready']:
        result['ready']['last'] = 2*center-data['ready']['last']
    return result


def altered_future(data, reflected, baseline, cutoff):
    """
    機能: 未来価格だけを変更し、同じ元通知の将来約定値も変更後の気配へ合わせる。
    引数: data/reflected(dict)、baseline(ndarray)、cutoff(int)は入力・鏡像・通知・変更原行。
    返り値: tuple[dict,ndarray]は未来だけ変えた入力と元通知。過去の通知は変更しない。
    """
    result = dict(data, ready=dict(data['ready']), quotes=dict(data['quotes']))
    for key in ('bid', 'ask'):
        result['quotes'][key] = data['quotes'][key].copy()
        result['quotes'][key][cutoff:] = reflected['quotes'][key][cutoff:]
    if 'last' in data['ready']:
        result['ready']['last'] = data['ready']['last'].copy()
        result['ready']['last'][cutoff:] = reflected['ready']['last'][cutoff:]
    changed = baseline.copy()
    chosen = changed[:, 0] >= cutoff
    index = changed[chosen, 0].astype(int)
    changed[chosen, 5] = np.where(changed[chosen, 3] > 0,
        result['quotes']['ask'][index], result['quotes']['bid'][index])
    return result, changed


def load_material(shared):
    """
    機能: 登録済み二巡の注文目録と、元入力の50場目録を読み取る。
    引数: shared(module)は現在研究の共通参照機能。
    返り値: tuple[dict,dict,dict]は原入力・第一巡・第二巡の目録。
    """
    packets, _, _ = shared.material()
    first = {x['session']:x for x in base.read(HERE/'第一巡結果143.json')['cache']}
    second = {x['session']:x for x in base.read(HERE/'第二巡結果143.json')['cache']}
    return {x['session']:x for x in packets}, first, second


def parent_state(orders, parent, row):
    """
    機能: 指定原行までの一親の実約定だけから実現純益とUID残高を復元する。
    引数: orders(ndarray)、parent/row(int)は保存実注文と対象親・観測終端。
    返り値: tuple[float,dict]は全新規費用込み実現純益と残玉情報。
    """
    realized = 0.
    tickets = {}
    for order in orders[(orders[:, 2] == parent) & (orders[:, 0] <= row)]:
        uid, side, qty, fee = int(order[8]), int(order[3]), int(order[4]), int(order[9])
        realized -= fee
        if order[7]:
            assert uid not in tickets
            tickets[uid] = dict(side=side, quantity=qty, entry=float(order[5]), first_fill=int(order[0]))
        else:
            item = tickets[uid]
            realized += item['side']*(float(order[5])-item['entry'])*qty*100.
            item['quantity'] -= qty
            assert item['quantity'] >= 0
    return realized, {uid:item for uid, item in tickets.items() if item['quantity'] > 0}


def audit_budget(orders, trace, data, config):
    """
    機能: 残玉の予算が実約定後の純益に等しく、含み益や新規費用を二重計上しないことを確認する。
    引数: orders/trace(ndarray)、data/config(dict)は実注文・判断・原板・条件。
    返り値: list[dict]は検算済み予算確定。最終の飛び越え損失を予算以内へ補正しない。
    """
    assert trace.ndim == 2 and trace.shape[1] == 13
    result = []
    for event in trace:
        row, parent, kind = int(event[0]), int(event[1]), int(event[2])
        if kind != 3:
            continue
        realized, held = parent_state(orders, parent, row)
        assert sum(item['quantity'] for item in held.values()) == 1
        uid, item = next(iter(held.items()))
        side, entry = item['side'], item['entry']
        assert side == int(event[3])
        assert abs(realized-event[7]) < 1e-7, ('実現純益', row, parent, realized, event[7])
        budget = max(0., realized)*config['profit_fraction']
        assert abs(budget-event[8]) < 1e-7, ('利益予算', row, parent)
        mark = data['quotes']['bid'][row] if side > 0 else data['quotes']['ask'][row]
        gain = side*(mark-entry)
        assert abs(event[10]-gain) < 1e-7
        assert abs(event[11]-gain) < 1e-7, '残玉化前の最高値を流用'
        gain_floor = (38.-budget)/100.
        parent_total = orders[orders[:, 2] == parent]
        net = float(np.sum(-parent_total[:, 3]*parent_total[:, 4]*parent_total[:, 5]*100.-parent_total[:, 9]))
        result.append(dict(row=row, parent=parent, uid=uid, realized_net=realized, budget=budget,
            residual_entry=entry, residual_side=side, risk_floor_price=entry+side*gain_floor,
            parent_net=net, final_below_budget_line=net < realized-budget-1e-7))
    return result


def mechanics(registry):
    """
    機能: 登録した二場の四源・全設定を未来不変、鏡像、数量・費用で検査する。
    引数: registry(Path)は第三巡登録。
    返り値: None。採用条件を探さず、機械的な反証結果だけ別JSONへ保存する。
    """
    record, plan = base.registration(registry)
    import common143 as shared
    import run143_round3 as runner
    import profit_residual143 as trader
    packets, first, second = load_material(shared)
    result = dict(登録=record, status='実行中', results=[], 条件探索=0, script_sha256=base.digest(__file__))
    destination = HERE/'第三巡の実データ機械監査143.json'
    try:
        for scene in SCENES:
            packet = shared.packet_from(packets[scene])
            key = (scene, 'NK225')
            data = dict(ready=packet['inputs'][key], quotes=packet['quotes'][key])
            sources, _, _ = runner.sources(scene, first, second)
            quote = data['quotes']
            index = np.flatnonzero(quote['quote_valid'] & np.isfinite(quote['bid']) & np.isfinite(quote['ask']))[0]
            center = float((quote['bid'][index]+quote['ask'][index])*.5)
            reflected = reflected_input(data, center)
            for source, baseline in sources.items():
                cap = 2 if source == 'CS' else 5
                for config in plan['configs']['residual']:
                    orders, trace = trader.replay(data, baseline, config)
                    mirrored, mt = trader.replay(reflected, base.mirror_orders(baseline, center), config)
                    cutoff = len(data['ready']['time_s'])//2
                    if len(orders):
                        cutoff = max(cutoff, int(orders[0, 0])+1)
                    assert cutoff < len(data['ready']['time_s'])
                    altered, changed_baseline = altered_future(data, reflected, baseline, cutoff)
                    future, ft = trader.replay(altered, changed_baseline, config)
                    count = base.assert_prefix(orders, future, cutoff)
                    np.testing.assert_array_equal(trace[trace[:, 0] < cutoff], ft[ft[:, 0] < cutoff])
                    base.assert_mirror(orders, mirrored, center)
                    account = base.orders_account(orders, data, cap, scene)
                    mirror_account = base.orders_account(mirrored, reflected, cap, scene)
                    base.orders_account(future, altered, cap, scene)
                    for column in ('profit', 'loss', 'net', 'holding_ratio'):
                        assert abs(account[column]-mirror_account[column]) < 1e-6
                    budgets = audit_budget(orders, trace, data, config)
                    mirror_budgets = audit_budget(mirrored, mt, reflected, config)
                    assert len(budgets) == len(mirror_budgets)
                    audit_budget(future, ft, altered, config)
                    if config['id'] == 'H00':
                        np.testing.assert_array_equal(orders, baseline)
                    result['results'].append(dict(session=scene, source=source, method=config['id'], cap=cap,
                        orders=len(orders), prefix_orders=count, trace_rows=len(trace),
                        future_unchanged=True, mirror_equal=True, next_quote_fee_uid_cap_flat=True,
                        realized_budget_checks=budgets))
            print(scene, '第三巡の独立機械監査合格', flush=True)
        result.update(status='全件合格', cases=len(result['results']),
            empty_order_cases=sum(row['orders'] == 0 for row in result['results']),
            empty_prefix_cases=sum(row['prefix_orders'] == 0 for row in result['results']),
            限界='価格時計・ラージBBO代理の内部整合性検査。次正常約定までの飛び越えは実現利益予算を超え得る。未知の収益性や実mini約定は未証明。')
        base.save(destination, result)
    except Exception:
        result.update(status='失敗', error=traceback.format_exc())
        base.save(destination, result)
        raise


def saved(registry, result_file):
    """
    機能: 第三巡全保存注文を独立会計し、無変更対照と元注文を確認する。
    引数: registry/result_file(Path)は登録と全結果。
    返り値: None。保存済み注文を読み取るだけで新しい判断を生成しない。
    """
    record, plan = base.registration(registry)
    import common143 as shared
    import run143_round3 as runner
    packets, first, second = load_material(shared)
    result = base.read(result_file)
    expected = {(row['session'], row['method']):row for row in result['rows']}
    cache = {item['session']:item for item in result['cache']}
    configs = {config['id'][1:]:config for config in plan['configs']['residual']}
    checks, unchanged, budgets = [], [], []
    for scene, item in packets.items():
        packet = shared.packet_from(item)
        key = (scene, 'NK225')
        data = dict(ready=packet['inputs'][key], quotes=packet['quotes'][key])
        sources, _, _ = runner.sources(scene, first, second)
        ref = cache[scene]
        path = ROOT/ref['path']
        assert base.digest(path) == ref['sha256']
        with np.load(path) as archive, np.load(HERE/'round3/traces'/f'NK225_{scene}.npz') as traces:
            for method in archive.files:
                cap = 2 if method.startswith('CS') else 5 if method[:2] in ('CA', 'CB', 'CG') else 10
                account = base.orders_account(archive[method], data, cap, scene)
                row = expected[scene, method]
                for column in ('profit', 'loss', 'net', 'holding_ratio'):
                    assert abs(account[column]-row[column]) < 1e-7, (scene, method, column)
                checks.append(dict(session=scene, method=method, cap=cap, orders=account['orders'], passed=True))
                if method[:2] in sources and method[2:] != '00':
                    for entry in audit_budget(archive[method], traces[method], data, configs[method[2:]]):
                        budgets.append(dict(session=scene, method=method, **entry))
            for name, source in sources.items():
                np.testing.assert_array_equal(archive[name+'00'], source)
                unchanged.append(dict(session=scene, source=name, exact_equal=True))
        print(scene, '第三巡保存全注文の独立会計合格', flush=True)
    base.save(HERE/'第三巡保存全注文の独立監査143.json', dict(登録=record, 新金融再生=0, status='全件合格',
        件数=len(checks), 注文数=sum(row['orders'] for row in checks), results=checks,
        unchanged_sources=unchanged, realized_budget_checks=budgets,
        account_unit='残玉を同じ元親に含めた費用後完結親の収支', script_sha256=base.digest(__file__)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('mechanics', 'saved'))
    parser.add_argument('--registration', type=base.Path, default=HERE/'第三巡登録143.json')
    parser.add_argument('--results', type=base.Path, default=HERE/'第三巡結果143.json')
    args = parser.parse_args()
    if args.stage == 'mechanics':
        mechanics(args.registration)
    else:
        saved(args.registration, args.results)
