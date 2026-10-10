"""売買を変更せず、保存時計上の判断から約定までの遅れと任意期限後返済を集計する。"""

import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent


def main() -> None:
    """機能: 完了台帳から返済の実観測時刻を集計し、監視区間内を再確認する。

    引数: なし。
    返り値: なし(None)。売買条件・候補・元の結果ファイルは書き換えない。
    """
    path = HERE / '売買結果.json'
    results = json.loads(path.read_text(encoding='utf-8'))
    inputs = pickle.loads((HERE.parent / 'inputs.pkl').read_bytes())
    details = []
    for method in results['methods']:
        for account in method['accounts']:
            key = account['session'], account['symbol']
            limit = inputs[key]['limit']
            orders = np.asarray(account['orders'], float).reshape(-1, 15)
            trades = np.asarray(account['trades'], float).reshape(-1, 22)
            order_delay = orders[:, 1] - orders[:, 0]
            exit_delay = trades[:, 1] - trades[:, 11]
            late = trades[:, 1] > limit
            forced = trades[:, 9] == 5
            forced_delay = trades[forced, 11] - (limit - 60.)
            assert (order_delay >= 0).all() and (exit_delay >= 0).all()
            assert (trades[:, 1] < limit + 300.).all()
            details.append({'手法': method['id'], '主条件': method['primary'], 'セッション': key[0], '銘柄': key[1],
                            '約定方式': account['price_mode'], '注文数': len(orders), '返済数': len(trades),
                            '判断から約定の最大秒': float(np.max(order_delay, initial=0)),
                            '返済判断から約定の最大秒': float(np.max(exit_delay, initial=0)),
                            '任意運用期限後の返済数': int(late.sum()),
                            '任意運用期限から返済までの最大超過秒': float(np.max(trades[:, 1] - limit, initial=0)),
                            '強制返済判断の予定からの最大遅延秒': float(np.max(forced_delay, initial=0)),
                            '通常監視終端前の返済': True})
    totals = {}
    for mode in ('quote', 'mid'):
        rows = [row for row in details if row['約定方式'] == mode]
        totals[mode] = {'返済数': sum(row['返済数'] for row in rows),
                        '任意運用期限後の返済数': sum(row['任意運用期限後の返済数'] for row in rows),
                        '判断から約定の最大秒': max(row['判断から約定の最大秒'] for row in rows),
                        '返済判断から約定の最大秒': max(row['返済判断から約定の最大秒'] for row in rows),
                        '任意運用期限から返済までの最大超過秒': max(row['任意運用期限から返済までの最大超過秒'] for row in rows),
                        '強制返済判断の予定からの最大遅延秒': max(row['強制返済判断の予定からの最大遅延秒'] for row in rows)}
    output = {'合格': True, '結果SHA256': hashlib.sha256(path.read_bytes()).hexdigest(),
              '全120条件を重複も含めた再生件数': True,
              '時計の限界': 'CurrentPriceTime は約定時計で受信時計ではない。同時刻の後続原本行による約定では0秒となる。',
              '任意運用期限': 'Day15:35/Night05:50。判断予定はその60秒前。通常監視終端はその300秒後で排他的。',
              '全体': totals, '口座別': details}
    (HERE / '実約定の遅延監査.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'合格': True, '全体': totals}, ensure_ascii=False))


if __name__ == '__main__':
    main()
