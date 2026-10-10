"""旧固定主条件の敗因を原本気配と実台帳で分解し、改善前の診断を残す。"""

import json
from pathlib import Path
import pickle
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent.parent
OLD = WORK / 'wave_v61/directional'
sys.path.insert(0, str(OLD))
from engine import equity_curve


def safe_ratio(top: float, bottom: float) -> float | None:
    """機能: 分母ゼロを未知として比率を計算する。

    引数: top/bottom(float)。
    返り値: 比率又はNone(float|None)。
    """
    return top / bottom if bottom else None


def first_side(path: np.ndarray, threshold: float) -> int:
    """機能: 基準幅の順行と逆行のどちらへ最初に到達したかを記録する。

    引数: path(ndarray)は実建値からの方向付き価格差、threshold(float)。
    返り値: 順行1/逆行-1/どちらも未到達0(int)。
    """
    positive, negative = np.flatnonzero(path >= threshold), np.flatnonzero(path <= -threshold)
    p = int(positive[0]) if len(positive) else len(path)
    n = int(negative[0]) if len(negative) else len(path)
    return 0 if p == n else (1 if p < n else -1)


def aggregate(records: list[dict], sessions: list[dict]) -> dict:
    """機能: 観測診断を売買組・セッションの母数を保ったまま集計する。

    引数: records/sessions(list[dict])。
    返り値: 件数・金額・比率を持つ診断辞書(dict)。
    """
    losing = [r for r in records if r['net'] < 0]
    winning = [r for r in records if r['net'] > 0]
    profit, loss = sum(r['net'] for r in winning), -sum(r['net'] for r in losing)
    kinds = {}
    for name, subset in (
        ('全組', records), ('負け組', losing),
        ('30分内の同方向再参加', [r for r in records if r['retry_same']]),
        ('負け直後30分内の同方向再参加', [r for r in records if r['retry_after_loss']]),
        ('30分内の反対方向再参加', [r for r in records if r['retry_reverse']])):
        kinds[name] = {'組数': len(subset), 'net': sum(r['net'] for r in subset),
                       '黒字率': safe_ratio(sum(r['net'] > 0 for r in subset), len(subset))}
    return {'組数': len(records), '勝組': len(winning), '負組': len(losing),
            '勝率': safe_ratio(len(winning), len(records)), 'profit': profit, 'loss': loss, 'net': profit - loss,
            '平均勝ち負け比': safe_ratio(profit / len(winning) if winning else 0., loss / len(losing) if losing else 0.),
            'PF': safe_ratio(profit, loss),
            '負け中に費用後黒字の評価が一度あった組数': sum(r['mfe_net'] > 0 for r in losing),
            '負け中に0.25W順行した組数': sum(r['mfe_w'] >= .25 for r in losing),
            '負け中に0.5W順行した組数': sum(r['mfe_w'] >= .5 for r in losing),
            '負け中に1W順行した組数': sum(r['mfe_w'] >= 1. for r in losing),
            '全組の事後順行評価からの返上額': sum(max(0., r['mfe_net'] - r['net']) for r in records),
            '同注文中値置換による差額': sum(r['mid_reprice_delta'] for r in records),
            '手数料合計': sum(r['fees'] for r in records),
            '0.25W先着': {str(v): sum(r['first_quarter'] == v for r in records) for v in (1, -1, 0)},
            '0.5W先着': {str(v): sum(r['first_half'] == v for r in records) for v in (1, -1, 0)},
            '中値変化0.25W先着': {str(v): sum(r['mid_first_quarter'] == v for r in records) for v in (1, -1, 0)},
            '中値変化0.5W先着': {str(v): sum(r['mid_first_half'] == v for r in records) for v in (1, -1, 0)},
            '新規瞬間のスプレッドだけで0.25W逆行': sum(r['entry_spread_w'] >= .25 for r in records),
            '新規スプレッド中央値W': float(np.median([r['entry_spread_w'] for r in records])) if records else None,
            '負け組MFE中央値W': float(np.median([r['mfe_w'] for r in losing])) if losing else None,
            '負け組MAE中央値W': float(np.median([r['mae_w'] for r in losing])) if losing else None,
            '勝ち組保有中央値分': float(np.median([r['hold'] for r in winning])) if winning else None,
            '負け組保有中央値分': float(np.median([r['hold'] for r in losing])) if losing else None,
            '再参加分類': kinds,
            'セッション数': len(sessions), '活動場数': sum(s['cycles'] > 0 for s in sessions),
            '黒字場数': sum(s['net'] > 0 for s in sessions),
            '一度黒字から場末赤字': sum(s['peak'] > 0 and s['net'] < 0 for s in sessions),
            '最大負場': min((s['net'] for s in sessions), default=0), 'セッション別': sessions}


