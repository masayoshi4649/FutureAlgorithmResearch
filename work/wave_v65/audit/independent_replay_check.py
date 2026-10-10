"""新損切り・利益保護トレールの全注文を独立した配列式と予約状態で検算する。"""

from collections import Counter
from decimal import Decimal, ROUND_FLOOR
import hashlib
import importlib
import json
import math
from pathlib import Path
import pickle
import sys

import numpy as np


HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=HERE.parents[2]


def same(actual,expected):
    """機能: 全行の構造と数値を別計算値へ照合する。

    引数: actual/expected(object)。返り値: なし(None)。不一致なら例外。
    """
    if isinstance(actual,dict):
        assert actual.keys()==expected.keys(),(actual.keys(),expected.keys())
        for key in actual:
            same(actual[key],expected[key])
    elif isinstance(actual,list):
        assert len(actual)==len(expected),(len(actual),len(expected))
        for a,b in zip(actual,expected):
            same(a,b)
    elif isinstance(actual,float):
        assert math.isclose(actual,expected,rel_tol=1e-12,abs_tol=1e-8),(actual,expected)
    else:
        assert actual==expected,(actual,expected)


def vector_trace(times,bid,ask,decision,side,config,cutoff):
    """機能: 累積最高値と最初の成立行を配列式で独立算出する。

    引数: times/bid/ask(ndarray)、decision/side(int)、config(dict)、cutoff(float)。
    返り値: 判断行・約定行・開始行・保護線・最大順行・理由(tuple)。
    """
    entry=decision+1
    anchor=float(ask[entry] if side==1 else bid[entry])
    liquidation=bid[entry:] if side==1 else ask[entry:]
    gain=side*(liquidation-anchor)
    best=np.maximum.accumulate(gain)
    active=best>=anchor*config['arm']-1e-9
    line=np.where(active,np.maximum(anchor*config['floor'],best-anchor*config['trail']),-anchor*config['stop'])
    hit=(gain<=line+1e-9)|(times[entry:]>=cutoff)
    matches=np.flatnonzero(hit)
    if len(matches):
        end=int(matches[0]);decision_i=entry+end;fill_i=decision_i+1
        reason=4 if times[decision_i]>=cutoff else 2 if active[end] else 1
    else:
        end=len(gain)-1;decision_i=fill_i=-1;reason=0
    armed=np.flatnonzero(active[:end+1])
    armed_i=entry+int(armed[0]) if len(armed) else -1
    return (decision_i,fill_i,armed_i,float(line[end]),max(0.,float(best[end])),reason)


def trade(account,quote,decision,side,config):
    """機能: 次行の新規・返済気配から全会計と事後診断を独立計算する。

    引数: account/quote/config(dict)、decision/side(int)。返り値: 取引1件(dict)。
    """
    topix=account['symbol']=='TOPIX'
    qty,value,fee_rate=(10,1000.,'41.8') if topix else (20,10.,'11')
    fee=int((Decimal(fee_rate)*qty).to_integral_value(rounding=ROUND_FLOOR))
    entry=decision+1
    assert quote['time_s'][entry]<account['limit']-300
    d,x,armed,line,peak,reason=vector_trace(quote['time_s'],quote['bid'],quote['ask'],decision,side,config,account['limit']-60)
    assert x<len(quote['seq']) and x==d+1
    assert quote['time_s'][x]<account['limit']+300
    entry_price=float(quote['ask'][entry] if side==1 else quote['bid'][entry])
    exit_price=float(quote['bid'][x] if side==1 else quote['ask'][x])
    gross=(exit_price*side-entry_price*side)*qty*value
    future=quote['bid'][entry:] if side==1 else quote['ask'][entry:]
    eventual=float(future.max() if side==1 else future.min())
    target=(side*eventual-side*entry_price)>=entry_price*.001-1e-9
    return dict(session=account['session'],symbol=account['symbol'],side=side,qty=qty,value=value,
        decision_i=decision,entry_i=entry,exit_decision_i=d,exit_i=x,armed_i=armed,
        decision_seq=int(account['seq'][decision]),entry_seq=int(account['seq'][entry]),exit_decision_seq=int(account['seq'][d]),exit_seq=int(account['seq'][x]),
        decision_time=float(account['time_s'][decision]),entry_time=float(account['time_s'][entry]),exit_decision_time=float(account['time_s'][d]),exit_time=float(account['time_s'][x]),
        entry_price=entry_price,exit_price=exit_price,gross=gross,entry_fee=fee,exit_fee=fee,fees=2*fee,net=gross-2*fee,reason=reason,
        protected=armed>=0,stop_gain=line,peak_gain=peak,hold_minutes=float((account['time_s'][x]-account['time_s'][entry])/60),
        protected_target_shortfall=bool(armed>=0 and side*(exit_price-entry_price)<entry_price*config['floor']-1e-9),
        eventual_target=bool(target),stopped_then_eventual_target=bool(reason==1 and target))


