"""結果未読の小構造資料で共通入口、busy対応、料金、赤字分母を固定する。"""

import copy
import hashlib
import json
from pathlib import Path
import analysis


HERE=Path(__file__).resolve().parent


def point(row: int, value: float=0., side: int=1) -> dict:
    """
    機能: 保存観測点と同じ型を持つ明示人工の価格時計/原seqを作る。
    引数: row(int)、value(float)、side(int) は位置・親局所清算・影方向。
    返り値: dict は有限正常点。実市場の時刻又は価格を読み込まない。
    """
    return dict(normal_row=row,raw_seq=row*2+1,raw_index=row*2,
        price_time_s=1790910000.+row,Last=4000.,bid=4000.,ask=4000.5,normal=True,
        parent_liquidation_yen=value,parent_peak_yen=max(0.,value),paper_parent=7,paper_direction=side,
        own_count=2,own_balance=float(side),peer_known=True,peer_count=3,peer_balance=float(side),
        peer_row=row-1,peer_raw_seq=(row-1)*2+1,peer_price_age_seconds=.5)


def parent(session: str, symbol: str, cid: int, pub: int, end: int,
           move: float, paper: int=7, kind: int=0, side: int=1) -> tuple:
    """
    機能: 初回全量/一返済の人工完結親を、実料と価格式から作る。
    引数: session/symbol(str)、cid/pub/end/paper/kind/side(int)、move(float)。
    返り値: tuple は保存小親と十四列origin。金融engineを運転しない。
    """
    q=analysis.CAP[symbol];base=4000. if symbol=='TOPIX' else 65000.;tick=.5 if symbol=='TOPIX' else 10.
    entryprice=base+tick if side>0 else base;exitprice=entryprice+side*move*tick
    charge=analysis.fee(q,symbol);net=side*(exitprice-entryprice)*q*analysis.MULT[symbol]-2*charge
    peak=max(1000.,net);minimum=min(-tick*q*analysis.MULT[symbol]-2*charge,net)
    def event(row: int, source: int, price: float, reason: int) -> dict:
        """
        機能: 人工の判断/約定を別観測点として保存する。
        引数: row/source/reason(int)、price(float) は注文行・判断行・理由・約定価格。
        返り値: dict は実料と観測点を持つ人工注文。
        """
        return dict(row=row,source_row=source,price=price,quantity=q,fee_yen=charge,reason=reason,
            reason_label='明示人工',判断=point(source),約定=point(row,net if reason!=90 else minimum))
    entry=event(pub+1,pub,entryprice,90);exit_event=event(end,end-1,exitprice,140)
    p=dict(session=session,symbol=symbol,parent=cid,paper_parent=paper,side=side,entry=entry,exits=[exit_event],
        entry_quantity=q,maximum_held_quantity=q,capacity=q,net_yen=net,fees_yen=charge*2,
        notional_yen=entryprice*q*analysis.MULT[symbol],parent_stop_yen=1000.,target_yen=500.,arm_yen=None,
        published_price_cap=entryprice,published_adverse_ticks=0,published_paper_price=base,published_paper_atr=4*tick,
        published_spread=tick,publication_kind=kind,published_own_count=2,published_own_balance=float(side),
        published_peer_count=3,published_peer_balance=float(side),worst_parent_liquidation_yen=minimum,
        best_parent_liquidation_yen=peak,parent_mfe_yen=peak,parent_mae_yen=max(0.,-minimum),
        first_parent_liquidation_argmin=point(pub+1,minimum),first_parent_liquidation_argmax=point(pub+2,peak),
        liquidation_side_mfe_price=tick,liquidation_side_mae_price=-tick,
        holding_price_proxy_seconds=float(end-pub-1),hindsight_only=True)
    origin=[cid,paper,pub+1,pub,side,q,entryprice,p['notional_yen'],0.,base,4*tick,entryprice,0.,cid]
    return p,origin


