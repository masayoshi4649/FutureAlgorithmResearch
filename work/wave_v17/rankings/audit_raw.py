"""返済時の原価格・数量から週集計と初期ATR基準の診断を独立計算する。"""
import json
import pickle
from collections import defaultdict
from pathlib import Path
import numpy as np
P=Path('work/wave_v17');O=P/'rankings';MULT={'NK225':1000.,'TOPIX':10000.}
checks=0

def ratio(a:float,b:float)->float|None:
    """機能: 分母が正なら比率を計算する。

    引数: a/b (float)。返り値: 比率または欠損 (float|None)。
    """
    return float(a/b) if b>1e-8 else None

def metrics(profits:np.ndarray,qty:np.ndarray)->dict:
    """機能: 個別返済の利益損失と数量を集計する。

    引数: profits/qty (ndarray)。返り値: 集計辞書 (dict)。
    """
    win=profits>1e-6; loss=profits< -1e-6
    gp=float(profits[win].sum());gl=float(-profits[loss].sum())
    wq=int(qty[win].sum());lq=int(qty[loss].sum());zq=int(qty[~(win|loss)].sum())
    return dict(gross_profit_yen=gp,gross_loss_yen=gl,net_yen=gp-gl,profit_units=wq,loss_units=lq,zero_units=zq,unit_balance=wq-lq,closed_units=wq+lq+zq,money_ratio=ratio(gp,gl),unit_ratio=ratio(wq,lq),avg_profit_per_unit=ratio(gp,wq),avg_loss_per_unit=ratio(gl,lq),unit_payoff=ratio(gp/wq,gl/lq) if wq and lq else None)

def compare(a:float|None,b:float|None,label:str)->None:
    """機能: 再計算値と原集計の一致を確認する。

    引数: a/b (float|None)、label (str)。返り値: なし (None)。
    """
    global checks
    if a is None or b is None:assert a is b,(label,a,b)
    else:assert np.isclose(a,b,rtol=1e-10,atol=1e-5),(label,a,b)
    checks+=1

raw=pickle.loads((P/'全返済と組.pkl').read_bytes())
sessions={(r['method_id'],r['session'],r['symbol']):r for r in json.loads((P/'セッション集計.json').read_text(encoding='utf-8'))}
weeks={(r['method_id'],r['symbol']):r for r in json.loads((P/'週合計.json').read_text(encoding='utf-8'))}
profit_parts=defaultdict(list);qty_parts=defaultdict(list);atr_parts=defaultdict(list);normalized_sessions=[]
legs=0
for key, block in raw.items():
    mid,session,symbol=key;t=block['trades'];c=block['cycles'];legs+=len(t)
    profits=t[:,2]*t[:,3]*(t[:,5]-t[:,4]);qty=t[:,3]
    np.testing.assert_allclose(profits,t[:,10],atol=1e-7,rtol=1e-12)
    assert (qty>0).all() and (qty==np.floor(qty)).all()
    value=profits*MULT[symbol]
    for field,calc in metrics(value,qty).items():compare(calc,sessions[key][field],f'{key}:{field}')
    campaign_atr={int(row[0]):row[5] for row in c}
    atr=np.array([campaign_atr[int(row[0])] for row in t])
    assert (atr>0).all()
    z=metrics(profits/atr,qty)
    normalized_sessions.append(dict(method_id=mid,session=session,symbol=symbol,atr_profit=z['gross_profit_yen'],atr_loss=z['gross_loss_yen'],atr_net=z['net_yen'],atr_pf=z['money_ratio'],atr_unit_payoff=z['unit_payoff']))
    profit_parts[mid,symbol].append(profits);qty_parts[mid,symbol].append(qty);atr_parts[mid,symbol].append(atr)
normalized=[]
for key,parts in profit_parts.items():
    profits=np.concatenate(parts);qty=np.concatenate(qty_parts[key]);atr=np.concatenate(atr_parts[key]);mid,symbol=key
    for field,calc in metrics(profits*MULT[symbol],qty).items():compare(calc,weeks[key][field],f'{key}:{field}')
    z=metrics(profits/atr,qty)
    normalized.append(dict(method_id=mid,symbol=symbol,atr_profit=z['gross_profit_yen'],atr_loss=z['gross_loss_yen'],atr_net=z['net_yen'],atr_pf=z['money_ratio'],atr_unit_payoff=z['unit_payoff'],avg_profit_atr_per_unit=z['avg_profit_per_unit'],avg_loss_atr_per_unit=z['avg_loss_per_unit']))
summary=dict(検査結果='一致',集計照合数=checks,原価格から検算した返済行数=legs,セッションセル数=len(raw),週セル数=len(weeks),初期ATR正規化の定義='各返済脚の数量×方向×(返済価格−建値)を同じ建玉一式の開始時ATRで割る。正負別の合計比をATR正規化PFとし、さらに正負別枚数で平均化した比をATR正規化１枚利益損失比とする。主順位変更には使わない。')
(O/'audit_raw_metrics.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
(O/'audit_atr_normalized.json').write_text(json.dumps(dict(定義=summary['初期ATR正規化の定義'],週=normalized,セッション=normalized_sessions),ensure_ascii=False,indent=2),encoding='utf-8')
print(summary)
for mid in ['M3_逆_A03','M3_逆_A00','M2_逆_A00','M2_逆_A01','M1_逆_A03']:
 print(mid,[(r['symbol'],round(r['atr_pf'],4),round(r['atr_unit_payoff'],4),round(r['atr_net'],4)) for r in normalized if r['method_id']==mid])
