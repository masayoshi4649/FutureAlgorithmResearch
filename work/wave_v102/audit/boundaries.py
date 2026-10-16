"""新門番の拒否後保持と、予約後の悪fill・未知源・期限を人工原板で独立反証する。"""

from pathlib import Path
import traceback
import numpy as np

import artificial
import common
import financial
import runtime_oracle
import support


def profile(symbol: str, side: int, config: dict, name: str) -> tuple[dict,dict]:
    """
    機能: 独立oracleが定めた最初追加予約の直後だけを変形し、因果順の正負入力を作る。
    引数: symbol(str)、side(int)は±1、config(dict)、name(str)は有限の意味境界名。
    返り値: tuple[dict,dict]。人工原板及び変形対象の判断行。実本体出力又は損益から行を選ばない。
    """
    value=artificial.fixture(symbol,1)
    expected=runtime_oracle.replay(value,config)
    reservation=next(item for item in expected['decisions'] if item['kind'] == '追加予約')
    row=reservation['row']
    next_row=row+1
    first=int(expected['orders'][0,0])
    record,signal=value['record'],value['signal']
    scale=1. if symbol == 'TOPIX' else 20.
    if name == '悪い次実fill':
        record['ask'][next_row]=record['ask'][next_row]+100.*scale
        record['price'][next_row]=(record['bid'][next_row]+record['ask'][next_row])*.5
    elif name == '予約後の資格悪化':
        signal['reset'][next_row],signal['quality'][next_row]=True,False
        signal['entry_peer_bbo'][next_row,5]=0.
    elif name == '初回実fillの未知peer':
        signal['entry_peer_bbo'][first,5]=0.
    elif name == '初回期限と追加':
        deadline=record['time_s'][first]+config['trend_hold_seconds']
        assert config['trend_hold_seconds'] > 0 and deadline > record['time_s'][next_row]
        record['time_s'][next_row:]+=deadline-record['time_s'][next_row]
        record['limit']=float(record['time_s'][-1])
        signal['grid']=record['time_s'].copy()
        signal['entry_peer_bbo'][:,2]=record['time_s']-1.
    elif name == '場末と追加':
        # 予約時はcut未到達、次行でforce成立。新規cutと60秒前forceを混同しない。
        record['limit']=float(record['time_s'][row]+301.)
        force=record['limit']-60.
        record['time_s'][next_row:]+=force-record['time_s'][next_row]
        signal['grid']=record['time_s'].copy()
        signal['entry_peer_bbo'][:,2]=record['time_s']-1.
    elif name != '拒否後の正常継続':
        raise AssertionError(name)
    if side == -1:
        center=value['reference_open']
        old_bid=record['bid'].copy()
        record['bid'],record['ask']=2*center-record['ask'],2*center-old_bid
        record['price']=2*center-record['price']
        signal['event'] *= -1
        peer=signal['entry_peer_bbo']
        peer_center=80000. if symbol == 'TOPIX' else 4000.
        old_bid=peer[:,3].copy()
        peer[:,3],peer[:,4]=2*peer_center-peer[:,4],2*peer_center-old_bid
    helper=common.module('102人工境界の不変LP素材',common.ROOT/'work/wave_v99/engine_preflight/support.py')
    key=record['session'],symbol
    helper.attach_support({key:value})
    support.verify_material(key,value['artificial_support_material'],value)
    assert (record['bid'] > 0).all() and (record['ask'] > record['bid']).all()
    return value,dict(初回実fill=first,最初追加判断=row,その次原行=next_row)


