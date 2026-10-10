"""既存方向性270条件と共通入力の品質を、追加売買なしで診断する。"""

from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PRIOR = HERE.parent.parent / 'wave_v61'
COMMON = HERE.parent.parent / 'wave_v60'


def read_json(path: Path) -> dict:
    """機能: 既存JSONを読取り専用で参照する。

    引数: path(Path)。返り値: 保存内容(dict)。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def distribution(values: np.ndarray) -> dict:
    """機能: 観測値の分布を固定分位点で記述する。

    引数: values(ndarray)。返り値: 件数・分位点・平均(dict)。
    """
    if not len(values):
        return dict(件数=0)
    return dict(件数=len(values), 最小=float(np.min(values)), 中央値=float(np.median(values)),
        p95=float(np.quantile(values, .95)), p99=float(np.quantile(values, .99)),
        最大=float(np.max(values)), 平均=float(np.mean(values)))


def input_quality(inputs: dict, quotes: dict) -> dict:
    """機能: 共通気配・約定時計・原本の標本を照合し、短期時間尺度の限界を測る。

    引数: inputs/quotes(dict)。返り値: 銘柄別分布・原本標本照合(dict)。
    """
    result = {}
    samples = []
    for symbol in ('TOPIX', 'NK225'):
        gaps, spreads, same_time_changed = [], [], 0
        total_rows = 0
        top_fields = Counter()
        for key, ready in inputs.items():
            if key[1] != symbol:
                continue
            q = quotes[key]
            seq, times = ready['seq'], ready['time_s']
            assert np.all(np.diff(seq) > 0) and np.all(np.diff(times) >= 0)
            assert np.array_equal(seq, q['seq']) and np.array_equal(times, q['time_s'])
            assert np.all(q['ask'] > q['bid']) and np.all(q['mid'] == (q['ask'] + q['bid']) / 2)
            gaps.append(np.diff(times))
            spreads.append(q['ask'] - q['bid'])
            same_time_changed += int(np.sum((np.diff(times) == 0) &
                ((np.diff(q['bid']) != 0) | (np.diff(q['ask']) != 0))))
            total_rows += len(seq)
            targets = {int(s): j for j, s in enumerate(seq[:128])}
            path = ROOT / 'book' / symbol / (key[0] + '.jsonl')
            observed = 0
            with path.open('rb') as stream:
                for row_id, line in enumerate(stream):
                    if row_id > max(targets):
                        break
                    if row_id not in targets:
                        continue
                    raw = json.loads(line)
                    index = targets[row_id]
                    bid, ask = float(raw['Buy1']['Price']), float(raw['Sell1']['Price'])
                    stamp = datetime.fromisoformat(raw['CurrentPriceTime']).timestamp()
                    assert bid == q['bid'][index] and ask == q['ask'][index] and stamp == times[index]
                    buy = [raw[f'Buy{k}']['Price'] for k in range(1, 11)]
                    sell = [raw[f'Sell{k}']['Price'] for k in range(1, 11)]
                    assert all(a >= b for a, b in zip(buy, buy[1:]))
                    assert all(a <= b for a, b in zip(sell, sell[1:]))
                    assert bid < ask
                    if raw.get('BidPrice') == bid:
                        top_fields['BidPriceとBuy1一致'] += 1
                    if raw.get('BidPrice') == ask:
                        top_fields['BidPriceとSell1一致'] += 1
                    if raw.get('AskPrice') == bid:
                        top_fields['AskPriceとBuy1一致'] += 1
                    if raw.get('AskPrice') == ask:
                        top_fields['AskPriceとSell1一致'] += 1
                    assert 'Time' not in raw['Buy1'] and 'Time' not in raw['Sell1']
                    observed += 1
            assert observed == len(targets)
            samples.append(dict(場=key[0], 銘柄=symbol, 標本数=observed))
        gap, spread = np.concatenate(gaps), np.concatenate(spreads)
        multiplier, single_fee = (1000, 41.8) if symbol == 'TOPIX' else (10, 11.)
        result[symbol] = dict(有効行数=total_rows, 隣接時計差秒=distribution(gap),
            時計同値割合=float(np.mean(gap == 0)), 時計同値だが最良気配変化=same_time_changed,
            最良気配差=distribution(spread), 原本最上位項目=dict(top_fields),
            一枚即時往復の参考費用円=distribution(spread * multiplier + 2 * single_fee))
    return dict(合格=True, 銘柄別=result, 原本標本=samples,
        注記='行等重みの分布であり実時間等重みではない。CurrentPriceTime差は受信遅延ではない。参考往復費用は41.8円の端数切捨て前で、実台帳は注文ごと整数費用。')


def summarize_groups(net: np.ndarray) -> dict:
    """機能: 全玉返済組の費用後勝率と平均勝負を計算する。

    引数: net(ndarray)。返り値: 全組数・勝率・損益・PF・平均勝負(dict)。
    """
    win, loss = net[net > 0], net[net < 0]
    payoff = float(win.mean() / -loss.mean()) if len(win) and len(loss) else None
    return dict(組数=len(net), 勝組数=len(win), 負組数=len(loss), 同値組数=int(np.sum(net == 0)),
        勝率=float(np.mean(net > 0)) if len(net) else None, 純益=float(net.sum()),
        PF=float(win.sum() / -loss.sum()) if len(loss) else None, 平均勝負比=payoff,
        最大負組=float(net.min(initial=0)))


def directional(inputs: dict, quotes: dict) -> dict:
    """機能: 270条件の固定注文から価格差・費用・組勝率・主条件返済理由を再集計する。

    引数: inputs/quotes(dict)。返り値: 条件別診断(dict)。中値は同じ注文列の付替えのみ。
    """
    source = read_json(PRIOR / 'directional/集計結果.json')
    all_results, primary = [], []
    for number, method in enumerate(source['methods']):
        ledger_path = PRIOR / 'directional/ledgers' / (method['id'] + '.pkl')
        ledgers = pickle.loads(ledger_path.read_bytes())
        for symbol in ('TOPIX', 'NK225'):
            value = 1000. if symbol == 'TOPIX' else 10.
            grouped, mids, spreads, fees, delays, hold, mfe, adverse = [], [], [], [], [], [], [], []
            reasons = defaultdict(lambda: dict(組数=0, 純益=0., MFE一幅未満=0))
            for account in method['accounts']:
                if account['symbol'] != symbol or account['price_mode'] != 'quote':
                    continue
                key = (account['session'], symbol)
                ledger = ledgers[(*key, 'quote')]
                orders, trades = ledger['orders'], ledger['trades']
                q, ready = quotes[key], inputs[key]
                i = np.searchsorted(ready['seq'], orders[:, 3])
                assert np.array_equal(orders[:, 7], np.where(orders[:, 5] > 0, q['ask'][i], q['bid'][i]))
                same_mid_gross = float(np.sum(-orders[:, 5] * orders[:, 6] * q['mid'][i]) * value)
                spread = float(np.sum(orders[:, 5] * orders[:, 6] * (orders[:, 7] - q['mid'][i])) * value)
                paid = float(orders[:, 9].sum())
                assert abs(same_mid_gross - spread - paid - account['net']) < 1e-6
                mids.append(same_mid_gross)
                spreads.append(spread)
                fees.append(paid)
                delays.extend((orders[:, 1] - orders[:, 0]).tolist())
                for group_id in np.unique(trades[:, 21]):
                    t = trades[trades[:, 21] == group_id]
                    net = float(t[:, 8].sum())
                    grouped.append(net)
                    reason = str(int(t[0, 9]))
                    reasons[reason]['組数'] += 1
                    reasons[reason]['純益'] += net
                    reasons[reason]['MFE一幅未満'] += int(t[0, 15] < 1)
                    hold.append((t[0, 1] - t[0, 22]) / 60)
                    mfe.append(t[0, 15])
                    adverse.append(t[0, 16])
            statistics = summarize_groups(np.array(grouped))
            row = dict(条件=method['id'], 系統=method['family'], 銘柄=symbol, 主条件=method['primary'],
                同注文中値粗益=sum(mids), 同注文気配価格差=sum(spreads), 注文費用=sum(fees),
                同注文中値費用後=sum(mids) - sum(fees), **statistics)
            assert abs(row['純益'] - method['summary'][symbol]['net']) < 1e-6
            all_results.append(row)
            if method['primary'] or method['id'] in ('D4_H30_W20_A1', 'D3_H120_W20_A2'):
                row = dict(row, 返済理由=dict(reasons), 判断約定時計差秒=distribution(np.array(delays)),
                    実保有分=distribution(np.array(hold)), 初回玉MFE幅=distribution(np.array(mfe)),
                    初回玉MAE幅=distribution(np.array(adverse)))
                primary.append(row)
        if (number + 1) % 90 == 0:
            print(json.dumps({'診断済条件': number + 1}, ensure_ascii=False), flush=True)
    summary = {}
    for symbol in ('TOPIX', 'NK225'):
        chosen = [row for row in all_results if row['銘柄'] == symbol]
        summary[symbol] = dict(条件数=len(chosen), 気配費用後黒字=sum(x['純益'] > 0 for x in chosen),
            気配費用前黒字=sum(x['純益'] + x['注文費用'] > 0 for x in chosen),
            同注文中値粗益黒字=sum(x['同注文中値粗益'] > 0 for x in chosen),
            同注文中値費用後黒字=sum(x['同注文中値費用後'] > 0 for x in chosen),
            全玉組勝率=distribution(np.array([x['勝率'] for x in chosen if x['勝率'] is not None])),
            目標同時達成数=sum(x['勝率'] is not None and x['勝率'] >= .95 and x['純益'] > 0 and
                x['平均勝負比'] is not None and x['平均勝負比'] > 1 for x in chosen))
    return dict(合格=True, 集約=summary, 主条件と旧候補=primary, 全条件=all_results,
        返済理由定義={'1':'初回建値の損切り','2':'順行後の追跡返済','3':'初回からの保有期限','4':'場内返済','5':'日内損失予算'},
        注記='条件同士は同じデータを使うため独立標本ではない。同注文中値は出口再判断を伴わない会計上の分解であり、新戦略や実約定可能な収益ではない。')


def main() -> None:
    """機能: 元資料・既存台帳だけで根本的な損失要因を記録する。

    引数: なし。返り値: なし(None)。API・新たな売買再生は実施しない。
    """
    inputs = pickle.loads((COMMON / 'inputs.pkl').read_bytes())
    quotes = pickle.loads((COMMON / 'quotes.pkl').read_bytes())
    for name, result in [('共通入力と原本標本の再確認.json', input_quality(inputs, quotes)),
                         ('既存方向性270条件の失敗分解.json', directional(inputs, quotes))]:
        (HERE / name).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'ファイル': name, '合格': result['合格'], '集約': result.get('集約')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
