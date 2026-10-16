"""既知逆票見送りの入口真偽・影状態・旧同値・実UID料金・接頭を私有人工で確認する。"""

from copy import deepcopy
from decimal import Decimal,ROUND_FLOOR
import traceback

import numpy as np
import numba
import common
import catalog
import daily
import engine
import fixtures
import interface
import old_engine
import policy
import runner


def expected(value: dict, mode: str) -> bool:
    """
    機能: 政策関数と別の集合式で三つの公開資格を求める。
    引数: value(dict)、mode(str)は人工当時票と比較政策。
    返り値: boolは集合式の許可。取引集合や損益の包含へ拡張しない。
    """
    eligible=bool(value['known'] and value['direction_votes']>=2)
    if mode=='CONFIRM':return eligible and value['balance']>=.25
    if mode=='VETO':return not(eligible and value['balance']<=-.25)
    return eligible and value['balance']>-.25


def partial(account: dict, cut: int) -> dict:
    """
    機能: 未来の紙上公開を除いた人工normal接頭を作成する。
    引数: account(dict)、cut(int)は人工口座と行数。
    返り値: dictは元limitを不変更にした接頭。端点清算を追加しない。
    """
    return dict(account,record={k:v[:cut].copy() if isinstance(v,np.ndarray) else v for k,v in account['record'].items()},
        quotes={k:v[:cut].copy() for k,v in account['quotes'].items()},feed=account['feed'][account['feed'][:,0]<cut].copy(),
        quiet=account['quiet'][:cut].copy(),quiet_force=account['quiet_force'][:cut].copy())


