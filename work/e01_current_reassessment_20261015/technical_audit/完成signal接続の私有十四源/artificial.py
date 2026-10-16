"""合成rawと独立実UID会計だけで九条件・閉足・支持・接頭・保存統合を検査する。"""

from copy import deepcopy
import json
import traceback

import common
import numpy as np
import catalog
import core
import interface
import normal_reference
import signals
import volume_reference


def fixture(side: int=1,n: int=450) -> tuple[dict,dict]:
    """
    機能: rawの正出来高増/Last対直前BBOからcanonical三窓票を作る小素材を生成する。
    引数: side(int:±1)、n(int) は方向反射と行数。
    返り値: tuple[dict,dict] は同原行TradeGate/TradeExit型。実入力を読まない。
    """
    gate=dict(schema_version=1,session='合成_Day',accounts={});exit_packet=dict(schema_version=1,session='合成_Day',accounts={})
    for symbol in ('TOPIX','NK225'):
        tick=.5 if symbol=='TOPIX' else 10.;base=4000. if symbol=='TOPIX' else 70000.;index=np.arange(n)
        offset=np.maximum(0,index-59).astype(float)
        for row in (67,75,87,105):offset[row:]-=1
        buy_bid=base-tick/2+offset*tick;buy_ask=buy_bid+tick;buy_last=buy_ask.copy()
        for row in (67,75,87,105):buy_last[row]=buy_bid[row-1]
        bid=buy_bid if side>0 else 2*base-buy_ask;ask=buy_ask if side>0 else 2*base-buy_bid
        last=buy_last if side>0 else 2*base-buy_last
        times=index.astype(float)*5.;times-=0.1 if symbol=='NK225' else 0.
        seq=index.astype(np.int64)+1000;mapping=index.astype(np.int64)
        raw=dict(raw_seq=seq.copy(),price_time_s=times.copy(),last=last.copy(),bid=bid.copy(),ask=ask.copy(),
            volume_delta=np.ones(n),volume_delta_usable=np.ones(n,bool),volume_reset_reason=np.zeros(n,np.uint8))
        raw['volume_delta_usable'][0]=False;ctx=volume_reference.context(raw)
        record=dict(price=last.copy(),seq=seq.copy(),time_s=times.copy(),start=0.,end=2100.,limit=2100.,tick=tick)
        quotes=dict(bid=bid.copy(),ask=ask.copy(),quote_valid=np.ones(n,bool),seq=seq.copy(),time_s=times.copy())
        account=dict(symbol=symbol,record=record,quotes=quotes,feed=np.zeros((0,10)),quiet=np.zeros(n,bool),quiet_force=np.zeros(n,bool),
                     mapping=mapping,trade_features={w:{} for w in ('10','30','60')})
        gate['accounts'][symbol]=account
        exit_packet['accounts'][symbol]=dict(symbol=symbol,record=deepcopy(record),quotes=deepcopy(quotes),
            votes={w:normal_reference.all_normal(raw,ctx,mapping,int(w)) for w in ('10','30','60')})
    return gate,exit_packet


def prefix(gate: dict,exit_packet: dict,length: int) -> tuple[dict,dict]:
    """
    機能: 合成入力の全行配列を接頭へ切る。
    引数: gate/exit_packet(dict)、length(int) は素材と接頭長。
    返り値: tuple[dict,dict] は同値の接頭。将来足高安や原行を補完しない。
    """
    g,e=deepcopy(gate),deepcopy(exit_packet)
    for s in catalog.CAP:
        for a in (g['accounts'][s],e['accounts'][s]):
            for key in ('record','quotes'):
                for name,value in a[key].items():
                    if isinstance(value,np.ndarray):a[key][name]=value[:length].copy()
        a=g['accounts'][s]
        for name in ('mapping','quiet','quiet_force'):a[name]=a[name][:length].copy()
        for v in e['accounts'][s]['votes'].values():
            for name in v:v[name]=v[name][:length].copy()
    return g,e


def arrays(left: dict,right: dict) -> int:
    """
    機能: Python/JITの注文・UID・全行実会計・公開・支持・判断を一致させる。
    引数: left/right(dict) は同一条件の実出力。
    返り値: int は比較配列数。
    """
    names=('orders','order_uids','exit_target_uids','economic_curve','publication_events','exit_judgments','execution_events','actual_origins','support_events')
    for name in names:np.testing.assert_array_equal(left[name],right[name],err_msg=name)
    assert left['summary']==right['summary'] and left['parent_diagnostics']==right['parent_diagnostics']
    return len(names)


