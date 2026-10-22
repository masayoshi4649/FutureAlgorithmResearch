"""解放済み価格・板・両市場の観測方向を、追跡短縮の根拠として生成する。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
_CACHE: dict = {}


def catalog() -> list[dict]:
    """機能: 損益参照前に決めた6機序×2窓の悪化根拠を返す。

    引数: なし。返り値: ID・説明・全数値条件の一覧 (list[dict])。
    符号は観測方向であり、保有方向と反対の場合だけ保有の悪化に該当する。
    """
    definitions = [
        ('price', '価格の方向反応', '窓全体と直近1/4窓の気配価格が同方向へ十分動いた。板数量を使わない。'),
        ('flow', '板フローの持続', 'OFIと距離重み付き板数量変化が一致し、1/2窓前にも同方向だった。価格確認は使わない。'),
        ('opposite', 'フローと逆の価格応答', '強いOFIと推定売買が同方向なのに、価格がその反対へ進んだ。吸収した主体や返済取引とは断定しない。'),
        ('dual_price', '両市場の価格反応', '自市場と60秒追加遅延した相手市場の価格反応が同方向だった。'),
        ('dual_flow', '両市場の板と価格', '両市場の価格反応に加え、OFIも同方向だった。両価格条件に対する板情報の追加価値を比較する。'),
        ('refill_then_price', '補充停滞後の逆価格', '1/2窓前に強いフロー・反対側補充・価格停滞を観測し、その後に価格が逆へ動いた。補充は取消後の再提示も含み得る。'),
    ]
    out = []
    for kind, name, description in definitions:
        for seconds in (120., 600.):
            out.append(dict(id=f'B{len(out):02d}', name=name + f'・{seconds / 60:g}分', family=kind,
                description=description, params=dict(kind=kind, window_seconds=seconds,
                short_fraction=.25, stage_fraction=.5, price_atr=.25, price_ticks=2.,
                short_atr=.10, short_ticks=1., ofi_threshold=.10, near_threshold=.05,
                trade_threshold=.15, refill_threshold=.20, stall_atr=.25, stall_ticks=1.,
                peer_delay_seconds=60., freshness_seconds=60., minimum_events=5)))
    return out


def clear_cache() -> None:
    """機能: 入力を切断・改変する検査の前に集計キャッシュを解放する。

    引数: なし。返り値: なし (None)。
    """
    _CACHE.clear()


def _positions(times: np.ndarray, targets: np.ndarray, freshness: float) -> np.ndarray:
    """機能: 目標時刻以前かつ許容鮮度以内の最後の公開イベント位置を返す。

    引数: times/targets (ndarray)、freshness (float)。返り値: 不在を-1とする位置 (ndarray[int64])。
    """
    index = np.searchsorted(times, targets, side='right').astype(np.int64) - 1
    valid = index >= 0
    if len(times):
        valid &= targets - times[np.maximum(index, 0)] <= freshness
    index[~valid] = -1
    return index


def _take(values: np.ndarray, positions: np.ndarray, missing: float | int = np.nan) -> np.ndarray:
    """機能: 有効な過去位置だけを取り出し、不在を指定値にする。

    引数: values/positions (ndarray)、missing (float|int)。返り値: 対応値 (ndarray)。
    """
    dtype = np.result_type(values.dtype, type(missing))
    out = np.full(len(positions), missing, dtype=dtype)
    valid = positions >= 0
    out[valid] = values[positions[valid]]
    return out


def _sign(values: np.ndarray, threshold: float | np.ndarray) -> np.ndarray:
    """機能: 正負対称の下限以上の観測値を方向化し、欠測を中立にする。

    引数: values (ndarray)、threshold (float|ndarray)。返り値: -1/0/+1 (ndarray[int8])。
    """
    return np.where(values >= threshold, 1, np.where(values <= -threshold, -1, 0)).astype(np.int8)


def _model(ready: dict, source: pd.DataFrame, params: dict) -> dict:
    """機能: 原本解放順の板特徴だけから、有限過去窓の価格とフローを作る。

    引数: ready/params (dict)、source (DataFrame)。返り値: 公開イベント列と参照位置 (dict)。
    長い解放遅延・窓内欠測・古い過去参照は根拠不足であり、悪化方向にはしない。
    """
    key = (id(ready), id(source), id(ready['atr']), len(ready['seq']), int(ready['seq'][-1]),
           tuple(sorted((k, v) for k, v in params.items() if k != 'kind')))
    if key in _CACHE:
        return _CACHE[key]
    required = ['time_s', 'seq', 'source_time_s', 'source_first_seq', 'source_last_seq', 'source_mid_last',
                'valid_event_count', 'ofi_signed', 'ofi_abs', 'dflow_near', 'trade_pos', 'trade_neg', 'refill_bid', 'refill_ask']
    assert all(column in source for column in required), '板特徴に必要列がありません'
    frame = source.loc[(source.seq <= ready['seq'][-1]) & (source.time_s <= ready['time_s'][-1]), required].copy()
    times = frame.time_s.to_numpy(float)
    seq = frame.seq.to_numpy(np.int64)
    assert np.all(np.diff(times) > 0) and np.all(np.diff(seq) > 0)
    assert (frame.source_first_seq <= frame.source_last_seq).all() and (frame.source_last_seq < frame.seq).all()
    assert (frame.source_time_s < frame.time_s).all()
    rows = np.searchsorted(ready['seq'], seq, side='left').astype(np.int64)
    assert np.all(rows < len(ready['seq']))
    assert np.array_equal(ready['seq'][rows], seq), '解放行が原本入力にありません'
    assert np.array_equal(ready['time_s'][rows], times), '解放時刻が原本行と一致しません'
    mid = frame.source_mid_last.to_numpy(float)
    atr = np.asarray(ready['atr'][rows], float)
    freshness, seconds = params['freshness_seconds'], params['window_seconds']
    assert np.isfinite(seconds) and seconds > 0
    usable = (np.isfinite(mid) & (mid > 0) & (frame.valid_event_count.to_numpy(float) > 0)
              & ((times - frame.source_time_s.to_numpy(float)) <= freshness))
    frame.index = pd.to_datetime(times, unit='s', utc=True)
    duration = pd.Timedelta(seconds=seconds)
    rolling_count = pd.Series(usable.astype(float), index=frame.index).rolling(duration).sum().to_numpy(float)
    gaps = np.r_[False, np.diff(times) > freshness] if len(times) else np.empty(0, bool)
    bad = pd.Series((~usable | gaps).astype(float), index=frame.index).rolling(duration).sum().to_numpy(float)

    def summed(column: str) -> np.ndarray:
        """機能: 利用可能な板数量だけを後方の時間窓で合計する。

        引数: column (str)。返り値: 窓合計 (ndarray[float])。
        """
        values = frame[column].where(usable)
        return values.rolling(duration, min_periods=params['minimum_events']).sum().to_numpy(float)

    def ratio(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
        """機能: 情報量が正の場合だけ偏りを計算する。

        引数: numerator/denominator (ndarray)。返り値: 偏り又はNaN (ndarray[float])。
        """
        return np.divide(numerator, denominator, out=np.full(len(times), np.nan), where=denominator > 0)

    long_ref = _positions(times, times - seconds, freshness)
    short_ref = _positions(times, times - seconds * params['short_fraction'], freshness)
    stage_ref = _positions(times, times - seconds * params['stage_fraction'], freshness)
    past_usable = _take(usable.astype(np.int8), long_ref, 0).astype(bool)
    valid = usable & past_usable & (long_ref >= 0) & (bad == 0) & (rolling_count >= params['minimum_events'])
    valid &= np.isfinite(atr) & (atr > 0)
    long_change = mid - _take(mid, long_ref)
    short_change = mid - _take(mid, short_ref)
    long_sign = _sign(long_change, np.maximum(params['price_atr'] * atr, params['price_ticks'] * ready['tick']))
    short_sign = _sign(short_change, np.maximum(params['short_atr'] * atr, params['short_ticks'] * ready['tick']))
    price = np.where(valid & (long_sign == short_sign) & (short_ref >= 0), long_sign, 0).astype(np.int8)
    signed, absolute = summed('ofi_signed'), summed('ofi_abs')
    flow = ratio(signed, absolute)
    trade_pos, trade_neg = summed('trade_pos'), summed('trade_neg')
    trades = ratio(trade_pos - trade_neg, trade_pos + trade_neg)
    bid, ask = summed('refill_bid'), summed('refill_ask')
    refill = ratio(bid - ask, bid + ask)
    near = frame.dflow_near.where(usable).rolling(duration, min_periods=params['minimum_events']).mean().to_numpy(float)
    model = dict(time_s=times, seq=seq, row=rows, source_time_s=frame.source_time_s.to_numpy(float),
                 source_first_seq=frame.source_first_seq.to_numpy(np.int64), source_last_seq=frame.source_last_seq.to_numpy(np.int64),
                 source_frame_index=frame.index.to_numpy(), mid=mid, atr=atr, valid=valid, usable=usable,
                 long_ref=long_ref, short_ref=short_ref, stage_ref=stage_ref,
                 window_first=np.searchsorted(times, times - seconds, side='right'),
                 price=price, long_change=long_change, short_change=short_change, long_sign=long_sign, short_sign=short_sign,
                 flow=flow, trade=trades, refill=refill, near=near)
    _CACHE[key] = model
    return model


def _evidence(model: dict, candidate: np.ndarray, peer: dict | None, peer_pos: np.ndarray, params: dict) -> pd.DataFrame:
    """機能: 各判断が参照した時刻・原本行・フロー値を後から追える表にする。

    引数: model/params (dict)、candidate/peer_pos (ndarray)、peer (dict|None)。返り値: 証拠表 (DataFrame)。
    """
    values = dict(event_index=np.arange(len(candidate), dtype=np.int64), direction=candidate,
                  release_time_s=model['time_s'], release_seq=model['seq'], release_row=model['row'],
                  source_time_s=model['source_time_s'], source_first_seq=model['source_first_seq'], source_last_seq=model['source_last_seq'],
                  window_first_event=model['window_first'], valid=model['valid'], mid=model['mid'], atr=model['atr'],
                  price_change=model['long_change'], short_price_change=model['short_change'],
                  ofi=model['flow'], trade_proxy=model['trade'], distance_flow=model['near'], refill_proxy=model['refill'])
    for name in ('long_ref', 'short_ref', 'stage_ref'):
        index = model[name]
        values[name + '_event'] = index
        for source_name, ending, missing in (('time_s', 'time_s', np.nan), ('seq', 'seq', -1), ('row', 'row', -1)):
            values[name + '_' + ending] = _take(model[source_name], index, missing)
    values['peer_event'] = peer_pos
    for source_name, ending, missing in (('time_s', 'release_time_s', np.nan), ('seq', 'release_seq', -1), ('row', 'release_row', -1),
                                       ('source_time_s', 'source_time_s', np.nan), ('source_last_seq', 'source_last_seq', -1),
                                       ('flow', 'ofi', np.nan), ('price', 'price_direction', 0)):
        values['peer_' + ending] = _take(peer[source_name], peer_pos, missing) if peer is not None else np.full(len(candidate), missing)
    values['peer_available_time_s'] = values['peer_release_time_s'] + params['peer_delay_seconds']
    return pd.DataFrame(values)


def build(spec: dict, inputs: dict, features: dict) -> dict:
    """機能: 指定した根拠を全銘柄・セッションの原本行へ過去解放順に対応させる。

    引数: spec (dict)、inputs/features (dict[(session,symbol),dict|DataFrame])。
    返り値: キー別direction/source_row/source_event_indexとイベント証拠表 (dict)。
    主カタログの条件は不変。時計感度はwindow_secondsだけを変更し内部1/4・1/2窓も同率にする。
    """
    params = dict(spec['params'])
    kind = params['kind']
    assert kind in {s['family'] for s in catalog()}
    models = {key: _model(ready, features[key], params) for key, ready in inputs.items()}
    output = {}
    for key, ready in inputs.items():
        model = models[key]
        n = len(model['time_s'])
        valid = model['valid']
        flow = _sign(model['flow'], params['ofi_threshold'])
        price = model['price']
        peer = None
        peer_pos = np.full(n, -1, np.int64)
        if kind == 'price':
            candidate = price.copy()
        elif kind == 'flow':
            near = _sign(model['near'], params['near_threshold'])
            previous_flow = _take(flow, model['stage_ref'], 0)
            previous_near = _take(near, model['stage_ref'], 0)
            before_valid = _take(valid.astype(np.int8), model['stage_ref'], 0).astype(bool)
            candidate = np.where(valid & before_valid & (flow == near) & (flow == previous_flow) & (flow == previous_near), flow, 0)
        elif kind == 'opposite':
            trade = _sign(model['trade'], params['trade_threshold'])
            candidate = np.where(valid & (flow == trade) & (price == -flow), price, 0)
        elif kind in ('dual_price', 'dual_flow'):
            other_key = key[0], 'TOPIX' if key[1] == 'NK225' else 'NK225'
            peer = models.get(other_key)
            if peer is None:
                candidate = np.zeros(n, np.int8)
            else:
                peer_pos = _positions(peer['time_s'] + params['peer_delay_seconds'], model['time_s'], params['freshness_seconds'])
                peer_price = _take(peer['price'], peer_pos, 0)
                candidate = np.where(valid & (peer_price == price), price, 0)
                if kind == 'dual_flow':
                    peer_flow = _take(_sign(peer['flow'], params['ofi_threshold']), peer_pos, 0)
                    candidate = np.where((candidate == flow) & (candidate == peer_flow), candidate, 0)
        else:
            ref = model['stage_ref']
            before_flow = _take(flow, ref, 0)
            before_refill = _take(_sign(model['refill'], params['refill_threshold']), ref, 0)
            before_change = _take(model['long_change'], ref)
            before_atr = _take(model['atr'], ref)
            stall = np.abs(before_change) <= np.maximum(params['stall_atr'] * before_atr, params['stall_ticks'] * ready['tick'])
            subsequent = _sign(model['mid'] - _take(model['mid'], ref),
                               np.maximum(params['price_atr'] * model['atr'], params['price_ticks'] * ready['tick']))
            before_valid = _take(valid.astype(np.int8), ref, 0).astype(bool)
            candidate = np.where(valid & before_valid & stall & (before_refill == -before_flow)
                                 & (subsequent == -before_flow) & (model['short_sign'] == subsequent), subsequent, 0)
        candidate = np.asarray(candidate, np.int8)
        candidate[~valid] = 0
        assert np.isin(candidate, (-1, 0, 1)).all()
        events = _evidence(model, candidate, peer, peer_pos, params)
        index = np.searchsorted(model['seq'], ready['seq'], side='right').astype(np.int64) - 1
        available = index >= 0
        if n:
            available &= ready['time_s'] - model['time_s'][np.maximum(index, 0)] <= params['freshness_seconds']
        index[~available] = -1
        direction = _take(candidate, index, 0).astype(np.int8)
        source_row = _take(model['row'], index, -1).astype(np.int64)
        assert np.all(source_row <= np.arange(len(source_row)))
        output[key] = dict(direction=direction, source_row=source_row,
                           source_event_index=index.astype(np.int32), events=events)
    return output


def freeze() -> dict:
    """機能: 12根拠の機序・数値と解放対応仕様を結果前固定する。

    引数: なし。返り値: 固定仕様 (dict)。異なる仕様での上書きを拒否する。
    """
    fixed = dict(conditions=catalog(), 方向='観測上昇+1/下落-1/根拠なし0。保有方向×direction=-1だけ悪化。',
        動作='悪化成立は直接返済を意味しない。固定3A0候補に短縮3min(A0,At)候補を加え、既存線は緩めない。',
        因果='自市場は解放seqで展開、peerは解放時刻+60秒以前だけ。欠測/古さ/中立を悪化としない。',
        品質='解放遅延60秒以内、直近解放と過去参照は60秒以内、窓内の欠測又は解放間隔60秒超は不発、最低5イベント。',
        比較='悪化窓120/600秒は全条件で固定。今回のC080/C120は旧入口時計の感度で、悪化窓は変えない。悪化窓自体の感度は未検査。',
        解釈='OFI・推定売買・補充は公開スナップショット由来の代理量。真の約定/取消、発注者、新規/返済は識別しない。',
        記録='原本direction/source_rowとraw→event位置を返し、イベント証拠表に全解放・過去窓・peer・stage参照を保存する。',
        事後条件追加=False, 新損益読取=False, API取得数=0, 現在保存物使用=False)
    path = HERE / 'deterioration_design_fixed.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8')) == fixed
    else:
        path.write_text(json.dumps(fixed, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return fixed


if __name__ == '__main__':
    freeze()
    print('6機序×2窓、計12条件の仕様を損益参照前に固定しました。')
