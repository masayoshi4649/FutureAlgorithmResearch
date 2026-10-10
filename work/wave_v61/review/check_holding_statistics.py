"""全玉又は全組の保有時間統計が、場別中央値の平均になっていないかを照合する。"""

import json
import pickle
from pathlib import Path

import numpy as np

HERE=Path(__file__).resolve().parent


def main() -> None:
    """機能: 全810モデルの週・全体保有中央値を返済原簿から再集計する。

    引数: なし。返り値: なし(None)。売買を再実行せず台帳のみ読む。
    """
    count=0
    for branch in ('directional','inventory'):
        source=HERE.parent/branch
        result=json.loads((source/'集計結果.json').read_text(encoding='utf-8'))
        for method in result['methods']:
            ledger=pickle.loads((source/method.get('ledger',method.get('ledger_path'))).read_bytes())
            values={}
            for key,raw in ledger.items():
                trades=raw['trades']
                if branch=='directional':
                    holds=[]
                    for gid in np.unique(trades[:,21]):
                        rows=trades[trades[:,21]==gid];holds.append((rows[0,1]-rows[0,22])/60)
                    mode=key[2]
                else:
                    holds=trades[:,22].tolist();mode=method['price_mode']
                values[(key[0],key[1],mode)]=holds
            for symbol in ('TOPIX','NK225'):
                modes=[('quote','summary','weeks'),('mid','mid_summary','mid_weeks')] if branch=='directional' else [(method['price_mode'],'summary','weeks')]
                for mode,sk,wk in modes:
                    chosen=[a for a in method['accounts'] if a['symbol']==symbol and a['price_mode']==mode]
                    periods=[(method[sk][symbol],chosen)]+[(summary,[a for a in chosen if a['week']==week]) for week,summary in method[wk][symbol].items()]
                    for summary,accounts in periods:
                        hold=[v for a in accounts for v in values[(a['session'],symbol,mode)]]
                        median=float(np.median(hold)) if hold else None
                        mean=float(np.mean(hold)) if hold else None
                        for field,expected in [('hold_median_minutes',median),('hold_mean_minutes',mean)]:
                            if expected is None:assert summary[field] is None
                            else:assert abs(summary[field]-expected)<1e-8,(method['id'],symbol,field)
                        count+=1
    result=dict(合格=True,週全体集計数=count,全玉又は全組の実値から中央値計算=True,場中央値平均ではない=True)
    (HERE/'保有時間集計の独立監査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
