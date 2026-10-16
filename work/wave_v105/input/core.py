"""不変104の正常列・入口を接続し、105の軽量候補特徴だけを付加する。"""

from copy import deepcopy
import importlib.util
import math
from pathlib import Path
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SYMBOLS = ('TOPIX', 'NK225')
ENTRIES = ('C_OWN', 'C_N30', 'U_P10')
TREND_WIDTH_FRACTION = .004
_spec = importlib.util.spec_from_file_location('105入力の当時特徴専用', HERE/'features.py')
features = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = features
_spec.loader.exec_module(features)


def trend_width(reference_open: float, tick: float) -> float:
    """
    機能: 旧90.prepareにある固定G0の追尾幅式だけを再現する。
    引数: reference_open/tick(float)は当時既知始値と旧執行呼値。
    返り値: floatはmax(2,ceil(始値*.004/呼値-1e-10))*呼値。新出口の幅を推測しない。
    """
    assert np.isfinite(reference_open) and reference_open > 0 and np.isfinite(tick) and tick > 0
    return max(2, math.ceil(reference_open*TREND_WIDTH_FRACTION/tick-1e-10))*tick


def opening_value(reference: dict, record: dict) -> float:
    """
    機能: 小metadataに保存された既知始値の利用可能時点を確認する。
    引数: reference(dict)はref_open、record(dict)は不変正常執行列。
    返り値: floatは保存実値。後発OpeningPrice又は初回価格からの推測は禁止する。
    """
    assert reference['known_from_i'] == 0 and len(record['seq']) > 0
    assert reference['source_seq'] <= int(record['seq'][0])
    assert reference['source_time'] <= float(record['time_s'][0])
    assert reference['reference_time'] <= reference['source_time']
    value = float(reference['value'])
    assert np.isfinite(value) and value > 0
    return value


def minimum_anchors(case: dict) -> np.ndarray:
    """
    機能: 採用済み各入口の全選択支持根拠から最古のanchor原seqを展開する。
    引数: case(dict)は変更しない旧normal入口と当時decisions。
    返り値: ndarray[int64]は同一正常行の最小原seq。非発火は-1で根拠を創作しない。
    """
    event = case['event']
    result = np.full(len(event), -1, np.int64)
    for decision in case['decisions']:
        row = int(decision['row'])
        assert decision['normal_row'] == row and event[row] == decision['side'] and result[row] == -1
        roots = decision['selected_support_roots']
        assert roots and all(float(root['support_price']) == float(decision['support_price']) for root in roots)
        anchors = [int(root['anchor_raw_seq']) for root in roots]
        assert all(0 <= value <= int(decision['raw_seq']) for value in anchors)
        result[row] = min(anchors)
    np.testing.assert_array_equal(result >= 0, event != 0)
    return result


def build_session(packet: dict, references: dict | None = None,
                  saved_prepared: dict | None = None) -> dict:
    """
    機能: 一場の既存104packetから、同じ正常執行入力と三入口の当時特徴を作る。
    引数: packet(dict)、references(dict|None)は商品別ref_open、saved_prepared(dict|None)は追加Dayの既prepared。
    返り値: dictはprepared/cases/features/raw_features。旧入口bool・売買イベント・根拠は変更しない。
    """
    assert packet['schema_version'] == 1 and set(packet['normal']) == set(packet['raw']) == set(SYMBOLS)
    assert packet['policy']['max_public_gap_seconds'] == packet['policy']['baseline_extra_age_seconds'] == 15.
    assert references is not None or saved_prepared is not None
    output = dict(schema_version=1, session=packet['session'], prepared={}, cases={},
        features={}, raw_features={}, opening_provenance={}, checks={})
    for symbol in SYMBOLS:
        record, raw = packet['normal'][symbol]['record'], packet['raw'][symbol]
        mapping = raw['execution_to_raw_index']
        np.testing.assert_array_equal(record['seq'], raw['raw_seq'][mapping])
        np.testing.assert_array_equal(record['time_s'], raw['price_time_s'][mapping])
        for name in ('bid', 'ask'):
            np.testing.assert_array_equal(record[name], raw[name][mapping])
        assert record['quote_valid'].dtype == record['price_valid'].dtype == np.bool_
        assert all(record[name].shape == record['seq'].shape for name in ('time_s', 'price', 'bid', 'ask', 'quote_valid', 'price_valid'))
        if saved_prepared is not None:
            saved = saved_prepared[packet['session'], symbol]
            for name, value in record.items():
                if isinstance(value, np.ndarray):
                    np.testing.assert_array_equal(saved['record'][name], value)
                else:
                    assert saved['record'][name] == value
            reference_open = float(saved['reference_open'])
            width = trend_width(reference_open, float(record['tick']))
            assert width == saved['signal']['trend_width']
            output['opening_provenance'][symbol] = dict(kind='同場保存済み完全prepared実値',
                reference_open=reference_open, width_actual_equal=True)
        else:
            reference = references[symbol]
            reference_open = opening_value(reference, record)
            width = trend_width(reference_open, float(record['tick']))
            output['opening_provenance'][symbol] = deepcopy(reference)
        output['prepared'][symbol] = dict(record=record, reference_open=reference_open, signal=dict(trend_width=width))
    # ----------------------------------------
    for entry in ENTRIES:
        output['cases'][entry], output['features'][entry], output['raw_features'][entry] = {}, {}, {}
        for symbol in SYMBOLS:
            original = packet['cases'][entry][symbol]
            normal = dict(original['normal'])
            normal['selected_support_anchor_min_raw_seq'] = minimum_anchors(normal)
            output['cases'][entry][symbol] = normal
            measured, raw_measured = {}, {}
            for candidate in original['candidates']:
                value = features.candidate_features(packet, symbol, candidate)
                raw_row = int(candidate['raw_row'])
                assert raw_row not in raw_measured
                raw_measured[raw_row] = value
                if candidate['normal_row'] is not None:
                    normal_row = int(candidate['normal_row'])
                    assert normal_row not in measured
                    assert normal['execution_to_raw_index'][normal_row] == raw_row
                    measured[normal_row] = value
            accepted_rows = {int(value['row']) for value in normal['decisions']}
            assert all(row in measured and measured[row]['accepted_104'] for row in accepted_rows)
            assert set(np.flatnonzero(normal['event'])) == accepted_rows
            output['features'][entry][symbol], output['raw_features'][entry][symbol] = measured, raw_measured
    output['checks'] = dict(normal_record_exact=True, original_case_fields_exact=True,
        selected_support_roots_preserved=True, thresholds_applied=0, financial_replay=0,
        reference_from_saved_input=True, complete_legacy_signal_reconstructed=False)
    return output
