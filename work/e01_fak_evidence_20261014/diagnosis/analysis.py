"""FAK票数追加の新旧実親を公開原seqで対応させ、出口差/消失/新参加へ分解する。"""

from collections import Counter
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import math
from statistics import median

CAP={'TOPIX':10,'NK225':20}
MULT={'TOPIX':1000,'NK225':10}
RATE={'TOPIX':(209,5),'NK225':(11,1)}
JST=timezone(timedelta(hours=9))
REASONS={140:'親純利益目標',141:'親純損失停止',142:'親純益保護',151:'紙上全退出/反方向',
    161:'場純損失停止',162:'場純利益停止',92:'予定静観',93:'場内期限'}


def close(a: float,b: float) -> bool:
    """
    機能: float保存金額の微小差だけを許す。
    引数: a/b(float) は同じ金額定義。
    返り値: bool は一万分の一円以内の同値。
    """
    return math.isclose(a,b,rel_tol=0.,abs_tol=.0001)


def point(value: dict) -> dict:
    """
    機能: 保存価格時計を日本日付の代理時刻へ表示する。
    引数: value(dict) は既保存観測点。
    返り値: dict は元項目とJST。欠測/受信時計を補完しない。
    """
    result=dict(value);t=value.get('price_time_s')
    result['JST_price_proxy']=datetime.fromtimestamp(t,JST).isoformat() if t is not None else None
    return result


def decompose(parent: dict,origin: list) -> dict:
    """
    機能: 全量一UID一返済をmid方向−横断不利−料金へ独立検算する。
    引数: parent(dict)、origin(list) は完結親と保存十四列系譜。
    返り値: dict は金額分解と全観測点。気配差を追加費用として再控除しない。
    """
    s=parent['symbol'];q=int(parent['entry_quantity']);side=int(parent['side']);entry=parent['entry'];exits=parent['exits']
    assert q==CAP[s] and len(exits)==1 and parent['maximum_held_quantity']==q
    exit_event=exits[0];assert entry['quantity']==exit_event['quantity']==q and side in (-1,1)
    assert int(origin[0])==parent['parent'] and int(origin[1])==parent['paper_parent'] and int(origin[4])==side and int(origin[5])==q
    assert int(origin[2])==entry['row'] and int(origin[3])==entry['source_row'] and int(origin[13])>=0
    e,x=entry['約定'],exit_event['約定'];assert e['normal'] and x['normal'] and exit_event['reason']!=152
    assert entry['row']>entry['source_row'] and exit_event['row']>exit_event['source_row']
    eb,ea,xb,xa=(Decimal(str(v)) for v in (e['bid'],e['ask'],x['bid'],x['ask']))
    assert 0<eb<ea and 0<xb<xa
    ep=Decimal(str(entry['price']));xp=Decimal(str(exit_event['price']))
    assert ep==(ea if side>0 else eb) and xp==(xb if side>0 else xa)
    factor=Decimal(q*MULT[s]);direction=Decimal(side)*((xb+xa-eb-ea)/2)*factor
    crossing=((ea-eb)+(xa-xb))/2*factor
    numerator,denominator=RATE[s];one_fee=q*numerator//denominator;cost=one_fee*2
    assert entry['fee_yen']==exit_event['fee_yen']==one_fee and parent['fees_yen']==cost
    gross=Decimal(side)*(xp-ep)*factor;net=direction-crossing-cost
    assert gross==direction-crossing and close(float(net),parent['net_yen'])
    assert close(x['parent_liquidation_yen'],parent['net_yen'])
    if net<0:
        label='mid方向が逆行' if direction<0 else 'mid不変で気配差と料負け' if direction==0 else 'mid順行しても気配差と料を回収できない'
    else:label='全費用回収後に黒字' if net>0 else '全費用回収後に零'
    result=dict(parent,actual_uid=int(origin[13]),gross_direction_mid_yen=float(direction),crossing_disadvantage_yen=float(crossing),
        actual_gross_yen=float(gross),order_fees_yen=cost,reconstructed_net_yen=float(net),cause=label,
        entry_spread=float(ea-eb),exit_spread=float(xa-xb),entry_mid=float((ea+eb)/2),exit_mid=float((xa+xb)/2),
        peak_returned_yen=max(0.,parent['parent_mfe_yen']-parent['net_yen']))
    result['entry']=dict(entry,判断=point(entry['判断']),約定=point(e))
    result['exits']=[dict(exit_event,判断=point(exit_event['判断']),約定=point(x),reason_label=REASONS[exit_event['reason']])]
    for field in ('first_parent_liquidation_argmax','first_parent_liquidation_argmin'):result[field]=point(parent[field])
    for where,p in (('publication',entry['判断']),('entry',e),('exit_decision',exit_event['判断']),('exit',x)):
        result[where+'_paper_remaining_quantity']=p['paper_remaining_quantity']
        result[where+'_paper_matches_origin']=p['paper_parent']==parent['paper_parent']
    result['definition']='実約定BBOのmid方向粗−横断不利−各注文実料＝親net。横断不利は約定価格差の分解であり追加二重控除しない。'
    target=parent.get('target_yen');arm=parent.get('arm_yen')
    result['peak_over_target']=parent['parent_mfe_yen']/target if target is not None and target>0 else None
    result['peak_over_arm']=parent['parent_mfe_yen']/arm if arm is not None and arm>0 else None
    return result


