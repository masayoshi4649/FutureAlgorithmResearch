"""00143の保存会計と因果性を、売買判断から独立して検査する。"""

import argparse
import hashlib
import json
import pickle
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRIOR = ROOT / 'work/conditional142_20261024'
OLD = ROOT / 'work/aggressive140_20261024'
JST = ZoneInfo('Asia/Tokyo')
INTEGER_COLUMNS = (0, 1, 2, 3, 4, 6, 7, 8, 9)


def read(path):
    """
    機能: UTF-8の保存JSONを読む。
    引数: path(Path)は入力ファイル。
    返り値: dict/listは保存内容。
    """
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest(path):
    """
    機能: 内容を全展開せずSHA256を計算する。
    引数: path(Path)は入力ファイル。
    返り値: strは内容指紋。
    """
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, report):
    """
    機能: 検査記録を既存金融資料とは別ファイルに保存する。
    引数: path(Path)、report(dict)は保存先と結果。
    返り値: None。
    """
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def bounds(scene):
    """
    機能: セッションの公式時計と03時以降を除く評価終端を定める。
    引数: scene(str)は日付_Day又は日付_Night。
    返り値: tuple[float,float,float]は開始・公式終端・保有率評価終端。
    """
    day = datetime.fromisoformat(scene[:10]).replace(tzinfo=JST)
    if scene.endswith('_Day'):
        start, end = day.replace(hour=8, minute=45), day.replace(hour=15, minute=45)
        return start.timestamp(), end.timestamp(), end.timestamp()
    assert scene.endswith('_Night')
    next_day = day + timedelta(days=1)
    return day.replace(hour=17).timestamp(), next_day.replace(hour=6).timestamp(), next_day.replace(hour=3).timestamp()


def holding(orders, times, scene):
    """
    機能: 約定だけから方向別残高を復元し、保有時間の和集合を測る。
    引数: orders(ndarray[N,10])、times(ndarray)、scene(str)は注文・価格時計・場名。
    返り値: dictは420/600分基準の保有率と平均枚数。夜の損益は切断しない。
    """
    start, official_end, end = bounds(scene)
    events = {}
    for order in orders:
        row, side, qty, new = int(order[0]), int(order[3]), int(order[4]), int(order[7])
        at = float(times[row])
        assert np.isfinite(at) and start <= at <= official_end, ('場外約定時計', at)
        delta = events.setdefault(at, [0, 0])
        position_side = side if new else -side
        delta[0 if position_side > 0 else 1] += qty if new else -qty
    long = short = 0
    previous = start
    occupied = total_occupied = gross_time = net_time = hedged_time = 0.
    for at, delta in sorted(events.items()):
        width = max(0., min(at, end) - max(previous, start))
        full_width = max(0., min(at, official_end) - max(previous, start))
        if long or short:
            occupied += width
            total_occupied += full_width
        gross_time += (long + short) * width
        net_time += abs(long - short) * width
        if long and short:
            hedged_time += width
        long += delta[0]
        short += delta[1]
        assert long >= 0 and short >= 0
        previous = at
    assert long == short == 0, '保有率の終端残高が0ではありません'
    duration = end - start
    assert duration == (420 if scene.endswith('_Day') else 600) * 60
    return dict(evaluation_minutes=duration / 60., held_minutes=occupied / 60.,
        holding_ratio=occupied / duration, average_gross_quantity=gross_time / duration,
        average_absolute_net_quantity=net_time / duration, hedged_minutes=hedged_time / 60.,
        full_holding_ratio=total_occupied / (official_end-start),
        excluded_03_06_minutes=(total_occupied-occupied) / 60.)


