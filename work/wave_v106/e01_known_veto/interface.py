"""同じ紙上GUを影として保ち、新規公開の確認だけを実注文へ接続する。"""

import numpy as np

import common
import catalog
import daily
import engine
import policy


def execute(account: dict, config: dict, python: bool=False) -> tuple:
    """
    機能: 元紙上feedのbusy・取消・部分返済を保って新規公開maskを再運転する。
    引数: account/config(dict)、python(bool)は人工用Python実行か。
    返り値: tupleは旧E01同契約9配列。新金融実行は根の登録後だけ別runnerから行う。
    """
    symbol=account['symbol'];record=account['record'];quotes=account['quotes']
    features=account['trade_features'][str(config['window_seconds'])]
    accepted,_=policy.mask(account['feed'],len(record['price']),features,config['mode'])
    fn=engine.simulate.py_func if python else engine.simulate
    return fn(record['time_s'],record['price'],quotes['bid'],quotes['ask'],quotes['quote_valid'],
              account['feed'],account['quiet'],account['quiet_force'],record['limit'],catalog.CAP[symbol],
              record['tick'],config['offset_atr'],config['execution']=='D0',accepted)


def account_output(session: str, account: dict, config: dict, values: tuple) -> dict:
    """
    機能: 実注文から料金とUIDを独立再構成し、不変GU又は場目標P1L8へ接続する。
    引数: session(str)、account/config(dict)、values(tuple)は当時注文出力。
    返り値: dictは実注文・全行清算・紙上公開診断・実量会計。元paper再計算はしない。
    """
    symbol=account['symbol'];quotes=account['quotes']
    base=daily.reconstruct((session,symbol),values[0],values[5],quotes)
    output=base if config['exit']=='GU' else daily.apply_policy(base,quotes,dict(profit_ticks=1,loss_ticks=8))
    accepted,reasons=policy.mask(account['feed'],len(account['record']['price']),
                                 account['trade_features'][str(config['window_seconds'])],config['mode'])
    output.update(case=config,limit_events=values[8],execution_events=values[6],execution_states=values[7],
                  gate_accepted=accepted,gate_reasons=reasons,shadow_feed_SHA256=account.get('paper_SHA256'),
                  shadow_GU_orders=values[0],shadow_GU_uids=values[5],shadow_GU_summary=base['summary'])
    return output
