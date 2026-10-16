"""全38条件の実入力接頭と、未来源変形による過去不変性だけを検査する。"""

import gc
from pathlib import Path

import numpy as np

import support


def subset(material: dict, sessions: list[str]) -> dict:
    """
    機能: 因果検査対象の保存場だけを読み取り参照で接続する。
    引数: material(dict)、sessions(list[str])。
    返り値: dictは旧及び新入力の部分集合。原配列を編集しない。
    """
    value=dict(material)
    for name in ('prices','features','legacy','raw_last_records','execution_lp_index'):
        value[name]={key:item for key,item in material[name].items() if key[0] in sessions}
    for name in ('grids','entries'):
        value[name]={key:material[name][key] for key in sessions}
    for name in ('price_lanes','trend_prices'):
        value[name]={source:{key:lane[key] for key in sessions} for source,lane in material[name].items()}
    return value


def future_signal(signal: dict, cutoff: float, side: str) -> dict:
    """
    機能: 切断後の自己源・相手源・判断状態を独立に変形する。
    引数: signal(dict)、cutoff(float)、side(str:own/peer/state)。
    返り値: dictは未来だけ変えた信号。過去源と入力原本は変更しない。
    """
    result=dict(signal);future=signal['grid']>=cutoff
    observed=signal['loss_observations'].copy()
    columns=(0,1,2,3,4,10,11,12,13,18,20) if side=='own' else (5,6,7,8,9,14,15,16,17,19,21)
    if side!='state':
        for column in columns:
            observed[future,column]=1e8+column
        result['loss_observations']=observed
    else:
        for name in ('mode','raw_mode','arm_common','current_valid','reverse_long','reverse_short'):
            if name in signal:
                changed=signal[name].copy()
                changed[future]=False if changed.dtype==bool else -changed[future]
                result[name]=changed
    return result


def future_price(material: dict, session: str, symbol: str, cutoff: float) -> dict:
    """
    機能: 新LPの未来価格・窓方向・源番号を変形し、候補生成の因果性を調べる。
    引数: material(dict)、session/symbol(str)、cutoff(float)。
    返り値: dictは価格laneだけ部分複製した入力。旧Q・OFIは編集しない。
    """
    output=dict(material);lanes=dict(material['trend_prices']);lane=dict(lanes['I3'])
    price=dict(lane[session]);markets=dict(price['markets']);market=dict(markets[symbol])
    future=price['grid']>=cutoff;current=dict(market['current'])
    for field in ('value','index','raw_seq','time_s'):
        values=current[field].copy();values[future]=1e8;current[field]=values
    current['valid']=current['valid'].copy();current['valid'][future]=False
    windows={}
    for seconds,old in market['windows'].items():
        window=dict(old)
        for field in ('ratio_ret_bp','ret_bp'):
            values=window[field].copy();values[future]=-1e6;window[field]=values
        windows[seconds]=window
    market.update(current=current,windows=windows);markets[symbol]=market
    price['markets']=markets;lane[session]=price;lanes['I3']=lane;output['trend_prices']=lanes
    return output


def main() -> None:
    """
    機能: 5場×両市場の最初1時間だけで38条件の接頭及び未来変形を照合する。
    引数: なし。
    返り値: Noneは前検証証跡。完結場の新損益を計算・集計しない。
    """
    strategy,catalog,data=support.components();material=data.load_inputs()
    sessions=['2026-09-21_Day','2026-09-24_Night','2026-09-29_Day','2026-10-07_Day','2026-10-12_Day']
    material=subset(material,sessions);configs=catalog.catalog();byid={c['id']:c for c in configs}
    counts=dict(短い実経路=0,実接頭=0,未来自己源変形=0,未来相手源変形=0,未来判断状態変形=0,
                新候補未来自己価格変形=0,新候補未来相手価格変形=0,新許可未来価格変形=0)
    horizons=(360,600,900,1200,1500,1800,2100,2400,3000,3600)
    for source in ('P0','P1','P2','P3'):
        prepared=strategy.prepare(material,byid[source+'_R0'])
        selected=[config for config in configs if config['trend_source']==source]
        for key,value in sorted(prepared.items()):
            record,signal=value['record'],value['signal'];start=record['start']
            end=int(np.searchsorted(record['time_s'],start+3600.,side='left'))
            assert end<len(record['time_s']) and record['time_s'][end]<record['limit']-600.
            base_record,base_signal=support.prefix(record,signal,end)
            for config in selected:
                full=strategy.ENGINE.execute(base_record,base_signal,config,finish=False)
                for seconds in horizons:
                    cutoff=start+seconds;stop=int(np.searchsorted(record['time_s'],cutoff,side='left'))
                    r,s=support.prefix(record,signal,stop)
                    part=strategy.ENGINE.execute(r,s,config,finish=False)
                    support.prefix_equal(full,part,stop);counts['実接頭']+=1
                    for side,label in (('own','未来自己源変形'),('peer','未来相手源変形'),('state','未来判断状態変形')):
                        poisoned=future_signal(s,cutoff,side)
                        changed=strategy.ENGINE.execute(r,poisoned,config,finish=False)
                        support.prefix_equal(full,changed,stop);counts[label]+=1
                counts['短い実経路']+=1
                del full
            # ----------------------------------------
            # 売買再生と別に、候補の時計及びJ2許可の未来入力への不依存を検査する。
            for seconds in horizons:
                cutoff=start+seconds;price=material['trend_prices']['I3'][key[0]]
                past_grid=price['grid']<cutoff
                for altered,label in ((key[1],'新候補未来自己価格変形'),
                    ('NK225' if key[1]=='TOPIX' else 'TOPIX','新候補未来相手価格変形')):
                    poisoned=future_price(material,key[0],altered,cutoff)
                    wanted=strategy.lp_allowed(price,material['grids'][key[0]])
                    got=strategy.lp_allowed(poisoned['trend_prices']['I3'][key[0]],material['grids'][key[0]])
                    for side in (-1,1):np.testing.assert_array_equal(wanted[side][past_grid],got[side][past_grid])
                    counts['新許可未来価格変形']+=1
                    if source in ('P2','P3'):
                        changed=strategy.lp_candidates(key,poisoned,source,signal)
                        original=value['trend_candidate_state'];past=price['candidate_grid']<cutoff
                        for name in ('states','valid','pulse','own_source','peer_source'):
                            np.testing.assert_array_equal(original[name][past],changed[name][past])
                        stop=int(np.searchsorted(record['time_s'],cutoff,side='left'))
                        rows=original['candidates'];changed_rows=changed['candidates']
                        np.testing.assert_array_equal(rows[rows[:,1]<stop],changed_rows[changed_rows[:,1]<stop])
                        counts[label]+=1
            print(source+' '+key[0]+' '+key[1]+' 接頭10時点・未来3種と候補/許可の因果性が一致',flush=True)
        del prepared;gc.collect()
    assert counts['短い実経路']==380 and counts['実接頭']==3800
    support.save('全38実入力の5場両市場と10接頭及び四源未来変形と候補許可の不変.json',
        dict(全合格=True,対象場=sessions,対象分数=[seconds/60 for seconds in horizons],完結新損益計算=0,**counts),
        [Path(__file__),Path(data.__file__),*material['paths']])


if __name__=='__main__':
    main()
