"""保存出来高入口の実親を価格方向・横断不利・料へ分け、唯一金融と保存比較を区別する。"""

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


def analyze(result: dict,fixed: dict) -> dict:
    """
    機能: volume新結果一読から唯一495金融・内部99aliasと旧PRICE198を分けて診断する。
    引数: result/fixed(dict) は正式結果と固定metadata。
    返り値: dict は検算済み診断。元packet/台帳/旧PRICE親経路を補完しない。
    """
    assert result['全合格'] and result['source開始終端一致'] and result['source_SHA256']==fixed['source_SHA256']
    assert result['case_SHA256']==fixed['case_SHA256'] and result['configs']==fixed['configs'] and result['sessions']==fixed['sessions']
    assert len(result['configs'])==12 and len(result['sessions'])==33
    assert result['counts']=={'既input一読':33,'価格票準備口座':66,'新account金融':495,'内部同値会計再利用':99}
    assert result['新account金融']==495 and result['内部同値会計再利用']==99 and result['保存PRICE会計']==198 and result['掲載口座']==792
    configs=[c for c in result['configs'] if c['actual_financial']];assert len(configs)==len(result['results'])==9
    assert len(result['reused_price_cases'])==3 and len(result['internal_aliases'])==3
    profiles={};summaries={};details={};comparison={};checks=0;unique_count=0
    for c in configs:
        cid=c['id'];assert not c['enable_opposed_price_exit'];rows=result['results'][cid]['rows'];assert len(rows)==66
        boundaries={(b['session'],b['symbol']):b for b in result['boundary'][cid]};assert len(boundaries)==66
        own=[];seen=set()
        for p in result['actual_parent_diagnostics'][cid]:
            origins=[o for o in boundaries[p['session'],p['symbol']]['actual_origins'] if int(o[0])==p['parent']];assert len(origins)==1
            d=decompose(p,origins[0]);d['entry_information']=entry_information(p,c)
            key=(p['session'],p['symbol'],d['actual_uid']);assert key not in seen;seen.add(key);own.append(d);checks+=1
            if c['actual_financial_by_symbol'][p['symbol']]:unique_count+=1
        for r in rows:
            ps=[p for p in own if p['session']==r['session'] and p['symbol']==r['symbol']]
            assert len(ps)==r['親数'] and close(sum(p['net_yen'] for p in ps),r['収支'])
            assert close(sum(max(0.,p['net_yen']) for p in ps),r['利益']) and close(sum(max(0.,-p['net_yen']) for p in ps),r['損失'])
            assert sum(p['fees_yen'] for p in ps)==r['費用'];checks+=1
        profiles[cid]=own;summaries[cid]={};details[cid]={};comparison[cid]={}
        for s in CAP:
            ps=[p for p in own if p['symbol']==s];rr=[r for r in rows if r['symbol']==s];assert len(rr)==33
            summary=group(ps);assert all(p['publication_kind']==0 for p in ps)
            summary['actual_financial']=c['actual_financial_by_symbol'][s];summary['economic_source_id']=c['economic_source_id_by_symbol'][s]
            summary['entry_information_counts']=dict(Counter(p['entry_information']['acceptance_class'] for p in ps))
            summary['qualification_denominator']='当該条件/商品の完結実親。公開資格の候補全体又は勝率の分母ではない。'
            summary['buy_sell']={str(k):group([p for p in ps if p['side']==k]) for k in (1,-1)}
            summary['day_night']={k:group([p for p in ps if p['session'].endswith('_'+k)]) for k in ('Day','Night')}
            summary['first_last']={k:group([p for p in ps if p['session'] in ss]) for k,ss in (('前16',result['sessions'][:16]),('後17',result['sessions'][16:]))}
            summary['adverse_ticks']={str(k):group([p for p in ps if p['published_adverse_ticks']==k]) for k in (0,1)}
            summary['volume_vote_bucket']={k:group([p for p in ps if lo<=p['entry_information']['volume']['direction_votes']<=hi])
                for k,lo,hi in (('2票',2,2),('3-4票',3,4),('5-9票',5,9),('10票以上',10,10**18))}
            for where in ('publication','entry','exit_decision','exit'):
                summary[where+'_paper_remaining']={str(q):group([p for p in ps if p[where+'_paper_matches_origin'] and p[where+'_paper_remaining_quantity']==q])
                    for q in sorted({p[where+'_paper_remaining_quantity'] for p in ps if p[where+'_paper_matches_origin']})}
                summary[where+'_other_paper_points']=sum(not p[where+'_paper_matches_origin'] for p in ps)
            summaries[cid][s]=summary
            worst=sorted((r for r in rr if r['収支']<0),key=lambda r:(r['収支'],r['session']))[:3]
            details[cid][s]=[dict(row=r,summary=group([p for p in ps if p['session']==r['session']]),
                maximum_two_negative_parents=sorted([p for p in ps if p['session']==r['session'] and p['net_yen']<0],key=lambda p:(p['net_yen'],p['parent']))[:2]) for r in worst]
            saved=result['comparison_reference']['cases'][c['paired_price_id']]
            comparison[cid][s]=saved_comparison(rr,saved,s);checks+=1
    for c in configs:
        if c['actual_financial_by_symbol']['NK225']:continue
        src=c['economic_source_id_by_symbol']['NK225'];assert c['entry_id']=='VOL25'
        ar=[r for r in result['results'][c['id']]['rows'] if r['symbol']=='NK225'];sr=[r for r in result['results'][src]['rows'] if r['symbol']=='NK225'];assert ar==sr
        for field in ('actual_origins','judgments'):
            assert [b[field] for b in result['boundary'][c['id']] if b['symbol']=='NK225']==[b[field] for b in result['boundary'][src] if b['symbol']=='NK225']
        aliases=[p for p in result['actual_parent_diagnostics'][c['id']] if p['symbol']=='NK225'];originals=[p for p in result['actual_parent_diagnostics'][src] if p['symbol']=='NK225']
        import copy
        normalized=copy.deepcopy(aliases)
        for p in normalized:
            assert p.pop('economic_alias_source_id')==src;p['published_entry_information']['entry_id']='VOL_SELECTED'
        assert normalized==originals;checks+=1
    counts={s:dict(improved=sum(v[s]['periods']['全33']['net_difference']>0 for v in comparison.values()),
        worsened=sum(v[s]['periods']['全33']['net_difference']<0 for v in comparison.values()),unchanged=sum(v[s]['periods']['全33']['net_difference']==0 for v in comparison.values()),
        scope='表示volume九条件。NK alias三組は追加効能証拠として独立に数えない。') for s in CAP}
    return dict(全合格=True,検算件数=checks,source_SHA256=result['source_SHA256'],case_SHA256=result['case_SHA256'],
        all_parent_decomposition=profiles,summaries=summaries,worst_three_red_sessions=details,paired_saved_price=comparison,net_change_counts=counts,
        unique_financial_account_count=495,internal_alias_account_count=99,saved_price_account_count=198,
        unique_financial_completed_parent_count=unique_count,activity=result['activity'],
        activity_scope='保存activityは公開候補/受理/実fill/失効/取消の数。全候補のvolume×price交差資格は未保存。実親の交差資格を候補全体へ一般化しない。',
        limitations=['気配横断不利は実約定grossの分解。既netに別費用を追加して二重控除しない。',
            '紙上残量は同観測行の現在paper残量。origin paperと違う観測は別親として分ける。Native q/capと混ぜない。',
            'MFE/MAEは当該政策の実保有区間だけの事後診断。別出口救済利益/結果後採否を作らない。',
            '時刻はCurrentPriceTime代理。二市場の価格時計模型/受信先後未証明を継承。'])