def group(parents: list[dict]) -> dict:
    """
    機能: 同分類の方向粗/横断不利/料金を親分母で集計する。
    引数: parents(list[dict]) は同じ定義の分解済み実親。
    返り値: dict は金額/勝負/保有秒/退出理由。事後ピークを利益へ換算しない。
    """
    direction=sum(p['gross_direction_mid_yen'] for p in parents);crossing=sum(p['crossing_disadvantage_yen'] for p in parents)
    fees=sum(p['order_fees_yen'] for p in parents);net=sum(p['net_yen'] for p in parents);assert close(direction-crossing-fees,net)
    neg=[p for p in parents if p['net_yen']<0]
    return dict(parent_count=len(parents),net_yen=net,gross_direction_mid_yen=direction,crossing_disadvantage_yen=crossing,fees_yen=fees,
        positive_parents=sum(p['net_yen']>0 for p in parents),negative_parents=len(neg),flat_parents=sum(p['net_yen']==0 for p in parents),
        causes=dict(Counter(p['cause'] for p in parents)),exit_reasons=dict(Counter(p['exits'][0]['reason_label'] for p in parents)),
        native_price_proxy_holding_median_seconds=median([p['holding_price_proxy_seconds'] for p in parents]) if parents else None,
        negative_once_positive=sum(p['parent_mfe_yen']>0 for p in neg),negative_denominator=len(neg),
        peak_returned_sum_yen=sum(p['peak_returned_yen'] for p in parents))


def entry_information(parent: dict,config: dict) -> dict:
    """
    機能: 実新規親の公開出来高signed票と現在価格資格を保存項目だけで検査する。
    引数: parent/config(dict) は完結実親小射影と固定条件。
    返り値: dict は当該実親の資格。未保存own_knownや候補全体の交差採否を補完しない。
    """
    info=parent['published_entry_information'];v=info['volume'];pub=parent['entry']['判断'];s=parent['symbol'];side=parent['side']
    assert info['entry_id']==config['entry_id'] and info['accepted'] and info['volume_accepted'] and v['known']
    assert v['window_seconds']==60 and v['candidate_raw_seq']==pub['raw_seq'] and v['candidate_raw_row']==pub['raw_index']
    assert v['candidate_price_time_s']==pub['price_time_s']
    count=v['direction_votes'];assert count==v['up_votes']+v['down_votes'] and count>=2
    assert close(v['balance'],side*(v['up_votes']-v['down_votes'])/count)
    assert v['balance']>=config['volume_balance_threshold'][s]
    if config['entry_id']=='VOL25_PRICE_BOTH':assert info['price_accepted']
    tolerance=parent['published_adverse_ticks'];assert tolerance in (0,1)
    return dict(volume=dict(v),volume_accepted=info['volume_accepted'],price_accepted=info['price_accepted'],
        acceptance_class='価格資格も通過' if info['price_accepted'] else '価格資格不通過・出来高資格で実新規',
        published_price_own=dict(known=pub.get('own_known'),count=parent['published_own_count'],
            absolute_balance=parent['published_own_balance'],side_balance=side*parent['published_own_balance'] if parent['published_own_balance'] is not None else None,
            known_scope='own_known単独列は未保存。全体price_acceptedを保存値として使い、未知をFalse又は零へ変換しない。'),
        published_price_peer=dict(known=pub.get('peer_known'),count=parent['published_peer_count'],
            absolute_balance=parent['published_peer_balance'],side_balance=side*parent['published_peer_balance'] if parent['published_peer_balance'] is not None else None,
            raw_seq=pub.get('peer_raw_seq'),price_age_seconds=pub.get('peer_price_age_seconds')),
        adverse_ticks=tolerance,price_cap=parent['published_price_cap'],
        scope='この親は実新規fill済み。資格countは完結実親分母であり公開候補全体の採否数又は勝率ではない。')


