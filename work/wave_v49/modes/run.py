"""事前固定した追従・反復二十方式を保存済み十六場で比較する。"""

from pathlib import Path
import gzip
import hashlib
import json
import socket
import numpy as np

import features
import engine

HERE=Path(__file__).resolve().parent
NEW='2026-09-30_Night'


def save(path, value):
    """機能: この作業の結果を有限JSONに保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False).encode('utf8')
    path.write_bytes(gzip.compress(raw,mtime=0) if path.suffix=='.gz' else raw)


def catalog():
    """機能: 売買損益を見る前に比較条件を列挙する。

    引数: なし。返り値: 方式一覧(list[dict])。
    """
    rows=[
        ('T00','追従のみ',1,0,0,0,0,0),
        ('T01','追従のみ・板確認',1,1,0,0,0,0),
        ('R00','反復のみ',2,0,0,0,0,0),
        ('R01','反復のみ・板確認',2,1,0,0,0,0),
        ('A00','追従・反復の自動選択',0,0,0,0,0,0),
        ('A01','自動選択・板確認',0,1,0,0,0,0),
        ('A02','自動選択・反復は吸収確認',0,2,0,0,0,0),
        ('A03','自動選択・経過時間で早めに短縮',0,0,1,0,0,0),
        ('A04','自動選択・経過時間で遅めに短縮',0,0,2,0,0,0),
        ('A05','自動選択・高安更新停止10分で短縮',0,0,3,0,0,0),
        ('A06','自動選択・高安更新停止20分で短縮',0,0,4,0,0,0),
        ('A07','自動選択・板逆行で短縮',0,0,7,0,0,0),
        ('A08','板確認・時間と板逆行で短縮',0,1,5,0,0,0),
        ('A09','板確認・更新停止10分と板逆行で短縮',0,1,6,0,0,0),
        ('A10','反復の利確後に毎回逆向きへ',0,0,0,1,0,0),
        ('A11','反復の利確後に逆側の価格と板を確認',0,0,0,2,0,0),
        ('A12','自動選択・非中立モード変化で退出',0,0,0,0,1,0),
        ('A13','板確認・更新停止10分・モード変化退出',0,1,3,0,1,0),
        ('SR01','反復入口を20分支持抵抗へ置換',0,0,0,0,0,1),
        ('SR02','支持抵抗の反発と追従時の突破',0,0,0,0,0,2),
    ]
    fields=['id','name','mode_choice','book_rule','exit_rule','flip_rule','mode_exit','sr_rule']
    return [dict(zip(fields,row)) for row in rows]


def freeze():
    """機能: 損益未読の条件と比較範囲を固定する。

    引数: なし。返り値: 固定書(dict)。
    """
    value=dict(方式=catalog(),比較='二十方式の共通試作器。同じ入口・単一保有・固定初期枚数。既存候補1の部分決済・影運転とは異なる。',
        初期枚数={'TOPIX':5,'NK225':10},片方向上限={'TOPIX':10,'NK225':20},増玉='なし',
        円換算={'TOPIX':1000,'NK225':10},費用=0,API取得数=0,
        エントリー='方向が有効なら追跡安値/高値から0.2ATR反発の逆指値。準備は最大300秒、無効なら次観測から取消。',
        追従出口='準備時ATR固定、初期損切1ATR、1.5ATR順行で3ATRトレール、3ATR順行後0.75ATR、最大360分。',
        反復出口='準備時ATR固定、初期損切0.8ATR、0.5ATR順行で0.35ATRトレール、最大45分。',
        時間早='追従30/60分で幅1/0.5ATR、反復10/20分で0.25/0.15ATR。',
        時間遅='追従60/120分で幅1/0.5ATR、反復20/40分で0.25/0.15ATR。',
        更新停止='最高含み益価格を10分/20分更新しない場合、追従0.5ATR・反復0.25ATR。',
        板逆行='公開済み板scoreが保有と逆へ0.15超の場合、追従0.5ATR・反復0.25ATR。',
        短縮共通='通常トレールの順行開始条件を満たしてからのみ。ストップを緩めない。新しい水準を既に通過していれば次行価格で成行返済。',
        支持抵抗='直近20実分の確定足高安。反復は端から0.25ATR以内、追従突破は端を0.1ATR超えることを追加。未来の確定ピボット不使用。',
        反転='反復のトレール黒字返済後120秒のみ。毎回反転は逆方向1呼値の逆指値、確認反転は逆側の通常価格条件と板score0.1超を要求。',
        場内返済='15:35/05:50で次行返済要求。最終まで建玉ゼロを検算。新規はその60秒前まで。',
        評価='旧15と原因分析済み09/30Nightを分離。全16は探索結果で未見試験ではない。取引ゼロを優位と呼ばない。')
    path=HERE/'方式の事前固定.json'
    if path.exists():assert json.loads(path.read_text(encoding='utf8'))==value
    else:save(path,value)
    return value


def execute(ready, model, spec, require_flat=True):
    """機能: 一口座の原本行と公開特徴を共通再生器へ渡す。

    引数: ready/model/spec(dict)、require_flat(bool)。返り値: 注文・決済・時価・モード・監査配列(tuple)。
    """
    return engine.replay(ready['time_s'],ready['last'],ready['atr'],
        *(model[k] for k in ('mode','trend','range_side','book_score','book_valid','absorb_side','support20','resistance20')),
        ready['limit'],ready['tick'],5 if ready['symbol']=='TOPIX' else 10,
        *(spec[k] for k in ('mode_choice','book_rule','exit_rule','flip_rule','mode_exit','sr_rule')),require_flat)


def metrics(trades, equity, multiplier):
    """機能: 金額と決済枚数の損小利大指標を計算する。

    引数: trades/equity(ndarray)、multiplier(float)。返り値: 指標(dict)。
    """
    p=trades[:,10]*multiplier;q=trades[:,3]
    gross=float(p[p>0].sum());loss=float(-p[p<0].sum())
    wq=float(q[p>0].sum());lq=float(q[p<0].sum())
    line=np.r_[0.,equity*multiplier]
    dd=float(np.max(np.maximum.accumulate(line)-line))
    return dict(net=float(p.sum()),gross_profit=gross,gross_loss=loss,trades=len(p),
        wins=int((p>0).sum()),losses=int((p<0).sum()),win_qty=wq,loss_qty=lq,
        flat_qty=float(q[p==0].sum()),dd=dd,
        unit_payoff=(gross/wq)/(loss/lq) if wq and lq and loss else None,
        pf=gross/loss if loss else None)


def audit(ready, orders, trades, equity, qty):
    """機能: 注文から現金・保有を再計算し、全行時価・場内返済を照合する。

    引数: ready(dict)、orders/trades/equity(ndarray)、qty(int)。返り値: 検算結果(dict)。
    """
    n=len(equity);flow=np.zeros(n);holding=np.zeros(n)
    for row in orders:
        i,source,cid,side,size,fill,reason,kind=row
        assert 0<=source<i<n and size==qty
        flow[int(i)]-=side*size*fill;holding[int(i)]+=side*size
        if kind:assert ready['time_s'][int(i)]<ready['limit']
    position=holding.cumsum();cash=flow.cumsum()
    assert np.abs(position).max(initial=0)<=qty and position[-1]==0
    np.testing.assert_allclose(cash+position*ready['last'],equity,atol=1e-6,rtol=0)
    np.testing.assert_allclose(trades[:,10],trades[:,2]*trades[:,3]*(trades[:,5]-trades[:,4]),atol=1e-6,rtol=0)
    assert abs(trades[:,10].sum()-equity[-1])<1e-6
    assert len(orders)==2*len(trades)
    return dict(合格=True,原本行数=n,往復=len(trades),最大保有=int(np.max(np.abs(position),initial=0)))


def blocked_socket(*args,**kwargs):
    """機能: 検証中のネットワーク利用を拒否する。

    引数: args(tuple)、kwargs(dict)。返り値: なし。常にRuntimeError。
    """
    raise RuntimeError('保存済みデータ専用の検証です')


def main():
    """機能: 全方式を再生し、期間別集計と注文明細を保存する。

    引数: なし。返り値: なし(None)。
    """
    definition=freeze();socket.socket=blocked_socket
    inputs,board=features.load_inputs();models=features.build(inputs,board)
    results=[];checks=[]
    for spec in definition['方式']:
        rows=[];ledgers=[];paths={}
        for key in sorted(inputs):
            ready=inputs[key];result=execute(ready,models[key],spec)
            orders,trades,equity,trade_modes,trace=result
            multiplier=1000 if key[1]=='TOPIX' else 10
            stat=metrics(trades,equity,multiplier)
            stat.update(session=key[0],symbol=key[1],trend_trades=int((trade_modes==1).sum()),
                range_trades=int((trade_modes==2).sum()),trend_net=float(trades[trade_modes==1,10].sum()*multiplier),
                range_net=float(trades[trade_modes==2,10].sum()*multiplier))
            rows.append(stat);paths[key]=equity*multiplier
            ledgers.append(dict(session=key[0],symbol=key[1],orders=orders.tolist(),trades=trades.tolist(),trade_modes=trade_modes.tolist()))
            checks.append(dict(id=spec['id'],session=key[0],symbol=key[1],**audit(ready,orders,trades,equity,5 if key[1]=='TOPIX' else 10)))
        # ----------------------------------------
        # 期間の時価下落は各場の原本行を時系列につなぎ、場ごとの最大値の単純最大で代用しない。
        periods={}
        for period in ('旧15','問題Night','全16'):
            periods[period]={}
            for symbol in ('TOPIX','NK225'):
                selected=[r for r in rows if r['symbol']==symbol and (period=='全16' or ((r['session']==NEW)==(period=='問題Night')))]
                totals={k:sum(r[k] for r in selected) for k in ('net','gross_profit','gross_loss','trades','wins','losses','win_qty','loss_qty','flat_qty','trend_trades','range_trades','trend_net','range_net')}
                offset=0.;lines=[np.array([0.])]
                for r in selected:
                    lines.append(paths[r['session'],symbol]+offset);offset+=r['net']
                line=np.concatenate(lines)
                totals['dd']=float(np.max(np.maximum.accumulate(line)-line))
                totals['win_sessions']=sum(r['net']>0 for r in selected)
                totals['active_sessions']=sum(r['trades']>0 for r in selected)
                totals['session_count']=len(selected)
                g,l,wq,lq=(totals[k] for k in ('gross_profit','gross_loss','win_qty','loss_qty'))
                totals['pf']=g/l if l else None
                totals['unit_payoff']=(g/wq)/(l/lq) if wq and lq and l else None
                totals['without_best_session']=totals['net']-max(0,max(r['net'] for r in selected))
                periods[period][symbol]=totals
        results.append(dict(spec=spec,periods=periods,sessions=rows))
        save(HERE/'ledgers'/(spec['id']+'.json.gz'),ledgers)
        save(HERE/'summaries'/(spec['id']+'.json'),results[-1])
        print(spec['id'],'完了',flush=True)
    save(HERE/'自動モードの比較.json',results)
    save(HERE/'会計検算.json',dict(合格=True,口座数=len(checks),詳細=checks,
        ソース指紋={name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in ('engine.py','features.py','run.py','方式の事前固定.json','特徴定義.json')}))


if __name__=='__main__':main()
