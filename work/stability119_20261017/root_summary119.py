"""完成結果を一度参照し、正式選択の要点と次の診断に必要な小集計だけを残す。"""

import hashlib
import json
import shutil
import numpy as np

import plan119 as plan


def aggregate(rows: list[dict]) -> dict:
    """
    機能: 期間ごとの場収支を簡潔に集計する。
    引数: rows(list[dict]) は同じ商品・政策の場集計。
    返り値: dict。無取引は勝ちでなく、利益額と活動率を併記する。
    """
    a = np.asarray([r['net'] for r in rows], float)
    positive = a[a > 1e-7]
    p, loss = sum(r['profit'] for r in rows), sum(r['loss'] for r in rows)
    return dict(場数=len(rows), 黒字=int(np.count_nonzero(a > 1e-7)), 赤字=int(np.count_nonzero(a < -1e-7)),
        無取引=sum(r['fills'] == 0 for r in rows), 未清算=sum(r['unclosed'] for r in rows),
        収支=float(a.sum()), 平均=float(a.mean()), 中央値=float(np.median(a)), 最悪=float(a.min()),
        黒字平均=float(positive.mean()) if len(positive) else None,
        上位三黒字除外=float(a.sum() - np.sort(positive)[-3:].sum()),
        利益=float(p), 損失=float(loss), 金額利益割合=float(p / (p + loss)) if p + loss else None,
        親数=sum(r['parents'] for r in rows), 費用=sum(r['fees'] for r in rows),
        最悪三場=[dict(session=r['session'], net=r['net'], parents=r['parents'], unclosed=r['unclosed']) for r in sorted(rows, key=lambda r: r['net'])[:3]])


def main() -> None:
    """
    機能: 選択6場で決めた候補の各期間成績を、経済条件を変えず小射影する。
    引数: なし。完成JSON一読だけを行う。
    返り値: None。原市場・cache・新金融を読まない。
    """
    path = plan.HERE / 'recovery119/戦略自動選択と全四十場の復元結果.json'
    payload = path.read_bytes()
    result = json.loads(payload)
    owned = plan.HERE / 'root_review'
    owned.mkdir(exist_ok=False)
    (owned / '完成結果の同bytes参照.json').write_bytes(payload)
    metadata = {s['id']: s for s in result['specs']}
    sources = result['runs'] + result['portfolios']
    primary = {}
    for symbol in ('TOPIX', 'NK225'):
        ranking = result['selection'][symbol]['ranking']
        auto = next((r['id'] for r in ranking if metadata[r['id']]['is_adaptive']), None)
        ids = list(dict.fromkeys([ranking[0]['id'], 'PORT'] + ([auto] if auto else [])))
        primary[symbol] = {mid: {period: aggregate([r for r in sources if r['symbol'] == symbol and r['method'] == mid and r['session'] in scenes])
            for period, scenes in result['splits'].items()} for mid in ids}
    # ----------------------------------------
    # 事後の全条件分布は診断用で、採用候補をこの順位へ入れ替えない。
    posthoc = {}
    for symbol in ('TOPIX', 'NK225'):
        candidates = []
        for mid in list(metadata) + ['PORT']:
            m = aggregate([r for r in sources if r['symbol'] == symbol and r['method'] == mid])
            candidates.append(dict(id=mid, **m))
        candidates.sort(key=lambda r: (r['未清算'] == 0 and r['収支'] > 0, r['黒字'], r['中央値'], r['収支']), reverse=True)
        posthoc[symbol] = dict(診断用上位=candidates[:5], 合計黒字条件=sum(c['収支'] > 0 for c in candidates),
            活動三十場以上黒字条件=sum(c['収支'] > 0 and c['無取引'] <= 10 for c in candidates),
            条件総数=len(candidates), 注意='全40を見た事後順位。主候補をこの順へ変更していない。')
    output = dict(全合格=True, 結果SHA256=hashlib.sha256(payload).hexdigest(), 正式選択=primary,
        診断分布=posthoc, 実入力読取=0, cache読取=0, 新金融=0, 元結果読取=1)
    plan.write(owned / '正式候補の短い成績と事後分布の区別.json', output)
    print(json.dumps(dict(結果SHA256=output['結果SHA256'], 正式候補={s: {mid: m['全40'] for mid, m in methods.items()} for s, methods in primary.items()},
        合計黒字条件={s: d['合計黒字条件'] for s, d in posthoc.items()}), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