def summary(rows):
    """機能: 全損益・枚数・状態件数を別集計する。

    引数: rows(list[dict])。返り値: 集計(dict)。
    """
    winning=[r for r in rows if r['net']>0];losing=[r for r in rows if r['net']<0]
    profit=math.fsum(r['net'] for r in winning);damage=-math.fsum(r['net'] for r in losing)
    avg_win=profit/len(winning) if winning else None;avg_loss=damage/len(losing) if losing else None
    return dict(trades=len(rows),wins=len(winning),losses=len(losing),flats=sum(r['net']==0 for r in rows),win_rate=len(winning)/len(rows) if rows else None,
        profit=profit,loss=damage,net=profit-damage,gross=math.fsum(r['gross'] for r in rows),fees=sum(r['fees'] for r in rows),
        win_qty=sum(r['qty'] for r in winning),loss_qty=sum(r['qty'] for r in losing),flat_qty=sum(r['qty'] for r in rows if r['net']==0),
        avg_win=avg_win,avg_loss=avg_loss,payoff=avg_win/avg_loss if avg_loss and avg_win is not None else None,pf=profit/damage if damage else None,
        protected=sum(r['protected'] for r in rows),protected_shortfall=sum(r['protected_target_shortfall'] for r in rows),stopped_then_target=sum(r['stopped_then_eventual_target'] for r in rows),
        stop_count=sum(r['reason']==1 for r in rows),trail_count=sum(r['reason']==2 for r in rows),close_count=sum(r['reason']==4 for r in rows),
        hold_median_minutes=float(np.median([r['hold_minutes'] for r in rows])) if rows else None)


def gated(account,quote,signals,config):
    """機能: 予約の約定時刻で締切を確認し、保持・休止ゲートを別再生する。

    引数: account/quote/config(dict)、signals(ndarray)。返り値: 台帳・ゲート(tuple)。
    """
    rows=[];gates=dict(candidates=len(signals),accepted=0,scheduled=0,holding=0,cooldown=0,cutoff=0,expired=0)
    busy_to=-1;cooldown_to=-math.inf
    previous_signal=-1
    for signal in signals:
        i,side=int(signal[0]),int(signal[1])
        assert i>=previous_signal and side in (-1,1)
        previous_signal=i
        if i<=busy_to:
            gates['holding']+=1
            continue
        now=float(quote['time_s'][i])
        if now>=account['limit']-300:
            gates['cutoff']+=1
            continue
        if now<cooldown_to:
            gates['cooldown']+=1
            continue
        gates['scheduled']+=1
        # 判断と独立に予約を進め、次行で初めて約定期限を知る。
        if quote['time_s'][i+1]>=account['limit']-300:
            gates['expired']+=1
            continue
        row=trade(account,quote,i,side,config)
        rows.append(row);gates['accepted']+=1
        busy_to=row['exit_i'];cooldown_to=row['exit_time']+600
    assert gates['scheduled']==gates['accepted']+gates['expired']
    assert sum(gates[k] for k in ('accepted','holding','cooldown','cutoff','expired'))==gates['candidates']
    return rows,gates


