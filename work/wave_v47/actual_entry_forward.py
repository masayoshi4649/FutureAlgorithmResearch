"""旧A0の実初回102組について、元の出口から切り離して先行価格を診断する。"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
import pickle
from datetime import datetime

import numpy as np

from forward_entry_diagnostic import sha,save_json,save_csv,summarize,HORIZONS,JST


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=HERE/'forward_actual'
LEDGER=HERE.parent/'wave_v45/ledgers/A0__V000.json.gz'


def labels(time: np.ndarray,price: np.ndarray,entry: int,anchor: float,
           atr: float,direction: int,deadline: float) -> np.ndarray:
    """機能: 実初回の指定約定価格を起点に、場内の先行値動きを計算する。

    引数: time/price (ndarray)、entry/direction (int)、anchor/atr/deadline (float)。
    返り値: 4期間×8列の評価値 (ndarray[float64])。
    列は状態、初回行、評価行、ATR、符号付変化ATR、最大順行ATR、最大逆行ATR、到達遅れ秒。
    """
    assert direction in (-1,1) and 0<=entry<len(time)
    assert np.isfinite(anchor) and anchor>0 and np.isfinite(atr) and atr>0
    result=np.full((4,8),np.nan)
    for h,minutes in enumerate(HORIZONS):
        result[h,1]=entry
        result[h,3]=atr
        target=float(time[entry])+minutes*60
        end=int(np.searchsorted(time,target,side='left'))
        if target>deadline or end>=len(time) or time[end]>deadline:
            result[h,0]=3
            continue
        path=direction*(price[entry:end+1]-anchor)/atr
        assert np.isfinite(path).all() and (price[entry:end+1]>0).all()
        result[h]=[0,entry,end,atr,path[-1],max(0,float(path.max())),max(0,float(-path.min())),time[end]-target]
    return result


def synthetic() -> dict:
    """機能: 観測価格と異なる指定約定値を使い、全期間を手計算で検査する。

    引数: なし。返り値: 人工検査記録 (dict)。
    """
    time=np.array([0.,0.,300.,900.,1800.,3600.,3601.])
    prices=np.array([500.,100.,110.,90.,120.,80.,200.])
    value=labels(time,prices,1,90.,10.,1,3600.)
    np.testing.assert_allclose(value[:,4],[2.,0.,3.,-1.])
    np.testing.assert_allclose(value[:,5],[2.,2.,3.,3.])
    np.testing.assert_allclose(value[:,6],[0.,0.,0.,1.])
    reflected=labels(time,1000-prices,1,910.,10.,-1,3600.)
    np.testing.assert_allclose(value,reflected)
    assert labels(time,prices,1,90.,10.,1,3599.)[-1,0]==3
    inverse=labels(time,prices,1,90.,10.,-1,3600.)
    np.testing.assert_allclose(inverse[:,4],-value[:,4])
    np.testing.assert_allclose(inverse[:,5],value[:,6])
    np.testing.assert_allclose(inverse[:,6],value[:,5])
    return dict(全合格=True,原本価格と異なる指定値基準=True,四期間手計算=True,
        初回から順行逆行を計算=True,元退出時刻を入力しない=True,場末不足=True,上下反射=True,反対方向対称=True)


def freeze() -> dict:
    """機能: 実初回の未来値動きを読む前に、母集団と評価規則を固定する。

    引数: なし。返り値: 固定規則 (dict)。
    """
    OUT.mkdir(exist_ok=True)
    value=dict(対象='旧13セッションのA0固定戦略。TOPIX50／NK22552の実初回102組。',
        基準='元注文台帳の初回約定価格と初回原本行時刻。元組の初回ATRを使用。数量を掛けない。',
        評価='5/15/30/60分経過後の最初の観測価格。元の退出を無視し、ready.limitと観測末尾の早い方まで。',
        共通標本='60分まで評価可能な初回を全4期間へ使用。各期間の全有効標本も別記。',
        集計='セッション別平均を等重み。欠測場数を表示し、ゼロ評価へ置換しない。',
        比較='全発火と実初回は違う時刻・標本であり、追跡新規だけの因果効果とは呼ばない。口座PF・勝率ではない。',
        新ナイト読取=False,売買再生=False,API取得数=0,人工=synthetic(),
        参照SHA256={path.relative_to(ROOT).as_posix():sha(path) for path in (
            Path(__file__),HERE/'forward_entry_diagnostic.py',LEDGER,HERE.parent/'wave_v23/inputs.pkl',
            HERE/'forward/先行価格診断.json')})
    target=OUT/'実初回診断の事前固定.json'
    if target.exists():
        assert json.loads(target.read_text(encoding='utf-8'))==value
    else:
        save_json(target,value)
    return value


def run() -> None:
    """機能: 102実初回の408評価とセッション・日夜集計を保存する。

    引数: なし。返り値: なし (None)。旧戦略の初回母集団を選び直さない。
    """
    fixed=freeze()
    inputs=pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    ledgers=json.loads(gzip.decompress(LEDGER.read_bytes()))
    assert len(inputs)==len(ledgers)==26 and not any(key[0]=='2026-09-29_Night' for key in inputs)
    events=[]
    sessions=[]
    counts={'TOPIX':0,'NK225':0}
    independent_checks=0
    for ledger in ledgers:
        key=ledger['session'],ledger['symbol']
        ready=inputs[key]
        orders=np.asarray(ledger['orders'],float).reshape(-1,8)
        cycles=np.asarray(ledger['cycles'],float).reshape(-1,10)
        opened=orders[(orders[:,6]==20)&(orders[:,7]==1)]
        assert len(opened)==len(cycles)
        results=[]
        directions=[]
        for cycle in cycles:
            campaign=int(cycle[0])
            order=opened[opened[:,2]==campaign]
            assert len(order)==1
            order=order[0]
            entry=int(order[0])
            assert entry==int(cycle[1]) and order[3]==cycle[8]
            assert order[4]==(5 if key[1]=='TOPIX' else 10)
            atr=float(cycle[5])
            anchor=float(order[5])
            direction=int(order[3])
            value=labels(ready['time_s'],ready['last'],entry,anchor,atr,direction,
                         min(float(ready['limit']),float(ready['time_s'][-1])))
            results.append(value)
            directions.append(direction)
            counts[key[1]]+=1
            common=bool(value[3,0]==0)
            for h,minutes in enumerate(HORIZONS):
                status=int(value[h,0])
                end=int(value[h,2]) if status==0 else None
                if status==0:
                    # ----------------------------------------
                    # 保存行を作る前に別式の価格極値で全有効ラベルを検算する。
                    segment=ready['last'][entry:end+1]
                    endpoint=direction*(ready['last'][end]-anchor)/atr
                    maximum=max(0.,direction*(float(segment.max())-anchor)/atr,
                                direction*(float(segment.min())-anchor)/atr)
                    adverse=max(0.,-direction*(float(segment.max())-anchor)/atr,
                                -direction*(float(segment.min())-anchor)/atr)
                    np.testing.assert_allclose(value[h,4:7],[endpoint,maximum,adverse],rtol=1e-10,atol=1e-10)
                    independent_checks+=1
                events.append(dict(セッション=key[0],銘柄=key[1],場='デイ' if key[0].endswith('_Day') else 'ナイト',
                    元組=campaign,方向=direction,初回行=entry,初回seq=int(ready['seq'][entry]),
                    初回時刻=datetime.fromtimestamp(ready['time_s'][entry],JST).isoformat(),指定約定価格=anchor,
                    同行観測価格=float(ready['last'][entry]),初回ATR=atr,期間分=minutes,
                    状態='有効' if status==0 else '期限不足',共通60分標本=common,
                    評価行=end,評価価格=float(ready['last'][end]) if end is not None else None,
                    符号付変化ATR=float(value[h,4]) if status==0 else None,
                    最大順行ATR=float(value[h,5]) if status==0 else None,
                    最大逆行ATR=float(value[h,6]) if status==0 else None,
                    到達遅れ秒=float(value[h,7]) if status==0 else None))
        results=np.asarray(results,float).reshape(-1,4,8)
        directions=np.asarray(directions,int)
        for side,label in ((0,'両方向'),(1,'買い'),(-1,'売り')):
            side_mask=np.ones(len(results),bool) if side==0 else directions==side
            common=results[:,3,0]==0
            for h,minutes in enumerate(HORIZONS):
                valid=results[:,h,0]==0
                for cohort in ('共通60分','期間別全有効'):
                    eligible=side_mask&(common if cohort=='共通60分' else valid)
                    sessions.append(dict(セッション=key[0],銘柄=key[1],場='デイ' if key[0].endswith('_Day') else 'ナイト',
                        方向区分=label,期間分=minutes,標本=cohort,実初回数=int(side_mask.sum()),
                        期限不足数=int((side_mask&~valid).sum()),共通60分除外数=int((side_mask&valid&~common).sum()),
                        **summarize(results[eligible,h,:])))
    assert counts=={'TOPIX':50,'NK225':52} and len(events)==408
    groups=[]
    for symbol in ('TOPIX','NK225'):
        for market in ('全場','デイ','ナイト'):
            for side in ('両方向','買い','売り'):
                for minutes in HORIZONS:
                    for cohort in ('共通60分','期間別全有効'):
                        chosen=[r for r in sessions if r['銘柄']==symbol and (market=='全場' or r['場']==market)
                            and r['方向区分']==side and r['期間分']==minutes and r['標本']==cohort]
                        active=[r for r in chosen if r['評価数']]
                        group=dict(銘柄=symbol,場=market,方向区分=side,期間分=minutes,標本=cohort,
                            全セッション数=len(chosen),評価セッション数=len(active),欠測セッション数=len(chosen)-len(active),
                            実初回数=sum(r['実初回数'] for r in chosen),評価数=sum(r['評価数'] for r in chosen),
                            期限不足数=sum(r['期限不足数'] for r in chosen),
                            正平均セッション数=sum(r['平均変化ATR']>0 for r in active),負平均セッション数=sum(r['平均変化ATR']<0 for r in active))
                        for column in ('平均変化ATR','平均最大順行ATR','平均最大逆行ATR','順方向率'):
                            group['場等重み'+column]=float(np.mean([r[column] for r in active])) if active else None
                        group['最大到達遅れ秒']=max(r['最大到達遅れ秒'] for r in active) if active else None
                        groups.append(group)
    assert len(sessions)==624 and len(groups)==144
    save_csv(OUT/'実初回全件と先行価格.csv',events)
    save_csv(OUT/'実初回セッション別.csv',sessions)
    save_csv(OUT/'実初回場別銘柄別.csv',groups)
    save_json(OUT/'実初回先行価格診断.json',dict(全合格=True,実初回数=counts,評価行数=len(events),
        セッション別=sessions,層別=groups,有効評価の別式照合数=independent_checks,
        固定SHA256=sha(OUT/'実初回診断の事前固定.json'),元退出を評価終端に使わない=True,
        口座利益ではない=True,新ナイト読取=False,API取得数=0))
    for path,digest in fixed['参照SHA256'].items():
        assert sha(ROOT/path)==digest,path
    print(json.dumps(dict(全合格=True,初回数=counts,評価行数=len(events),有効評価の別式照合数=independent_checks),ensure_ascii=False),flush=True)


if __name__=='__main__':
    run()