def period_summary(rows: list[dict]) -> dict:
    """
    機能: 主金額を全場又は明示範囲の親正負額と場netへ集計する。
    引数: rows(list[dict]) は同商品範囲の全場小会計。
    返り値: dict は正負/無取引/金額比。無活動を勝ちへ数えない。
    """
    gain=sum(r['利益'] for r in rows);loss=sum(r['損失'] for r in rows);net=sum(r['収支'] for r in rows)
    assert close(gain-loss,net)
    active=sum(r['親数']>0 for r in rows)
    return dict(session_count=len(rows),profit_yen=gain,loss_yen=loss,net_yen=net,
        profit_share=gain/(gain+loss) if gain+loss else None,mean_session_net_yen=net/len(rows) if rows else None,
        black=sum(r['収支']>0 for r in rows),red=sum(r['収支']<0 for r in rows),no_trade=len(rows)-active,
        flat_active=active-sum(r['収支']!=0 for r in rows),parent_count=sum(r['親数'] for r in rows))


def saved_comparison(rows: list[dict],saved: dict,symbol: str) -> dict:
    """
    機能: 保存PRICEの同場P/L表だけと全場及び各政策top3除外を比較する。
    引数: rows(list[dict])、saved(dict)、symbol(str) は新小会計・PRICE保存説明・商品。
    返り値: dict は純会計差。旧親対応/経路が無いため共通親効果を作らない。
    """
    old=[dict(session=r['session'],symbol=r['symbol'],利益=r['profit'],損失=r['loss'],収支=r['net'],親数=r['campaigns'])
        for r in saved['rows'] if r['symbol']==symbol]
    assert len(rows)==len(old)==33 and {r['session'] for r in rows}=={r['session'] for r in old}
    scopes={}
    for label,new_scope,old_scope in (('全33',rows,old),('各政策の上位3正収支場除外',
        [r for r in rows if r['session'] not in {t['session'] for t in sorted((x for x in rows if x['収支']>0),key=lambda x:(-x['収支'],x['session']))[:3]}],
        [r for r in old if r['session'] not in {t['session'] for t in sorted((x for x in old if x['収支']>0),key=lambda x:(-x['収支'],x['session']))[:3]}])):
        new,prior=period_summary(new_scope),period_summary(old_scope)
        scopes[label]=dict(new=new,saved_price=prior,net_difference=new['net_yen']-prior['net_yen'],
            black_difference=new['black']-prior['black'],red_difference=new['red']-prior['red'],no_trade_difference=new['no_trade']-prior['no_trade'])
    lookup={r['session']:r for r in old}
    return dict(periods=scopes,by_session=[dict(session=r['session'],new_net=r['収支'],saved_price_net=lookup[r['session']]['収支'],
        difference=r['収支']-lookup[r['session']]['収支']) for r in rows],
        limitation='PRICEは旧109の保存rowsだけ。個別親対応/時刻経路/避けた負親/失った勝親は未保存で未測。trim除外場は政策ごとに違い得る。')


def entry_key(parent: dict) -> tuple:
    """
    機能: 新旧の同じ公開候補を紙上親/公開原seq/方向で識別する。
    引数: parent(dict) は完結実親小射影。
    返り値: tuple は場/商品/紙上CID/公開原seq/side。実CID/UIDのずれをキーにしない。
    """
    return (parent['session'],parent['symbol'],parent['paper_parent'],parent['entry']['判断']['raw_seq'],parent['side'])


