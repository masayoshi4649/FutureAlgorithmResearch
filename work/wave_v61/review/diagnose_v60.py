"""前回台帳を持越し・実保有時間・価格差・費用・損失集中に分けて記述診断する。"""

from __future__ import annotations

from datetime import datetime,timedelta
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

HERE=Path(__file__).resolve().parent
OLD=HERE.parents[1]/'wave_v60'
BINS=(0,5,15,30,60,120,240,float('inf'))
LABELS=('5分未満','5〜15分','15〜30分','30〜60分','60〜120分','120〜240分','240分以上')


def stats(rows: list) -> dict:
    """機能: 玉の費用後損益・保有時間と損失集中を集計する。

    引数: rows(list[dict])。返り値: 集計(dict)。事後分類を入口の予知条件にしない。
    """
    net=np.asarray([r['net'] for r in rows]);qty=np.asarray([r['qty'] for r in rows]);hold=np.asarray([r['hold'] for r in rows])
    profit=float(net[net>0].sum());loss=float(-net[net<0].sum())
    winq=float(qty[net>0].sum());lossq=float(qty[net<0].sum())
    worst=np.sort(-net[net<0])[::-1]
    meanwin=profit/winq if winq else None;meanloss=loss/lossq if lossq else None
    gross=sum(r['gross'] for r in rows);fees=sum(r['fees'] for r in rows);spread=sum(r['spread'] for r in rows)
    assert abs(gross-fees-net.sum())<1e-5
    return dict(返済玉組=len(rows),延べ枚数=int(qty.sum()),勝ち組=int((net>0).sum()),負け組=int((net<0).sum()),
                勝率=float((net>0).mean()) if len(rows) else None,利益=profit,損失=loss,純収支=float(net.sum()),
                粗収支=float(gross),手数料=float(fees),同注文の気配中値差=float(spread),同注文を中値とした粗収支=float(gross+spread),
                同注文を中値とした費用後収支=float(net.sum()+spread),
                平均勝ち一枚=meanwin,平均負け一枚=meanloss,平均勝負比=meanwin/meanloss if meanwin is not None and meanloss else None,
                保有中央値分=float(np.median(hold)) if len(rows) else None,保有平均分=float(hold.mean()) if len(rows) else None,
                最大負け=float(worst[0]) if len(worst) else 0.,最大3負け=float(worst[:3].sum()),最大10負け=float(worst[:10].sum()),
                最大3負けの損失比=float(worst[:3].sum()/loss) if loss else None,
                最大10負けの損失比=float(worst[:10].sum()/loss) if loss else None)


def divisions(rows: list) -> dict:
    """機能: 終了後に確定する保有時間・場跨ぎ・返済理由を診断用に分解する。

    引数: rows(list)。返り値: 分類集計(dict)。勝てた時間だけへ入口を絞る用途ではない。
    """
    return dict(全体=stats(rows),場内玉=stats([r for r in rows if not r['carry']]),
                持越し玉=stats([r for r in rows if r['carry']]),
                保有時間={label:stats([r for r in rows if lower<=r['hold']<upper]) for label,lower,upper in zip(LABELS,BINS,BINS[1:])},
                返済理由={str(reason):stats([r for r in rows if r['reason']==reason]) for reason in sorted({r['reason'] for r in rows})},
                格子玉=stats([r for r in rows if r['role']==0]),カバー玉=stats([r for r in rows if r['role']==1]))


def week(session: str) -> str:
    """機能: 場開始日から週の月曜を求める。

    引数: session(str)。返り値: 週開始日(str)。
    """
    date=datetime.fromisoformat(session[:10]);return (date-timedelta(days=date.weekday())).date().isoformat()


