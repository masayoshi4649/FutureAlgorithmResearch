"""直近位相と方向別取消を、私有小素材と旧exact写しで確かめる。"""

from copy import deepcopy
from pathlib import Path
import sys
import traceback

import numpy as np

sys.dont_write_bytecode=True
import catalog
import common
import features
import selection

INTERFACE=common.module('106局所位相の実接口',common.HERE/'interface.py')
FIXTURE=common.module('106局所位相の私有素材写し',common.HERE/'engine/fixture_source.py')
BASE=INTERFACE.module('106局所位相のexact基準写し',common.HERE/'engine/reference_core.py')
ACCOUNT=common.module('106局所位相の方向別独立会計',common.HERE/'engine/accounting.py')
ARRAYS=('orders','trades','growth_cohorts','events','curve','target_trace','judgments','source_curve',
    'control_judgments','control_events','control_integer_events','candidate_controls')


def reference(p: dict, normal: dict, cfg: dict, q: int, finish: bool=True) -> dict:
    """
    機能: 旧range_price同bytesの私有coreへ同じ経済入力を渡す。
    引数: p/normal/cfg(dict)、q(int)、finish(bool)は人工素材と実数量。
    返り値: dictは比較経済。旧source/cacheへの書込みと正式金融はない。
    """
    signal,settings=INTERFACE.connect(p,normal,cfg,q)
    for name in ('quiet','quiet_start_s','entry_families','target_prices','entry_stop_prices','entry_limit_prices','entry_modes','range_pending_trend'):
        signal[name]=normal[name]
    output=BASE.execute(p['record'],signal,settings,finish=finish,python=True)
    INTERFACE.assign_sources(p['record'],output,signal)
    return output


def packet_fixture(side: int=1, family: int=2) -> dict:
    """
    機能: 元AUTO候補と、同時計先頭sampleとは違う当行midを持つ私有入力を作る。
    引数: side/family(int)は買1/売-1、R2/C1。
    返り値: dictは元packetとshort。六点の出典行/自己尾部knownを明示する。
    """
    prepared,cases,measured={},{},{}
    for symbol in ('TOPIX','NK225'):
        p,normal,_=FIXTURE.fixture(symbol,side,family,1);prepared[symbol]=p;cases[symbol]={'C_OWN':normal}
        r=p['record'];n=len(r['seq']);tick=r['tick'];opening=p['reference_open']
        offsets=np.array([300.,240.,180.,120.,60.,0.]);times=r['time_s'][:,None]-offsets
        rows=np.maximum(np.arange(n)[:,None]-offsets.astype(np.int64),0)
        mids=np.broadcast_to(opening+side*tick*np.array([6.,20.,10.,4.,3.,-.5]),(n,6)).copy()
        known=r['time_s']>=300
        high,low=mids.max(axis=1),mids.min(axis=1)
        net=mids[:,-1]-mids[:,0];tv=np.abs(np.diff(mids,axis=1)).sum(axis=1)
        own=dict(stamps=r['time_s'],known=known.copy(),reason=np.where(known,0,1).astype(np.uint8),
            rows=rows.astype(np.int64),raw_seq=rows.astype(np.int64),times=times,ages=np.zeros((n,6)),midpoint=mids,
            ER=np.abs(net)/tv,TV=tv,high=high,low=low,centre=(high+low)/2,span_ticks=(high-low)/tick,return_bp=net/mids[:,0]*10000)
        peer=deepcopy(own);peer['times']=times-1
        state=np.full(n,1,np.int8);state[~known]=0
        if family==1:state[330]=2*side
        event=np.zeros(n,np.int8)
        if family==2:event[330]=side
        measured[symbol]=dict(sample_tables={'own':own,'peer':peer},normal_sample_index=np.arange(n,dtype=np.int32),
            own_known=known.copy(),own_reason=own['reason'].copy(),peer_known=known.copy(),qok=np.ones(n,bool),
            raw_mapping=np.arange(n,dtype=np.int64),previous_normal_row=np.arange(n,dtype=np.int64)-1,
            states={'0.4':state},boundary_events={'0.4':event})
    for symbol in ('TOPIX','NK225'):
        other='NK225' if symbol=='TOPIX' else 'TOPIX'
        measured[symbol]['sample_tables']['peer']=deepcopy(measured[other]['sample_tables']['own'])
        measured[symbol]['sample_tables']['peer']['times']-=1
    packet=dict(schema_version=1,session='私有人工',prepared=prepared,cases=cases,measured=measured,
        quiet={s:dict(active=np.zeros(1001,bool),start_s=np.full(1001,np.nan)) for s in prepared})
    packet['short']={s:features.build(packet,s) for s in prepared}
    return packet


