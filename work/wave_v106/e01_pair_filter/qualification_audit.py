"""不明の根拠を原fieldへ戻し、価格代理時計の停止と気配欠測を区別する。"""

from collections import defaultdict
import time

import numpy as np

import analyze
import core
import summarize


def field_counts(raw: dict, begin: int, end: int) -> dict:
    """
    機能: 当時窓の原行区間にある価格・数量連動・時計・原seqの不正を分離する。
    引数: raw(dict)、begin/end(int)は両端を含む既存原行位置。
    返り値: dictは各fieldの件数。価格正常でも数量を原因にしたresetを別記する。
    """
    assert 0 <= begin <= end < len(raw['raw_seq'])
    sl=slice(begin,end+1); times=raw['price_time_s'][sl]; seq=raw['raw_seq'][sl]
    valid=raw['bbo_valid'][sl]; reset=raw['price_reset_reason'][sl]
    values=dict(原行数=end-begin+1, 原価格時計非有限=int((~np.isfinite(times)).sum()),
        原隣接時計逆行=int((np.diff(times)<0).sum()), 原seq断裂=int((np.diff(seq)!=1).sum()),
        同時計原隣接更新=int((np.diff(times)==0).sum()),
        旧正常気配不明=int((~valid).sum()), 正常執行非対応=int((raw['normal_execution_row'][sl]<0).sum()),
        最良価格数量連動reset32=int(((reset&32)!=0).sum()),
        reset32かつ正常価格=int((((reset&32)!=0)&valid).sum()),
        前原行系列使用不能64=int(((reset&64)!=0).sum()),
        reset64かつ正常価格=int((((reset&64)!=0)&valid).sum()),
        原行価格時計highwater逆行8=int(((reset&8)!=0).sum()),
        価格時計場外16=int(((reset&16)!=0).sum()),
        reset32以外の価格系列理由=int(((reset&np.uint16(65535^32))!=0).sum()))
    return values


def endpoint_causes(raw: dict, row: int) -> dict:
    """
    機能: 公表端点のfullqualified不合格を四resetと正常価格の組合せへ分ける。
    引数: raw(dict)、row(int)は不変公表原行。
    返り値: dictは端点資格の実観測理由。保持されない元数量値を捏造しない。
    """
    result=dict(qualified=bool(raw['qualified'][row]), bbo_valid=bool(raw['bbo_valid'][row]),
        raw_seq=int(raw['raw_seq'][row]), price_time_s=float(raw['price_time_s'][row]),
        volume_time_s=float(raw['volume_time_s'][row]) if np.isfinite(raw['volume_time_s'][row]) else None)
    for key in ('price_reset_reason','depth_reset_reason','lp_reset_reason','volume_reset_reason'):
        result[key]=int(raw[key][row])
    result['正常価格だが価格数量連動32']=bool(result['bbo_valid'] and result['price_reset_reason']&32)
    result['四resetゼロだがfullqualified不明']=bool(not result['qualified'] and not any(result[k] for k in
        ('price_reset_reason','depth_reset_reason','lp_reset_reason','volume_reset_reason')))
    return result


def gap_detail(raw: dict, record: dict, previous: int, current: int) -> dict:
    """
    機能: 新最大価格時計間隔15秒超の区間で、実正常気配更新と同時計BBO変化を数える。
    引数: raw/record(dict)、previous/current(int)は隣接公表原行。
    返り値: dictは観測の意味監査。これらを使って過去のpeer採否を救済しない。
    """
    mapping=raw['execution_to_raw_index']; start=int(np.searchsorted(mapping,previous,side='left'))
    finish=int(np.searchsorted(mapping,current,side='right')); indexes=np.arange(start,finish)
    b,a,t=record['bid'][indexes],record['ask'][indexes],record['time_s'][indexes]
    q=record['quote_valid'][indexes] & np.isfinite(b) & np.isfinite(a) & (b>0) & (a>b)
    changed=(np.diff(b)!=0)|(np.diff(a)!=0)
    pair=q[1:]&q[:-1]; same=np.diff(t)==0
    numbers=dict(公表価格時計差秒=float(raw['price_time_s'][current]-raw['price_time_s'][previous]),
        原seq差=int(raw['raw_seq'][current]-raw['raw_seq'][previous]),
        正常執行対応行数=len(indexes),正常気配行数=int(q.sum()),
        間の正常気配行数=int(q[1:-1].sum()) if len(q)>2 else 0,
        正常BBO変更数=int((changed&pair).sum()),同価格時計の正常BBO変更数=int((changed&pair&same).sum()),
        正常隣接quoteの同時計数=int((pair&same).sum()),
        開始公表=core.quote(raw,previous),終了公表=core.quote(raw,current),
        区間field=field_counts(raw,previous,current))
    return numbers


