"""完成数量coreだけを私有複製し、独立純参照と直接価格走査へ接続する。"""

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import traceback

import numpy as np

import episode_reference_v3 as reference


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = BASE.parents[1]
PROOF = HERE / '完成数量coreと独立episode及び価格先着のSOURCE_ONLY接続_v2.json'
ENGINE_SHA = 'bebbd28aa1916199a4e8cbba777d0b29d8d0c9538bb9817512c6760104b5045d'
checks, prefixes, arrays_checked = 0, 0, 0


def check(value: bool, detail: object) -> None:
    """
    機能: 独立条件の成立数を数え、不成立なら停止する。
    引数: value(bool)は検査結果、detail(object)は根拠。
    返り値: None。
    """
    global checks
    checks += 1
    assert value, detail


def equal_array(actual: np.ndarray, expected: np.ndarray, detail: object) -> None:
    """
    機能: 同型配列をNaN位置も含めて比較する。
    引数: actual/expected(ndarray)、detail(object)は比較値と根拠。
    返り値: None。
    """
    global arrays_checked
    check(actual.shape == expected.shape, (detail, 'shape'))
    check(np.array_equal(actual, expected, equal_nan=True), (detail, actual, expected))
    arrays_checked += 1


def materialize(rows: list[reference.Observation]) -> dict:
    """
    機能: 先に固定した純素材を必要12列の合成配列にする。
    引数: rows(list[Observation])は独立期待素材。
    返り値: dict[str,ndarray]は合成入力。保存NPZを読まない。
    """
    n = len(rows)
    return dict(raw_seq=np.arange(n, dtype=np.int64), price_time_s=np.full(n, 100.),
        last=np.array([row.last for row in rows], float), bid=np.array([row.bid for row in rows], float),
        ask=np.array([row.ask for row in rows], float), bid_qty=np.array([row.bid_q for row in rows], float),
        ask_qty=np.array([row.ask_q for row in rows], float), best_quantity_valid=np.ones(n, bool),
        volume_delta_known=np.array([row.volume_known for row in rows], bool),
        volume_delta_observed=np.array([row.delta for row in rows], float), volume_time_s=np.full(n, 101.),
        price_reset_reason=np.array([0 if row.price_known else 8 for row in rows], np.int64))


def masks(a: dict, start: float = 0, end: float = 1000) -> tuple:
    """
    機能: 根のfield契約を行別の集合述語で独立に評価する。
    引数: a(dict[str,ndarray])は合成列、start/end(float)は観測窓。
    返り値: tupleは価格reason、公開reason、数量既知、出来高既知。
    """
    n = len(a['raw_seq'])
    price, public, qty, vol = [], [], [], []
    for i in range(n):
        pt, b, ask = a['price_time_s'][i], a['bid'][i], a['ask'][i]
        reason = sum(bit for bit, failed in (
            (1, not math.isfinite(pt)), (2, math.isfinite(pt) and not start <= pt < end),
            (4, not (math.isfinite(b) and math.isfinite(ask) and 0 < b < ask)),
            (8, i > 0 and a['raw_seq'][i] != a['raw_seq'][i - 1] + 1),
            (16, i > 0 and not math.isfinite(a['price_time_s'][i - 1])),
            (32, bool(a['price_reset_reason'][i] & 8) or (i > 0 and math.isfinite(pt) and math.isfinite(a['price_time_s'][i - 1]) and pt < a['price_time_s'][i - 1]))) if failed)
        q = bool(a['best_quantity_valid'][i] and all(math.isfinite(a[name][i]) and a[name][i] > 0 for name in ('bid_qty', 'ask_qty')))
        observed = math.isfinite(a['volume_delta_observed'][i]) and a['volume_delta_observed'][i] >= 0
        v = bool(a['volume_delta_known'][i] and observed)
        price.append(reason)
        public.append(reason + (0 if q else 64) + (0 if a['volume_delta_known'][i] else 128) + (0 if observed else 256))
        qty.append(q)
        vol.append(v)
    return np.array(price, np.uint16), np.array(public, np.uint16), np.array(qty, bool), np.array(vol, bool)


