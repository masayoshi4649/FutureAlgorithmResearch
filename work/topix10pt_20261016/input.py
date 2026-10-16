"""現在値の原順観測と、次の正常価格で公開する1分足を分離する。"""

from datetime import datetime, timedelta, timezone
from io import BytesIO
import hashlib
import json
import math
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
JST = timezone(timedelta(hours=9))
PRICE_REASONS = {1: '価格時計不明', 2: '現在値不明又は非正', 4: '場開始前',
                 8: '観測窓終了以後', 16: '採用済最大価格時計より古い'}
BOOK_REASONS = {1: '買気配非有限', 2: '売気配非有限', 4: '買気配非正',
                8: '売気配非正', 16: '気配同値', 32: '買気配が売気配を超過',
                64: '買最良数量不明又は非正', 128: '売最良数量不明又は非正'}


# ----------------------------------------


def finite(value: object) -> float:
    """
    機能: 原値の有限数値だけを保持し、欠測・boolをNaNへ区別する。
    引数: value(object) はJSONの値。
    返り値: float は有限数値又はNaN。欠測を前値や0で救済しない。
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
    機能: timezone付き原時計だけをepoch秒へ変換する。
    引数: value(object) は日時文字列。
    返り値: float はepoch秒又はNaN。物理的受信時刻は作らない。
    """
    if not isinstance(value, str) or not value:
        return math.nan
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return math.nan
        number = parsed.timestamp()
    except (ValueError, TypeError, OverflowError, OSError):
        return math.nan
    return number if math.isfinite(number) else math.nan


def bounds(session: str) -> tuple[float, float]:
    """
    機能: 場IDから従来と同じ排他的観測窓を求める。
    引数: session(str) は開始日_Day又は開始日_Night。
    返り値: tuple[float,float] は開始・終了epoch。Day08:45～15:40、Night17:00～翌05:55。
    """
    date, kind = session.rsplit('_', 1)
    assert kind in ('Day', 'Night')
    day = datetime.fromisoformat(date).replace(tzinfo=JST)
    if kind == 'Day':
        start, end = day.replace(hour=8, minute=45), day.replace(hour=15, minute=40)
    else:
        start = day.replace(hour=17)
        end = (day + timedelta(days=1)).replace(hour=5, minute=55)
    return start.timestamp(), end.timestamp()


def source_path(info: dict) -> Path:
    """
    機能: 固定済み入力の位置をプロジェクト配下の絶対pathへ解決する。
    引数: info(dict) はpathを含む小目録。
    返り値: Path は既存入力の位置。本文は読まない。
    """
    path = (ROOT / info['path']).resolve()
    assert path.is_relative_to(ROOT) and path.is_file()
    return path


def check_stat(path: Path, info: dict) -> tuple[int, int]:
    """
    機能: 本文の前後に使う固定サイズと更新時刻を検査する。
    引数: path(Path)、info(dict) は入力位置と固定目録。
    返り値: tuple[int,int] はサイズとmtime_ns。本文の二重読みを行わない。
    """
    stat = path.stat()
    if 'bytes' in info:
        assert stat.st_size == info['bytes']
    if 'mtime_ns' in info:
        assert stat.st_mtime_ns == info['mtime_ns']
    return stat.st_size, stat.st_mtime_ns


def check_digest(digest: str, info: dict) -> None:
    """
    機能: 読んだ同じbytesの指紋を既固定SHAがあれば照合する。
    引数: digest(str)、info(dict) は指紋と小目録。
    返り値: None。新JSONLで未固定のSHAを観測前から既知とは呼ばない。
    """
    expected = info.get('sha256', info.get('SHA256'))
    if expected is not None:
        assert digest == expected


