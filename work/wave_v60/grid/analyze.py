"""固定済みグリッド成績から、費用・含み・両建てと保護の違いを記述する。"""

import json
from pathlib import Path

from backtest import save


HERE = Path(__file__).resolve().parent


def main() -> None:
    """機能: 新しいルールを選択せず、全モデルの共通成績と主5案の会計を抜粋する。

    引数: なし。返り値: なし(None)。既存売買結果だけを読み、診断JSONを保存する。
    """
    result = json.loads((HERE / '売買結果.json').read_text(encoding='utf8'))
    methods = result['methods']
    counts = {}
    for mode in ('quote', 'mid', 'passive'):
        selected = [m for m in methods if m['price_mode'] == mode]
        positive = [m['id'] for m in selected if all(m['summary'][s]['net'] > 0 for s in ('TOPIX', 'NK225'))]
        counts[mode] = dict(条件数=len(selected), 両銘柄同時黒字=positive,
            各銘柄黒字数={s: sum(m['summary'][s]['net'] > 0 for m in selected) for s in ('TOPIX', 'NK225')},
            両銘柄全3週黒字=[m['id'] for m in selected if all(
                w['net'] > 0 for s in ('TOPIX', 'NK225') for w in m['weeks'][s].values())])
    primary = []
    for method in methods:
        if not method['primary']:
            continue
        row = dict(id=method['id'], summary=method['summary'], weeks=method['weeks'], diagnosis={})
        for symbol in ('TOPIX', 'NK225'):
            accounts = [a for a in method['accounts'] if a['symbol'] == symbol]
            trades = [t for a in accounts for t in a['trades']]
            by_reason = {}
            for trade in trades:
                key = result['meta']['reasons'][str(int(trade[19]))]
                stat = by_reason.setdefault(key, dict(返済玉数=0, 枚数=0, 粗損益=0., 配分費用控除後=0.))
                stat['返済玉数'] += 1
                stat['枚数'] += int(trade[4])
                stat['粗損益'] += trade[15]
                stat['配分費用控除後'] += trade[18]
            misleading = [dict(session=a['session'], 実現費用後=a['gross_pnl'] - a['fees'],
                               含み変化=a['mtm_change'], 期間純収支=a['net']) for a in accounts
                          if (a['gross_pnl'] - a['fees']) * a['net'] < 0]
            row['diagnosis'][symbol] = dict(返済理由=by_reason, 実現収支と時価収支の符号が異なる場=misleading,
                持越し玉数=sum(t[11] != t[12] for t in trades),
                持越し枚数=sum(t[4] for t in trades if t[11] != t[12]),
                カバー往復数=sum(t[2] == 1 for t in trades),
                カバー費用後損益=sum(t[18] for t in trades if t[2] == 1))
        primary.append(row)
    # ----------------------------------------
    # 同じ幅・段数・持越し・注文モデルでG0と保護枝を比較し、運用全体の差として残す。
    comparisons = []
    index = {(m['family'], m['config']['fraction'], m['config']['steps'], m['config']['carry'], m['price_mode']): m
             for m in methods}
    for method in methods:
        if method['family'] == 'G0':
            continue
        c = method['config']
        baseline = index[('G0', c['fraction'], c['steps'], c['carry'], method['price_mode'])]
        for symbol in ('TOPIX', 'NK225'):
            base, current = baseline['summary'][symbol], method['summary'][symbol]
            comparisons.append(dict(id=method['id'], baseline=baseline['id'], symbol=symbol,
                収支差=current['net'] - base['net'], 最大資産減少幅差=current['drawdown'] - base['drawdown'],
                負け玉含み合計差=current['max_losing_inventory'] - base['max_losing_inventory'],
                費用差=current['fees'] - base['fees']))
    save(HERE / '結果の診断.json', dict(注文モデル別=counts, 主条件=primary, 基準との対比=comparisons,
        注記='全25場は既知。主5案は変更しない。保護追加は建玉と後続入口も変えるため、差は運用全体の比較である。3週目は水曜Dayまでの資料末尾。'))
    save(HERE / '集計抜粋.json', dict(meta=result['meta'], sessions=result['sessions'], methods=[
        {**{k: v for k, v in m.items() if k not in ('accounts', 'week_details')},
         'accounts': [{k: v for k, v in a.items() if k not in ('orders', 'trades', 'cancellations')} for a in m['accounts']]}
        for m in methods]))
    print(json.dumps(counts, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
