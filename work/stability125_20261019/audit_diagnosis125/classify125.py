"""保存会計だけから入口・出口・利益返し・実撤回距離を敵対的に切り分ける。"""

from collections import defaultdict
from io import BytesIO
import hashlib
import json
from pathlib import Path

import numpy as np


HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]
EXPECTED='2ef627501c50359baadc6bbfa343d372c882f2b0f39fdbb1de8019fb02fdf19b'


def saved(path: Path,expected: str|None=None) -> tuple[dict,dict]:
    """
    機能: 完成した保存小JSONを指紋拘束して所有複写する。
    引数: path(Path)、expected(str|None)は対象と既知SHA。
    返り値: tuple[dict,dict]は内容と参照。金融再生・原市場は使用しない。
    """
    payload=path.read_bytes();sha=hashlib.sha256(payload).hexdigest()
    assert expected is None or sha==expected
    target=HERE/'owned'/path.name;target.parent.mkdir(parents=True,exist_ok=True)
    assert not target.exists();target.write_bytes(payload)
    return json.loads(payload),dict(path=path.relative_to(ROOT).as_posix(),sha256=sha)


def stats(rows: list[dict]) -> dict:
    """
    機能: 完結groupの損益・順行後損失・逆行を集計する。
    引数: rows(list[dict])は同商品・政策又は同入口出口のgroup。
    返り値: dictは件数・金額と明示分母。分類同士の重複を排除した確率とは呼ばない。
    """
    losses=[r for r in rows if r['net']<0];positive=[r for r in losses if r['mfe']>0]
    armable=[r for r in positive if not r['added'] and r['mfe']>=r['trail_arm_yen']-1e-6]
    risks=[r['cost_to_stop_ratio'] for r in rows if r['cost_to_stop_ratio'] is not None]
    return dict(groups=len(rows),net=sum(r['net'] for r in rows),profit=sum(max(0.,r['net']) for r in rows),
        loss=sum(max(0.,-r['net']) for r in rows),wins=sum(r['net']>0 for r in rows),losses=len(losses),
        never_positive_losses=len(losses)-len(positive),never_positive_loss_net=sum(r['net'] for r in losses if r['mfe']<=0),
        positive_then_losses=len(positive),positive_then_loss_net=sum(r['net'] for r in positive),
        noadd_positive_loss_below_arm=sum(not r['added'] and r['mfe']<r['trail_arm_yen']-1e-6 for r in positive),
        noadd_positive_loss_reached_arm=len(armable),reached_arm_loss_net=sum(r['net'] for r in armable),
        added_groups=sum(r['added'] for r in rows),nonpositive_initial_stop_width=sum(r['effective_stop_width']<=0 for r in rows),
        decision_spread_gt_half_actual_stop=sum(r['cost_to_stop_ratio'] is not None and r['cost_to_stop_ratio']>.5 for r in rows),
        decision_last_directional_gross=sum(r['decision_last_directional_gross'] for r in rows),
        entry_vs_decision_last_drag=sum(r['entry_vs_decision_last_drag'] for r in rows),
        exit_vs_decision_last_drag=sum(r['exit_vs_decision_last_drag'] for r in rows),
        complete_decision_last_parts=sum(r['decision_last_complete'] for r in rows),
        stop_cost_ratio_median=float(np.median(risks)) if risks else None)


