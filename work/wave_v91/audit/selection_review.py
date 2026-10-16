"""追加Dayを読まず旧前16場の参考代表選定を注文会計から独立再現する。"""

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
    values=[]; nets=[]; active=0
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
    values=np.asarray(values,float)
    profit=float(values[values>1e-5].sum()); loss=float(-values[values < -1e-5].sum())
    wins=int((values>1e-5).sum()); losses=int((values < -1e-5).sum())
    payoff=profit/wins/(loss/losses) if wins and losses else None
    return dict(net=profit-loss,campaigns=len(values),active_sessions=active,
                profit_share=profit/(profit+loss) if profit+loss else None,
                positive_session_rate=sum(value>1e-5 for value in nets)/active if active else None,
                payoff=payoff)


def score(item):
    """
    機能: 最低利益割合・最低黒字率・割合和・固定IDの昇順を再現する。
    引数: item (dict)。
    返り値: tuple。
    """
    rows=[item['前16'][name] for name in common.SYMBOLS]
    shares=[row['profit_share'] if row['profit_share'] is not None else -1 for row in rows]
    rates=[row['positive_session_rate'] if row['positive_session_rate'] is not None else -1 for row in rows]
    return -min(shares),-min(rates),-sum(shares),item['id']


def main():
    """
    機能: 旧前16の選定を独立再現し追加場を未参照のまま証明する。
    引数: なし。
    返り値: None。
    """
    fixed=full.read(common.WORK/'事前固定.json')
    selected=full.read(common.WORK/'前16参考代表.json')
    assert selected['追加Day完結損益前選定'] and selected['固定SHA256']==common.sha(common.WORK/'事前固定.json')
    items=[]; fingerprints={}
    for config in fixed['条件']:
        path=common.WORK/'ledgers'/f'{config["id"]}.pkl'
        result_path=common.WORK/'results'/f'{config["id"]}.json'
        ledger=full.read(path); result=full.read(result_path)
        assert common.sha(path)==result['ledger_SHA256']
        summary={symbol:summarize(ledger,fixed['前16'],symbol) for symbol in common.SYMBOLS}
        for symbol,row in summary.items():
            common.same(row,{name:result['periods']['前16'][symbol][name] for name in row})
        items.append(dict(id=config['id'],前16=summary))
        fingerprints.update(common.fingerprint([path,result_path]))
    active=[item for item in items if all(row['campaigns']>=20 and row['active_sessions']>=8 for row in item['前16'].values())]
    positive=[item for item in active if all(row['net']>0 for row in item['前16'].values())]
    good=[item for item in positive if all(row['payoff'] is not None and row['payoff']>1 for row in item['前16'].values())]
    pool=good or positive or active or items
    chosen=min(pool,key=score)['id']
    level=0 if good else 1 if positive else 2 if active else 3
    assert chosen==selected['selected'] and level==selected['level']
    common.same([item['id'] for item in pool],selected['eligible'])
    common.same({item['id']:list(score(item)) for item in pool},selected['scores'])
    common.save('追加場未参照の旧前16参考代表の注文会計による独立再選定.json',
                dict(全合格=True,参考代表=chosen,段階=level,旧前16注文会計=items,
                     選定に追加場又は後14損益使用=0,追加場損益閲覧=0,凍結変更=0,
                     SHA256=dict(common.fingerprint([Path(__file__),common.WORK/'事前固定.json',common.WORK/'前16参考代表.json']),**fingerprints)))
    print(f'旧前16の独立注文会計で参考代表 {chosen} に一致。追加場未参照。',flush=True)


if __name__=='__main__':
    main()
