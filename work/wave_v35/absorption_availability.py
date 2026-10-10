"""既存原本の固定先頭区間で、出来高と可視最良数量を同時に観測できるか確認する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def inspect(symbol: str) -> dict:
    """機能: 2026年9月21日日中の先頭2万行を読み、価格・数量不変の出来高増分を数える。

    引数: symbol (str) はTOPIX又はNK225。返り値: 可用性と原本行例 (dict)。
    この固定接頭部だけの存在確認であり、全期間の頻度・収益性を推定しない。
    """
    path = ROOT / 'book' / symbol / '2026-09-21_Day.jsonl'
    previous = None
    examples, keys = [], []
    positive = stable = read = 0
    fingerprint = hashlib.sha256()
    with path.open('rb') as stream:
        for seq, line in enumerate(stream):
            if seq >= 20000:
                break
            fingerprint.update(line)
            read = seq + 1
            current = json.loads(line)
            keys = sorted(current)
            bid, ask = current.get('Buy1') or {}, current.get('Sell1') or {}
            values = (current.get('CurrentPrice'), current.get('TradingVolume'),
                      bid.get('Price'), ask.get('Price'), bid.get('Qty'), ask.get('Qty'))
            if any(value is None for value in values) or values[2] >= values[3]:
                previous = None
                continue
            if previous is not None:
                prior_seq, prior, old = previous
                delta = values[1] - old[1]
                if delta > 0:
                    positive += 1
                    if values[2:] == old[2:] and values[0] == old[0]:
                        stable += 1
                        if len(examples) < 2:
                            examples.append(dict(前seq=prior_seq, 後seq=seq,
                                前価格時刻=prior.get('CurrentPriceTime'), 後価格時刻=current.get('CurrentPriceTime'),
                                前出来高時刻=prior.get('TradingVolumeTime'), 後出来高時刻=current.get('TradingVolumeTime'),
                                価格=values[0], 累積出来高前後=[old[1], values[1]],
                                累積売買代金前後=[prior.get('TradingValue'), current.get('TradingValue')],
                                Buy1=bid, Sell1=ask))
            previous = seq, current, values
    return dict(対象=path.relative_to(ROOT).as_posix(), 先頭読取行数=read,
        読取接頭部SHA256=fingerprint.hexdigest(), 累積出来高増加の隣接観測数=positive,
        最良両側価格数量と現在値すべて不変の増加観測数=stable, 例=examples, 原本キー=keys)


def main() -> None:
    """機能: 固定2接頭部の存在確認を保存し、同じ原本の再読取一致を確認する。

    引数: なし。返り値: なし (None)。API・取引再生・売買閾値の探索は行わない。
    """
    rows = [inspect(symbol) for symbol in ('TOPIX', 'NK225')]
    assert rows == [inspect(symbol) for symbol in ('TOPIX', 'NK225')]
    value = dict(用途='データ可用性の読取確認。全期間頻度や真の補充量の推定ではない。',
        原本行は0始まり=True, 対象=rows, 再読取一致=True, API取得数=0,
        現在保存物使用=False, 新規損益再生=False, 売買閾値変更=False)
    (HERE / '見えない補充代理の可用性.json').write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
