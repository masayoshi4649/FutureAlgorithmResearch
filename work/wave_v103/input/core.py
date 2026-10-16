"""価格代理時計、公開出来高時計及び表示板を原行順のまま分離保存する。"""

from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Iterable

import numpy as np

sys.dont_write_bytecode = True

PRICE_RESET = {1: '最初の原行', 2: '原seq断裂', 4: '価格代理時計不明',
               8: '価格代理時計逆行', 16: '価格代理時計が場外',
               32: '当該最良価格又は最良数量不正', 64: '前原行の価格系列使用不能'}
DEPTH_RESET = {**PRICE_RESET, 128: '当該十段表示不正', 256: '前原行の十段表示使用不能'}
LP_RESET = {1: '最初の原行', 2: '原seq断裂', 4: '価格代理時計不明',
            8: '価格代理時計逆行', 16: '価格代理時計が場外',
            32: '当該現在値不正', 64: '前原行の現在値系列使用不能'}
VOLUME_RESET = {1: '最初の原行', 2: '原seq断裂', 4: '累計出来高不明又は負',
                8: '出来高時計不明', 16: '出来高時計が場外',
                32: '累計出来高減少', 64: '出来高時計逆行', 128: '前原行の出来高使用不能'}
FLOAT_FIELDS = ('price_time_s', 'last', 'bid', 'ask', 'bid_qty', 'ask_qty',
                'volume', 'volume_time_s', 'trading_value', 'trading_value_time_s',
                'volume_delta_observed', 'volume_delta')
DEPTH_FIELDS = ('bid_prices', 'bid_quantities', 'ask_prices', 'ask_quantities')
DEPTH_FLAG_FIELDS = ('bid_element_valid', 'ask_element_valid')
BOOL_FIELDS = ('price_time_valid', 'in_session', 'last_valid', 'best_price_valid',
               'best_quantity_valid', 'depth_valid', 'price_row_valid', 'lp_row_valid',
               'price_transition_valid', 'depth_transition_valid',
               'volume_value_valid', 'volume_time_valid', 'volume_in_session',
               'volume_time_not_after_price', 'volume_delta_known', 'volume_delta_usable',
               'trading_value_valid', 'trading_value_time_known', 'received_at_present')
REASON_FIELDS = ('price_reset_reason', 'depth_reset_reason', 'lp_reset_reason', 'volume_reset_reason')


def finite(value: object) -> float:
    """
    機能: 実際に観測した有限数値を保持し、欠測やboolをNaNへ区別する。
    引数: value(object)はJSONの値。
    返り値: floatは観測数値又はNaN。負値や0の使用資格は別flagで判定する。
    """
    if isinstance(value, bool):
        return math.nan
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return math.nan
    return number if math.isfinite(number) else math.nan


def clock(value: object) -> float:
    """
    機能: timezone付き原時計をepoch秒へ変換し、不明時計を補完しない。
    引数: value(object)は日時文字列。
    返り値: floatはepoch秒又はNaN。実受信時計へ読み替えない。
    """
    if not isinstance(value, str) or not value:
        return math.nan
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            return math.nan
        number = stamp.timestamp()
    except (ValueError, TypeError, OverflowError, OSError):
        return math.nan
    return number if math.isfinite(number) else math.nan


def depth(raw: dict, label: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, bool]:
    """
    機能: 一方の十段を元段番号のまま取り出し、価格順序と各数量の資格を分ける。
    引数: raw(dict)、label(str:Buy/Sell)は原行と側。
    返り値: tuple[ndarray,ndarray,ndarray,bool]は価格、数量、段資格及び全段資格。
    欠落段や不正値を0へ救済せず、並べ替えや同価格の合算も行わない。
    """
    assert label in ('Buy', 'Sell')
    prices = np.full(10, np.nan, np.float64)
    quantities = prices.copy()
    for index in range(10):
        value = raw.get(f'{label}{index+1}')
        value = value if isinstance(value, dict) else {}
        prices[index] = finite(value.get('Price'))
        quantities[index] = finite(value.get('Qty'))
    valid = np.isfinite(prices) & (prices > 0) & np.isfinite(quantities) & (quantities >= 0)
    order = np.all(np.diff(prices) < 0) if label == 'Buy' else np.all(np.diff(prices) > 0)
    return prices, quantities, valid, bool(valid.all() and order)


