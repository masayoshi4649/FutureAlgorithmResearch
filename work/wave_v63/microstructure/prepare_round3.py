"""既知結果で選んだ代表条件を、当場の先に完了した影取引で校正する対照へ固定する。"""

import json
import math
from pathlib import Path


HERE=Path(__file__).resolve().parent


def main() -> None:
    """機能: 基準と校正9通りを結果前に固定する。

    引数: なし。返り値: なし(None)。校正自体は売買器で過去結果だけを使う。
    代表条件の選び方は既知全25場による事後選定で、独立検証ではない。
    """
    path=HERE/'round3'
    path.mkdir(exist_ok=True)
    target=path/'条件案.json'
    assert not target.exists()
    result=json.loads((HERE/'round2'/'集計結果.json').read_text(encoding='utf-8'))
    conditions=[]
    selected=[]
    for signal in range(6):
        available=[m for m in result['methods'] if m['config']['signal']==signal]
        def score(m: dict) -> tuple:
            """機能: 一方だけ良い条件を避け、悪い方のPFと標本数で代表を選ぶ。

            引数: m(dict)。返り値: 順位(tuple)。銘柄間の円は合算しない。
            """
            v=m['summary']
            enough=all(a['cycles']>=20 for a in v.values())
            return (not enough,-min(a['pf'] or 0. for a in v.values()),m['id'])
        base=sorted(available,key=score)[0]
        selected.append(dict(id=base['id'],summary=base['summary']))
        for window in (0,5,10,20):
            rates=(0.,) if window==0 else (.6,.8,.95)
            for rate in rates:
                c=dict(base['config'])
                c.update(id=base['id'].replace('M2_','M3_')+f'_校正{window}_{int(rate*100)}',
                    calibration=int(window>0),window=window or 20,required_wins=math.ceil(window*rate) if window else 19,
                    control_id=base['id'],treatment='当場の完了済み影取引から入口の可否を決める' if window else '校正なし対照')
                conditions.append(c)
    document=dict(理由='一律の板信号は既知範囲でも不足。同じ入口/出口の影取引を場初から独立に回し、その判断行までに終了した直近の影組の勝率で局所的に入口を止める。手法間の選択にもなる。',
        校正='影取引の資金や利益を実口座に計上しない。紙の勝率が実勝率95%を保証するとは主張しない。5/10/20組窓と60/80/95%の全対照を残し、取引0も記録する。',
        代表の選定='各6入口ごと、両銘柄20組以上を優先、悪い側PF最大、同点ID順。既知全場の事後選定。',selected=selected,conditions=conditions)
    target.write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'第3ラウンド{len(conditions)}条件を事前固定')


if __name__=='__main__':
    main()