def main() -> None:
    """
    機能: T0及びT1の予約競合と拒否後継続を、両商品・買売反射で独立比較する。
    引数: なし。本体/sourceの完成通知後だけ実行する。
    返り値: None。不合格は原因と開始指紋を別保存。正式損益を生成しない。
    """
    catalog=common.module('102独立境界条件',common.BASE/'catalog.py')
    strategy=common.module('102独立境界戦略',common.BASE/'strategy.py')
    configs=[config for config in catalog.catalog() if config['id'] in ('B1_T0_Q1_X1','B1_T1_Q1_X1')]
    names=('悪い次実fill','予約後の資格悪化','初回実fillの未知peer',
           '初回期限と追加','場末と追加','拒否後の正常継続')
    paths=[common.BASE/name for name in ('engine.py','strategy.py','catalog.py','結果前の設計案.json')]
    paths += [common.HERE/name for name in ('common.py','math_oracle.py','compare_utils.py','financial.py',
        'support.py','watch.py','runtime_oracle.py','artificial.py','boundaries.py')]
    signatures=common.fingerprints(paths)
    results=[]
    for config in configs:
        for name in names:
            for symbol in common.SYMBOLS:
                for side in (1,-1):
                    try:
                        value,where=profile(symbol,side,config,name)
                        key=value['record']['session'],symbol
                        output=strategy.play(config,key,{key:value})
                        runtime_oracle.compare(value,config,output)
                        financial.verify_account(value['record'],config,output)
                        orders=output['orders']
                        adds=orders[orders[:,8] == 16]
                        trace=output['growth_gate_state_trace']
                        row,next_row=where['最初追加判断'],where['その次原行']
                        if name in ('悪い次実fill','予約後の資格悪化'):
                            assert len(adds) and adds[0,1] == row and adds[0,0] == next_row
                            if name == '悪い次実fill':
                                assert trace[next_row,18] == 1 and orders[-1,1] == next_row
                                assert orders[-1,0] == next_row+1
                        elif name == '初回実fillの未知peer':
                            events=output['growth_events']
                            baselines=events[events[:,1] == 5]
                            assert len(baselines) and baselines[0,0] == where['初回実fill']+1
                            assert not ((events[:,0] == baselines[0,0]) & (events[:,1] == 2)).any()
                        elif name == '初回期限と追加':
                            assert len(adds) == 0 and output['trades'][0,5] == 1
                            assert orders[-1,1] == next_row and orders[-1,8] == 3
                        elif name == '場末と追加':
                            assert len(adds) == 0 and orders[-1,8] == 4
                            assert orders[-1,0] == next_row and orders[-1,10] == value['record']['limit']-60.
                        else:
                            denied=np.flatnonzero((trace[:,13] == 1) & (trace[:,14] == 0))
                            accepted=np.flatnonzero(trace[:,14] == 1)
                            assert len(denied) and len(accepted) and denied[0] < accepted[0]
                            assert adds[0,1] == accepted[0]
                        results.append(dict(条件=config['id'],境界=name,商品=symbol,方向=side,
                            生成基準=where,注文=len(orders),追加=len(adds),純損益=float(output['trades'][0,11])))
                    except Exception as error:
                        serial=1
                        failure=common.HERE/f'独立境界不合格_{serial:05d}.json'
                        while failure.exists():
                            serial+=1
                            failure=common.HERE/f'独立境界不合格_{serial:05d}.json'
                        common.save(failure,dict(合格=False,条件=config['id'],境界=name,商品=symbol,方向=side,
                            完了件数=len(results),原因=str(error),詳細=traceback.format_exc(),
                            正式102損益=0,API取得=0,実注文=0,SHA256=signatures))
                        raise
    assert len(results) == 48 and common.fingerprints(paths) == signatures
    common.save(common.HERE/'余裕拒否後の継続と据置後の実fill悪化及び予約競合の独立境界.json',dict(
        合格=True,人工境界=48,線政策=2,意味境界=6,結果=results,
        範囲='人工原候補を独立再生した最初追加判断の後だけを変形。将来本体結果から最初判断を選ばない。',
        状態の範囲='保有11数理と新19全列は独立。旧70補助flags全列は保存復元と区別する。',
        金融本体変更=0,正式102損益=0,API取得=0,実注文=0,SHA256=signatures))
    print('48境界: T0/T1の拒否後継続・悪fill・資格・未知・期限・場末が独立一致。',flush=True)


if __name__ == '__main__':
    main()
