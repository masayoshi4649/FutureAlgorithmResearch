"""完成保存の上下回転二場だけで、逆側の枚数超過と利益返済後の全玉を確認する。"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from io import BytesIO
import hashlib
import json
from pathlib import Path

import numpy as np


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=HERE/'diagnosis/formal_e'


def save(path: Path, value: dict) -> None:
    """
    機能: 読取境界と保存会計の診断を新規JSONへ残す。
    引数: path(Path)は未使用先、value(dict)は完成値からの説明。
    返り値: None。意思決定や金融を再実行しない。
    """
    assert not path.exists()
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def clock(session: str, seconds: float) -> str:
    """
    機能: 場基準の秒を翌日表記付き日本時間へ整える。
    引数: session(str)は場名、seconds(float)はUNIX epochの保存秒。
    返り値: strは日内時刻。Nightの日付を推測補正しない。
    """
    value=datetime.fromtimestamp(float(seconds),timezone(timedelta(hours=9)))
    base=datetime.fromisoformat(session.split('_')[0]).date()
    assert (value.date()-base).days in (0,1)
    return ('翌' if value.date()>base else '')+value.strftime('%H:%M:%S')


def inspect(orders: np.ndarray, lots: np.ndarray, quotes: dict, setting: dict, session: str) -> dict:
    """
    機能: 実約定原行ごとの全残玉を復元し、初回側を逆側が追い越した状態を区別する。
    引数: orders/lots(np.ndarray)は一政策の保存済み注文と玉、quotes(dict)は同bytes気配、setting(dict)は倍率・料、session(str)は場。
    返り値: dictは注文があった原行に限る枚数超過・解消・両側上限と金額の証跡。時間占有率や予測正答率ではない。
    """
    byrow=defaultdict(list)
    for row in orders:
        byrow[int(row[4])].append(row)
    where={int(raw):i for i,raw in enumerate(quotes['row'])}
    held={}
    cash=0.
    seed=0
    cycle_start=0.
    active=False
    over=False
    crossings=[]
    removed=[]
    full=[]
    cycles=[]
    trace=[]
    current=None
    fee=int(np.floor(setting['fee']+1e-9))
    multiple=setting['multiplier']
    for raw,group in sorted(byrow.items()):
        if not active:
            assert not held
            cycle_start=cash
            seed=0
        before_over=over
        counter_profit_exits=[]
        for order in group:
            identity,kind,side=int(order[0]),int(order[1]),int(order[2])
            if kind==2:
                oldside,entry=held.pop(identity)
                assert side==-oldside
                cash+=oldside*(order[7]-entry)*multiple-order[8]
                if seed and oldside==-seed and int(order[9])==1:
                    counter_profit_exits.append(identity)
            else:
                assert identity not in held
                if not active:
                    active=True
                    seed=side
                held[identity]=(side,float(order[7]))
                cash-=order[8]
        q=where[raw]
        equity=cash+sum(side*((quotes['bid'][q] if side==1 else quotes['ask'][q])-entry)*multiple-fee
                        for side,entry in held.values())
        long=sum(side==1 for side,entry in held.values())
        short=sum(side==-1 for side,entry in held.values())
        main=long if seed==1 else short
        cover=short if seed==1 else long
        over=main>0 and cover>main
        item=dict(raw=raw,time=clock(session,quotes['time'][q]),long=long,short=short,
                  equity=float(equity),cash=float(cash),basket_net=float(equity-cycle_start),
                  initial_side=seed,last=float(quotes['last'][q]))
        if over and not before_over:
            crossings.append(item)
        if before_over and not over and counter_profit_exits and main>0:
            removed.append(dict(**item,profitable_counter_uids=counter_profit_exits))
        if long==setting['cap'] and short==setting['cap']:
            full.append(item)
        trace.append(item)
        current=item
        if active and not held:
            cycles.append(dict(end=item,net=float(cash-cycle_start)))
            active=False
            over=False
    net=float(lots[:,13].sum()) if len(lots) else 0.
    assert not held and np.isclose(cash,net)
    worst=sorted(lots,key=lambda v:v[13])[:3]
    return dict(net=net,closed_lots=len(lots),wins=int(np.count_nonzero(lots[:,13]>0)),
        losses=int(np.count_nonzero(lots[:,13]<0)),
        profit=float(np.maximum(lots[:,13],0).sum()),loss=float(np.maximum(-lots[:,13],0).sum()),
        realized_and_all_inventory_identity=True,unclosed=0,completed_cycles=len(cycles),
        first_counter_excess=crossings[0] if crossings else None,counter_excess_episodes=len(crossings),
        counter_excess_lost_on_profit_exit=removed[:5],first_both_caps=full[0] if full else None,
        worst_lots=[dict(uid=int(v[0]),side=int(v[1]),rung=int(v[2]),
            entry=clock(session,v[5]),entry_price=float(v[6]),exit=clock(session,v[9]),
            exit_price=float(v[10]),net=float(v[13]),reason=int(v[14]),
            peak=float(v[15]),trough=float(v[16])) for v in worst],
        last=current,trace=trace)


def main() -> None:
    """
    機能: ROOT所有の完成結果と独立監査所有二場だけを読み、上下回転と保持対照を診断する。
    引数: なし。結果SHAと独立所有先はe完成根拠.jsonへ固定する。
    返り値: None。原市場・元measurement・旧金融を再実行しない。
    """
    config=json.loads((HERE/'e完成根拠.json').read_text(encoding='utf-8'))
    result_path=HERE/'root_owned_e/カバーを維持する組全体追尾と全四十場.json'
    payload=result_path.read_bytes()
    assert hashlib.sha256(payload).hexdigest()==config['result_sha256']
    data=json.loads(payload)
    specs=data['specs']
    selected={s:min((r for r in data['runs'] if r['symbol']==s and r['method']=='ROTATE_S2_T1'),key=lambda r:r['net'])['session']
              for s in ('TOPIX','NK225')}
    for symbol,session in selected.items():
        assert (ROOT/config['audit_owned']/symbol/(session+'.npz')).is_file(), '監査所有コピーの保全完了前です'
    OUT.mkdir(parents=True,exist_ok=True)
    planned=dict(result_sha256=config['result_sha256'],selected=selected,
        cases=['ROTATE_S2_T1','KEEP_S2_T1','RESCUE_S2_T1'],owned_source=config['audit_owned'],
        numerical_inputs=2,original_market_reads=0,financial_replay=0,
        限界='ROTATE固定条件の各商品最低収支一場へ条件付けた原因説明。全40場の確率ではない。')
    plan=OUT/'読取計画.json'
    if plan.exists():
        assert set(p.name for p in OUT.iterdir())=={'読取計画.json'}
        assert json.loads(plan.read_text(encoding='utf-8'))==planned
    else:
        save(plan,planned)
    sys_path=HERE/'recovery_e1'
    import sys
    sys.path.insert(0,str(sys_path))
    import catalog120e1
    examples=[]
    for symbol,session in selected.items():
        reference=next(x for x in data['cache'] if x['symbol']==symbol and x['session']==session)
        path=ROOT/config['audit_owned']/symbol/(session+'.npz')
        raw=path.read_bytes()
        assert hashlib.sha256(raw).hexdigest()==reference['sha256']
        owned=OUT/(symbol+'_'+session+'.npz')
        owned.write_bytes(raw)
        with np.load(BytesIO(raw),allow_pickle=False) as source:
            quotes={name:source['quotes__'+name] for name in ('row','time','last','bid','ask')}
            orders=source['orders'];lots=source['lots']
            for identity in ('ROTATE_S2_T1','KEEP_S2_T1','RESCUE_S2_T1'):
                index=next(i for i,s in enumerate(specs) if s['id']==identity)
                description=inspect(orders[orders[:,0]==index,1:],lots[lots[:,0]==index,1:],quotes,
                    catalog120e1.settings(symbol,session),session)
                expected=next(r for r in data['runs'] if r['symbol']==symbol and r['session']==session and r['method']==identity)
                assert np.isclose(description['net'],expected['net'])
                examples.append(dict(symbol=symbol,session=session,method=identity,**description))
    save(OUT/'実保有の逆側追越と利確後の残在庫.json',dict(passed=True,examples=examples,
        result_sha256=config['result_sha256'],owned_inputs=2,original_market_reads=0,financial_replay=0))
    print(json.dumps([dict(symbol=x['symbol'],session=x['session'],method=x['method'],net=x['net'],
        first_counter_excess=x['first_counter_excess'],first_both_caps=x['first_both_caps'],
        counter_excess_episodes=x['counter_excess_episodes'],counter_excess_lost=x['counter_excess_lost_on_profit_exit'][:1])
        for x in examples],ensure_ascii=False))


if __name__=='__main__':
    main()