def run() -> dict:
    """
    機能: 合成両商品/買売/九条件で実order会計・閉足・支持更新・未来接頭・JSONを検査する。
    引数: なし。
    返り値: dict は検査数。実入力/金融/原板/APIは0。
    """
    comparisons=0;accounts=0;prefixes=0;supports=0;configs=catalog.configs()
    assert json.loads(json.dumps(configs,allow_nan=False))==configs
    for side in (1,-1):
        gate,ex=fixture(side);prepared=interface.prepare(gate,ex,python=True,initial_capacity=2)
        compiled=interface.prepare(gate,ex,initial_capacity=2)
        for s in catalog.CAP:
            for name in ('candidates','breakpoints','consumed','retired'):
                np.testing.assert_array_equal(prepared[s][name],compiled[s][name]);comparisons+=1
            candidates=prepared[s]['candidates'];assert len(candidates)>0 and np.all(candidates[:,12]<candidates[:,6]) and np.all(candidates[:,6]<candidates[:,0])
            third=candidates[candidates[:,1]==2]
            assert len(third)>0 and np.all(third[:,9]>third[:,6]) and np.all(third[:,9]<third[:,0]);comparisons+=2
            for config in configs:
                a=interface.play(gate['accounts'][s],prepared[s],config,gate['session'],python=True,initial_capacity=2)
                b=interface.play(gate['accounts'][s],compiled[s],config,gate['session'],initial_capacity=2)
                comparisons+=arrays(a,b);accounts+=1
                assert len(a['parent'])>0 and all(p['枚数']==catalog.CAP[s] for p in a['parent'])
                assert np.all(a['orders'][:,1]<a['orders'][:,0]) and np.all(a['orders'][:,4]==catalog.CAP[s])
                assert all(p['fees_yen']==2*(catalog.CAP[s]*catalog.FEE_RATIO[s][0]//catalog.FEE_RATIO[s][1]) for p in a['parent_diagnostics'])
                for parent in a['parent_diagnostics']:
                    assert parent['entry_response_proof_row']<parent['entry']['row']
                    for update in parent['support_events']:
                        assert update[5]>parent['entry']['row'] and side*(update[4]-update[3])>=0;supports+=1
                json.dumps(a['parent_diagnostics'],ensure_ascii=False,allow_nan=False)
                json.dumps(interface.finite(dict(publications=a['publication_events'],judgments=a['exit_judgments'],support=a['support_events'])),allow_nan=False)
            # ----------------------------------------
            # 接頭へ将来bucket/quoteを持ち込まない。実出力は接頭の未予約次quoteを足さない。
        full=prepared
        for length in (60,61,63,68,71,90,180,301):
            g,e=prefix(gate,ex,length);part=interface.prepare(g,e,python=True,initial_capacity=2)
            for s in catalog.CAP:
                for name in ('high','low','bucket_id','confirmed_row'):np.testing.assert_array_equal(part[s]['bar'][name],full[s]['bar'][name][:length]);comparisons+=1
                expected=full[s]['candidates'][full[s]['candidates'][:,0]<length]
                np.testing.assert_array_equal(part[s]['candidates'],expected);comparisons+=1;prefixes+=1
                for config in configs:
                    result=interface.play(g['accounts'][s],part[s],config,g['session'],finish=False,python=True,initial_capacity=2)
                    complete=interface.play(gate['accounts'][s],full[s],config,gate['session'],python=True,initial_capacity=2)
                    for name in ('orders','publication_events','support_events','exit_judgments','execution_events'):
                        expected=complete[name][complete[name][:,0]<length]
                        np.testing.assert_array_equal(result[name],expected);comparisons+=1
                    np.testing.assert_array_equal(result['economic_curve'],complete['economic_curve'][:length]);comparisons+=1
                    json.dumps(result['parent_diagnostics'],ensure_ascii=False,allow_nan=False)
    assert supports>0
    return dict(全合格=True,九条件の両商品買売口座=accounts,配列照合=comparisons,閉足と状態の接頭=prefixes,保有後の新支持確認=supports,
        JSON全保存統合=True,私有PythonJIT同値=True,個別料金と実UID会計=True,実cache=0,金融=0,原板=0,API=0)


def main() -> None:
    """
    機能: source完成時の所有人工を実行し成功/Falseを別保存する。
    引数: なし。
    返り値: None。正式freeze/register/金融を開始しない。
    """
    before=common.sources()
    try:
        value=run();assert before==common.sources();value['source_SHA256']=before
        common.write('確定閉足と現在九Native及び実料支持接頭の人工検査.json',value)
        print('九Native SOURCE_ONLY人工合格 '+str(value['配列照合'])+' 配列、実入力/金融/API0',flush=True)
    except Exception:
        common.write('人工False.json',dict(全合格=False,source_SHA256=before,原因=traceback.format_exc(),実入力=0,金融=0,API=0,自動再開始=False));raise


if __name__=='__main__':main()