def artificial() -> dict:
    """
    機能: 全気配正常でも価格代理時計gapが窓を不明にする反例を純人工で保存する。
    引数: なし。
    返り値: dictは反例と数量連動例。新たな資格緩和を実装しない。
    """
    times=np.array([0.,0.,0.,0.,20.,30.]); bid=np.array([100.,101.,102.,101.,103.,104.])
    raw=dict(raw_seq=np.arange(6,dtype=np.int64),price_time_s=times,bid=bid,ask=bid+1,
        bbo_valid=np.ones(6,bool),qualified=np.ones(6,bool),price_reset_reason=np.zeros(6,np.uint16),
        normal_execution_row=np.arange(6,dtype=np.int32),execution_to_raw_index=np.arange(6,dtype=np.int64))
    public=dict(rows=np.array([0,4,5],np.int64),raw_seq=np.array([0,4,5],np.int64),times=np.array([0.,20.,30.]))
    policy=dict(max_public_gap_seconds=15.,baseline_extra_age_seconds=15.,spread_max_ticks=2.,spread_increment_ticks=1.)
    observed=core.observe(raw,core.public_windows(raw,public,1.,policy),30.,30,5,False)
    assert observed['state']=='UNKNOWN' and observed['unknown_reason']&32
    record=dict(bid=bid,ask=bid+1,time_s=times,quote_valid=np.ones(6,bool))
    detail=gap_detail(raw,record,0,4)
    assert detail['間の正常気配行数']==3 and detail['同価格時計の正常BBO変更数']==3
    coupled={k:v.copy() for k,v in raw.items()};coupled['price_reset_reason'][2]=32
    counts=field_counts(coupled,0,5)
    assert counts['reset32かつ正常価格']==1 and counts['旧正常気配不明']==0
    return dict(全合格=True,検査数=2,価格時計gapでも正常気配更新あり=detail,
        数量連動resetだが価格不正ゼロ=counts,新金融=0,新注文=0)