def decode(raw: dict, start: float, end: float) -> dict:
    """
    機能: 原行の価格、板、出来高及び時計を別資格の観測値へ取り出す。
    引数: raw(dict)、start/end(float)は原行と排他的な場内上下限。
    返り値: dictは一行の観測。心理、成行方向及び約定消費を分類しない。
    """
    bp, bq, bv, bvalid = depth(raw, 'Buy')
    ap, aq, av, avalid = depth(raw, 'Sell')
    pt, vt = clock(raw.get('CurrentPriceTime')), clock(raw.get('TradingVolumeTime'))
    last, volume = finite(raw.get('CurrentPrice')), finite(raw.get('TradingVolume'))
    value, value_time = finite(raw.get('TradingValue')), clock(raw.get('TradingValueTime'))
    time_valid, volume_time_valid = math.isfinite(pt), math.isfinite(vt)
    best_price = bool(math.isfinite(bp[0]) and math.isfinite(ap[0]) and 0 < bp[0] < ap[0])
    best_quantity = bool(math.isfinite(bq[0]) and math.isfinite(aq[0]) and bq[0] > 0 and aq[0] > 0)
    inside = bool(time_valid and start <= pt < end)
    return dict(price_time_s=pt, last=last, bid=bp[0], ask=ap[0], bid_qty=bq[0], ask_qty=aq[0],
        bid_prices=bp, bid_quantities=bq, ask_prices=ap, ask_quantities=aq,
        bid_element_valid=bv, ask_element_valid=av,
        price_time_valid=time_valid, in_session=inside,
        last_valid=bool(math.isfinite(last) and last > 0),
        best_price_valid=best_price, best_quantity_valid=best_quantity,
        depth_valid=bool(bvalid and avalid and best_price and best_quantity),
        price_row_valid=bool(inside and best_price and best_quantity),
        lp_row_valid=bool(inside and math.isfinite(last) and last > 0),
        volume=volume, volume_time_s=vt,
        volume_value_valid=bool(math.isfinite(volume) and volume >= 0),
        volume_time_valid=volume_time_valid,
        volume_in_session=bool(volume_time_valid and start <= vt < end),
        volume_time_not_after_price=bool(time_valid and volume_time_valid and vt <= pt),
        trading_value=value, trading_value_time_s=value_time,
        trading_value_valid=bool(math.isfinite(value) and value >= 0),
        trading_value_time_known=math.isfinite(value_time),
        received_at_present=any(name in raw for name in ('ReceivedAt', 'received_at', 'receivedAt')))


def apply_transitions(row: dict, previous: dict | None, seq: int, previous_seq: int | None,
                      last_price_clock: float | None, last_volume_clock: float | None) -> dict:
    """
    機能: 公開原行の隣接関係だけで、価格・十段・現在値・出来高のresetを独立に判定する。
    引数: row/previous(dict|None)、seq/previous_seq(int|None)、
        last_price_clock/last_volume_clock(float|None)は現在行と過去観測。
    返り値: dictはresetと出来高差を追加した現在行。将来行及び相手市場は参照しない。
    """
    first = previous is None
    gap = previous_seq is not None and seq != previous_seq+1
    base = (1 if first else 0) | (2 if gap else 0)
    pt, vt = row['price_time_s'], row['volume_time_s']
    price_reverse = row['price_time_valid'] and last_price_clock is not None and pt < last_price_clock
    volume_reverse = row['volume_time_valid'] and last_volume_clock is not None and vt < last_volume_clock
    common_price = base | (0 if row['price_time_valid'] else 4) | (8 if price_reverse else 0) | (0 if row['in_session'] else 16)
    price_reason = common_price | (0 if row['best_price_valid'] and row['best_quantity_valid'] else 32)
    lp_reason = common_price | (0 if row['last_valid'] else 32)
    if previous is not None:
        previous_price_valid = previous['price_row_valid'] and not (previous['price_reset_reason'] & 8)
        previous_lp_valid = previous['lp_row_valid'] and not (previous['lp_reset_reason'] & 8)
        price_reason |= 0 if previous_price_valid else 64
        lp_reason |= 0 if previous_lp_valid else 64
    depth_reason = price_reason | (0 if row['depth_valid'] else 128)
    if previous is not None and not previous['depth_valid']:
        depth_reason |= 256
    volume_observation_valid = row['volume_value_valid'] and row['volume_in_session']
    volume_reason = base | (0 if row['volume_value_valid'] else 4) | (0 if row['volume_time_valid'] else 8)
    volume_reason |= 0 if row['volume_in_session'] else 16
    volume_reason |= 64 if volume_reverse else 0
    if previous is not None:
        previous_volume_valid = (previous['volume_value_valid'] and previous['volume_in_session']
                                 and not (previous['volume_reset_reason'] & 64))
        volume_reason |= 0 if previous_volume_valid else 128
        if previous['volume_value_valid'] and row['volume_value_valid'] and row['volume'] < previous['volume']:
            volume_reason |= 32
    known = previous is not None and volume_observation_valid and volume_reason == 0
    price_pair = (previous is not None and row['price_time_valid'] and previous['price_time_valid']
                  and row['in_session'] and previous['in_session'] and not price_reverse
                  and pt >= previous['price_time_s'] and not gap)
    usable = bool(known and price_pair and row['volume_time_not_after_price']
                  and previous['volume_time_not_after_price'])
    observed = float(row['volume'] - previous['volume']) if known else math.nan
    row.update(price_reset_reason=price_reason, depth_reset_reason=depth_reason,
        lp_reset_reason=lp_reason, volume_reset_reason=volume_reason,
        price_transition_valid=bool(previous is not None and price_reason == 0),
        depth_transition_valid=bool(previous is not None and depth_reason == 0),
        volume_delta_known=bool(known), volume_delta_usable=usable,
        volume_delta_observed=observed, volume_delta=observed if usable else math.nan)
    return row


