"""取得済みの途中夜間原板から、売買を行わず検証用の気配列を作る。"""

from pathlib import Path
from datetime import datetime, timezone, timedelta
import hashlib
import json
import pickle
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
JST = timezone(timedelta(hours=9))


def main():
    """途中場の時刻・気配と入力指紋を保存する。

    引数: なし。
    返り値: None。売買条件は評価せず、追加のAPI取得もしない。
    """
    source = ROOT / 'work/current_idle_20261026/三波確認/data/NK225_book.jsonl'
    stamp = lambda value: datetime.fromisoformat(value).timestamp()
    start = stamp('2026-10-26T17:00:00+09:00')
    limit = stamp('2026-10-27T06:00:00+09:00')
    cutoff = stamp('2026-10-26T21:13:52+09:00')
    us_open = stamp('2026-10-26T22:30:00+09:00')
    rows, counts = [], dict(raw=0, outside=0, invalid_clock=0, reversed=0, invalid_last=0)
    previous = start
    with source.open(encoding='utf-8') as stream:
        for line in stream:
            counts['raw'] += 1
            value = json.loads(line)
            try:
                at = stamp(value['CurrentPriceTime'])
            except (KeyError, TypeError, ValueError):
                counts['invalid_clock'] += 1
                continue
            if not start <= at < cutoff:
                counts['outside'] += 1
                continue
            if at < previous:
                counts['reversed'] += 1
                continue
            last = value.get('CurrentPrice') or 0.
            if not np.isfinite(last) or last <= 0:
                counts['invalid_last'] += 1
                continue
            previous = at
            bid = float(value.get('Buy1', {}).get('Price') or 0.)
            ask = float(value.get('Sell1', {}).get('Price') or 0.)
            bq = float(value.get('Buy1', {}).get('Qty') or 0.)
            aq = float(value.get('Sell1', {}).get('Qty') or 0.)
            valid = np.isfinite([bid, ask, bq, aq]).all() and 0 < bid < ask and min(bq, aq) > 0
            rows.append([at, bid, ask, valid])
    array = np.asarray(rows, float)
    data = dict(ready=dict(session='2026-10-26_Night', time_s=array[:, 0], start=start,
                          limit=limit, us_open=us_open, tick=10., partial=True),
                quotes=dict(bid=array[:, 1], ask=array[:, 2], quote_valid=array[:, 3].astype(bool)))
    empty = np.empty((0, 10))
    payload = dict(data=data, label=dict(direction='途中', first_price=None, final_price=None),
                   baseline=empty, pre=empty, post=empty, partial=True)
    target = HERE / 'inputs/2026-10-26_Night.pkl'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))
    counts.update(accepted=len(rows), valid_quotes=int(array[:, 3].sum()), first=array[0, 0], last=array[-1, 0])
    manifest = dict(session='2026-10-26_Night', cutoff='2026-10-26T21:13:52+09:00', counts=counts,
        source=str(source.relative_to(ROOT)), source_sha256=hashlib.file_digest(source.open('rb'), 'sha256').hexdigest(),
        target=str(target.relative_to(ROOT)), target_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        limitation='原価格時計を代用。同時刻は原行順。実受信時計は無い。終端は清算せず含み損益を別表示。')
    (HERE / 'current_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(counts))


if __name__ == '__main__':
    main()
