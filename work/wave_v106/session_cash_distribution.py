"""保存済み代表二条件の場内金額利益割合と、全期間の金額比を分けて集計する。"""

import hashlib
import json
from pathlib import Path
import statistics


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / 'アルゴリズム調査/00103_往復帯の回避と損失後再参加の統合検証/E01取引更新と損失予算の公開会計.json'


def aggregate(rows: list[dict]) -> dict:
    """
    機能: 決済一組の相殺前利益・損失を合計し、金額利益割合を返す。
    引数: rows(list[dict])は同条件・同商品のセッション会計。
    返り値: dictは利益、損失、収支、金額利益割合。無取引だけなら割合はNone。
    """
    profit = sum(r['profit'] for r in rows)
    loss = sum(r['loss'] for r in rows)
    return dict(利益=profit, 損失=loss, 収支=profit-loss,
                金額利益割合=profit/(profit+loss) if profit+loss else None)


def inspect(rows: list[dict]) -> dict:
    """
    機能: 全33場の個別割合と、無取引を除いた分布及び大勝ち除外を集計する。
    引数: rows(list[dict])は保存済み同商品33場、時間順。
    返り値: dictは場数と金額比。頻度と金額重み、場平均と親平均を混同しない。
    """
    assert len(rows) == 33
    ratios = []
    for row in rows:
        assert abs(row['profit']-row['loss']-row['net']) < 1e-6
        total = row['profit']+row['loss']
        ratios.append(dict(session=row['session'], 金額利益割合=row['profit']/total if total else None,
                           利益=row['profit'], 損失=row['loss'], 収支=row['net']))
    active = [r['金額利益割合'] for r in ratios if r['金額利益割合'] is not None]
    biggest = sorted([r for r in rows if r['net'] > 0], key=lambda r:r['net'], reverse=True)[:3]
    excluded = {r['session'] for r in biggest}
    kept = [r for r in rows if r['session'] not in excluded]
    return dict(全場数=len(rows), 活動場数=len(active), 無取引場数=len(rows)-len(active),
                場内金額比の最小=min(active), 場内金額比の最大=max(active), 場内金額比の中央値=statistics.median(active),
                百パーセント場数=sum(x == 1 for x in active), 零パーセント場数=sum(x == 0 for x in active),
                金額比八割以上の場数=sum(x >= .8 for x in active), 場ごとの値=ratios,
                全33金額比=aggregate(rows), 前16金額比=aggregate(rows[:16]), 後17金額比=aggregate(rows[16:]),
                利益上位3場除外=dict(除外場=sorted(excluded), 残場数=len(kept), **aggregate(kept)),
                定義='金額利益割合=決済一組の利益額/(利益額+損失額)。投資元本への利回りではない。全期間割合は金額加重で、場数頻度の平均ではない。')


def main() -> None:
    """
    機能: 既知33場の代表二条件だけを既存会計から再集計し、根拠を残す。
    引数: なし。保存済み公開会計の一読取だけを利用する。
    返り値: None。金融・原板・APIを再生せず、未見の有効性の証拠に数えない。
    """
    target = HERE / '代表二条件の場内金額比と全期間比.json'
    assert not target.exists()
    saved = SOURCE.read_bytes()
    data = json.loads(saved)
    results = {}
    for symbol, identifier in (('TOPIX','E01_TRADE_W60_VETO_D0_P1L8'),
                               ('NK225','E01_TRADE_W60_CONFIRM_D0_P1L8')):
        rows = [r for r in data['cases'][identifier]['rows'] if r['symbol'] == symbol]
        result = inspect(rows)
        assert abs(result['全33金額比']['金額利益割合']-data['cases'][identifier]['summary'][symbol]['profit_share']) < 1e-10
        results[symbol] = dict(条件=identifier, **result)
    # ----------------------------------------
    # 商品別に違う代表を選んだ比較であることを明記する。
    value = dict(全合格=True, 商品別=results,
                 元資料=dict(path=SOURCE.relative_to(ROOT).as_posix(), SHA256=hashlib.sha256(saved).hexdigest()),
                 新金融再生=0, 原板読取=0, API取得=0,
                 限界='同じ33既知場の商品別代表の再集計。共通条件の両商品達成でも、未知成功でもない。無取引を勝ちに含めない。')
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf8')
    for symbol, result in results.items():
        print(symbol, '全33金額比', round(100*result['全33金額比']['金額利益割合'],1),
              '上位3除外', round(100*result['利益上位3場除外']['金額利益割合'],1), flush=True)


if __name__ == '__main__':
    main()
