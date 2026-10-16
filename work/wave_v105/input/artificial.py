"""純人工で当時特徴・整数系譜・旧幅式・同時計往復の保存を検査する。"""

import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import traceback

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
COUNTS = {}
for _name, _path in (('core', HERE/'core.py'), ('data', HERE/'data.py'),
                    ('prices', ROOT/'work/wave_v104/peer/prices.py'),
                    ('oldcore', ROOT/'work/wave_v104/peer/core.py')):
    _identifier = '105入力人工専用'+_name
    _specification = importlib.util.spec_from_file_location(_identifier, _path)
    _module = importlib.util.module_from_spec(_specification)
    sys.modules[_identifier] = _module
    _specification.loader.exec_module(_module)
    globals()[_name] = _module
POLICY = dict(max_public_gap_seconds=15., baseline_extra_age_seconds=15.,
    spread_max_ticks=2., spread_increment_ticks=1.)


def check(name: str, condition: bool) -> None:
    """
    機能: 純人工の期待を確認し、日本語の検査件数を保存する。
    引数: name(str)、condition(bool)は項目と成立条件。
    返り値: None。不成立でAssertionErrorを送出する。
    """
    assert condition, name
    COUNTS[name] = COUNTS.get(name, 0)+1


def equal(left: object, right: object) -> bool:
    """
    機能: 人工入力の辞書・配列をNaNと型も含めて再帰比較する。
    引数: left/right(object)は比較対象。
    返り値: boolは同値かどうか。seqは整数のまま検算する。
    """
    if isinstance(left, np.ndarray):
        return isinstance(right, np.ndarray) and left.dtype == right.dtype and np.array_equal(left, right, equal_nan=True)
    if isinstance(left, dict):
        return isinstance(right, dict) and set(left) == set(right) and all(equal(value, right[name]) for name, value in left.items())
    if isinstance(left, (list, tuple)):
        return isinstance(right, type(left)) and len(left) == len(right) and all(equal(a, b) for a, b in zip(left, right))
    if isinstance(left, float) and np.isnan(left):
        return isinstance(right, float) and np.isnan(right)
    return left == right