def orders_account(orders, data, cap=10, scene=None):
    """
    機能: 次正常BBO・整数費用・UID別残高・親完結会計を独立検査する。
    引数: orders(ndarray[N,10])、data(dict)、cap(int)、scene(str|None)は注文と入力・上限・場名。
    返り値: dictは親完結単位の利益損失・費用・枚数・任意の保有率。
    """
    assert orders.ndim == 2 and orders.shape[1] == 10 and np.isfinite(orders).all()
    assert np.equal(orders[:, INTEGER_COLUMNS], np.trunc(orders[:, INTEGER_COLUMNS])).all(), '整数列が小数'
    assert np.all(np.diff(orders[:, 0]) >= 0), '保存注文が約定行順ではありません'
    ready, quote = data['ready'], data['quotes']
    symbol = ready['symbol']
    assert symbol in ('NK225', 'TOPIX')
    fee, multiplier = (385, 100.) if symbol == 'NK225' else (418, 1000.)
    bid, ask = quote['bid'], quote['ask']
    normal = np.flatnonzero(quote['quote_valid'] & np.isfinite(bid) & np.isfinite(ask) & (bid > 0.) & (bid < ask))
    tickets, parents = {}, {}
    long = short = maximum_long = maximum_short = 0
    for order in orders:
        row, decision, parent, side, qty = map(int, order[:5])
        price, reason = float(order[5]), int(order[6])
        new, uid, cost = map(int, order[7:])
        assert 0 <= decision < row < len(bid), ('判断・約定の原行', decision, row)
        assert side in (-1, 1) and qty > 0 and new in (0, 1)
        index = np.searchsorted(normal, decision, side='right')
        assert index < len(normal) and row == normal[index], ('次正常原行ではない', decision, row)
        assert abs(price - (ask[row] if side > 0 else bid[row])) < 1e-8, '売買気配が不一致'
        assert cost == qty * fee // 10, '注文単位の手数料切捨てが不一致'
        key = (parent, uid)
        if new:
            assert key not in tickets, ('UID再利用', key)
            tickets[key] = [side, qty, price]
            item = parents.setdefault(parent, dict(parent=parent, side=side, gross=0., fees=0,
                quantity=0, first_decision=decision, first_fill=row, last_fill=row, close_reasons=[]))
            assert item['side'] == side, ('同じ親に逆方向新規', parent)
            item['quantity'] += qty
            if side > 0:
                long += qty
            else:
                short += qty
        else:
            assert key in tickets, ('存在しない建玉の返済', key)
            entry_side, remaining, entry_price = tickets[key]
            assert entry_side == -side and remaining >= qty, ('返済側又は数量', key)
            tickets[key][1] -= qty
            item = parents[parent]
            item['gross'] += entry_side * (price-entry_price) * qty * multiplier
            item['close_reasons'].append(reason)
            if side < 0:
                long -= qty
            else:
                short -= qty
        item['fees'] += cost
        item['last_fill'] = row
        assert 0 <= long <= cap and 0 <= short <= cap, ('片方向上限', long, short, cap)
        maximum_long, maximum_short = max(maximum_long, long), max(maximum_short, short)
    assert long == short == 0 and all(item[1] == 0 for item in tickets.values()), '場末未返済'
    for item in parents.values():
        item['net'] = item['gross'] - item['fees']
    profit = sum(item['net'] for item in parents.values() if item['net'] > 0)
    loss = -sum(item['net'] for item in parents.values() if item['net'] < 0)
    result = dict(orders=len(orders), parents=len(parents), profit=profit, loss=loss, net=profit-loss,
        gross=sum(item['gross'] for item in parents.values()), fees=sum(item['fees'] for item in parents.values()),
        pf=profit/loss if loss else None, maximum_long=maximum_long, maximum_short=maximum_short,
        new_quantity=sum(item['quantity'] for item in parents.values()), parent_records=list(parents.values()),
        account_unit='新規・追加・部分返済の全費用を含む完結親の収支')
    if scene:
        result.update(holding(orders, ready['time_s'], scene))
    return result


