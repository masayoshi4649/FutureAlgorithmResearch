"""新損失安定性の評価を人工場の円額・数量単位・無取引母数から独立検査する。"""

from pathlib import Path
import sys

import numpy as np

import common
import full


def main() -> None:
    """
    機能: 数量を揃える比較単位・無取引除外・活動損失下方偏差の人工正負を検算する。
    引数: なし。
    返り値: None、人工証跡JSON。正式セッション損益を読まない。
    """
    sys.path.insert(0,str(common.WORK))
    source=common.module('正式安定性94の人工比較',common.WORK/'research.py')
    cases=[]
    for budget in (2,10):
        config=dict(trend_budget=0,range_budget=budget)
        rows=[];prices={};prepared={}
        for symbol in common.SYMBOLS:
            multiplier=1000. if symbol=='TOPIX' else 10.;scale=1 if symbol=='TOPIX' else 2
            for index,(net,activity) in enumerate(((100,1),(-40,2),(0,0),(-20,1),(200,3))):
                session=f'人工場{index}'
                first=4000. if symbol=='TOPIX' else 68000.
                record=dict(price=np.array([first]),price_valid=np.array([True]))
                prices[session,symbol]=record;prepared[session,symbol]=dict(record=record)
                rows.append(dict(session=session,symbol=symbol,net=net*scale,
                                 campaigns=activity,equity_drawdown=abs(net)*scale*2))
        sessions=[f'人工場{index}' for index in range(5)]
        expected=full.stability(rows,config,prices,sessions)
        actual=source.stability(rows,config,prepared,sessions)
        common.same(actual,expected)
        for symbol in common.SYMBOLS:
            assert actual[symbol]['active_sessions']==4 and actual[symbol]['no_trade_sessions']==1
            assert actual[symbol]['positive_session_rate']==.5
            cases.append(dict(商品=symbol,設定片方向枚数=actual[symbol]['configured_quantity'],
                              無取引を母数へ入れない=True,下方偏差=actual[symbol]['downside_rms_units']))
    for symbol in common.SYMBOLS:
        relevant=[case for case in cases if case['商品']==symbol]
        common.same(relevant[0]['下方偏差'],relevant[1]['下方偏差'])
    unchanged=full.stability(rows,config,prices,sessions)
    added=[dict(row,campaigns=1,net=1.) if row['campaigns']==0 else row for row in rows]
    more_activity=full.stability(added,config,prices,sessions)
    for symbol in common.SYMBOLS:
        common.same(unchanged[symbol]['downside_rms_units'],more_activity[symbol]['downside_rms_units'])
        assert unchanged[symbol]['active_downside_rms_units']>more_activity[symbol]['active_downside_rms_units']
    common.save('セッション損失安定性の数量比較単位と無取引除外の独立人工検査.json',
                dict(全合格=True,人工=cases,設定枚数変更だけで共通単位の下方偏差が改善しない=True,
                     活動場を増やしただけで主RMSの同じ損失を希釈しない=True,
                     全31既知=True,新保存場損益計算=0,新保存場損益閲覧=0,
                     SHA256=common.fingerprint([Path(__file__),Path(full.__file__),common.WORK/'research.py',
                                               common.WORK/'セッション安定性の事前評価.json'])))


if __name__=='__main__':main()