def extract_rows(rows: Iterable[tuple[int, dict]], start: float, end: float,
                 normal_record: dict | None = None) -> tuple[dict, dict]:
    """
    機能: 全原行を保存順のまま抽出し、旧正常執行系列へ原seqで対応させる。
    引数: rows(Iterable[tuple[int,dict]])、start/end(float)、normal_record(dict|None)は旧執行入力。
    返り値: tuple[dict,dict]は型付き配列と取得診断。場外、不正板及び時計欠測行も保存する。
    """
    assert math.isfinite(start) and math.isfinite(end) and start < end
    columns = {name: [] for name in (*FLOAT_FIELDS, *DEPTH_FIELDS, *DEPTH_FLAG_FIELDS, *BOOL_FIELDS, *REASON_FIELDS)}
    sequences, previous, previous_seq, identity = [], None, None, None
    last_price_clock = last_volume_clock = None
    for seq, raw in rows:
        assert isinstance(seq, (int, np.integer)) and not isinstance(seq, bool) and seq >= 0
        assert previous_seq is None or seq > previous_seq, '原行の重複及び逆行は修復しません'
        assert isinstance(raw, dict)
        current_identity = tuple(raw.get(name) for name in ('Symbol', 'SymbolName', 'Exchange'))
        assert all(value is not None for value in current_identity), ('銘柄識別欠測', seq)
        if identity is None:
            identity = current_identity
        assert identity == current_identity, ('銘柄又は限月の混在', seq)
        row = apply_transitions(decode(raw, start, end), previous, int(seq), previous_seq,
                                last_price_clock, last_volume_clock)
        sequences.append(seq)
        for name in columns:
            columns[name].append(row[name])
        if row['price_time_valid']:
            last_price_clock = row['price_time_s'] if last_price_clock is None else max(last_price_clock, row['price_time_s'])
        if row['volume_time_valid']:
            last_volume_clock = row['volume_time_s'] if last_volume_clock is None else max(last_volume_clock, row['volume_time_s'])
        previous, previous_seq = row, int(seq)
    arrays = {name: np.asarray(values, dtype=np.float64 if name in (*FLOAT_FIELDS, *DEPTH_FIELDS)
                           else np.uint16 if name in REASON_FIELDS else bool)
              for name, values in columns.items()}
    for name in (*DEPTH_FIELDS, *DEPTH_FLAG_FIELDS):
        arrays[name] = arrays[name].reshape((-1, 10))
    arrays['raw_seq'] = np.asarray(sequences, np.int64)
    arrays['normal_execution_row'] = np.full(len(sequences), -1, np.int32)
    arrays['execution_to_raw_index'] = np.zeros(0, np.int64)
    if normal_record is not None:
        indexes = np.searchsorted(arrays['raw_seq'], normal_record['seq'])
        assert (indexes < len(sequences)).all()
        assert len(normal_record['seq']) == len(set(normal_record['seq']))
        for name, old in (('raw_seq', 'seq'), ('price_time_s', 'time_s'), ('last', 'price'), ('bid', 'bid'), ('ask', 'ask')):
            np.testing.assert_array_equal(arrays[name][indexes], normal_record[old])
        arrays['normal_execution_row'][indexes] = np.arange(len(indexes), dtype=np.int32)
        arrays['execution_to_raw_index'] = indexes.astype(np.int64)
    diagnosis = dict(raw_rows=len(sequences), normal_execution_rows=len(arrays['execution_to_raw_index']),
        identity=dict(zip(('Symbol', 'SymbolName', 'Exchange'), identity)) if identity is not None else None,
        all_raw_rows_retained=True, normal_seq_time_lp_bid_ask_equal=normal_record is not None,
        qualifications={name: int(arrays[name].sum()) for name in BOOL_FIELDS},
        resets={name: {str(bit): int(np.sum((arrays[name] & bit) != 0)) for bit in (
            PRICE_RESET if name == 'price_reset_reason' else DEPTH_RESET if name == 'depth_reset_reason'
            else LP_RESET if name == 'lp_reset_reason' else VOLUME_RESET)} for name in REASON_FIELDS},
        received_clock_used=False, inferred_aggressor_volume=False, trade_or_cancel_identified=False)
    return arrays, diagnosis


