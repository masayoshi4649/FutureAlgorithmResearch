"""固定した第二試行を再運転せず、共通順位と実損失親を短く射影する。"""

from pathlib import Path
import hashlib
import json

import numpy as np

HERE = Path(__file__).resolve().parent


def metrics(rows: list) -> dict:
    """
    機能: 全場を分母として無取引を別記する。
    引数: rows(list[dict]) は一政策一商品の全40場。
    返り値: dict。円額の銘柄横断比較は行わない。
    """
    net = np.array([r['net'] for r in rows])
    black = net[net > 1e-7]
    red = net[net < -1e-7]
    absolute = np.abs(net).mean()
    return dict(black=len(black), red=len(red), idle=sum(r['fills'] == 0 for r in rows),
                net=float(net.sum()), median=float(np.median(net)), mean=float(net.mean()),
                normalized_median=float(np.median(net) / absolute) if absolute else 0.,
                worst=float(net.min()), mean_black=float(black.mean()) if len(black) else None,
                worst_ratio=float(-red.min() / black.mean()) if len(black) and len(red) else (0. if len(black) else 1e99),
                without_top3=float(net.sum() - np.sort(black)[-3:].sum()),
                profit=sum(r['profit'] for r in rows), loss=sum(r['loss'] for r in rows),
                parents=sum(r['parents'] for r in rows), fees=sum(r['fees'] for r in rows),
                unclosed=sum(r['unclosed'] for r in rows))


def main() -> None:
    """
    機能: 指定SHA結果を一度私有保全し、主候補と損失親を保存する。
    引数: なし。新しい金融再生は行わない。
    返り値: None。事後順位を未知検証の選択と呼ばない。
    """
    source = HERE / 'measurement/復帰確認と執行保護の全四十場.json'
    payload = source.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == '7c56485d4b168928bd432cdb9644037ad2c4d733c19b3fc0168786a928b0586f'
    out = HERE / 'root_owned'
    assert not out.exists()
    out.mkdir()
    (out / source.name).write_bytes(payload)
    data = json.loads(payload)
    summaries = {s['id']: {symbol: metrics([r for r in data['runs'] if r['method'] == s['id'] and r['symbol'] == symbol])
                          for symbol in ('TOPIX', 'NK225')} for s in data['specs']}
    ranking = []
    for spec in data['specs']:
        if spec['id'].startswith('BASELINE'):
            continue
        m = summaries[spec['id']]
        eligible = all(x['net'] > 0 and x['median'] > 0 and x['without_top3'] > 0 and x['unclosed'] == 0 for x in m.values())
        ranking.append(dict(id=spec['id'], family=spec['family'], eligible=eligible, metrics=m))
    ranking.sort(key=lambda r: (-int(r['eligible']), -min(m['black'] for m in r['metrics'].values()),
                 -min(m['normalized_median'] for m in r['metrics'].values()),
                 max(m['worst_ratio'] for m in r['metrics'].values()), r['id']))
    top = ranking[0]['id']
    episodes = []
    for symbol in ('TOPIX', 'NK225'):
        rows = [r for r in data['runs'] if r['method'] == top and r['symbol'] == symbol]
        bad = sorted(rows, key=lambda r: r['net'])[:3]
        good = sorted(rows, key=lambda r: -r['net'])[:1]
        for row in bad + good:
            trade = next(e for e in data['episodes'] if e['symbol'] == symbol and e['method'] == top and e['session'] == row['session'])
            episodes.append(dict(row=row, parents=trade['parents']))
    result = dict(ranking=ranking, baseline={k: v for k, v in summaries.items() if k.startswith('BASELINE')},
                  all_summaries=summaries, ranked_top_worst_and_winner=episodes, 新金融=0)
    (out / '全条件の事後比較と損失親.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(top=ranking[:6], baseline=result['baseline']), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