def mirror_data(data, center, peer_center):
    """
    機能: 既存30/36/48列特徴と売買気配を上下対称へ変換する。
    引数: data(dict)、center/peer_center(float)は入力と価格中心。
    返り値: dictは独立配列を持つ鏡像。時計・幅・数量・効率は変えない。
    """
    result = dict(data, ready=dict(data['ready']), quotes=dict(data['quotes']))
    original = data['features']
    assert original.shape[1] in (30, 36, 48), '未知の追加列は鏡像規則を先に指定してください'
    changed = original.copy()
    changed[:, 0], changed[:, 1] = 2*center-original[:, 1], 2*center-original[:, 0]
    for column in (5, 6, 7, 10):
        changed[:, column] = 2*center-original[:, column]
    for column in (17, 19):
        changed[:, column] = 2*peer_center-original[:, column]
    for column in (3, 4, 12, 13, 14, 15, 20, 21, 24, 25, 26, 27, 28, 29):
        changed[:, column] = -original[:, column]
    if original.shape[1] == 48:
        for column in (36, 37):
            changed[:, column] = 2*center-original[:, column]
        for column in (42, 43):
            changed[:, column] = 2*peer_center-original[:, column]
        changed[:, 38], changed[:, 39] = 2*center-original[:, 39], 2*center-original[:, 38]
        changed[:, 44], changed[:, 45] = 2*peer_center-original[:, 45], 2*peer_center-original[:, 44]
    result['features'] = changed
    result['quotes']['bid'] = 2*center-data['quotes']['ask']
    result['quotes']['ask'] = 2*center-data['quotes']['bid']
    if 'last' in data['ready']:
        result['ready']['last'] = 2*center-data['ready']['last']
    return result


def mirror_orders(orders, center):
    """
    機能: 入口を固定する介入へ渡す保存通知を鏡像へ変換する。
    引数: orders(ndarray[N,10])、center(float)は通知と価格中心。
    返り値: ndarrayは側と価格のみを反転したコピー。未来通知の採否は別途検査する。
    """
    result = orders.copy()
    result[:, 3] = -orders[:, 3]
    result[:, 5] = 2*center-orders[:, 5]
    return result


def mirror_history(history, center):
    """
    機能: 公開済み高安・価格差・平均・始値の9列履歴を反転する。
    引数: history(ndarray[N,9])、center(float)は公開履歴と自己価格中心。
    返り値: ndarrayは高安交換・価格反射・差の符号反転を施したコピー。
    """
    assert history.ndim == 2 and history.shape[1] == 9
    changed = history.copy()
    changed[:, 0], changed[:, 1] = 2*center-history[:, 1], 2*center-history[:, 0]
    changed[:, 3:5] = -history[:, 3:5]
    changed[:, 5:8] = 2*center-history[:, 5:8]
    return changed


def mirror_history15(history, center):
    """
    機能: 旧基本枠の公開15列履歴を上下反転する。
    引数: history(ndarray[N,15])、center(float)は履歴と自己価格中心。
    返り値: ndarrayは自他方向差と自己高安・平均・始値を反転したコピー。
    """
    assert history.ndim == 2 and history.shape[1] == 15
    changed = history.copy()
    for column in (0, 1, 8):
        changed[:, column] = 2*center-history[:, column]
    changed[:, 3], changed[:, 4] = 2*center-history[:, 4], 2*center-history[:, 3]
    for column in (6, 7, 10, 11, 13):
        changed[:, column] = -history[:, column]
    return changed


def future_data(data, reflected, cutoff):
    """
    機能: 指定原行以降のみを変え、過去約定不変の反例入力を用意する。
    引数: data/reflected(dict)、cutoff(int)は元・鏡像・変更開始行。
    返り値: dictは前半を保持したコピー。
    """
    result = dict(data, ready=dict(data['ready']), quotes=dict(data['quotes']))
    for key in ('bid', 'ask'):
        result['quotes'][key] = data['quotes'][key].copy()
        result['quotes'][key][cutoff:] = reflected['quotes'][key][cutoff:]
    result['features'] = data['features'].copy()
    result['features'][cutoff:] = reflected['features'][cutoff:]
    if 'last' in data['ready']:
        result['ready']['last'] = data['ready']['last'].copy()
        result['ready']['last'][cutoff:] = reflected['ready']['last'][cutoff:]
    return result


