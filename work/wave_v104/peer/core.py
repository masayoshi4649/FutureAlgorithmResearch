"""103活動cacheの同一原行BBOと固定自己根拠を、104の入力接口へ戻す。"""

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SYMBOLS = ('TOPIX', 'NK225')
GATES = ('OWN', 'N3', 'N10', 'N30', 'P3', 'P10', 'P30', 'P10T2')
STAGE_NAMES = ('anchor', 'prepared', 'recovery', 'moved', 'ready', 'first_price_move')


def catalog_draft() -> list[dict]:
    """
    機能: 金融値なしの19入口接口を人工用の草案として定義する。
    引数: なし。
    返り値: list[dict]はC/R各8とU3。root正式catalogの選定を代行しない。
    """
    values = [dict(id=family+'_'+gate, kind='single', family=family, gate=gate)
              for family in ('C', 'R') for gate in GATES]
    values += [dict(id='U_'+gate, kind='union', gate=gate) for gate in ('OWN', 'N10', 'P10')]
    assert len(values) == 19
    return values


def restore_account(account: dict, execution_record: dict) -> dict:
    """
    機能: 活動cacheのnormal BBOを同一原行へ戻し、入口資格と出口観測正常を分ける。
    引数: account(dict)は不変活動cache、execution_record(dict)は根が渡す旧正常執行record。
    返り値: dictはraw/normalの観測、qualified/reset/map。非対応はNaNで未来探索しない。
    """
    source, record = account['source'], account['normal_record']
    seq, times = source['raw_seq'], source['price_time_s']
    mapping, reverse = source['execution_to_raw_index'], source['normal_execution_row']
    n, m = len(seq), len(mapping)
    assert seq.dtype == np.int64 and mapping.dtype == np.int64
    assert reverse.shape == source['qualified'].shape == times.shape == (n,)
    assert np.all((mapping >= 0) & (mapping < n)) and np.all(np.diff(mapping) > 0)
    np.testing.assert_array_equal(reverse[mapping], np.arange(m))
    np.testing.assert_array_equal(np.flatnonzero(reverse >= 0), mapping)
    np.testing.assert_array_equal(record['seq'], seq[mapping])
    np.testing.assert_array_equal(record['time_s'], times[mapping])
    assert all(record[name].shape == (m,) for name in ('price', 'bid', 'ask'))
    for name in ('seq', 'time_s', 'price', 'bid', 'ask'):
        np.testing.assert_array_equal(execution_record[name], record[name], err_msg=name)
    for name in ('start', 'end', 'limit', 'tick'):
        assert execution_record[name] == record[name], name
    assert 'quote_valid' in execution_record and 'price_valid' in execution_record
    execution_valid = execution_record['quote_valid']
    assert execution_valid.shape == (m,) and execution_valid.dtype == np.bool_
    assert execution_record['price_valid'].shape == (m,) and execution_record['price_valid'].dtype == np.bool_
    raw_bid, raw_ask = np.full(n, np.nan), np.full(n, np.nan)
    raw_bid[mapping], raw_ask[mapping] = record['bid'], record['ask']
    bbo_finite = (np.isfinite(times) & np.isfinite(raw_bid) & np.isfinite(raw_ask)
        & (raw_bid > 0) & (raw_ask > raw_bid))
    raw_execution_valid = np.zeros(n, bool)
    raw_execution_valid[mapping] = execution_valid
    bbo_valid = bbo_finite & raw_execution_valid
    qualified = source['qualified']
    assert qualified.dtype == np.bool_
    reset = np.zeros(n, bool)
    reasons = {}
    for name in ('price_reset_reason', 'depth_reset_reason', 'lp_reset_reason', 'volume_reset_reason'):
        value = source[name]
        assert value.shape == (n,) and value.dtype == np.uint16
        assert not np.any(qualified & (value != 0)), name
        reasons[name] = value
        reset |= value != 0
    clock_or_sequence_invalid = ~np.isfinite(times)
    if n > 1:
        clock_or_sequence_invalid[1:] |= (~np.isfinite(times[1:]) | ~np.isfinite(times[:-1])
            | (times[1:] < times[:-1]) | (seq[1:] != seq[:-1]+1))
    raw = dict(raw_seq=seq, price_time_s=times, volume_time_s=source['volume_time_s'],
        bid=raw_bid, ask=raw_ask, bbo_valid=bbo_valid, bbo_finite=bbo_finite,
        execution_quote_valid=raw_execution_valid, qualified=qualified,
        entry_quality=qualified & bbo_valid, entry_reset=reset,
        clock_or_sequence_invalid=clock_or_sequence_invalid,
        normal_execution_row=reverse, execution_to_raw_index=mapping, **reasons)
    normal = dict(record=execution_record, restore_record=record, bid=record['bid'], ask=record['ask'],
        bbo_valid=bbo_valid[mapping].copy(), entry_quality=raw['entry_quality'][mapping].copy(),
        entry_reset=reset[mapping].copy())
    normal['quote_valid'] = execution_valid & normal['bbo_valid']
    normal['price_valid'] = execution_record['price_valid']
    return dict(raw=raw, normal=normal, item=account['item'])


