"""実結果を使わず、注文・親・脚と全場/除外後分母を独立算術へ照合する。"""

from copy import deepcopy
from decimal import Decimal, ROUND_FLOOR
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
import traceback

HERE=Path(__file__).resolve().parent
TARGET=HERE.parents[1]/'metrics'
PROOF=HERE/'注文別料と親脚金額及び全場三基準の独立SOURCE_ONLY確認.json'
FIELDS=['row','source_row','parent','uid','target_uid','side','q','price','new','reason','fee','raw_seq','source_raw_seq']


def sha(path: Path) -> str:
    """
    機能: 監査対象二sourceと私有検査源の指紋を求める。
    引数: path(Path) はsource又は新証跡。
    返り値: str はSHA256。データ・結果は開かない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fee(q: int,symbol: str) -> int:
    """
    機能: 各実注文料金をDecimalで独立にfloorする。
    引数: q(int)、symbol(str) は注文量と商品。
    返り値: int は円料。分割注文を合算しない。
    """
    return int((Decimal(q)*Decimal('41.8' if symbol=='TOPIX' else '11')).to_integral_value(rounding=ROUND_FLOOR))


def make_account(symbol: str,side: int,parts: tuple[int,...],moves: tuple[int,...]) -> dict:
    """
    機能: 二つの独立実親を注文から手計算して合成する。
    引数: symbol(str)、side(int)、parts/moves(tuple[int,...]) は一親目の返済量と値幅。
    返り値: dict はnative互換の完了口座。新規/返済の会計だけから構築する。
    """
    cap=10 if symbol=='TOPIX' else 20;mult=1000 if symbol=='TOPIX' else 10
    tick=Fraction(1,2) if symbol=='TOPIX' else Fraction(10);base=Fraction(4000 if symbol=='TOPIX' else 70000)
    assert sum(parts)==cap and len(parts)==len(moves)
    orders=[];parents=[];legs=[];total_fee=0;cash=Fraction()
    for k,(amounts,steps,sd) in enumerate(((parts,moves,side),((cap,),(4,),-side))):
        cid=7+k;uid=30+k;entry_row=1 if k==0 else 15;entry=base+10*k*tick
        entry_fee=fee(cap,symbol);total_fee+=entry_fee;gross_sum=Fraction();exit_cost=0
        orders.append([entry_row,entry_row-1,cid,uid,-1,sd,cap,float(entry),1,90,entry_fee,100+entry_row,99+entry_row])
        for j,(q,delta) in enumerate(zip(amounts,steps)):
            row=entry_row+2+j;price=entry+sd*delta*tick;cost=fee(q,symbol)
            gross=sd*(price-entry)*q*mult;allocation=Fraction(entry_fee*q,cap);net=gross-allocation-cost
            orders.append([row,row-1,cid,-1,uid,-sd,q,float(price),0,143 if j==0 and len(amounts)>1 else 142,cost,100+row,99+row])
            legs.append(dict(parent=cid,uid=uid,side=sd,q=q,entry_row=entry_row,exit_row=row,
                entry_price=float(entry),exit_price=float(price),gross_yen=float(gross),
                entry_fee_allocated=float(allocation),exit_fee=cost,net_yen=float(net)))
            gross_sum+=gross;exit_cost+=cost;total_fee+=cost
        net=gross_sum-entry_fee-exit_cost;cash+=net
        parents.append(dict(parent=cid,uid=uid,side=sd,quantity=cap,entry_row=entry_row,exit_row=entry_row+1+len(amounts),
            entry_price=float(entry),gross_yen=float(gross_sum),fee_yen=entry_fee+exit_cost,net_yen=float(net),
            粗損益=float(gross_sum),費用=entry_fee+exit_cost,収支=float(net)))
    pnl=[Fraction(str(p['net_yen'])) for p in parents]
    summary=dict(利益=float(sum((v for v in pnl if v>0),Fraction())),損失=float(-sum((v for v in pnl if v<0),Fraction())),
        収支=float(cash),親数=len(parents),勝ち親=sum(v>0 for v in pnl),負け親=sum(v<0 for v in pnl),零親=sum(v==0 for v in pnl),
        費用=total_fee,新規枚数=cap*2,勝ち枚数=sum(v['q'] for v in legs if v['net_yen']>0),
        負け枚数=sum(v['q'] for v in legs if v['net_yen']<0),零枚数=sum(v['q'] for v in legs if v['net_yen']==0),全会計合格=True)
    return dict(completed=True,finish=True,orders=orders,order_fields=list(FIELDS),parent=parents,actual_legs=legs,summary=summary,
        final_state=dict(held_quantity=0,pending_new=0,reserved_quantity=0,exit_queue_count=0,force_observed=1,cash_yen=float(cash),paid_fee_yen=total_fee))


def population(symbol: str,sessions: list[str],values: list[list[int]]) -> tuple[list[dict],list[dict],list[dict]]:
    """
    機能: 任意の親netから期間集計専用の合成場・親・脚を作る。
    引数: symbol(str)、sessions(list[str])、values(list[list[int]]) は固定分母と各場親net。
    返り値: tuple はrows/parents/legs。市場で実現した経路ではなく指標境界の人工。
    """
    assert len(sessions)==len(values);rows=[];parents=[];legs=[];cap=10 if symbol=='TOPIX' else 20
    for session,pnl in zip(sessions,values):
        rows.append(dict(symbol=symbol,session=session,利益=sum(max(v,0) for v in pnl),損失=-sum(min(v,0) for v in pnl),
            収支=sum(pnl),親数=len(pnl),勝ち枚数=cap*sum(v>0 for v in pnl),負け枚数=cap*sum(v<0 for v in pnl),零枚数=cap*sum(v==0 for v in pnl)))
        for cid,net in enumerate(pnl):
            side=1 if cid%2==0 else -1
            parents.append(dict(symbol=symbol,session=session,parent=cid,net_yen=net,side=side))
            legs.append(dict(symbol=symbol,session=session,parent=cid,net_yen=net,side=side,q=cap))
    return rows,parents,legs


def reference(rows: list[dict],parents: list[dict],symbol: str) -> dict:
    """
    機能: 全場平均と三基準を親金額・場netの厳密分数だけで独立計算する。
    引数: rows/parents(list[dict])、symbol(str) は同一期間。
    返り値: dict は照合すべき主指標。無取引を勝ちへ数えない。
    """
    nets=[Fraction(str(r['収支'])) for r in rows];pp=[Fraction(str(p['net_yen'])) for p in parents]
    profit=sum((p for p in pp if p>0),Fraction());loss=-sum((p for p in pp if p<0),Fraction())
    positives=[v for v in nets if v>0];negatives=[-v for v in nets if v<0];n=len(rows)
    active=sum(r['親数']>0 for r in rows);winmean=sum(positives,Fraction())/len(positives) if positives else None
    worst=max([Fraction()]+negatives);share=profit/(profit+loss) if profit+loss else None
    classical=share is not None and share>=Fraction(13,20) and Fraction(len(negatives),n)<=Fraction(1,5) and winmean is not None and worst<=winmean
    return dict(mean_session_net_yen=float(sum(nets,Fraction())/n),session_count=n,active_sessions=active,
        no_trade_sessions=n-active,flat_active_sessions=active-len(positives)-len(negatives),positive_sessions=len(positives),losing_sessions=len(negatives),
        red_full_rate=len(negatives)/n,red_active_rate=len(negatives)/active if active else None,
        mean_positive_session_net_yen=float(winmean) if winmean is not None else None,worst_negative_session_abs_yen=float(worst),
        target65=share is not None and share>=Fraction(13,20),target_red20=Fraction(len(negatives),n)<=Fraction(1,5),
        target_worst_mean=winmean is not None and worst<=winmean,all_stability_targets=classical,
        target_floor_yen=100000 if symbol=='TOPIX' else None,
        target_mean_success=sum(nets,Fraction())/n>=100000 if symbol=='TOPIX' else None,
        all_main_targets=classical and (symbol!='TOPIX' or sum(nets,Fraction())/n>=100000))


def main() -> None:
    """
    機能: 対象sourceを変更せず独立会計と期間基準を合成検証して小証跡を保存する。
    引数: なし。
    返り値: None。既結果・原NPZ・cache・金融・APIは使わない。
    """
    assert not PROOF.exists() and not (HERE/'False.json').exists()
    bound={n:sha(TARGET/n) for n in ('metrics.py','artificial_metrics.py')}
    spec=importlib.util.spec_from_file_location('数量実約定の独立金額対象',TARGET/'metrics.py')
    metrics=importlib.util.module_from_spec(spec);spec.loader.exec_module(metrics)
    checks=0;account_count=0;scenario_count=0;refusals=0;examples=[]
    try:
        for symbol in ('TOPIX','NK225'):
            for q in range(1,101):assert metrics.fee(q,symbol)==fee(q,symbol);checks+=1
            cap=10 if symbol=='TOPIX' else 20
            for side in (-1,1):
                for parts,moves in (((cap,),(2,)),((cap//2,cap//2),(2,-2)),((1,2,cap-3),(3,-1,0))):
                    daily=make_account(symbol,side,parts,moves);row=metrics.account(symbol,'2026-10-01_Day',daily)
                    for key in daily['summary']:
                        if key in row:assert row[key]==daily['summary'][key];checks+=1
                    assert row['粗損益']==sum(p['gross_yen'] for p in daily['parent']);checks+=1
                    account_count+=1
                    examples.append(dict(symbol=symbol,side=side,parts=list(parts),net=row['収支'],profit=row['利益'],loss=row['損失'],
                        win_quantity=row['勝ち枚数'],loss_quantity=row['負け枚数'],fee=row['費用']))
            daily=make_account(symbol,1,(cap//2,cap//2),(2,-2))
            for category in ('fee','parentnet','legnet','quantity','cash','completed','summary'):
                bad=deepcopy(daily)
                if category=='fee':bad['orders'][1][10]+=1
                elif category=='parentnet':bad['parent'][0]['net_yen']+=1
                elif category=='legnet':bad['actual_legs'][0]['net_yen']+=1
                elif category=='quantity':bad['actual_legs'][0]['q']+=1
                elif category=='cash':bad['final_state']['cash_yen']+=1
                elif category=='completed':bad['completed']=False
                else:bad['summary']['親数']=True
                try:metrics.account(symbol,'2026-10-01_Day',bad)
                except AssertionError:refusals+=1
                else:raise AssertionError(category+'を受理')
        sessions=[f'2026-10-{i//2+1:02d}_'+('Day' if i%2==0 else 'Night') for i in range(33)]
        scenarios=[('全無取引',[[] for _ in sessions]),('一勝32無',[[100]]+[[] for _ in sessions[1:]]),
            ('平均10万等号',[[100000] for _ in sessions]),('平均10万の1円未満下',[[99999]]+[[100000] for _ in sessions[1:]]),
            ('金額65等号',[[13,-7]]+[[] for _ in sessions[1:]]),('金額65直下',[[1299999,-700001]]+[[] for _ in sessions[1:]]),
            ('赤6場',[[1000] for _ in range(27)]+[[-1000] for _ in range(6)]),
            ('赤7場',[[1000] for _ in range(26)]+[[-1000] for _ in range(7)]),
            ('親利益と場netの混同防止',[[9000,-8000],[1000],[-2000]]+[[] for _ in range(30)]),
            ('活動flatと無取引の別',[[1000,-1000],[0]]+[[] for _ in range(31)]),
            ('上位3同値と残赤字',[[1000000],[1000000],[1000000]]+[[-100] for _ in range(30)]),
            ('上位正が三つ未満',[[100],[-100]]+[[] for _ in range(31)])]
        for symbol in ('TOPIX','NK225'):
            for label,values in scenarios:
                rows,parents,legs=population(symbol,sessions,values);out=metrics.periods(rows,parents,sessions,symbol,legs)
                ranked=sorted((i for i,r in enumerate(rows) if r['収支']>0),key=lambda i:(-rows[i]['収支'],rows[i]['session']))[:3]
                excluded={sessions[i] for i in ranked};assert out['除外場']==[sessions[i] for i in ranked];checks+=1
                groups={'全場':sessions,'前半':sessions[:16],'後半':sessions[16:],
                    'デイ':sessions[::2],'ナイト':sessions[1::2],
                    '上位3黒字場除外':[s for s in sessions if s not in excluded]}
                for name,ids in groups.items():
                    rr=[r for r in rows if r['session'] in ids];pp=[p for p in parents if p['session'] in ids]
                    expected=reference(rr,pp,symbol)
                    assert out[name]['sessions']==ids;checks+=1
                    for key,value in expected.items():assert out[name][key]==value,(label,name,key,out[name][key],value);checks+=1
                for name,side in (('買い',1),('売り',-1)):
                    pp=[p for p in parents if p['side']==side]
                    ll=[l for l in legs if l['side']==side]
                    assert out['方向'][name]['収支']==sum(p['net_yen'] for p in pp);checks+=1
                    assert out['方向'][name]['勝ち枚数']==sum(l['q'] for l in ll if l['net_yen']>0);checks+=1
                if label=='親利益と場netの混同防止':assert out['全場']['mean_positive_session_net_yen']==1000 and not out['全場']['target_worst_mean'];checks+=2
                if label=='活動flatと無取引の別':assert out['全場']['flat_active_sessions']==2 and out['全場']['no_trade_sessions']==31;checks+=2
                scenario_count+=1
            short_sessions=sessions[:5]
            rows,pp,ll=population(symbol,short_sessions,[[1000],[1000],[1000],[1000],[-1000]])
            boundary=metrics.scope(rows,pp,symbol)
            assert boundary['red_full_rate']==.2 and boundary['target_red20'] and boundary['target_worst_mean'];checks+=3
            rows,pp,ll=population(symbol,short_sessions,[[1000],[1000],[1000],[1000],[-1001]])
            assert not metrics.scope(rows,pp,symbol)['target_worst_mean'];checks+=1
        assert bound=={n:sha(TARGET/n) for n in bound}
        proof=dict(全合格=True,source_SHA256=bound,監査sourceSHA256=sha(Path(__file__)),比較数=checks,
            独立合成口座=account_count,期間分母素材=scenario_count,不整合拒否=refusals,合成例=examples,
            独立方法='Decimal注文別floor料・手計算二親・異符号返済脚・Fraction全場とtrim分母。owner人工は読取だけで実行しない。',
            確認='TOP全33平均10万。NK円床None。65%/赤2割/最悪赤vs平均黒は場net。親profit/脚枚数を区別。',
            留保='一勝32無のNK数式合格は活動成功ではない。時間/在庫接頭の本体検査はNative独立監査の範囲。',
            既結果=0,金融結果=0,原入力=0,NPZ=0,cache=0,API=0,金融再生=0,source変更=False)
        PROOF.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps(dict(全合格=True,比較数=checks,不整合拒否=refusals,SHA256=sha(PROOF)),ensure_ascii=False))
    except BaseException:
        (HERE/'False.json').write_text(json.dumps(dict(全合格=False,source_SHA256=bound,比較数=checks,
            原因=traceback.format_exc(),既結果=0,金融=0,NPZ=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise


if __name__=='__main__':
    main()
