"""後15の正式損益を読まず前16場の参考代表選定を注文会計から独立再現する。"""

import math
from pathlib import Path

import numpy as np

import common
import full


def summarize(ledgers, sessions, symbol):
    """
    機能: 全親の新規返済注文から旧前16の選定指標だけを計算する。
    引数: ledgers (dict)、sessions (list[str])、symbol (str)。
    返り値: dict。追加場又は将来期間の損益は参照しない。
    """
    unit,fee = (1000.,41.8) if symbol=='TOPIX' else (10.,11.)
    values=[]; nets=[]; active=0;rows=[]
    for session in sessions:
        orders = np.asarray(ledgers[session,symbol]['orders'],float).reshape(-1,17)
        entries={}; local=[]
        for order in orders:
            parent,source,side,quantity = map(int,(order[2],order[3],order[4],order[5]))
            assert quantity==order[5] and order[9]==math.floor(quantity*fee+1e-8)
            key=source,parent
            if order[7]:
                assert key not in entries
                entries[key]=order
            else:
                entry=entries.pop(key)
                assert side==-entry[4] and quantity==entry[5]
                local.append(entry[4]*(order[6]-entry[6])*quantity*unit-entry[9]-order[9])
        assert not entries
        values.extend(local); nets.append(sum(local)); active+=bool(local)
        rows.append(dict(session=session,symbol=symbol,net=sum(local),campaigns=len(local),equity_drawdown=0.))
    values=np.asarray(values,float)
    profit=float(values[values>1e-5].sum()); loss=float(-values[values < -1e-5].sum())
    wins=int((values>1e-5).sum()); losses=int((values < -1e-5).sum())
    payoff=profit/wins/(loss/losses) if wins and losses else None
    days={}
    for row in rows:days[row['session'][:10]]=days.get(row['session'][:10],0.)+row['net']
    best=max(days,key=lambda day:days[day])
    return dict(net=profit-loss,campaigns=len(values),active_sessions=active,
                profit_share=profit/(profit+loss) if profit+loss else None,
                positive_session_rate=sum(value>1e-5 for value in nets)/active if active else None,
                payoff=payoff,without_best_day_net=sum(row['net'] for row in rows if row['session'][:10]!=best),
                session_rows=rows)


def score(item):
    """
    機能: 活動場の下方偏差・黒字率・最大赤字・下位25%・金額利益割合を再現する。
    引数: item (dict)。
    返り値: tuple。
    """
    rows=[item['前16'][name] for name in common.SYMBOLS]
    shares=[row['profit_share'] if row['profit_share'] is not None else -1 for row in rows]
    stable=[item['stability'][name] for name in common.SYMBOLS]
    rates=[row['positive_session_rate'] if row['positive_session_rate'] is not None else -1 for row in stable]
    rms=[row['downside_rms_units'] if row['downside_rms_units'] is not None else 1e300 for row in stable]
    lower=[row['active_net_q25_units'] if row['active_net_q25_units'] is not None else -1e300 for row in stable]
    return (max(rms),-min(rates),max(row['worst_session_loss_units'] for row in stable),
            -min(lower),-min(shares),item['id'])


def main():
    """
    機能: 旧前16の選定を独立再現し追加場を未参照のまま証明する。
    引数: なし。
    返り値: None。
    """
    fixed=full.read(common.WORK/'事前固定.json')
    selected=full.read(common.WORK/'前16参考代表.json')
    assert selected['後15正式損益前選定'] and selected['全31既知'] and selected['固定SHA256']==common.sha(common.WORK/'事前固定.json')
    data=common.module('前16選定だけの不変入力94',common.WORK/'data_r1.py')
    material=data.load_inputs()
    items=[]; fingerprints={}
    for config in fixed['条件']:
        path=common.WORK/'front/ledgers'/f'{config["id"]}.pkl'
        result_path=common.WORK/'front/results'/f'{config["id"]}.json'
        ledger=full.read(path); result=full.read(result_path)
        assert common.sha(path)==result['ledger_SHA256']
        summary={symbol:summarize(ledger,fixed['前16'],symbol) for symbol in common.SYMBOLS}
        for symbol,row in summary.items():
            observed=result['periods']['前16'][symbol]
            columns={name:value for name,value in row.items() if name not in ('without_best_day_net','session_rows')}
            common.same(columns,{name:observed[name] for name in columns})
            common.same(row['without_best_day_net'],observed['without_best_day']['net'])
        rows=[row for value in summary.values() for row in value['session_rows']]
        stable=full.stability(rows,config,material['prices'],fixed['前16'])
        for symbol,value in stable.items():
            fields={key:field for key,field in value.items() if key!='worst_intraday_drawdown_units'}
            common.same(fields,{key:result['stability'][symbol][key] for key in fields})
        items.append(dict(id=config['id'],前16=summary,stability=stable))
        fingerprints.update(common.fingerprint([path,result_path]))
    active=[item for item in items if all(row['campaigns']>=20 and row['active_sessions']>=8 for row in item['前16'].values())]
    positive=[item for item in active if all(row['net']>0 for row in item['前16'].values())]
    good=[item for item in positive if all(row['payoff'] is not None and row['payoff']>1 for row in item['前16'].values())]
    robust=[item for item in good if all(row['without_best_day_net']>0 for row in item['前16'].values())]
    target=[item for item in robust if all(row['profit_share']>=.8 for row in item['前16'].values())]
    pool=target or robust or good or positive or active or items
    chosen=min(pool,key=score)['id']
    level=0 if target else 1 if robust else 2 if good else 3 if positive else 4 if active else 5
    assert chosen==selected['selected'] and level==selected['level']
    common.same([item['id'] for item in pool],selected['eligible'])
    common.same({item['id']:list(score(item)) for item in pool},selected['scores'])
    common.save('後15正式損益未参照の前16参考代表の注文会計による独立再選定.json',
                dict(全合格=True,参考代表=chosen,段階=level,旧前16注文会計=items,
                     全31既知=True,選定に後15正式損益使用=0,当段階後15損益閲覧=0,凍結変更=0,
                     SHA256=dict(common.fingerprint([Path(__file__),common.WORK/'事前固定.json',common.WORK/'前16参考代表.json']),**fingerprints)))
    print(f'旧前16の独立注文会計で参考代表 {chosen} に一致。追加場未参照。',flush=True)


if __name__=='__main__':
    main()