def main() -> None:
    """
    機能: 三点数学、未知/未来、方向別取消と旧対照経済/料金/接頭/JITを結果前に検査する。
    引数: なし。私有人工のみを使う。
    返り値: None。成功/失敗を新所有域へ保存、金融/原板/APIを読まない。
    """
    checks=[];target=common.HERE/'直近位相と方向別待機取消の人工検査.json';assert not target.exists()
    paths=[common.HERE/n for n in ('artificial.py','common.py','catalog.py','features.py','selection.py','selection_snapshot.py','interface.py')]
    paths += [common.HERE/'engine'/n for n in ('core.py','reference_core.py','fixture_source.py','accounting.py','accounting_reference.py')]
    before={p.relative_to(common.ROOT).as_posix():common.digest(p) for p in paths}
    try:
        points=np.array([[100.,104.,103.],[103.,99.,100.],[100.,100.,100.],[100.,103.,100.],
            [100.,100.5,101.5],[100.,101.,102.],[100.,np.nan,102.],[100.,101.,103.]],np.float64)
        known=np.array([1,1,1,1,1,1,1,0],bool);a=features.phase(points,known,1.)
        assert a['direction'].tolist()==[1,-1,0,0,0,1,0,0]
        assert a['ER'][0]==.6 and a['ER'][1]==.6 and a['ER'][2]==0 and a['known'][2]
        assert not a['known'][6] and not a['known'][7]
        checks.extend(['ER0.6境界と2呼値境界','買売反射と強方向','TV0既知中立','往復中立','幅不足','NaN未知とknown資格'])
        for side in (1,-1):
            packet=packet_fixture(side);symbol='TOPIX';short=packet['short'][symbol]
            assert short['own']['points'][330,-1]==(packet['prepared'][symbol]['record']['bid'][330]+packet['prepared'][symbol]['record']['ask'][330])/2
            assert short['own']['points'][330,-1]!=packet['measured'][symbol]['sample_tables']['own']['midpoint'][330,-1]
            assert short['own']['direction'][330]==-side
            checks.append(f'{side}/当行midと同clock先頭を混同しない')
            broken=deepcopy(packet);broken['measured'][symbol]['own_known'][330]=False
            wrong=features.build(broken,symbol);assert not wrong['own']['known'][330]
            checks.append(f'{side}/同clock後半の尾部未知を先頭knownで救済しない')
            for cfg in catalog.catalog():
                base=selection.legacy.build(packet,symbol,cfg);normal=selection.build(packet,symbol,cfg)
                assert base['event'][330]==side and normal['event'][330]==0
                assert normal['local_phase_rejected'][330] and normal['local_phase_candidates'][0]['accepted']==False
            checks.append(f'{side}/全18基準R候補の強逆行拒否')
            cpacket=packet_fixture(side,1)
            for cfg in catalog.catalog():
                old=selection.legacy.build(cpacket,symbol,cfg);current=selection.build(cpacket,symbol,cfg)
                for name in ('event','support_price','entry_quality','entry_reset','entry_families','entry_modes'):
                    np.testing.assert_array_equal(old[name],current[name])
                assert old['decisions']==current['decisions']
            checks.append(f'{side}/全18元C候補と支持roots不変更')
            for policy in ('OWN_VETO','BOTH_VETO','ALIGNED'):
                allowed,cancel=features.decisions(short,side,policy);assert not allowed[330] and cancel[330]
            same=deepcopy(short)
            for name in ('own','peer'):same[name]['direction'][330]=side
            for policy in ('OWN_VETO','BOTH_VETO','ALIGNED'):
                allowed,cancel=features.decisions(same,side,policy);assert allowed[330] and not cancel[330]
            checks.append(f'{side}/逆行取消と順行待機')
            neutral=deepcopy(same);neutral['peer']['direction'][330]=0
            allowed,cancel=features.decisions(neutral,side,'ALIGNED');assert not allowed[330] and not cancel[330]
            checks.append(f'{side}/ALIGNED同方向消失だけでは取消しない')
            unknown=deepcopy(short)
            for name in ('own','peer'):unknown[name]['known'][330]=False
            for policy in ('OWN_VETO','BOTH_VETO','ALIGNED'):
                _,cancel=features.decisions(unknown,side,policy);assert not cancel[330]
            checks.append(f'{side}/UNKNOWNは追加取消なし')
            future=deepcopy(packet)
            for s in ('TOPIX','NK225'):
                future['prepared'][s]['record']['bid'][400:]+=1000
                future['prepared'][s]['record']['ask'][400:]+=1000
                future['measured'][s]['sample_tables']['own']['midpoint'][400:]+=2000
                future['measured'][s]['sample_tables']['peer']['midpoint'][400:]+=3000
            after=features.build(future,symbol)
            for name in ('own','peer'):
                for key in ('direction','ER','net_ticks','TV_ticks','known','points'):
                    np.testing.assert_array_equal(short[name][key][:400],after[name][key][:400])
            checks.append(f'{side}/未来価格とsample変更の過去位相不変')

        for symbol in ('TOPIX','NK225'):
            q=5 if symbol=='TOPIX' else 10
            for side in (1,-1):
                for mode in (1,2):
                    p,normal,cfg=FIXTURE.fixture(symbol,side,2,mode)
                    if mode==2:FIXTURE.clearing(p,400,side,p['reference_open']-side*p['record']['tick'])
                    normal['local_cancel_buy']=np.zeros(1001,bool);normal['local_cancel_sell']=np.zeros(1001,bool)
                    old=reference(p,normal,cfg,q);actual=INTERFACE.play(p,normal,cfg,q,python=True)
                    for name in ARRAYS:np.testing.assert_array_equal(old[name],actual[name])
                    ACCOUNT.inspect(('私有人工',symbol),p['record'],actual,normal)
                    check_fee=209 if symbol=='TOPIX' else 110
                    assert np.all(actual['orders'][:,9]==check_fee)
                    checks.append(f'{symbol}/{side}/{mode}/取消オフ全経済exactと実料金')
                    jit=INTERFACE.play(p,normal,cfg,q,python=False)
                    for name in ARRAYS:np.testing.assert_array_equal(actual[name],jit[name])
                    checks.append(f'{symbol}/{side}/{mode}/PythonとJIT一致')

                p,normal,cfg=FIXTURE.fixture(symbol,side,2,2)
                FIXTURE.clearing(p,400,side,p['reference_open']-side*p['record']['tick'])
                normal['local_cancel_buy']=np.zeros(1001,bool);normal['local_cancel_sell']=np.zeros(1001,bool)
                cancel=normal['local_cancel_buy'] if side==1 else normal['local_cancel_sell'];cancel[350]=True
                out=INTERFACE.play(p,normal,cfg,q,python=True)
                assert len(out['orders'])==0 and len(out['pending_cancel_diagnostics'])==1
                d=out['pending_cancel_diagnostics'][0];assert d['local_veto'] and not d['original_known_trend']
                checks.append(f'{symbol}/{side}/pending強反対を取消し後の到達で復活なし')
                FIXTURE.add_event(p,normal,450,side,2,2)
                FIXTURE.clearing(p,500,side,p['reference_open']-side*2*p['record']['tick'])
                out=INTERFACE.play(p,normal,cfg,q,python=True)
                assert len(out['trades'])==1 and out['trades'][0,15]==450
                checks.append(f'{symbol}/{side}/取消後の別原行新候補は再参加')
                normal['local_cancel_buy'][:]=False;normal['local_cancel_sell'][:]=False
                opposite=normal['local_cancel_sell'] if side==1 else normal['local_cancel_buy'];opposite[350]=True
                out=INTERFACE.play(p,normal,cfg,q,python=True)
                assert out['trades'][0,15]==330 and out['trades'][0,2]==400
                checks.append(f'{symbol}/{side}/逆側maskで順行pendingを誤取消しない')
                normal['local_cancel_buy'][:]=False;normal['local_cancel_sell'][:]=False
                cancel=normal['local_cancel_buy'] if side==1 else normal['local_cancel_sell'];cancel[400]=True
                out=INTERFACE.play(p,normal,cfg,q,python=True)
                assert out['trades'][0,2]==400 and out['raw_entry_diagnostics'][0]['fill_local_cancel_condition']
                assert not out['raw_entry_diagnostics'][0]['fill_known_trend']
                checks.append(f'{symbol}/{side}/live指値初reach同行を先約定しTREND欄を混同しない')

                market,ncase,cfg=FIXTURE.fixture(symbol,side,2,1)
                ncase['local_cancel_buy']=np.zeros(1001,bool);ncase['local_cancel_sell']=np.zeros(1001,bool)
                (ncase['local_cancel_buy'] if side==1 else ncase['local_cancel_sell'])[331]=True
                out=INTERFACE.play(market,ncase,cfg,q,python=True);assert out['trades'][0,2]==331
                checks.append(f'{symbol}/{side}/market次quote同行取消より実fillを保持')
                cmarket,ccase,cfg=FIXTURE.fixture(symbol,side,1,1)
                cmarket['record']['quote_valid'][331:340]=False
                ccase['local_cancel_buy']=np.ones(1001,bool);ccase['local_cancel_sell']=np.ones(1001,bool)
                out=INTERFACE.play(cmarket,ccase,cfg,q,python=True);old=reference(cmarket,ccase,cfg,q)
                for name in ARRAYS:np.testing.assert_array_equal(out[name],old[name])
                assert out['trades'][0,2]==340
                checks.append(f'{symbol}/{side}/Cのpendingと保有へ適用しない')

                full=INTERFACE.play(p,normal,cfg,q,python=True)
                small,nsmall=FIXTURE.prefix(p,normal,390)
                prefix=INTERFACE.play(small,nsmall,cfg,q,finish=False,python=True)
                assert prefix['target_trace'][-1,4]==q and len(prefix['trades'])==0
                np.testing.assert_array_equal(full['curve'][:390],prefix['curve'])
                np.testing.assert_array_equal(full['target_trace'][:390],prefix['target_trace'])
                changes=deepcopy(p);changes['record']['bid'][390:]+=1000;changes['record']['ask'][390:]+=1000
                nfuture=deepcopy(normal);nfuture['local_cancel_buy'][390:]=True;nfuture['local_cancel_sell'][390:]=True
                changed=INTERFACE.play(changes,nfuture,cfg,q,python=True)
                np.testing.assert_array_equal(changed['curve'][:390],prefix['curve'])
                checks.append(f'{symbol}/{side}/pending接頭を端点清算せず未来変更で不変')
        assert len(catalog.catalog())==18
        assert before=={p.relative_to(common.ROOT).as_posix():common.digest(p) for p in paths}
        common.write(target,dict(全合格=True,検査件数=len(checks),検査=checks,source_SHA256=before,
            私有人工のみ=True,正式input読取=0,新金融再生=0,原板読取=0,API取得=0,
            限界='人工は取消述語と過去特徴の機械性の検査。勝率/収益の証明ではない。'))
        print(f'直近位相/取消人工 {len(checks)} 件合格、金融0',flush=True)
    except BaseException as exc:
        common.write(common.HERE/'直近位相の人工失敗.json',dict(全合格=False,例外=repr(exc),検査完了=checks,source_SHA256=before,
            traceback=traceback.format_exc(),新金融再生=0))
        raise


if __name__=='__main__':main()