def read_old(info: dict) -> dict:
    """
    機能: 旧44列NPZを一回読み、同一bytesのSHA検査後に全列を展開する。
    引数: info(dict) はpath・サイズ・SHA等の固定目録。
    返り値: dict[str,ndarray] は生成元と同じ44列。正常行逆写像を価格採用へ流用しない。
    """
    path = source_path(info)
    before = check_stat(path, info)
    payload = path.read_bytes()
    check_digest(hashlib.sha256(payload).hexdigest(), info)
    assert check_stat(path, info) == before
    with np.load(BytesIO(payload), allow_pickle=False) as saved:
        assert len(saved.files) == 44
        arrays = {name: saved[name].copy() for name in saved.files}
    assert np.asarray(arrays['raw_seq']).dtype == np.int64
    assert len(arrays['raw_seq']) > 0 and np.all(np.diff(arrays['raw_seq']) > 0)
    n = len(arrays['raw_seq'])
    mapping = arrays['execution_to_raw_index']
    inverse = arrays['normal_execution_row']
    assert inverse.dtype == np.int32 and inverse.shape == (n,)
    assert mapping.dtype == np.int64 and np.all((mapping >= 0) & (mapping < n))
    assert np.all(np.diff(mapping) > 0) and np.all(inverse >= -1)
    np.testing.assert_array_equal(mapping, np.flatnonzero(inverse >= 0))
    np.testing.assert_array_equal(inverse[mapping], np.arange(len(mapping), dtype=np.int32))
    return arrays


def parse_records(records: list[dict]) -> dict:
    """
    機能: 合成又は原JSONの原順から必要価格・表示数量・公表出来高を抽出する。
    引数: records(list[dict]) は順序を保持したJSON行。
    返り値: dict[str,ndarray] は未補完の最小原列。原行の並べ替え・欠落行の除去を行わない。
    """
    n = len(records)
    names = ('price_time_s', 'last', 'bid', 'ask', 'bid_qty', 'ask_qty', 'volume', 'volume_time_s')
    values = {name: np.full(n, np.nan, np.float64) for name in names}
    for name in ('bid_prices', 'ask_prices', 'bid_quantities', 'ask_quantities'):
        values[name] = np.full((n, 10), np.nan, np.float64)
    identity = None
    for row, raw in enumerate(records):
        assert isinstance(raw, dict)
        current = tuple(raw.get(key) for key in ('Symbol', 'SymbolName', 'Exchange'))
        assert all(value is not None for value in current)
        if identity is None:
            identity = current
        assert current == identity
        values['price_time_s'][row] = clock(raw.get('CurrentPriceTime'))
        values['last'][row] = finite(raw.get('CurrentPrice'))
        values['volume'][row] = finite(raw.get('TradingVolume'))
        values['volume_time_s'][row] = clock(raw.get('TradingVolumeTime'))
        for label, side in (('Buy', 'bid'), ('Sell', 'ask')):
            for level in range(10):
                item = raw.get(f'{label}{level + 1}')
                item = item if isinstance(item, dict) else {}
                values[f'{side}_prices'][row, level] = finite(item.get('Price'))
                values[f'{side}_quantities'][row, level] = finite(item.get('Qty'))
            values[side][row] = values[f'{side}_prices'][row, 0]
            values[f'{side}_qty'][row] = values[f'{side}_quantities'][row, 0]
    values['raw_seq'] = np.arange(n, dtype=np.int64)
    return values


def volume_contract(arrays: dict, start: float, end: float) -> tuple[np.ndarray, np.ndarray]:
    """
    機能: 新JSONLにも103＋v2と同じ公開出来高差の使用資格を構成する。
    引数: arrays(dict[str,ndarray])、start/end(float) は原列と観測窓。
    返り値: tuple[ndarray[bool],ndarray[float64]] は使用資格と差。出来高時計を価格時計と同一視しない。
    """
    pt, vt, volume = (arrays[key] for key in ('price_time_s', 'volume_time_s', 'volume'))
    n = len(pt)
    usable, delta = np.zeros(n, np.bool_), np.full(n, np.nan, np.float64)
    if n == 0:
        return usable, delta
    pmax = np.maximum.accumulate(np.where(np.isfinite(pt), pt, -np.inf))
    vmax = np.maximum.accumulate(np.where(np.isfinite(vt), vt, -np.inf))
    reverse_price = np.zeros(n, np.bool_)
    reverse_price[1:] = np.isfinite(pt[1:]) & (pt[1:] < pmax[:-1])
    reverse_volume = np.zeros(n, np.bool_)
    reverse_volume[1:] = np.isfinite(vt[1:]) & (vt[1:] < vmax[:-1])
    row_ok = np.isfinite(volume) & (volume >= 0) & np.isfinite(vt) & (vt >= start) & (vt < end)
    if n > 1:
        observed = volume[1:] - volume[:-1]
        known = row_ok[1:] & row_ok[:-1] & ~reverse_volume[1:] & ~reverse_volume[:-1] & (observed >= 0)
        known &= arrays['raw_seq'][1:] == arrays['raw_seq'][:-1] + 1
        price_ok = np.isfinite(pt) & (pt >= start) & (pt < end)
        usable[1:] = known & price_ok[1:] & price_ok[:-1] & (vt[1:] <= pt[1:]) & (vt[:-1] <= pt[:-1])
        usable[1:] &= ~reverse_price[1:] & ~reverse_price[:-1]
        delta[1:] = np.where(usable[1:], observed, np.nan)
    return usable, delta


