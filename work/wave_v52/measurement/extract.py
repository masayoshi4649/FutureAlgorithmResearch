"""保存板を記録順に読み、市場の動作を価格方向の言い換えと分けて測定する。"""

from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import pickle
import sys
import time

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SUMS = ('exec_buy', 'exec_sell', 'exec_unknown', 'source_volume_delta',
        'noexec_bid_add', 'noexec_bid_remove', 'noexec_ask_add', 'noexec_ask_remove',
        'refill_bid', 'refill_ask', 'both_up', 'both_down', 'quote_ticks',
        'spread_widen', 'spread_narrow', 'all_bid_add', 'all_bid_remove',
        'all_ask_add', 'all_ask_remove', 'trade_events', 'no_trade_events',
        'volume_resets', 'unavailable_volume_events', 'quote_events',
        'refill_bid_fixed_quote', 'refill_ask_fixed_quote',
        'depth_valid_events', 'depth_incomplete_events', 'depth_disordered_events', 'depth_duplicate_events')
MEANS = ('supply_bid_near', 'supply_ask_near', 'supply_bid_far', 'supply_ask_far',
         'spread_ticks_mean', 'bid_qty_mean', 'ask_qty_mean')
META = ('time_s', 'seq', 'source_time_s', 'source_first_seq', 'source_last_seq',
        'source_mid_first', 'source_mid_last', 'source_bid_first', 'source_ask_first', 'source_bid_last', 'source_ask_last',
        'source_last', 'source_age', 'raw_events', 'valid_events', 'continuity_resets',
        'volume_time_s', 'bid', 'ask', 'mid', 'last', 'atr')
COLUMNS = META + SUMS + MEANS


