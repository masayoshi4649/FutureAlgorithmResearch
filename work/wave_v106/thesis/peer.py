"""保存104の公表価格窓を、同一原行の正常執行時計へstrict過去で投影する。"""

import numpy as np


def project(packet: dict, record: dict, symbol: str, window: int) -> dict:
    """
    機能: 既存相手窓をstrict過去・鮮度15秒で自己normal行へ対応させる。
    引数: packet(dict)は不変104peer、record(dict)は同normal、symbol(str)、window(int)は10/30。
    返り値: dictは方向・既知資格・自己資格とfloat/int64系譜。未来の同時計を救済しない。
    """
    assert window in (10, 30) and symbol in ('TOPIX', 'NK225')
    raw = packet['raw'][symbol]
    mapping = raw['execution_to_raw_index']
    np.testing.assert_array_equal(raw['raw_seq'][mapping], record['seq'])
    np.testing.assert_array_equal(raw['price_time_s'][mapping], record['time_s'])
    for name in ('bid', 'ask'):
        np.testing.assert_array_equal(raw[name][mapping], record[name])
    self_known = (raw['bbo_valid'][mapping] & (raw['price_reset_reason'][mapping] == 0)
                  & ~raw['clock_or_sequence_invalid'][mapping] & record['quote_valid'])
    other = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
    measured = packet['peer_features'][other]['windows'][str(window)]
    published = measured['source_time_s']
    assert np.all(np.isfinite(published)) and np.all(np.diff(published) > 0)
    selected = np.searchsorted(published, record['time_s'], side='left') - 1
    n = len(selected)
    direction, known = np.full(n, 3, np.int8), np.zeros(n, bool)
    floats, integers = np.full((n, 6), np.nan), np.full((n, 4), -1, np.int64)
    rows = np.flatnonzero(selected >= 0)
    if len(rows):
        indexes = selected[rows]
        age = record['time_s'][rows] - published[indexes]
        source_rows = measured['public_rows'][indexes]
        reference_rows = measured['reference_raw_row'][indexes]
        direction[rows] = measured['direction_t1'][indexes]
        known[rows] = ((age > 0.) & (age <= 15.)
                       & (measured['unknown_reason'][indexes] == 0)
                       & ~measured['ambiguous'][indexes])
        floats[rows] = np.column_stack((published[indexes], age,
            measured['bid_change_ticks'][indexes], measured['ask_change_ticks'][indexes],
            measured['reference_time_s'][indexes], measured['current_spread_ticks'][indexes]))
        integers[rows] = np.column_stack((measured['source_raw_seq'][indexes],
            measured['reference_raw_seq'][indexes], source_rows, reference_rows)).astype(np.int64)
    assert np.all(floats[known, 0] < record['time_s'][known])
    assert np.all((floats[known, 1] > 0) & (floats[known, 1] <= 15.))
    return dict(self_known=self_known, direction=direction, known=known,
        float_lineage=floats, integer_lineage=integers,
        float_columns=['peer_time','peer_age','bid_change_ticks','ask_change_ticks','reference_time','spread_ticks'],
        integer_columns=['peer_raw_seq','peer_reference_raw_seq','peer_raw_row','peer_reference_raw_row'],
        peer_window=window, preserved_104_unknown=True)


def prepared_session(light: dict, packet: dict) -> dict:
    """
    機能: 完成106の正常入力・三入口へ当時の相手価格列だけを接続する。
    引数: light(dict)は完成106入力、packet(dict)は同場の保存104peer。
    返り値: dictはprepared/cases/peers。旧入口と正常経済列は同じ配列参照で保持する。
    """
    assert light['session'] == packet['session'] and light['schema_version'] == 1
    result = dict(schema_version=1, session=light['session'], prepared=light['prepared'],
        cases=light['cases'], peers={})
    for symbol in ('TOPIX', 'NK225'):
        result['peers'][symbol] = {str(window): project(packet,
            light['prepared'][symbol]['record'], symbol, window) for window in (10, 30)}
    return result
