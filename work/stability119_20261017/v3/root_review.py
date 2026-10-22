"""第三対照を再実行せず、張り方ごとの安定性と残った損失親を確認する。"""

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('_second_summary119', HERE.parent / 'v2/root_review.py')
PREVIOUS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREVIOUS)


def main() -> None:
    """
    機能: 全第三対照から共通候補と小枚数対照を同じ事前順位で射影する。
    引数: なし。指定完成SHAの結果だけを読む。
    返り値: None。順位は既知開発の事後比較とする。
    """
    source = HERE / 'measurement/小試行と順行追加の全四十場.json'
    payload = source.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == '0e027e11a03e4f6a8c0bf9f1166e9f7487505ab91be5ea12b0d76eb9a88b0ca5'
    own = HERE / 'root_owned'
    own.mkdir(exist_ok=False)
    (own / source.name).write_bytes(payload)
    data = json.loads(payload)
    summaries, ranking = {}, []
    for spec in data['specs']:
        m = {symbol: PREVIOUS.metrics([r for r in data['runs'] if r['symbol'] == symbol and r['method'] == spec['id']])
             for symbol in ('TOPIX', 'NK225')}
        summaries[spec['id']] = m
        eligible = all(x['net'] > 0 and x['median'] > 0 and x['without_top3'] > 0 and x['unclosed'] == 0 for x in m.values())
        ranking.append(dict(id=spec['id'], family=spec['family'], eligible=eligible, metrics=m))
    ranking.sort(key=lambda r: (-int(r['eligible']), -min(x['black'] for x in r['metrics'].values()),
                 -min(x['normalized_median'] for x in r['metrics'].values()),
                 max(x['worst_ratio'] for x in r['metrics'].values()), r['id']))
    selected = ranking[0]['id']
    details = []
    for symbol in ('TOPIX', 'NK225'):
        rows = [r for r in data['runs'] if r['method'] == selected and r['symbol'] == symbol]
        for row in sorted(rows, key=lambda r: r['net'])[:3] + sorted(rows, key=lambda r: -r['net'])[:1]:
            detail = next(e for e in data['episodes'] if e['method'] == selected and e['symbol'] == symbol and e['session'] == row['session'])
            details.append(dict(row=row, episode=detail))
    result = dict(ranking=ranking, all_summaries=summaries, top_worst_and_winner=details, 新金融=0)
    (own / '全条件と張り方及び残った損失の事後比較.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(qualified=sum(x['eligible'] for x in ranking), top=ranking[:5]), ensure_ascii=False, indent=2))
    for family in ('COMMON20', 'OPEN20', 'CENTER20', 'FAIL20', 'A20', 'D20'):
        print(family, {mode: {s: {k: m[k] for k in ('net', 'black', 'red', 'idle', 'median', 'worst', 'without_top3')}
                             for s, m in summaries[f'{family}_{mode}_T10'].items()} for mode in ('SCOUT', 'FULL', 'GROW')})


if __name__ == '__main__':
    main()
