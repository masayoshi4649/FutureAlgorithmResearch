"""日経限定研究の入力参照、独立枠の接続、深夜除外の評価を共通化する。"""

import json
import pickle
import sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT / 'work/conditional142_20261024'
sys.path.insert(0, str(OLD))
import run142 as previous

prior = previous.prior


def read(path):
    """
    機能: 日本語の研究JSONを読み取る。
    引数: path(Path又はstr)は入力ファイル。
    返り値: dict又はlistは保存内容。
    """
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    """
    機能: 研究資料をUTF-8で保存し、非有限値の混入を拒否する。
    引数: path(Path又はstr)、value(dict又はlist)は出力先と内容。
    返り値: None。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def material():
    """
    機能: 同じ50場の原入力と、日経の保存F1・基本枠を指紋付きで参照する。
    引数: なし。
    返り値: tuple[list,dict,dict]は原入力目録、142注文目録、事後方向の評価資料。
    """
    packets, _, _ = previous.first.material()
    origin = read(OLD / '結果142.json')
    cache = {(x['session'], x['symbol']): x for x in origin['cache']}
    labels = {x['session']: x for x in read(HERE / 'F1始終値方向と深夜除外保有率143.json')['sessions']}
    assert len(packets) == len(labels) == 50
    return packets, cache, labels


def packet_from(item):
    """
    機能: 指紋の一致した原入力だけを開く。
    引数: item(dict)は既存の入力目録。
    返り値: dictは原行と時刻・公開指標を保持する一場の資料。
    """
    path = Path(item['path'])
    if not path.is_absolute():
        path = ROOT / path
    assert prior.ref(path)['sha256'] == item['sha256']
    return pickle.loads(path.read_bytes())


def sources(scene, cache):
    """
    機能: 保存F1を基本枠と追加枠へ分離する。採用済みの全親を保持する。
    引数: scene(str)、cache(dict)はセッションと注文目録。
    返り値: tuple[ndarray,ndarray,ndarray]は基本、追加、元F1の十列注文。
    """
    arrays = previous.first.load_arrays(cache[scene, 'NK225'])
    base = arrays['B5' if scene.endswith('_Day') else 'Z04']
    f1 = arrays['M1' if scene.endswith('_Day') else 'J04']
    keep = np.isin(f1[:, 2], np.unique(base[:, 2])) if len(base) else np.zeros(len(f1), bool)
    assert np.array_equal(f1[keep], base)
    return base.copy(), f1[~keep].copy(), f1.copy()


def merge(*sleeves):
    """
    機能: 事前に分けた独立数量枠を、親ID衝突なしで同時運用として合成する。
    引数: sleeves(tuple[ndarray])は各枠の時刻順十列注文。共同上限は別に監査する。
    返り値: ndarrayは全約定行。空き枠の貸借や事後の採否選択を行わない。
    """
    blocks = []
    for sleeve, orders in enumerate(sleeves):
        if not len(orders):
            continue
        copied = orders.copy()
        assert np.max(copied[:, 2]) < 10_000_000
        copied[:, 2] += sleeve * 10_000_000
        blocks.append(copied)
    result = np.concatenate(blocks) if blocks else np.empty((0, 10))
    return result[np.argsort(result[:, 0], kind='stable')] if len(result) else result


def holding(orders, ready):
    """
    機能: 03～06時を除く実保有率と、平均保有枚数・全時間率を積分する。
    引数: orders(ndarray)、ready(dict)は約定と公式開始・原価格時計。
    返り値: dictは場の保有時間・率・平均数量。両建ては相殺しない。
    """
    start = float(ready['start'])
    day = ready['session'].endswith('_Day')
    duration = (420 if day else 600) * 60.
    full_duration = (420 if day else 780) * 60.
    count = 0
    last = start
    active = quantity_seconds = full_active = 0.
    for row in orders:
        now = float(ready['time_s'][int(row[0])])
        assert now >= last
        eligible = max(0., min(now, start + duration) - max(last, start))
        entire = max(0., min(now, start + full_duration) - max(last, start))
        if count:
            active += eligible
            full_active += entire
        quantity_seconds += count * eligible
        count += int(row[4]) if row[7] else -int(row[4])
        assert count >= 0
        last = now
    assert count == 0
    return dict(evaluation_minutes=duration / 60., held_minutes_excluding_03_06=active / 60., held_minutes=full_active / 60.,
                holding_ratio=active / duration, average_quantity=quantity_seconds / duration,
                full_holding_ratio=full_active / full_duration)


def account(orders, packet, method, label):
    """
    機能: 全注文を元会計で計上し、終了後だけ始終値分類を評価列へ接続する。
    引数: orders(ndarray)、packet(dict)、method(str)、label(dict)は注文と事後評価資料。
    返り値: dictは一場の全損益・深夜除外率・分類。終値を売買関数へ渡さない。
    """
    scene = packet['session']
    ready = packet['inputs'][scene, 'NK225']
    quotes = packet['quotes'][scene, 'NK225']
    result = prior.common.account(orders, ready['time_s'], quotes, method, scene, 'NK225')
    parents = result.pop('parents')
    result['parent_count'] = len(parents)
    result['parent_records'] = [{k: v for k, v in p.items() if k != 'legs'} for p in parents]
    result['buy_sell'] = {}
    for side, name in ((1, '買い'), (-1, '売り')):
        chosen = [p for p in parents if p['side'] == side]
        result['buy_sell'][name] = dict(parents=len(chosen), profit=sum(p['net'] for p in chosen if p['net'] > 0.),
                                        loss=-sum(p['net'] for p in chosen if p['net'] < 0.), net=sum(p['net'] for p in chosen))
    entries = orders[orders[:, 7] == 1]
    result['first_minutes'] = float((ready['time_s'][int(entries[0, 0])] - ready['start']) / 60.) if len(entries) else None
    result['split'] = '既知開発50場'
    index = orders[:, 0].astype(int)
    mid = (quotes['bid'][index] + quotes['ask'][index]) * .5
    result['midpoint_gross'] = float(np.sum(-orders[:, 3] * orders[:, 4] * mid * 100.))
    result['bbo_drag'] = result['midpoint_gross'] - result['gross']
    result.update(holding(orders, ready))
    result.update(direction=label['direction'], opening=label['first_price'], closing=label['final_price'],
                  market_change=label['change'], close_time=label['final_price_time'], close_basis=label['basis'])
    return result
