"""旧在庫の赤字を同じ注文の価格要因と、独立再生の経路差に分解する。"""

import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE=Path(__file__).resolve().parent
WORK=HERE.parent.parent


def digest(path: Path) -> str:
    """機能: 診断のコード・仕様・入力のSHA256を求める。

    引数: path(Path)。返り値: SHA256(str)。
    """
    result=hashlib.sha256()
    with path.open('rb') as source:
        while block:=source.read(4*1024*1024):
            result.update(block)
    return result.hexdigest()


def save(path: Path, value: object) -> None:
    """機能: 日本語JSONを非有限値なしで保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def groups(orders: np.ndarray, midpoint: np.ndarray, value: float) -> list[dict]:
    """機能: gross両側枚数が0に戻るまでの全注文を、一つの費用後往復組にまとめる。

    引数: orders/midpoint(ndarray)、value(float)。返り値: 全flat往復組(list[dict])。
    同原本行でも注文番号順に処理し、両建てのnet0を全返済と誤認しない。
    """
    output=[]
    long_qty=short_qty=0
    start=-1
    gross=fee=mid_cash=0.
    for row in orders:
        if long_qty+short_qty==0:
            assert row[9]==1
            start=int(row[0])
            first_time=float(row[4])
            gross=fee=mid_cash=0.
        side,qty,kind=int(row[10]),int(row[11]),int(row[9])
        if kind==1:
            if side>0:
                long_qty+=qty
            else:
                short_qty+=qty
        else:
            if side<0:
                long_qty-=qty
            else:
                short_qty-=qty
        assert long_qty>=0 and short_qty>=0
        gross+=float(row[14])
        fee+=float(row[13])
        mid_cash-=side*qty*midpoint[int(row[2])]*value+row[13]
        if long_qty+short_qty==0:
            output.append(dict(first_order=start,last_order=int(row[0]),orders=int(row[0])-start+1,
                gross=gross,fees=fee,net=gross-fee,fixed_mid_net=mid_cash,
                hold_minutes=(float(row[4])-first_time)/60.))
    assert long_qty+short_qty==0
    np.testing.assert_allclose(sum(g['net'] for g in output),orders[:,14].sum()-orders[:,13].sum(),atol=1e-5)
    return output


def describe_groups(records: list[dict]) -> dict:
    """機能: 往復組の勝率・平均勝負・損失の大きさを算出する。

    引数: records(list[dict])。返り値: 分布(dict)。95%だけで採用しない。
    """
    net=np.asarray([r['net'] for r in records],float)
    win=net[net>0]
    loss=-net[net<0]
    gp=float(win.sum()); gl=float(loss.sum())
    return dict(groups=len(net),wins=len(win),losses=len(loss),flats=int((net==0).sum()),
        win_rate=len(win)/len(net) if len(net) else None,
        net=float(net.sum()),profit=gp,loss=gl,pf=gp/gl if gl else None,
        avg_win=float(win.mean()) if len(win) else None,avg_loss=float(loss.mean()) if len(loss) else None,
        payoff=float(win.mean()/loss.mean()) if len(win) and len(loss) else None,
        max_win=float(win.max()) if len(win) else 0.,max_loss=float(loss.max()) if len(loss) else 0.)


def main() -> None:
    """機能: 既存180条件×3約定モデルを再売買せず代数分解し、新しい改善仮説の根拠にする。

    引数: なし。返り値: なし(None)。新入口・新利確幅を結果から選ぶ処理はない。
    """
    fixed=dict(コードSHA256=digest(Path(__file__)),旧結果SHA256=digest(WORK/'wave_v61/inventory/集計結果.json'),
        気配SHA256=digest(WORK/'wave_v60/quotes.pkl'),時刻SHA256=digest(WORK/'wave_v60/inputs.pkl'),
        診断='既存quoteの同じ注文行をmid再評価。実約定差と手数料を代数分解し、独立mid経路との差を別記。passiveも同様。',
        主勝率='全flatまでの一連の注文。gross両側残が0になるまで同じ組。費用は全新規返済分。',
        追加観測='新規から5/30/60秒後の中値方向変化は原因記述用ラベル。新入口へ投入しない。API0。')
    fp=HERE/'R0_診断仕様固定.json'
    if fp.exists():
        assert json.loads(fp.read_text(encoding='utf8'))==fixed
    else:
        save(fp,fixed)
    original=json.loads((WORK/'wave_v61/inventory/集計結果.json').read_text(encoding='utf8'))
    quote=pickle.loads((WORK/'wave_v60/quotes.pkl').read_bytes())
    ready=pickle.loads((WORK/'wave_v60/inputs.pkl').read_bytes())
    method_map={(m['condition_id'],m['price_mode']):m for m in original['methods']}
    output=[]
    for index,method in enumerate(original['methods'],1):
        ledger=pickle.loads((WORK/'wave_v61/inventory'/method['ledger_path']).read_bytes())
        accounts=[]
        by_symbol={s:dict(records=[],delay=[],moves={5:[],30:[],60:[]}) for s in ('TOPIX','NK225')}
        for key,record in ledger.items():
            session,symbol=key
            orders=record['orders']; mids=quote[key]['mid']; times=ready[key]['time_s']
            multiplier=1000. if symbol=='TOPIX' else 10.
            tick=ready[key]['tick']
            closed=groups(orders,mids,multiplier)
            result=describe_groups(closed)
            fixed_mid=float(sum(g['fixed_mid_net'] for g in closed))
            fees=float(orders[:,13].sum())
            result.update(session=session,symbol=symbol,fees=fees,fixed_mid_net=fixed_mid,
                fill_to_mid_difference=fixed_mid-result['net'],gross=result['net']+fees)
            np.testing.assert_allclose(result['net'],next(a['net'] for a in method['accounts'] if a['session']==session and a['symbol']==symbol),atol=1e-5)
            accounts.append(result)
            by_symbol[symbol]['records'].extend(closed)
            decision,fill=orders[:,1].astype(int),orders[:,2].astype(int)
            by_symbol[symbol]['delay'].extend((times[fill]-times[decision]).tolist())
            entries=orders[(orders[:,9]==1)&(orders[:,18]==0)]
            ei=entries[:,2].astype(int)
            sides=entries[:,10]
            for horizon in (5,30,60):
                later=np.searchsorted(times,times[ei]+horizon,side='left')
                valid=later<len(times)
                changes=sides[valid]*(mids[later[valid]]-mids[ei[valid]])/tick
                by_symbol[symbol]['moves'][horizon].extend(changes.tolist())
        summary={}
        for symbol,state in by_symbol.items():
            current=describe_groups(state['records'])
            selected=[a for a in accounts if a['symbol']==symbol]
            delays=np.asarray(state['delay'])
            own_mid=float(sum(a['fixed_mid_net'] for a in selected))
            native_mid=method_map[(method['condition_id'],'mid')]['summary'][symbol]['net']
            current.update(fees=sum(a['fees'] for a in selected),gross=sum(a['gross'] for a in selected),
                active_sessions=sum(a['groups']>0 for a in selected),positive_sessions=sum(a['net']>0 for a in selected),
                same_orders_mid_net=own_mid,fill_to_mid_difference=own_mid-current['net'],
                independent_mid_net=native_mid,independent_path_difference=native_mid-own_mid,
                same_clock_fraction=float((delays==0).mean()) if len(delays) else None,
                decision_fill_median_seconds=float(np.median(delays)) if len(delays) else None,
                entry_forward_ticks={str(h):dict(count=len(values),mean=float(np.mean(values)) if values else None,
                    positive_fraction=float(np.mean(np.asarray(values)>0)) if values else None)
                    for h,values in state['moves'].items()})
            summary[symbol]=current
        output.append(dict(id=method['id'],condition_id=method['condition_id'],family=method['family'],
            price_mode=method['price_mode'],primary=method['primary'],accounts=accounts,summary=summary))
        if method['primary'] or index%108==0:
            print(index,method['id'],{s:(v['net'],v['win_rate'],v['fill_to_mid_difference'],v['independent_path_difference']) for s,v in summary.items()},flush=True)
    save(HERE/'R0_旧在庫の原因分解.json',dict(methods=output,meta=fixed,
        注意='独立midとquoteの差は価格差と後続経路差の合計。時刻同値は実際の通信遅延0の証明ではない。未来変化は記述用で売買条件に使っていない。'))
    print('既存在庫の全180条件・3モデルの原因分解を保存しました',flush=True)


if __name__=='__main__':
    main()
