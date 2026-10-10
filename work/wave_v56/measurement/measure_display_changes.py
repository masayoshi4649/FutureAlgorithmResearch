"""旧共通価格差分が除外していた表示消失を、新しい純観測関数で全原本から集計する。"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import math
from pathlib import Path
import pickle

from display_changes import best_ofi, side_changes, synthetic_checks


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SIDE_VALUES = ('common_add', 'common_remove', 'known_disappeared', 'known_appeared',
               'unknown_old_quantity', 'unknown_new_quantity', 'known_add', 'known_remove', 'best_disappeared')


def book(raw: dict, side: str) -> dict | None:
    """機能: 10段の価格・数量が有限、非負、完全かつ順序正常な場合だけ返す。

    引数: raw(dict)、side(str:Buy/Sell)。返り値: 価格別数量または品質不良(dict|None)。
    """
    levels, before = {}, None
    for index in range(1, 11):
        item = raw.get(f'{side}{index}') or {}
        try:
            price, quantity = float(item['Price']), float(item['Qty'])
        except (TypeError, ValueError, KeyError):
            return None
        if not math.isfinite(price) or not math.isfinite(quantity) or price <= 0 or quantity < 0:
            return None
        if before is not None and (before <= price if side == 'Buy' else before >= price):
            return None
        levels[price], before = quantity, price
    return levels


def empty_counts() -> dict:
    """機能: 全行または出来高別の測定合計を初期化する。

    引数: なし。返り値: 数値集計辞書(dict)。
    """
    result = dict(最良比較数=0, OFI正行数=0, OFI負行数=0, OFIゼロ行数=0,
                  OFI正量=0., OFI負量=0., OFI純量=0., 深板比較数=0)
    result.update({f'{side}_{name}': 0. for side in ('bid', 'ask') for name in SIDE_VALUES})
    return result


def accumulate(target: dict, ofi: float, bid: dict | None, ask: dict | None) -> None:
    """機能: 最良OFIと両側の既知/不明表示量を、意味を混ぜず加算する。

    引数: target(dict)、ofi(float)、bid/ask(dict|None)。返り値: なし(None)。
    """
    target['最良比較数'] += 1
    target['OFI正行数' if ofi > 0 else 'OFI負行数' if ofi < 0 else 'OFIゼロ行数'] += 1
    target['OFI正量'] += max(0., ofi)
    target['OFI負量'] += max(0., -ofi)
    target['OFI純量'] += ofi
    if bid is not None and ask is not None:
        target['深板比較数'] += 1
        for side, changes in (('bid', bid), ('ask', ask)):
            for name in SIDE_VALUES:
                target[f'{side}_{name}'] += changes[name]


def volume(raw: dict) -> float | None:
    """機能: 累積出来高の欠測を0へ補完せず識別する。

    引数: raw(dict)。返り値: 非負有限出来高または不明(float|None)。
    """
    try:
        value = float(raw['TradingVolume'])
    except (TypeError, ValueError, KeyError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def measure_one(key: tuple, expected: object) -> dict:
    """機能: 一原本を読取専用で逐次処理し、最良OFIと表示範囲を補正した数量差を集計する。

    引数: key(tuple[session,symbol])、expected(ndarray[int])。
    返り値: 原本ハッシュ、品質、全行/出来高別集計(dict)。未来値や損益は読まない。
    """
    session, symbol = key
    path = ROOT / 'book' / symbol / f'{session}.jsonl'
    counts = {name: empty_counts() for name in ('全比較', '出来高不変', '出来高正増分', '出来高不明またはリセット')}
    index, previous, invalid_depth = 0, None, 0
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for seq, line in enumerate(stream):
            hasher.update(line)
            if index >= len(expected) or seq != expected[index]:
                previous = None
                continue
            index += 1
            raw = json.loads(line)
            bid = float(raw['Buy1']['Price']), float(raw['Buy1']['Qty'])
            ask = float(raw['Sell1']['Price']), float(raw['Sell1']['Qty'])
            assert 0 < bid[0] < ask[0] and bid[1] > 0 and ask[1] > 0
            bid_book, ask_book, current_volume = book(raw, 'Buy'), book(raw, 'Sell'), volume(raw)
            invalid_depth += int(bid_book is None or ask_book is None)
            if previous is not None:
                old_bid, old_ask, old_bid_book, old_ask_book, old_volume, old_seq = previous
                assert old_seq + 1 == seq
                ofi = best_ofi(old_bid, old_ask, bid, ask)
                bid_change = ask_change = None
                if all(item is not None for item in (bid_book, ask_book, old_bid_book, old_ask_book)):
                    bid_change = side_changes(old_bid_book, bid_book, 'bid')
                    ask_change = side_changes(old_ask_book, ask_book, 'ask')
                if current_volume is None or old_volume is None or current_volume < old_volume:
                    label = '出来高不明またはリセット'
                else:
                    label = '出来高不変' if current_volume == old_volume else '出来高正増分'
                accumulate(counts['全比較'], ofi, bid_change, ask_change)
                accumulate(counts[label], ofi, bid_change, ask_change)
            previous = bid, ask, bid_book, ask_book, current_volume, seq
    assert index == len(expected)
    return dict(セッション=session, 銘柄=symbol, 原本=str(path), 原本SHA256=hasher.hexdigest(),
                有効行数=index, 深板不正行数=invalid_depth, 観測合計=counts)


def main() -> None:
    """機能: 合成検査と46原本の全数集計を保存し、旧共通価格法との差を板観測資料へ追記する。

    引数: なし。返り値: なし(None)。旧作業ファイルは変更しない。
    """
    checks = synthetic_checks()
    (HERE / '表示範囲の合成監査.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf8')
    inputs = pickle.loads((ROOT / 'work/wave_v55/clean_inputs.pkl').read_bytes())
    baseline = json.loads((ROOT / 'work/wave_v52/measurement/気配キャッシュ監査.json').read_text(encoding='utf8'))
    hashes = {(row['セッション'], row['銘柄']): row['原本SHA256'] for row in baseline['原本別']}
    audits = []
    with ProcessPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(measure_one, key, inputs[key]['seq']): key for key in sorted(inputs)}
        for future in as_completed(futures):
            key = futures[future]
            row = future.result()
            assert row['原本SHA256'] == hashes[key]
            audits.append(row)
            print(f'{key[0]} {key[1]}: 最良OFI・表示範囲差分を測定', flush=True)
    audits.sort(key=lambda row: (row['セッション'], row['銘柄']))
    totals = {}
    for symbol in ('TOPIX', 'NK225'):
        totals[symbol] = {name: empty_counts() for name in ('全比較', '出来高不変', '出来高正増分', '出来高不明またはリセット')}
        for row in audits:
            if row['銘柄'] != symbol:
                continue
            for partition, values in row['観測合計'].items():
                for name, value in values.items():
                    totals[symbol][partition][name] += value
    output = dict(
        合格=True, 原本数=len(audits), 原本有効行数=sum(row['有効行数'] for row in audits),
        原本SHA256一致=True, 深板不正行数=sum(row['深板不正行数'] for row in audits),
        旧観測との差='共通表示価格の差分に、最良消失と表示範囲内欠落による既知消失/既知出現を加えた。遠方10段外へ出た旧価格、遠方から入った新価格は不明に分離し量差へ加えない。',
        bestOFI='bid上昇は新best数量、低下は旧best数量の負、同値は数量差。ask上昇は旧best数量の正、低下は新best数量の負、同値は旧数量−新数量。二側を合計。',
        OFIの意味='表示される最良価格・数量の変化。成行売買差、取消量、参加者の心理、将来方向とは同一でない。',
        数量合計の意味='各更新間の表示変化量を足した値。同じ数量が何度も出入りした場合を含み、固有注文数や出来高ではない。',
        品質='最良OFIは隣接有効best行。深板差分は両時点とも完全で順序正常な10段だけ。欠落・重複・順序不正を跨がない。',
        合成監査=checks, 銘柄別=totals, 原本別=audits,
        ATR使用=False, 損益参照=False, 現在API取得数=0,
    )
    target = HERE / '表示範囲補正とOFIの全数監査.json'
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    overview_path = HERE.parent / 'diagnosis/板の観測可能性.json'
    overview = json.loads(overview_path.read_text(encoding='utf8'))
    overview['表示範囲補正の追加観測'] = dict(説明=output['旧観測との差'], 根拠=str(target), 銘柄別=totals)
    overview_path.write_text(json.dumps(overview, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    print(json.dumps(totals, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
