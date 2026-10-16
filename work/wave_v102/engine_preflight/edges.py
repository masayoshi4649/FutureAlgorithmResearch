"""初期幅余裕と据置の拒否・実fill・期限を、少数人工で検査する。"""

import copy
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from support import HERE, ROOT, WORK, attach_support, load
from selfcheck import prepared_fixture, run


def late_fixture(config: dict, symbol: str, side: int, change_row: int) -> dict:
    """
    機能: 初回を通常時に建て、指定した後半行で追加資格を生む人工素材を作る。
    引数: config(dict)、symbol(str)、side/change_row(int)。
    返り値: dict。一つの人工口座。実データを読み込まない。
    """
    data = prepared_fixture(config, symbol, side)
    key = next(iter(data)); current = data[key]
    record, signal = current['record'], current['signal']
    size, base, tick = 3001, current['reference_open'], record['tick']
    width = max(2, math.ceil(base*.001/tick-1e-10))*tick
    progress = np.zeros(size); progress[340:] = .5; progress[change_row:] = 10.
    quote = base+(tick if side == 1 else 0.)+side*np.round(progress*width/tick)*tick
    record.update(time_s=np.arange(size,dtype=float), seq=np.arange(size,dtype=np.int64)+1000,
        price_valid=np.ones(size,bool), quote_valid=np.ones(size,bool), limit=3000., end=3100.,
        bid=quote-tick if side == 1 else quote.copy(), ask=quote.copy() if side == 1 else quote+tick)
    record['price'] = .5*(record['bid']+record['ask'])
    grid=np.arange(300.,3001.,5.); source=grid.astype(int)-1
    event=np.zeros(size,np.int8); event[330]=side
    mapped=np.full(size,-1,np.int32); mapped[grid.astype(int)]=np.arange(len(grid),dtype=np.int32)
    peer_base, peer_tick=(50000.,10.) if symbol=='TOPIX' else (4000.,.5)
    peer_width=max(2,math.ceil(peer_base*.001/peer_tick-1e-10))*peer_tick
    peer_quote=peer_base+(peer_tick if side==1 else 0.)+side*np.round(progress*peer_width/peer_tick)*peer_tick
    peer_bid=peer_quote-peer_tick if side==1 else peer_quote
    peer_ask=peer_quote if side==1 else peer_quote+peer_tick
    signal.update(grid=grid, mapped=mapped, event=event, quality=np.ones(size,bool), reset=np.zeros(size,bool),
        mode=np.zeros(len(grid),np.int8), entry_j2_long=np.ones(len(grid),bool), entry_j2_short=np.ones(len(grid),bool),
        wait_opposite_long=np.zeros(len(grid),bool), wait_opposite_short=np.zeros(len(grid),bool),
        entry_peer_bbo=np.column_stack((source,source+9000,source.astype(float),peer_bid[source],peer_ask[source],np.ones(len(grid)))))
    return attach_support({key:current})


def first_addition(output: dict) -> tuple[int, int]:
    """
    機能: 人工で実際に成立した最初の追加の判断行と実約定行を取り出す。
    引数: output(dict)は人工出力。
    返り値: tuple[int,int]。将来を用いた本番判定ではなく競合検査の境界設定だけに使う。
    """
    rows=output['growth_cohorts'][output['growth_cohorts'][:,23]==1]
    assert len(rows)
    return int(rows[0,5]), int(rows[0,8])


