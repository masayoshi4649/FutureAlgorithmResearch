"""保存状態・相手窓・会計集計を独立に照合する。正式再生は呼ばない。"""

from collections import Counter
from decimal import Decimal, ROUND_CEILING
import importlib.util
from pathlib import Path
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WAVE = HERE.parents[1]
ROOT = WAVE.parents[1]
COUNTS = Counter()


def module(name: str, path: Path) -> object:
    """
    機能: 既に独立確認した小さい集計ソースを読取専用で接続する。
    引数: name(str)、path(Path)は読取対象。
    返り値: object。正式CLIや金融は実行しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


OLD = module('104監査の独立103算式', ROOT/'work/wave_v103/review/finance_audit/全19条件の注文現金と時価及び安定性を独立監査する.py')
OLD.COUNTS = COUNTS
equal, charge, totals, sum_rows = OLD.equal, OLD.charge, OLD.totals, OLD.sum_rows
aggregate_check, stable_check = OLD.aggregate_check, OLD.stable_check


def deep(actual: object, expected: object, label: object) -> None:
    """
    機能: 由来の辞書とtuple/listを再帰的に独立期待値へ照合する。
    引数: actual/expected(object)、label(object)は比較値と診断位置。
    返り値: None。不明と既知0は別に扱う。
    """
    if isinstance(expected, dict):
        assert isinstance(actual, dict) and set(actual) == set(expected), label
        for key, value in expected.items():
            deep(actual[key], value, (label, key))
    elif isinstance(expected, (tuple, list)):
        assert isinstance(actual, (tuple, list)) and len(actual) == len(expected), label
        for i, value in enumerate(expected):
            deep(actual[i], value, (label, i))
    else:
        equal(actual, expected, label)


def width(reference: float, tick: float) -> float:
    """
    機能: 始値0.1%の初期保険をDecimalで呼値へ切り上げる。
    引数: reference/tick(float)は保存時点で既知の値。
    返り値: floatは最低2呼値の幅。未来高安は使わない。
    """
    steps = int((Decimal(str(reference))*Decimal('.001')/Decimal(str(tick))).to_integral_value(rounding=ROUND_CEILING))
    return max(2, steps)*tick


def public_rows(raw: dict) -> np.ndarray:
    """
    機能: 新最大価格時計の最初原行を累積最大から独立に求める。
    引数: raw(dict)は保存原行。
    返り値: ndarray[int64]は公表原行。無効先頭を後半へ差し替えない。
    """
    times = raw['price_time_s']
    finite = np.isfinite(times)
    high = np.maximum.accumulate(np.where(finite, times, -np.inf))
    prior = np.r_[-np.inf, high[:-1]]
    return np.flatnonzero(finite & (times > prior))


def state_index(account: dict) -> dict:
    """
    機能: 旧103自己packetのepisodeイベントを当時順に索引化する。
    引数: account(dict)は一回読取の保存活動。
    返り値: dictはfamily/anchor/sideのイベント索引。
    """
    result = {}
    for family in ('C', 'R'):
        packet = account['packets'][family+'1']
        lookup = {}
        for i, anchor in enumerate(packet['event_anchor_raw_seq']):
            lookup.setdefault((int(anchor), int(packet['events'][i, 2])), []).append(i)
        result[family] = lookup
    return result


def history_check(history: dict, raw: dict, account: dict, lookup: dict, row: int, side: int) -> float:
    """
    機能: 当時self lineageを旧packetの実eventと原seqへ直接照合する。
    引数: history/raw/account/lookup(dict)、row/side(int)は判断原行と方向。
    返り値: floatは当時固定support。未来eventやC列17の誤用は拒否する。
    """
    family = history['family']
    packet = account['packets'][family+'1']
    anchor, column = int(history['anchor_raw_seq']), 0 if side == 1 else 1
    assert packet['qualified'][row] and packet['ready'][row, column]
    equal(packet['anchor_raw_seq'][row, column], anchor, '自己当時anchor')
    indexes = lookup[family][anchor, side]
    eligible = [i for i in indexes if packet['events'][i, 0] <= row]
    assert eligible
    i, event = eligible[-1], packet['events'][eligible[-1]]
    equal(history['event_index'], i, '最後の実event')
    equal(history['row'], row, '自己原行')
    equal(history['raw_seq'], raw['raw_seq'][row], '自己原seq')
    equal(history['price_time_s'], raw['price_time_s'][row], '自己時計')
    deep(history['episode'], (family, side if family == 'C' else -side, anchor), 'episode')
    support = float(event[15 if family == 'C' else 17])
    equal(history['support_price'], support, '実event固定支持')
    for offset, name in enumerate(('anchor', 'prepared', 'recovery', 'moved', 'ready', 'first_price_move'), 6):
        source = int(event[offset])
        assert source <= row
        expected = None if source < 0 else dict(row=source, raw_seq=int(raw['raw_seq'][source]), price_time_s=float(raw['price_time_s'][source]))
        deep(history['stages'][name], expected, ('当時段階', name))
        COUNTS['全当時stage'] += 1
    return support


def common_candidates(account: dict, raw: dict) -> dict:
    """
    機能: 単一初回OWNとUの全ready競合・一回消費を独立に作る。
    引数: account/raw(dict)は旧状態と同原行source。
    返り値: dictはfamilyごとのrow→side/episode。金融は実行しない。
    """
    result = {}
    for family in ('C', 'R'):
        pulse = account['pulses'][family+'_OWN']
        result[family] = {int(value['row']): (int(value['side']), [tuple(value['episode'])]) for value in pulse['decisions']}
        assert set(result[family]) == set(np.flatnonzero(pulse['event']))
    packets = [account['packets'][family+'1'] for family in ('C', 'R')]
    active = np.zeros((len(raw['raw_seq']), 4), bool)
    anchors = np.empty((len(raw['raw_seq']), 4), np.int64)
    for j, packet in enumerate(packets):
        active[:, 2*j:2*j+2] = packet['ready'] & packet['qualified'][:, None] & raw['qualified'][:, None]
        anchors[:, 2*j:2*j+2] = packet['anchor_raw_seq']
    codes = np.sum(active*np.array([1, 2, 4, 8]), axis=1)
    changed = np.r_[True, (codes[1:] != codes[:-1]) | np.any(anchors[1:] != anchors[:-1], axis=1)]
    consumed, output = set(), {}
    for row in np.flatnonzero(changed & (codes != 0)):
        roots = []
        for j in np.flatnonzero(active[row]):
            family, side = ('C' if j < 2 else 'R'), (1 if j % 2 == 0 else -1)
            roots.append((side, (family, side if family == 'C' else -side, int(anchors[row, j]))))
        sides = {value[0] for value in roots}
        if len(sides) != 1:
            continue
        fresh = [key for _, key in roots if key not in consumed]
        if fresh:
            output[int(row)] = next(iter(sides)), fresh
            consumed.update(fresh)
    result['U'] = output
    return result


def peer_tools(raw: dict) -> dict:
    """
    機能: 原行不正と公表間隔をprefixで作り、実判断の窓を独立検算する。
    引数: raw(dict)は一場相手原行。
    返り値: dictは公表と不正prefix。source窓関数は使わない。
    """
    rows = public_rows(raw)
    bad = (~raw['bbo_valid'] | ~np.isfinite(raw['price_time_s']) | (raw['price_reset_reason'] != 0))
    bad[1:] |= (raw['raw_seq'][1:] != raw['raw_seq'][:-1]+1) | (raw['price_time_s'][1:] < raw['price_time_s'][:-1])
    gaps = np.r_[False, np.diff(raw['price_time_s'][rows]) > 15]
    return dict(rows=rows, times=raw['price_time_s'][rows], bad=np.r_[0, np.cumsum(bad)], gaps=np.r_[0, np.cumsum(gaps)])


def gate_check(candidate: dict, gate: str, own: dict, peer: dict, tools: dict, tick: float) -> bool:
    """
    機能: 判断時のstrictpast相手BBO窓とmetadataを独立に検算する。
    引数: candidate/own/peer/tools(dict)、gate(str)、tick(float)は相手呼値。
    返り値: boolは採用可否。未知を中立へ変換しない。
    """
    if gate == 'OWN':
        assert candidate['peer'] is None and candidate['peer_status'] == 'NOT_USED' and not candidate['peer_used']
        return True
    time = float(own['price_time_s'][candidate['raw_row']])
    index = int(np.searchsorted(tools['times'], time, side='left')-1)
    window, threshold = (10, 2) if gate == 'P10T2' else (int(gate[1:]), 1)
    state, reason, db, da = 'UNKNOWN', 0, None, None
    metadata = candidate['peer']
    if index < 0:
        assert metadata['row'] is None and metadata['public_index'] is None
        fresh = False
    else:
        row = int(tools['rows'][index])
        age = time-float(peer['price_time_s'][row])
        assert age > 0
        fresh = age <= 15
        aindex = int(np.searchsorted(tools['times'], tools['times'][index]-window, side='right')-1)
        ar = int(tools['rows'][aindex]) if aindex >= 0 else -1
        if ar < 0:
            reason |= 1
        if not peer['qualified'][row] or not peer['bbo_valid'][row]:
            reason |= 2
        if ar >= 0:
            if not peer['qualified'][ar] or not peer['bbo_valid'][ar]:
                reason |= 4
            if tools['times'][index]-tools['times'][aindex] > window+15:
                reason |= 8
            if tools['bad'][row+1]-tools['bad'][ar]:
                reason |= 16
            if tools['gaps'][index+1]-tools['gaps'][aindex+1]:
                reason |= 32
            db, da = (peer['bid'][row]-peer['bid'][ar])/tick, (peer['ask'][row]-peer['ask'][ar])/tick
            spread = (peer['ask'][row]-peer['bid'][row])/tick
            old_spread = (peer['ask'][ar]-peer['bid'][ar])/tick
            if not reason:
                state = ('AMBIGUOUS' if db*da < 0 or spread > max(2, old_spread+1) else
                         'UP' if db >= threshold and da >= threshold else
                         'DOWN' if db <= -threshold and da <= -threshold else 'NEUTRAL')
            reference = metadata['reference']
            equal(reference['row'], ar, '相手基準raw')
            equal(reference['raw_seq'], peer['raw_seq'][ar], '相手基準seq')
            equal(reference['public_index'], aindex, '相手基準公開index')
            equal(reference['price_time_s'], peer['price_time_s'][ar], '相手基準時計')
        else:
            assert metadata['reference'] is None
        for key, expected in dict(row=row, public_index=index, raw_seq=int(peer['raw_seq'][row]),
            price_time_s=float(peer['price_time_s'][row]), age_seconds=age, window_seconds=window,
            threshold_ticks=threshold, source_direction=state, unknown_reason=reason).items():
            equal(metadata[key], expected, ('相手窓', key))
        for key, value in (('bid_change_ticks', db), ('ask_change_ticks', da)):
            equal(metadata[key], float(value) if value is not None and np.isfinite(value) else None, ('相手進行', key))
    effective = state if fresh else 'UNKNOWN'
    side = candidate['side']
    status = ('SUPPORT' if effective == ('UP' if side == 1 else 'DOWN') else
              'OPPOSE' if effective == ('DOWN' if side == 1 else 'UP') else effective)
    equal(candidate['peer_status'], status, '相手採否状態')
    accepted = status == 'SUPPORT' or (gate.startswith('N') and status == 'NEUTRAL')
    COUNTS['全候補相手窓'] += 1
    return accepted


def check_prepared(packet: dict, original: dict, prepared: dict, entries: list[dict], session: str) -> dict:
    """
    機能: 一回読取の新preparedを旧状態・旧執行へ全19×2で独立に照合する。
    引数: packet/original/prepared(dict)、entries(list[dict])、session(str)は保存入力。
    返り値: dictは台帳監査のcontext。原本・NPZ・金融再生は0。
    """
    assert set(packet['cases']) == {value['id'] for value in entries}
    contexts = {}
    tools = {symbol: peer_tools(packet['raw'][symbol]) for symbol in ('TOPIX', 'NK225')}
    for symbol in ('TOPIX', 'NK225'):
        record, old = prepared[session, symbol]['record'], original['accounts'][symbol]
        raw, mapping = packet['raw'][symbol], packet['raw'][symbol]['execution_to_raw_index']
        for name in ('raw_seq', 'price_time_s', 'qualified', 'execution_to_raw_index', 'normal_execution_row',
                     'price_reset_reason', 'depth_reset_reason', 'lp_reset_reason', 'volume_reset_reason'):
            np.testing.assert_array_equal(raw[name], old['source'][name])
        for name in ('seq', 'time_s', 'price', 'bid', 'ask'):
            np.testing.assert_array_equal(record[name], old['normal_record'][name])
        qok = (record['quote_valid'] & np.isfinite(record['time_s']) & np.isfinite(record['bid']) & np.isfinite(record['ask'])
                & (record['bid'] > 0) & (record['ask'] > record['bid']))
        expected_raw_quote = np.zeros(len(raw['raw_seq']), bool)
        expected_raw_quote[mapping] = qok
        np.testing.assert_array_equal(raw['bbo_valid'], expected_raw_quote)
        reset = np.logical_or.reduce([raw[name] != 0 for name in ('price_reset_reason', 'depth_reset_reason', 'lp_reset_reason', 'volume_reset_reason')])
        np.testing.assert_array_equal(raw['entry_reset'], reset)
        np.testing.assert_array_equal(raw['entry_quality'], raw['qualified'] & expected_raw_quote)
        common, lookup = common_candidates(old, raw), state_index(old)
        other = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
        for entry in entries:
            value, expected = packet['cases'][entry['id']][symbol], common[entry['family']]
            candidates = value['candidates']
            assert [int(c['raw_row']) for c in candidates] == list(expected)
            event, support = np.zeros(len(raw['raw_seq']), np.int8), np.full(len(raw['raw_seq']), np.nan)
            for candidate in candidates:
                row = int(candidate['raw_row'])
                side, episodes = expected[row]
                assert candidate['side'] == side and raw['qualified'][row] and not reset[row]
                deep(candidate['episodes'], episodes, '共通初回episode')
                levels = [history_check(history, raw, old, lookup, row, side) for history in candidate['self_lineages']]
                equal(candidate['support_price'], max(levels) if side == 1 else min(levels), '固定新支持')
                accepted = gate_check(candidate, entry['gate'], raw, packet['raw'][other], tools[other], packet['items'][other]['tick'])
                assert candidate['accepted'] == accepted
                if accepted:
                    event[row], support[row] = side, candidate['support_price']
                COUNTS['全共通候補と支持'] += 1
            for name, wanted in (('event', event), ('support_price', support)):
                np.testing.assert_array_equal(value['raw'][name], wanted)
                np.testing.assert_array_equal(value['normal'][name], wanted[mapping])
            normal = value['normal']
            assert normal['entry_id'] == entry['id']
            np.testing.assert_array_equal(normal['execution_to_raw_index'], mapping)
            np.testing.assert_array_equal(normal['entry_quality'], raw['entry_quality'][mapping])
            np.testing.assert_array_equal(normal['entry_reset'], reset[mapping])
            assert {int(row['row']) for row in normal['decisions']} == set(np.flatnonzero(normal['event']))
        last = np.maximum.accumulate(np.where(qok, np.arange(len(qok)), -1))
        contexts[symbol] = dict(record=record, raw=raw, cases={ident: value[symbol]['normal'] for ident, value in packet['cases'].items()},
            qok=qok, good=np.flatnonzero(qok), last=last, prepared=prepared[session, symbol], original=old, symbol=symbol)
        COUNTS['全19正常入口商品'] += 1
    return contexts
