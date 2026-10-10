"""人工価格だけで単発IFD-OCOの成立・不成立・優先・口座を独立検算する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
import urllib.request

import numpy as np

import engine_single as engine
import design
import execution_audit

HERE = Path(__file__).resolve().parent
EXECUTION_FAILURES = []


def denied(*args: object, **kwargs: object) -> None:
    """機能: 人工検査からの通信を拒否する。

    引数: 任意(object)。返り値: なし(None)、常に例外。
    """
    raise AssertionError('人工検査では通信を使用しません')


def fixture(times: list, prices: list, limit: float = 2200.) -> dict:
    """機能: 観測行の疎密を指定できる人工原本を作る。

    引数: times/prices(list)、limit(float)。返り値: 原本形式(dict)。
    """
    assert len(times) == len(prices)
    return dict(seq=np.arange(len(times),dtype=np.int64),time_s=np.asarray(times,float),
        last=np.asarray(prices,float),atr=np.full(len(times),2.),tick=1.,limit=limit,session_close=limit+600.)


def oracle(ready: dict, pulses: np.ndarray, delay: float, observed: bool, complete: bool) -> dict:
    """機能: 注文と建玉を別オブジェクトとして規則から取引結果を再構築する。

    引数: ready(dict)、pulses(ndarray)、delay(float)、observed/complete(bool)。返り値: 期待4配列(dict)。
    エンジンのsimulate・台帳・集計は使用せず、当行で成立しない注文も走査する。
    """
    times, prices = ready['time_s'],ready['last']
    queue = None; held = None; timer = None; resume = -float('inf')
    trades=[];orders=[];curve=[];candidate_count=accepted=cancelled=0
    realized=cash=peak=worst=0.
    for i,(time,price) in enumerate(zip(times,prices)):
        if time >= ready['session_close'] and (queue is not None or held is not None):
            raise ValueError('終場時の未完了')
        used=False
        if held is not None:
            decision=None
            if i > held['row'] and time >= held['child_at']:
                lower,upper=held['stop'],held['target']
                stop_hit = price <= lower if held['side']==1 else price >= lower
                target_hit = price >= upper if held['side']==1 else price <= upper
                if stop_hit: decision=(price if observed else lower,1,held['row'])
                elif target_hit: decision=(price if observed else upper,2,held['row'])
            if decision is None and timer is not None and i > timer['row'] and time >= timer['at']:
                decision=(price,timer['reason'],timer['row'])
            if decision is not None:
                fill,reason,source=decision;side=held['side']
                pnl=side*(fill-held['price']);realized+=pnl;cash+=side*fill
                orders.append([i,source,-side,1.,fill,reason,0.])
                trades.append([held['row'],i,side,held['price'],fill,held['risk'],pnl,reason,held['decision'],source])
                held=None;timer=None;resume=time+300.;used=True
        if queue is not None and time >= ready['limit']:
            queue=None;cancelled+=1
        if not used and held is None and queue is not None and i > queue['row'] and time >= queue['at']:
            side=queue['side'];risk=queue['risk'];cash-=side*price
            held=dict(side=side,price=price,row=i,decision=queue['row'],risk=risk,
                child_at=time+delay,stop=price-side*risk,target=price+side*2*risk,timer_at=time+1800.)
            orders.append([i,queue['row'],side,1.,price,0.,1.]);queue=None;used=True
        if held is not None and timer is None:
            reason = 4 if time >= ready['limit'] else 3 if time >= held['timer_at'] else None
            if reason is not None: timer=dict(row=i,at=time+delay,reason=reason)
        if pulses[i] != 0:
            candidate_count+=1
            if not used and held is None and queue is None and time < ready['limit']-300. and time >= resume:
                atr=float(ready['atr'][i]);tick=ready['tick']
                if np.isfinite(atr) and atr>0:
                    risk=float(np.ceil(max(atr,2*tick)/tick)*tick)
                    queue=dict(row=i,side=int(pulses[i]),risk=risk,at=time+delay);accepted+=1
        quantity=held['side'] if held is not None else 0
        equity=cash+quantity*price;peak=max(peak,equity);worst=max(worst,peak-equity)
        curve.append([realized,equity,quantity,peak-equity])
    if complete and (held is not None or queue is not None): raise ValueError('保存末尾未完了')
    return dict(trades=np.asarray(trades,float).reshape(-1,10),orders=np.asarray(orders,float).reshape(-1,7),
        curve=np.asarray(curve,float).reshape(-1,4),stats=np.asarray([realized,worst,candidate_count,accepted,cancelled,
            0 if held is None else held['side'],0 if queue is None else queue['side']],float))


def account(ready: dict, result: dict) -> None:
    """機能: 全注文から現金・保有を、全返済から実現損益を別に積算する。

    引数: ready/result(dict)。返り値: なし(None)。
    """
    changes=np.zeros((len(ready['seq']),3))
    for row,source,side,qty,price,reason,opening in result['orders']:
        assert int(row)==row and int(source)==source and source<row and qty==1
        assert ready['time_s'][int(row)]<ready['session_close']
        changes[int(row),:2] += [-side*qty*price,side*qty]
    for trade in result['trades']:
        assert trade[1]>trade[0]
        assert trade[6]==trade[2]*(trade[4]-trade[3])
        changes[int(trade[1]),2] += trade[6]
    sums=changes.cumsum(axis=0);equity=sums[:,0]+sums[:,1]*ready['last']
    expected=np.column_stack((sums[:,2],equity,sums[:,1],np.maximum.accumulate(np.maximum(0,equity))-equity))
    np.testing.assert_allclose(result['curve'],expected,rtol=0,atol=1e-9)
    assert np.all(abs(sums[:,1])<=1)


def verify(label: str, ready: dict, positions: dict, delay: float = 0., observed: bool = False,
           complete: bool = True) -> tuple:
    """機能: 独立参照と注文器の全配列又は拒否を照合する。

    引数: label(str)、ready/positions(dict)、delay(float)、observed/complete(bool)。返り値: 検査記録・結果(tuple)。
    """
    pulse=np.zeros(len(ready['seq']),np.int8)
    for row,direction in positions.items(): pulse[row]=direction
    expected_error=actual_error=None;expected=actual=None
    try: expected=oracle(ready,pulse,delay,observed,complete)
    except ValueError as error: expected_error=str(error)
    try: actual=engine.run(ready,pulse,delay,observed,complete)
    except ValueError as error: actual_error=str(error)
    assert (expected_error is None)==(actual_error is None),(label,expected_error,actual_error)
    if expected_error is None:
        for field in expected: np.testing.assert_array_equal(actual[field],expected[field],err_msg=label+field)
        account(ready,actual)
        if complete:
            try: execution_audit.check(ready,pulse,actual,delay,observed)
            except (AssertionError,ValueError,IndexError) as error:
                EXECUTION_FAILURES.append(dict(検査=label,秒=delay,観測約定=observed,
                    例外=type(error).__name__,説明=str(error),時刻=ready['time_s'].tolist(),価格=ready['last'].tolist()))
    return dict(検査=label,秒=delay,観測約定=observed,完全口座=complete,独立式一致=True,
        未完了又は場外拒否=expected_error is not None),actual


def main() -> None:
    """機能: 指定境界・疎な人工経路・不正入力を検査し、欠陥も隠さず保存する。

    引数: なし。返り値: なし(None)。原本・実相場・保存ライブは読まない。
    """
    socket.create_connection=denied;urllib.request.urlopen=denied
    sources=[Path(engine.__file__),Path(design.__file__),HERE/'check_engine_single.py',Path(execution_audit.__file__),Path(__file__)]
    before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    checks=[];findings=[]
    cases=[
        ('同秒で親子は別行',fixture([0,0,0,1],[100,100,105,105]),{0:1},0.,True),
        ('未成熟中だけの交差は遡って返済しない',fixture([0,15,16,29,30,1815,1830],[100,100,95,100,100,100,100]),{0:1},15.,True),
        ('未成熟時間返済中もOCO有効',fixture([0,15,1815,1820,1830],[100,100,100,95,95]),{0:1},15.,True),
        ('成熟時間返済より成熟停止が優先',fixture([0,15,1815,1830],[100,100,100,95]),{0:1},15.,True),
        ('成熟時間返済より成熟利確が優先',fixture([0,15,1815,1830],[100,100,100,106]),{0:1},15.,True),
        ('安全時刻で未成熟新規を取消',fixture([0,699,700,1000],[100]*4,1000),{1:1},15.,True),
        ('新規締切等号は不採用',fixture([0,700,701,1000,1001],[100]*5,1000),{1:1},0.,True),
        ('締切前準備の遅延約定は安全時刻前まで可',fixture([0,699,999,1000,1015],[100]*5,1000),{1:1},15.,True),
        ('反対パルスは既存新規を変更しない',fixture([0,1,5,10,1805,1810],[100]*6),{0:1,1:-1},5.,True),
        ('最終行の新規予約を完了と誤認しない',fixture([0,1],[100,100]),{1:1},0.,True),
        ('最終行の保有を完了と誤認しない',fixture([0,1],[100,100]),{0:1},0.,True),
        ('途中切断の未約定は架空約定しない',fixture([0,1],[100,100]),{1:1},15.,False),
        ('場末返済判断だけでは完了しない',fixture([0,1,1000],[100]*3,1000),{0:1},0.,True),
        ('真の終場でOCO交差しても場内約定へ戻さない',fixture([0,1,1600],[100,100,90],1000),{0:1},0.,True),
        ('真の終場の予約取消も間に合わなければ拒否',fixture([0,699,1600],[100]*3,1000),{1:1},15.,True),
        ('休止等号だけで再準備し同じ返済行には再入場しない',fixture([0,1,2,301,302,303,304],[100,100,104,100,100,100,104]),{0:1,2:-1,3:1,4:1},0.,True),
    ]
    for label,ready,pulses,delay,complete in cases:
        for mirror in (False,True):
            for observed in (False,True):
                material=deepcopy(ready);directions=dict(pulses)
                if mirror:
                    material['last']=400-material['last'];directions={k:-v for k,v in directions.items()}
                item,result=verify(label,material,directions,delay,observed,complete)
                item['上下反射']=mirror;checks.append(item)
    # ----------------------------------------
    # 入力ATRは準備行で固定。後続のATR変化・無効なATR発火を混同しない。
    ready=fixture([0,1,5,10,20,2000,2010],[100,100,100,105,105,105,105])
    ready['atr'][:]=100.;ready['atr'][0]=2.
    item,result=verify('入口判断のATRを固定',ready,{0:1},5.)
    assert result['trades'][0,5]==2.;checks.append(item)
    ready=fixture([0,1,2,2200,2201],[100]*5);ready['atr'][0]=np.nan
    item,result=verify('ATR欠測パルスは新規化しない',ready,{0:1})
    assert len(result['orders'])==0;checks.append(item)
    # ----------------------------------------
    # 小さな固定乱数の疎な観測。未発火・予約中・休止中を含め全行の不成立も比較する。
    for seed in range(16):
        random=np.random.default_rng(seed)
        n=160;times=np.cumsum(random.choice([0.,1.,5.,20.,60.],n))
        limit=float(times[-1]+100.)
        prices=1000.+np.cumsum(random.choice([-5.,-1.,0.,1.,5.],n))
        ready=fixture(list(times)+[limit,limit+1,limit+15,limit+30],list(prices)+[float(prices[-1])]*4,limit)
        pulse={i:int(random.choice([-1,1])) for i in range(0,n,7)}
        for delay in (0.,1.,5.,15.):
            for observed in (False,True):
                item,result=verify('固定乱数の全成立不成立',ready,pulse,delay,observed)
                item['seed']=seed;checks.append(item)
                for end in (41,100):
                    part={k:v[:end].copy() if isinstance(v,np.ndarray) else v for k,v in ready.items()}
                    row,short=verify('途中切断',part,{k:v for k,v in pulse.items() if k<end},delay,observed,False)
                    np.testing.assert_array_equal(short['curve'],result['curve'][:end])
                    np.testing.assert_array_equal(short['orders'],result['orders'][result['orders'][:,0]<end])
                    row['seed']=seed;row['切断行']=end;checks.append(row)
                    future=deepcopy(ready);future['last'][end:]+=11.;future['atr'][end:]*=3
                    future_pulse={k:(-v if k>=end else v) for k,v in pulse.items()}
                    future_row,changed=verify('未来価格ATRパルス差替',future,future_pulse,delay,observed)
                    np.testing.assert_array_equal(changed['curve'][:end],result['curve'][:end])
                    np.testing.assert_array_equal(changed['orders'][changed['orders'][:,0]<end],short['orders'])
                    future_row['seed']=seed;future_row['切断行']=end;checks.append(future_row)
    # ----------------------------------------
    # 境界加工で列長がずれたとき、末尾を黙って捨てる実装を拒否する。
    invalid=fixture([0,1,2],[100]*3);invalid['time_s']=invalid['time_s'][:2]
    try: result=engine.run(invalid,np.asarray([0,0,1],np.int8))
    except (AssertionError,ValueError): checks.append(dict(検査='異長列の末尾脱落を拒否',独立式一致=True))
    else:
        findings.append(dict(欠陥='入力列の異長による末尾パルス脱落',入力='seq/pulse/last/atr各3行、timeだけ2行、pulse=[0,0,1]',
            観測結果=dict(curve行数=len(result['curve']),stats=result['stats'].tolist()),
            期待='売買開始前に異長を拒否',実相場への発生を確認したものではない=True))
    rejected=[]
    for name in ('空配列','二次元','float行番号','時刻NaN','時刻無限','時刻逆行','行番号重複','呼値0','呼値NaN',
                 '終場逆転','価格0','価格NaN','パルス型','bool遅延','完結flag型'):
        r=fixture([0,1,2,2200,2201],[100]*5);pulse=np.zeros(5,np.int8);kwargs={}
        if name=='空配列':
            for k in ('seq','time_s','last','atr'):r[k]=r[k][:0]
            pulse=pulse[:0]
        elif name=='二次元':r['atr']=r['atr'][:,None]
        elif name=='float行番号':r['seq']=r['seq'].astype(float)
        elif name=='時刻NaN':r['time_s'][1]=np.nan
        elif name=='時刻無限':r['time_s'][-1]=np.inf
        elif name=='時刻逆行':r['time_s'][2]=0.
        elif name=='行番号重複':r['seq'][2]=r['seq'][1]
        elif name=='呼値0':r['tick']=0.
        elif name=='呼値NaN':r['tick']=np.nan
        elif name=='終場逆転':r['session_close']=r['limit']
        elif name=='価格0':r['last'][1]=0.
        elif name=='価格NaN':r['last'][1]=np.nan
        elif name=='パルス型':pulse=pulse.astype(float)
        elif name=='bool遅延':kwargs['delay']=True
        else:kwargs['require_flat']='false'
        try:engine.run(r,pulse,**kwargs)
        except (AssertionError,ValueError):rejected.append(name)
        else:findings.append(dict(欠陥='不正入力を拒否しない',入力=name))
    audit_rejections=[]
    ready=fixture([0,15,30,1820,1840,2200,2215],[100,100,106,106,106,106,106])
    pulse=np.zeros(7,np.int8);pulse[0]=1
    result=engine.run(ready,pulse,15.)
    execution_audit.check(ready,pulse,result,15.,False)
    for name in ('新規脱落','返済脱落','約定重複','方向改変','根拠未来','価格改変','返済損益改変',
                 '時価改変','保有改変','候補数改変','受付数改変','取消数改変'):
        broken=deepcopy(result)
        if name=='新規脱落':broken['orders']=broken['orders'][1:]
        elif name=='返済脱落':broken['orders']=broken['orders'][:1]
        elif name=='約定重複':broken['orders']=np.vstack((broken['orders'],broken['orders'][-1]))
        elif name=='方向改変':broken['orders'][0,2]*=-1
        elif name=='根拠未来':broken['orders'][0,1]=broken['orders'][0,0]
        elif name=='価格改変':broken['orders'][1,4]+=1
        elif name=='返済損益改変':broken['trades'][0,6]+=1
        elif name=='時価改変':broken['curve'][2,1]+=1
        elif name=='保有改変':broken['curve'][2,2]+=1
        elif name=='候補数改変':broken['stats'][2]+=1
        elif name=='受付数改変':broken['stats'][3]+=1
        else:broken['stats'][4]+=1
        try:execution_audit.check(ready,pulse,broken,15.,False)
        except AssertionError:audit_rejections.append(name)
        else:findings.append(dict(欠陥='外部独立監査が破損を拒否しない',入力=name))
    catalog=design.catalog();supplement=design.supplementary()
    assert len(catalog)==48 and len(supplement)==192 and len({r['id'] for r in catalog+supplement})==240
    assert design.rules()['各銘柄1枚'] is True
    after={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    assert before==after,'検査中に元実装が変わりました'
    report=dict(有効入力の独立人工一致=True,入力契約を含む全合格=not findings,人工検査数=len(checks),
        検査=checks,欠陥=findings,実相場損益未実施=True,原本未読=True,現在保存物使用=False,API取得数=0,
        元コード変更=False,SHA256=before,前後SHA256一致=True,
        不正入力拒否数=len(rejected),不正入力拒否=rejected,外部独立監査の不一致=EXECUTION_FAILURES,
        外部独立監査も全一致=not EXECUTION_FAILURES,外部監査破損拒否数=len(audit_rejections),外部監査破損拒否=audit_rejections,
        発見前engineSHA256='69cfb34c7c10b934aa7e0848abac87e93ddec89f826c27472e062832d8b1a6f9',
        結果前の入力契約補正='時刻列だけ短いと末尾パルスを消失。親担当が非空・同長等を追加し、今回の人工で拒否を確認。',
        仕様上の注意='新規5分前締切は準備受付の締切。既予約は安全時刻より前なら締切後にも約定し得る。')
    (HERE/'check_engine_adversarial.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('検査','SHA256','欠陥')},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