def run() -> None:
    """
    機能: 保存33価格packetのみを一回読んで、不明の実fieldと公表gapの意味を監査する。
    引数: なし。
    返り値: None。旧価格窓/金融sourceを変更せず、未知を支持へ補完しない。
    """
    started=time.monotonic(); plan=analyze.read(analyze.HERE/'分析事前計画.json')
    old=analyze.read(analyze.HERE/'入口状態と保存損益の分類.json'); assert old['全合格']
    art=artificial(); frames=[]; gap_cases={}; counters=defaultdict(lambda:defaultdict(int)); examples=[]
    dependencies=[analyze.HERE/'qualification_audit.py',analyze.HERE/'core.py',
        analyze.HERE/'入口状態と保存損益の分類.json',analyze.ROOT/'work/wave_v103/input/入力schema.json',
        analyze.ROOT/'work/wave_v103/engine/states.py']
    hashes={p.relative_to(analyze.ROOT).as_posix():analyze.digest(p) for p in dependencies}
    for session in plan['data']['sessions']:
        packet=analyze.checked_packet(plan['data']['packets'][session])
        if 'peer' in packet:
            packet=packet['peer']
        subset=[e for e in old['entries'] if e['session']==session]
        for entry in subset:
            symbol=entry['symbol'];other='NK225' if symbol=='TOPIX' else 'TOPIX'
            for stage,value in entry['stages'].items():
                for window,measured in value['windows'].items():
                    for role,obs in measured.items():
                        market=symbol if role=='own' else other
                        raw=packet['raw'][market];record=packet['normal'][market]['record']
                        key='|'.join((stage,symbol,window,role)); count=counters[key]
                        count['全観測窓']+=1;count['UNKNOWN窓']+=obs['state']=='UNKNOWN'
                        if obs['source'] is None or obs['reference'] is None:
                            count['端点又は基準なし']+=1
                            continue
                        begin,end=obs['reference']['raw_row'],obs['source']['raw_row']
                        values=field_counts(raw,begin,end)
                        endpoints={name:endpoint_causes(raw,row) for name,row in (('reference',begin),('source',end))}
                        for name,v in values.items():
                            count['fieldのある窓:'+name]+=v>0
                            count['窓を重複合算した原行数:'+name]+=v
                        for name,ep in endpoints.items():
                            if not ep['qualified']:
                                count[name+':fullqualified不合格']+=1
                                if ep['bbo_valid']:
                                    count[name+':fullqualified不合格だが正常価格']+=1
                                for resetname in ('price_reset_reason','depth_reset_reason','lp_reset_reason','volume_reset_reason'):
                                    count[name+':'+resetname+'非零']+=ep[resetname]!=0
                        public=packet['peer_features'][market]['public']; rows=public['rows'];times=public['times']
                        first=int(np.searchsorted(rows,begin,side='left'));last=int(np.searchsorted(rows,end,side='left'))
                        gaps=[i for i in range(first+1,last+1) if times[i]-times[i-1]>15.]
                        count['publicgap15秒超のある窓']+=bool(gaps)
                        for index in gaps:
                            start,finish=int(rows[index-1]),int(rows[index]); gapkey=(session,market,start,finish)
                            if gapkey not in gap_cases:
                                gap_cases[gapkey]=dict(session=session,symbol=market,**gap_detail(raw,record,start,finish))
                        if obs['state']=='UNKNOWN':
                            frame=dict(session=session,symbol=symbol,parent=entry['parent'],stage=stage,role=role,
                                window=int(window),unknown_reason=obs['unknown_reason'],
                                selection_unknown_reason=obs['selection_unknown_reason'],own_tail_unknown=obs['own_tail_unknown'],
                                endpoints=endpoints,原区間=values,公表gap数=len(gaps))
                            frames.append(frame)
        print(session+' UNKNOWN原field・当時窓内clock gap監査完了',flush=True)
        del packet
    gaps=list(gap_cases.values())
    gap_summary=dict(当時入口窓に含まれる独立公表gap=len(gaps),
        間に正常quote更新あり=sum(g['間の正常気配行数']>0 for g in gaps),
        同価格時計で正常BBO変更あり=sum(g['同価格時計の正常BBO変更数']>0 for g in gaps),
        原seq連続かつ区間全quote正常=sum(g['区間field']['原seq断裂']==0 and g['区間field']['旧正常気配不明']==0 for g in gaps),
        同価格時計のBBO変更合計=sum(g['同価格時計の正常BBO変更数'] for g in gaps))
    examples=sorted(gaps,key=lambda g:g['同価格時計の正常BBO変更数'],reverse=True)[:6]
    for example in examples:
        example['開始価格時計']=summarize.displayed(example['開始公表']['price_time_s'])
        example['終了価格時計']=summarize.displayed(example['終了公表']['price_time_s'])
    assert all(analyze.digest(analyze.ROOT/p)==h for p,h in hashes.items())
    analyze.write(analyze.HERE/'UNKNOWN観測定義と原fieldの監査.json',dict(全合格=True,
        当時窓数=246*2*3*2,未知窓詳細=frames,分類別=dict(counters),公表gap監査=gap_summary,具体6gap=examples,
        人工反例=art,source_SHA256=hashes,source開始終端一致=True,旧104packet読取=33,
        新金融=0,新注文=0,原板再読取=0,API=0,経過秒=time.monotonic()-started,
        機械定義の問題=['CurrentPriceTimeは板受信時計ではない。価格clockの新最大が15秒出ない事実を、quote受信中断と同一視できない。',
            'PRICE_RESET32は最良価格又は最良数量不正、64は前原行系列不正。正常価格がある場合も価格窓の全区間不正へ連動する。',
            'qualifiedは元103の10段・数量・LP・出来高差資格を含む。価格端点の知識そのものと別の条件である。'],
        維持すべき未知=['真の受信時計と二市場受信順は未観測。今回のgap診断は同時配信の証明ではない。',
            'peer strictpastとasof古さは、区間publicgapによる不明とは別。時計逆行・原seq断裂・実BBO欠測を価格支持へ補完しない。',
            '104rawでは最良数量の実値を保持しないため、reset32かつ正常価格は数量連動を強く示すが元数量値を復元しない。'],
        未検証の価格観測対照=['窓の全区間publicgap破棄と、所定時点の正常BBO比較を分ける。前者を外す比較を結果前に固定できる。',
            '数量/出来高qualificationを価格だけの観測資格から分離する。ただし実価格/時計/原seq欠測はそのまま拒否。',
            '当該自己原行のBBOと公表first行BBOを分離し、指値待ち中のprice支持を監視する。peerのarrival不明は別に残す。']))
    print('UNKNOWN原field監査完成。金融0・価格窓変更0',flush=True)


if __name__=='__main__':
    run()
