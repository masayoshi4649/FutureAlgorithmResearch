"""保存診断の分母と清算費用分解を、市場未使用の小算数で確認する。"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('取引更新診断の独立小算数',HERE/'analyze.py')
analyze=importlib.util.module_from_spec(spec);spec.loader.exec_module(analyze)


def rows(values: list[float], active: bool=True) -> list[dict]:
    """
    機能: 33場の利益/損失を持つ人工小会計を生成する。
    引数: values(list[float])は収支、active(bool)は実取引の有無。
    返り値: list[dict]は診断の最小行schema。市場値や金融結果は使わない。
    """
    result=[]
    for i,value in enumerate(values):
        stat=dict(profit=max(0.,value),loss=max(0.,-value),net=value,gross=value,fees=0.,campaigns=int(active),winning_lots=int(value>0),losing_lots=int(value<0))
        empty={k:0 for k in stat}
        result.append(dict(session=f'人工{i}',symbol='TOPIX',**stat,directions={'買い':dict(stat),'売り':dict(empty)},sources={'J2':dict(stat),'O06':dict(empty)}))
    return result


def main() -> None:
    """
    機能: 大勝ち除外・活動中央値・無取引・中値とBBO及び費用の分離を独立期待値で照合する。
    引数: なし。
    返り値: None。結果前に固定した診断sourceを変えず、人工証跡だけ保存する。
    """
    value=analyze.metrics(rows([1000.]+[-10.]*32),'TOPIX')
    assert value['net']==680. and value['without_top3_net']==-320. and value['median_active_net']==-10.
    assert value['positive_active_rate']==1/33 and value['profit_share']==1000/1320
    empty=analyze.metrics(rows([0.]*33,False),'TOPIX')
    assert empty['profit_share'] is None and empty['positive_active_rate'] is None and empty['no_trade_sessions']==33
    assert empty['median_active_net'] is None
    active_zero=analyze.metrics(rows([0.]*33,True),'TOPIX')
    assert active_zero['positive_active_rate']==0 and active_zero['positive_sessions']==0
    record=dict(symbol='TOPIX',seq=np.arange(4,dtype=np.int64),time_s=np.arange(4,dtype=float),quote_valid=np.ones(4,bool),
        bid=np.array([99.5,99.5,102.,101.5]),ask=np.array([100.,100.,102.5,102.]),tick=.5)
    trade=np.array([1,1,1,3,1,5,100.,101.5,209.,209.,7500.,7082.,12,10,1,0],dtype=float)
    order=np.zeros(17);order[0]=3;order[1]=2;order[2]=1;order[7]=0
    ledger=dict(orders=np.array([order]),entry_filter=np.ones(4,bool))
    detail=analyze.describe(record,ledger,trade,None)
    assert detail['midpoint_gross']==10000. and detail['BBO_cost_relative_to_mid']==2500. and detail['fees']==418.
    assert detail['best_liquidation_net']==9582. and detail['profit_given_back']==2500. and detail['positive_liquidation_seen']
    assert detail['decision']['raw_seq']==0 and detail['entry']['raw_seq']==1 and detail['exit']['raw_seq']==3
    target=HERE/'診断の分母と価格費用分離の人工検査.json'
    analyze.write(target.name,dict(全合格=True,検査数=4,検査=['活動1/33と大勝ち除外赤字','無取引を勝ちに含めない','活動0円も黒字でない','中値/BBO費用/手数料/利益返しの独立算数'],
        source_SHA256={str((HERE/'analyze.py').relative_to(analyze.ROOT)).replace('\\','/'):analyze.digest(HERE/'analyze.py')},
        金融結果読取=0,市場データ読取=0,新金融再生=0,API取得=0))
    print(json.dumps(dict(全合格=True,純算数検査=4),ensure_ascii=False))


if __name__=='__main__':main()
