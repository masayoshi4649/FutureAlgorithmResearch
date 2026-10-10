"""保存原本を順に読み、同価格の表示量減少と回復を一度だけ数える補充観測を作る。"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
spec = importlib.util.spec_from_file_location('display57', HERE.parent / 'wave_v56/measurement/display_changes.py')
display = importlib.util.module_from_spec(spec)
spec.loader.exec_module(display)
MULTIPLIER = {'TOPIX': 10000., 'NK225': 1000.}
EVENT_DTYPE = np.dtype([('i', 'i8'), ('seq', 'i8'), ('time', 'f8'), ('side', 'i1'),
                        ('price', 'f8'), ('qty', 'f8'), ('start_seq', 'i8'),
                        ('start_time', 'f8'), ('decline', 'f8'), ('bestqty', 'f8')])
FLOAT_COLUMNS = ('bid', 'ask', 'mid', 'last', 'bid_far', 'ask_far', 'bid_qty', 'ask_qty',
                 'exec_buy_qty', 'exec_sell_qty', 'exec_unknown_qty', 'exec_mean_price',
                 'volume_delta', 'best_ofi')
RESET_REASONS = {1: '最初の観測または前観測なし', 2: '原本行の不連続',
                 4: '不完全または不正な10段', 8: '約定時計逆行', 16: '累積出来高リセット'}


def finite(value: object) -> float | None:
    """機能: JSON数値の欠測を0へ置換せず識別する。

    引数: value(object)。返り値: 有限数または欠測(float|None)。
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def read_book(raw: dict, label: str) -> dict | None:
    """機能: 10段の完全性、正の価格、非負数量、価格順序を検査する。

    引数: raw(dict)、label(str:Buy/Sell)。返り値: 正当な価格数量辞書または不明(dict|None)。
    """
    result, previous = {}, None
    for depth in range(1, 11):
        item = raw.get(f'{label}{depth}') or {}
        price, qty = finite(item.get('Price')), finite(item.get('Qty'))
        if price is None or qty is None or price <= 0 or qty < 0:
            return None
        if previous is not None and (price >= previous if label == 'Buy' else price <= previous):
            return None
        result[price], previous = qty, price
    return result


@dataclass
class Snapshot:
    """原本一行で同時に表示される気配と累積値を保持する。"""
    bid: float
    ask: float
    bid_qty: float
    ask_qty: float
    bid_book: dict | None
    ask_book: dict | None
    last: float
    volume: float | None
    turnover: float | None

    @property
    def valid(self) -> bool:
        """機能: 最良気配と両側10段が使用可能かを判定する。

        引数: なし。返り値: 正当ならTrue(bool)。
        """
        return (0 < self.bid < self.ask and self.bid_qty > 0 and self.ask_qty > 0
                and self.bid_book is not None and self.ask_book is not None)


def snapshot(raw: dict) -> Snapshot:
    """機能: 既存有効原本行の気配、数量、出来高、売買代金を取り出す。

    引数: raw(dict)。返り値: 一行の観測状態(Snapshot)。
    """
    bid, ask = raw['Buy1'], raw['Sell1']
    volume = finite(raw.get('TradingVolume'))
    turnover = finite(raw.get('TradingValue'))
    return Snapshot(float(bid['Price']), float(ask['Price']), float(bid['Qty']), float(ask['Qty']),
                    read_book(raw, 'Buy'), read_book(raw, 'Sell'), float(raw['CurrentPrice']),
                    volume if volume is not None and volume >= 0 else None,
                    turnover if turnover is not None and turnover >= 0 else None)


