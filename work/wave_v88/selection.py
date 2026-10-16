"""前半だけで参考配分を選び、後半の成績で選び直さない。"""


def select(results):
    """
    機能: 前16場の共通黒字と活動を確認し、商品内の収支下落比で参考を選ぶ。
    引数: results(dict[str,dict]) は固定22条件の結果。
    返り値: tuple[str又はNone,list[dict]]。選定IDと全21候補の判定証拠。
    """
    rows = []
    for identifier, result in results.items():
        if identifier == 'GU_HALF':
            continue
        stats = result['periods']['前16']
        eligible = all(stats[s]['net']>0 and stats[s]['campaigns']>=20 and stats[s]['max_drawdown']>0 for s in ('TOPIX','NK225'))
        rows.append(dict(id=identifier, eligible=eligible,
            score=min(stats[s]['net']/stats[s]['max_drawdown'] for s in ('TOPIX','NK225')) if eligible else None,
            tie_score=min(stats[s]['worst_session']/stats[s]['max_drawdown'] for s in ('TOPIX','NK225')) if eligible else None))
    candidates = sorted([r for r in rows if r['eligible']], key=lambda r:(-r['score'],-r['tie_score'],r['id']))
    return (candidates[0]['id'] if candidates else None), rows