def main() -> None:
    """
    機能: 保存82NPZの注文・完結群だけを各一読し、24商品条件を分類する。
    引数: なし。
    返り値: None。価格入力・原本・金融・API・試行台帳への変更は0。
    """
    result,result_ref=saved(WORK/'十二条件と二商品全四十一場の会計.json',EXPECTED)
    diagnosis,diag_ref=saved(WORK/'diagnosis125.json')
    assert result['passed'] and diagnosis['passed'] and diagnosis['source_result']['sha256']==EXPECTED
    assert len(result['rows'])==984 and len(result['cache'])==82
    oi={k:i for i,k in enumerate(result['order_columns'])};ti={k:i for i,k in enumerate(result['trade_columns'])}
    spec_map={s['id']:s for s in result['specs']};all_groups=[];read_log=[];positions={}
    session_map={(r['symbol'],r['session'],r['method']):r for r in result['rows']}
    for ref in result['cache']:
        payload=(ROOT/ref['path']).read_bytes();assert hashlib.sha256(payload).hexdigest()==ref['sha256']
        read_log.append(dict(path=ref['path'],sha256=ref['sha256'],reads=1,arrays='全12条件のorders/tradesだけ'))
        with np.load(BytesIO(payload),allow_pickle=False) as source:
            for spec in result['specs']:
                method=spec['id'];o=source[method+'__orders'];t=source[method+'__trades']
                row=session_map[ref['symbol'],ref['session'],method]
                assert np.isfinite(o).all() and np.isfinite(t).all() and np.all(o[:,oi['fee']]==0)
                assert np.all(t[:,ti['entry_fees']]==0) and np.all(t[:,ti['exit_fee']]==0)
                assert np.sum(t[:,ti['net']])==row['net'] and len(t)==row['groups']
                for trade in t:
                    gid=int(trade[ti['group_id']]);group=o[o[:,oi['group_id']]==gid]
                    entries=group[group[:,oi['kind']]==1];exits=group[group[:,oi['kind']]==2]
                    assert len(entries)>=1 and len(exits)==1-int(trade[ti['proxy_flag']])
                    first=entries[0];side=int(trade[ti['side']]);mult=1000. if ref['symbol']=='TOPIX' else 10.
                    quantity=float(trade[ti['quantity']]);stop=float(trade[ti['initial_stop']]);price=float(first[oi['price']])
                    effective=side*(price-stop);spread=float(first[oi['decision_ask']]-first[oi['decision_bid']])
                    initial_w=float(trade[ti['initial_w']]);net=float(trade[ti['net']]);mfe=float(trade[ti['mfe']])
                    decision_direction=entry_drag=exit_drag=0.;parts_complete=len(exits)==1
                    if parts_complete:
                        cost=sum(e[oi['decision_last']]*e[oi['quantity']] for e in entries)
                        exit_last=exits[0,oi['decision_last']]
                        decision_direction=side*(exit_last*quantity-cost)*mult
                        entry_drag=side*sum((e[oi['price']]-e[oi['decision_last']])*e[oi['quantity']] for e in entries)*mult
                        exit_drag=side*(exit_last-trade[ti['exit_price']])*quantity*mult
                        assert abs(decision_direction-entry_drag-exit_drag-net)<1e-5
                    all_groups.append(dict(symbol=ref['symbol'],session=ref['session'],method=method,group_id=gid,
                        side=side,quantity=quantity,first_quantity=float(first[oi['quantity']]),first_price=price,
                        first_fill_row=int(first[oi['fill_row']]),first_time=float(first[oi['fill_time']]),
                        exit_time=float(trade[ti['exit_time']]),entry_reason=int(trade[ti['entry_reason']]),
                        exit_reason=int(trade[ti['exit_reason']]),net=net,mfe=mfe,mae=float(trade[ti['mae']]),
                        initial_w=initial_w,initial_stop=stop,effective_stop_width=effective,decision_spread=spread,
                        cost_to_w_ratio=spread/initial_w,cost_to_stop_ratio=spread/effective if effective>0 else None,
                        added=len(entries)>1,trail_arm_yen=spec['trail_start_w']*initial_w*quantity*mult,
                        decision_last_complete=parts_complete,decision_last_directional_gross=decision_direction,
                        entry_vs_decision_last_drag=entry_drag,exit_vs_decision_last_drag=exit_drag))
                positions[(ref['symbol'],ref['session'],method)]=dict(max_long=row['max_long'],max_short=row['max_short'],
                    unclosed=row['summary']['unclosed_quantity'])
    aggregates={};pairs=[]
    for method in spec_map:
        aggregates[method]={}
        for symbol in ('TOPIX','NK225'):
            own=[r for r in all_groups if r['method']==method and r['symbol']==symbol]
            original=[r for r in result['rows'] if r['method']==method and r['symbol']==symbol]
            assert sum(r['net'] for r in own)==sum(r['net'] for r in original)
            assert len(own)==sum(r['groups'] for r in original)
            aggregates[method][symbol]=dict(all=stats(own),
                entry={str(k):stats([r for r in own if r['entry_reason']==k]) for k in sorted({r['entry_reason'] for r in own})},
                exit={str(k):stats([r for r in own if r['exit_reason']==k]) for k in sorted({r['exit_reason'] for r in own})})
    for family in ('A','B','C'):
        for symbol in ('TOPIX','NK225'):
            base=[r for r in all_groups if r['method']==family+'00' and r['symbol']==symbol]
            added=[r for r in all_groups if r['method']==family+'01' and r['symbol']==symbol]
            key=lambda r:(r['session'],r['side'],r['first_fill_row'],r['entry_reason'])
            bm={key(r):r for r in base};am={key(r):r for r in added};common=set(bm)&set(am)
            pairs.append(dict(family=family,symbol=symbol,base_net=sum(r['net'] for r in base),add_net=sum(r['net'] for r in added),
                policy_change=sum(r['net'] for r in added)-sum(r['net'] for r in base),base_groups=len(base),add_groups=len(added),
                matching_first_entries=len(common),common_net_change=sum(am[k]['net']-bm[k]['net'] for k in common),
                added_onto_common=sum(am[k]['added'] for k in common),
                five_worst_common_changes=[dict(session=k[0],side=k[1],first_fill_row=k[2],
                    base_net=bm[k]['net'],add_net=am[k]['net'],change=am[k]['net']-bm[k]['net'],
                    base_quantity=bm[k]['quantity'],add_quantity=am[k]['quantity'])
                    for k in sorted(common,key=lambda k:am[k]['net']-bm[k]['net'])[:5]],
                limitation='00→01は追加許可だけの政策対照。ただし追加は平均建値・停止線・退出時刻・後続参加も変え、全差額を共通親の数量だけの直接効果とはしない。'))
    specific=[]
    for detail in diagnosis['details']:
        copied=[]
        for trade in detail['trades']:
            match=[r for r in all_groups if r['symbol']==detail['symbol'] and r['session']==detail['session']
                and r['method']==detail['method'] and r['group_id']==trade['group_id']]
            assert len(match)==1 and match[0]['net']==trade['net']
            assert abs(trade['last_directional_gross']-trade['entry_drag']-trade['exit_drag']-trade['fees']-trade['net'])<1e-5
            copied.append(dict(trade,geometry=match[0]))
        specific.append(dict(detail,trades=copied))
    output=dict(passed=True,references=[result_ref,diag_ref],aggregates=aggregates,addition_pairs=pairs,
        details=specific,groups=all_groups,read_log=read_log,
        all_groups_count=len(all_groups),saved_account_cache_reads=82,price_input_reads=0,original_market_reads=0,
        financial_replays=0,API=0,real_orders=0,
        caveats=['入口と出口の分類は直交する。二表の損失件数を足さない。',
            '全群の方向寄与は判断時Lastで、そこから実約定までの時間変化とBBO対Last差をdragへ含める。真のspreadだけの原因とは呼ばない。',
            '最悪6場の抽出群だけはroot診断の実fill行Last分解を引用。全41場の実fillLast分解とは分ける。',
            'MFEからnetへの差は後から見た利益返しで、そのまま機械で回収できた利益額ではない。',
            '初期撤回幅と判断spread比は時点が異なる。事後診断であり、その比を使う新しい注文取消しの効果は未測定。',
            '有料旧条件と今回無料・異入口・純建玉の差を、両建て解除だけの因果効果とはしない。'])
    target=HERE/'全十二条件の入口出口と順行返し及び実撤回距離.json';assert not target.exists()
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,path=target.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        groups=len(all_groups),C00={s:aggregates['C00'][s]['all'] for s in ('TOPIX','NK225')},pairs=pairs),ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
