"""第二巡の固定支持・旧入口復元を、登録後の機械検査と保存会計で独立監査する。"""

import argparse
import traceback
import numpy as np
import audit143 as base


HERE, ROOT = base.HERE, base.ROOT
SCENES = ('2026-10-22_Day', '2026-10-21_Night')


def signature(config, original):
    """
    機能: 名前・出典を除き、実際の売買核へ渡る同一設定を識別する。
    引数: config(dict)、original(module)は設定と旧売買核。
    返り値: tupleは実動作キーと値の組。同じ条件を別の証拠と数えない。
    """
    keys = tuple(key for key in original.configurations()[0] if key not in ('id', 'name'))
    return tuple((key, config[key]) for key in sorted(keys))


def mirror24(data, center, peer_center):
    """
    機能: 旧24列特徴に明示的な鏡像変換を施す。
    引数: data(dict)、center/peer_center(float)は入力と価格中心。
    返り値: dictは24列を保持した独立鏡像入力。
    """
    features = data['features']
    assert features.shape[1] == 24
    padded = dict(data, features=np.column_stack((features, np.zeros((len(features), 6)))))
    result = base.mirror_data(padded, center, peer_center)
    result['features'] = result['features'][:, :24]
    return result


def source_cache(shared):
    """
    機能: 保存キー修正後の旧第二巡注文の目録を取得する。
    引数: shared(module)は現在研究の共通参照関数。
    返り値: dictは場名から旧日経注文の内容指紋への対応。
    """
    directory = ROOT/'work/aggressive140_20261024'
    cache = {}
    for folder in ('round2_known', 'round2_new'):
        for item in base.read(directory/folder/'結果140.json')['cache']:
            if item['symbol'] == 'NK225':
                cache[item['session']] = item
    return cache


def get_previous(cache, scene, method):
    """
    機能: 旧正規キーの保存注文をSHA一致後に読み取る。
    引数: cache(dict)、scene/method(str)は目録・場・旧手法名。
    返り値: ndarray|Noneは保存注文、又は未保存。
    """
    item = cache.get(scene)
    if item is None:
        return None
    path = ROOT/item['path']
    assert base.digest(path) == item['sha256']
    with np.load(path) as archive:
        return archive[method].copy() if method in archive.files else None


def validate_configs(configs, original):
    """
    機能: 再利用条件が真正旧設定と同一であり、初回枚数が上限以下か検証する。
    引数: configs(list[dict])、original(module)は設定一覧と旧売買核。
    返り値: list[dict]は別名の同一設定群。新しい金融結果は生成しない。
    """
    old = {item['id']:item for item in original.configurations()}
    groups = {}
    for config in configs:
        assert 1 <= config['initial'] <= config['maximum'] <= 5
        if config.get('reuse_method'):
            assert signature(config, original) == signature(old[config['reuse_method']], original)
        for label, tested in ((config['id'], config), ('L'+config['id'][1:], dict(config, initial=1, maximum=2))):
            groups.setdefault(signature(tested, original), []).append(label)
    return [dict(labels=labels, parameters=dict(key)) for key, labels in groups.items()]


def cutoff_for(orders, count):
    """
    機能: 原行の後半を変更し、可能なら少なくとも一約定を過去側へ残す。
    引数: orders(ndarray)、count(int)は注文と入力原行数。
    返り値: intは変更開始原行。無注文を有意な因果検査と扱わない。
    """
    cutoff = count//2
    if len(orders):
        cutoff = max(cutoff, int(orders[0, 0])+1)
    assert cutoff < count
    return cutoff


