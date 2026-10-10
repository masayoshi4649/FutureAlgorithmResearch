"""E01の赤字・黒字・同値時間帯を事後分類し、他方式の同じ区間を比較する。"""
from pathlib import Path
import gzip
import json

HERE = Path(__file__).resolve().parent


def main() -> None:
    """機能: E01の時間帯別損益区分ごとに他方式の口座増減を比較する。

    引数: なし。返り値: なし(None)。分類は事後説明用で注文判断へ渡さない。
    """
    source = json.loads(gzip.decompress((HERE / '時間区間損益.json.gz').read_bytes()))
    lookup = {}
    for account in source['口座']:
        method = account['手法']
        for row in account['区間']:
            key = account['セッション'], account['銘柄'], row['開始'], row['終了_未満']
            lookup.setdefault(method, {})[key] = row
    base = lookup['E01']
    for rows in lookup.values():
        assert set(rows) == set(base)
    sessions = sorted({key[0] for key in base})
    groups = {'全23': sessions, '既知追加4': sessions[-4:]}
    result = []
    for period, chosen in groups.items():
        for symbol in ('TOPIX', 'NK225'):
            matching = [key for key in base if key[0] in chosen and key[1] == symbol]
            categories = {'E01赤字区間': [key for key in matching if base[key]['時価収支円'] < 0],
                          'E01黒字区間': [key for key in matching if base[key]['時価収支円'] > 0],
                          'E01同値区間': [key for key in matching if base[key]['時価収支円'] == 0]}
            assert sum(len(keys) for keys in categories.values()) == len(matching)
            for method, rows in lookup.items():
                classified = []
                for label, keys in categories.items():
                    baseline = sum(base[key]['時価収支円'] for key in keys)
                    value = sum(rows[key]['時価収支円'] for key in keys)
                    classified.append(dict(区分=label, 区間数=len(keys), E01時価収支円=baseline,
                                           比較時価収支円=value, 差円=value - baseline,
                                           改善区間数=sum(rows[key]['時価収支円'] > base[key]['時価収支円'] for key in keys),
                                           悪化区間数=sum(rows[key]['時価収支円'] < base[key]['時価収支円'] for key in keys),
                                           比較方式赤字区間数=sum(rows[key]['時価収支円'] < 0 for key in keys)))
                assert abs(sum(row['比較時価収支円'] for row in classified) - sum(rows[key]['時価収支円'] for key in matching)) < 1e-7
                result.append(dict(期間=period, 銘柄=symbol, 手法=method, 区分別=classified))
    worst = []
    for symbol in ('TOPIX', 'NK225'):
        selected = [key for key in base if key[0] in sessions[-4:] and key[1] == symbol]
        selected.sort(key=lambda key: base[key]['時価収支円'])
        for key in selected[:5]:
            worst.append(dict(セッション=key[0], 銘柄=symbol, 開始=key[2], 終了_未満=key[3],
                              手法別時価収支円={method: rows[key]['時価収支円'] for method, rows in lookup.items()}))
    document = dict(用途='E01の結果を見た後の損失時間帯の説明。新規判断・候補選択にこの分類を使わない。',
                    指標='返済損益だけでなく含みの増減を含む時価収支。', 比較=result, 既知追加4の最大赤字区間=worst)
    (HERE / 'E01赤字区間比較.json').write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(dict(手法数=len(lookup), 比較組数=len(result), 最大赤字窓数=len(worst)), ensure_ascii=False))


if __name__ == '__main__':
    main()
