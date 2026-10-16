"""完了金融の原seq対応を読み、避けた損失と失った利益及び残る具体損失を分ける。"""

from collections import defaultdict
from datetime import datetime,timedelta,timezone
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent;PHASE=HERE.parent
sys.dont_write_bytecode=True;sys.path.insert(0,str(PHASE))
import common
import data
import features
import selection

JST=timezone(timedelta(hours=9))
FIELDS=('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')


def clock(record: dict, row: int) -> dict:
    """
    機能: 同normal行の原seqと価格代理時計を一緒に記載する。
    引数: record(dict)、row(int)は保存価格と原行。
    返り値: dictはJST価格時計。板到着時刻又は遅延へ変換しない。
    """
    return dict(normal_row=int(row),raw_seq=int(record['seq'][row]),price_time=float(record['time_s'][row]),
        JST=datetime.fromtimestamp(float(record['time_s'][row]),JST).isoformat())


def parent_map(ledger: dict, record: dict) -> dict:
    """
    機能: 実完結親を入口判断原seqと方向へ一対一に対応させる。
    引数: ledger/record(dict)は保存金融と同一normal価格。
    返り値: dict[str,ndarray]はseq|sideから親への対応。場跨ぎparent番号を使わない。
    """
    assert ledger['row_count']==len(record['seq'])
    result={}
    for trade in ledger['trades']:
        row=int(trade[15]);key=str(int(record['seq'][row]))+'|'+str(int(trade[4]))
        assert key not in result;result[key]=trade
    return result


def delta(left: dict, right: dict) -> dict:
    """
    機能: 失われた/加わった実親と共通親の収支を5項へ厳密分解する。
    引数: left/right(dict)は同数量・同元候補の原seq親対応。
    返り値: dictは5寄与と全対象keys。新金融を行わない。
    """
    removed=sorted(set(left)-set(right));added=sorted(set(right)-set(left));common_keys=sorted(set(left)&set(right))
    avoided=sum(-float(left[k][11]) for k in removed if left[k][11]<0)
    lost=sum(float(left[k][11]) for k in removed if left[k][11]>0)
    changed=sum(float(right[k][11]-left[k][11]) for k in common_keys)
    additional=sum(float(right[k][11]) for k in added)
    total=sum(float(v[11]) for v in right.values())-sum(float(v[11]) for v in left.values())
    assert abs(total-(avoided-lost+changed+additional))<1e-4
    for k in common_keys:
        np.testing.assert_array_equal(left[k][[2,3,4,5,6,7,8,9,10,11,13,15]],right[k][[2,3,4,5,6,7,8,9,10,11,13,15]])
    return dict(収支変化=total,避けた基準損失=avoided,失った基準利益=lost,共通入口の出口変化=changed,
        新たな入口の収支=additional,消えた基準入口=removed,新しい入口=added,共通入口=common_keys)


def extrema(record: dict, trade: np.ndarray) -> dict:
    """
    機能: 実保有区間の正常清算quoteから事後MFE/MAEと料込最高清算額を算出する。
    引数: record(dict)、trade(ndarray)は同価格と完結親。
    返り値: dictは観測済み極値。未来予測の当たり率にしない。
    """
    a,b=int(trade[2]),int(trade[3]);side=int(trade[4]);q=int(trade[5]);E=float(trade[6]);m=1000. if record['symbol']=='TOPIX' else 10.
    rows=np.arange(a,b+1);bid=record['bid'][rows];ask=record['ask'][rows]
    valid=record['quote_valid'][rows]&np.isfinite(bid)&np.isfinite(ask)&(bid>0)&(ask>bid)
    rows=rows[valid];assert len(rows)
    quotes=record['bid'][rows] if side==1 else record['ask'][rows];movement=side*(quotes-E)
    best=int(np.argmax(movement));worst=int(np.argmin(movement));maximum=float(movement[best]*q*m-trade[8]-trade[9])
    return dict(MFE_ticks=max(0.,float(movement[best]))/record['tick'],MAE_ticks=max(0.,float(-movement[worst]))/record['tick'],
        best_net=maximum,best_clock=clock(record,int(rows[best])),worst_clock=clock(record,int(rows[worst])),
        profit_given_back=max(0.,maximum-float(trade[11])) if maximum>0 else 0.)


