"""全32正式活動を読まず、疎normal投影・消費・段階由来・保存接口を独立人工で確認する。"""

from copy import deepcopy
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
WAVE = HERE.parents[1]
ACTIVITY = WAVE / 'activity'


def load(name: str, path: Path) -> object:
    """
    機能: 活動source又は私有人工部品だけを固有名で読む。
    引数: name(str)、path(Path)はモジュール名とsource。
    返り値: objectは部品。正式測定、金融及びAPI関数を呼ばない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


def digest(path: Path) -> str:
    """
    機能: 小sourceと私有人工保存の内容指紋を取る。
    引数: path(Path)は対象ファイル。
    返り値: strはSHA256。正式全32cacheを読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ----------------------------------------

def add_map(raw: dict, mode: str) -> dict:
    """
    機能: 正常執行行を独立に選び、同一原行の双方向mapを設定する。
    引数: raw(dict)、mode(str)は人工配列とdense/odd/evenの対応方式。
    返り値: dictは双方向map付きの新人工配列。発火を次の正常行へ動かさない。
    """
    result = deepcopy(raw)
    n = len(result['raw_seq'])
    mapping = np.arange(n, dtype=np.int64)
    if mode == 'odd':
        mapping = mapping[mapping % 2 == 1]
    elif mode == 'even':
        mapping = mapping[mapping % 2 == 0]
    else:
        assert mode == 'dense'
    reverse = np.full(n, -1, np.int32)
    reverse[mapping] = np.arange(len(mapping), dtype=np.int32)
    result['execution_to_raw_index'], result['normal_execution_row'] = mapping, reverse
    result.pop('独立正常資格', None)
    return result


def qualify_for_oracle(raw: dict) -> dict:
    """
    機能: 私有人工に元の正常資格を戻し、活動本体とは別oracleへ渡す。
    引数: raw(dict)は正常条件が既知の人工。
    返り値: dictは同じ観測を参照するoracle用辞書。
    """
    good = raw['depth_transition_valid'].copy()
    return dict(raw, 独立正常資格=good)


def own_pulse(packet: dict, raw: dict, family: str) -> np.ndarray:
    """
    機能: 相手を省く部品の全方向競合及び一度消費を別実装で計算する。
    引数: packet/raw(dict)、family(str)は人工状態、観測及び入口思想。
    返り値: ndarray[int8]は自己だけのpulse。受付外の消費も保持する。
    """
    emitted, consumed = np.zeros(len(raw['raw_seq']), np.int8), set()
    for row in range(len(emitted)):
        candidates = []
        if packet['qualified'][row]:
            for col, side in enumerate((1, -1)):
                if packet['ready'][row, col]:
                    key = (family, side if family == 'C' else -side, int(packet['anchor_raw_seq'][row, col]))
                    candidates.append((side, key))
        if len(candidates) == 1 and candidates[0][1] not in consumed:
            emitted[row] = candidates[0][0]
            consumed.add(candidates[0][1])
    return emitted


def expected_summary(event: np.ndarray, raw: dict, item: dict) -> dict:
    """
    機能: mapを用いず原行を一つずつ数え、受付とnormal投影の期待件数を作る。
    引数: event(ndarray[int8])、raw/item(dict)は独立pulseと人工期間。
    返り値: dictは各方向の発火/受付/正常対応。損益や勝敗を作らない。
    """
    labels = ('raw_pulses', 'normal_pulses', 'non_normal_pulses', 'reception_pulses',
              'outside_reception_pulses', 'reception_normal_pulses', 'reception_non_normal_pulses')
    counts = {str(side): dict.fromkeys(labels, 0) for side in (1, -1)}
    for row, direction in enumerate(event):
        if direction == 0:
            continue
        target = counts[str(int(direction))]
        normal = int(raw['normal_execution_row'][row]) >= 0
        received = (raw['price_time_valid'][row] and np.isfinite(raw['price_time_s'][row])
                    and item['start'] + 300 <= raw['price_time_s'][row] < item['limit'] - 300)
        target['raw_pulses'] += 1
        target['normal_pulses' if normal else 'non_normal_pulses'] += 1
        target['reception_pulses' if received else 'outside_reception_pulses'] += 1
        if received:
            target['reception_normal_pulses' if normal else 'reception_non_normal_pulses'] += 1
    return dict(sides=counts, **{label: sum(side[label] for side in counts.values()) for label in labels})