def observations(a: dict, price: np.ndarray, qty: np.ndarray, vol: np.ndarray) -> list:
    """
    機能: 独立資格を純episode参照の行へ結ぶ。
    引数: a(dict)、price/qty/vol(ndarray)は合成列と独立資格。
    返り値: list[Observation]は当時行。未来値は参照しない。
    """
    rows = []
    for i in range(len(price)):
        rows.append(reference.Observation(bid=a['bid'][i], ask=a['ask'][i],
            bid_q=a['bid_qty'][i] if qty[i] else float('nan'), ask_q=a['ask_qty'][i],
            delta=a['volume_delta_observed'][i], last=a['last'][i], price_known=price[i] == 0,
            volume_known=bool(vol[i]), fresh_price=i > 0 and math.isfinite(a['price_time_s'][i - 1]) and a['price_time_s'][i] > a['price_time_s'][i - 1]))
    return rows


def naive_outcome(a: dict, public: int, side: int, tick: float, valid: np.ndarray) -> tuple:
    """
    機能: 区間木を使わず各後続行を直接走査して両BBOの初先着を調べる。
    引数: a(dict)、public/side(int)、tick(float)、valid(ndarray[bool])は合成列と起点。
    返り値: tuple[int,int]は先着codeと終点行。公開当行は走査しない。
    """
    b0, a0 = a['bid'][public], a['ask'][public]
    for i in range(public + 1, len(valid)):
        if not valid[i]:
            return 0, i
        direction = [side * (a[name][i] - origin) for name, origin in (('bid', b0), ('ask', a0))]
        if min(direction) >= tick:
            return 1, i
        if max(direction) <= -tick:
            return -1, i
    return 2, len(valid) - 1