class ReplenishmentState:
    """両側の価格別エピソードを保持し、入力一行だけずつ進める。"""

    def __init__(self, multiplier: float):
        """機能: 場内の補充状態と平均執行代理の倍率を初期化する。

        引数: multiplier(float) はラージ一枚の価格倍率。返り値: なし(None)。
        """
        self.multiplier = multiplier
        self.previous = None
        self.previous_seq = None
        self.previous_time = None
        self.episodes = {1: {}, -1: {}}
        self.discarded = dict(expired=0, outside=0, reset=0)

    def clear(self) -> None:
        """機能: 情報の不連続時に未完了のエピソードをすべて破棄する。

        引数: なし。返り値: なし(None)。
        """
        self.discarded['reset'] += sum(len(value) for value in self.episodes.values())
        self.episodes = {1: {}, -1: {}}

    def process_side(self, before: dict, after: dict, side: int, bestqty: float,
                     seq: int, stamp: float, index: int) -> list[tuple]:
        """機能: 一方の価格別減少残高に既知回復だけを割り当て、完了を一度だけ返す。

        引数: before/after(dict)、side(int:1/-1)、bestqty(float)、seq/index(int)、stamp(float)。
        返り値: 当該原本行で完了した補充イベント(list[tuple])。
        """
        label = 'bid' if side == 1 else 'ask'
        active = self.episodes[side]
        after_far = min(after) if side == 1 else max(after)
        for price in list(active):
            episode = active[price]
            outside = price < after_far if side == 1 else price > after_far
            if outside or stamp - episode[0] > 30. or seq - episode[1] > 500:
                self.discarded['outside' if outside else 'expired'] += 1
                del active[price]
        changes = display.side_changes(before, after, label)
        prices = (before.keys() & after.keys()) | set(changes['disappeared_prices']) | set(changes['appeared_prices'])
        events = []
        for price in sorted(prices):
            delta = after.get(price, 0.) - before.get(price, 0.)
            if delta < 0:
                if price not in active:
                    active[price] = [stamp, seq, bestqty, -delta, 0.]
                else:
                    active[price][3] -= delta
            elif delta > 0 and price in active:
                episode = active[price]
                episode[4] += min(delta, max(0., episode[3] - episode[4]))
                if episode[4] >= .8 * episode[3] and episode[4] >= .25 * episode[2]:
                    events.append((index, seq, stamp, side, price, episode[4], episode[1], episode[0], episode[3], episode[2]))
                    del active[price]
        return events

    def step(self, now: Snapshot, seq: int, stamp: float, index: int) -> tuple[dict, list[tuple]]:
        """機能: 現在原本行の公開情報だけでリセット、執行代理、補充完了を更新する。

        引数: now(Snapshot)、seq/index(int)、stamp(float)。返り値: 特徴と完了イベント(tuple)。
        同行の完了イベントは同行観測後に判定可能で、注文の約定行は別に扱う。
        """
        old = self.previous
        reason = 1 if old is None else 0
        if self.previous_seq is not None and seq != self.previous_seq + 1:
            reason |= 2
        if not now.valid:
            reason |= 4
        if self.previous_time is not None and stamp < self.previous_time:
            reason |= 8
        if old is not None and old.volume is not None and now.volume is not None and now.volume < old.volume:
            reason |= 16
        row = dict(bid=now.bid, ask=now.ask, mid=(now.bid + now.ask) / 2., last=now.last,
                   bid_far=min(now.bid_book) if now.bid_book is not None else np.nan,
                   ask_far=max(now.ask_book) if now.ask_book is not None else np.nan,
                   bid_qty=now.bid_qty, ask_qty=now.ask_qty, valid=now.valid, reset=bool(reason), reset_reason=reason,
                   exec_buy_qty=0., exec_sell_qty=0., exec_unknown_qty=0., exec_mean_price=np.nan,
                   volume_delta=np.nan, best_ofi=np.nan)
        events = []
        if reason:
            self.clear()
        else:
            row['best_ofi'] = display.best_ofi((old.bid, old.bid_qty), (old.ask, old.ask_qty),
                                               (now.bid, now.bid_qty), (now.ask, now.ask_qty))
            if old.volume is not None and now.volume is not None:
                dv = now.volume - old.volume
                row['volume_delta'] = dv
                if dv > 0:
                    value_change = None if old.turnover is None or now.turnover is None else now.turnover - old.turnover
                    mean = np.nan if value_change is None or value_change <= 0 else value_change / (dv * self.multiplier)
                    row['exec_mean_price'] = mean
                    label = 'exec_buy_qty' if mean >= old.ask else 'exec_sell_qty' if mean <= old.bid else 'exec_unknown_qty'
                    row[label] = dv
            events.extend(self.process_side(old.bid_book, now.bid_book, 1, old.bid_qty, seq, stamp, index))
            events.extend(self.process_side(old.ask_book, now.ask_book, -1, old.ask_qty, seq, stamp, index))
        self.previous = now if now.valid else None
        self.previous_seq, self.previous_time = seq, stamp
        return row, events


def load_inputs() -> dict:
    """機能: 価格・時刻・原本行だけに限定済みの46口座入力を読む。

    引数: なし。返り値: 全口座辞書(dict)。旧売買結果は開かない。
    """
    result = pickle.loads((HERE.parent / 'wave_v55/clean_inputs.pkl').read_bytes())
    assert len(result) == 46
    return result


