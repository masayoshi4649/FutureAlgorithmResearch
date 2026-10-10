"""公平な有限ランダム歩行で、予測なしの注文管理の期待利益を監査する。"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo

import numpy as np

OUT=Path(__file__).resolve().parent
OLD=OUT.parent/'wave_v23'
sys.path.insert(0,str(OLD))
import engine
import managers
import discovery_managers

IDS=('G00','G08','G12','G14','G18','D071','D291','D301')
SEEDS=range(1024)
COUNT=416
TICK=.5


def summary(values: list[float]) -> dict:
    """機能: 独立価格経路ごとの損益を平均・標準誤差・勝率へ集計する。

    引数: values (list[float]) はティック×枚単位。返り値: 集計 (dict)。
    """
    a=np.asarray(values,dtype=float)
    mean=float(a.mean());deviation=float(a.std(ddof=1));error=deviation/np.sqrt(len(a))
    wins=a[a>1e-9];losses=a[a<-1e-9]
    mean_win=float(wins.mean()) if len(wins) else None
    mean_loss=float(-losses.mean()) if len(losses) else None
    return {'経路数':len(a),'平均損益':mean,'標準偏差':deviation,'標準誤差':float(error),
            '平均の近似95%区間':[mean-1.96*error,mean+1.96*error],
            '黒字経路数':len(wins),'赤字経路数':len(losses),'同値経路数':int(np.sum(np.abs(a)<=1e-9)),
            '経路勝率':len(wins)/len(a),'平均勝ち':mean_win,'平均負け':mean_loss,
            '平均勝ち負け比':mean_win/mean_loss if mean_win is not None and mean_loss else None,
            '最悪経路損益':float(a.min()),'最良経路損益':float(a.max())}


def path(seed: int) -> tuple[dict,np.ndarray]:
    """機能: 価格と方向の独立乱数を分離した有限の公平価格経路を作る。

    引数: seed (int)。返り値: エンジン入力・独立ランダム方向 (tuple[dict,ndarray])。
    """
    prices_rng=np.random.default_rng(np.random.SeedSequence([seed,1907]))
    side_rng=np.random.default_rng(np.random.SeedSequence([seed,9301]))
    steps=prices_rng.integers(0,2,size=COUNT-1,dtype=np.int64)*2-1
    price=1000.+TICK*np.r_[0,steps.cumsum()]
    stamps=np.arange(COUNT)*60.
    blocks=np.floor(stamps/1800).astype(int)
    sides=(side_rng.integers(0,2,size=int(blocks[-1])+1,dtype=np.int64)*2-1).astype(np.int8)
    ready={'time_s':stamps,'last':price,'atr':np.full(COUNT,4*TICK),'tick':TICK,
           'start':0.,'limit':410*60.,'us_open':np.inf}
    assert price.min()>0 and np.all(np.abs(np.diff(price))==TICK)
    return ready,sides[blocks]


def verify(result: dict, ready: dict) -> float:
    """機能: 各約定の観測価格一致と、予測可能保有の値洗い恒等式を検査する。

    引数: result/ready (dict)。返り値: 経路損益 (float、ティック×枚)。
    """
    orders=result['orders'];curve=result['curve'];stats=result['stats']
    assert stats[9]==0 and stats[6]<1e-7 and max(stats[2:4])<=10
    assert np.all(orders[:,0]>orders[:,1])
    rows=orders[:,0].astype(int)
    np.testing.assert_allclose(orders[:,5],ready['last'][rows],atol=1e-9)
    previous_net=np.r_[0,curve[:-1,6]]
    changes=np.r_[0,np.diff(ready['last'])]
    gain=(previous_net*changes).cumsum()
    np.testing.assert_allclose(curve[:,0],gain,atol=1e-7)
    np.testing.assert_allclose(stats[0],gain[-1],atol=1e-7)
    np.testing.assert_allclose(result['trades'][:,10].sum(),stats[0],atol=1e-7)
    return float(stats[0]/TICK)


def high_win_reference(ready: dict) -> float:
    """機能: 事前に+1/−4ティックを設定する１枚の単純OCO対照を返す。

    引数: ready (dict)。返り値: 損益 (float、ティック×枚)。
    時刻20分で建て、以降の最初の到達か最終返済時刻で閉じる有限戦略。
    """
    price=ready['last'];entry=20;exit_row=411;entry_price=price[entry]
    for row in range(entry+1,exit_row+1):
        movement=(price[row]-entry_price)/TICK
        if movement>=1 or movement<=-4:
            exit_row=row
            break
    return float((price[exit_row]-entry_price)/TICK)


def main() -> None:
    """機能: 固定した８管理×２方向×1024価格経路を１プロセスで監査する。

    引数: なし。返り値: なし (None)。実相場の成績は読み込まない。
    """
    specs={row['id']:row for row in discovery_managers.catalog() if row['id'] in IDS}
    fixed={'管理ID':list(IDS),'乱数種':list(SEEDS),'価格':'+1/-1ティック等確率・独立増分',
           '観測数':COUNT,'価格刻み':TICK,'ATRティック':4,'観測間隔秒':60,'初期価格':1000,
           '方向':['固定買い','独立30分コイントス'],'片方向上限':10,'銘柄設定':'TOPIXミニ',
           '理論参考':'時刻20分で１枚買い、+1/−4ティックのOCO、未到達なら411分で返済',
           '元管理パラメータ':specs,'実相場成績参照':False,'プロセス数':1}
    freeze_path=OUT/'fair_market_fixed.json'
    if freeze_path.exists():
        assert json.loads(freeze_path.read_text(encoding='utf-8'))['条件']==fixed
    else:
        freeze_path.write_text(json.dumps({'固定時刻':datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),'条件':fixed},
                                          ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    values={(identifier,mode):[] for identifier in IDS for mode in ('固定買い','独立30分コイントス')}
    trade_stats={key:{'勝ち枚数':0,'負け枚数':0,'同値枚数':0,'利益ティック枚':0.,'損失ティック枚':0.}for key in values}
    references=[];started=time.perf_counter();replays=0
    for seed in SEEDS:
        ready,random_side=path(seed)
        references.append(high_win_reference(ready))
        for mode,side in [('固定買い',np.ones(COUNT,dtype=np.int8)),('独立30分コイントス',random_side)]:
            for identifier in IDS:
                cfg=managers.make_config(specs[identifier],'TOPIX',ready)
                result=engine.run(ready,side,cfg,True)
                values[(identifier,mode)].append(verify(result,ready))
                trades=result['trades'];pnl=trades[:,10]/TICK
                wins=pnl>1e-9;losses=pnl<-1e-9;item=trade_stats[(identifier,mode)]
                item['勝ち枚数']+=int(trades[wins,3].sum());item['負け枚数']+=int(trades[losses,3].sum())
                item['同値枚数']+=int(trades[~(wins|losses),3].sum())
                item['利益ティック枚']+=float(pnl[wins].sum());item['損失ティック枚']+=float(-pnl[losses].sum())
                replays+=1
        if (seed+1)%128==0:
            print(f'公平価格 {seed+1}/1024経路、{replays}再生、{time.perf_counter()-started:.1f}秒',flush=True)
    results=[]
    for key,sample in values.items():
        identifier,mode=key;item=trade_stats[key]
        count=item['勝ち枚数']+item['負け枚数']+item['同値枚数']
        item['決済枚数勝率']=item['勝ち枚数']/count if count else None
        item['１枚平均利益']=item['利益ティック枚']/item['勝ち枚数'] if item['勝ち枚数']else None
        item['１枚平均損失']=item['損失ティック枚']/item['負け枚数'] if item['負け枚数']else None
        results.append({'管理':identifier,'管理名':specs[identifier]['name'],'方向':mode,
                        **summary(sample),'決済枚数統計':item,'全経路損益':sample})
    output={'目的':'公平な価格では予測なし・売買以外の入出金なしで正の期待利益は生まれないことを、既存管理器の会計と数値で確認する。',
            '単位':'ティック×枚。実相場の円損益ではない。','設定':fixed,'結果':results,
            '高勝率の理論対照':{'説明':'１枚の+1/−4ティックOCO、有限時間で全返済。期限を設けず先に上側へ到達する理論確率は4/5。有限期限でも期待利益は0。',
                                **summary(references),'全経路損益':references},
            '検算':{'再生数':replays,'約定は観測価格と全件一致':True,'場内全返済':True,'上限遵守':True,
                    '経路毎P&Lと直前保有×価格増分の累積が全行一致':True,'実相場成績未参照':True,'経過秒':time.perf_counter()-started}}
    (OUT/'fair_market_audit.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    lines=['# 公平な価格で注文管理だけに期待利益があるか','',
           '方向予測のない、公平な有限ランダム歩行だけを使った監査。実相場の利益を否定する試験ではない。既存５管理と、新管理から利益保護・増玉２形態を結果を見る前に固定し、各1024価格経路を比較した。',
           '', '単位は **ティック×枚**。価格は毎分±１ティック、固定ATR４ティック。TOPIX側の片方向上限10枚で検査し、全玉を最後までに返済した。費用を追加せず、約定値がその観測価格と全件一致することを確認したため、飛び越し指定値の利益は含まれない。',
           '', '|管理|方向|平均損益|標準誤差|経路勝率|平均勝ち|平均負け|最悪損益|',
           '|---|---|---:|---:|---:|---:|---:|---:|']
    for row in results:
        lines.append(f"|{row['管理']}|{row['方向']}|{row['平均損益']:+.3f}|{row['標準誤差']:.3f}|{row['経路勝率']:.1%}|{row['平均勝ち']:.2f}|{row['平均負け']:.2f}|{row['最悪経路損益']:.1f}|")
    reference=output['高勝率の理論対照']
    lines+=['',f"+1/−4ティックの事前OCO対照は勝率 **{reference['経路勝率']:.1%}**、平均損益 **{reference['平均損益']:+.3f}**、標準誤差 **{reference['標準誤差']:.3f}**。高勝率でも１回の損失が大きく、利益の期待値が正になるとは限らない。",'',
            '## なぜ注文操作だけでは正の期待値にならないか','',
            '時刻t−1までに決めた符号付き保有枚数を q[t−1]、次の価格変化を ΔP[t] とすると、費用なし・売買以外の入出金なしの最終損益は Σ q[t−1]ΔP[t]。公平な価格では、過去と独立な注文乱数を知っても E[ΔP[t]｜その時点の情報]=0 なので、各項の期待値も0になる。',
            '', '今回は保有上限と終了時刻が有限なので、無限の倍賭けや無限の待機による例外は使えない。利確・損切り・部分返済・両建て・増玉は勝率や損失分布を変えるが、この前提の下で正の期待値を生むことはない。全経路の実現損益が、この直前保有×次変化の和と全行で一致した。',
            '', '表の平均は有限乱数標本なので0からずれる。標準誤差と近似95%区間はJSONへ保存し、平均が一番良かった管理を採用し直していない。各管理は同じ価格経路を共有し、行同士が独立した別市場という意味ではない。',
            '', '現実の先物価格がこの公平モデルそのものであるとは仮定していない。実相場の方向性や板情報に予測力があれば、この監査とは前提が異なる。また、どの市況でも利益を保証する方法がないことを全モデルについて実験だけで証明した、という主張でもない。',
            '', '再実行は `python work/wave_v25/fair_market_audit.py`。数値条件は `fair_market_fixed.json`、全経路と決済枚数統計は `fair_market_audit.json`。原本と旧コードは読み取りのみ、外部API取得はしていない。']
    (OUT/'fair_market_audit.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(output['検算'],ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
