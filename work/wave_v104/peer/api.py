"""自己OWN共通候補を一般peer方向へ接続し、当時metadataと同一行投影を返す。"""

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
for _name in ('core', 'prices'):
    _identifier = '104peer接口内部'+_name
    if _identifier not in sys.modules:
        _specification = importlib.util.spec_from_file_location(_identifier, HERE/(_name+'.py'))
        _module = importlib.util.module_from_spec(_specification)
        sys.modules[_identifier] = _module
        _specification.loader.exec_module(_module)
    globals()[_name] = sys.modules[_identifier]


POLICY = dict(max_public_gap_seconds=15., baseline_extra_age_seconds=15.,
              spread_max_ticks=2., spread_increment_ticks=1.)


def nullable(value: float) -> float | None:
    """
    機能: 当時metadataの不明数値を明示Noneへ変換する。
    引数: value(float)は観測又はNaN。
    返り値: float|Noneは既知数値又は不明。0への補完はしない。
    """
    return float(value) if np.isfinite(value) else None


def gate_decision(candidate: dict, gate: str, own: dict, peer: dict,
                  feature: dict, selection: dict) -> dict:
    """
    機能: 同じ自己初回候補に対して、その時既知の相手価格gateを一度判定する。
    引数: candidate/own/peer/feature/selection(dict)、gate(str)は8入口確認のいずれか。
    返り値: dictは採否と原公表・基準・測定lineage。OWN/Nを支持ありと偽らない。
    """
    specification, row, side = prices.gate_spec(gate), candidate['row'], candidate['side']
    if not specification['use_peer']:
        return dict(accepted=True, mode='OWN', peer_used=False, status='NOT_USED', peer=None)
    index = int(selection['public_indexes'][row])
    source = int(selection['rows'][row])
    age = nullable(selection['ages'][row])
    metadata = dict(public_index=None if index < 0 else index, row=None if source < 0 else source,
        raw_seq=None if source < 0 else int(peer['raw_seq'][source]),
        price_time_s=None if source < 0 else float(peer['price_time_s'][source]), age_seconds=age,
        window_seconds=specification['window'], threshold_ticks=specification['threshold'],
        reference=None, source_direction='UNKNOWN', unknown_reason=None,
        ambiguous_spread=False, ambiguous_sign=False, bid_change_ticks=None, ask_change_ticks=None)
    state = prices.UNKNOWN
    if index >= 0:
        window = feature['windows'][str(specification['window'])]
        state = int(window['direction_t'+str(specification['threshold'])][index])
        metadata.update(source_direction=prices.STATUS_NAMES[state], unknown_reason=int(window['unknown_reason'][index]),
            ambiguous_spread=bool(window['ambiguous_spread'][index]), ambiguous_sign=bool(window['ambiguous_sign'][index]),
            bid_change_ticks=nullable(window['bid_change_ticks'][index]), ask_change_ticks=nullable(window['ask_change_ticks'][index]))
        reference_row = int(window['reference_raw_row'][index])
        if reference_row >= 0:
            metadata['reference'] = dict(public_index=int(window['reference_public_index'][index]),
                row=reference_row, raw_seq=int(peer['raw_seq'][reference_row]),
                price_time_s=float(peer['price_time_s'][reference_row]),
                bid=nullable(peer['bid'][reference_row]), ask=nullable(peer['ask'][reference_row]))
        metadata.update(bid=nullable(peer['bid'][source]), ask=nullable(peer['ask'][source]))
        assert float(peer['price_time_s'][source]) < float(own['price_time_s'][row])
    if not selection['fresh'][row]:
        state = prices.UNKNOWN
    status = 'SUPPORT' if state == side else 'OPPOSE' if state == -side else prices.STATUS_NAMES[state]
    accepted = status == 'SUPPORT' or (specification['mode'] == 'NOT_OPPOSE' and status == 'NEUTRAL')
    return dict(accepted=accepted, mode=specification['mode'], peer_used=True, status=status, peer=metadata)


