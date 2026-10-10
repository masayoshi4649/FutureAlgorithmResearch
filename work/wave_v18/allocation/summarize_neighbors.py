"""既存の全配分集計から近傍の成績を抽出し、選択の感度だけを説明する。"""

from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    """機能: TOPIX代表の近隣とNK初回１枚の追加幅一覧を保存する。

    引数: なし。返り値: なし (None)。再生・配分選択のやり直しは行わない。
    """
    out = Path(__file__).resolve().parent
    weekly = json.loads((out / '全配分の週合計.json').read_text(encoding='utf-8'))
    lookup = {(r['symbol'], r['initial_qty'], r['add_qty']): r for r in weekly if r['method_id'] == 'M3_逆_A03'}
    # ----------------------------------------
    # 追加数量が初回後の空き枠を超える場合、既に列挙した等価な配分を参照する。
    topix = []
    for initial, requested_add in [(6, 3), (7, 2), (7, 3), (7, 4), (8, 3)]:
        effective_add = min(requested_add, 10-initial)
        r = lookup[('TOPIX', initial, effective_add)]
        topix.append(dict(initial_qty=initial, requested_add_qty=requested_add,
                          effective_add_qty=effective_add, allocation_id=r['allocation_id'],
                          net_yen=r['net_yen'], money_ratio=r['money_ratio'], unit_payoff=r['unit_payoff'],
                          drawdown_yen=r['drawdown_yen'], positive_sessions=r['positive_sessions'],
                          eligible=r['selection']['eligible'],
                          equivalence='空き枠まで切り詰めるため同じ約定経路' if effective_add != requested_add else '列挙した配分そのもの'))
    nk = []
    for add in range(1, 20):
        r = lookup[('NK225', 1, add)]
        nk.append(dict(initial_qty=1, add_qty=add, allocation_id=r['allocation_id'], net_yen=r['net_yen'],
                       money_ratio=r['money_ratio'], unit_payoff=r['unit_payoff'], drawdown_yen=r['drawdown_yen'],
                       positive_sessions=r['positive_sessions'], eligible=r['selection']['eligible']))
    result = dict(method_id='M3_逆_A03', TOPIX近傍=topix, NK225初回１枚の全追加幅=nk,
                  TOPIX短文='初回７・追加３は週+1,029,500円、PF1.821。前後の初回枚数・追加幅でも利益は残る。初回７・追加４は空き枠３で切り詰めるため７・３と同じ。',
                  NK225短文='初回１・追加15は+191,900円/PF1.901、追加16は+203,300円/PF1.969だが、追加17では−14,300円/PF0.947。比率上位の配分でも１枚の差に敏感な参考候補。',
                  順位維持='当初固定した配分選択は変更しない。近傍確認から別の配分を後付けで選ばない。',
                  原因の構造='初期損失予算は初回枚数分のATR。追加数量が変わると合算損益から逆算する損切り価格が変わり、呼値丸め・返済時刻・再入場時刻も変わる。数量だけの比例換算にはならない。',
                  使用資料='全配分の週合計.json。新しい信号条件・出口条件・配分条件は試していない。')
    (out / '配分近傍比較.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