def assert_prefix(original, changed, cutoff):
    """
    機能: 未来を変更しても変更開始より前の約定が不変か確認する。
    引数: original/changed(ndarray[N,10])、cutoff(int)は注文と変更開始原行。
    返り値: intは確認した過去約定件数。0件を有意な検査と誤記しない。
    """
    prefix = original[original[:, 0] < cutoff]
    np.testing.assert_array_equal(prefix, changed[changed[:, 0] < cutoff])
    return len(prefix)


def assert_mirror(original, changed, center):
    """
    機能: 鏡像でも判断・数量・費用が同一で、側と価格だけが反転するか確認する。
    引数: original/changed(ndarray[N,10])、center(float)は注文と価格中心。
    返り値: None。不一致では例外となる。
    """
    np.testing.assert_array_equal(original[:, [0, 1, 2, 4, 6, 7, 8, 9]], changed[:, [0, 1, 2, 4, 6, 7, 8, 9]])
    np.testing.assert_array_equal(original[:, 3], -changed[:, 3])
    np.testing.assert_allclose(original[:, 5], 2*center-changed[:, 5], rtol=0, atol=1e-8)


def registration(path):
    """
    機能: 実データを新条件で再生する前に登録・計画・凍結実装を照合する。
    引数: path(Path)は親担当が作成する登録JSON。
    返り値: tuple[dict,dict]は登録と計画。未登録では停止する。
    """
    assert Path(path).exists(), '未登録の実データ金融再生は禁止です'
    record = read(path)
    assert record['returncode'] == 0
    target = ROOT / record['plan']['path']
    assert digest(target) == record['plan']['sha256']
    plan = read(target)
    assert record['id'] == plan['id']
    for source, sha in plan['spec']['implementation'].items():
        assert digest(ROOT/source) == sha, source
    return record, plan


def baseline():
    """
    機能: 保存F1全50場を新共通会計で検査し、独立した既存方向監査と照合する。
    引数: なし。
    返り値: None。既存注文のみを読み、売買エンジンは呼ばない。
    """
    previous = read(HERE/'F1始終値方向と深夜除外保有率143.json')
    rows = previous['sessions']
    manifest = {x['session']:x for name in ('known_manifest140.json', 'inputs/input_manifest.json') for x in read(OLD/name)['packets']}
    cache = {x['session']:x for x in read(PRIOR/'結果142.json')['cache'] if x['symbol'] == 'NK225'}
    results = []
    for prior in rows:
        scene = prior['session']
        item = manifest[scene]
        packet_path = ROOT/item['path']
        assert digest(packet_path) == item['sha256']
        packet = pickle.loads(packet_path.read_bytes())
        item = cache[scene]
        order_path = ROOT/item['path']
        assert digest(order_path) == item['sha256']
        method = 'M1' if scene.endswith('_Day') else 'J04'
        with np.load(order_path) as archive:
            orders = archive[method]
        key = (scene, 'NK225')
        account = orders_account(orders, dict(ready=packet['inputs'][key], quotes=packet['quotes'][key]), 10, scene)
        for column in ('profit', 'loss', 'net'):
            assert abs(account[column]-prior[column]) < 1e-7, (scene, column)
        assert abs(account['holding_ratio']-prior['holding_ratio_excluding_03_06']) < 1e-12
        results.append(dict(session=scene, method=method, **account))
    save(HERE/'保存F1の共通会計照合143.json', dict(status='全件合格', 新金融再生=0, 件数=len(results),
        注文数=sum(row['orders'] for row in results), results=results, script_sha256=digest(Path(__file__))))
    print('保存F1全50場の共通会計照合合格', flush=True)