def check_lineage(history: dict, packet: dict, raw: dict, side: int) -> int:
    """
    機能: 保存lineageをpacketの過去eventから独立に復元し未来混入を拒否する。
    引数: history/packet/raw(dict)、side(int)は保存由来、状態、原行と参加方向。
    返り値: intは一致した段階数。活動core.lineage及びstage_lookupを使わない。
    """
    row, anchor = history['row'], history['anchor_raw_seq']
    candidates = [index for index, event in enumerate(packet['events'])
                  if int(packet['event_anchor_raw_seq'][index]) == anchor
                  and int(event[2]) == side and int(event[0]) <= row]
    assert candidates
    last = packet['events'][candidates[-1]]
    assert history['last_event_index'] == candidates[-1]
    assert history['raw_seq'] == int(raw['raw_seq'][row])
    assert history['price_time_s'] == float(raw['price_time_s'][row])
    count = 0
    for offset, name in enumerate(('anchor', 'prepared', 'recovery', 'moved', 'ready', 'first_price_move'), 6):
        index = int(last[offset])
        expected = None if index < 0 else dict(row=index, raw_seq=int(raw['raw_seq'][index]),
                                               price_time_s=float(raw['price_time_s'][index]))
        assert history['stages'][name] == expected and index <= row
        count += 1
    return count


# ----------------------------------------

