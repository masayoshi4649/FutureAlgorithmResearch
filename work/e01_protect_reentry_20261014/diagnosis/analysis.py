"""保存小結果だけで実親の対応と再参加差を診断し、事後ピークを売買へ戻さない。"""

from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import math


CAP={'TOPIX':10,'NK225':20}
MULT={'TOPIX':1000,'NK225':10}
FEE={'TOPIX':(209,5),'NK225':(11,1)}
JST=timezone(timedelta(hours=9))
WIDE_CLOCK=datetime(2026,10,2,21,29,50,tzinfo=JST).timestamp()


def near(a: float, b: float) -> bool:
    """
    機能: 保存価格の浮動小差だけを許し、金額の誤対応を拒否する。
    引数: a/b(float) は同一定義の保存金額。
    返り値: bool は絶対一万分の一円以内の同値。
    """
    return math.isclose(a,b,rel_tol=0.,abs_tol=.0001)


def timestamp(point: dict) -> dict:
    """
    機能: 保存価格時計に日本日付の表示を加える。受信/応答時計を作らない。
    引数: point(dict) は保存された観測点。
    返り値: dict は元項目と価格時計代理のJST。欠測はNoneを保持する。
    """
    result=dict(point);value=point.get('price_time_s')
    result['JST_price_proxy']=datetime.fromtimestamp(value,JST).isoformat() if value is not None else None
    return result


def entrance_key(parent: dict) -> tuple:
    """
    機能: 実CIDの採番差に依存せず、同一公開入口を対応させる。
    引数: parent(dict) は完結実親の小射影。
    返り値: tuple は場/商品/paper親/公開原seq/side。
    """
    return (parent['session'],parent['symbol'],int(parent['paper_parent']),
            int(parent['entry']['判断']['raw_seq']),int(parent['side']))


def fee(q: int, symbol: str) -> int:
    """
    機能: 各実注文の税込料金を整数分数から独立に求める。
    引数: q(int)、symbol(str) は実注文枚数と商品。
    返り値: int は一注文の円未満切捨て料。
    """
    numerator,denominator=FEE[symbol]
    return q*numerator//denominator


def profile(parent: dict, origin: list, judgments: list[list]) -> dict:
    """
    機能: 実全量一新規/一返済の料金・数量・UID・時点を独立検算して小射影する。
    引数: parent(dict)、origin(list)、judgments(list[list]) は保存親と境界系譜。
    返り値: dict は実親診断。存在しない深板、peer価格又は連続状態は補完しない。
    """
    s=parent['symbol'];entry=parent['entry'];exits=parent['exits'];q=int(parent['entry_quantity'])
    assert q==CAP[s] and parent['maximum_held_quantity']==q and len(exits)==1
    assert entry['quantity']==q and exits[0]['quantity']==q
    assert int(origin[0])==parent['parent'] and int(origin[1])==parent['paper_parent']
    assert int(origin[2])==entry['row'] and int(origin[3])==entry['source_row']
    assert int(origin[4])==parent['side'] and int(origin[5])==q
    assert near(float(origin[6]),entry['price']) and near(float(origin[7]),parent['notional_yen'])
    assert entry['row']>entry['source_row'] and exits[0]['row']>exits[0]['source_row']
    cost=fee(q,s)*2;assert parent['fees_yen']==cost
    assert entry['fee_yen']==fee(q,s)==exits[0]['fee_yen']
    gross=Decimal(parent['side'])*Decimal(q)*Decimal(MULT[s])*(Decimal(str(exits[0]['price']))-Decimal(str(entry['price'])))
    assert near(float(gross-cost),parent['net_yen'])
    assert near(exits[0]['約定']['parent_liquidation_yen'],parent['net_yen'])
    for field,point_field in (('parent_mfe_yen','first_parent_liquidation_argmax'),('worst_parent_liquidation_yen','first_parent_liquidation_argmin')):
        point=parent[point_field];assert point['normal'] and entry['row']<=point['normal_row']<=exits[0]['row']
        assert near(parent[field],point['parent_liquidation_yen'])
    assert near(parent['parent_mae_yen'],max(0.,-parent['worst_parent_liquidation_yen']))
    result=dict(parent)
    result['entry']=dict(entry,判断=timestamp(entry['判断']),約定=timestamp(entry['約定']))
    result['exits']=[dict(e,判断=timestamp(e['判断']),約定=timestamp(e['約定'])) for e in exits]
    for field in ('first_parent_liquidation_argmax','first_parent_liquidation_argmin'):result[field]=timestamp(parent[field])
    result['actual_uid']=int(origin[13]);result['common_entrance_key']=list(entrance_key(parent))
    result['peak_returned_yen']=max(0.,parent['parent_mfe_yen']-parent['net_yen'])
    result['peak_target_ratio']=parent['parent_mfe_yen']/parent['target_yen'] if parent['target_yen'] else None
    result['peak_arm_ratio']=parent['parent_mfe_yen']/parent['arm_yen'] if parent['arm_yen'] else None
    result['published_side_own_balance']=parent['side']*parent['published_own_balance']
    result['published_side_peer_balance']=parent['side']*parent['published_peer_balance']
    result['saved_exit_judgments']=[j for j in judgments if int(j[1])==parent['parent']]
    result['paper_direction_points']=[dict(kind=kind,**timestamp(point)) for kind,point in
        [('実新規',entry['約定']),('最大純清算',parent['first_parent_liquidation_argmax']),
         ('最小純清算',parent['first_parent_liquidation_argmin']),('退出判断',exits[0]['判断']),('実返済',exits[0]['約定'])]]
    result['paper_direction_scope']='保存された観測点と制御判断だけ。連続全paper更新又は相手板価格は未収録。'
    return result