def mechanics(registry):
    """
    機能: 登録後に昼夜各一場の全条件を未来変更・鏡像・通知変更で独立検査する。
    引数: registry(Path)は親担当の正式登録。
    返り値: None。採否探索はせず検査結果だけを別JSONへ残す。
    """
    record, plan = registration(registry)
    import common143 as shared
    import core_overlay143 as overlay
    import episode143 as episode
    packets, cache, _ = shared.material()
    manifest = {item['session']:item for item in packets}
    result = dict(登録=record, 条件探索=0, results=[], status='実行中', script_sha256=digest(Path(__file__)))
    target = HERE/'第一巡の実データ機械監査143.json'
    try:
        for scene in ('2026-10-23_Day', '2026-10-22_Night'):
            packet = shared.packet_from(manifest[scene])
            prepared, _, _, histories15 = shared.previous.prepared(packet)
            data = prepared['NK225']
            base, _, _ = shared.sources(scene, cache)
            centers = {}
            for symbol, item in prepared.items():
                quote = item['quotes']
                good = np.flatnonzero(quote['quote_valid'] & np.isfinite(quote['bid']) & np.isfinite(quote['ask']))
                centers[symbol] = float((quote['bid'][good[0]]+quote['ask'][good[0]])*.5)
            reflected = mirror_data(data, centers['NK225'], centers['TOPIX'])
            h15 = histories15[scene, 'NK225']
            m15 = mirror_history15(h15, centers['NK225'])
            mirrored_base = mirror_orders(base, centers['NK225'])
            cases = [('overlay', config, None) for config in plan['configs']['overlay']]
            cases += [('episode', config, 5) for config in plan['configs']['episode']]
            cases += [('episode', dict(config, maximum=2, initial=min(config['initial'], 2)), 2) for config in plan['configs']['episode']]
            history_cache = {}
            for engine, config, size in cases:
                if engine == 'overlay':
                    orders, trace = overlay.replay(data, base, h15, config)
                    mirrored, mt = overlay.replay(reflected, mirrored_base, m15, config)
                    cap = 5
                else:
                    window = config['window']
                    if window not in history_cache:
                        history_cache[window] = shared.previous.first.original.history(data['ready']['time_s'], data['features'][:, 10], data['ready']['start'], window)
                    history = history_cache[window]
                    mh = mirror_history(history, centers['NK225'])
                    orders, trace = episode.replay(data, history, config)
                    mirrored, mt = episode.replay(reflected, mh, config)
                    cap = size
                cutoff = len(data['features'])//2
                if len(orders):
                    cutoff = max(cutoff, int(orders[0, 0])+1)
                assert cutoff < len(data['features'])
                altered = future_data(data, reflected, cutoff)
                if engine == 'overlay':
                    altered_history = h15.copy()
                    altered_history[cutoff:] = m15[cutoff:]
                    altered_base = base.copy()
                    future_fills = altered_base[:, 0] >= cutoff
                    future_rows = altered_base[future_fills, 0].astype(int)
                    future_sides = altered_base[future_fills, 3]
                    altered_base[future_fills, 5] = np.where(future_sides > 0,
                        altered['quotes']['ask'][future_rows], altered['quotes']['bid'][future_rows])
                    future, ft = overlay.replay(altered, altered_base, altered_history, config)
                    initial = {}
                    for order in base:
                        if order[7] and int(order[2]) not in initial:
                            initial[int(order[2])] = int(order[1])
                    removed = {parent for parent, first in initial.items() if first >= cutoff}
                    shortened = base[~np.isin(base[:, 2], list(removed))]
                    changed_notifications, _ = overlay.replay(data, shortened, h15, config)
                    assert_prefix(orders, changed_notifications, cutoff)
                    notification_count = len(base)-len(shortened)
                    if config['id'] == 'O00':
                        np.testing.assert_array_equal(orders, base)
                else:
                    altered_history = history.copy()
                    altered_history[cutoff:] = mh[cutoff:]
                    future, ft = episode.replay(altered, altered_history, config)
                    notification_count = None
                count = assert_prefix(orders, future, cutoff)
                np.testing.assert_array_equal(trace[trace[:, 0] < cutoff], ft[ft[:, 0] < cutoff])
                assert_mirror(orders, mirrored, centers['NK225'])
                normal_account = orders_account(orders, data, cap, scene)
                mirror_account = orders_account(mirrored, reflected, cap, scene)
                orders_account(future, altered, cap, scene)
                for key in ('net', 'profit', 'loss', 'holding_ratio'):
                    assert abs(normal_account[key]-mirror_account[key]) < 1e-6, (engine, config['id'], key)
                result['results'].append(dict(session=scene, engine=engine, method=config['id'], cap=cap,
                    orders=len(orders), prefix_orders=count, cutoff=cutoff, removed_future_notification_orders=notification_count,
                    future_unchanged=True, mirror_equal=True, next_bbo_fee_uid_cap_flat=True,
                    no_change_equal=config['id'] == 'O00'))
                print(scene, engine, config['id'], cap, '独立機械監査合格', flush=True)
        result['status'] = '全件合格'
        result['cases'] = len(result['results'])
        result['empty_order_cases'] = sum(row['orders'] == 0 for row in result['results'])
        result['empty_prefix_cases'] = sum(row['prefix_orders'] == 0 for row in result['results'])
        result['限界'] = '代理ラージBBO・価格時計の模型内検査。実miniの約定、受信時刻、未知場の収益性は証明しない。無注文の条件は非空の因果検査とは数えない。'
        save(target, result)
    except Exception:
        result['status'] = '失敗'
        result['error'] = traceback.format_exc()
        save(target, result)
        raise


