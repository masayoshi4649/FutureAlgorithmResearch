"""時計変更による新規件数増加と、同時刻・異なる時刻の組を会計分解する。"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read(identifier: str) -> dict:
    """機能: 各銘柄・場の保存台帳を読む。

    引数: identifier(str)。返り値: 台帳辞書(dict)。
    """
    rows = json.loads(gzip.decompress((HERE / 'ledgers' / (identifier+'.json.gz')).read_bytes()))
    return {(r['session'], r['symbol']): r for r in rows}


def positions(ledger: dict) -> dict:
    """機能: 組を初回時刻・方向・価格の組で識別して収支を対応させる。

    引数: ledger(dict)。返り値: 組収支(dict)。
    """
    values = {}
    for cycle in ledger['cycles']:
        order = next(o for o in ledger['orders'] if o[2] == cycle[0] and o[7] == 1)
        key = int(order[0]), int(order[3]), float(order[5])
        assert key not in values
        values[key] = cycle[3] * ledger['config']['point_value']
    return values


def main() -> None:
    """機能: 既存版対新時計と同休止15分同士を比較する。

    引数: なし。返り値: なし(None)。
    """
    result = {}
    for old, new in (('K00', 'K20'), ('K04', 'K20'), ('K00', 'K04'), ('K00', 'K24')):
        if not all((HERE / 'ledgers' / (identifier+'.json.gz')).exists() for identifier in (old, new)):
            continue
        before, after = read(old), read(new)
        rows = []
        for key in before:
            a, b = positions(before[key]), positions(after[key])
            common = a.keys() & b.keys()
            only_a, only_b = a.keys()-b.keys(), b.keys()-a.keys()
            change = sum(b.values()) - sum(a.values())
            common_change = sum(b[k]-a[k] for k in common)
            assert abs(common_change+sum(b[k] for k in only_b)-sum(a[k] for k in only_a)-change) < 1e-6
            rows.append(dict(セッション=key[0], 銘柄=key[1], 旧収支円=sum(a.values()), 新収支円=sum(b.values()), 差額円=change,
                旧組数=len(a), 新組数=len(b), 同じ入口数=len(common), 同じ入口の収支変化円=common_change,
                旧だけの入口数=len(only_a), 旧だけの入口収支円=sum(a[k] for k in only_a),
                新だけの入口数=len(only_b), 新だけの入口収支円=sum(b[k] for k in only_b)))
        total = {}
        for symbol in ('TOPIX', 'NK225'):
            own = [r for r in rows if r['銘柄'] == symbol]
            total[symbol] = {field: sum(r[field] for r in own) for field in rows[0] if field not in ('セッション', '銘柄')}
        result[old+'→'+new] = dict(総計=total, 各場=rows)
    output = dict(比較=result, 注意='同じ入口は原本行・方向・初回価格が同一の組。新だけの入口には追加再入だけでなく入口時刻が変更された組を含む。会計分解であり、その組だけを除いた反実仮想の再生ではない。')
    (HERE / '時計変更の分解.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({key: value['総計'] for key, value in result.items()}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