def mechanics(registry):
    """
    機能: 登録済み昼夜二場で旧同値・新条件因果・上下対称・全返済を検証する。
    引数: registry(Path)は第二巡登録。
    返り値: None。全50金融探索は親担当が行い、本関数は指定二場の機械検査だけを保存する。
    """
    record, plan = base.registration(registry)
    import common143 as shared
    import core_overlay143 as old_overlay
    import core_overlay_v2_143 as overlay
    original = shared.previous.first.original
    groups = validate_configs(plan['configs']['restored'], original)
    packets, cache, _ = shared.material()
    packets = {item['session']:item for item in packets}
    oldcache = source_cache(shared)
    result = dict(登録=record, status='実行中', results=[], reused_checks=[], old_overlay_checks=[],
        duplicate_settings=groups, 条件探索=0, script_sha256=base.digest(__file__))
    destination = HERE/'第二巡の実データ機械監査143.json'
    try:
        for scene in SCENES:
            packet = shared.packet_from(packets[scene])
            prepared30, _, _, history15 = shared.previous.prepared(packet)
            data = prepared30['NK225']
            baseline, _, _ = shared.sources(scene, cache)
            centers = {}
            for symbol, item in prepared30.items():
                q = item['quotes']
                ix = np.flatnonzero(q['quote_valid'] & np.isfinite(q['bid']) & np.isfinite(q['ask']))[0]
                centers[symbol] = (q['bid'][ix]+q['ask'][ix])*.5
            reflected = base.mirror_data(data, centers['NK225'], centers['TOPIX'])
            h = history15[scene, 'NK225']
            mh = base.mirror_history15(h, centers['NK225'])
            mirrored_baseline = base.mirror_orders(baseline, centers['NK225'])
            for config in old_overlay.configurations():
                before, oldtrace = old_overlay.replay(data, baseline, h, config)
                after, trace = overlay.replay(data, baseline, h, config)
                np.testing.assert_array_equal(before, after)
                np.testing.assert_array_equal(oldtrace, trace)
                result['old_overlay_checks'].append(dict(session=scene, method=config['id'], orders=len(after), equal=True))
            for config in plan['configs']['overlay']:
                orders, trace = overlay.replay(data, baseline, h, config)
                mirror_orders, _ = overlay.replay(reflected, mirrored_baseline, mh, config)
                cutoff = cutoff_for(orders, len(data['features']))
                altered = base.future_data(data, reflected, cutoff)
                altered_h = h.copy()
                altered_h[cutoff:] = mh[cutoff:]
                altered_baseline = baseline.copy()
                chosen = altered_baseline[:, 0] >= cutoff
                indices = altered_baseline[chosen, 0].astype(int)
                altered_baseline[chosen, 5] = np.where(altered_baseline[chosen, 3] > 0,
                    altered['quotes']['ask'][indices], altered['quotes']['bid'][indices])
                future, future_trace = overlay.replay(altered, altered_baseline, altered_h, config)
                past_count = base.assert_prefix(orders, future, cutoff)
                np.testing.assert_array_equal(trace[trace[:, 0] < cutoff], future_trace[future_trace[:, 0] < cutoff])
                base.assert_mirror(orders, mirror_orders, centers['NK225'])
                accounting = base.orders_account(orders, data, 5, scene)
                mirrored_accounting = base.orders_account(mirror_orders, reflected, 5, scene)
                base.orders_account(future, altered, 5, scene)
                for key in ('profit', 'loss', 'net', 'holding_ratio'):
                    assert abs(accounting[key]-mirrored_accounting[key]) < 1e-6
                result['results'].append(dict(session=scene, engine='overlay', methods=[config['id']], orders=len(orders),
                    cap=5, prefix_orders=past_count, future_unchanged=True, mirror_equal=True, account=True))
            prepared24 = {}
            for group in groups:
                config = group['parameters']
                window = config['window']
                if window not in prepared24:
                    prepared24[window] = original.prepare(packet, window)['NK225']
                source = prepared24[window]
                if window == 40:
                    np.testing.assert_array_equal(source['features'], data['features'][:, :24])
                    np.testing.assert_array_equal(source['quotes']['bid'], data['quotes']['bid'])
                    np.testing.assert_array_equal(source['quotes']['ask'], data['quotes']['ask'])
                opposite = mirror24(source, centers['NK225'], centers['TOPIX'])
                orders, curve = original.replay(source, config)
                mirrored, mc = original.replay(opposite, config)
                cutoff = cutoff_for(orders, len(source['features']))
                altered = base.future_data(source, opposite, cutoff)
                future, fc = original.replay(altered, config)
                past_count = base.assert_prefix(orders, future, cutoff)
                np.testing.assert_allclose(curve[:cutoff], fc[:cutoff], rtol=0, atol=1e-6)
                base.assert_mirror(orders, mirrored, centers['NK225'])
                np.testing.assert_allclose(curve, mc, rtol=0, atol=1e-6)
                cap = config['maximum']
                for rows, inputs, equity in ((orders, source, curve), (mirrored, opposite, mc), (future, altered, fc)):
                    account = base.orders_account(rows, inputs, cap, scene)
                    assert abs(account['net']-equity[-1]) < 1e-6
                for saved_config in plan['configs']['restored']:
                    if saved_config.get('reuse_method') and signature(saved_config, original) == signature(config, original):
                        expected = get_previous(oldcache, scene, saved_config['reuse_method'])
                        assert expected is not None, (scene, '登録検査場の旧単体保存が見つかりません')
                        np.testing.assert_array_equal(orders, expected)
                        result['reused_checks'].append(dict(session=scene, method=saved_config['reuse_method'], orders=len(orders), equal=True))
                result['results'].append(dict(session=scene, engine='restored', methods=group['labels'], orders=len(orders),
                    cap=cap, initial=config['initial'], budget_ticks=config['budget_ticks'], prefix_orders=past_count,
                    future_unchanged=True, mirror_equal=True, account=True))
            print(scene, '第二巡の独立機械監査合格', flush=True)
        result.update(status='全件合格', cases=len(result['results']), empty_order_cases=sum(row['orders'] == 0 for row in result['results']),
            empty_prefix_cases=sum(row['prefix_orders'] == 0 for row in result['results']),
            限界='原価格時計とラージBBO代理の模型内検査。独立設定だけ数え、同値ラベルの重複を証拠数へ足さない。未知場の収益性は未証明。')
        base.save(destination, result)
    except Exception:
        result.update(status='失敗', error=traceback.format_exc())
        base.save(destination, result)
        raise