def main() -> None:
    """
    機能: B/T1の拒否と成行・通常追尾・未知・期限の順序を人工だけで保存する。
    引数: なし。
    返り値: None。102の正式損益と実接頭を実行せず、旧領域を変更しない。
    """
    paths=[Path(__file__),HERE/'support.py',HERE/'selfcheck.py',WORK/'engine.py',WORK/'strategy.py',WORK/'catalog.py']
    beginning={str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    strategy=load('102境界の現在実行',WORK/'strategy.py')
    catalog=load('102境界の有限20',WORK/'catalog.py')
    configs={value['id']:value for value in catalog.catalog()}
    config=configs['B1_T1_Q1_X3']
    counts=dict(T1悪い次正常fillを保持=0,拒否後も同親同基準で再判定=0,
        当該通常追尾更新後を比較=0,未知初回peer復帰同行を禁止=0,
        初回期限は追加fillより先=0,場末は追加fillより先=0,
        entry_cut後の既予約追加は実fill=0,予約後支持悪化でも実fill=0,
        active床だけでT1拒否=0)
    facts=[]
    for symbol in catalog.SYMBOLS:
        for side in (1,-1):
            data=prepared_fixture(config,symbol,side); key=next(iter(data)); value=data[key]
            normal=run(strategy,config,copy.deepcopy(data)); gate=normal['growth_gate_state_trace']
            state=normal['growth_state_trace']; decision,fill=first_addition(normal)
            reject=np.flatnonzero((gate[:,13]==1)&(gate[:,10]==1)&(gate[:,12]==0))
            assert len(reject) and reject[0]<decision
            first=int(reject[0])
            assert np.all(state[first:decision+1,0]==state[first,0])
            assert np.all(state[first:decision+1,2]==1)
            np.testing.assert_array_equal(state[first:decision+1,50:60],
                np.broadcast_to(state[first,50:60],(decision-first+1,10)))
            assert np.all(state[first:decision+1,6]==state[first,6])
            counts['拒否後も同親同基準で再判定']+=1
            ordinary=np.flatnonzero((gate[1:,14]==1)&(side*(gate[1:,6]-state[:-1,24])>0))+1
            assert len(ordinary), '現在原行の通常追尾更新を許す正例がありません'
            row=int(ordinary[0]); assert gate[row,6]==state[row,24] and gate[row,7]==gate[row,6]
            counts['当該通常追尾更新後を比較']+=1

            # ----------------------------------------
            # 次気配は正常な1呼値spreadのまま不利に動かし、実約定を巻き戻さない。
            width=gate[decision,4]
            value['record']['bid'][fill]+=side*20.*width
            value['record']['ask'][fill]+=side*20.*width
            value['record']['price'][fill]=.5*(value['record']['bid'][fill]+value['record']['ask'][fill])
            data=attach_support(data)
            bad=run(strategy,config,data)
            assert first_addition(bad)==(decision,fill)
            observed=bad['growth_gate_state_trace'][fill]
            assert observed[15]==1 and observed[18]==1 and side*(observed[17]-observed[16])>0
            cohort=bad['growth_cohorts'][1]
            assert cohort[11]==value['record']['ask' if side==1 else 'bid'][fill]
            assert bad['growth_parent_diagnostics'][0,19]>=bad['growth_parent_diagnostics'][0,18]
            assert bad['growth_gate_state_trace'][fill,14]!=1
            counts['T1悪い次正常fillを保持']+=1
            facts.append(dict(商品=symbol,方向=side,追加判断=decision,実追加=fill,
                実追加前線=float(observed[16]),実追加後線=float(observed[17]),
                不利実fillの線変更=True,実超過=float(bad['growth_parent_diagnostics'][0,18])))

            # ----------------------------------------
            # 既予約は支持・品質・reset悪化だけでは取消しない。
            data=prepared_fixture(config,symbol,side);value=data[key]
            next_grid=int(value['signal']['grid'][np.searchsorted(value['signal']['grid'],decision,side='right')])
            value['record']['quote_valid'][fill:next_grid]=False
            latest=np.searchsorted(value['signal']['grid'],next_grid,side='right')-1
            value['signal']['quality'][next_grid]=False;value['signal']['reset'][next_grid]=True
            value['signal']['entry_peer_bbo'][latest,5]=0.
            value['trend_lp_allowed'][1][latest]=False;value['trend_lp_allowed'][-1][latest]=False
            altered=run(strategy,config,data)
            assert first_addition(altered)==(decision,next_grid)
            counts['予約後支持悪化でも実fill']+=1

            # ----------------------------------------
            # 最初の新規予約は過去判断を保ち、未知peerで実fillしても最初の復帰は基準だけ。
            data=prepared_fixture(config,symbol,side);value=data[key]
            initial_fill=int(normal['growth_cohorts'][0,8])
            grid=value['signal']['grid']; fallback_fill=int(grid[np.searchsorted(grid,initial_fill,side='right')])
            value['record']['quote_valid'][initial_fill:fallback_fill]=False
            unknown=int(np.searchsorted(grid,fallback_fill,side='right')-1)
            value['signal']['entry_peer_bbo'][unknown,5]=0.
            uncertain=run(strategy,config,data)
            assert uncertain['growth_cohorts'][0,8]==fallback_fill
            anchors=uncertain['growth_events'][uncertain['growth_events'][:,1]==5]
            assert len(anchors) and anchors[0,0]>fallback_fill
            anchor=int(anchors[0,0]); assert uncertain['growth_state_trace'][anchor,30]==anchor
            assert uncertain['growth_state_trace'][anchor,48]==0
            counts['未知初回peer復帰同行を禁止']+=1

            # ----------------------------------------
            # 場末強制は、既予約追加の正常fillより先に取消を有効にする。
            data=prepared_fixture(config,symbol,side);value=data[key]
            value['record']['time_s'][fill:]=np.linspace(1040.,1100.,len(value['record']['time_s'])-fill)
            value['signal']['mapped'][fill:]=-1
            forced=run(strategy,config,data)
            assert len(forced['growth_cohorts'])==1
            assert np.any((forced['growth_events'][:,1]==4)&(forced['growth_events'][:,2]==1))
            counts['場末は追加fillより先']+=1

            # ----------------------------------------
            # 追加の通常期限は初回に固定し、直前予約を保持玉へ変える前に取消する。
            timed_config=configs['B1_T1_Q1_X1']
            probe=run(strategy,timed_config,late_fixture(timed_config,symbol,side,2140))
            deadline=int(probe['growth_cohorts'][0,10])+1800
            data=late_fixture(timed_config,symbol,side,deadline-16);value=data[key]
            projected=run(strategy,timed_config,copy.deepcopy(data)); reserved,unused=first_addition(projected)
            assert reserved<deadline
            value['record']['quote_valid'][reserved+1:deadline]=False
            expired=run(strategy,timed_config,data)
            assert len(expired['growth_cohorts'])==1
            assert np.any((expired['growth_events'][:,1]==4)&(expired['growth_events'][:,2]==3))
            assert expired['trades'][0,13]==3
            counts['初回期限は追加fillより先']+=1

            # ----------------------------------------
            # entry_cutは新しい追加判断を止めるだけ。以前の追加予約を取消しない。
            data=late_fixture(config,symbol,side,2684);value=data[key]
            projected=run(strategy,config,copy.deepcopy(data));reserved,unused=first_addition(projected)
            assert reserved<2700
            value['record']['quote_valid'][reserved+1:2700]=False
            cut=run(strategy,config,data)
            actual_decision,actual_fill=first_addition(cut)
            assert actual_decision==reserved and actual_fill==2700
            counts['entry_cut後の既予約追加は実fill']+=1

    # ----------------------------------------
    # 丸めの細かいTOPIXだけに、予算合格とactive費用床拒否を分離した人工点を入れる。
    for side in (1,-1):
        data=prepared_fixture(config,'TOPIX',side);key=next(iter(data));value=data[key]
        record,signal=value['record'],value['signal'];base=value['reference_open'];tick=record['tick'];width=4.
        progress=np.zeros(len(record['time_s']))
        for row,units in ((340,.5),(360,1.5),(380,3.),(400,6.),(420,10.),(450,12.),(460,13.5),(480,14.),(500,20.),(700,18.)):
            progress[row:]=units
        quote=base+(tick if side==1 else 0.)+side*progress*width
        record['bid']=quote-tick if side==1 else quote.copy();record['ask']=quote.copy() if side==1 else quote+tick
        record['price']=.5*(record['bid']+record['ask'])
        peer_quote=50000.+(10. if side==1 else 0.)+side*np.round(progress*50./10.)*10.
        source=signal['entry_peer_bbo'][:,0].astype(int)
        signal['entry_peer_bbo'][:,3]=(peer_quote-10. if side==1 else peer_quote)[source]
        signal['entry_peer_bbo'][:,4]=(peer_quote if side==1 else peer_quote+10.)[source]
        special=run(strategy,config,attach_support(data));g=special['growth_gate_state_trace'];s=special['growth_state_trace']
        rows=np.flatnonzero((g[:,13]==1)&(g[:,10]==1)&(g[:,11]==1)&(g[:,12]==0)&(s[:,22]==1)&
                           (side*(s[:,38]-g[:,6])<=0)&(side*(s[:,39]-g[:,6])>0))
        assert len(rows), '予算だけ合格して費用床で拒否する人工点がありません'
        counts['active床だけでT1拒否']+=1
    ending={str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    assert beginning==ending
    proof=dict(全合格=True,検査件数=counts,反例=facts,新正式102損益=0,実原板再生=0,
        API取得=0,実注文=0,エンジン変更=0,開始と終端の全依存SHA一致=True,開始SHA256=beginning,SHA256=ending)
    target=HERE/'余裕と据置の拒否及び不利実fillと通常追尾と未知期限場末の少数自己検査.json'
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in proof.items() if k not in ('SHA256','開始SHA256')},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
