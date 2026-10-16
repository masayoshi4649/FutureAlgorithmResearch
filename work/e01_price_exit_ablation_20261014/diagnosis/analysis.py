"""反票OFFの保存実親をmid方向・気配横断不利・実料へ分け、ON集計と対応する。"""

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


def compare_period(off: dict,on: dict) -> dict:
    """
    機能: 保存ON/OFFの同期間net/黒赤無を算術比較する。
    引数: off/on(dict) は各期間のaggregate/economic/stability。
    返り値: dict は差分。trimは各政策自身の上位三場除外で母集団が異なり得る。
    """
    oa,na=off['aggregate'],on['aggregate'];os,ns=off['stability'],on['stability']
    return dict(off_net=oa['収支'],on_net=na['収支'],net_difference=oa['収支']-na['収支'],
        off_black=os['positive_sessions'],on_black=ns['positive_sessions'],black_difference=os['positive_sessions']-ns['positive_sessions'],
        off_red=os['losing_sessions'],on_red=ns['losing_sessions'],red_difference=os['losing_sessions']-ns['losing_sessions'],
        off_no_trade=os['no_trade_sessions'],on_no_trade=ns['no_trade_sessions'],no_trade_difference=os['no_trade_sessions']-ns['no_trade_sessions'],
        off_session_count=off['economic']['session_count'],on_session_count=on['economic']['session_count'])


def analyze(result: dict,fixed: dict) -> dict:
    """
    機能: 新十二OFF結果一読から全親の分解/分類と保存ON集計差を射影する。
    引数: result/fixed(dict) は正式結果と固定metadata。
    返り値: dict は検算済み診断。旧ON親/経路、原packet/台帳を補完しない。
    """
    assert result['全合格'] and result['source開始終端一致'] and result['source_SHA256']==fixed['source_SHA256']
    assert result['case_SHA256']==fixed['case_SHA256'] and result['configs']==fixed['configs'] and result['sessions']==fixed['sessions']
    assert len(result['configs'])==12 and len(result['sessions'])==33
    assert result['counts']=={'既input一読':33,'価格票準備口座':66,'新account金融':792}
    profiles={};summaries={};details={};comparison={};checks=0
    for c in result['configs']:
        cid=c['id'];assert not c['enable_opposed_price_exit'];rows=result['results'][cid]['rows'];assert len(rows)==66
        boundaries={(b['session'],b['symbol']):b for b in result['boundary'][cid]};assert len(boundaries)==66
        own=[];seen=set()
        for p in result['actual_parent_diagnostics'][cid]:
            origins=[o for o in boundaries[p['session'],p['symbol']]['actual_origins'] if int(o[0])==p['parent']];assert len(origins)==1
            d=decompose(p,origins[0]);key=(p['session'],p['symbol'],d['actual_uid']);assert key not in seen;seen.add(key);own.append(d);checks+=1
        for r in rows:
            ps=[p for p in own if p['session']==r['session'] and p['symbol']==r['symbol']]
            assert len(ps)==r['親数'] and close(sum(p['net_yen'] for p in ps),r['収支'])
            assert close(sum(max(0.,p['net_yen']) for p in ps),r['利益']) and close(sum(max(0.,-p['net_yen']) for p in ps),r['損失'])
            assert sum(p['fees_yen'] for p in ps)==r['費用'];checks+=1
        profiles[cid]=own;summaries[cid]={};details[cid]={};comparison[cid]={}
        assert result['paired_saved_on'][cid]['on_id']==c['paired_on_id']
        for s in CAP:
            ps=[p for p in own if p['symbol']==s];rr=[r for r in rows if r['symbol']==s];assert len(rr)==33
            summary=group(ps);summary['entry_type']={str(k):group([p for p in ps if p['publication_kind']==k]) for k in (0,1,2)}
            summary['buy_sell']={str(k):group([p for p in ps if p['side']==k]) for k in (1,-1)}
            summary['day_night']={k:group([p for p in ps if p['session'].endswith('_'+k)]) for k in ('Day','Night')}
            for where in ('publication','entry','exit_decision','exit'):
                summary[where+'_paper_remaining']={str(q):group([p for p in ps if p[where+'_paper_matches_origin'] and p[where+'_paper_remaining_quantity']==q])
                    for q in sorted({p[where+'_paper_remaining_quantity'] for p in ps if p[where+'_paper_matches_origin']})}
                summary[where+'_other_paper_points']=sum(not p[where+'_paper_matches_origin'] for p in ps)
            summaries[cid][s]=summary
            worst=sorted((r for r in rr if r['収支']<0),key=lambda r:(r['収支'],r['session']))[:3]
            details[cid][s]=[dict(row=r,summary=group([p for p in ps if p['session']==r['session']]),
                maximum_two_negative_parents=sorted([p for p in ps if p['session']==r['session'] and p['net_yen']<0],key=lambda p:(p['net_yen'],p['parent']))[:2]) for r in worst]
            off=result['results'][cid]['periods'][s];on=result['paired_saved_on'][cid]['saved_on'][s]
            full=compare_period(off['全33'],on['全場']);trim=compare_period(off['上位3正収支場除外'],on['上位三除外'])
            on_rows={r['session']:r for r in on['全場']['economic']['by_session']};assert len(on_rows)==33
            scene=[dict(session=r['session'],off_net=r['収支'],on_net=on_rows[r['session']]['net_yen'],
                net_difference=r['収支']-on_rows[r['session']]['net_yen'],off_parent_count=r['親数'],on_parent_count=on_rows[r['session']]['parent_count']) for r in rr]
            assert close(sum(r['net_difference'] for r in scene),full['net_difference']);checks+=1
            comparison[cid][s]=dict(paired_on_id=c['paired_on_id'],full=full,own_top3_excluded=trim,by_session_net_only=scene,
                limitation='ON各場net/親数は保存済み。ON親対応/各場P&L内訳/入口退出時刻経路は未収録。trimの除外場は政策ごとに違い得る。')
    counts={s:dict(improved=sum(v[s]['full']['net_difference']>0 for v in comparison.values()),
        worsened=sum(v[s]['full']['net_difference']<0 for v in comparison.values()),unchanged=sum(v[s]['full']['net_difference']==0 for v in comparison.values())) for s in CAP}
    return dict(全合格=True,検算件数=checks,source_SHA256=result['source_SHA256'],case_SHA256=result['case_SHA256'],
        all_parent_decomposition=profiles,summaries=summaries,worst_three_red_sessions=details,paired_on_off=comparison,net_change_counts=counts,
        limitations=['気配横断不利は実約定grossの分解。既netに別費用を追加して二重控除しない。',
            '紙上残量は同観測行の現在paper残量。origin paperと違う観測は別親として分ける。Native q/capと混ぜない。',
            'MFE/MAEは当該政策の実保有区間だけの事後診断。別出口救済利益/結果後採否を作らない。',
            '時刻はCurrentPriceTime代理。二市場の価格時計模型/受信先後未証明を継承。'])