def main() -> None:
    """機能: 保存検証の主5＋5方式と固定条件の場内対照を再集計して証拠を保存する。

    引数: なし。返り値: なし(None)。新再生・外部取得・旧成果変更は行わない。
    """
    sources={b:OLD/b/'売買結果.json' for b in ('medium','grid')}
    inputs=pickle.loads((OLD/'inputs.pkl').read_bytes());quotes=pickle.loads((OLD/'quotes.pkl').read_bytes())
    mids={}
    for symbol in ('TOPIX','NK225'):
        for w in sorted({week(k[0]) for k in inputs}):
            keys=sorted(k for k in inputs if k[1]==symbol and week(k[0])==w)
            mids[(symbol,w)]=np.concatenate([quotes[k]['mid'] for k in keys])
    diagnostic={};counterparts=[];durations=[]
    for branch,path in sources.items():
        data=json.loads(path.read_text(encoding='utf-8'));methods=data['methods'];byid={m['id']:m for m in methods}
        chosen=[m for m in methods if m['primary']]
        diagnostic[branch]={}
        for m in chosen:
            result={}
            for symbol in ('TOPIX','NK225'):
                rows=[];multiplier=1000 if symbol=='TOPIX' else 10
                for a in m['accounts']:
                    if a['symbol']!=symbol or (branch=='medium' and a['price_mode']!='quote'):continue
                    for tr in a['trades']:
                        if branch=='grid':
                            side,qty=tr[3],tr[4];entry_i,exit_i=int(tr[7]),int(tr[8]);mid=mids[(symbol,a['week'])]
                            spread=side*qty*((tr[13]-mid[entry_i])+(mid[exit_i]-tr[14]))*multiplier
                            record=dict(net=tr[18],gross=tr[15],fees=tr[16]+tr[17],hold=tr[22],qty=qty,spread=spread,
                                        carry=tr[11]!=tr[12],reason=int(tr[19]),role=int(tr[2]))
                        else:
                            side,qty=tr[2],tr[3];entry_i,exit_i=int(tr[19]),int(tr[20]);mid=quotes[(a['session'],symbol)]['mid']
                            spread=side*qty*((tr[4]-mid[entry_i])+(mid[exit_i]-tr[5]))*multiplier
                            record=dict(net=tr[8],gross=tr[6],fees=tr[7],hold=tr[17],qty=qty,spread=spread,
                                        carry=False,reason=int(tr[9]),role=0)
                        assert spread>=-1e-8;rows.append(record)
                result[symbol]=divisions(rows)
                assert abs(result[symbol]['全体']['純収支']-m['summary'][symbol]['net'])<1e-5
                if branch=='grid':
                    match=byid[m['id'].replace('_W_quote','_S_quote')]
                    week_stats=m['summary'][symbol];session_stats=match['summary'][symbol]
                    counterparts.append(dict(方式=m['family'],銘柄=symbol,週内ID=m['id'],場内ID=match['id'],
                        週内収支=week_stats['net'],場内収支=session_stats['net'],差=session_stats['net']-week_stats['net'],
                        週内DD=week_stats['drawdown'],場内DD=session_stats['drawdown'],
                        週内料金=week_stats['fees'],場内料金=session_stats['fees'],
                        週内返済玉=week_stats['cycles'],場内返済玉=session_stats['cycles']))
            diagnostic[branch][m['id']]=result
        if branch=='medium':
            for m in methods:
                if m['config']['minutes']!=30:continue
                base=m['id'].rsplit('_T',1)[0]
                for symbol in ('TOPIX','NK225'):
                    durations.append(dict(基礎条件=base,銘柄=symbol,
                        期限={str(minutes):{key:byid[base+f'_T{minutes}']['summary'][symbol][key] for key in
                             ('net','fees','cycles','drawdown','hold_median_minutes','payoff')} for minutes in (30,45,60)}))
    result=dict(目的='前回台帳の記述診断。未来の保有時間・勝敗分類を新しい入口条件へ流用しない。',
                対象='既知25場。事前主条件10方式と、それと他条件を揃えた場内型/期限対照。',
                価格差='気配の実注文時刻・数量を固定して中値との差だけを計算。別売買経路となる独立中値再生とは異なる。',
                因果の限定='持越し分類や保有時間帯の成績は終了後の分類。場内型との差も後続新規・中心移動が変わるため純粋な持越し効果ではない。',
                主条件の分解=diagnostic,同条件の週内場内比較=counterparts,同条件の期限比較=durations,
                元結果SHA256={b:hashlib.sha256(p.read_bytes()).hexdigest() for b,p in sources.items()},
                追加API=0,新売買再生=0,旧成果変更=False)
    HERE.mkdir(parents=True,exist_ok=True)
    (HERE/'前回台帳の性質診断.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'完了':True,'主方式':sum(len(v) for v in diagnostic.values()),'週内場内対照':len(counterparts),'期限対照':len(durations)},ensure_ascii=False))


if __name__=='__main__':main()
