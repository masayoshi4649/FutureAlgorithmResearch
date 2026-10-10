"""最終価格約定の感度試験に使う、同じ原本行の最良買い・売り気配を抽出する。"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle
import time

import numpy as np

from extract import HERE, ROOT, finite, save_json


def load_inputs_only() -> dict:
    """機能: 売買結果ファイルを開かずに、監査済み逐次価格入力だけを集める。

    引数: なし。返り値: 46口座の入力辞書(dict)。
    """
    paths = [ROOT / 'work/wave_v47/inputs.pkl']
    paths += [ROOT / 'work/wave_v48' / folder / 'new_inputs.pkl'
              for folder in ('update_20260930', 'update_20261001')]
    paths += [ROOT / 'work/wave_v50' / folder / 'new_inputs.pkl'
              for folder in ('update_20261001_day', 'update_20261002_two', 'update_20261007_added')]
    result = {}
    for path in paths:
        values = pickle.loads(path.read_bytes())
        assert not set(values).intersection(result)
        result.update(values)
    assert len(result) == 46
    return result


def extract_quotes(path: Path, ready: dict) -> tuple[dict, dict]:
    """機能: 既存の有効行番号に対応する最良気配を原本の記録順に読み出す。

    引数: path(Path)、ready(dict)。返り値: 気配配列と監査情報(tuple[dict,dict])。
    過去・未来の行で価格を補間せず、同じ原本行だけを使用する。
    """
    expected = np.asarray(ready['seq'], dtype=np.int64)
    size = len(expected)
    bid, ask = np.empty(size, dtype=np.float64), np.empty(size, dtype=np.float64)
    index = raw_count = 0
    hasher = hashlib.sha256()
    previous_text, current_s = None, None
    with path.open('rb') as stream:
        for seq, line in enumerate(stream):
            raw_count += 1
            hasher.update(line)
            if index >= size or seq != expected[index]:
                continue
            raw = json.loads(line)
            buyer = raw.get('Buy1') or {}
            seller = raw.get('Sell1') or {}
            bid_price, ask_price = finite(buyer.get('Price')), finite(seller.get('Price'))
            bid_qty, ask_qty = finite(buyer.get('Qty')), finite(seller.get('Qty'))
            assert 0 < bid_price < ask_price and bid_qty > 0 and ask_qty > 0, (path, seq)
            last = finite(raw.get('CurrentPrice'))
            assert last > 0 and last == ready['last'][index], (path, seq, '最終価格不一致')
            stamp = raw.get('CurrentPriceTime')
            assert stamp, (path, seq, '約定時刻欠損')
            if stamp != previous_text:
                parsed = datetime.fromisoformat(stamp)
                assert parsed.tzinfo is not None, (path, seq, 'タイムゾーン欠損')
                current_s, previous_text = parsed.timestamp(), stamp
            assert current_s == ready['time_s'][index], (path, seq, '時刻不一致')
            bid[index], ask[index] = bid_price, ask_price
            index += 1
    assert index == size and np.isfinite(bid).all() and np.isfinite(ask).all()
    mid = (bid + ask) / 2.
    spread = (ask - bid) / ready['tick']
    last = np.asarray(ready['last'], dtype=float)
    # ----------------------------------------
    # これは気配との位置関係だけの記述であり、注文・将来収益を参照しない。
    audit = dict(原本=str(path), 原本SHA256=hasher.hexdigest(), 読取行数=raw_count,
                 気配行数=size, 原本行番号時刻最終価格一致=True,
                 最終価格が買い気配より下=int((last < bid).sum()),
                 最終価格が売り気配より上=int((last > ask).sum()),
                 最終価格が気配の間または端=int(((bid <= last) & (last <= ask)).sum()),
                 最終価格と中値の差絶対値中央値呼値=float(np.median(np.abs(last - mid) / ready['tick'])),
                 スプレッド中央値呼値=float(np.median(spread)),
                 スプレッド最大呼値=float(np.max(spread)))
    result = dict(seq=expected.copy(), time_s=np.asarray(ready['time_s']).copy(), bid=bid, ask=ask, mid=mid)
    return result, audit


def main() -> None:
    """機能: 全46原本の気配を保存し、既存特徴抽出時の原本ハッシュとも比較する。

    引数: なし。返り値: なし(None)。売買成績を読み込まずAPIへ接続しない。
    """
    inputs = load_inputs_only()
    baseline = json.loads((HERE / '監査.json').read_text(encoding='utf8'))
    hashes = {row['原本']: row['原本SHA256'] for row in baseline['原本別']}
    output, audits = {}, []
    for key in sorted(inputs):
        session, symbol = key
        started = time.monotonic()
        path = ROOT / 'book' / symbol / f'{session}.jsonl'
        values, audit = extract_quotes(path, inputs[key])
        assert audit['原本SHA256'] == hashes[str(path)], (path, '原本ハッシュ変更')
        audit.update(セッション=session, 銘柄=symbol, 処理秒=round(time.monotonic() - started, 2))
        output[key] = values
        audits.append(audit)
        print(f'{session} {symbol}: {audit["気配行数"]:,} 気配行 / {audit["処理秒"]} 秒', flush=True)
    (HERE / 'quotes.pkl').write_bytes(pickle.dumps(output, pickle.HIGHEST_PROTOCOL))
    summary = dict(合格=True, 原本数=len(audits), 原本行数=sum(row['読取行数'] for row in audits),
                   気配行数=sum(row['気配行数'] for row in audits),
                   コードSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   定義='Buy1は買い気配bid、Sell1は売り気配ask。midはその平均。readyの各seqと同じ原本行。',
                   感度試験の用途='買い注文を同じ約定行のask、売り注文をbidへ置換する固定注文時刻の感度試験。注文時刻・数量・判断・損切り条件を置換後に再計算するバックテストではない。',
                   限界='板の正確な受信時刻、実際の待ち行列、板消費、遅延、約定保証は再現しない。最良数量以上の注文について全量約定を保証しない。',
                   原本不変=True, 売買結果未使用=True, 現在API取得数=0, 原本別=audits)
    save_json(HERE / '気配キャッシュ監査.json', summary)


if __name__ == '__main__':
    main()