def describe(ledger: dict, record: dict, short: dict, trade: np.ndarray) -> dict:
    """
    機能: 実親の入口・fill・出口と当時短位相、支持/中心を短く抜き出す。
    引数: ledger/record/short(dict)、trade(ndarray)は保存経済と現在までの価格位相。
    返り値: dictは具体原因資料。MFEだけは事後量として分離する。
    """
    parent=int(trade[0]);source=int(trade[1]);decision=int(trade[15]);fill=int(trade[2]);exit=int(trade[3])
    entry=next(d for d in ledger['raw_entry_diagnostics'] if int(d['parent_id'])==parent);episode=entry['episode']
    order=next(o for o in ledger['orders'] if int(o[2])==parent and not o[7])
    return dict(key=str(int(record['seq'][decision]))+'|'+str(int(trade[4])),parent_id=parent,source='C' if source==0 else 'R_PRICE',
        side='買い' if trade[4]==1 else '売り',quantity=int(trade[5]),net=float(trade[11]),
        decision=clock(record,decision),decision_bid=float(record['bid'][decision]),decision_ask=float(record['ask'][decision]),
        phase=features.at_phase(short,decision),fill=clock(record,fill),entry_price=float(trade[6]),
        exit_decision=clock(record,int(order[1])),exit=clock(record,exit),exit_price=float(trade[7]),exit_reason=int(trade[13]),
        fees=float(trade[8]+trade[9]),fixed_support=episode.get('support_price'),fixed_stop=episode.get('stop_price'),
        fixed_target=episode.get('target_price'),planned_RR=episode.get('fee_included_ratio'),
        actual_fill_local_condition=entry.get('fill_local_cancel_condition'),extrema=extrema(record,trade))


def absence_reason(normal: dict, ledger: dict, record: dict, key: str) -> dict:
    """
    機能: 元実入口が消えた理由を局所拒否、待機取消、占有又はcooldownへ分ける。
    引数: normal/ledger/record(dict)、key(str)は現在選択/経済と元入口seq|side。
    返り値: dictは当時の記録に基づく説明。不明を予測改善へ代用しない。
    """
    seq,side=map(int,key.split('|'));rows=np.flatnonzero(record['seq']==seq);assert len(rows)==1;row=int(rows[0])
    if normal['local_phase_rejected'][row]:
        return dict(reason='R新規を局所位相で拒否',clock=clock(record,row),phase=features.at_phase(normal['local_phase'],row))
    controls=ledger['candidate_controls'];columns=ledger['candidate_control_columns']
    selected=controls[controls[:,columns.index('row')]==row]
    if len(selected):
        value=selected[0];code=int(value[columns.index('rejection')])
        if not value[columns.index('accepted')]:
            return dict(reason=ledger.get('rejections',{}).get(code,'既保存候補審査'),code=code,clock=clock(record,row),
                phase=int(value[columns.index('phase')]),blocked_mask=int(value[columns.index('blocked_mask')]))
    posted=[e for e in ledger['events'] if int(e[3])==1 and int(e[0])==row and int(e[4])==side]
    if posted:
        parent=int(posted[0][1]);cancel=next((d for d in ledger.get('pending_cancel_diagnostics',[]) if d['parent_id']==parent),None)
        if cancel is not None:return dict(reason='未fill待機を取消',cancel=cancel,cancel_clock=clock(record,cancel['row']))
        events=[e for e in ledger['events'] if int(e[1])==parent and int(e[3])==6]
        if events:return dict(reason='既知時間又は既待機条件で取消',cancel_clock=clock(record,int(events[0][0])),detail=float(events[0][11]))
    return dict(reason='実入口なし、個別原因を追加推測しない',clock=clock(record,row),normal_event=int(normal['event'][row]))


