"""4層比較の改善内容と、注文時刻を変えない約定基準の感度を調べる。"""

from pathlib import Path
import json
import pickle

import numpy as np

from engine import REASONS
from features import load_inputs_only
from signals import candidates


HERE = Path(__file__).resolve().parent


def save(path: Path, value: object) -> None:
    """機能: 結果をUTF-8の日本語JSONへ書く。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def main() -> None:
    """機能: 既に固定した売買を変えず、集計・判断の頻度・将来反応を確認する。

    引数: なし。返り値: なし(None)。将来反応は分析専用で入口へ戻さない。
    """
    result = json.loads((HERE/'売買結果.json').read_text(encoding='utf8'))
    quotes = pickle.loads((HERE.parent/'wave_v52/measurement/quotes.pkl').read_bytes())
    features = pickle.loads((HERE/'特徴.pkl').read_bytes())
    inputs = load_inputs_only()
    evaluation = []
    for method in result['methods']:
        for symbol in ('TOPIX','NK225'):
            accounts = [a for a in method['accounts'] if a['symbol']==symbol]
            sensitivity, reasons = [], {}
            for account in accounts:
                q = quotes[(account['session'],symbol)]
                value = 1000 if symbol=='TOPIX' else 10
                mid_net = 0.
                for order in account['orders']:
                    i = int(np.searchsorted(q['seq'],int(order[3])))
                    assert q['seq'][i] == order[3]
                    mid_net -= order[5]*order[6]*q['mid'][i]*value
                sensitivity.append(dict(session=account['session'],last=account['net'],mid=mid_net))
                for leg in account['trades']:
                    reason = REASONS[int(leg[7])]
                    if reason not in reasons:
                        reasons[reason] = dict(脚数=0,枚数=0,利益円=0.,損失円=0.,保有秒合計=0.)
                    v = reasons[reason]
                    v['脚数'] += 1
                    v['枚数'] += int(leg[3])
                    v['利益円'] += max(leg[6],0.)
                    v['損失円'] += max(-leg[6],0.)
                    v['保有秒合計'] += leg[1]-leg[0]
            legs = [leg for a in accounts for leg in a['trades']]
            summary = method['summary'][symbol]
            item = dict(id=method['id'],symbol=symbol,**summary,
                        periods={k:v['net'] for k,v in method['periods'][symbol].items()},
                        weeks={k:v['net'] for k,v in method['weeks'][symbol].items()},
                        day=sum(a['net'] for a in accounts if a['session'].endswith('Day')),
                        night=sum(a['net'] for a in accounts if a['session'].endswith('Night')),
                        median_hold_min=float(np.median([l[15] for l in legs])) if legs else None,
                        half_legs=sum(int(l[7]) in (6,7) for l in legs),
                        mid_net=sum(x['mid'] for x in sensitivity),sensitivity=sensitivity,exit_reasons=reasons)
            evaluation.append(item)
    # ----------------------------------------
    # 入口イベントの重なりを許した説明用の前方反応。独立標本や検証期間とはみなさない。
    responses = {}
    for key, frame in features.items():
        values, rows = candidates(frame)
        ready,q = inputs[key],quotes[key]
        for family,signals in values.items():
            name = (family,key[1])
            if name not in responses:
                responses[name] = []
            for row, signal in zip(rows,signals):
                if not signal[0]:
                    continue
                i = int(row.ready_index)+1
                if i >= len(q['seq']) or ready['time_s'][i] >= ready['limit']-300:
                    continue
                response = dict(session=key[0],seq=int(row.seq),direction=int(signal[0]),time=float(row.time_s))
                for horizon in (300.,900.):
                    future = ready['time_s'][i]+horizon
                    j = int(np.searchsorted(ready['time_s'],future,side='right'))-1
                    valid = future<=ready['limit'] and j>=i and future-ready['time_s'][j]<=60.
                    response[str(int(horizon/60))] = float(signal[0]*(q['mid'][j]-q['mid'][i])/row.atr5) if valid else None
                responses[name].append(response)
    forward = []
    for (family,symbol),events in responses.items():
        summary = dict(family=family,symbol=symbol,events=len(events))
        for horizon in ('5','15'):
            values = np.array([e[horizon] for e in events if e[horizon] is not None])
            summary[horizon] = dict(n=len(values),mean_atr=float(values.mean()) if len(values) else None,
                                    positive_rate=float((values>0).mean()) if len(values) else None)
        forward.append(summary)
    save(HERE/'成績の分解.json',dict(評価=evaluation,入口の将来反応=forward,
                                   感度='同一の判断・注文・枚数で約定値だけ原本中値に置換。別の売買再生ではない。追加費用ではない。',
                                   反応='全入口候補の中値による5分/15分変化。重複あり、未来は結果分析専用。'))
    for symbol in ('TOPIX','NK225'):
        selected = [x for x in evaluation if x['symbol']==symbol]
        for row in sorted(selected,key=lambda x:x['net'],reverse=True)[:8]:
            print(symbol,row['id'],'net',row['net'],'PF',round(row['pf'] or 0,3),'payoff',round(row['payoff'] or 0,3),
                  'wins',row['positive_sessions'],'no_best',row['without_best'],'period',list(row['periods'].values()),
                  'mid',row['mid_net'],'cycles',row['cycles'],flush=True)
    for symbol in ('TOPIX','NK225'):
        selected = [x for x in result['component'] if x['symbol']==symbol]
        print(symbol,'管理改善',sum(x['management_delta']>0 for x in selected),'確認改善',sum(x['confirmation_delta']>0 for x in selected),
              '併用改善',sum(x['both_delta']>0 for x in selected),flush=True)


if __name__ == '__main__':
    main()