def extract_jsonl(path: Path, start: float, end: float, normal_record: dict) -> tuple[dict, dict]:
    """
    機能: 一原本を一度だけ読み、その読取と同時にSHAを取り全原行を抽出する。
    引数: path(Path)、start/end(float)、normal_record(dict)は原本と旧正常執行入力。
    返り値: tuple[dict,dict]は配列と原本指紋付き診断。生原本の二重hashは行わない。
    """
    hasher = hashlib.sha256()
    byte_count = 0

    def rows() -> Iterable[tuple[int, dict]]:
        """
        機能: 元の行をhashへ加え、同じバイト列をJSONとして一度だけ読む。
        引数: なし。
        返り値: Iterable[tuple[int,dict]]は原seqと原行。JSON不正は行を飛ばさず停止する。
        """
        nonlocal byte_count
        with path.open('rb') as stream:
            for seq, line in enumerate(stream):
                hasher.update(line)
                byte_count += len(line)
                yield seq, json.loads(line)

    arrays, diagnosis = extract_rows(rows(), start, end, normal_record)
    diagnosis.update(raw_SHA256=hasher.hexdigest(), raw_bytes=byte_count)
    assert byte_count == path.stat().st_size, '読取中の原本追記を検出しました'
    return arrays, diagnosis


def schema() -> dict:
    """
    機能: 保存列の型、形状及びreset理由と観測制限を明示する。
    引数: なし。
    返り値: dictは入力仕様。Nは全原行数、Mは旧正常執行行数。
    """
    fields = {name: dict(dtype='float64', shape=['N']) for name in FLOAT_FIELDS}
    fields.update({name: dict(dtype='float64', shape=['N', 10]) for name in DEPTH_FIELDS})
    fields.update({name: dict(dtype='bool', shape=['N', 10]) for name in DEPTH_FLAG_FIELDS})
    fields.update({name: dict(dtype='bool', shape=['N']) for name in BOOL_FIELDS})
    fields.update({name: dict(dtype='uint16', shape=['N']) for name in REASON_FIELDS})
    fields.update(raw_seq=dict(dtype='int64', shape=['N']), normal_execution_row=dict(dtype='int32', shape=['N']),
                  execution_to_raw_index=dict(dtype='int64', shape=['M']))
    return dict(version=1, columns=fields,
        price_reset_reason={str(bit): name for bit, name in PRICE_RESET.items()},
        depth_reset_reason={str(bit): name for bit, name in DEPTH_RESET.items()},
        lp_reset_reason={str(bit): name for bit, name in LP_RESET.items()},
        volume_reset_reason={str(bit): name for bit, name in VOLUME_RESET.items()},
        raw_seq='JSONLの0起点行番号。全原行を保存し、時計欠測/場外/不正板を削除しない。',
        price_time_s='CurrentPriceTimeからの価格代理時計。板更新の受信時刻ではない。',
        depth='Buy/Sell1〜10の元段番号。有限だが負の観測値も保持し、使用資格false。欠測はNaN。十段外を0としない。',
        volume_delta_known='隣接原行の両累計及び両出来高時計が同場で正常、非減少/非逆行、原seq連続のときだけTrue。',
        volume_delta_usable='knownに加え両価格時計が場内正常非逆行で、両行ともvolume_time_s<=price_time_sのときだけTrue。',
        volume_delta_observed='known時だけ公開累計差、他はNaN。支持へ使うにはusableが必要。',
        volume_delta='usable時だけ同累計差、他はNaN。不明は0へ補完しない。',
        trading_value='累計売買代金の観測値のみ。専用時計不明時に出来高時計との同時更新や成行方向を仮定しない。',
        normal_alignment='旧正常執行record.seq/time_s/price/bid/askと原行を全件一致させる。新資格で旧執行を正常化しない。',
        limitations=['真の共通受信時計と両市場の受信順は不明。', '表示減少の約定/取消及び同主体再発注は不明。',
                    '累計出来高と表示変化の同時観測は消費因果や方向別約定量の証明ではない。'],
        financial_execution=0, current_API=0, actual_orders=0)
