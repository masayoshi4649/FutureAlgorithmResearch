"""E01の15秒最悪約定差を理由・時間帯・元の損益別に分解する。"""

from collections import defaultdict
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import statistics


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = next((ROOT / 'アルゴリズム調査').glob('00046*/計算結果.json'))
REASONS = {1: '組の損切り', 2: '追跡返済', 7: '一部利確', 9: '場内返済',
           20: '追跡新規', 30: '順行後の悪化で半減'}
FACTORS = {'TOPIX': 1000, 'NK225': 10}
TICKS = {'TOPIX': 0.5, 'NK225': 10}


def summarize(rows: list[dict], symbol: str) -> dict:
    """機能: 注文群の差額を件数・枚数・保存価格の呼値で正規化する。

    引数: rows(list[dict])、symbol(str)。返り値: 集計値(dict)。
    """
    n = len(rows)
    units = sum(o['quantity'] for o in rows)
    total = sum(o['adverse_yen'] for o in rows)
    differences = [o['adverse_yen'] / o['quantity'] / FACTORS[symbol] for o in rows]
    ticks = [x / TICKS[symbol] for x in differences]
    sessions = defaultdict(list)
    for row in rows:
        sessions[row['session']].append(row)
    session_means = [sum(o['adverse_yen'] for o in group) / sum(o['quantity'] for o in group)
                     / FACTORS[symbol] / TICKS[symbol] for group in sessions.values()]
    return {'注文数': n, 'セッション数': len(sessions), '合計枚数': units,
            '悪化注文数': sum(o['adverse_yen'] > 0 for o in rows),
            '悪化発生率': sum(o['adverse_yen'] > 0 for o in rows) / n,
            '悪化額円': total, '注文平均悪化額円': total / n,
            '注文平均悪化幅ポイント': statistics.mean(differences),
            '注文平均悪化幅呼値': statistics.mean(ticks),
            '注文中央値悪化幅呼値': statistics.median(ticks),
            '注文最大悪化幅呼値': max(ticks),
            '枚数加重平均悪化幅ポイント': total / units / FACTORS[symbol],
            '枚数加重平均悪化幅呼値': total / units / FACTORS[symbol] / TICKS[symbol],
            '各セッション枚数加重平均の単純平均呼値': statistics.mean(session_means)}


def group_orders(rows: list[dict], symbol: str, key: str) -> dict:
    """機能: 指定の注文項目で分けて同じ物差しで集計する。

    引数: rows(list[dict])、symbol(str)、key(str)。返り値: 群別集計(dict)。
    """
    grouped = defaultdict(list)
    for row in rows:
        grouped[str(row[key])].append(row)
    return {group: summarize(orders, symbol) for group, orders in sorted(grouped.items())}


def band(dt: datetime) -> str:
    """機能: 日本時間の発注時刻を記述的な時間帯に分ける。

    引数: dt(datetime)。返り値: 時間帯名(str)。
    """
    minute = dt.hour * 60 + dt.minute
    if 525 <= minute < 690:
        return '日中08:45〜11:30'
    if 690 <= minute < 930:
        return '日中11:30〜15:30'
    if 930 <= minute < 1020:
        return '日中15:30〜終了'
    if 1020 <= minute < 1350:
        return '夜間17:00〜22:30'
    if minute >= 1350:
        return '夜間22:30〜24:00'
    if minute < 180:
        return '夜間00:00〜03:00'
    return '夜間03:00〜終了'


def trade_summary(rows: list[dict], symbol: str) -> dict:
    """機能: 同一の決済単位で元の勝ち負けと悪化負担を集計する。

    引数: rows(list[dict])、symbol(str)。返り値: 損益別集計(dict)。
    """
    units = sum(t['quantity'] for t in rows)
    return {'決済件数': len(rows), '決済枚数': units,
            '理想損益円': sum(t['ideal_pnl'] for t in rows),
            '最悪損益円': sum(t['worst_pnl'] for t in rows),
            '悪化額円': sum(t['adverse_yen'] for t in rows),
            '新規悪化額円': sum(t['entry_adverse_yen'] for t in rows),
            '返済悪化額円': sum(t['exit_adverse_yen'] for t in rows),
            '枚数加重往復悪化幅呼値': sum(t['adverse_yen'] for t in rows) / units / FACTORS[symbol] / TICKS[symbol],
            '黒字から赤字の件数': sum(t['ideal_pnl'] > 0 and t['worst_pnl'] < 0 for t in rows),
            '黒字からゼロの件数': sum(t['ideal_pnl'] > 0 and t['worst_pnl'] == 0 for t in rows)}