def metric(parents: list[dict]) -> dict:
    """
    機能: 完結実親netの正負と、実保有中ピークを別の分母で集計する。
    引数: parents(list[dict]) は同商品/同条件又は分類群。
    返り値: dict は金額/件数。ピークは診断限定で救済利益へ換算しない。
    """
    gain=sum(max(0.,p['net_yen']) for p in parents);loss=sum(max(0.,-p['net_yen']) for p in parents)
    negatives=[p for p in parents if p['net_yen']<0]
    return dict(parent_count=len(parents),profit_yen=gain,loss_yen=loss,net_yen=gain-loss,
        positive_parents=sum(p['net_yen']>0 for p in parents),negative_parents=len(negatives),
        flat_parents=sum(p['net_yen']==0 for p in parents),mean_parent_net_yen=(gain-loss)/len(parents) if parents else None,
        negative_once_positive=sum(p['parent_mfe_yen']>0 for p in negatives),negative_denominator=len(negatives),
        nonnegative_mfe_sum_yen=sum(max(0.,p['parent_mfe_yen']) for p in parents),
        peak_returned_sum_yen=sum(p['peak_returned_yen'] for p in parents),
        exit_reasons=dict(Counter(str(p['exits'][0]['reason']) for p in parents)))


def comparison(before: list[dict], after: list[dict]) -> dict:
    """
    機能: 同出口ORIGINと再参加を同一公開入口で対応し、全差額を五つへ分解する。
    引数: before/after(list[dict]) は同商品/同範囲の完結実親。
    返り値: dict は共通親差、避け損失/失った利益、追加参加、欠けた入口の留保。
    """
    old={entrance_key(p):p for p in before};new={entrance_key(p):p for p in after}
    assert len(old)==len(before) and len(new)==len(after)
    joined=old.keys()&new.keys();removed=old.keys()-new.keys();added=new.keys()-old.keys()
    avoid=sum(-old[k]['net_yen'] for k in removed if old[k]['net_yen']<0)
    missed=sum(old[k]['net_yen'] for k in removed if old[k]['net_yen']>0)
    difference=sum(new[k]['net_yen']-old[k]['net_yen'] for k in joined)
    extra=sum(new[k]['net_yen'] for k in added);total=sum(p['net_yen'] for p in after)-sum(p['net_yen'] for p in before)
    assert near(total,avoid-missed+difference+extra)
    missing=[]
    for key in sorted(removed):
        p=old[key];row=p['entry']['source_row']
        busy=[n for n in after if n['session']==p['session'] and n['symbol']==p['symbol'] and
              n['entry']['source_row']<=row<n['exits'][0]['row']]
        missing.append(dict(common_entrance_key=list(key),baseline_parent=p['parent'],net_yen=p['net_yen'],
            publication=timestamp(p['entry']['判断']),accepted_to_exit_busy_parent_ids=[n['parent'] for n in busy],
            interpretation='他の保存済み実親の受理～返済のbusy区間に該当。' if busy else
                '小結果だけでは個別の拒否/失効原因を特定できない。場の理由集計を当該親へ流用しない。'))
    return dict(net_difference_yen=total,avoided_baseline_loss_yen=avoid,missed_baseline_profit_yen=missed,
        common_entrance_quantity_or_exit_difference_yen=difference,new_entrance_net_yen=extra,
        common_count=len(joined),removed_count=len(removed),added_count=len(added),
        new_geometry_added_count=sum(new[k]['publication_kind']!=0 for k in added),
        later_paper_origin_added_count=sum(new[k]['publication_kind']==0 for k in added),
        missing_baseline_entrances=missing,
        common_parent_pairs=[dict(common_entrance_key=list(k),before_parent=old[k]['parent'],after_parent=new[k]['parent'],
            before_net_yen=old[k]['net_yen'],after_net_yen=new[k]['net_yen'],
            before_exit=old[k]['exits'][0],after_exit=new[k]['exits'][0]) for k in sorted(joined)],
        added_parents=[new[k] for k in sorted(added)],
        limitation='同入口の出口差と参加集合/場停止の差を分離する。合計差を出口改善だけとは呼ばない。')