def add_group(groups: dict, name: str, trade: np.ndarray) -> None:
    """
    機能: 同じ当時条件の黒字反証と親分母を条件別に残す。
    引数: groups(dict)、name(str)、trade(ndarray)は集計先と分類及び親。
    返り値: None。異なる条件で重なる親を独立試行へ合算しない。
    """
    value=groups.setdefault(name,dict(parents=0,wins=0,losses=0,profit=0.,loss=0.,net=0.))
    net=float(trade[11]);value['parents']+=1;value['wins']+=int(net>0);value['losses']+=int(net<0)
    value['profit']+=max(0.,net);value['loss']+=max(0.,-net);value['net']+=net


def main() -> None:
    """
    機能: 先固定した全親5寄与/最悪3場/9月29日と後続を一回の保存読取で診断する。
    引数: なし。LP cache33とunique金融台帳だけを読む。
    返り値: None。金融再生/API/原板抽出/閾値変更は行わない。
    """
    target=HERE/'具体損失と5寄与及び9月29日の回避後続.json';assert not target.exists()
    plan_path=HERE/'具体損失と5寄与の診断前固定.json';plan=common.read(plan_path)
    source=PHASE/'finance/results.json';result=common.read(source);assert result['全合格'] and common.digest(source)==plan['結果SHA256']
    configs=result['configs'];targets={};output={};unique_reads=0;target_seq=13592;target_session='2026-09-29_Day'
    representative=next(c['id'] for c in configs if c['local_policy']=='ALIGNED')
    detailed=set(result['actual_condition_ids'])|{representative}
    for cfg in configs:
        ident=cfg['id'];output[ident]={};targets[ident]={}
        for symbol in ('TOPIX','NK225'):
            rows=[r for r in result['cases'][ident]['rows'] if r['symbol']==symbol]
            worst=sorted((r for r in rows if r['net']<0),key=lambda r:(r['net'],r['session']))[:3] if ident in detailed else []
            targets[ident][symbol]={r['session'] for r in worst}
            output[ident][symbol]=dict(total={f:0. for f in FIELDS},groups={},worst_sessions={r['session']:{} for r in worst},session_deltas={},target_scene={})
    for session in result['sessions']:
        packet=data.load_session(session)
        for symbol in ('TOPIX','NK225'):
            record=packet['prepared'][symbol]['record'];short=packet['short'][symbol];memo={}
            def load(item: dict) -> dict:
                """
                機能: この場商品内で同path台帳を一回だけhash読取する。
                引数: item(dict)は固定path/SHA256。
                返り値: dictは保存金融。alias共有台帳の重複読取を避ける。
                """
                nonlocal unique_reads
                key=item['path']
                if key not in memo:memo[key]=common.unpack(item);unique_reads+=1
                return memo[key]
            baselines={b:load(value['ledgers'][session][symbol]) for b,value in result['baselines'].items()}
            left_maps={b:parent_map(value,record) for b,value in baselines.items()}
            for cfg in configs:
                ident=cfg['id'];ledger=load(result['cases'][ident]['ledgers'][session][symbol]);right=parent_map(ledger,record)
                baseline=baselines[cfg['base_id']];left=left_maps[cfg['base_id']];value=delta(left,right)
                current=output[ident][symbol];current['session_deltas'][session]=value
                for f in FIELDS:current['total'][f]+=value[f]
                for trade in right.values():
                    side=int(trade[4]);row=int(trade[15]);family='C' if trade[1]==0 else 'R'
                    own=int(short['own']['direction'][row]);peer=int(short['peer']['direction'][row])
                    own_known=bool(short['own']['known'][row]);peer_known=bool(short['peer']['known'][row])
                    add_group(current['groups'],family+'/全親',trade)
                    add_group(current['groups'],family+'/自己強反対='+str(own_known and own==-side),trade)
                    add_group(current['groups'],family+'/双方強反対='+str(own_known and peer_known and own==-side and peer==-side),trade)
                    add_group(current['groups'],family+'/双方強同方向='+str(own_known and peer_known and own==side and peer==side),trade)
                if session in targets[ident][symbol] or (session==target_session and symbol=='TOPIX'):
                    normal=selection.build(packet,symbol,cfg)
                    removed=value['消えた基準入口'];added=value['新しい入口']
                    lost=sorted((k for k in removed if left[k][11]>0),key=lambda k:(-left[k][11],k))
                    avoided=sorted((k for k in removed if left[k][11]<0),key=lambda k:(left[k][11],k))
                    if session in targets[ident][symbol]:
                        losing=sorted((t for t in right.values() if t[11]<0),key=lambda t:(t[11],t[0]))[:2]
                        current['worst_sessions'][session]=dict(
                            baseline_row=next(r for r in result['baselines'][cfg['base_id']]['rows'] if r['session']==session and r['symbol']==symbol),
                            changed_row=next(r for r in result['cases'][ident]['rows'] if r['session']==session and r['symbol']==symbol),
                            contribution=value,largest_loss_parents=[describe(ledger,record,short,t) for t in losing],
                            avoided_loss_examples=[dict(parent=describe(baseline,record,short,left[k]),reason=absence_reason(normal,ledger,record,k)) for k in avoided[:2]],
                            lost_winner_examples=[dict(parent=describe(baseline,record,short,left[k]),reason=absence_reason(normal,ledger,record,k)) for k in lost[:2]],
                            new_parent_examples=[describe(ledger,record,short,right[k]) for k in sorted(added,key=lambda k:(right[k][11],k))[:2]])
                    if session==target_session and symbol=='TOPIX':
                        key=str(target_seq)+'|1';row=int(np.flatnonzero(record['seq']==target_seq)[0])
                        baseline_trade=left.get(key);changed_trade=right.get(key)
                        later_lost=[k for k in lost if int(k.split('|')[0])>target_seq]
                        later_added=[k for k in added if int(k.split('|')[0])>target_seq]
                        current['target_scene']=dict(clock=clock(record,row),bid=float(record['bid'][row]),ask=float(record['ask'][row]),
                            phase=features.at_phase(short,row),base_id=cfg['base_id'],base_actual=describe(baseline,record,short,baseline_trade) if baseline_trade is not None else None,
                            changed_actual=describe(ledger,record,short,changed_trade) if changed_trade is not None else None,
                            actual_loss_avoided=float(-baseline_trade[11]) if baseline_trade is not None and baseline_trade[11]<0 and changed_trade is None else 0.,
                            current_candidate=next((d for d in normal['local_phase_candidates'] if int(d['raw_seq'])==target_seq),None),
                            absence=absence_reason(normal,ledger,record,key) if changed_trade is None else None,
                            session_delta=value,
                            later_lost_winners=[dict(parent=describe(baseline,record,short,left[k]),reason=absence_reason(normal,ledger,record,k)) for k in later_lost],
                            later_added_parents=[describe(ledger,record,short,right[k]) for k in sorted(later_added,key=lambda k:int(k.split('|')[0]))])
                    del normal
            del memo
        del packet
    for ident,values in output.items():
        for symbol,v in values.items():
            for f in FIELDS:assert abs(v['total'][f]-result['diagnosis'][ident][symbol][f])<1e-4
    assert unique_reads==1254,unique_reads
    common.write(target,dict(全合格=True,事後診断専用=True,results=output,詳細対象=list(sorted(detailed)),
        対応='entry判断原seq|side、場商品ごと照合。全共通親のentry/exit row価格qty費用及びnetがexact。',
        全33入力cache読取=33,unique台帳読取=unique_reads,新金融再生=0,原板読取=0,API取得=0,
        SHA256={p.relative_to(common.ROOT).as_posix():common.digest(p) for p in (Path(__file__),plan_path,source)},
        限界=['alias6は同一C_ONLY派生経済。詳細は代表1だけ、6の独立反証へ数えない。',
            'MFEは観測済み清算BBOの事後極値。価格時計は到着時計ではない。',
            '消えた入口は予測拒否/取消だけでなく、別の保有/予約/cooldownも含む。',
            '全親を同じ当時条件に通し、黒字反証と正しい分母を残す。未実行の追加フィルタの利益とは呼ばない。']))
    print('具体損失/5寄与/9月29日と後続診断を保存、金融再生0',flush=True)


if __name__=='__main__':main()