def inspect(engine: object, a: dict, label: str) -> dict:
    """
    機能: 一合成入力を資格、全31公開欄、直接先着と不変性へ照合する。
    引数: engine(object)は新私有core、a(dict)は合成列、label(str)は根拠。
    返り値: dictはcore結果。金融や保存入力は呼ばない。
    """
    original = {key: value.copy() for key, value in a.items()}
    result = engine.measure(a, 0, 1000, 1)
    price, public, qty, vol = masks(a)
    equal_array(result['price_reason_mask'], price, (label, '価格理由'))
    equal_array(result['publication_reason_mask'], public, (label, '公開理由'))
    equal_array(result['price_valid_mask'], price == 0, (label, '価格資格'))
    for key in a:
        equal_array(a[key], original[key], (label, '入力不変更', key))
    expected = reference.events(observations(a, price, qty, vol))
    fields, events = result['fields'], result['events']
    check(events.shape == (len(expected), 31), (label, 'event件数'))
    starts = sorted(set([event['start'] for event in expected]))
    episode_ids = {}
    for actual, target in zip(events, expected):
        event = dict(zip(fields, actual))
        start, pub, side = target['start'], target['publication'], target['side']
        episode_ids.setdefault(start, event['episode'])
        check(episode_ids[start] == event['episode'], (label, 'episode対応'))
        direct = dict(type=target['type'], start_i=start, pub_i=pub, d=side, bid=target['bid'], ask=target['ask'],
            bid_q0=a['bid_qty'][start], ask_q0=a['ask_qty'][start], bid_q_at_public=a['bid_qty'][pub], ask_q_at_public=a['ask_qty'][pub],
            min_bid_q=min(a['bid_qty'][start:pub + 1]), min_ask_q=min(a['ask_qty'][start:pub + 1]),
            opposite_q0=target['q0'], opposite_q_at_public=target['qstar'],
            opposite_min_q=min(a['ask_qty' if side > 0 else 'bid_qty'][start:pub + 1]),
            quantity_ratio=target['ratio'], quantity_group=int(target['group'] == '維持/回復'), total_volume=target['activity'],
            npositive=sum(a['volume_delta_observed'][i] > 0 for i in range(start + 1, pub + 1)),
            fresh_price_time=int(target['fresh_price']), volume_after_price=int(math.isfinite(a['volume_time_s'][pub]) and a['volume_time_s'][pub] > a['price_time_s'][pub]),
            volume_clock_known=int(math.isfinite(a['volume_time_s'][pub])), start_raw_seq=a['raw_seq'][start],
            pub_raw_seq=a['raw_seq'][pub], pub_price_time_s=a['price_time_s'][pub])
        first = next(i for i in range(start + 1, pub + 1) if a['volume_delta_observed'][i] > 0)
        direct.update(first_positive_i=first,
            first_positive_fresh_price_time=int(a['price_time_s'][first] > a['price_time_s'][first - 1]),
            first_positive_volume_after_price=int(math.isfinite(a['volume_time_s'][first]) and a['volume_time_s'][first] > a['price_time_s'][first]),
            first_positive_volume_clock_known=int(math.isfinite(a['volume_time_s'][first])))
        direct['minimum_quantity_ratio'] = direct['opposite_min_q'] / direct['opposite_q0']
        check(set(direct) | {'episode'} == set(fields), (label, '全31欄を検査'))
        for key, value in direct.items():
            check(math.isclose(event[key], value, abs_tol=1e-10, rel_tol=1e-12), (label, key, event[key], value))
    expected_outcomes = np.array([naive_outcome(a, int(event[fields.index('pub_i')]), int(event[fields.index('d')]), 1, price == 0) for event in events], dtype=float).reshape(-1, 2)
    equal_array(result['outcomes'], expected_outcomes, (label, '直接先着'))
    check(result['counts']['type0_events'] == sum(target['type'] == 0 for target in expected), 'type0分母')
    check(result['counts']['type1_events'] == sum(target['type'] == 1 for target in expected), 'type1分母')
    check(result['counts']['raw_rows'] == len(price), '原行分母')
    check(result['counts']['price_known_rows'] == sum(price == 0), '価格既知分母')
    check(result['counts']['price_unknown_rows'] == sum(price != 0), '価格不明分母')
    check(result['counts']['quantity_unknown_rows'] == sum(~qty), '数量不明分母')
    check(result['counts']['volume_unknown_rows'] == sum(~vol), '出来高不明分母')
    check(result['counts']['publication_eligible_rows'] == sum(public == 0), '公開資格分母')
    for type1 in [event for event in expected if event['type'] == 1]:
        pair = [i for i, target in enumerate(expected) if target['start'] == type1['start']]
        check(len(pair) == 2, '同達成episodeは各type一回')
        equal_array(result['outcomes'][pair[0]], result['outcomes'][pair[1]], '達成集合のtype0/type1同値')
    return result