def fixture() -> tuple:
    """
    機能: 十二case×全33場の小結果schemaを、少数の実親型だけで構成する。
    引数: なし。
    返り値: tuple は明示人工result/fixed。792というcountsは型契約だけで金融実行数ではない。
    """
    sessions=['人工%02d_%s'%(i,'Day' if i%2==0 else 'Night') for i in range(33)]
    configs=[dict(id='E01_PROTECT_'+mode+'_'+exit_id,reentry_id=mode,exit_id=exit_id) for mode in
        ('ORIGIN','PULL','BREAK','ADAPTIVE') for exit_id in ('TARGET','TIGHT_TRAIL','WIDE_TRAIL')]
    source={'人工source':'明示人工'};cases={};profiles={};boundaries={};activity={}
    for c in configs:
        cid=c['id'];own=[];bounds=[];rows=[]
        for session in sessions:
            for s in analysis.CAP:
                group=[];origins=[]
                if session==sessions[0]:
                    p,o=parent(session,s,0 if c['reentry_id']=='ORIGIN' else 8,310,320 if c['reentry_id']=='ORIGIN' else 330,
                        1. if c['reentry_id']=='ORIGIN' else 2.)
                    group.append(p);origins.append(o)
                    if c['reentry_id']=='ORIGIN':p,o=parent(session,s,1,340,350,-1.,paper=8)
                    else:p,o=parent(session,s,9,332,350,0.,kind=1)
                    group.append(p);origins.append(o)
                own.extend(group);bounds.append(dict(session=session,symbol=s,actual_origins=origins,judgments=[]))
                gain=sum(max(0.,p['net_yen']) for p in group);loss=sum(max(0.,-p['net_yen']) for p in group)
                rows.append(dict(session=session,symbol=s,親数=len(group),利益=gain,損失=loss,収支=gain-loss,
                    費用=sum(p['fees_yen'] for p in group)))
        cases[cid]=dict(rows=rows);profiles[cid]=own;boundaries[cid]=bounds;activity[cid]=[]
    fixed=dict(configs=configs,sessions=sessions,source_SHA256=source,case_SHA256={'人工case':'明示人工'})
    value=dict(全合格=True,source開始終端一致=True,configs=configs,sessions=sessions,source_SHA256=source,
        case_SHA256=fixed['case_SHA256'],counts={'既input一読':33,'価格票準備口座':66,'新account金融':792},
        results=cases,actual_parent_diagnostics=profiles,boundary=boundaries,activity=activity)
    return value,fixed


def run() -> None:
    """
    機能: 共通key/五寄与/欠落busy/完結UID/料金/赤字分母と誤対応拒否を固定する。
    引数: なし。
    返り値: None。診断源署名の純人工を新保存。金融結果/packet/台帳/APIは未読。
    """
    source={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob('*.py')}
    value,fixed=fixture();out=analysis.analyze(value,fixed);checks=out['検算件数']
    for cid,by_symbol in out['comparisons_to_same_exit_origin'].items():
        for s,c in by_symbol.items():
            tick=.5 if s=='TOPIX' else 10.;unit=tick*analysis.CAP[s]*analysis.MULT[s]
            assert c['common_count']==c['added_count']==c['removed_count']==1
            assert analysis.near(c['common_entrance_quantity_or_exit_difference_yen'],unit)
            assert c['new_geometry_added_count']==1 and c['later_paper_origin_added_count']==0
            assert c['missing_baseline_entrances'][0]['accepted_to_exit_busy_parent_ids']==[9]
            assert c['common_parent_pairs'][0]['before_parent']==0 and c['common_parent_pairs'][0]['after_parent']==8;checks+=5
    for s in analysis.CAP:
        for cid,m in out['summaries'].items():
            assert m[s]['session_count']==33 and m[s]['no_trade_sessions']==32
            assert m[s]['parent_count']==2 and analysis.near(m[s]['mean_session_net_yen'],m[s]['net_yen']/33);checks+=2
    # ----------------------------------------
    # CIDは同じでも公開原seqが違えば同入口にせず、sideの違いも区別する。
    a=out['parents']['E01_PROTECT_ORIGIN_TARGET'][0];b=copy.deepcopy(a)
    b['entry']['判断']['raw_seq']+=1;assert analysis.entrance_key(a)!=analysis.entrance_key(b);checks+=1
    b=copy.deepcopy(a);b['side']=-b['side'];assert analysis.entrance_key(a)!=analysis.entrance_key(b);checks+=1
    empty=analysis.metric([]);assert empty['mean_parent_net_yen'] is None and empty['parent_count']==0;checks+=1
    unknown=analysis.timestamp(dict(price_time_s=None));assert unknown['JST_price_proxy'] is None;checks+=1
    # ----------------------------------------
    # 不一致会計/非全量/重複公開keyを成功として通さない。
    first=value['configs'][0]['id']
    for kind in range(5):
        bad=copy.deepcopy(value);p=bad['actual_parent_diagnostics'][first][0]
        if kind==0:p['fees_yen']+=1
        elif kind==1:p['entry_quantity']-=1
        elif kind==2:p['net_yen']+=100
        elif kind==3:bad['actual_parent_diagnostics'][first].append(copy.deepcopy(p))
        else:p['entry']['source_row']=p['entry']['row']
        try:analysis.analyze(bad,fixed)
        except AssertionError:checks+=1
        else:raise AssertionError('誤対応人工を拒否しない')
    assert {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob('*.py')}==source
    target=HERE/'共通入口と実料及び再参加差の純人工.json';assert not target.exists()
    target.write_text(json.dumps(dict(全合格=True,確認数=checks,source_SHA256=source,型契約のcase=12,型契約の場=33,
        結果読取=0,packet読取=0,台帳読取=0,新金融=0,API=0),ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('診断純人工合格 '+str(checks)+'確認。実結果未読。')


if __name__=='__main__':run()
