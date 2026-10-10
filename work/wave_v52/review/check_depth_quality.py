"""既存入力に対応する46原本の10段品質を、特徴抽出器とは独立に検査する。"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def numeric(value: object) -> float | None:
    """機能: JSON値から有限数値だけを読む。

    引数: value(object)。返り値: 有限数値または欠測(float|None)。
    """
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (ValueError, TypeError):
        return None
    return parsed if math.isfinite(parsed) else None


def one_account(job: tuple[str, str]) -> dict:
    """機能: 原本1口座を逐次読み、最良有効板の10段品質を数える。

    引数: job(tuple[str,str])はセッションと銘柄。
    返り値: 行数と品質不備件数、少数の該当行(dict)。原本は読み取り専用。
    """
    session, symbol = job
    base, kind = session.rsplit('_', 1)
    day = datetime.fromisoformat(base).replace(tzinfo=timezone(timedelta(hours=9)))
    if kind == 'Day':
        start, end = day+timedelta(hours=8, minutes=45), day+timedelta(hours=15, minutes=40)
    else:
        start, end = day+timedelta(hours=17), day+timedelta(days=1, hours=5, minutes=55)
    a, b = start.timestamp(), end.timestamp()
    path = ROOT/'book'/symbol/(session+'.jsonl')
    counts = dict(原本行数=0, 時刻欠測=0, 時刻無zone=0, 時間外=0, 最良不正=0,
                  有効板=0, 十段欠測=0, 重複価格=0, 価格順不正=0, 十段不備=0)
    examples = []
    previous_stamp, seconds = None, None
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for seq, line in enumerate(stream):
            hasher.update(line)
            counts['原本行数'] += 1
            raw = json.loads(line)
            stamp = raw.get('CurrentPriceTime')
            if not stamp:
                counts['時刻欠測'] += 1
                continue
            if stamp != previous_stamp:
                parsed = datetime.fromisoformat(stamp)
                if parsed.tzinfo is None:
                    counts['時刻無zone'] += 1
                    continue
                seconds, previous_stamp = parsed.timestamp(), stamp
            if not a <= seconds < b:
                counts['時間外'] += 1
                continue
            bid, ask = raw.get('Buy1') or {}, raw.get('Sell1') or {}
            values = [numeric(bid.get('Price')), numeric(ask.get('Price')),
                      numeric(bid.get('Qty')), numeric(ask.get('Qty')), numeric(raw.get('CurrentPrice'))]
            if any(v is None or v <= 0 for v in values) or values[0] >= values[1]:
                counts['最良不正'] += 1
                continue
            counts['有効板'] += 1
            complete, duplicate, ordered = True, False, True
            for side in ('Buy', 'Sell'):
                prices = []
                for depth in range(1, 11):
                    level = raw.get(f'{side}{depth}') or {}
                    price, qty = numeric(level.get('Price')), numeric(level.get('Qty'))
                    if price is None or price <= 0 or qty is None or qty < 0:
                        complete = False
                        continue
                    prices.append(price)
                duplicate |= len(prices) != len(set(prices))
                sign = -1 if side == 'Buy' else 1
                ordered &= all(sign*(right-left) > 0 for left, right in zip(prices, prices[1:]))
            counts['十段欠測'] += int(not complete)
            counts['重複価格'] += int(duplicate)
            counts['価格順不正'] += int(not ordered)
            if not complete or duplicate or not ordered:
                counts['十段不備'] += 1
                if len(examples) < 5:
                    examples.append(dict(原本0始まり行=seq, 時刻=stamp,
                                         完全=complete, 重複=duplicate, 価格順正常=ordered))
    return dict(セッション=session, 銘柄=symbol, 原本SHA256=hasher.hexdigest(), 不備例=examples, **counts)


def main() -> None:
    """機能: 固定対象46口座を独立走査し、品質の全数監査を保存する。

    引数: なし。返り値: なし(None)。APIを利用しない。
    """
    source = ROOT/'work/wave_v51/overlay/research.py'
    spec = importlib.util.spec_from_file_location('depth_audit_inputs', source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    accounts = sorted(module.load()[0])
    results = []
    with ProcessPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(one_account, key): key for key in accounts}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(f'{result["セッション"]} {result["銘柄"]}: {result["有効板"]:,}有効板 / 不備{result["十段不備"]:,}', flush=True)
    results.sort(key=lambda x: (x['セッション'], x['銘柄']))
    names = [name for name, value in results[0].items() if isinstance(value, int)]
    total = {name: sum(row[name] for row in results) for name in names}
    report = dict(原本数=len(results), 合計=total, 原本別=results,
                  抽出器と独立=True, 現在API取得数=0,
                  判定='最良有効板に十段不備があれば距離供給等へ品質条件が必要。未来価格は参照しない。')
    (HERE/'十段品質の全数監査.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(total, ensure_ascii=False))


if __name__ == '__main__':
    main()
