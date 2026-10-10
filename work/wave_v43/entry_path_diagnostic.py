"""同じ初回約定だけを対応させ、合議の入口経路差を事後診断する。"""

from __future__ import annotations

import runner

HERE = runner.HERE


def campaigns(identifier: str) -> dict:
    """機能: 台帳の元組を、場・銘柄・初回約定行・方向で一意に並べる。

    引数: identifier(str)。返り値: 元組辞書(dict)。旧組番号を条件間対応へ使わない。
    """
    output = {}
    for ledger in runner.read(HERE/'ledgers'/(identifier+'.json.gz')):
        factor = ledger['config']['point_value']
        for cycle in ledger['cycles']:
            key = (ledger['session'], ledger['symbol'], int(cycle[1]), int(cycle[8]))
            assert key not in output
            opening = [o for o in ledger['orders'] if o[2] == cycle[0] and o[6] == 20 and o[7] == 1]
            assert len(opening) == 1 and opening[0][0] == key[2] and opening[0][3] == key[3]
            output[key] = dict(session=key[0], symbol=key[1], entry_row=key[2], side=key[3],
                close_row=int(cycle[2]), net_yen=cycle[3]*factor, initial_risk_yen=cycle[4]*factor,
                initial_atr=cycle[5], entry_price=opening[0][5], initial_qty=int(opening[0][4]))
    return output


def main() -> None:
    """機能: 二出口×三合議中央を同じ単一中央へ比べ、入口経路と収支差を保存する。

    引数: なし。返り値: なし(None)。事後診断であり、固定採否や売買規則は変更しない。
    """
    guard = runner.read(HERE/'追加完備監査.json')
    assert guard['全合格']
    runner.verify(guard['参照資料SHA256'])
    cells = []
    for manager in runner.design.MANAGERS:
        reference_id = f'S100__{manager}__V000'
        reference = campaigns(reference_id)
        for mode in ('M2', 'V2', 'U3'):
            identifier = f'{mode}_100__{manager}__V000'
            actual = campaigns(identifier)
            for symbol in runner.old.SYMBOLS:
                a = {k:v for k,v in actual.items() if k[1] == symbol}
                b = {k:v for k,v in reference.items() if k[1] == symbol}
                common = sorted(a.keys() & b.keys())
                for key in common:
                    for field in ('initial_qty', 'entry_price', 'initial_risk_yen', 'initial_atr'):
                        assert a[key][field] == b[key][field], (identifier, key, field)
                added = [a[k] for k in sorted(a.keys()-b.keys())]
                removed = [b[k] for k in sorted(b.keys()-a.keys())]
                changes = [dict(**a[k], old_net_yen=b[k]['net_yen'], difference_yen=a[k]['net_yen']-b[k]['net_yen']) for k in common]
                delta = sum(v['net_yen'] for v in a.values())-sum(v['net_yen'] for v in b.values())
                reconstructed = sum(v['difference_yen'] for v in changes)+sum(v['net_yen'] for v in added)-sum(v['net_yen'] for v in removed)
                assert abs(delta-reconstructed) < 1e-6
                cells.append(dict(id=identifier, reference=reference_id, symbol=symbol,
                    旧取引組数=len(b), 新取引組数=len(a), 同じ初回約定組数=len(common),
                    同じ初回約定の収支差円=sum(v['difference_yen'] for v in changes),
                    共通組の価格数量初期ATRリスク一致=True,
                    共通各組の収支個別一致=all(v['difference_yen'] == 0 for v in changes),
                    新側だけの初回約定組数=len(added), 旧側だけの初回約定組数=len(removed),
                    新側未対応組収支円=sum(v['net_yen'] for v in added),
                    旧側未対応組収支円=sum(v['net_yen'] for v in removed), 全収支差円=delta,
                    対応組=changes, 新側未対応=added, 旧側未対応=removed))
    runner.save(HERE/'入口経路の事後診断.json', dict(全合格=True, 事後診断=True,
        説明='同時刻・同方向の初回約定行だけを対応させる。未対応には時刻ずれも含み、純粋な追加又は消滅取引とは呼ばない。',
        採否変更=False, 売買再生=False, 結果=cells,
        元追加完備SHA256=runner.digest(HERE/'追加完備監査.json'), 実装SHA256=runner.digest(HERE/'entry_path_diagnostic.py')))
    for row in cells:
        print({k:v for k,v in row.items() if not isinstance(v, list)})


if __name__ == '__main__':
    main()