def read_jsonl(info: dict) -> dict:
    """
    機能: 新場JSONLを一回読み、同じ行bytesから指紋と最小原列を作る。
    引数: info(dict) はpath、session、サイズ等の固定目録。
    返り値: dict は原列と読取metadata。原JSONが不正なら行を飛ばさず停止する。
    """
    path = source_path(info)
    before, digest = check_stat(path, info), hashlib.sha256()
    records, chunks, identity = [], [], None
    with path.open('rb') as stream:
        for line in stream:
            digest.update(line)
            assert line.strip()
            raw = json.loads(line.decode('utf-8'))
            assert isinstance(raw, dict)
            current = tuple(raw.get(key) for key in ('Symbol', 'SymbolName', 'Exchange'))
            assert all(value is not None for value in current)
            if identity is None:
                identity = current
            assert identity == current
            records.append(raw)
            if len(records) == 10000:
                chunks.append(parse_records(records))
                records.clear()
    assert check_stat(path, info) == before
    value = digest.hexdigest()
    check_digest(value, info)
    if records:
        chunks.append(parse_records(records))
    assert chunks, '空の原JSONLは正常な場入力として作成しません'
    arrays = {name: np.concatenate([item[name] for item in chunks], axis=0) for name in chunks[0]}
    arrays['raw_seq'] = np.arange(len(arrays['last']), dtype=np.int64)
    del records
    del chunks
    start, end = tuple(info['bounds']) if 'bounds' in info else bounds(info['session'])
    usable, delta = volume_contract(arrays, start, end)
    arrays['volume_delta_usable'], arrays['volume_delta'] = usable, delta
    arrays['_read_metadata'] = dict(path=info['path'], bytes=before[0], sha256=value,
                                    rows=len(arrays['raw_seq']), reads=1)
    return arrays


# ----------------------------------------


def book_reasons(arrays: dict) -> np.ndarray:
    """
    機能: 最良気配と数量の異常を価格現在値とは別のbitへ分類する。
    引数: arrays(dict[str,ndarray]) は原列。
    返り値: ndarray[uint16] は非有限・非正・同値・逆転・数量異常の併存可能な理由。
    """
    bid, ask, bq, aq = (arrays[key] for key in ('bid', 'ask', 'bid_qty', 'ask_qty'))
    mask = np.zeros(len(bid), np.uint16)
    for condition, bit in (
        (~np.isfinite(bid), 1), (~np.isfinite(ask), 2),
        (np.isfinite(bid) & (bid <= 0), 4), (np.isfinite(ask) & (ask <= 0), 8),
        (np.isfinite(bid) & np.isfinite(ask) & (bid == ask), 16),
        (np.isfinite(bid) & np.isfinite(ask) & (bid > ask), 32),
        (~np.isfinite(bq) | (bq <= 0), 64), (~np.isfinite(aq) | (aq <= 0), 128)):
        mask[condition] |= bit
    return mask


