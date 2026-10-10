"""固定一枚の全取引・集計・最大勝ち除外・近傍選択を独立に照合する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle
import time

import numpy as np

OUT = Path(__file__).resolve().parent
SESSIONS = [f'2026-09-{d:02d}_{p}' for d in range(21,26) for p in ['Day','Night']]
MULT = {'TOPIX':1000., 'NK225':10.}
CHECKS = 0


def read(name: str) -> object:
    """機能: 日本語JSONを読む。

    引数: name (str)。返り値: 内容 (object)。
    """
    return json.loads((OUT/name).read_text(encoding='utf-8'))


def eq(a: object, b: object, label: str) -> None:
    """機能: 独立値と保存値を照合する。

    引数: a/b (object)、label (str)。返り値: なし (None)。
    """
    global CHECKS
    if a is None or b is None or isinstance(b,(str,bool)):
        assert a == b, (label,a,b)
    else:
        assert np.isclose(a,b,rtol=1e-10,atol=1e-5), (label,a,b)
    CHECKS += 1


def ratio(a: float,b: float) -> float | None:
    """機能: 正の分母で比率を求める。

    引数: a/b (float)。返り値: 比率または欠損 (float|None)。
    """
    return float(a/b) if b > 1e-8 else None


def check(actual: dict,expected: dict,label: str) -> None:
    """機能: 独立指標を保存集計へ照合する。

    引数: actual/expected (dict)、label (str)。返り値: なし (None)。
    """
    for key,value in expected.items():
        eq(actual[key],value,f'{label}:{key}')


def trade_fields(values: np.ndarray) -> dict:
    """機能: 一枚取引の利益・損失・件数を求める。

    引数: values (ndarray)。返り値: 会計指標 (dict)。
    """
    win,loss=values>1e-6,values < -1e-6
    p,l=float(values[win].sum()),float(-values[loss].sum())
    w,d,z=int(win.sum()),int(loss.sum()),int((~(win|loss)).sum())
    return dict(gross_profit_yen=p,gross_loss_yen=l,net_yen=p-l,profit_units=w,loss_units=d,
                zero_units=z,unit_balance=w-d,closed_units=len(values),money_ratio=ratio(p,l),unit_ratio=ratio(w,d),
                avg_profit_per_unit=ratio(p,w),avg_loss_per_unit=ratio(l,d),unit_payoff=ratio(p/w,l/d) if w and d else None,
                cycle_profit_yen=p,cycle_loss_yen=l,cycles=len(values),cycle_wins=w,cycle_losses=d,
                order_count=2*len(values),reversals=0,cover_profit_yen=0.,cover_loss_yen=0.)


def aggregate(rows: list[dict],values: np.ndarray) -> dict:
    """機能: 週合計・時価最大下落・最大寄与除外・時間帯別成績を求める。

    引数: rows (list[dict])、values (ndarray)。返り値: 週指標 (dict)。
    """
    out=trade_fields(values)
    out.update(net_r=sum(r['net_r'] for r in rows),session_count=len(rows),
               positive_sessions=sum(r['net_yen']>0 for r in rows),active_sessions=sum(r['cycles']>0 for r in rows),
               cycle_pf=out['money_ratio'],cycle_payoff=out['unit_payoff'])
    offsets=np.r_[0.,np.cumsum([r['net_yen'] for r in rows])[:-1]]
    highs=[offset+r['max_equity_yen'] for offset,r in zip(offsets,rows)]
    lows=[offset+r['min_equity_yen'] for offset,r in zip(offsets,rows)]
    out['drawdown_yen']=max([0.]+[max([0.]+highs[:i])-low for i,low in enumerate(lows)]+[r['drawdown_yen'] for r in rows])
    for k in ['max_long','max_short','max_gross','max_net']:
        out[k]=max(r[k] for r in rows)
    best=max(range(len(rows)),key=lambda i:rows[i]['net_yen'])
    removed=[r for i,r in enumerate(rows) if i!=best]
    p=sum(r['gross_profit_yen'] for r in removed)
    l=sum(r['gross_loss_yen'] for r in removed)
    wins=sorted([float(v) for v in values if v>0],reverse=True)
    streak,longest=0,0
    for value in values:
        streak=streak+1 if value<0 else 0
        longest=max(streak,longest)
    maximum=wins[0] if wins else 0.
    out.update(best_session=rows[best]['session'],drop_best_session_net=p-l,drop_best_session_pf=ratio(p,l),
               best_trade_yen=maximum,drop_best_trade_net=out['net_yen']-maximum,
               drop_top3_trades_net=out['net_yen']-sum(wins[:3]),worst_trade_yen=float(values.min()) if len(values) else 0.,
               longest_loss_streak=longest,first_half_net=sum(r['net_yen'] for r in rows[:5]),
               second_half_net=sum(r['net_yen'] for r in rows[5:]),
               day_net=sum(r['net_yen'] for r in rows if r['session'].endswith('Day')),
               night_net=sum(r['net_yen'] for r in rows if r['session'].endswith('Night')),
               recovery=ratio(out['net_yen'],out['drawdown_yen']))
    return out


def eligible(week: dict) -> bool:
    """機能: 固定済み資格を独立に判定する。

    引数: week (dict)。返り値: 合格か (bool)。
    """
    positives=['net_yen','drop_best_session_net','drop_best_trade_net','first_half_net','second_half_net','day_net','night_net']
    return (all(week[k]>0 for k in positives) and (week['money_ratio'] or 0)>1 and
            (week['unit_payoff'] or 0)>1 and week['positive_sessions']>=6 and
            week['active_sessions']>=8 and week['cycles']>=30)


def main() -> None:
    """機能: 全台帳と順位を独立検算し、表示候補の全行資産曲線を再構成する。

    引数: なし。返り値: なし (None)。通信・原本変更・新条件探索なし。
    """
    started=time.time()
    records,sessions,selection=read('週比較.json'),read('セッション比較.json'),read('選択結果.json')
    catalog={r['id']:r for r in read('全条件一覧.json')}
    indexed={(r['method_id'],r['session'],r['symbol']):r for r in sessions}
    raw=pickle.loads((OUT/'全取引台帳.pkl').read_bytes())
    assert len(records)==len(catalog)==904 and len(raw)==len(sessions)==904*20
    inputs={}
    for stage in ['development','holdout']:
        inputs.update(pickle.loads((OUT.parent/'wave_v16'/f'入力_{stage}.pkl').read_bytes()))
    total_trades,total_orders,full_rows=0,0,0
    pnl_arrays={}
    for key,block in raw.items():
        method,session,symbol=key
        config=catalog[method]['config']
        ready=inputs[(session,symbol)]
        tr,cy,orders=block['trades'],block['cycles'],block['orders']
        assert config['initial_qty']==config['audit_cap']==1
        assert all(config[k]==0 for k in ['add_mode','hedge_ratio','reverse_mode','split_target'])
        assert config['entry_atr']>0
        assert len(tr)==len(cy) and len(orders)==2*len(tr)
        assert np.all(tr[:,3]==1) and np.all(tr[:,8]==0)
        assert np.isin(tr[:,2],[-1,1]).all()
        en,ex=tr[:,6].astype(int),tr[:,7].astype(int)
        assert np.all(en<ex) and np.all(en[1:]>ex[:-1]), '同時保有１枚・組を跨いだ重複なし'
        assert np.all(ready['time_s'][en]>=ready['start']+1200)
        assert np.all(ready['time_s'][en]<ready['limit']-1800)
        assert np.all(ready['time_s'][en[1:]]-ready['time_s'][ex[:-1]]>=config['cooldown_min']*60-1e-8)
        assert np.all(orders[:,1]<orders[:,0]), '注文条件は約定前行以前'
        assert np.all(orders[:,4]==1)
        np.testing.assert_array_equal(orders[:,7],np.tile([1.,0.],len(tr)))
        np.testing.assert_array_equal(orders[::2,0],en)
        np.testing.assert_array_equal(orders[1::2,0],ex)
        np.testing.assert_array_equal(orders[::2,5],tr[:,4])
        np.testing.assert_array_equal(orders[1::2,5],tr[:,5])
        point=tr[:,2]*(tr[:,5]-tr[:,4])
        np.testing.assert_allclose(point,tr[:,10],rtol=1e-12,atol=1e-8)
        np.testing.assert_allclose(point,cy[:,3],rtol=1e-12,atol=1e-8)
        np.testing.assert_array_equal(en,cy[:,1]);np.testing.assert_array_equal(ex,cy[:,2])
        np.testing.assert_allclose(cy[:,4],config['stop_atr']*cy[:,5],rtol=1e-12,atol=1e-8)
        assert np.all(cy[:,6:8]<=1)
        values=point*MULT[symbol]
        pnl_arrays[key]=values
        derived=trade_fields(values)
        derived['net_r']=float(np.sum(point/cy[:,4])) if len(cy) else 0.
        check(indexed[key],derived,str(key))
        eq(block['stats'][9],0,'場末在庫ゼロ')
        eq(block['stats'][10],0,'反転なし')
        eq(block['stats'][0]*MULT[symbol],derived['net_yen'],'最後の確定損益')
        assert block['stats'][2]<=1 and block['stats'][3]<=1
        if method in selection['displayed']:
            size=len(ready['last'])
            delta=np.bincount(en,weights=tr[:,2],minlength=size)-np.bincount(ex,weights=tr[:,2],minlength=size)
            position=np.cumsum(delta)
            cash=np.bincount(en,weights=-tr[:,2]*tr[:,4],minlength=size)+np.bincount(ex,weights=tr[:,2]*tr[:,5],minlength=size)
            equity=(np.cumsum(cash)+position*ready['last'])*MULT[symbol]
            peaks=np.maximum.accumulate(np.r_[0.,equity])[1:]
            assert position[-1]==0 and np.all(abs(position)<=1)
            check(indexed[key],dict(drawdown_yen=float((peaks-equity).max(initial=0)),
                  min_equity_yen=float(equity.min(initial=0)),max_equity_yen=float(equity.max(initial=0))), '独立全行時価')
            full_rows+=size
        total_trades+=len(tr);total_orders+=len(orders)
    rebuilt={}
    for record in records:
        rebuilt[record['id']]={}
        for symbol in MULT:
            rows=[indexed[(record['id'],s,symbol)] for s in SESSIONS]
            vals=np.concatenate([pnl_arrays[(record['id'],s,symbol)] for s in SESSIONS])
            week=aggregate(rows,vals)
            check(record['weeks'][symbol],week,f'週:{record["id"]}:{symbol}')
            rebuilt[record['id']][symbol]=week
    # ----------------------------------------
    # 他変数を厳密固定した上下近傍・資格・優先順位を別実装で再選択する。
    by_id={r['id']:r for r in records}
    param_keys=list(next(iter(catalog.values()))['config'])
    param_keys.remove('audit_cap')
    results=[]
    for record in records:
        peers=set()
        for varied in ['entry_atr','stop_atr','main_trail']:
            matching=[r for r in records if r['signal_id']==record['signal_id'] and
                      all(r['config'][k]==record['config'][k] for k in param_keys if k!=varied)]
            lower=[r for r in matching if r['config'][varied]<record['config'][varied]]
            upper=[r for r in matching if r['config'][varied]>record['config'][varied]]
            if lower:peers.add(max(lower,key=lambda r:r['config'][varied])['id'])
            if upper:peers.add(min(upper,key=lambda r:r['config'][varied])['id'])
        assert set(record['neighbor']['ids'])==peers
        positive=sum(all(rebuilt[p][s]['net_yen']>0 and rebuilt[p][s]['drop_best_session_net']>0 for s in MULT) for p in peers)
        values=[min(rebuilt[p][s]['drop_best_session_pf'] or 0 for s in MULT) for p in peers]
        neighbor=dict(count=len(peers),positive_count=positive,positive_rate=positive/len(peers) if peers else 0.,
                      median_drop_pf=float(np.median(values)) if values else 0.,worst_drop_pf=min(values) if values else 0.)
        check(record['neighbor'],neighbor,'近傍')
        common=all(eligible(rebuilt[record['id']][s]) for s in MULT)
        stable=common and len(peers)>=3 and neighbor['positive_rate']>=.75
        score=min(rebuilt[record['id']][s]['drop_best_session_pf'] or 0 for s in MULT)
        changes=len(record['changes'])+int(record['signal_id']!='S00')
        check(record,dict(common_eligible=common,stable_eligible=stable,score=score,change_count=changes),'資格')
        results.append(dict(id=record['id'],common=common,stable=stable,score=score,changes=changes,median=neighbor['median_drop_pf']))
    ranked=sorted(results,key=lambda r:(-int(r['stable']),-r['median'],-r['score'],r['changes'],r['id']))
    assert selection['ranking']==[r['id'] for r in ranked]
    stable=[r for r in ranked if r['stable']]
    primary=stable[0]['id'] if stable else 'V0000'
    eq(selection['primary'],primary,'主候補')
    eq(selection['common_eligible_count'],sum(r['common'] for r in results),'両銘柄資格数')
    eq(selection['stable_eligible_count'],len(stable),'近傍込み資格数')
    eq(selection['single_point_best'],max(results,key=lambda r:r['score'])['id'],'単発最高')
    for symbol in MULT:
        qualified=[r for r in records if eligible(rebuilt[r['id']][symbol])]
        chosen=max(qualified,key=lambda r:rebuilt[r['id']][symbol]['drop_best_session_pf'])['id'] if qualified else 'V0000'
        eq(selection['by_symbol'][symbol],chosen,'銘柄別最高')
    hashes=read('探索前の固定記録.json')['ハッシュ']
    assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==value for path,value in hashes.items())
    output=dict(合格=True,条件数=len(records),全セッション数=len(raw),返済行数=total_trades,注文行数=total_orders,
                数値照合数=CHECKS,全件一枚上限=True,全件場末返済=True,全件次行以降注文=True,
                表示候補の時価再構成行数=full_rows,近傍と順位全904件一致=True,
                最大勝ちセッション='円の純収支が最大のセッションを丸ごと一つ除外',
                最大勝ち取引='固定一枚の一組を一つ除外。セッション除外とは別々の寄与度診断',
                前半後半='時間順10セッションを先頭5・後半5に分割',
                主候補=primary,入力原本不変=True,現在API取得数=0,経過秒=time.time()-started)
    (OUT/'audit.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(output,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