def counterpart(before: list[dict],after: list[dict]) -> dict:
    """
    機能: 同公開の共通親と旧のみ/新のみを分けて五寄与の金額恒等式を検算する。
    引数: before/after(list[dict]) は同場又は同商品範囲の旧新完結親。
    返り値: dict は共通出口/価格/料差、避け損失、失い利益、新参加、全差。
    """
    old={entry_key(p):p for p in before};new={entry_key(p):p for p in after}
    assert len(old)==len(before) and len(new)==len(after)
    common=[]
    for key in sorted(old.keys()&new.keys()):
        a,b=old[key],new[key]
        common.append(dict(entry_key=list(key),old_parent=a['parent'],new_parent=b['parent'],old_uid=a['actual_uid'],new_uid=b['actual_uid'],
            old_net=a['net_yen'],new_net=b['net_yen'],net_difference=b['net_yen']-a['net_yen'],
            gross_difference=b['actual_gross_yen']-a['actual_gross_yen'],fee_difference=b['order_fees_yen']-a['order_fees_yen'],
            old_exit_row=a['exits'][0]['row'],new_exit_row=b['exits'][0]['row']))
    removed=[old[k] for k in sorted(old.keys()-new.keys())];added=[new[k] for k in sorted(new.keys()-old.keys())]
    avoided=sum(-p['net_yen'] for p in removed if p['net_yen']<0);lost=sum(p['net_yen'] for p in removed if p['net_yen']>0)
    common_diff=sum(p['net_difference'] for p in common);new_net=sum(p['net_yen'] for p in added)
    total=sum(p['net_yen'] for p in after)-sum(p['net_yen'] for p in before)
    assert close(avoided-lost+common_diff+new_net,total)
    for p in common:assert close(p['gross_difference']-p['fee_difference'],p['net_difference'])
    return dict(old_parents=len(before),new_parents=len(after),common=common,removed=removed,added=added,
        contribution=dict(avoided_loss=avoided,lost_profit=lost,common_entry_exit_difference=common_diff,new_entry_net=new_net,net_difference=total),
        limitation='消失親を全てFAK失効由来とは断定しない。後参加/busy/場停止も全運転に含まれる。UIDや実CIDの番号差だけを新参加にしない。')


