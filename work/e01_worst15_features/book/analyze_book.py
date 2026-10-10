"""15秒最悪約定の悪化と判断時板・原本更新系列の関係を独立に調べる。"""

from collections import defaultdict
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def load() -> tuple[dict, dict]:
    """機能: 固定済み00046結果と判断時原本行入力を読み込む。

    引数: なし。返り値: 比較結果と入力辞書(tuple[dict,dict])。
    """
    spec = importlib.util.spec_from_file_location('comparison', ROOT/'work/e01_worst15/analyze.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    inputs = {}
    for name in module.INPUTS:
        inputs.update(pickle.loads((ROOT/name).read_bytes()))
    result = json.loads((module.REPORT/'計算結果.json').read_text(encoding='utf8'))
    return result, inputs


def summary(frame: pd.DataFrame) -> dict:
    """機能: 枚数による金額差を除き、注文あたり及び枚数加重の悪化呼値を集計する。

    引数: frame(DataFrame)。返り値: 件数、平均、中央値など(dict)。
    """
    q = frame.quantity
    return dict(n=len(frame), units=int(q.sum()), adverse_yen=float(frame.adverse_yen.sum()),
                bad_rate=float((frame.adverse_ticks>0).mean()), mean_ticks=float(frame.adverse_ticks.mean()),
                weighted_ticks=float((frame.adverse_ticks*q).sum()/q.sum()),
                median_ticks=float(frame.adverse_ticks.median()),
                q90_ticks=float(frame.adverse_ticks.quantile(.9)))


def main() -> None:
    """機能: 判断行だけの板を原本から抽出し、探索的な層別結果を保存する。

    引数: なし。返り値: なし(None)。原本は変更せず、通信しない。
    """
    result, inputs = load()
    rows = []
    raw_count = 0
    for account in result['sessions']:
        session, symbol = account['session'], account['symbol']
        ready = inputs[session,symbol]
        targets = {int(ready['seq'][o['decision_row']]) for o in account['orders']}
        selected = {}
        path = ROOT/'book'/symbol/(session+'.jsonl')
        with path.open('rb') as handle:
            for seq, line in enumerate(handle):
                if seq in targets:
                    selected[seq] = json.loads(line)
                    if len(selected) == len(targets):
                        break
        assert set(selected) == targets
        raw_count += len(selected)
        for order in account['orders']:
            i = order['decision_row']
            raw = selected[int(ready['seq'][i])]
            last, timestamp, tick, side = float(ready['last'][i]), float(ready['time_s'][i]), float(ready['tick']), order['side']
            assert raw['CurrentPrice'] == last
            assert datetime.fromisoformat(raw['CurrentPriceTime']).timestamp() == timestamp
            bid, ask = raw['Buy1'], raw['Sell1']
            assert 0 < bid['Price'] < ask['Price'] and min(bid['Qty'],ask['Qty']) > 0
            bq, aq = bid['Qty'], ask['Qty']
            near_bq = sum((raw.get('Buy'+str(level)) or {}).get('Qty',0) for level in range(1,11)
                          if (raw.get('Buy'+str(level)) or {}).get('Price',0) >= bid['Price']-3*tick)
            near_aq = sum((raw.get('Sell'+str(level)) or {}).get('Qty',0) for level in range(1,11)
                          if 0 < (raw.get('Sell'+str(level)) or {}).get('Price',0) <= ask['Price']+3*tick)
            before_same = int(np.searchsorted(ready['time_s'][:i+1],timestamp,side='left'))
            future_end = int(np.searchsorted(ready['time_s'],timestamp+15,side='right'))
            before15 = int(np.searchsorted(ready['time_s'][:i+1],timestamp-15,side='left'))
            wprices = ready['last'][i:future_end]
            wtimes = ready['time_s'][i:future_end]
            row = dict(session=session, symbol=symbol, **order,
                       seq=int(ready['seq'][i]), last=last, tick=tick,
                       adverse_ticks=float(side*(order['worst_price']-order['ideal_price'])/tick),
                       threshold_gap_ticks=float(side*(last-order['ideal_price'])/tick),
                       postdecision_ticks=float(side*(order['worst_price']-last)/tick),
                       spread_ticks=float((ask['Price']-bid['Price'])/tick),
                       bid_qty=bq, ask_qty=aq,
                       opposing_qty=aq if side>0 else bq,
                       near_opposing_qty=near_aq if side>0 else near_bq,
                       imbalance=float(side*(bq-aq)/(bq+aq)),
                       near_imbalance=float(side*(near_bq-near_aq)/(near_bq+near_aq)),
                       last_mid_ticks=float(side*(last-(bid['Price']+ask['Price'])/2)/tick),
                       past_same_time_rows=i-before_same,
                       last_time_step=float(timestamp-ready['time_s'][before_same-1]) if before_same else None,
                       past15_rows=i-before15+1,
                       past15_unique_times=int(len(np.unique(ready['time_s'][before15:i+1]))),
                       window_unique_prices=int(len(np.unique(wprices))),
                       window_unique_times=int(len(np.unique(wtimes))))
            rows.append(row)
    frame = pd.DataFrame(rows)
    frame['段階'] = np.where(frame.is_entry,'新規','返済')
    output = dict(原本一致注文数=raw_count, 注文数=len(frame), 層別={}, 相関={}, 上位悪化={}, 注記=[
        '板は実際のミニ・マイクロではなく保存されたラージ先物の板。厚みを発注可能数量と同一視しない。',
        '板時刻はCurrentPriceTimeで、板受信時刻を保存していない。実時間で15秒の受信遅延を測定した結果ではない。',
        '事後に多数の層別を探索した結果であり、因果や将来有効性は未確定。',
        '価格最悪値の探索対象はCurrentPriceであり、板気配で約定を再計算した結果ではない。',
        '今回調べたのは判断行の気配差・静的厚み・偏り。補充継続・取り消し・OFIなど時間変化の効果はこの分析だけでは否定できない。'])
    for symbol, subset in frame.groupby('symbol'):
        bins = {'全注文':np.repeat('全体',len(subset)),
                '段階':subset['段階'],
                '気配幅':np.where(subset.spread_ticks<=1,'1呼値以下',np.where(subset.spread_ticks<=2,'2呼値','3呼値以上')),
                '売買方向と最良板偏り':np.where(subset.imbalance<-.25,'逆方向',np.where(subset.imbalance>.25,'同方向','中立')),
                '売買方向と近傍板偏り':np.where(subset.near_imbalance<-.25,'逆方向',np.where(subset.near_imbalance>.25,'同方向','中立')),
                '注文側近傍厚み四分位':pd.qcut(subset.near_opposing_qty,4,duplicates='drop').astype(str),
                '最終価格と中値':np.where(subset.last_mid_ticks<-.5,'不利方向から離れる',np.where(subset.last_mid_ticks>.5,'不利方向へ離れる','半呼値以内')),
                '価格更新間隔':np.where(subset.last_time_step>15,'15秒超',np.where(subset.last_time_step>5,'5秒超15秒以内','5秒以内')),
                '判断以前の同価格時刻行数':np.where(subset.past_same_time_rows>100,'101行以上',np.where(subset.past_same_time_rows>10,'11～100行','10行以下')),
                '15秒窓内価格時刻種類数':np.where(subset.window_unique_times==1,'1種類',np.where(subset.window_unique_times<=3,'2～3種類','4種類以上'))}
        output['層別'][symbol]={name:{str(group):summary(part) for group,part in subset.groupby(np.asarray(labels))}
                                    for name,labels in bins.items()}
        features=['spread_ticks','near_opposing_qty','imbalance','near_imbalance','last_mid_ticks','last_time_step','past_same_time_rows','past15_rows']
        output['相関'][symbol]={name:float(subset[[name,'adverse_ticks']].corr(method='spearman').iloc[0,1]) for name in features}
        output['上位悪化'][symbol]=subset.nlargest(10,'adverse_ticks').to_dict('records')
    output['窓品質']={s:{'単一価格時刻窓数':int((g.window_unique_times==1).sum()),'単一価格窓数':int((g.window_unique_prices==1).sum()),
                              '同時刻過去100行超':int((g.past_same_time_rows>100).sum()),'15秒末尾の空白最大秒':float(g.last_observation_gap.max())}
                     for s,g in frame.groupby('symbol')}
    output['段階別相関']={s:{'新規' if entry else '返済':{'n':len(g), **{name:float(g[[name,'adverse_ticks']].corr(method='spearman').iloc[0,1]) for name in features}}
                                  for entry,g in f.groupby('is_entry')} for s,f in frame.groupby('symbol')}
    output['悪化内訳呼値']={s:{'判断行と理想価格の差':float((g.threshold_gap_ticks*g.quantity).sum()/g.quantity.sum()),
                                  '判断行から最悪値までの差':float((g.postdecision_ticks*g.quantity).sum()/g.quantity.sum())}
                              for s,g in frame.groupby('symbol')}
    assert sum(r['adverse_yen'] for r in rows if r['symbol']=='TOPIX') == 370000
    assert sum(r['adverse_yen'] for r in rows if r['symbol']=='NK225') == 161200
    assert all(abs(r['threshold_gap_ticks']+r['postdecision_ticks']-r['adverse_ticks'])<1e-8 for r in rows)
    (HERE/'板特徴注文.json').write_text(frame.to_json(orient='records',force_ascii=False,indent=2),encoding='utf8')
    (HERE/'板特徴集計.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    print(json.dumps({k:v for k,v in output.items() if k not in ('上位悪化','層別')},ensure_ascii=False,indent=2))
    print(json.dumps(output['層別'],ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