def main() -> None:
    """機能: 既存の主5条件のみを原本経路と突き合わせ、事後診断を保存する。

    引数: なし。
    返り値: なし(None)。条件変更や新売買のバックテストはしない。
    """
    results = json.loads((OLD / '集計結果.json').read_text(encoding='utf-8'))
    inputs = pickle.loads((WORK / 'wave_v60/inputs.pkl').read_bytes())
    quotes = pickle.loads((WORK / 'wave_v60/quotes.pkl').read_bytes())
    report, all_records = [], []
    for method in results['methods']:
        if not method['primary']:
            continue
        ledgers = pickle.loads((OLD / method['ledger']).read_bytes())
        for symbol in ('TOPIX', 'NK225'):
            records, sessions = [], []
            value = 1000. if symbol == 'TOPIX' else 10.
            for key in sorted(inputs):
                if key[1] != symbol:
                    continue
                ready, quote = inputs[key], quotes[key]
                ledger = ledgers[(*key, 'quote')]
                orders, trades = ledger['orders'], ledger['trades']
                assert (trades[:, 23] == 1).all()
                curve, _ = equity_curve(ready, quote, orders, value, True)
                sessions.append(dict(session=key[0], net=float(curve[-1]), peak=float(max(curve.max(), 0)),
                                     trough=float(min(curve.min(), 0)), cycles=len(trades)))
                previous = None
                for trade in trades:
                    start, end = int(trade[19]), int(trade[20])
                    side, qty, width, entry = int(trade[2]), int(trade[3]), trade[10], trade[4]
                    liquidation = quote['bid'][start:end + 1] if side > 0 else quote['ask'][start:end + 1]
                    path = side * (liquidation - entry)
                    midpoint_path = side * (quote['mid'][start:end + 1] - quote['mid'][start])
                    mfe, mae = max(0., path.max()) / width, max(0., -path.min()) / width
                    np.testing.assert_allclose([mfe, mae], trade[15:17], atol=1e-8)
                    near = previous is not None and trade[0] - previous[1] <= 1800.
                    same = near and side == previous[2]
                    mid_gross = side * qty * (quote['mid'][end] - quote['mid'][start]) * value
                    row = dict(id=method['id'], symbol=symbol, session=key[0], entry_seq=int(trade[12]), exit_seq=int(trade[13]),
                               side=side, net=float(trade[8]), gross=float(trade[6]), fees=float(trade[7]),
                               mfe_w=float(mfe), mae_w=float(mae), mfe_net=float(mfe * width * qty * value - trade[7]),
                               hold=float(trade[17]), first_quarter=first_side(path, .25 * width),
                               first_half=first_side(path, .5 * width), mid_reprice_delta=float(mid_gross - trade[6]),
                               mid_first_quarter=first_side(midpoint_path, .25 * width),
                               mid_first_half=first_side(midpoint_path, .5 * width),
                               entry_spread_w=float((quote['ask'][start] - quote['bid'][start]) / width),
                               retry_same=bool(same), retry_after_loss=bool(same and previous[8] < 0),
                               retry_reverse=bool(near and not same), reason=int(trade[9]))
                    records.append(row)
                    previous = trade
            report.append(dict(id=method['id'], symbol=symbol, **aggregate(records, sessions)))
            all_records.extend(records)
    (HERE / '旧主条件の損失診断.json').write_text(json.dumps({'方法別': report,
        '注意': 'MFEは事後到達評価であって実行可能利益ではない。重複する5方式の組を独立標本として検定しない。再参加分類は観測上の関連で因果ではない。'},
        ensure_ascii=False, indent=2), encoding='utf-8')
    (HERE / '診断組明細.pkl').write_bytes(pickle.dumps(all_records, protocol=pickle.HIGHEST_PROTOCOL))
    print(json.dumps([{k: r[k] for k in ('id', 'symbol', '組数', '勝率', '負組', '負け中に0.5W順行した組数',
                       '負け組MFE中央値W', '同注文中値置換による差額', '手数料合計', '一度黒字から場末赤字')}
                      for r in report], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
