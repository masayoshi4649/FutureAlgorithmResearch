"""原因診断の組集計を、元の決済台帳と別経路で突き合わせる。"""

import gzip
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1] / 'wave_v67'


def main() -> None:
    """機能: 全組の損益・枚数・途中値の行範囲を独立照合する。

    引数: なし。返り値: なし(None)。
    """
    checked = {}
    for code in ('E01', 'R01'):
        origin = json.loads(gzip.decompress((SOURCE / f'observed/{code}.json.gz').read_bytes()))
        diagnosis = json.loads((HERE / f'{code}_組別診断.json').read_text(encoding='utf8'))
        mapping = {(r['セッション'], r['銘柄'], r['組']):r for r in diagnosis}
        assert len(mapping) == len(diagnosis)
        for ledger in origin['ledgers']:
            for cycle in ledger['cycles']:
                record = mapping[ledger['session'], ledger['symbol'], int(cycle[0])]
                trades = [t for t in ledger['trades'] if t['組'] == int(cycle[0])]
                assert abs(record['損益'] - sum(t['収支'] for t in trades)) < 1e-6
                assert abs(record['総損益'] - cycle[3] * {'TOPIX':1000,'NK225':10}[ledger['symbol']]) < 1e-6
                assert record['枚数'] == sum(t['枚数'] for t in trades)
                assert record['最大順行ATR'] >= 0 and record['最大逆行ATR'] >= 0
                assert record['新規行'] == min(t['新規行'] for t in trades)
                assert record['返済行'] == max(t['返済行'] for t in trades)
                for midway in record['途中']:
                    if midway['生存']:
                        assert record['新規行'] <= midway['原本行'] < record['返済行']
                        assert 0 <= midway['過去最大順行ATR'] <= record['最大順行ATR']
                        assert 0 <= midway['過去最大逆行ATR'] <= record['最大逆行ATR']
            values = [r for r in diagnosis if r['セッション'] == ledger['session'] and r['銘柄'] == ledger['symbol']]
            row = next(r for r in origin['rows'] if r['session'] == ledger['session'] and r['symbol'] == ledger['symbol'])
            assert len(values) == row['campaigns']
            assert abs(sum(r['損益'] for r in values) - row['net']) < 1e-6
            assert abs(sum(r['手数料'] for r in values) - row['fees']) < 1e-6
        checked[code] = dict(口座数=len(origin['ledgers']), 組数=len(diagnosis), 会計一致=True, 途中範囲一致=True)
    (HERE / '診断会計の独立照合.json').write_text(json.dumps(checked, ensure_ascii=False, indent=2), encoding='utf8')
    print('診断会計の全組照合済み', checked, flush=True)


if __name__ == '__main__':
    main()
