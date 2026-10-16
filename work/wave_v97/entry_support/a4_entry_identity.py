"""A4四出口の見かけの四例を、共通する実新規と相違する返済へ分ける。"""

from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import pickle

import numpy as np

from diagnose import HERE, ROOT, WORK, SYMBOLS, sha


def main() -> None:
    """
    機能: 既存A4台帳だけから、新規の完全同一性と返済条件の差を確認する。
    引数: なし。
    返り値: Noneは入口例数の確認JSON。損益による設定選びや新規再生は行わない。
    """
    ids = [f'A4_X{i}' for i in range(4)]
    paths, all_orders = [], {}
    for ident in ids:
        merged = {}
        for part in ('front','back'):
            path = WORK / part / 'ledgers' / (ident+'.pkl')
            with path.open('rb') as stream:
                merged.update(pickle.load(stream))
            paths.append(path)
        all_orders[ident] = {key:np.asarray(value['orders']) for key,value in merged.items()}
    results = {}
    for symbol in SYMBOLS:
        base = {key:orders[orders[:,7]==1] for key,orders in all_orders['A4_X3'].items() if key[1]==symbol}
        examples = []
        for key,orders in base.items():
            for entry in orders:
                examples.append(dict(場=key[0], 判断原行=int(entry[1]), 約定原行=int(entry[0]),
                    判断時計=datetime.fromtimestamp(entry[10],timezone(timedelta(hours=9))).isoformat(),
                    約定時計=datetime.fromtimestamp(entry[11],timezone(timedelta(hours=9))).isoformat(),
                    売買方向=int(entry[4]), 数量=int(entry[5]), 実新規価格=float(entry[6])))
        same = {}
        exits = {}
        for ident in ids:
            same[ident] = all(np.array_equal(orders,all_orders[ident][key][all_orders[ident][key][:,7]==1])
                for key,orders in base.items())
            exits[ident] = [dict(場=key[0], 判断原行=int(order[1]), 約定原行=int(order[0]),
                判断時計=datetime.fromtimestamp(order[10],timezone(timedelta(hours=9))).isoformat(),
                約定時計=datetime.fromtimestamp(order[11],timezone(timedelta(hours=9))).isoformat(),
                返済理由=int(order[8]), 実返済価格=float(order[6]))
                for key,orders in all_orders[ident].items() if key[1]==symbol for order in orders if order[7]==0]
        assert all(same.values())
        results[symbol] = dict(共通新規事例数=len(examples), 新規全17列完全同一=same,
            共通新規=examples, 出口ごとの返済=exits)
    paths += [Path(__file__),HERE/'diagnose.py',HERE/'全31の候補許可と現在門番及び待機不成立の独立入力診断.json']
    proof = dict(全合格=True, 結果=results,
        解釈='A4は両商品それぞれ同じ一つの新規事例を四出口で決済した比較。四つの独立した入口成功例ではなく、同一経済でもない。活動充足や汎用性を四倍の根拠として扱えない。',
        新売買実行=0, 条件変更=0, 損益による選定=0, API取得=0, 実注文=0,
        SHA256={str(path.relative_to(ROOT)):sha(path) for path in paths})
    path = HERE/'A4四出口の同一新規一事例と返済相違の独立照合.json'
    path.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,結果=results,解釈=proof['解釈']),ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