def fixture(walk: np.ndarray | None = None, times: np.ndarray | None = None,
            candidate_row: int = 44, side: int = 1, tick: float = .5,
            mutation: str = '') -> dict:
    """
    機能: 既存104接口と同shapeの小人工packetを作る。
    引数: walk/times(ndarray|None)、candidate_row/side(int)、tick(float)、mutation(str)。
    返り値: dictは2商品正常列・三入口・公開窓。原本又は正式packetは読まない。
    """
    length = 65 if times is None else len(times)
    times = 1000.+np.arange(length, dtype=float) if times is None else times.copy()
    walk = np.arange(length, dtype=float) if walk is None else walk.copy()
    assert len(walk) == length
    packet = dict(schema_version=1, session='人工', raw={}, normal={}, items={},
        peer_features={}, cases={entry: {} for entry in core.ENTRIES}, policy=POLICY)
    for symbol in core.SYMBOLS:
        stamp = times.copy()-(.25 if symbol == 'NK225' and mutation != 'peer_equal' else 0.)
        if mutation == 'peer_stale' and symbol == 'NK225':
            stamp[21:] = stamp[20]
        bid = (1000.+side*walk)*tick
        ask = bid+tick
        seq = np.arange(length, dtype=np.int64)+9007199254740993
        quote_ok, qualified = np.ones(length, bool), np.ones(length, bool)
        price_reset = np.zeros(length, np.uint16)
        if mutation == 'seq':
            seq[30:] += 2
            qualified[30] = False
        if mutation == 'reset':
            price_reset[30] = 8
            qualified[30] = False
        if mutation == 'quote':
            quote_ok[30] = False
        if mutation == 'quantity':
            qualified[30] = False
        if mutation == 'spread':
            ask[44] += 3*tick
        if mutation == 'opposite_sign':
            ask[44] -= 8*tick
            bid[44] -= 12*tick
            assert ask[44] > bid[44]
        mapping = np.arange(length, dtype=np.int64)
        if mutation == 'unmapped':
            mapping = mapping[mapping != candidate_row]
            bid[candidate_row] = ask[candidate_row] = np.nan
        reverse = np.full(length, -1, np.int32)
        reverse[mapping] = np.arange(len(mapping), dtype=np.int32)
        finite = np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask > bid)
        raw = dict(raw_seq=seq, price_time_s=stamp, bid=bid, ask=ask,
            bbo_valid=finite & quote_ok, qualified=qualified,
            entry_reset=price_reset != 0, price_reset_reason=price_reset,
            normal_execution_row=reverse, execution_to_raw_index=mapping)
        record = dict(session='人工', symbol=symbol, seq=seq[mapping].copy(), time_s=stamp[mapping].copy(),
            price=((bid+ask)/2.)[mapping].copy(), bid=bid[mapping].copy(), ask=ask[mapping].copy(),
            quote_valid=quote_ok[mapping].copy(), price_valid=np.ones(len(mapping), bool),
            source_i=mapping.copy(), start=1000., end=1100., limit=1090., tick=tick)
        packet['raw'][symbol], packet['normal'][symbol] = raw, dict(record=record)
        packet['items'][symbol] = dict(tick=tick)
        packet['peer_features'][symbol] = prices.build(raw, dict(tick=tick), oldcore.publications(raw), POLICY)
        support = float(bid[candidate_row]-side*tick) if mutation != 'unmapped' else 999.*tick
        normal_row = None if reverse[candidate_row] < 0 else int(reverse[candidate_row])
        roots = [dict(family='C', anchor_raw_seq=int(seq[2]), support_price=support),
                 dict(family='R', anchor_raw_seq=int(seq[4]), support_price=support)]
        for entry in core.ENTRIES:
            accepted = entry != 'C_N30'
            candidate = dict(row=candidate_row, raw_row=candidate_row, normal_row=normal_row,
                raw_seq=int(seq[candidate_row]), price_time_s=float(stamp[candidate_row]),
                side=side, entry_id=entry, support_price=support, accepted=accepted,
                selected_support_roots=deepcopy(roots), self_lineages=deepcopy(roots))
            event, supports = np.zeros(len(mapping), np.int8), np.full(len(mapping), np.nan)
            decisions = []
            if accepted and normal_row is not None:
                event[normal_row], supports[normal_row] = side, support
                decision = deepcopy(candidate)
                decision['row'] = normal_row
                decisions.append(decision)
            normal = dict(entry_id=entry, execution_to_raw_index=mapping,
                event=event, support_price=supports, decisions=decisions,
                entry_quality=(qualified & raw['bbo_valid'])[mapping].copy(), entry_reset=raw['entry_reset'][mapping].copy())
            packet['cases'][entry][symbol] = dict(normal=normal, candidates=[candidate])
    return packet


def refs(packet: dict) -> dict:
    """
    機能: 人工初回までに既知のref_openを作る。
    引数: packet(dict)は小人工入力。
    返り値: dictは商品別の保存始値。正式metadata又は金融値は読まない。
    """
    return {symbol: dict(value=1000.*record['tick'], known_from_i=0,
        source_seq=int(record['seq'][0]), source_time=float(record['time_s'][0]),
        reference_time=float(record['time_s'][0]))
        for symbol in core.SYMBOLS for record in [packet['normal'][symbol]['record']]}


def oracle(midpoint: np.ndarray, side: int, tick: float) -> tuple[float, float, float]:
    """
    機能: 公表窓とは独立な二重ループでD/TV/過去最大逆行を計算する。
    引数: midpoint(ndarray[float])、side(int)、tick(float)は人工経路。
    返り値: tuple[float,float,float]は方向付きD、TV、N。
    """
    net = side*(float(midpoint[-1])-float(midpoint[0]))/tick
    variation = sum(abs(float(midpoint[i])-float(midpoint[i-1]))/tick for i in range(1, len(midpoint)))
    adverse = max(side*(float(midpoint[i])-float(midpoint[j]))/tick
        for i in range(len(midpoint)) for j in range(i, len(midpoint)))
    return net, variation, adverse