def extract_one(key: tuple, ready: dict, max_valid_rows: int | None = None) -> tuple[dict, np.ndarray, dict]:
    """機能: 一原本を一度だけ順番に読み、既存有効行と同長の特徴とイベントを生成する。

    引数: key(tuple)、ready(dict)、max_valid_rows(int|None)。返り値: 特徴・イベント・監査(tuple)。
    切断検査以外は全原本を読み、最終行を含む全有効seq/time/lastを照合する。
    """
    session, symbol = key
    path = ROOT / 'book' / symbol / f'{session}.jsonl'
    size = len(ready['seq']) if max_valid_rows is None else min(max_valid_rows, len(ready['seq']))
    output = {name: np.full(size, np.nan) for name in FLOAT_COLUMNS}
    output.update(seq=ready['seq'][:size].copy(), time_s=ready['time_s'][:size].copy(),
                  valid=np.zeros(size, dtype=bool), reset=np.zeros(size, dtype=bool), reset_reason=np.zeros(size, dtype=np.uint8))
    state, events = ReplenishmentState(MULTIPLIER[symbol]), []
    pointer, raw_rows, text_before, stamp = 0, 0, None, None
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for seq, line in enumerate(stream):
            if max_valid_rows is not None and pointer >= size:
                break
            raw_rows += 1
            hasher.update(line)
            if pointer >= size or seq != ready['seq'][pointer]:
                continue
            raw = json.loads(line)
            text = raw['CurrentPriceTime']
            if text != text_before:
                parsed = datetime.fromisoformat(text)
                assert parsed.tzinfo is not None, (key, seq)
                stamp, text_before = parsed.timestamp(), text
            assert stamp == ready['time_s'][pointer]
            now = snapshot(raw)
            assert now.last == ready['last'][pointer]
            row, completed = state.step(now, seq, stamp, pointer)
            for name, value in row.items():
                output[name][pointer] = value
            events.extend(completed)
            pointer += 1
    assert pointer == size
    event_array = np.asarray(events, dtype=EVENT_DTYPE)
    for name in ('bid', 'ask', 'mid', 'last'):
        assert np.isfinite(output[name]).all()
    known_volume = np.isfinite(output['volume_delta']) & (output['volume_delta'] >= 0)
    np.testing.assert_allclose((output['exec_buy_qty'] + output['exec_sell_qty'] + output['exec_unknown_qty'])[known_volume],
                               output['volume_delta'][known_volume])
    if len(event_array):
        assert np.all(event_array['seq'] == output['seq'][event_array['i']])
        assert np.all(event_array['time'] == output['time_s'][event_array['i']])
        assert np.all(event_array['start_seq'] < event_array['seq'])
        assert np.all(event_array['qty'] >= .8 * event_array['decline'])
        assert np.all(event_array['qty'] <= event_array['decline'])
        assert np.all(event_array['qty'] >= .25 * event_array['bestqty'])
        assert np.all(event_array['seq'] - event_array['start_seq'] <= 500)
        assert np.all(event_array['time'] - event_array['start_time'] <= 30.)
    audit = dict(セッション=session, 銘柄=symbol, 原本=str(path), 原本SHA256=hasher.hexdigest(),
                 読取行数=raw_rows, 有効入力行数=size, 完全10段行数=int(output['valid'].sum()),
                 リセット行数=int(output['reset'].sum()),
                 リセット理由別={label: int(((output['reset_reason'] & bit) != 0).sum()) for bit, label in RESET_REASONS.items()},
                 補充完了数=len(event_array), 買い側補充完了数=int((event_array['side'] == 1).sum()),
                 売り側補充完了数=int((event_array['side'] == -1).sum()), 未完了破棄数=state.discarded,
                 原本seq時計最終値完全一致=True, 完了数量と期限整合=True, ATR使用=False)
    return output, event_array, audit