def main() -> None:
    """
    機能: 活動sourceを独立人工で比較し、事前固定、route、非活動定義及び接口を検算する。
    引数: なし。
    返り値: None。review/activity_reviewのみへ保存。全32正式測定、金融、旧損益、APIは0。
    """
    target = HERE / '活動投影と因果由来及びcache契約の独立人工.json'
    assert not target.exists(), '完成証跡は上書きしません'
    core = load('独立活動core103', ACTIVITY / 'core.py')
    data = load('独立活動data103', ACTIVITY / 'data.py')
    helpers = load('独立活動の人工生成部品103', HERE.parent / '定着反転と二市場判断を独立人工で比較する.py')
    oracle = load('独立活動の補足07oracle103', HERE.parent / '補足07の独立状態機械と接頭を検算する.py')
    engine = core.states()
    for name in ('fixed_quantity', 'seed', 'log_event'):
        setattr(engine, name, getattr(engine, name).py_func)
    plan = core.read(ACTIVITY / '全32活動測定前の固定.json')
    specification = core.read(ACTIVITY / '活動cache仕様.json')
    assert specification == core.schema() and plan['活動定義'] == specification
    assert plan['対象場数'] == 32 and plan['口座数'] == len(plan['v2口座']) == 64
    source_verified = {}
    for name, wanted in plan['source_SHA256'].items():
        assert digest(ROOT / name) == wanted, name
        source_verified[name] = wanted
    assert digest(ACTIVITY / 'states_snapshot.py') == digest(WAVE / 'engine' / 'states.py')
    configs, matrix_cases, pulse_comparisons, lineage_stages = core.catalog(), 0, 0, 0
    zero_cases, outside_consumed, missing_only, future_checks = 0, 0, 0, 0
    by_session = {}
    for label, base_rows in (('C', helpers.scenarios()[0][1]), ('R', helpers.scenarios()[1][1])):
        for reflection in (False, True):
            for map_mode in ('dense', 'odd', 'even'):
                for start in (0., 110.):
                    rows = [deepcopy(row) for row in base_rows]
                    rows += [deepcopy(rows[-1]) for _ in range(14)]
                    for row in rows[len(base_rows):]:
                        row['volume'] = 0
                    raw, items = {}, {}
                    for symbol, tick, clock_offset in (('TOPIX', .5, 400.), ('NK225', 10., 399.9)):
                        current = helpers.raw_fixture(rows, tick, reflection)
                        current['price_time_s'] += clock_offset
                        current['volume_time_s'] += clock_offset
                        raw[symbol] = add_map(current, map_mode)
                        items[symbol] = dict(symbol=symbol, session='独立人工', start=start,
                                             end=1100., limit=1000., tick=tick)
                    before = {symbol: {name: value.copy() for name, value in current.items()}
                              for symbol, current in raw.items()}
                    payload = core.build_session('独立人工', raw, items, configs, python=True)
                    matrix_cases += 1
                    by_session[str(matrix_cases)] = payload['summary']
                    expected_packets = {}
                    for symbol in core.SYMBOLS:
                        expected_packets[symbol] = {}
                        for config in configs:
                            if config['kind'] == 'single' and not config['id'].endswith('_OWN'):
                                packet = oracle.oracle07(qualify_for_oracle(raw[symbol]), config, items[symbol]['tick'], helpers)
                                packet.update(qualified=raw[symbol]['depth_transition_valid'], config=config)
                                expected_packets[symbol][config['id']] = packet
                    for symbol in core.SYMBOLS:
                        other = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
                        account = payload['accounts'][symbol]
                        for name, value in raw[symbol].items():
                            np.testing.assert_array_equal(value, before[symbol][name])
                        for config in configs:
                            if config['kind'] not in ('single', 'union'):
                                continue
                            ident = config['id']
                            route = payload['case_routes'][ident]
                            if config['kind'] == 'single':
                                packet_id = route['packet']
                                family = config['family']
                                own, peer = expected_packets[symbol][packet_id], expected_packets[other][packet_id]
                                components = {family: dict(own=own, peer=peer, peer_raw=raw[other])}
                                expected_event = helpers.pulse_oracle(components, raw[symbol]) if config['use_peer'] else own_pulse(own, raw[symbol], family)
                            else:
                                components = {family: dict(own=expected_packets[symbol][family + '1'],
                                                peer=expected_packets[other][family + '1'], peer_raw=raw[other])
                                              for family in ('C', 'R')}
                                expected_event = helpers.pulse_oracle(components, raw[symbol])
                            actual = account['pulses'][ident]
                            np.testing.assert_array_equal(expected_event, actual['event'])
                            expected = expected_summary(expected_event, raw[symbol], items[symbol])
                            for field in expected:
                                assert actual['summary'][field] == expected[field], (ident, field)
                            mapping = raw[symbol]['execution_to_raw_index']
                            np.testing.assert_array_equal(actual['normal_event'], expected_event[mapping])
                            pulse_comparisons += 1
                            for decision in actual['decisions']:
                                row = decision['row']
                                normal = raw[symbol]['normal_execution_row'][row]
                                assert decision['normal_row'] == (None if normal < 0 else int(normal))
                                for record in decision['lineage']:
                                    family = record['episode'][0]
                                    packet_id = 'C1' if family == 'C' else 'R1'
                                    if config['kind'] == 'single':
                                        packet_id = route['packet']
                                    lineage_stages += check_lineage(record['own'], account['packets'][packet_id], raw[symbol], decision['side'])
                                    if record['peer'] is not None:
                                        history = record['peer']
                                        assert 0 < decision['price_time_s'] - history['price_time_s'] <= 15
                                        same_times = np.flatnonzero(raw[other]['price_time_s'] == history['price_time_s'])
                                        assert history['row'] == same_times[0]
                                        lineage_stages += check_lineage(history, payload['accounts'][other]['packets'][packet_id], raw[other], decision['side'])
                            if expected['raw_pulses'] == 0:
                                zero_cases += 1
                                assert not any(field in actual['summary'] for field in ('wins', 'profit', 'stable', '勝ち', '利益'))
                            if start > 0 and expected['raw_pulses'] > 0:
                                assert expected['reception_pulses'] == 0
                                assert np.count_nonzero(actual['event']) <= 1
                                outside_consumed += 1
                            if expected['raw_pulses'] > 0 and expected['normal_pulses'] == 0:
                                assert not actual['normal_event'].any()
                                missing_only += 1
                        for config in configs:
                            ident = config['id']
                            if config['kind'] == 'previous':
                                assert payload['case_routes'][ident] is None and account['summaries'][ident] is None
                            elif config['kind'] == 'portfolio':
                                route = payload['case_routes'][ident]
                                assert route['allocations'] == config['allocations']
                                assert route['per_direction_caps'] == config['per_direction_caps']
                                summary = account['summaries'][ident]
                                assert summary['allocations'] == list(config['allocations'][symbol])
                                assert summary['leg_pulses'] == sum(account['pulses'][leg]['summary']['raw_pulses'] for leg in ('C1', 'R1'))
                                assert 'orders' not in summary and 'profit' not in summary
                        for source, name in (('raw_seq', 'seq'), ('price_time_s', 'time_s'), ('last', 'price'), ('bid', 'bid'), ('ask', 'ask')):
                            np.testing.assert_array_equal(account['normal_record'][name], raw[symbol][source][raw[symbol]['execution_to_raw_index']])
                    altered = deepcopy(raw)
                    cut = len(base_rows)
                    for current in altered.values():
                        current['volume_delta'][cut:] = 9000
                        current['bid_quantities'][cut:] *= 100
                        current['depth_transition_valid'][cut:] = False
                    future = core.build_session('独立人工', altered, items, configs, python=True)
                    for symbol in core.SYMBOLS:
                        for ident, pulse in payload['accounts'][symbol]['pulses'].items():
                            old = [decision for decision in pulse['decisions'] if decision['row'] < cut]
                            new = [decision for decision in future['accounts'][symbol]['pulses'][ident]['decisions'] if decision['row'] < cut]
                            assert old == new
                            np.testing.assert_array_equal(pulse['event'][:cut], future['accounts'][symbol]['pulses'][ident]['event'][:cut])
                            future_checks += 1
    # ----------------------------------------
    # 私有領域へだけ保存し、manifest読取は明示人工のstubへ限定してAPIの往復を調べる。
    private = HERE / '私有人工cache'
    private.mkdir()
    original_here = data.HERE
    original_read = data.core.read
    data.HERE = private
    saved_path = private / 'cache' / '独立人工.pkl.gz'
    saved_sha = data.dump_session(saved_path, payload)
    fake_manifest = dict(人工専用=True, 全合格=True, 対象場数=32, 口座数=64,
                         正式金融再生=0, 現在API取得=0, 実注文=0, sessions=['独立人工'],
                         cache={'独立人工': dict(位置=str(saved_path.relative_to(ROOT)), SHA256=saved_sha)},
                         開始SHA256=source_verified, by_session={'独立人工': payload['summary']})
    data.core.read = lambda path: fake_manifest
    try:
        restored = data.load_session('独立人工', verify=True)
        assert restored['summary'] == payload['summary']
        assert restored['case_routes'] == payload['case_routes']
        assert not restored['accounts']['TOPIX']['normal_record']['price'].flags.writeable
        assert not restored['accounts']['NK225']['pulses']['U_C1R1']['event'].flags.writeable
    finally:
        data.HERE, data.core.read = original_here, original_read
    # ----------------------------------------
    # 受付4境界と不活動の合計を独立に確かめる。正式prepare.mainは呼ばない。
    raw_edge = dict(raw_seq=np.arange(4, dtype=np.int64), price_time_s=np.array([299.999, 300., 699.999, 700.]),
                    price_time_valid=np.ones(4, bool), execution_to_raw_index=np.array([1, 3], np.int64),
                    normal_execution_row=np.array([-1, 0, -1, 1], np.int32))
    emitted = np.array([1, -1, 1, -1], np.int8)
    packet = dict(event=emitted, decisions=[dict(row=row, raw_seq=row, side=int(side)) for row, side in enumerate(emitted)])
    edge = core.project(packet, raw_edge, dict(start=0, limit=1000))
    assert [row['in_reception'] for row in edge['decisions']] == [False, True, True, False]
    assert [row['normal_row'] for row in edge['decisions']] == [None, 0, None, 1]
    expected = expected_summary(emitted, raw_edge, dict(start=0, limit=1000))
    assert all(edge['summary'][name] == value for name, value in expected.items())
    for name, wanted in source_verified.items():
        assert digest(ROOT / name) == wanted
    result = dict(全合格=True,
        scope='固定activity sourceを私有人工及び独立07状態/pulse/投影/lineage oracleで検査。全32正式活動、金融、旧損益は未読。',
        人工二市場セット数=matrix_cases, 独立発火投影比較件数=pulse_comparisons,
        因果段階照合数=lineage_stages, 発火0を勝敗にしない比較件数=zero_cases,
        受付外消費後復活なし比較件数=outside_consumed, normal非対応pulse非移動件数=missing_only,
        raw発火及びlineage未来不変件数=future_checks, 受付4境界=True,
        条件19route及びOLDnull=True, 単一14をlocal12で再利用=True,
        配分は実枚数保持で腿数を注文数としない=True, 旧正常5列の同原行直接対応=True,
        cache私有保存と人工manifestでload接口一致=True,
        cacheload配列readonly=True, source固定一致件数=len(source_verified),
        実用限界=[
            '発火0は未活動であり、赤字がなかったことを安定黒字と評価できない。',
            '活動場数はraw発火の存在。受付外又は正常非対応だけでも活動場になり、実注文数ではない。受付内normal対応と実金融成立を別に評価する。',
            'normal_eventは受付外発火も保存する。後段の金融受付に同じ開始以上・終了未満の門が必要。',
            '価格代理時計は受信時計ではない。厳密過去でも実際の先後は証明できない。',
            '相手の同時刻後続で完成し同時刻中に崩れたreadyは一度も公表されない。両市場同期が遅れる又は失われ、活動を減らす可能性がある。',
            '両市場で同じ思想、同方向、15秒内のreadyを要求するため、正しいが片方で未完成の動きも捨てる。許容すれば成績が良くなるという主張ではない。',
            '表示減少の約定/取消/真補充及び全出来高の方向は未同定。活動があることだけで入口優位性は証明されない。'],
        SHA256={str(path.relative_to(ROOT)): digest(path) for path in (
            Path(__file__), ACTIVITY / 'core.py', ACTIVITY / 'data.py', ACTIVITY / 'prepare.py',
            ACTIVITY / 'artificial.py', ACTIVITY / 'states_snapshot.py', ACTIVITY / '活動cache仕様.json',
            ACTIVITY / '人工発火の正常列直接投影と未来不変.json', ACTIVITY / '全32活動測定前の固定.json',
            HERE.parent / '補足07の独立状態機械と接頭を検算する.py', saved_path)},
        正式全32測定=0, 正式活動値読取=0, 正式口座読取=0, 金融再生=0, 旧金融結果読取=0,
        API取得=0, 実注文=0, 他owner_source変更=0, JIT実行=0)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 人工セット数=matrix_cases, 発火投影比較件数=pulse_comparisons,
                         因果段階照合数=lineage_stages, 発火0件数=zero_cases, 非対応件数=missing_only,
                         受付外消費件数=outside_consumed, SHA256=digest(target)), ensure_ascii=False))


if __name__ == '__main__':
    main()