def main() -> None:
    """
    機能: 入口閾値/包含と機械fixtureを検査し、結果前sourceを人工証跡へ束縛する。
    引数: なし。
    返り値: None。大型input/旧ledger/金融/原板/APIは読まず、旧JITへ書かない。
    """
    assert not runner.ART.exists();clones=runner.check_clones();checks=[];array_checks=0
    balances=(-1.,-.250000001,-.25,-.249999999,0.,.249999999,.25,.250000001,1.)
    for known in (False,True):
        for count in (0,1,2,3,8):
            for balance in balances:
                value=dict(known=known,reason=8 if not known else 0,direction_votes=count if known else None,
                    balance=balance if known and count else None,accepted=False)
                observed={mode:policy.verdict(value,mode)[0] for mode in ('CONFIRM','KNOWN_VETO','VETO')}
                for mode in observed:assert observed[mode]==expected(value,mode)
                assert not observed['CONFIRM'] or observed['KNOWN_VETO']
                assert not observed['KNOWN_VETO'] or observed['VETO']
                checks.append(dict(観点='真偽表と公開maskの包含',known=known,votes=count,balance=balance,observed=observed))
    for malformed in (None,float('nan'),float('inf')):
        try:policy.verdict(dict(known=True,reason=0,direction_votes=2,balance=malformed),'KNOWN_VETO')
        except AssertionError:pass
        else:raise AssertionError('壊れた既知balanceの救済')
    checks.append(dict(観点='既知二票のbalance不正は契約違反として拒否'))
    # ----------------------------------------
    # 新maskがすべて通過なら、旧全九配列とPython/JITを一致させる。実料金はDecimal別算定。
    for symbol in catalog.QUANTITY:
        for side in (1,-1):
            a=fixtures.fixture(symbol,side);c=catalog.configs()[0]
            r,q=a['record'],a['quotes']
            old=old_engine.simulate.py_func(r['time_s'],r['price'],q['bid'],q['ask'],q['quote_valid'],a['feed'],
                a['quiet'],a['quiet_force'],r['limit'],catalog.CAP[symbol],r['tick'],0.,True)
            fresh=interface.execute(a,c);py=interface.execute(a,c,True)
            for x,y,z in zip(old,fresh,py):
                np.testing.assert_array_equal(x,y);np.testing.assert_array_equal(y,z);array_checks+=2
            for config in catalog.configs():
                out=interface.account_output('人工',a,config,fresh)
                charges=[int((Decimal(str(daily.FEE[symbol]))*Decimal(int(o[4]))).to_integral_value(rounding=ROUND_FLOOR)) for o in out['orders']]
                np.testing.assert_array_equal(out['order_fees'],charges)
                assert out['summary']['費用']==sum(charges)
                if symbol=='TOPIX' and config['exit']=='GU':np.testing.assert_array_equal(out['order_fees'][:3],[209,83,125])
                if config['exit']=='P1L8' and out['control']['発動']:
                    decision=out['control']['判断行'];fill=out['control']['返済行']
                    assert fill>decision and not np.any((out['orders'][:,0]>decision)&(out['orders'][:,7]==1))
            checks.append(dict(観点='全True旧経済exactとPythonJIT・UID料',symbol=symbol,side=side))
            # ----------------------------------------
            # 未知/票不足/強逆票の新規は拒否しても、影の部分返済・後続親はそのまま継続する。
            for missing in ('unknown','few','opposite'):
                b=fixtures.fixture(symbol,side);v=b['trade_features']['60'][1]
                if missing=='unknown':v.update(known=False,reason=8,direction_votes=None,balance=None)
                elif missing=='few':v.update(known=True,direction_votes=1,balance=1.)
                else:v.update(known=True,direction_votes=2,balance=-.25)
                b['trade_features']['60'][8].update(balance=0.,accepted=False)
                got=interface.execute(b,c);assert len(got[0])==2 and np.all(got[0][:,2]==1)
                assert got[7][1,1]==side*catalog.QUANTITY[symbol] and got[7][6,1]==0
                assert int(got[8][got[8][:,2]==0][0,17])==95
                assert got[7][2,3]+got[7][2,4]==0 and got[7][8,5]==1
                interface.account_output('人工拒否',b,c,got)
                checks.append(dict(観点='拒否後shadow部分と中立後続を実運転',symbol=symbol,side=side,reason=missing))
            b=fixtures.fixture(symbol,side);b['quotes']['quote_valid'][7:9]=False
            got=interface.execute(b,c);assert np.all(got[0][:,2]==0)
            post=got[8][(got[8][:,2]==1)&(got[8][:,1]==1)]
            assert len(post)==1 and post[0,17]==94
            checks.append(dict(観点='旧実返済待ちbusyで許可された別親を実新規へ再利用しない',symbol=symbol,side=side))
            b=fixtures.fixture(symbol,side);b['quotes']['quote_valid'][2]=False
            r,q=b['record'],b['quotes'];mask=np.ones(len(r['price']),bool);mask[2:8]=False
            got=engine.simulate.py_func(r['time_s'],r['price'],q['bid'],q['ask'],q['quote_valid'],b['feed'],b['quiet'],b['quiet_force'],r['limit'],catalog.CAP[symbol],r['tick'],0.,True,mask)
            ordinary=interface.execute(b,c,True);np.testing.assert_array_equal(got[0],ordinary[0])
            assert ordinary[0][0,0]==3
            checks.append(dict(観点='非公開行maskは次quote待ちの追加取消に使わない',symbol=symbol,side=side))
            quiet=fixtures.fixture(symbol,side);quiet['quiet'][2]=True
            got=interface.execute(quiet,c,True);assert not np.any((got[0][:,2]==0)&(got[0][:,7]==1))
            checks.append(dict(観点='既知quietは公開後のfillより先に取消',symbol=symbol,side=side))
            # ----------------------------------------
            # 未返済接頭と未来気配/将来候補票改変が前方注文・曲線・影状態を変えない。
            base=fixtures.fixture(symbol,side);full=interface.execute(base,c,True);cut=5
            prefix=interface.execute(partial(base,cut),c,True)
            np.testing.assert_array_equal(prefix[0],full[0][full[0][:,0]<cut])
            for index in (2,7):np.testing.assert_array_equal(prefix[index],full[index][:cut]);array_checks+=1
            assert prefix[7][-1,3]+prefix[7][-1,4]>0
            changed=deepcopy(base);changed['quotes']['bid'][cut:]+=20*daily.TICK[symbol];changed['quotes']['ask'][cut:]+=20*daily.TICK[symbol]
            changed['trade_features']['60'][8].update(known=False,reason=8,direction_votes=None,balance=None)
            after=interface.execute(changed,c,True)
            np.testing.assert_array_equal(after[0][after[0][:,0]<cut],prefix[0])
            for index in (2,7):np.testing.assert_array_equal(after[index][:cut],prefix[index]);array_checks+=1
            np.testing.assert_array_equal(after[6][after[6][:,0]<cut],prefix[6]);array_checks+=1
            checks.append(dict(観点='未返済prefix保持と未来BBO/票不変',symbol=symbol,side=side))
    # ----------------------------------------
    # Dispatcherの数学は旧exactだが、所有cacheの場所だけを新領域に閉じ込める。
    cache_paths=[]
    for module in (engine,old_engine):
        for value in vars(module).values():
            if isinstance(value,numba.core.registry.CPUDispatcher) and getattr(value,'_cache',None) is not None:
                path=value._cache._impl._locator.get_cache_path();assert str(common.HERE.resolve()) in str(path)
                cache_paths.append(str(path))
    common.write(runner.ART,dict(全合格=True,検査数=len(checks),旧PythonJITと接頭配列照合=array_checks,検査=checks,
        source_SHA256=common.sources(),不変sourceの同bytes=clones,私有JIT位置=cache_paths,
        大型input読取=0,保存金融ledger読取=0,新金融=0,原paper再計算=0,原NPZ=0,API=0,
        確率の主張='入口maskの包含だけを証明する。取引集合の包含や収益改善は金融前のため未測定。'))
    print('KNOWN_VETO人工合格',len(checks),'観点',array_checks,'配列照合',flush=True)


if __name__=='__main__':
    try:main()
    except BaseException:
        common.write(common.HERE/'人工初回False.json',dict(全合格=False,原因=traceback.format_exc(),source_SHA256=common.sources(),新金融=0));raise
