"""同一注文の中値再評価を注文キャッシュフローとは別の返済脚式で検査する。"""

from __future__ import annotations

import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
TASK = HERE.parent


def main() -> None:
    """機能: 固定した全注文を返済脚ごとの中値差から独立再評価する。

    引数: なし。返り値: なし(None)。注文や出口判断は再計算しない。
    """
    result=json.loads((TASK/'売買結果.json').read_text(encoding='utf8'))
    source=json.loads((TASK/'成績の分解.json').read_text(encoding='utf8'))
    measured={(r['id'],r['symbol']):r for r in source['評価']}
    quotes=pickle.loads((TASK.parent/'wave_v52/measurement/quotes.pkl').read_bytes())
    count=0
    for method in result['methods']:
        totals={'TOPIX':0.,'NK225':0.}
        for account in method['accounts']:
            key=account['session'],account['symbol']
            q=quotes[key]
            value=1000. if key[1]=='TOPIX' else 10.
            net=0.
            for t in account['trades']:
                begin,end=np.searchsorted(q['seq'],[t[11],t[12]])
                assert q['seq'][begin]==t[11] and q['seq'][end]==t[12]
                net+=t[2]*t[3]*(q['mid'][end]-q['mid'][begin])*value
            expected=next(x for x in measured[method['id'],key[1]]['sensitivity'] if x['session']==key[0])
            assert np.isclose(net,expected['mid'],rtol=0,atol=1e-6)
            totals[key[1]]+=net
            count+=1
        for symbol,net in totals.items():
            assert np.isclose(net,measured[method['id'],symbol]['mid_net'],rtol=0,atol=1e-6)
    evidence=dict(合格=True,口座数=count,条件銘柄組数=len(measured),
                  方法='判断時刻・新規返済時刻・枚数を固定し、各返済脚の符号付き中値差から再計算。注文の現金増減式と一致。',
                  限界='中値で条件を再判定する別の売買再生ではない。中値で約定できることを確認する検査でもない。')
    (HERE/'中値再評価の独立検査.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf8')
    print('中値再評価合格',count,flush=True)


if __name__=='__main__':
    main()