def old_width_checks() -> None:
    """
    機能: 金融をimportせず旧90.prepare関数そのものと固定G0の幅を人工照合する。
    引数: なし。
    返り値: None。旧関数の周辺状態は小人工stub、幅計算の本体は原sourceそのまま。
    """
    source_path = ROOT/'work/wave_v90/strategy.py'
    tree = ast.parse(source_path.read_text(encoding='utf-8'))
    original = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'prepare')
    namespace = dict(np=np, math=math,
        state=lambda grid, entry, config: dict(grid=grid['grid']),
        mapping=lambda grid, record: np.zeros(len(record['time_s']), np.int32))
    exec(compile(ast.Module(body=[original], type_ignores=[]), str(source_path), 'exec'), namespace)
    path = ROOT/'work/wave_v102/catalog.py'
    spec = importlib.util.spec_from_file_location('105人工の固定G0数値だけ', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = next(value for value in module.catalog() if value['id'] == 'G0_Q1_X1')
    check('固定G0の幅係数は004', config['trend_width_fraction'] == core.TREND_WIDTH_FRACTION)
    for tick in (.5, 10., 1.):
        for reference in (1., 1000., 4071.5, 68880., 1000.+1e-8):
            record = dict(tick=tick, time_s=np.array([1.]))
            key = ('人工', 'TOPIX')
            material = dict(grids={'人工': dict(grid=np.array([1.]))},
                entries={'人工': dict(entries={'J2': dict(long_allowed=np.ones(1, bool), short_allowed=np.ones(1, bool))})},
                prices={key: record}, legacy={key: dict(candidates=[])},
                features={key: dict(quality=np.ones(1, bool), reset=np.zeros(1, bool))},
                metadata=dict(references={'|'.join(key): dict(ref_open=dict(known_from_i=0, value=reference))}))
            actual = namespace['prepare'](material, config)[key]['signal']['trend_width']
            check('旧prepare本体の幅と人工同値', actual == core.trend_width(reference, tick))


def run() -> dict:
    """
    機能: 人工の採否不変・未来不変・公開時計と実候補区別を検査する。
    引数: なし。
    返り値: dictは金融前の人工証跡。正式packet・原本・利益ラベル読取は0。
    """
    old_width_checks()
    for tick in (.5, 10.):
        for side in (-1, 1):
            packet = fixture(side=side, tick=tick)
            before = deepcopy(packet)
            built = core.build_session(packet, refs(packet))
            check('入力packet変更なし', equal(before, packet))
            for entry in core.ENTRIES:
                for symbol in core.SYMBOLS:
                    original = packet['cases'][entry][symbol]['normal']
                    current = built['cases'][entry][symbol]
                    check('旧normal入口の全字段一致', all(equal(value, current[name]) for name, value in original.items()))
                    check('正常record全列一致', equal(built['prepared'][symbol]['record'], packet['normal'][symbol]['record']))
                    values = built['features'][entry][symbol][44]
                    check('旧拒否候補は復活しない', values['accepted_104'] == (entry != 'C_N30'))
                    check('支持系譜整数一致', equal(values['selected_support_roots'], packet['cases'][entry][symbol]['candidates'][0]['selected_support_roots']))
                    anchors = current['selected_support_anchor_min_raw_seq']
                    check('2の53乗超の最低anchor整数一致', anchors[44] == 9007199254740995 if entry != 'C_N30' else np.all(anchors == -1))
                    for role in ('own', 'own_normal', 'peer'):
                        for window in ('10', '30'):
                            measured = values[role][window]
                            mids = measured['path_source']['midpoint']
                            d, tv, n = oracle(mids, side, tick)
                            check('DTVN独立二重ループ一致', measured['known'] and
                                measured['directional_net_ticks'] == d and measured['total_variation_ticks'] == tv and measured['max_adverse_ticks'] == n)
                            check('順行の方向付きetaは1', measured['efficiency'] == 1.)
                    check('相手はstrictpastかつ15秒内', values['peer']['10']['public_endpoint']['price_time_s'] < values['price_time_s']
                        and 0 < values['peer']['10']['age_seconds'] <= 15)
    # ----------------------------------------
    walk = np.zeros(65)
    packet = fixture(walk=walk)
    built = core.build_session(packet, refs(packet))
    for role in ('own', 'own_normal', 'peer'):
        value = built['features']['C_OWN']['TOPIX'][44][role]['10']
        check('既知TV0とUNKNOWNを区別', value['known'] and value['zero_variation'] and value['total_variation_ticks'] == 0. and value['efficiency'] is None)
    packet = fixture(walk=-np.arange(65, dtype=float))
    value = core.build_session(packet, refs(packet))['features']['C_OWN']['TOPIX'][44]
    check('逆行etaを絶対値で救済しない', value['own_normal']['10']['efficiency'] == -1.)
    # ----------------------------------------
    times = 1000.+np.arange(65, dtype=float)
    times[43] = times[42]
    walk = np.arange(65, dtype=float)
    walk[43] = walk[42]+10.
    packet = fixture(walk=walk, times=times, candidate_row=43)
    value = core.build_session(packet, refs(packet))['features']['C_OWN']['TOPIX'][43]
    check('同時計公表終点と実候補BBOを分離', value['own']['10']['public_endpoint']['raw_row'] == 42 and value['current']['raw_row'] == 43
        and value['own']['10']['public_endpoint']['bid'] != value['current']['bid'])
    check('全normalは同時計後半も含む', value['own_normal']['10']['path_source']['raw_seq'][-1] == packet['raw']['TOPIX']['raw_seq'][43])
    times = 1000.+np.arange(65, dtype=float)
    times[41:44] = times[40]
    walk = np.arange(65, dtype=float)
    walk[41], walk[42], walk[43] = 45., 35., 41.
    packet = fixture(walk=walk, times=times, candidate_row=43)
    value = core.build_session(packet, refs(packet))['features']['C_OWN']['TOPIX'][43]
    check('同時計往復が公開TVから落ちる差を保存', value['own_normal']['10']['total_variation_ticks'] > value['own']['10']['total_variation_ticks']
        and value['own_normal']['10']['max_adverse_ticks'] == 10.)
    check('同時計往復で自己効率は公開効率より低い', value['own_normal']['10']['efficiency'] < value['own']['10']['efficiency'])
    # ----------------------------------------
    for mutation in ('seq', 'reset', 'quote'):
        packet = fixture(mutation=mutation)
        value = core.build_session(packet, refs(packet))['features']['C_OWN']['TOPIX'][44]
        for role in ('own', 'own_normal', 'peer'):
            check('途中不正はUNKNOWNで数値補完なし', not value[role]['30']['known'] and value[role]['30']['efficiency'] is None)
    packet = fixture(mutation='quantity')
    value = core.build_session(packet, refs(packet))['features']['C_OWN']['TOPIX'][44]
    check('中間数量不明と正常BBOを混同しない', value['own_normal']['30']['known'])
    packet = fixture(mutation='spread')
    value = core.build_session(packet, refs(packet))['features']['C_OWN']['TOPIX'][44]
    check('spread曖昧を既知支持にしない', value['own']['10']['observed_known'] and not value['own']['10']['known'] and value['own']['10']['ambiguous'])
    packet = fixture(mutation='opposite_sign')
    value = core.build_session(packet, refs(packet))['features']['C_OWN']['TOPIX'][44]
    check('両気配逆符号はneutral救済しない', value['own']['10']['ambiguous_sign'] and not value['own']['10']['known'])
    packet = fixture(mutation='peer_equal')
    value = core.build_session(packet, refs(packet))['features']['C_OWN']['TOPIX'][44]
    check('相手同時計公表は採らず厳密過去だけ', value['peer']['10']['public_endpoint']['raw_row'] == 43 and value['peer']['10']['age_seconds'] == 1.)
    packet = fixture(mutation='peer_stale')
    value = core.build_session(packet, refs(packet))['features']['C_OWN']['TOPIX'][44]
    check('相手公表15秒超はUNKNOWN', value['peer']['10']['age_seconds'] > 15.
        and not value['peer']['10']['known'] and value['peer']['10']['efficiency'] is None)
    times = 1000.+np.arange(65, dtype=float)
    times[30] = times[29]-1.
    packet = fixture(times=times)
    value = core.build_session(packet, refs(packet))['features']['C_OWN']['TOPIX'][44]
    check('途中時計逆転を跨がない', not value['own_normal']['30']['known'] and value['own_normal']['30']['efficiency'] is None)
    times = 1000.+np.arange(65, dtype=float)
    times[30:] += 20.
    packet = fixture(times=times)
    value = core.build_session(packet, refs(packet))['features']['C_OWN']['TOPIX'][44]
    check('途中公表gap15秒超を跨がない', not value['own']['30']['known'] and (value['own']['30']['legacy_unknown_reason'] & 32) != 0)
    packet = fixture(candidate_row=5)
    value = core.build_session(packet, refs(packet))['features']['C_OWN']['TOPIX'][5]
    check('不足窓で数値0補完なし', not value['own_normal']['10']['known'] and value['own_normal']['10']['max_adverse_ticks'] is None)
    packet = fixture(mutation='unmapped')
    built = core.build_session(packet, refs(packet))
    check('normal非対応を将来行へ移動しない', len(built['features']['C_OWN']['TOPIX']) == 0
        and 44 in built['raw_features']['C_OWN']['TOPIX'] and not np.any(built['cases']['C_OWN']['TOPIX']['event']))
    # ----------------------------------------
    first_prefix = None
    for cut in (45, 48, 65):
        length, times = cut, 1000.+np.arange(cut, dtype=float)
        walk = np.arange(cut, dtype=float)
        prefix = fixture(walk=walk, times=times)
        before = core.build_session(prefix, refs(prefix))
        if first_prefix is None:
            first_prefix = before['features']
        check('実接頭延長による過去候補不変', equal(first_prefix, before['features']))
        changed = fixture(walk=walk, times=times)
        for symbol in core.SYMBOLS:
            raw = changed['raw'][symbol]
            raw['bid'][45:] += 99999.
            raw['ask'][45:] += 99999.
            record = changed['normal'][symbol]['record']
            record['bid'][45:] = raw['bid'][45:]
            record['ask'][45:] = raw['ask'][45:]
            changed['peer_features'][symbol] = prices.build(raw, changed['items'][symbol], oldcore.publications(raw), POLICY)
        after = core.build_session(changed, refs(changed))
        check('将来価格改変で過去候補特徴不変', equal(before['features'], after['features']))
    # ----------------------------------------
    packet = fixture()
    reference = refs(packet)
    reference['TOPIX']['known_from_i'] = 1
    try:
        core.build_session(packet, reference)
    except AssertionError:
        check('遅れて既知になる始値は拒否', True)
    else:
        raise AssertionError('遅れ始値が採用された')
    reference = refs(packet)
    reference['TOPIX']['source_time'] += 1.
    try:
        core.build_session(packet, reference)
    except AssertionError:
        check('初回正常行より後の始値sourceを拒否', True)
    else:
        raise AssertionError('未来始値sourceが採用された')
    saved = {('人工', symbol): dict(record=packet['normal'][symbol]['record'], reference_open=1000.*packet['items'][symbol]['tick'],
        signal=dict(trend_width=core.trend_width(1000.*packet['items'][symbol]['tick'], packet['items'][symbol]['tick']))) for symbol in core.SYMBOLS}
    direct = core.build_session(packet, saved_prepared=saved)
    check('追加Day同prepared実幅対照の人工', all(direct['opening_provenance'][symbol]['width_actual_equal'] for symbol in core.SYMBOLS))
    saved['人工', 'TOPIX']['signal']['trend_width'] += .5
    try:
        core.build_session(packet, saved_prepared=saved)
    except AssertionError:
        check('既保存実幅との不一致を拒否', True)
    else:
        raise AssertionError('実幅不一致が採用された')
    sources = [HERE/name for name in ('core.py', 'features.py', 'data.py', 'prepare.py', 'artificial.py', '入力schema.json')]
    sources += [ROOT/'work/wave_v90/strategy.py', ROOT/'work/wave_v104/peer/core.py', ROOT/'work/wave_v104/peer/prices.py']
    sources += [ROOT/f'work/wave_v{number}/catalog.py' for number in range(91, 103)]
    return dict(全合格=True, 人工専用=True, 検査項目数=len(COUNTS), 検査件数=COUNTS,
        source_SHA256={str(path.relative_to(ROOT)): data.digest(path) for path in sources},
        正式packet読取=0, 原本読取=0, 旧64base再prepare=0, 新金融再生=0, 利益ラベル読取=0, 現在API=0,
        実幅対照の範囲='旧90.prepare関数本体をASTで取り出し、周辺状態だけを人工stub化して15例。固定G0値は元catalog純定義。正式追加Day実値2口座は正式許可後に対照する。')


def main() -> None:
    """
    機能: 人工検査の成功又は失敗を所有域へ保存する。
    引数: なし。
    返り値: None。不合格もFalse証跡を保存して例外を送出する。
    """
    path = HERE/'Q1当時経路と既存執行接続の人工検査.json'
    try:
        result = run()
    except Exception as error:
        path.write_text(json.dumps(dict(全合格=False, 人工専用=True, 失敗=str(error), 検査件数=COUNTS,
            traceback=traceback.format_exc(), 正式packet読取=0, 新金融再生=0), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        raise
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査項目数=result['検査項目数'], 総件数=sum(COUNTS.values())), ensure_ascii=False))


if __name__ == '__main__':
    main()