def entries() -> list[dict]:
    """
    機能: 根が結果前に固定した19入口だけを読む。
    引数: なし。
    返り値: list[dict]はid/family/gate。121金融条件又は結果を読み込まない。
    """
    path = HERE.parent/'catalog.py'
    name = '104peer結果前の19入口'
    if name not in sys.modules:
        specification = importlib.util.spec_from_file_location(name, path)
        value = importlib.util.module_from_spec(specification)
        sys.modules[name] = value
        specification.loader.exec_module(value)
    values = sys.modules[name].entries()
    assert len(values) == len({value['id'] for value in values}) == 19
    assert sum(value['family'] in ('C', 'R') for value in values) == 16
    assert sum(value['family'] == 'U' for value in values) == 3
    return values


def publications(raw: dict) -> dict:
    """
    機能: 保存価格代理時計の新最大最初原行だけを公表源へ固定する。
    引数: raw(dict)は復元済み一商品原行入力。
    返り値: dictは公表row/seq/time。unknownの先頭を後半へ差し替えない。
    """
    indexes, maximum = [], -np.inf
    for row, stamp in enumerate(raw['price_time_s']):
        if np.isfinite(stamp) and stamp > maximum:
            maximum = stamp
            indexes.append(row)
    rows = np.asarray(indexes, np.int64)
    return dict(rows=rows, raw_seq=raw['raw_seq'][rows].copy(), times=raw['price_time_s'][rows].copy())


def peer_rows(own: dict, peer: dict, public: dict) -> dict:
    """
    機能: 自己clockより厳密過去の最新公表源と15秒内資格を求める。
    引数: own/peer/public(dict)は自己・相手原行と相手公表源。
    返り値: dictは相手row/index/age/fresh。未知を中立又は支持へ置換しない。
    """
    times = own['price_time_s']
    positions = np.searchsorted(public['times'], times, side='left')-1
    known = (positions >= 0) & np.isfinite(times)
    rows, ages = np.full(len(times), -1, np.int64), np.full(len(times), np.nan)
    rows[known] = public['rows'][positions[known]]
    ages[known] = times[known]-peer['price_time_s'][rows[known]]
    fresh = known & (ages > 0) & (ages <= 15.)
    positions[~known] = -1
    return dict(rows=rows, public_indexes=positions, ages=ages, fresh=fresh)


def stage_lookup(packet: dict) -> dict:
    """
    機能: sparseな当時段階ログを整数基準seq・方向へ索引化する。
    引数: packet(dict)は103の不変C1/R1状態。
    返り値: dictはepisodeからevent index列。将来ログを過去へ混ぜない。
    """
    lookup = {}
    for index, anchor in enumerate(packet['event_anchor_raw_seq']):
        side = int(packet['events'][index, 2])
        lookup.setdefault((int(anchor), side), []).append(index)
    return lookup