def save_json(path: Path, value: object) -> None:
    """機能: 有限値のみ許可して日本語の監査結果を保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def load_ready() -> dict:
    """機能: 既存監査済みの23場の逐次価格入力を読み込む。

    引数: なし。返り値: 銘柄と場をキーにした入力(dict)。
    """
    module_path = ROOT / 'work/wave_v51/overlay/research.py'
    spec = importlib.util.spec_from_file_location('existing_inputs52', module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.load()[0]


def finite(value: object, default: float = 0.) -> float:
    """機能: JSON値を有限の実数へ変換する。

    引数: value(object)、default(float)。返り値: 数値または代替値(float)。
    """
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (ValueError, TypeError):
        return default


def snapshot(raw: dict, tick: float, weights: dict) -> tuple | None:
    """機能: 上位10段を読み最良板の妥当性と距離別供給量を求める。

    引数: raw(dict)、tick(float)、weights(dict)。返り値: 板状態(tuple|None)。
    Buyが買い気配、Sellが売り気配。板外の数量をゼロとは補完しない。
    """
    books, supply, bests = [], [], []
    incomplete = disordered = duplicate = False
    for side in ('Buy', 'Sell'):
        levels = []
        for depth in range(1, 11):
            item = raw.get(f'{side}{depth}') or {}
            price, qty = finite(item.get('Price')), finite(item.get('Qty'), -1.)
            levels.append((price, qty) if price > 0 and qty >= 0 else (0., 0.))
        best, best_qty = levels[0]
        if best <= 0 or best_qty <= 0:
            return None
        book = dict((p, q) for p, q in levels if p > 0)
        positive = [price for price, qty in levels if price > 0]
        incomplete |= len(positive) != 10
        duplicate |= len(set(positive)) != len(positive)
        disordered |= any((a <= b if side == 'Buy' else a >= b) for a, b in zip(positive, positive[1:]))
        near = far = 0.
        for price, qty in book.items():
            distance = max(0., ((best - price) if side == 'Buy' else (price - best)) / tick)
            if distance not in weights:
                weights[distance] = math.exp(-distance / 2.), math.exp(-distance / 8.)
            wn, wf = weights[distance]
            near += wn * qty
            far += wf * qty
        books.append(book)
        supply.append((near, far))
        bests.append((best, best_qty))
    bid, bid_qty = bests[0]
    ask, ask_qty = bests[1]
    last = finite(raw.get('CurrentPrice'))
    if bid >= ask or last <= 0:
        return None
    volume = finite(raw.get('TradingVolume'), -1.)
    return (bid, ask, bid_qty, ask_qty, books[0], books[1], last, volume,
            supply[0][0], supply[1][0], supply[0][1], supply[1][1],
            not (incomplete or disordered or duplicate), incomplete, disordered, duplicate)


def refill(history: dict, price: float, delta: float, stamp: float) -> float:
    """機能: 30秒以内の同価格減少に対応する数量回復だけを数える。

    引数: history(dict)、price/delta/stamp(float)。返り値: 非負の対応回復量(float)。
    同一注文・同一主体・約定後の補充であるとは判定しない。
    """
    events = history.setdefault(price, deque())
    while events and events[0][0] < stamp - 30.:
        events.popleft()
    if delta < 0:
        events.append([stamp, -delta])
        return 0.
    left, matched = delta, 0.
    while events and left > 0:
        use = min(left, events[0][1])
        left -= use
        matched += use
        events[0][1] -= use
        if events[0][1] <= 0:
            events.popleft()
    return matched


def new_block(stamp: float, seq: int) -> dict:
    """機能: 同じ約定時刻の行を封印して集計する箱を作る。

    引数: stamp(float)、seq(int)。返り値: 未公開集計(dict)。
    """
    return dict(time=stamp, first_seq=seq, last_seq=seq, raw=0, valid=0, resets=0,
                first=None, last=None, volume_time=stamp,
                sums={name: 0. for name in SUMS}, means=[0.] * len(MEANS))


def observe(block: dict, now: tuple, previous: tuple | None,
            stamp: float, tick: float, histories: tuple) -> None:
    """機能: 現在行までの板変化を、心理を断定せず観測量として加算する。

    引数: block(dict)、now/previous(tuple|None)、stamp/tick(float)、histories(tuple)。
    返り値: なし(None)。未来の価格・出来高・行へアクセスしない。
    """
    block['valid'] += 1
    if block['first'] is None:
        block['first'] = now
    block['last'] = now
    values = block['sums']
    for offset, name in enumerate(('depth_valid_events', 'depth_incomplete_events', 'depth_disordered_events', 'depth_duplicate_events')):
        values[name] += int(now[12 + offset])
    means = now[8:12] + ((now[1] - now[0]) / tick, now[2], now[3])
    for index, value in enumerate(means):
        if index >= 4 or now[12]:
            block['means'][index] += value
    if previous is None:
        return
    dv = now[7] - previous[7] if now[7] >= 0 and previous[7] >= 0 else None
    if dv is None:
        values['unavailable_volume_events'] += 1
    elif dv < 0:
        values['volume_resets'] += 1
    elif dv > 0:
        values['source_volume_delta'] += dv
        values['trade_events'] += 1
        # 最後の約定値は出来高増分の全内訳ではないため、執行方向の代理値である。
        key = 'exec_buy' if now[6] >= previous[1] else 'exec_sell' if now[6] <= previous[0] else 'exec_unknown'
        values[key] += dv
    else:
        values['no_trade_events'] += 1

    # ----------------------------------------
    # 最良価格の移動は数量情報とは別に記録し、追加情報検定の価格対照へ渡す。
    db, da = now[0] - previous[0], now[1] - previous[1]
    values['both_up'] += int(db > 0 and da > 0)
    values['both_down'] += int(db < 0 and da < 0)
    values['quote_ticks'] += (db + da) / (2. * tick)
    values['quote_events'] += int(db != 0 or da != 0)
    spread_change = (da - db) / tick
    values['spread_widen'] += max(spread_change, 0.)
    values['spread_narrow'] += max(-spread_change, 0.)

    # ----------------------------------------
    # 深い板の重複・順序不正・欠測を実際の数量変化と扱わない。
    if not now[12] or not previous[12]:
        histories[0].clear()
        histories[1].clear()
        return

    # ----------------------------------------
    # 前後とも表示される同価格だけを比較し、表示範囲外への移動を取消に数えない。
    for side, label in enumerate(('bid', 'ask')):
        before, current = previous[4 + side], now[4 + side]
        added = removed = recovered = 0.
        for price in before.keys() & current.keys():
            delta = current[price] - before[price]
            if delta > 0:
                added += delta
            elif delta < 0:
                removed -= delta
            if delta:
                recovered += refill(histories[side], price, delta, stamp)
        values[f'all_{label}_add'] += added
        values[f'all_{label}_remove'] += removed
        if dv == 0:
            values[f'noexec_{label}_add'] += added
            values[f'noexec_{label}_remove'] += removed
        values[f'refill_{label}'] += recovered
        if db == 0 and da == 0:
            values[f'refill_{label}_fixed_quote'] += recovered


def extract(path: Path, ready: dict, max_rows: int | None = None) -> tuple[pd.DataFrame, dict]:
    """機能: 原本を一方向に読み、閉鎖した時刻ブロックのみ次時刻に公開する。

    引数: path(Path)、ready(dict)、max_rows(int|None)。
    返り値: 特徴表と監査結果(tuple[DataFrame,dict])。末尾の未公開箱は捨てる。
    """
    start, end, tick = ready['start'], ready['limit'] + 300., ready['tick']
    expected_seq = np.asarray(ready['seq'], dtype=np.int64)
    index = 0
    weights, histories, previous, block = {}, ({}, {}), None, None
    stamp_text = None
    stamp = -math.inf
    rows = []
    hasher = hashlib.sha256()
    counts = dict(読取行数=0, 時刻欠損=0, 時間外=0, 不正板=0, 入力一致行数=0,
                  公開時板不正=0, 公開元全板不正=0, 出来高時刻が約定時刻より未来=0,
                  公開時刻を超える出来高時刻=0)
    with path.open('rb') as stream:
        for seq, line in enumerate(stream):
            if max_rows is not None and seq >= max_rows:
                break
            counts['読取行数'] += 1
            hasher.update(line)
            raw = json.loads(line)
            text = raw.get('CurrentPriceTime')
            if not text:
                counts['時刻欠損'] += 1
                previous, histories = None, ({}, {})
                if block:
                    block['resets'] += 1
                continue
            if text != stamp_text:
                parsed_time = datetime.fromisoformat(text)
                assert parsed_time.tzinfo is not None, (path, seq, 'タイムゾーン欠損')
                current_s = parsed_time.timestamp()
                assert current_s >= stamp, (path, seq, '時刻逆行')
                stamp, stamp_text = current_s, text
                for history in histories:
                    for price in list(history):
                        events = history[price]
                        while events and events[0][0] < stamp - 30.:
                            events.popleft()
                        if not events:
                            del history[price]
            if not start <= stamp < end:
                counts['時間外'] += 1
                previous, histories = None, ({}, {})
                continue
            now = snapshot(raw, tick, weights)
            atr = 0.
            if now is not None:
                assert index < len(expected_seq) and expected_seq[index] == seq, (path, seq, index)
                assert ready['time_s'][index] == stamp and ready['last'][index] == now[6]
                atr = float(ready['atr'][index])
                counts['入力一致行数'] += 1
                index += 1

            # ----------------------------------------
            # 現在の箱に現在行を加算する前に過去の箱を公開する。
            if block is None or stamp != block['time']:
                if block is not None and block['valid']:
                    if now is None:
                        counts['公開時板不正'] += 1
                    else:
                        assert block['last_seq'] < seq and block['time'] < stamp
                        assert block['volume_time'] <= stamp, (path, seq, block['volume_time'], stamp)
                        first, last = block['first'], block['last']
                        metadata = (stamp, seq, block['time'], block['first_seq'], block['last_seq'],
                                    (first[0] + first[1]) / 2., (last[0] + last[1]) / 2.,
                                    first[0], first[1], last[0], last[1], last[6], stamp - block['time'],
                                    block['raw'], block['valid'], block['resets'], block['volume_time'],
                                    now[0], now[1], (now[0] + now[1]) / 2., now[6], atr)
                        means = tuple(x / (block['sums']['depth_valid_events'] if i < 4 else block['valid'])
                                      if (block['sums']['depth_valid_events'] if i < 4 else block['valid']) else 0.
                                      for i, x in enumerate(block['means']))
                        rows.append(metadata + tuple(block['sums'][name] for name in SUMS) + means)
                elif block is not None:
                    counts['公開元全板不正'] += 1
                block = new_block(stamp, seq)
            block['last_seq'] = seq
            block['raw'] += 1
            volume_text = raw.get('TradingVolumeTime')
            if volume_text:
                parsed_volume_time = datetime.fromisoformat(volume_text)
                assert parsed_volume_time.tzinfo is not None, (path, seq, '出来高タイムゾーン欠損')
                volume_s = parsed_volume_time.timestamp()
                block['volume_time'] = max(block['volume_time'], volume_s)
                counts['出来高時刻が約定時刻より未来'] += int(volume_s > stamp)
            if now is None:
                counts['不正板'] += 1
                block['resets'] += 1
                previous, histories = None, ({}, {})
                continue
            observe(block, now, previous, stamp, tick, histories)
            previous = now
    if max_rows is None:
        assert index == len(expected_seq), (path, index, len(expected_seq))
    result = pd.DataFrame.from_records(rows, columns=COLUMNS)
    assert (result.source_last_seq < result.seq).all()
    assert (result.source_time_s < result.time_s).all()
    assert (result.volume_time_s <= result.time_s).all()
    assert np.isfinite(result.drop(columns=['atr']).to_numpy(dtype=float)).all()
    for name in ('seq', 'source_first_seq', 'source_last_seq', 'raw_events', 'valid_events', 'continuity_resets'):
        result[name] = result[name].astype(np.int64)
    audit = dict(原本=str(path), 原本SHA256=hasher.hexdigest(), 特徴行数=len(result),
                 最後の未公開時刻=block['time'] if block else None,
                 最後の未公開行数=block['raw'] if block else 0, **counts)
    return result, audit


def main() -> None:
    """機能: 固定した観測定義で全場を読み、特徴と監査を保存する。

    引数: CLIの--sample/--resume。返り値: なし(None)。APIへ接続しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--sample', action='store_true')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    HERE.mkdir(parents=True, exist_ok=True)
    (HERE / 'accounts').mkdir(exist_ok=True)
    save_json(HERE / '観測定義.json', dict(
        列=list(COLUMNS), コードSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        執行代理='累積出来高の正増分を、最後約定価格が直前最良売気配以上なら買、買気配以下なら売、その間なら未知へ全量配分。集約出来高の真の売買主導は不明。tick-rule不使用。',
        無出来高増減='出来高差ゼロの隣接有効板の共通表示価格のみ数量増減。取消/新規発注の断定はしない。',
        回復='同価格の直近30秒の未対応数量減少を上限に、後の増加を対応。両最良値不変時を別記。主体は識別しない。',
        距離='各側最良気配からの呼値数d。近 exp(-d/2)、遠 exp(-d/8)。イベント平均。',
        十段品質='10段欠測・同価格重複・並び順不正は品質列に計数。深板の数量差分と回復履歴を切り、距離供給平均から除外する。最良価格と出来高の測定は保持。',
        公開='同じCurrentPriceTimeの連続blockを次時刻先頭有効板で公開。その先頭板は特徴集計には入れない。末尾箱は未公開。受信時刻不明。',
        結果ラベル='未来価格を含めない。mid/quote列は公開済み過去値の対照情報であり新たな予測情報とは数えない。'))
    inputs = load_ready()
    features, audits = {}, []
    for key in sorted(inputs):
        session, symbol = key
        target = HERE / 'accounts' / f'{session}_{symbol}.pkl'
        audit_path = target.with_suffix('.json')
        if args.resume and target.exists() and audit_path.exists():
            features[key] = pickle.loads(target.read_bytes())
            audits.append(json.loads(audit_path.read_text(encoding='utf8')))
            continue
        started = time.monotonic()
        frame, audit = extract(ROOT / 'book' / symbol / f'{session}.jsonl', inputs[key], 15000 if args.sample else None)
        audit.update(セッション=session, 銘柄=symbol, 処理秒=round(time.monotonic() - started, 2))
        if args.sample:
            save_json(HERE / '標本監査.json', audit)
            frame.to_pickle(HERE / 'sample.pkl')
            print(json.dumps(audit, ensure_ascii=False), flush=True)
            break
        target.write_bytes(pickle.dumps(frame, pickle.HIGHEST_PROTOCOL))
        save_json(audit_path, audit)
        features[key], audits = frame, audits + [audit]
        print(f'{session} {symbol}: {audit["読取行数"]:,}原本行 → {len(frame):,}特徴行 / {audit["処理秒"]}秒', flush=True)
    if args.sample:
        return
    (HERE / 'features.pkl').write_bytes(pickle.dumps(features, pickle.HIGHEST_PROTOCOL))
    checks = []
    for key in (('2026-09-21_Day', 'TOPIX'), ('2026-10-06_Day', 'NK225')):
        full = features[key]
        cutoff = int(full.seq.iloc[min(len(full) - 1, 1800)])
        part, _ = extract(ROOT / 'book' / key[1] / f'{key[0]}.jsonl', inputs[key], cutoff)
        expected = full.loc[full.seq < cutoff].reset_index(drop=True)
        pd.testing.assert_frame_equal(part, expected, check_exact=True)
        checks.append(dict(口座=list(key), 原本打切り行=cutoff, 一致特徴行数=len(part)))
    save_json(HERE / '監査.json', dict(合格=True, 原本数=len(audits), 原本行数=sum(x['読取行数'] for x in audits),
                                     特徴行数=sum(x['特徴行数'] for x in audits),
                                     入力一致行数=sum(x['入力一致行数'] for x in audits),
                                     途中切断=checks, 原本別=audits, 現在API取得数=0))


if __name__ == '__main__':
    main()