def saved(registry, result_file):
    """
    機能: 第二巡の全保存注文を独立再会計し、再利用と重複設定も照合する。
    引数: registry/result_file(Path)は登録・結果。
    返り値: None。新しい注文は生成しない。
    """
    record, plan = base.registration(registry)
    import common143 as shared
    original = shared.previous.first.original
    groups = validate_configs(plan['configs']['restored'], original)
    configs = {config['id']:config for config in plan['configs']['restored']}
    result = base.read(result_file)
    expected = {(row['session'], row['method']):row for row in result['rows']}
    cache = {item['session']:item for item in result['cache']}
    oldcache = source_cache(shared)
    packets, _, _ = shared.material()
    checks, old_equal = [], []
    for item in packets:
        scene = item['session']
        packet = shared.packet_from(item)
        key = (scene, 'NK225')
        data = dict(ready=packet['inputs'][key], quotes=packet['quotes'][key])
        item = cache[scene]
        path = ROOT/item['path']
        assert base.digest(path) == item['sha256']
        with np.load(path) as archive:
            for method in archive.files:
                cap = configs[method]['maximum'] if method.startswith('R') else 2 if method.startswith('L') else 5 if method.startswith('O') else 10
                account = base.orders_account(archive[method], data, cap, scene)
                row = expected[scene, method]
                for column in ('profit', 'loss', 'net', 'holding_ratio'):
                    assert abs(account[column]-row[column]) < 1e-7, (scene, method, column)
                checks.append(dict(session=scene, method=method, cap=cap, orders=account['orders'], passed=True))
            for group in groups:
                reference = archive[group['labels'][0]]
                for label in group['labels'][1:]:
                    np.testing.assert_array_equal(reference, archive[label])
            for config in configs.values():
                if not config.get('reuse_method'):
                    continue
                old = get_previous(oldcache, scene, config['reuse_method'])
                if old is not None:
                    np.testing.assert_array_equal(old, archive[config['id']])
                    old_equal.append(dict(session=scene, method=config['id'], source_method=config['reuse_method'], equal=True))
        print(scene, '第二巡保存全注文の独立会計合格', flush=True)
    base.save(HERE/'第二巡保存全注文の独立監査143.json', dict(登録=record, status='全件合格', 新金融再生=0,
        件数=len(checks), 注文数=sum(row['orders'] for row in checks), results=checks,
        reused_checks=old_equal, duplicate_settings=groups,
        account_unit='新規・追加・全返済の費用を含む完結親の収支', script_sha256=base.digest(__file__)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('mechanics', 'saved'))
    parser.add_argument('--registration', type=base.Path, default=HERE/'第二巡登録143.json')
    parser.add_argument('--results', type=base.Path, default=HERE/'第二巡結果143.json')
    args = parser.parse_args()
    if args.stage == 'mechanics':
        mechanics(args.registration)
    else:
        saved(args.registration, args.results)
