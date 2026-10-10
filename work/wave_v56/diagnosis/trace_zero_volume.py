"""原本行ごとの出来高不変と気配後退を確認し、時刻ブロック集計の識別限界を補う。"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import pickle


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def finite(value: object) -> float | None:
    """機能: JSONの数値を有限値に限定し、欠測を0に置き換えず返す。

    引数: value(object)。返り値: 有限値または欠測(float|None)。
    """
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def displayed(raw: dict, side: str) -> dict | None:
    """機能: 一方の10段表示が完全・順序正当な場合だけ価格別数量を返す。

    引数: raw(dict)、side(str)。返り値: 価格数量辞書または品質不良(dict|None)。
    """
    levels = []
    for index in range(1, 11):
        item = raw.get(f'{side}{index}') or {}
        price, quantity = finite(item.get('Price')), finite(item.get('Qty'))
        if price is None or quantity is None or price <= 0 or quantity < 0:
            return None
        levels.append((price, quantity))
    for before, after in zip(levels, levels[1:]):
        if (before[0] <= after[0] if side == 'Buy' else before[0] >= after[0]):
            return None
    return dict(levels)


def trace(path: Path, expected: object) -> dict:
    """機能: 既存の全有効原本行を同じ順序で走査し、出来高0変化時の気配変化を数える。

    引数: path(Path)、expected(ndarray) は既存有効原本seq。
    返り値: 原本品質・件数・最初の具体例(dict)。取消と執行を識別したとは扱わない。
    """
    counts = dict(有効隣接比較数=0, 出来高両時点既知比較数=0, 出来高不変比較数=0,
                  出来高正増分比較数=0, 出来高リセット比較数=0,
                  出来高不変かつ買い気配低下数=0, 出来高不変かつ売り気配上昇数=0,
                  出来高不変かつ中値下落数=0, 出来高不変かつ中値上昇数=0,
                  出来高不変かつ買い気配低下で買い同価格表示純減数=0)
    examples, previous, index = [], None, 0
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for seq, line in enumerate(stream):
            hasher.update(line)
            if index >= len(expected) or seq != expected[index]:
                previous = None
                continue
            raw = json.loads(line)
            index += 1
            bid, ask = float(raw['Buy1']['Price']), float(raw['Sell1']['Price'])
            volume = finite(raw.get('TradingVolume'))
            if volume is not None and volume < 0:
                volume = None
            if previous is not None:
                before, previous_bid, previous_ask, previous_volume, previous_seq = previous
                assert previous_seq + 1 == seq
                counts['有効隣接比較数'] += 1
                if volume is not None and previous_volume is not None:
                    counts['出来高両時点既知比較数'] += 1
                    change = volume - previous_volume
                    if change > 0:
                        counts['出来高正増分比較数'] += 1
                    elif change < 0:
                        counts['出来高リセット比較数'] += 1
                    else:
                        counts['出来高不変比較数'] += 1
                        lower, higher = bid < previous_bid, ask > previous_ask
                        middle = (bid + ask) - (previous_bid + previous_ask)
                        counts['出来高不変かつ買い気配低下数'] += int(lower)
                        counts['出来高不変かつ売り気配上昇数'] += int(higher)
                        counts['出来高不変かつ中値下落数'] += int(middle < 0)
                        counts['出来高不変かつ中値上昇数'] += int(middle > 0)
                        if lower:
                            old_book, new_book = displayed(before, 'Buy'), displayed(raw, 'Buy')
                            if old_book is not None and new_book is not None:
                                common = old_book.keys() & new_book.keys()
                                net = sum(new_book[price] - old_book[price] for price in common)
                                if net < 0:
                                    counts['出来高不変かつ買い気配低下で買い同価格表示純減数'] += 1
                                    if len(examples) < 3:
                                        examples.append(dict(前原本行=previous_seq, 原本行=seq,
                                                             約定時計=raw.get('CurrentPriceTime'),
                                                             前出来高=previous_volume, 出来高=volume,
                                                             前買い気配=previous_bid, 買い気配=bid,
                                                             前売り気配=previous_ask, 売り気配=ask,
                                                             買い共通表示価格の数量純変化=net,
                                                             前の最良買い価格が現表示に残る=previous_bid in new_book))
            previous = raw, bid, ask, volume, seq
    assert index == len(expected)
    return dict(原本=str(path), 原本SHA256=hasher.hexdigest(), 有効原本行数=index,
                件数=counts, 最初の原本例=examples)


def main() -> None:
    """機能: 46原本を読取専用で走査し、キャッシュとの原本不変照合も保存する。

    引数: なし。返り値: なし(None)。損益、将来価格、取引条件は参照しない。
    """
    inputs = pickle.loads((ROOT / 'work/wave_v55/clean_inputs.pkl').read_bytes())
    baseline = json.loads((ROOT / 'work/wave_v52/measurement/気配キャッシュ監査.json').read_text(encoding='utf8'))
    hashes = {(row['セッション'], row['銘柄']): row['原本SHA256'] for row in baseline['原本別']}
    audits, sums = [], {symbol: {} for symbol in ('TOPIX', 'NK225')}
    for key in sorted(inputs):
        session, symbol = key
        audit = trace(ROOT / 'book' / symbol / f'{session}.jsonl', inputs[key]['seq'])
        assert audit['原本SHA256'] == hashes[key], key
        audit.update(セッション=session, 銘柄=symbol)
        audits.append(audit)
        for name, value in audit['件数'].items():
            sums[symbol][name] = sums[symbol].get(name, 0) + value
        print(f'{session} {symbol}: 原本行での出来高不変・買い気配低下 {audit["件数"]["出来高不変かつ買い気配低下数"]:,}', flush=True)
    output = dict(
        目的='CurrentPriceTimeブロック全体では出来高増分が常に正でも、その内部で出来高が変わらず気配が後退する更新が存在するかを直接原本で確かめる。',
        観測='同じ累積出来高の二つの隣接有効原本行で、買い気配の低下または売り気配の上昇を数える。',
        深板='前後とも正しく並ぶ10段の共通価格だけで数量差を数える。表示範囲外に消えた量を取消量として加算しない。',
        限界='記録された出来高の不変を直接観測した。取消、新規指値、未反映約定、配信の分割更新を完全に識別する情報はない。通信受信時刻も不明。',
        因果主張='これだけで取消が価格下落を起こしたとは断定しない。価格移動を最終約定値や推定成行量だけで説明しきれない観測例である。',
        原本不変=True, ATR使用=False, 将来損益参照=False, API取得数=0,
        銘柄別=sums, 原本別=audits,
    )
    (HERE / '出来高不変時の原本気配変化.json').write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    print(json.dumps(sums, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