def main() -> None:
    """機能: 保存済み469注文を分解してJSONの証跡を出力する。

    引数: なし。返り値: なし(None)。
    """
    source_bytes = SOURCE.read_bytes()
    data = json.loads(source_bytes)
    result = {'対象': 'E01の全19セッション・469注文、判断と枚数は固定',
              '入力SHA256': hashlib.sha256(source_bytes).hexdigest(),
              '呼値の定義': '保存した先物価格の呼値。TOPIX0.5ポイント、NK22510円。実際のミニ/マイクロ板の約定試験ではない。',
              '時刻の定義': '条件成立・発注判断の日本時間。時間帯の区分は説明用で、独立検証済みの予測ルールではない。',
              '銘柄別': {}}
    all_count = 0
    for symbol in FACTORS:
        orders, trades = [], []
        for account in data['sessions']:
            if account['symbol'] != symbol:
                continue
            for order in account['orders']:
                dt = datetime.fromisoformat(order['decision_jst'])
                orders.append(dict(order, session=account['session'], symbol=symbol,
                                   区分='新規' if order['is_entry'] else '返済',
                                   理由=REASONS[order['reason']], 昼夜=account['session'].split('_')[1],
                                   時間帯=band(dt), 時=dt.strftime('%H'),
                                   売買='買い' if order['side'] == 1 else '売り',
                                   方向='ロング' if (order['side'] == 1) == order['is_entry'] else 'ショート'))
            by_order = {o['order']: o for o in account['orders']}
            for trade in account['trades']:
                entry, exit_order = by_order[trade['entry_order']], by_order[trade['exit_order']]
                quantity = trade['quantity']
                entry_diff = entry['adverse_yen'] * quantity / entry['quantity']
                exit_diff = exit_order['adverse_yen'] * quantity / exit_order['quantity']
                assert abs(entry_diff + exit_diff - (trade['ideal_pnl'] - trade['worst_pnl'])) < 1e-7
                trades.append(dict(trade, session=account['session'],
                                   adverse_yen=entry_diff + exit_diff, entry_adverse_yen=entry_diff,
                                   exit_adverse_yen=exit_diff))
        all_count += len(orders)
        ordered = sorted(orders, key=lambda o: o['adverse_yen'], reverse=True)
        n10 = math.ceil(len(orders) / 10)
        total = sum(o['adverse_yen'] for o in orders)
        campaigns = defaultdict(list)
        for trade in trades:
            campaigns[(trade['session'], trade['campaign'])].append(trade)
        campaign_rows = [{'session': session, 'campaign': campaign,
                          '理想損益円': sum(t['ideal_pnl'] for t in parts),
                          '最悪損益円': sum(t['worst_pnl'] for t in parts),
                          '悪化額円': sum(t['adverse_yen'] for t in parts),
                          '初回枚数': sum(t['quantity'] for t in parts)}
                         for (session, campaign), parts in campaigns.items()]
        assert abs(total - data['totals'][symbol]['adverse_yen']) < 1e-7
        assert abs(total - sum(t['adverse_yen'] for t in trades)) < 1e-7
        output = {'全注文': summarize(orders, symbol),
                  '区分別': group_orders(orders, symbol, '区分'),
                  '理由別': group_orders(orders, symbol, '理由'),
                  '昼夜別': group_orders(orders, symbol, '昼夜'),
                  '時間帯別': group_orders(orders, symbol, '時間帯'),
                  '時別': group_orders(orders, symbol, '時'),
                  '売買別': group_orders(orders, symbol, '売買'),
                  '方向別': group_orders(orders, symbol, '方向'),
                  'セッション別': group_orders(orders, symbol, 'session'),
                  '集中度': {'上位10注文額円': sum(o['adverse_yen'] for o in ordered[:10]),
                             '上位10注文集中率': sum(o['adverse_yen'] for o in ordered[:10]) / total,
                             '上位1割注文数': n10, '上位1割集中率': sum(o['adverse_yen'] for o in ordered[:n10]) / total,
                             '最大注文悪化額円': ordered[0]['adverse_yen'],
                             '最大注文を除いた平均悪化幅呼値': summarize(ordered[1:], symbol)['枚数加重平均悪化幅呼値']},
                  '上位10注文': ordered[:10],
                  '理想損益別決済': {'黒字': trade_summary([t for t in trades if t['ideal_pnl'] > 0], symbol),
                                    '赤字': trade_summary([t for t in trades if t['ideal_pnl'] < 0], symbol)},
                  '組別': campaign_rows}
        output['理由別最大1注文を除外'] = {}
        for reason in sorted({o['理由'] for o in orders}):
            subset = sorted([o for o in orders if o['理由'] == reason],
                            key=lambda o: o['adverse_yen'], reverse=True)
            output['理由別最大1注文を除外'][reason] = summarize(subset[1:], symbol)
        for label, predicate in [('黒字', lambda r: r['理想損益円'] > 0), ('赤字', lambda r: r['理想損益円'] < 0),
                                  ('ゼロ', lambda r: r['理想損益円'] == 0)]:
            subset = [r for r in campaign_rows if predicate(r)]
            output.setdefault('理想損益別組', {})[label] = {
                '組数': len(subset), '理想損益円': sum(r['理想損益円'] for r in subset),
                '最悪損益円': sum(r['最悪損益円'] for r in subset), '悪化額円': sum(r['悪化額円'] for r in subset),
                '黒字から赤字の組数': sum(r['理想損益円'] > 0 and r['最悪損益円'] < 0 for r in subset)}
        result['銘柄別'][symbol] = output
    result['監査'] = {'注文数': all_count, '全469注文': all_count == 469,
                    '各銘柄の注文差額と決済差額と元集計一致': True, '現在API取得数': 0}
    (HERE / '集計.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    for symbol, output in result['銘柄別'].items():
        print(symbol)
        for key in ['全注文', '理由別', '昼夜別', '時間帯別', '集中度', '理想損益別決済', '理想損益別組']:
            print(key, json.dumps(output[key], ensure_ascii=False))


if __name__ == '__main__':
    main()