def mean_by_bucket(values: np.ndarray, valid: np.ndarray, bucket: np.ndarray, size: int) -> tuple[np.ndarray, np.ndarray]:
    """
    機能: 有限な観測だけの分別平均と有効観測数を計算する。
    引数: values(ndarray)、valid(ndarray[bool])、bucket(ndarray[int])、size(int) は値・資格・分・全分数。
    返り値: tuple[ndarray,ndarray] は平均と件数。観測なしはNaN。
    """
    selected = valid & np.isfinite(values)
    count = np.bincount(bucket[selected], minlength=size).astype(np.int64)
    total = np.bincount(bucket[selected], weights=values[selected], minlength=size)
    result = np.full(size, np.nan, np.float64)
    np.divide(total, count, out=result, where=count > 0)
    return result, count


def prepare_session(arrays: dict, start: float, end: float, tick: float = 0.5) -> dict:
    """
    機能: 原順現在値を採用し、次分の正常現在値が来た原行で以前の1分足を公開する。
    引数: arrays(dict[str,ndarray])、start/end(float)、tick(float) は原列・排他的観測窓・観測呼値。
    返り値: dict はbars/prices/diagnostics。空分・未確定足を補完せず、気配異常だけで現在値を切らない。
    """
    assert math.isfinite(start) and math.isfinite(end) and start < end
    assert start % 60 == 0 and end % 60 == 0 and math.isfinite(tick) and tick > 0
    names = ('raw_seq', 'price_time_s', 'last', 'bid', 'ask', 'bid_qty', 'ask_qty',
             'bid_prices', 'ask_prices', 'bid_quantities', 'ask_quantities', 'volume_delta_usable', 'volume_delta')
    n = len(arrays['raw_seq'])
    assert arrays['raw_seq'].dtype == np.int64 and np.all(np.diff(arrays['raw_seq']) > 0)
    for name in names:
        value = arrays[name]
        assert isinstance(value, np.ndarray)
        assert value.shape == ((n, 10) if name in ('bid_prices', 'ask_prices', 'bid_quantities', 'ask_quantities') else (n,))
    pt, last = arrays['price_time_s'], arrays['last']
    base = np.isfinite(pt) & np.isfinite(last) & (last > 0) & (pt >= start) & (pt < end)
    highest = np.maximum.accumulate(np.where(base, pt, -np.inf))
    previous_highest = np.concatenate(([-np.inf], highest[:-1])) if n else np.empty(0)
    accepted = base & (pt >= previous_highest)
    reason = np.zeros(n, np.uint16)
    for condition, bit in ((~np.isfinite(pt), 1), (~np.isfinite(last) | (last <= 0), 2),
                           (np.isfinite(pt) & (pt < start), 4), (np.isfinite(pt) & (pt >= end), 8),
                           (base & (pt < previous_highest), 16)):
        reason[condition] |= bit
    row = np.flatnonzero(accepted).astype(np.int64)
    prices = dict(raw_row_index=row, raw_seq=arrays['raw_seq'][row].copy(),
                  price_time_s=pt[row].astype(np.float64), last=last[row].astype(np.float64))
    assert np.all(np.diff(prices['price_time_s']) >= 0)
    size = int((end - start) // 60)
    bars = {name: np.full(size, np.nan, np.float64) for name in (
        'open', 'high', 'low', 'close', 'volume', 'book_imbalance', 'book_depth', 'book_ofi',
        'anchor', 'pub_price_time_s', 'book_valid_fraction')}
    bars['t_s'] = start + 60 * np.arange(1, size + 1, dtype=np.float64)
    for name in ('valid', 'volume_known', 'book_quote_valid', 'closed'):
        bars[name] = np.zeros(size, np.bool_)
    for name in ('pub_raw_row', 'pub_raw_seq', 'last_raw_row'):
        bars[name] = np.full(size, -1, np.int64)
    for name in ('observations', 'book_flow_count', 'book_depth_count'):
        bars[name] = np.zeros(size, np.int64)
    book_mask = book_reasons(arrays)
    if len(row):
        bucket = ((pt[row] - start) // 60).astype(np.int64)
        unique, first, count = np.unique(bucket, return_index=True, return_counts=True)
        final = first + count - 1
        bars['open'][unique] = last[row[first]]
        bars['close'][unique] = last[row[final]]
        bars['high'][unique] = np.maximum.reduceat(last[row], first)
        bars['low'][unique] = np.minimum.reduceat(last[row], first)
        bars['observations'][unique] = count
        bars['last_raw_row'][unique] = row[final]
        bars['valid'][unique] = True

        # ----------------------------------------
        # 現在値を採用した原行だけをその分へ帰属させ、出来高と板の資格は別に集計する。
        usable = arrays['volume_delta_usable'][row]
        delta = arrays['volume_delta'][row]
        assert usable.dtype == np.bool_
        assert np.all(np.isfinite(delta[usable]) & (delta[usable] >= 0))
        bad_volume = np.bincount(bucket[~usable], minlength=size)
        volume = np.bincount(bucket[usable], weights=delta[usable], minlength=size)
        bars['volume_known'] = (bars['observations'] > 0) & (bad_volume == 0)
        bars['volume'][bars['volume_known']] = volume[bars['volume_known']]
        quote = book_mask[row] == 0
        good_count = np.bincount(bucket[quote], minlength=size)
        np.divide(good_count, bars['observations'], out=bars['book_valid_fraction'], where=bars['observations'] > 0)
        bid, ask, bq, aq = (arrays[key][row] for key in ('bid', 'ask', 'bid_qty', 'ask_qty'))
        imbalance = np.full(len(row), np.nan)
        scale = np.maximum(bq[quote], aq[quote])
        qb, qa = bq[quote] / scale, aq[quote] / scale
        imbalance[quote] = (qb - qa) / (qb + qa)
        bars['book_imbalance'], _ = mean_by_bucket(imbalance, quote, bucket, size)
        depth_totals = []
        all_quantity = np.concatenate((arrays['bid_quantities'][row], arrays['ask_quantities'][row]), axis=1)
        quantity_scale = np.max(np.where(np.isfinite(all_quantity) & (all_quantity >= 0), all_quantity, 0), axis=1)
        quantity_scale[quantity_scale == 0] = 1
        for side, best in (('bid', bid), ('ask', ask)):
            levels = arrays[f'{side}_prices'][row]
            quantities = arrays[f'{side}_quantities'][row]
            direction = -1 if side == 'bid' else 1
            distance = direction * (levels - best[:, None]) / tick
            good = np.isfinite(levels) & (levels > 0) & np.isfinite(quantities) & (quantities >= 0) & (distance >= 0)
            weighted = np.zeros_like(levels)
            np.divide(quantities / quantity_scale[:, None], 1 + distance, out=weighted, where=good)
            depth_totals.append(np.sum(weighted, axis=1))
        db, da = depth_totals
        depth_ok = quote & np.isfinite(db) & np.isfinite(da) & ((db + da) > 0)
        depth = np.full(len(row), np.nan)
        depth[depth_ok] = (db[depth_ok] - da[depth_ok]) / (db[depth_ok] + da[depth_ok])
        bars['book_depth'], bars['book_depth_count'] = mean_by_bucket(depth, depth_ok, bucket, size)
        flow = np.full(len(row), np.nan)
        flow_ok = np.zeros(len(row), np.bool_)
        flow_ok[1:] = quote[1:] & quote[:-1] & (bucket[1:] == bucket[:-1]) & (row[1:] == row[:-1] + 1)
        flow_ok[1:] &= arrays['raw_seq'][row[1:]] == arrays['raw_seq'][row[:-1]] + 1
        indexes = np.flatnonzero(flow_ok)
        prev = indexes - 1
        flow[indexes] = ((bid[indexes] >= bid[prev]) * bq[indexes] - (bid[indexes] <= bid[prev]) * bq[prev]
                         - (ask[indexes] <= ask[prev]) * aq[indexes] + (ask[indexes] >= ask[prev]) * aq[prev])
        assert np.isfinite(flow[indexes]).all(), '有効flowの加減算が有限範囲を超えました'
        bars['book_flow_count'] = np.bincount(bucket[flow_ok], minlength=size).astype(np.int64)
        total_flow = np.bincount(bucket[flow_ok], weights=flow[flow_ok], minlength=size)
        absolute_flow = np.bincount(bucket[flow_ok], weights=np.abs(flow[flow_ok]), minlength=size)
        np.divide(total_flow, absolute_flow, out=bars['book_ofi'], where=absolute_flow > 0)
        bars['book_quote_valid'] = (bars['book_valid_fraction'] >= .8) & (bars['book_flow_count'] >= 1)

        # ----------------------------------------
        # 境界を知らせる当行は以前の足へ混ぜず、最後の実在足だけの予測起点とする。
        transitions = np.concatenate(([0], np.flatnonzero(np.diff(bucket) > 0) + 1))
        closed_until = 0
        for point in transitions:
            current = int(bucket[point])
            if current > closed_until:
                bars['closed'][closed_until:current] = True
                bars['pub_raw_row'][closed_until:current] = row[point]
                bars['pub_raw_seq'][closed_until:current] = arrays['raw_seq'][row[point]]
                bars['pub_price_time_s'][closed_until:current] = pt[row[point]]
                previous = int(bucket[point - 1]) if point > 0 else -1
                if previous >= 0:
                    bars['anchor'][previous] = last[row[point]]
                closed_until = current
        bars['valid'] &= bars['closed']
        bars['volume_known'] &= bars['valid']
        bars['book_quote_valid'] &= bars['valid']
        for name in ('open', 'high', 'low', 'close', 'volume', 'book_imbalance', 'book_depth', 'book_ofi', 'book_valid_fraction'):
            bars[name][~bars['valid']] = np.nan
        bars['anchor'][~bars['valid']] = np.nan
        bars['last_raw_row'][~bars['closed']] = -1
        for name in ('observations', 'book_flow_count', 'book_depth_count'):
            bars[name][~bars['closed']] = 0
    complete = np.isfinite(pt) & np.isfinite(last) & (last > 0) & (pt >= end) & (pt >= previous_highest)
    diagnostics = dict(raw_rows=n, accepted_prices=int(len(row)),
        skipped_prices=int(n - len(row)), stale_clock_rows=int(np.count_nonzero(reason & 16)),
        raw_seq_gaps=int(np.count_nonzero(np.diff(arrays['raw_seq']) != 1)),
        same_clock_accepted=int(np.count_nonzero(np.diff(prices['price_time_s']) == 0)),
        window_complete=bool(np.any(complete)), published_real_bars=int(np.count_nonzero(bars['valid'])),
        unpublished_minutes=int(np.count_nonzero(~bars['closed'])),
        published_empty_minutes=int(np.count_nonzero(bars['closed'] & ~bars['valid'])),
        price_reasons={str(bit): int(np.count_nonzero(reason & bit)) for bit in PRICE_REASONS},
        book_reasons_raw={str(bit): int(np.count_nonzero(book_mask & bit)) for bit in BOOK_REASONS},
        book_reasons_accepted={str(bit): int(np.count_nonzero(book_mask[row] & bit)) for bit in BOOK_REASONS},
        book_quote_valid_bars=int(np.count_nonzero(bars['book_quote_valid'])),
        note='価格時計による後ずらし公開。受信時計や実約定の証明ではない。気配/数量不正で現在値を打ち切らない。')
    return dict(bars=bars, prices=prices, diagnostics=diagnostics)


def strict_peer_join(own: dict, peer: dict) -> np.ndarray:
    """
    機能: 自己の分末より1分以上前で、自己公開時計までに公開済みの相手確定足を選ぶ。
    引数: own/peer(dict[str,ndarray]) は自己・相手のbars。
    返り値: ndarray[int64] は相手足index又は−1。受信時計順の証明や未来足の同時参照はしない。
    """
    result = np.full(len(own['t_s']), -1, np.int64)
    indexes = np.flatnonzero(peer['valid'] & np.isfinite(peer['pub_price_time_s']))
    if not len(indexes):
        return result
    times, published = peer['t_s'][indexes], peer['pub_price_time_s'][indexes]
    assert np.all(np.diff(times) > 0) and np.all(np.diff(published) >= 0)
    for row in np.flatnonzero(own['valid'] & np.isfinite(own['anchor']) & np.isfinite(own['pub_price_time_s'])):
        cutoff = own['t_s'][row] - 60
        before_time = int(np.searchsorted(times, cutoff, side='right'))
        before_publication = int(np.searchsorted(published, own['pub_price_time_s'][row], side='right'))
        position = min(before_time, before_publication) - 1
        if position >= 0:
            result[row] = indexes[position]
    return result