def main() -> None:
    """機能: 全46原本の特徴を生成し、原本同一性と数量保存を監査して保存する。

    引数: なし。返り値: なし(None)。現在API、将来ラベル、損益は参照しない。
    """
    inputs = load_inputs()
    baseline = json.loads((HERE.parent / 'wave_v52/measurement/気配キャッシュ監査.json').read_text(encoding='utf8'))
    hashes = {(row['セッション'], row['銘柄']): row['原本SHA256'] for row in baseline['原本別']}
    all_features, all_events, audits = {}, {}, []
    with ProcessPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(extract_one, key, ready): key for key, ready in sorted(inputs.items())}
        for future in as_completed(futures):
            key = futures[future]
            features, events, audit = future.result()
            assert audit['原本SHA256'] == hashes[key]
            all_features[key], all_events[key] = features, events
            audits.append(audit)
            print(f'{key[0]} {key[1]}: {len(features["seq"]):,} 行 / 補充完了 {len(events):,}', flush=True)
    # ----------------------------------------
    # 気配も独立抽出済みキャッシュの同一原本行へ照合する。
    quotes = pickle.loads((HERE.parent / 'wave_v52/measurement/quotes.pkl').read_bytes())
    for key, features in all_features.items():
        for name in ('seq', 'time_s', 'bid', 'ask', 'mid'):
            assert np.array_equal(features[name], quotes[key][name]), (key, name)
    prefix_audits = []
    for key in (('2026-09-24_Day', 'TOPIX'), ('2026-10-01_Night', 'NK225')):
        size = len(inputs[key]['seq']) // 2
        shorter, shorter_events, _ = extract_one(key, inputs[key], max_valid_rows=size)
        for name in shorter:
            np.testing.assert_array_equal(shorter[name], all_features[key][name][:size])
        expected_events = all_events[key][all_events[key]['i'] < size]
        np.testing.assert_array_equal(shorter_events, expected_events)
        prefix_audits.append(dict(セッション=key[0], 銘柄=key[1], 原本有効行数=size, 特徴イベント完全一致=True))
    (HERE / 'features.pkl').write_bytes(pickle.dumps(all_features, pickle.HIGHEST_PROTOCOL))
    (HERE / 'events.pkl').write_bytes(pickle.dumps(all_events, pickle.HIGHEST_PROTOCOL))
    specification = dict(
        列=list(next(iter(all_features.values()))), イベント列=list(EVENT_DTYPE.names),
        公開='各有効原本行の観測完了時点。iはclean_inputs配列位置、seqは0始まり原本行、timeはCurrentPriceTime。約定判断と実約定は別コード。',
        最良='Buy1がbid、Sell1がask。bid_far/ask_farは完全な10段の最遠価格。不正深板時はvalid=False。',
        補充='各side×同価格で累積既知減少を記録し、既知増加を未回復残高まで割当て。累積減少80%以上かつ開始直前最良数量25%以上を回復したら一度だけ完了・状態clear。',
        期限='開始から30秒以内かつ500原本行以内。いずれかを超えると破棄。原本更新行数であり値段変更回数ではない。',
        観測範囲='前best消失を既知の表示0と扱う。遠方10段外の表示量は不明とし、その価格の未完了履歴を破棄する。',
        リセット=RESET_REASONS, リセットの範囲='原本不連続・完全10段不正・約定時計逆行・出来高resetで両側未完了状態を破棄。前比較状態がなければ初期化だけ。',
        完了履歴='120秒/2000原本行の価格別完了履歴は親signals側が担当。この抽出器では異価格を合算した履歴を作らない。',
        執行代理='正のΔTradingValue/(正のΔVolume×ラージ倍率)を前bid/askと比較。ask以上はbuy、bid以下はsell、その間や代金不明はunknown。真aggressorや個々の約定内訳は保証しない。',
        ラージ倍率=MULTIPLIER,
        時計='CurrentPriceTimeは受信時計ではない。同時計の更新は原本順。執行代理に使う累積値はその原本行に実際に含まれる値だけ。',
        不明出来高='volume_delta=NaNなら増分不明。執行側数量の0は既知の無執行量という意味にはしない。validは深板の有効性で出来高既知とは別。',
        禁止='ATR、将来ラベル、損益、現在セッションAPIを使用しない。',
    )
    summary = dict(合格=True, 原本数=len(audits), 原本有効行数=sum(row['有効入力行数'] for row in audits),
                   補充完了数=sum(row['補充完了数'] for row in audits), 原本SHA256一致=True,
                   seq時刻価格気配完全一致=True, 数量保存と期限整合=True, 途中切断=prefix_audits,
                   コードSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   売買結果未参照=True, ATR使用=False, 現在API取得数=0,
                   原本別=sorted(audits, key=lambda row: (row['セッション'], row['銘柄'])))
    for name, value in (('特徴仕様.json', specification), ('特徴監査.json', summary)):
        (HERE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


if __name__ == '__main__':
    main()
