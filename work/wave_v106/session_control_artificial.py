"""場内利益停止の因果順序・気配差・費用と約定悪化を実データなしで検査する。"""

from copy import deepcopy
import json
from pathlib import Path

import numpy as np

import session_control


def fixture() -> tuple[dict,dict]:
    """
    機能: 目標到達後に利益が戻る手作りの価格経路を作る。
    引数: なし。
    返り値: tuple[dict,dict]は正常気配入力と元運転の台帳。
    """
    record=dict(symbol='TOPIX',seq=np.arange(6,dtype=np.int64),time_s=np.arange(6,dtype=float),
        bid=np.array([100,100,103,102,100,99.],float),ask=np.array([101,101,104,103,101,100.],float),
        quote_valid=np.ones(6,bool),tick=1.)
    orders=np.zeros((2,17),float)
    orders[0]=[1,0,1,0,1,1,101,1,10,41,0,1,0,1,10,1,1]
    orders[1]=[5,4,1,0,-1,1,99,0,1,41,4,5,0,1,1,1,2]
    trades=np.array([[1,0,1,5,1,1,101,99,41,41,-2000,-2082,10,1,1,0]],float)
    ledger=dict(row_count=6,orders=orders,trades=trades,equity_change_rows=np.arange(6),
        equity_change_values=np.array([0,-1082,1918,918,-1082,-2082.],float))
    return record,ledger


def main() -> None:
    """
    機能: 手計算した利益停止、逆行、欠測、未来変更不変を照合する。
    引数: なし。
    返り値: None。売買判断に将来の価格を混ぜた場合は停止する。
    """
    record,ledger=fixture()
    result=session_control.simulate(record,ledger,1500,None)
    assert result['decision_row']==2 and result['fill_row']==3
    assert result['orders'][-1,6]==102 and result['trades'][-1,11]==918
    row=session_control.account('人工',record,result,1000)
    assert row['net']==918 and row['fees']==82
    changed_record,changed_ledger=deepcopy(record),deepcopy(ledger)
    changed_record['bid'][4:]=[10000,1]
    changed_record['ask'][4:]=[10001,2]
    changed_ledger['equity_change_values'][4:]=[9898918,-100082]
    future=session_control.simulate(changed_record,changed_ledger,1500,None)
    np.testing.assert_array_equal(result['orders'],future['orders'])
    np.testing.assert_array_equal(result['trades'],future['trades'])
    np.testing.assert_array_equal(result['curve'],future['curve'])
    loss=session_control.simulate(record,ledger,5000,500)
    assert loss['decision_row']==1 and loss['fill_row']==2 and loss['stop_reason']=='損失予算'
    assert loss['trades'][-1,11]==1918
    session_control.account('人工',record,loss,1000)
    unknown_record,unknown_ledger=deepcopy(record),deepcopy(ledger)
    unknown_record['quote_valid'][3]=False
    unknown_ledger['equity_change_values'][3]=1918
    unknown=session_control.simulate(unknown_record,unknown_ledger,1500,None)
    assert unknown['decision_row']==2 and unknown['fill_row']==4
    assert unknown['trades'][-1,11]==-1082
    session_control.account('人工',unknown_record,unknown,1000)
    untouched=session_control.simulate(record,ledger,10000,None)
    assert not untouched['stopped']
    np.testing.assert_array_equal(untouched['orders'],ledger['orders'])
    np.testing.assert_array_equal(untouched['trades'],ledger['trades'])
    session_control.account('人工',record,untouched,1000)
    result=dict(全合格=True,人工検査=[
        '目標判断の次正常気配で返済','利益目標到達後の不利約定を隠さない','全行現金・枚数・手数料一致',
        '判断後さらに先の価格変更で注文不変','損失枠判断後の有利約定も保存','不正気配では約定せず次正常行を待つ',
        '未到達は元と同じ運転'],正式金融再生=0)
    session_control.research.write(Path(__file__).parent/'場内利益停止の人工検査.json',result)
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