def self_lineage(packet: dict, raw: dict, row: int, side: int, lookup: dict) -> dict:
    """
    機能: 判断時点以下の自己段階と正しいC/R固定支持価格を取得する。
    引数: packet/raw(dict)、row/side(int)、lookup(dict)は対象当時状態。
    返り値: dictはepisode・支持価格・当時stage。C列17をC支持価格へ誤用しない。
    """
    column = 0 if side == 1 else 1
    assert packet['qualified'][row] and packet['ready'][row, column]
    anchor = int(packet['anchor_raw_seq'][row, column])
    indexes = [index for index in lookup[(anchor, side)] if packet['events'][index, 0] <= row]
    assert indexes
    index = indexes[-1]
    event, family = packet['events'][index], packet['config']['family']
    assert family in ('C', 'R')
    support = float(event[15] if family == 'C' else event[17])
    assert np.isfinite(support) and support > 0
    stages = {}
    for offset, name in enumerate(STAGE_NAMES, 6):
        source = int(event[offset])
        assert source <= row
        stages[name] = None if source < 0 else dict(row=source, raw_seq=int(raw['raw_seq'][source]),
            price_time_s=float(raw['price_time_s'][source]))
    intent = side if family == 'C' else -side
    return dict(family=family, episode=(family, intent, anchor), side=side,
        row=row, raw_seq=int(raw['raw_seq'][row]), price_time_s=float(raw['price_time_s'][row]),
        anchor_raw_seq=anchor, support_price=support, event_index=index, stages=stages)


def single_candidates(account: dict, raw: dict, family: str) -> list[dict]:
    """
    機能: 現OWNの初回同一原行候補を再利用し、条件別に待機して選び直さない。
    引数: account/raw(dict)、family(str)はC/R。
    返り値: list[dict]は共通候補と自己lineage。peer gateの採否はまだ行わない。
    """
    packet = account['packets'][family+'1']
    original = account['pulses'][family+'_OWN']
    lookup, candidates = stage_lookup(packet), []
    assert [int(value['row']) for value in original['decisions']] == np.flatnonzero(original['event']).tolist()
    seen = set()
    for value in original['decisions']:
        row, side = int(value['row']), int(value['side'])
        assert int(raw['raw_seq'][row]) == value['raw_seq'] and int(original['event'][row]) == side
        lineage = self_lineage(packet, raw, row, side, lookup)
        assert lineage['episode'] == tuple(value['episode']) and lineage['episode'] not in seen
        seen.add(lineage['episode'])
        candidates.append(dict(row=row, raw_seq=int(raw['raw_seq'][row]),
            price_time_s=float(raw['price_time_s'][row]), side=side,
            episodes=[lineage['episode']], self_lineages=[lineage], support_price=lineage['support_price']))
    return candidates


def union_candidates(account: dict, raw: dict) -> list[dict]:
    """
    機能: 全readyで方向競合し、新しい未消費同方向根拠だけで一度候補化する。
    引数: account/raw(dict)は不変C1/R1 packetと原行入力。
    返り値: list[dict]は共通U候補。scalar支持線は新根拠の買max/売min。
    """
    packets = {family: account['packets'][family+'1'] for family in ('C', 'R')}
    lookups = {family: stage_lookup(packet) for family, packet in packets.items()}
    consumed, candidates = set(), []
    for row in range(len(raw['raw_seq'])):
        if not raw['qualified'][row]:
            continue
        active = []
        for family, packet in packets.items():
            if not packet['qualified'][row]:
                continue
            for column, side in enumerate((1, -1)):
                if packet['ready'][row, column]:
                    intent = side if family == 'C' else -side
                    key = family, intent, int(packet['anchor_raw_seq'][row, column])
                    active.append((side, key, family))
        directions = {value[0] for value in active}
        if len(directions) != 1:
            continue
        pending = [value for value in active if value[1] not in consumed]
        if not pending:
            continue
        side = next(iter(directions))
        histories = [self_lineage(packets[family], raw, row, side, lookups[family]) for _, _, family in pending]
        levels = [history['support_price'] for history in histories]
        support = max(levels) if side == 1 else min(levels)
        consumed.update(value[1] for value in pending)
        candidates.append(dict(row=row, raw_seq=int(raw['raw_seq'][row]),
            price_time_s=float(raw['price_time_s'][row]), side=side,
            episodes=[history['episode'] for history in histories], self_lineages=histories,
            support_price=support, support_prices=levels,
            competition_ready_episodes=[value[1] for value in active]))
    return candidates
