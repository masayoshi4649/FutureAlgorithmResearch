"""第三巡登録後に、中期状態の未来不変・上下対称と保存注文の会計を検査する。"""

import argparse
import pickle
import traceback
from pathlib import Path
import numpy as np
import verify_mechanics142 as base
from verify_patrol_mechanics142 import reversals


HERE, ROOT, OLD = base.HERE, base.ROOT, base.OLD
SCENES = ('2026-10-23_Day', '2026-10-22_Night')


def registration(path):
    """
    機能: 第三巡登録・計画・全凍結実装の内容指紋を確認する。
    引数: path(Path)は登録JSONの保存位置。
    返り値: tuple[dict,dict]は確認済み登録と計画。未登録では実データを読まない。
    """
    if not path.exists():
        raise SystemExit('第三巡未登録のため実データ検査は実行しません。')
    record = base.read(path)
    assert record['returncode'] == 0
    plan_path = ROOT / record['plan']['path']
    assert base.digest(plan_path) == record['plan']['sha256']
    plan = base.read(plan_path)
    assert record['id'] == plan['id']
    assert len(plan['configs']['regime']) == 6
    for source, sha in plan['spec']['implementation'].items():
        assert base.digest(ROOT / source) == sha, source
    return record, plan


def mirror(data, center, peer_center):
    """
    機能: 自他の価格・方向を鏡像化し、追加中期平均と高安も上下交換する。
    引数: data(dict)、center/peer_center(float)は入力と自他の価格中心。
    返り値: dictは48列鏡像入力。R・範囲・気配幅・刻み・標準偏差・効率は不変。
    """
    reflected = base.mirror(data, center, peer_center)
    original = data['features']
    changed = reflected['features']
    for column in (36, 37):
        changed[:, column] = 2. * center - original[:, column]
    for column in (42, 43):
        changed[:, column] = 2. * peer_center - original[:, column]
    changed[:, 38], changed[:, 39] = 2. * center - original[:, 39], 2. * center - original[:, 38]
    changed[:, 44], changed[:, 45] = 2. * peer_center - original[:, 45], 2. * peer_center - original[:, 44]
    np.testing.assert_array_equal(original[:, 30:36], changed[:, 30:36])
    np.testing.assert_array_equal(original[:, [40, 41, 46, 47]], changed[:, [40, 41, 46, 47]])
    return reflected


def mechanics(registry):
    """
    機能: 昼夜各一場×二市場×6政策の注文・判断履歴・時価を独立確認する。
    引数: registry(Path)は第三巡登録。未登録状態での金融再生を拒否する。
    返り値: None。利益の採否や条件探索をせず、機械的な検査記録だけを保存する。
    """
    record, plan = registration(registry)
    import run142
    import patrol_features142 as early
    import regime_features142 as features
    import regime_trader142 as trader
    manifest = {x['session']: x for x in base.read(OLD / 'inputs/input_manifest.json')['packets']}
    report = dict(登録=record, 条件探索=0, results=[], status='実行中', script_sha256=base.digest(Path(__file__)))
    output = HERE / '中期状態の実データ独立検査142.json'
    try:
        for scene in SCENES:
            item = manifest[scene]
            path = ROOT / item['path']
            assert base.digest(path) == item['sha256']
            packet = pickle.loads(path.read_bytes())
            standard, _, _, history = run142.prepared(packet)
            data = features.prepare(packet, early.prepare(packet, standard), history)
            centers = {s: float((d['quotes']['bid'][0] + d['quotes']['ask'][0]) * .5) for s, d in data.items()}
            for symbol in ('NK225', 'TOPIX'):
                source = data[symbol]
                peer = 'TOPIX' if symbol == 'NK225' else 'NK225'
                opposite = mirror(source, centers[symbol], centers[peer])
                for config in plan['configs']['regime']:
                    orders, curve, trace = trader.replay(source, config)
                    cutoff = len(source['features']) // 2
                    if len(orders):
                        cutoff = max(cutoff, int(orders[0, 0]) + 1)
                    assert cutoff < len(source['features'])
                    changed = base.future_only(source, opposite, cutoff)
                    future, fc, ft = trader.replay(changed, config)
                    mirrored, mc, mt = trader.replay(opposite, config)
                    prefix = orders[orders[:, 0] < cutoff]
                    np.testing.assert_array_equal(prefix, future[future[:, 0] < cutoff])
                    np.testing.assert_array_equal(trace[trace[:, 0] < cutoff], ft[ft[:, 0] < cutoff])
                    np.testing.assert_allclose(curve[:cutoff], fc[:cutoff], rtol=0, atol=1e-8)
                    np.testing.assert_array_equal(orders[:, [0, 1, 2, 4, 6, 7, 8, 9]], mirrored[:, [0, 1, 2, 4, 6, 7, 8, 9]])
                    np.testing.assert_array_equal(orders[:, 3], -mirrored[:, 3])
                    np.testing.assert_allclose(orders[:, 5], 2. * centers[symbol] - mirrored[:, 5], rtol=0, atol=1e-8)
                    np.testing.assert_array_equal(trace[:, [0, 1, 3, 4, 5, 6]], mt[:, [0, 1, 3, 4, 5, 6]])
                    np.testing.assert_array_equal(trace[:, 2], -mt[:, 2])
                    np.testing.assert_allclose(trace[:, 7:], mt[:, 7:], rtol=0, atol=1e-8)
                    np.testing.assert_allclose(curve, mc, rtol=0, atol=1e-6)
                    for rows, input_data, values in ((orders, source, curve), (future, changed, fc), (mirrored, opposite, mc)):
                        cash = base.audit_orders(rows, input_data, 5)
                        np.testing.assert_allclose(cash, values[-1], rtol=0, atol=1e-6)
                        reversals(rows)
                    report['results'].append(dict(session=scene, symbol=symbol, method=config['id'], orders=len(orders),
                        prefix_orders=len(prefix), cutoff=cutoff, reversals=reversals(orders), mirror=True, future=True,
                        prefix_has_fills=bool(len(prefix)), quantity_fee_nextquote_flat=True, same_row_reversal=0))
                    print(scene, symbol, config['id'], '中期状態の独立検査合格', flush=True)
        report['status'] = '全件合格'
        report['cases'] = len(report['results'])
        report['empty_prefix_cases'] = sum(not x['prefix_has_fills'] for x in report['results'])
        report['限界'] = '原価格時計・代理BBO模型の機械検査。実mini約定・受信時計・未見収益性は未証明。無注文の検査があれば件数を別記する。'
        base.save(output, report)
    except Exception:
        report['status'] = '失敗'
        report['error'] = traceback.format_exc()
        base.save(output, report)
        raise