def analyze(result: dict,fixed: dict,previous: dict) -> dict:
    """
    機能: 新111結果と旧110一読済み診断の各一目的読取から全新旧親の原因を対応させる。
    引数: result/fixed/previous(dict) は完成小結果・正式metadata・授権旧診断射影。
    返り値: dict は新297/alias99/旧396を分離した対応と具体赤字場。
    """
    assert result['全合格'] and result['source開始終端一致'] and result['source_SHA256']==fixed['source_SHA256']
    assert result['case_SHA256']==fixed['case_SHA256'] and result['configs']==fixed['configs'] and result['sessions']==fixed['sessions']
    assert len(result['configs'])==12 and len(result['sessions'])==33 and previous['全合格']
    assert result['counts']=={'既input一読':33,'価格票準備口座':66,'新account金融':297,'内部同値会計再利用':99}
    assert result['新account金融']==297 and result['内部同値会計再利用']==99 and result['旧経済同値保存会計']==396 and result['掲載口座']==792
    configs=[c for c in result['configs'] if c['actual_financial']];assert len(configs)==len(result['results'])==6
    assert len(result['reused_economic_cases'])==6 and len(result['internal_aliases'])==3
    profiles={};summaries={};comparison={};details={};checks=0;unique=0
    for c in configs:
        cid=c['id'];before=previous['all_parent_decomposition'][c['paired_previous_id']]
        rows=result['results'][cid]['rows'];assert len(rows)==66
        boundaries={(b['session'],b['symbol']):b for b in result['boundary'][cid]};assert len(boundaries)==66
        own=[]
        for p in result['actual_parent_diagnostics'][cid]:
            origins=[o for o in boundaries[p['session'],p['symbol']]['actual_origins'] if int(o[0])==p['parent']];assert len(origins)==1
            d=decompose(p,origins[0]);d['entry_information']=entry_information(p,c)
            if d['published_adverse_ticks']==1:
                assert d['published_own_count']>=2 and d['published_peer_count']>=2 and p['published_own_known'] and p['published_peer_known']
            else:assert d['published_adverse_ticks']==0
            own.append(d);checks+=1
            if c['actual_financial_by_symbol'][p['symbol']]:unique+=1
        profiles[cid]=own;summaries[cid]={};comparison[cid]={};details[cid]={}
        for row in rows:
            ps=[p for p in own if p['session']==row['session'] and p['symbol']==row['symbol']]
            assert len(ps)==row['親数'] and close(sum(p['net_yen'] for p in ps),row['収支'])
            assert close(sum(max(0,p['net_yen']) for p in ps),row['利益']) and close(sum(max(0,-p['net_yen']) for p in ps),row['損失'])
            assert sum(p['fees_yen'] for p in ps)==row['費用'];checks+=1
        for symbol in CAP:
            old=[p for p in before if p['symbol']==symbol];new=[p for p in own if p['symbol']==symbol]
            change=counterpart(old,new);checks+=1
            rr=[r for r in rows if r['symbol']==symbol];assert len(rr)==33
            per_scene=[]
            for row in rr:
                group_old=[p for p in old if p['session']==row['session']];group_new=[p for p in new if p['session']==row['session']]
                paired=counterpart(group_old,group_new)
                per_scene.append(dict(session=row['session'],old_net=sum(p['net_yen'] for p in group_old),new_net=row['収支'],contribution=paired['contribution'],
                    common_count=len(paired['common']),removed_count=len(paired['removed']),added_count=len(paired['added'])))
            assert close(sum(p['contribution']['net_difference'] for p in per_scene),change['contribution']['net_difference'])
            comparison[cid][symbol]=dict(**change,by_session=per_scene,actual_financial=c['actual_financial_by_symbol'][symbol],source_id=c['economic_source_id_by_symbol'][symbol])
            summary=group(new);summary.update(old=group(old),actual_financial=c['actual_financial_by_symbol'][symbol],source_id=c['economic_source_id_by_symbol'][symbol],
                price_qualification={label:group([p for p in new if p['entry_information']['price_accepted']==flag]) for label,flag in (('価格通過',True),('価格不通過',False))},
                day_night={k:group([p for p in new if p['session'].endswith('_'+k)]) for k in ('Day','Night')},
                direction={str(k):group([p for p in new if p['side']==k]) for k in (1,-1)},
                first_last={k:group([p for p in new if p['session'] in ss]) for k,ss in (('前16',result['sessions'][:16]),('後17',result['sessions'][16:]))})
            summaries[cid][symbol]=summary
            worst=sorted((r for r in rr if r['収支']<0),key=lambda r:(r['収支'],r['session']))[:3]
            details[cid][symbol]=[dict(session=r['session'],net=r['収支'],maximum_negative_parent=min(
                (p for p in new if p['session']==r['session'] and p['net_yen']<0),key=lambda p:(p['net_yen'],p['parent']))) for r in worst]
    return dict(全合格=True,検算件数=checks,source_SHA256=result['source_SHA256'],case_SHA256=result['case_SHA256'],
        all_parent_decomposition=profiles,summaries=summaries,paired_parents=comparison,worst_three_red_sessions=details,
        unique_financial_account_count=297,internal_alias_account_count=99,saved_economic_account_count=396,
        unique_financial_completed_parent_count=unique,activity=result['activity'],previous_activity=previous['activity'],
        activity_scope='FAK失効/fillは保存activityの条件商品場ごと件数。失効の公開候補個別系譜は未保存で、消失旧親全てへ同理由を割り当てない。',
        reused_economic_cases=result['reused_economic_cases'],
        limits=['共通キーは場/商品/紙上CID/公開原seq/side。実UID/CIDの番号ではない。',
            '横断不利は実grossの分解。既netへ追加費用として二重控除しない。',
            '旧診断110は保存済み実親経路だけ。旧PRICE親対応/時刻経路は未保存。',
            '事後MFE/MAEは既実保有区間だけ。新入場又は別出口救済へ用いない。',
            '時刻はCurrentPriceTime価格代理。二市場の物理受信先後は未証明。'])