def analyze(value: dict, fixed: dict) -> dict:
    """
    機能: 十二条件の保存小結果を一目的射影し、赤字上位場と10/2Nightを対応比較する。
    引数: value/fixed(dict) は一読結果と事前固定。原input/台帳へ接続しない。
    返り値: dict は検算済み小診断。事後極値は出口採否へ使用しない。
    """
    assert value['全合格'] and value['source開始終端一致']
    assert value['source_SHA256']==fixed['source_SHA256'] and value['case_SHA256']==fixed['case_SHA256']
    assert value['configs']==fixed['configs'] and value['sessions']==fixed['sessions'] and len(value['configs'])==12
    assert value['counts']=={'既input一読':33,'価格票準備口座':66,'新account金融':792}
    configs={c['id']:c for c in value['configs']};sessions=value['sessions'];parents={};summaries={};details={};special={};checks=0
    for cid,config in configs.items():
        rows=value['results'][cid]['rows'];assert len(rows)==66
        assert len({(r['session'],r['symbol']) for r in rows})==66
        boundaries={(r['session'],r['symbol']):r for r in value['boundary'][cid]};assert len(boundaries)==66
        parents[cid]=[]
        for p in value['actual_parent_diagnostics'][cid]:
            boundary=boundaries[p['session'],p['symbol']]
            origins=[v for v in boundary['actual_origins'] if int(v[0])==p['parent']];assert len(origins)==1
            parents[cid].append(profile(p,origins[0],boundary['judgments']));checks+=1
        assert len({entrance_key(p) for p in parents[cid]})==len(parents[cid])
        for row in rows:
            group=[p for p in parents[cid] if p['session']==row['session'] and p['symbol']==row['symbol']]
            m=metric(group);assert len(group)==row['親数']
            assert near(m['net_yen'],row['収支']) and near(m['profit_yen'],row['利益']) and near(m['loss_yen'],row['損失'])
            assert sum(p['fees_yen'] for p in group)==row['費用'];checks+=1
        summaries[cid]={};details[cid]={};special[cid]=[]
        for s in CAP:
            own=[p for p in parents[cid] if p['symbol']==s];rr=[r for r in rows if r['symbol']==s]
            assert len(rr)==len(sessions)==33
            m=metric(own);m.update(mean_session_net_yen=m['net_yen']/33,session_count=33,
                active_sessions=sum(r['親数']>0 for r in rr),red_sessions=sum(r['収支']<0 for r in rr),
                no_trade_sessions=sum(r['親数']==0 for r in rr),directional={str(side):metric([p for p in own if p['side']==side]) for side in (1,-1)},
                day_night={kind:metric([p for p in own if p['session'].endswith('_'+kind)]) for kind in ('Day','Night')})
            summaries[cid][s]=m
            worst=sorted((r for r in rr if r['収支']<0),key=lambda r:(r['収支'],r['session']))[:3]
            details[cid][s]=dict(worst_three_red_sessions=[dict(row=r,parents=[p for p in own if p['session']==r['session']]) for r in worst],
                maximum_negative_parent=min((p for p in own if p['net_yen']<0),key=lambda p:(p['net_yen'],p['session'],p['parent']),default=None))
        for p in parents[cid]:
            if p['session']=='2026-10-02_Night' and p['symbol']=='TOPIX' and p['side']==1:
                entry_clock=p['entry']['約定']['price_time_s'];exit_clock=p['exits'][0]['約定']['price_time_s']
                classification=('参照広幅時計より後に実新規' if entry_clock>WIDE_CLOCK else
                    '参照広幅時計より前に実返済' if exit_clock<WIDE_CLOCK else
                    '参照広幅時計と同価格時計で実返済。物理先後は未証明' if exit_clock==WIDE_CLOCK else '参照広幅時計を跨いで実保有')
                special[cid].append(dict(parent=p,wide_reference_JST='2026-10-02T21:29:50+09:00',classification=classification,
                    limitation='00107で確認した時計との価格代理上の比較。新政策が当該瞬間に見た未保存BBOを補完しない。'))
    comparisons={}
    for cid,config in configs.items():
        if config['reentry_id']=='ORIGIN':continue
        baseline='E01_PROTECT_ORIGIN_'+config['exit_id']
        comparisons[cid]={s:comparison([p for p in parents[baseline] if p['symbol']==s],[p for p in parents[cid] if p['symbol']==s]) for s in CAP}
    return dict(全合格=True,source_SHA256=value['source_SHA256'],case_SHA256=value['case_SHA256'],検算件数=checks,
        summaries=summaries,comparisons_to_same_exit_origin=comparisons,worst_details=details,
        topix_20261002_night_buy=special,parents=parents,activity=value['activity'],
        limitations=['実CID/UIDは各政策内。共通入口は場/商品/paper親/公開原seq/sideで対応。',
            '価格更新票はLast方向代理で旧volume票とは別。相手時計はstrict PriceTime模型で物理受信順未証明。',
            'MFE/MAEはその政策の実保有範囲だけの事後診断。仮想救済利益/事後採否条件へ使わない。',
            '個別拒否と一回FAK失効の全publication配列は小結果に未保存。activityの場集計だけで欠落理由を断定しない。'])
