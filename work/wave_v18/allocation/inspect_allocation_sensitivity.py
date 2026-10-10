"""既に比較した配分の近傍差を、元の注文履歴で確認する。"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np

import search_allocation as search


def main() -> None:
    """機能: NKの初回１枚・追加16枚と17枚の最初の価格経路差を保存する。

    引数: なし。返り値: なし (None)。選択順位・既存集計は変更しない。
    """
    out = Path(__file__).resolve().parent
    weekly = json.loads((out / '全配分の週合計.json').read_text(encoding='utf-8'))
    near = [r for r in weekly if r['method_id'] == 'M3_逆_A03' and r['symbol'] == 'NK225'
            and r['initial_qty'] == 1 and 12 <= r['add_qty'] <= 19]
    blocks = pickle.loads((out / '表示配分の生台帳.pkl').read_bytes())
    inputs = {}
    for stage in ['development', 'holdout']:
        inputs.update(pickle.loads((search.V16 / f'入力_{stage}.pkl').read_bytes()))
    states = pickle.loads((search.V17 / '主方向状態.pkl').read_bytes())
    examples = []
    for session in search.SESSIONS:
        symbol = 'NK225'
        chosen = blocks[('M3_逆_A03__NK225__I01_A16', session, symbol)]
        config = dict(chosen['config'], add_qty=17)
        direction = np.ascontiguousarray(states[(session, symbol)]['M3'] * -1, dtype=np.int8)
        other = search.engine.run(inputs[(session, symbol)], direction, config)
        left, right = chosen['orders'], other['orders']
        columns = [0, 1, 2, 3, 5, 6, 7]
        for j in range(min(len(left), len(right))):
            if not np.array_equal(left[j, columns], right[j, columns]):
                row_a, row_b = int(left[j, 0]), int(right[j, 0])
                examples.append(dict(session=session, first_changed_order=j,
                                     add_16_order=left[j], add_17_order=right[j],
                                     add_16_time_s=inputs[(session, symbol)]['time_s'][row_a],
                                     add_17_time_s=inputs[(session, symbol)]['time_s'][row_b],
                                     add_16_net_yen=chosen['stats'][0]*10,
                                     add_17_net_yen=other['stats'][0]*10))
                break
    result = dict(近傍配分=near, 注文経路の最初の差=examples,
                  説明='初期損失予算は初回１枚分のATRで固定。追加数量が変わると組全体の損益から逆算する損切り価格が変わり、呼値丸め・退出時刻・再入場時刻へ影響する。数量比例ではない。',
                  注意='追加16枚の選択は元の事前規則どおり。近傍の確認で順位を選び直していない。')
    search.save('配分感度の補足.json', result)
    print(json.dumps(dict(近傍数=len(near), 注文経路差セッション数=len(examples)), ensure_ascii=False))


if __name__ == '__main__':
    main()