def filter_case(config: dict, candidates: list[dict], own: dict, peer: dict,
                feature: dict, selection: dict, normal: dict) -> dict:
    """
    機能: 共通消費済候補の採否を一回保存し、同じ原行normalへ直接投影する。
    引数: config/own/peer/feature/selection/normal(dict)、candidates(list[dict])は結果前の共通候補。
    返り値: dictはraw/normal event・支持・自己相手lineage及び全候補採否。未来復活しない。
    """
    n, mapping = len(own['raw_seq']), own['execution_to_raw_index']
    event, support = np.zeros(n, np.int8), np.full(n, np.nan)
    decisions, candidate_records = [], []
    for candidate in candidates:
        row = candidate['row']
        assert own['qualified'][row] and not own['entry_reset'][row]
        tested = gate_decision(candidate, config['gate'], own, peer, feature, selection)
        record = deepcopy(candidate)
        normal_row = int(own['normal_execution_row'][row])
        record.update(gate=config['gate'], entry_id=config['id'], accepted=tested['accepted'],
            mode=tested['mode'], peer_used=tested['peer_used'], peer_status=tested['status'], peer=tested['peer'],
            raw_row=row, normal_row=None if normal_row < 0 else normal_row)
        levels = record.get('support_prices', [record['support_price']])
        chosen = [history for history in record['self_lineages'] if history['support_price'] == record['support_price']]
        assert chosen
        record['selected_support_roots'] = [dict(family=history['family'], anchor_raw_seq=history['anchor_raw_seq'],
                                                support_price=history['support_price']) for history in chosen]
        record['all_support_prices'] = levels
        candidate_records.append(record)
        if tested['accepted']:
            assert event[row] == 0
            event[row], support[row] = candidate['side'], candidate['support_price']
            decisions.append(record)
    normal_decisions = []
    for value in decisions:
        if value['normal_row'] is not None:
            row = deepcopy(value)
            row['row'] = row['normal_row']
            normal_decisions.append(row)
    raw_value = dict(entry_id=config['id'], event=event, support_price=support, decisions=decisions,
                     entry_quality=own['entry_quality'], entry_reset=own['entry_reset'])
    normal_value = dict(entry_id=config['id'], execution_to_raw_index=mapping,
        event=event[mapping].copy(), support_price=support[mapping].copy(), decisions=normal_decisions,
        entry_quality=normal['entry_quality'], entry_reset=normal['entry_reset'])
    assert np.count_nonzero(normal_value['event']) == len(normal_decisions)
    return dict(config=dict(config), raw=raw_value, normal=normal_value, candidates=candidate_records)


def prepared_session(activity_payload: dict, execution_records: dict) -> dict:
    """
    機能: 根が一度ロードした103活動一場と旧執行recordから、全19入口を準備する。
    引数: activity_payload(dict)は不変cache、execution_records(dict[symbol,dict])は旧baseの正常執行資格。
    返り値: dictはraw/normal/peer_features/cases。cache・原本・NPZ・金融・APIを暗黙ロードしない。
    """
    assert activity_payload['schema_version'] == 1
    assert set(activity_payload['accounts']) == set(execution_records) == set(core.SYMBOLS)
    accounts = activity_payload['accounts']
    restored = {symbol: core.restore_account(accounts[symbol], execution_records[symbol]) for symbol in core.SYMBOLS}
    public = {symbol: core.publications(restored[symbol]['raw']) for symbol in core.SYMBOLS}
    features = {symbol: prices.build(restored[symbol]['raw'], restored[symbol]['item'], public[symbol], POLICY) for symbol in core.SYMBOLS}
    selections = {}
    for symbol in core.SYMBOLS:
        other = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
        selections[symbol] = core.peer_rows(restored[symbol]['raw'], restored[other]['raw'], public[other])
        if 'C1' in accounts[symbol]['pulses'] and 'peer_rows' in accounts[symbol]['pulses']['C1']:
            np.testing.assert_array_equal(selections[symbol]['rows'], accounts[symbol]['pulses']['C1']['peer_rows'])
    common = {symbol: {family: core.single_candidates(accounts[symbol], restored[symbol]['raw'], family) for family in ('C', 'R')}
              for symbol in core.SYMBOLS}
    for symbol in core.SYMBOLS:
        common[symbol]['U'] = core.union_candidates(accounts[symbol], restored[symbol]['raw'])
    result = dict(schema_version=1, session=activity_payload['session'],
        raw={symbol: restored[symbol]['raw'] for symbol in core.SYMBOLS},
        normal={symbol: restored[symbol]['normal'] for symbol in core.SYMBOLS},
        items={symbol: restored[symbol]['item'] for symbol in core.SYMBOLS},
        peer_features=features, common_candidates=common, cases={}, policy=dict(POLICY))
    for config in core.entries():
        result['cases'][config['id']] = {}
        for symbol in core.SYMBOLS:
            other = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
            result['cases'][config['id']][symbol] = filter_case(config, common[symbol][config['family']],
                restored[symbol]['raw'], restored[other]['raw'], features[other], selections[symbol], restored[symbol]['normal'])
    assert len(result['cases']) == 19
    return result