def main() -> None:
    """
    機能: 完成sourceを新所有域へ複製し、純素材と全接頭の接続を保存する。
    引数: なし。
    返り値: None。NPZ/cache/元金融/APIは一切読まない。
    """
    global prefixes
    assert not PROOF.exists()
    try:
        source = BASE / 'engine.py'
        raw = source.read_bytes()
        check(hashlib.sha256(raw).hexdigest() == ENGINE_SHA, '完成core指紋')
        snapshot = HERE / '完成core通常import私有複製'
        snapshot.mkdir(exist_ok=False)
        copied = snapshot / 'engine.py'
        copied.write_bytes(raw)
        sys.path.insert(0, str(snapshot))
        import importlib
        engine = importlib.import_module('engine')
        check(Path(engine.__file__).resolve() == copied.resolve(), '新私有通常moduleだけimport')
        datasets = {name: materialize(rows) for name, (rows, _) in reference.fixtures().items()}
        base = materialize([reference.Observation(delta=0), reference.Observation(delta=10),
            reference.Observation(bid=101, ask=102, last=102), reference.Observation(bid=99, ask=100, last=100)])
        for name, key, index, value in (
            ('公開後Qty不明でも価格先着', 'best_quantity_valid', 2, False), ('公開後Volume不明でも価格先着', 'volume_delta_known', 2, False),
            ('公開後価格不明は先着を打切', 'price_reset_reason', 2, 8), ('lockedBBOは不正', 'ask', 2, 101),
            ('価格時計が非有限', 'price_time_s', 2, float('nan')), ('価格時計逆行', 'price_time_s', 2, 99),
            ('seq断裂', 'raw_seq', 2, 8), ('観測窓終了', 'price_time_s', 2, 1000),
            ('初行価格時計欠測の次も未知', 'price_time_s', 0, float('nan')), ('当行数量flag不明', 'best_quantity_valid', 1, False),
            ('当行Vflag不明', 'volume_delta_known', 1, False), ('当行Vobserved欠測', 'volume_delta_observed', 1, float('nan')),
            ('当行Vobserved負', 'volume_delta_observed', 1, -1), ('volume時計非有限でも既知delta', 'volume_time_s', 1, float('nan')),
            ('価格時計fresh', 'price_time_s', 1, 101)):
            data = {key_: values.copy() for key_, values in base.items()}
            data[key][index] = value
            datasets[name] = data
        summaries = {}
        for name, data in datasets.items():
            result = inspect(engine, data, name)
            for stop in range(1, len(data['raw_seq']) + 1):
                prefix = {key: value[:stop].copy() for key, value in data.items()}
                cut = inspect(engine, prefix, name + '/prefix' + str(stop))
                mask = result['events'][:, result['fields'].index('pub_i')] < stop
                equal_array(cut['events'], result['events'][mask], (name, '未来公開特徴を混ぜない'))
                prefixes += 1
            summaries[name] = dict(n=len(result['events']), outcomes=result['outcomes'].tolist())
        for name, change in (
            ('負原seq拒否', lambda a: a['raw_seq'].__setitem__(0, -1)),
            ('厳密表現不能原seq拒否', lambda a: a['raw_seq'].__setitem__(0, 2**53)),
            ('公開後累計overflow拒否', lambda a: a['volume_delta_observed'].__setitem__(slice(1, 3), 1e308)),
            ('数量比overflow拒否', lambda a: (a['ask_qty'].__setitem__(0, 1e-308), a['ask_qty'].__setitem__(1, 1e308)))):
            data = {key: value.copy() for key, value in base.items()}
            if name == '公開後累計overflow拒否':
                data['bid'][:] = 100
                data['ask'][:] = 101
            change(data)
            refused = False
            try:
                engine.measure(data, 0, 1000, 1)
            except AssertionError:
                refused = True
            check(refused, name)
        artifact_path = BASE / '固定BBO数量と公表活動及び価格先着の人工検査.json'
        artifact = json.loads(artifact_path.read_bytes())
        check(artifact['全合格'] and artifact['source_SHA256']['engine.py'] == ENGINE_SHA, 'owner人工へのsource結合')
        check(hashlib.sha256(source.read_bytes()).hexdigest() == ENGINE_SHA, '完成core不変更')
        result = dict(全合格=True, 検査数=checks, 配列照合=arrays_checked, 接頭数=prefixes, 合成素材=len(datasets),
            source_SHA256={'engine.py': ENGINE_SHA}, owner人工SHA256=hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
            独立純参照SHA256=hashlib.sha256(Path(reference.__file__).read_bytes()).hexdigest(), 素材要約=summaries,
            初版訂正='file-spec私有moduleの再帰JIT接続でunresolved symbol。初版False/sourceを保全し、根指定のsys.path先頭から通常module importだけへ訂正。元source変更なし。',
            scope='完成coreだけの独立接続。runner/正式freeze/登録/実データは別段階。原raw配列でなく合成必要12列を使用。',
            未測=['実数量本体と観測確率', '金融・約定・費用・心理・真攻撃・補充', 'runner全5sourceと正式登録の実接続'],
            private_source=str(copied.relative_to(ROOT)), NPZ=0, cache=0, 原板=0, 原金融=0, API=0, 新金融=0,
            監査sourceSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    except Exception as error:
        result = dict(全合格=False, 検査数=checks, 理由=str(error), traceback=traceback.format_exc(),
            NPZ=0, cache=0, 原板=0, 原金融=0, API=0, 新金融=0)
        PROOF.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        raise
    PROOF.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査数=checks, 配列照合=arrays_checked, 接頭数=prefixes,
                         SHA256=hashlib.sha256(PROOF.read_bytes()).hexdigest()), ensure_ascii=False))


if __name__ == '__main__':
    main()