def saved(registry, result_file):
    """
    機能: 第一巡の全保存注文を再会計し、各枠上限・費用・保有率を照合する。
    引数: registry/result_file(Path)は登録と保存結果。
    返り値: None。新しい売買判断は一切生成しない。
    """
    record, _ = registration(registry)
    import common143 as shared
    result = read(result_file)
    expected = {(row['session'], row['method']):row for row in result['rows']}
    cache = {row['session']:row for row in result['cache']}
    packets, _, _ = shared.material()
    checks = []
    for item in packets:
        scene = item['session']
        packet = shared.packet_from(item)
        key = (scene, 'NK225')
        data = dict(ready=packet['inputs'][key], quotes=packet['quotes'][key])
        item = cache[scene]
        path = ROOT/item['path']
        assert digest(path) == item['sha256']
        with np.load(path) as archive:
            for method in archive.files:
                cap = 3 if method == 'A3' else 2 if method.startswith('S') else 5 if method[0] in ('O', 'E', 'A', 'B') else 10
                account = orders_account(archive[method], data, cap, scene)
                row = expected[scene, method]
                for column in ('net', 'profit', 'loss', 'holding_ratio'):
                    assert abs(account[column]-row[column]) < 1e-7, (scene, method, column)
                checks.append(dict(session=scene, method=method, cap=cap, orders=account['orders'],
                    会計一致=True, 保有率一致=True, next_bbo_fee_uid_cap_flat=True))
            f1, f00 = archive['F1'], archive['F00']
            a1 = orders_account(f1, data, 10, scene)
            a0 = orders_account(f00, data, 10, scene)
            for column in ('net', 'profit', 'loss', 'holding_ratio'):
                assert abs(a1[column]-a0[column]) < 1e-7, (scene, 'F00無変更', column)
        print(scene, '保存全条件の独立会計合格', flush=True)
    save(HERE/'第一巡保存全注文の独立監査143.json', dict(登録=record, 新金融再生=0,
        status='全件合格', 件数=len(checks), 注文数=sum(row['orders'] for row in checks), results=checks,
        account_unit='新規・追加・部分返済の全費用を含む完結親の収支',
        無変更F00とF1全場会計保有率一致=True, script_sha256=digest(Path(__file__))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('baseline', 'mechanics', 'saved'))
    parser.add_argument('--registration', type=Path, default=HERE/'第一巡登録143.json')
    parser.add_argument('--results', type=Path, default=HERE/'第一巡結果143.json')
    args = parser.parse_args()
    if args.stage == 'baseline':
        baseline()
    elif args.stage == 'mechanics':
        mechanics(args.registration)
    else:
        saved(args.registration, args.results)