def first(path,positive,negative):
    """機能: 対称又は非対称の二条件の最初の到達を分類する。

    引数: path(ndarray)、positive/negative(float)。返り値: 順行1・逆行-1・未到達0(int)。
    """
    positive_hits=np.flatnonzero(path>=positive-1e-9);negative_hits=np.flatnonzero(path<=-negative+1e-9)
    a=int(positive_hits[0]) if len(positive_hits) else len(path)
    b=int(negative_hits[0]) if len(negative_hits) else len(path)
    return 1 if a<b else -1 if b<a else 0


def main():
    """機能: 12条件全台帳、予約ゲート、因果prefix、旧14先着から新11勝を監査する。

    引数: なし。返り値: なし(None)。監査資料以外を編集しない。
    """
    result=json.loads((WORK/'結果.json').read_text(encoding='utf-8'))
    fixed=json.loads((WORK/'実行前固定.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((WORK/'実行前固定.json').read_bytes()).hexdigest()==result['固定SHA']
    for path,sha in fixed['SHA'].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==sha
    inputs=pickle.loads((ROOT/'work/wave_v60/inputs.pkl').read_bytes())
    quotes=pickle.loads((ROOT/'work/wave_v60/quotes.pkl').read_bytes())
    candidates=pickle.loads((ROOT/'work/wave_v63/directional/round3/入口候補.pkl').read_bytes())
    old=pickle.loads((ROOT/'work/wave_v63/directional/round3/ledgers/R3_DEPTH_C_quote.pkl').read_bytes())
    count_rows=count_isolated=count_accounts=0;reports=[]
    for method in result['methods']:
        config=method['config'];actual=[];isolated=[];accounts=[]
        for key in sorted(inputs):
            account,q=inputs[key],quotes[key]
            for name in ('seq','time_s'):
                np.testing.assert_array_equal(account[name],q[name])
            assert (np.diff(account['seq'])>0).all()
            rows,gates=gated(account,q,candidates[key]['DEPTH'],config)
            actual.extend(rows)
            accounts.append(dict(session=key[0],symbol=key[1],**summary(rows),gates=gates))
            for prior in old[(*key,'quote')]['trades']:
                matches=np.flatnonzero(account['seq']==int(prior[18]));assert len(matches)==1
                isolated.append(trade(account,q,int(matches[0]),int(prior[2]),config))
        same(method['rows'],actual);same(method['isolated'],isolated);same(method['accounts'],accounts)
        for symbol in ('TOPIX','NK225'):
            same(method['summary'][symbol],summary([r for r in actual if r['symbol']==symbol]))
            same(method['isolated_summary'][symbol],summary([r for r in isolated if r['symbol']==symbol]))
        count_rows+=len(actual);count_isolated+=len(isolated);count_accounts+=len(accounts)
        reports.append(dict(id=config['id'],連続取引数=len(actual),個別取引数=len(isolated),全口座一致=True,summary=method['summary']))
    # ----------------------------------------
    # 本体のprefixと未来改変を、別式の因果状態と照合する。
    sys.dont_write_bytecode=True
    sys.path.insert(0,str(WORK))
    engine=importlib.import_module('replay')
    prefix_checks=0;pending_exit=0;never_armed=0;future_checks=0;same_time_fills=0
    for method in result['methods']:
        c=method['config']
        for r in method['rows']:
            q=quotes[(r['session'],r['symbol'])];a=inputs[(r['session'],r['symbol'])]
            d,e,x=r['decision_i'],r['entry_i'],r['exit_i']
            cut_points={e+1,r['exit_decision_i']+1,x+1}
            if r['armed_i']>=0:
                cut_points.add(r['armed_i']+1)
            for length in sorted(cut_points):
                expected=vector_trace(q['time_s'][:length],q['bid'][:length],q['ask'][:length],d,r['side'],c,a['limit']-60)
                observed=engine.trace(q['time_s'][:length],q['bid'][:length],q['ask'][:length],d,r['side'],c['stop'],c['arm'],c['trail'],c['floor'],a['limit']-60)
                same(list(observed),list(expected));prefix_checks+=1
                pending_exit+=int(expected[0]>=0 and expected[1]>=length)
                never_armed+=int(expected[0]==-1 and expected[2]==-1)
            altered_bid=q['bid'][:x+4].copy();altered_ask=q['ask'][:x+4].copy()
            if len(altered_bid)>x+1:
                altered_bid[x+1:]+=10000;altered_ask[x+1:]+=10000
            observed=engine.trace(q['time_s'][:len(altered_bid)],altered_bid,altered_ask,d,r['side'],c['stop'],c['arm'],c['trail'],c['floor'],a['limit']-60)
            expected=vector_trace(q['time_s'],q['bid'],q['ask'],d,r['side'],c,a['limit']-60)
            same(list(observed),list(expected));future_checks+=1
            same_time_fills+=int(q['time_s'][r['exit_decision_i']]==q['time_s'][r['exit_i']])
    rng=np.random.default_rng(6507);synthetic_count=0
    for c in fixed['全条件']:
        for side in (1,-1):
            for pattern in ('開始直後に追跡','損切り後の復帰','保護後飛越え','値動き乱数'):
                gains={'開始直後に追跡':[-10,120,109,108,300,299],
                    '損切り後の復帰':[-10,-101,-102,300,299,298],
                    '保護後飛越え':[-10,300,-100,-150,1000,0],
                    '値動き乱数':[-10,*rng.integers(-300,600,size=5).tolist()]}[pattern]
                mid=np.array([100000-side*5,*[100000+side*(g+5) for g in gains]],dtype=float)
                bid,ask=mid-5,mid+5;times=np.floor(np.arange(len(mid))/3).astype(float)
                for cutoff in (9999.,1.):
                    expected=vector_trace(times,bid,ask,0,side,c,cutoff)
                    observed=engine.trace(times,bid,ask,0,side,c['stop'],c['arm'],c['trail'],c['floor'],cutoff)
                    same(list(observed),list(expected));synthetic_count+=1
    expired_times=np.array([0.,299.,300.,301.])
    expired_seq=np.arange(4,dtype=np.int64)
    expired_account=dict(session='合成',symbol='NK225',limit=600.,seq=expired_seq,time_s=expired_times)
    expired_quote=dict(seq=expired_seq,time_s=expired_times,bid=np.full(4,99990.),ask=np.full(4,100000.))
    expired_signals=np.array([[1.,1.],[2.,-1.]])
    expected_expired=gated(expired_account,expired_quote,expired_signals,fixed['主案'])
    observed_expired=engine.replay(expired_account,expired_quote,expired_signals,fixed['主案'])
    same(list(observed_expired),list(expected_expired))
    assert expected_expired[1]['scheduled']==1 and expected_expired[1]['expired']==1 and expected_expired[1]['accepted']==0
    # ----------------------------------------
    # 旧14順行先着と実11勝の間を、起点・価格・開始幅の一軸ずつで分解する。
    old_extent=json.loads((ROOT/'work/wave_v64/最大順行と入口採点.json').read_text(encoding='utf-8'))
    primary=result['methods'][0];new_rows={(r['session'],r['symbol'],r['decision_i'],r['side']):r for r in primary['isolated']}
    labels=('旧判断mid同幅','判断時新規気配からmid同幅','新建値からmid同幅','新建値から返済気配同幅','新建値百分率0_10','開始0_11','実決済勝敗')
    breakdown=[]
    for r in old_extent['rows']:
        if r['method']!='R3_DEPTH_C_quote' or r['symbol']!='NK225':
            continue
        key=(r['session'],r['symbol']);q=quotes[key];d=r['decision_i'];e=d+1;s=r['side']
        anchor=float(q['ask'][e] if s==1 else q['bid'][e]);width=r['extent']['到達']['0.10']['幅']
        decision_quote=float(q['ask'][d] if s==1 else q['bid'][d])
        decision_quote_path=s*(q['mid'][e:]-decision_quote)
        midpoint_path=s*(q['mid'][e:]-anchor);liquidation_path=s*((q['bid'] if s==1 else q['ask'])[e:]-anchor)
        actual=new_rows[(*key,d,s)]
        stages=[r['extent']['到達']['0.10']['先着'],first(decision_quote_path,width,width),first(midpoint_path,width,width),first(liquidation_path,width,width),
            first(liquidation_path,anchor*.001,anchor*.001),first(liquidation_path,anchor*.0011,anchor*.001),1 if actual['net']>0 else -1 if actual['net']<0 else 0]
        breakdown.append(dict(session=r['session'],decision_seq=r['decision_seq'],side=s,decision_mid=r['decision_mid'],entry_price=anchor,
            建値への方向差=s*(anchor-r['decision_mid']),判断時の気配差負担=s*(decision_quote-r['decision_mid']),
            次行までの新規気配悪化=s*(anchor-decision_quote),stages=dict(zip(labels,stages)),net=actual['net'],reason=actual['reason']))
    assert len(breakdown)==23
    stage_counts={label:{str(v):sum(r['stages'][label]==v for r in breakdown) for v in (-1,0,1)} for label in labels}
    transitions=[]
    for before,after in zip(labels,labels[1:]):
        lost=[dict(session=r['session'],decision_seq=r['decision_seq']) for r in breakdown if r['stages'][before]==1 and r['stages'][after]!=1]
        gained=[dict(session=r['session'],decision_seq=r['decision_seq']) for r in breakdown if r['stages'][before]!=1 and r['stages'][after]==1]
        transitions.append(dict(前=before,後=after,失った件数=len(lost),得た件数=len(gained),失った入口=lost,得た入口=gained))
    assert [stage_counts[label]['1'] for label in labels]==[14,14,12,12,12,11,11]
    same(primary['summary']['NK225']['net'],-18120.);same(primary['summary']['TOPIX']['net'],-405884.)
    for path,sha in fixed['SHA'].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==sha
    report=dict(結論='12条件の全連続・個別取引、全600口座ゲートと会計、prefixと未来改変検査が別式と一致',
        連続取引照合数=count_rows,個別取引照合数=count_isolated,口座照合数=count_accounts,
        prefix検査数=prefix_checks,返済判断済み未約定prefix数=pending_exit,開始前未決済prefix数=never_armed,
        未来改変検査数=future_checks,同時計の次原板返済約定数=same_time_fills,合成状態検査数=synthetic_count,
        予約後期限超過の合成検査=dict(一致=True,gates=expected_expired[1]),
        ゲート='新規予約は判定行の時計だけ。次行で期限超過ならexpired、scheduled=accepted+expiredを独立確認。',
        主案=primary['summary'],条件別=reports,
        旧14先着から新11勝の分解=dict(段階件数=stage_counts,移行=transitions,全23入口=breakdown),
        留意点=['0.1%利益線は判断条件で、次行約定利益の保証ではない。原板更新を同じCurrentPriceTimeでも原本順に処理する。',
        '前回の22/23 eventual到達と今回の11/23勝は異なる問い。旧mid先着14からの3件差は次行までの新規気配悪化2件と0.11%開始条件1件。判断時の半気配差だけではこの23件の先着数は変わらない。',
        '個別旧入口比較は重複可能な反実仮想。連続再生では元の入口候補列、保有状態、10分休止、締切を使う。',
        '幅は実新規約定基準の連続値、約定価格は離散した売買気配。手数料は新規・返済の両方に課金。',
        '事後eventual_targetは返済後の原因診断だけに使われ、売買条件へ渡されていない。',
        'ラージ板を小型商品の代理にする既知25場の再生で、未知将来の保証ではない。'],
        結果SHA256=hashlib.sha256((WORK/'結果.json').read_bytes()).hexdigest(),監査コードSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (HERE/'全条件の独立監査.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('結論','連続取引照合数','個別取引照合数','口座照合数','prefix検査数','返済判断済み未約定prefix数','未来改変検査数','同時計の次原板返済約定数','合成状態検査数')},ensure_ascii=False))


if __name__=='__main__':
    main()