def saved(registry, result_file):
    """
    機能: 第三巡保存全50場の親識別子・次正常気配・費用・数量を独立会計する。
    引数: registry/result_file(Path)は第三巡登録と結果JSON。
    返り値: None。保存注文のみを検査し、新しい売買判断は行わない。
    """
    record, _ = registration(registry)
    result = base.read(result_file)
    stats = {(x['session'], x['symbol'], x['method']): x for x in result['rows']}
    packets = {x['session']: x for f in (OLD / 'known_manifest140.json', OLD / 'inputs/input_manifest.json') for x in base.read(f)['packets']}
    cache = {(x['session'], x['symbol']): x for x in result['cache']}
    checked = []
    for scene in sorted(packets):
        item = packets[scene]
        path = Path(item['path'])
        path = path if path.is_absolute() else ROOT / path
        assert base.digest(path) == item['sha256']
        packet = pickle.loads(path.read_bytes())
        for symbol in ('NK225', 'TOPIX'):
            key = scene, symbol
            ref = cache[key]
            path = ROOT / ref['path']
            assert base.digest(path) == ref['sha256']
            data = dict(ready=packet['inputs'][key], quotes=packet['quotes'][key])
            with np.load(path) as z:
                for method in z.files:
                    orders = z[method]
                    standalone = method.startswith('R')
                    cash = base.audit_orders(orders, data, 5 if standalone else 10)
                    expected = stats[scene, symbol, method]['net']
                    assert abs(cash - expected) < 1e-6, (scene, symbol, method, cash, expected)
                    if standalone:
                        reversals(orders)
                    checked.append(dict(session=scene, symbol=symbol, method=method, orders=len(orders), 会計一致=True))
        print(scene, '第三巡保存会計の独立検査合格', flush=True)
    base.save(HERE / '第三巡保存全注文の独立検査142.json', dict(登録=record, 新金融再生=0, status='全件合格',
        件数=len(checked), 注文数=sum(x['orders'] for x in checked), results=checked))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('mechanics', 'saved'), nargs='?', default='mechanics')
    parser.add_argument('--registration', type=Path, default=HERE / '第三巡登録142.json')
    parser.add_argument('--results', type=Path, default=HERE / '第三巡結果142.json')
    arguments = parser.parse_args()
    if arguments.stage == 'saved':
        saved(arguments.registration, arguments.results)
    else:
        mechanics(arguments.registration)
