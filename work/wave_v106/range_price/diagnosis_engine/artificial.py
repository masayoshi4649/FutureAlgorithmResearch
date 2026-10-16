"""売買を再生せず、原因診断の分母と時点を私有小配列で確かめる。"""

from copy import deepcopy
from pathlib import Path
import sys

import numpy as np

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import diagnose


def fixture(symbol: str, side: int) -> tuple[dict,dict,dict,np.ndarray,dict]:
    """
    機能: 買売反射で同じ経済となる小さい正常列と診断台帳を作る。
    引数: symbol(str)、side(int)は商品と買1/売-1。
    返り値: tupleはrecord/measured/ledger/trade/config。金融関数を呼ばない。
    """
    tick=.5 if symbol=='TOPIX' else 10.;quantity=5 if symbol=='TOPIX' else 10
    multiplier=1000. if symbol=='TOPIX' else 10.;fee=209. if symbol=='TOPIX' else 110.
    E=10000.;movement=tick*np.array([-1.,-1.,2.,5.,3.,-1.,-2.])
    clearing=E+side*movement
    bid=clearing if side==1 else clearing-tick
    ask=clearing+tick if side==1 else clearing
    record=dict(symbol=symbol,tick=tick,seq=np.arange(20,27),time_s=np.arange(1720000000.,1720000007.),
        bid=bid,ask=ask,quote_valid=np.ones(7,np.bool_))
    trade=np.zeros(16);trade[[0,1,2,3,4,5]]=[1,1,1,6,side,quantity]
    trade[6]=E;trade[7]=clearing[6];trade[8]=trade[9]=fee
    trade[10]=side*(trade[7]-E)*quantity*multiplier;trade[11]=trade[10]-2*fee
    trade[13]=11;trade[15]=0
    stop=E-side*2*tick;target=E+side*6*tick
    episode=dict(stop_price=stop,target_price=target,entry_mode='MARKET',fixed_low=E-8*tick,
        fixed_high=E+8*tick,fixed_centre=E,planned_entry=E-side*tick,
        planned_net_profit=7*tick*quantity*multiplier-2*fee,
        planned_net_loss=tick*quantity*multiplier+2*fee,fee_included_ratio=3.,
        own_six={'known':True,'prices':[E]*6},peer_six={'known':True,'prices':[E]*6},prior_quote_row=0)
    order=np.zeros(17);order[[0,1,2,7]]=[6,5,1,0]
    ledger=dict(raw_entry_diagnostics=[dict(parent_id=1,episode=episode,fill_known_trend=False)],orders=np.array([order]))
    states=np.array([1,1,1,0,-2*side,-2*side,3],np.int8)
    return record,dict(states={'0.2':states}),ledger,trade,dict(range_er=.2)


def main() -> None:
    """
    機能: 最大順逆行・判断前の状態・約定RR・黒字反証の純解析人工を保存する。
    引数: なし。私有小配列と診断sourceのみを読む。
    返り値: None。実入力・正式結果・金融関数・APIは使用しない。
    """
    checks=[]
    for symbol in ('TOPIX','NK225'):
        mirrored=[]
        for side in (1,-1):
            record,measured,ledger,trade,config=fixture(symbol,side)
            detail=diagnose.describe(record,measured,ledger,trade,config)
            q=int(trade[5]);mult=1000. if symbol=='TOPIX' else 10.;tick=record['tick']
            ext=detail['held']['extrema'];mode=detail['held']['mode']
            assert ext['MFE_ticks']==5 and ext['MAE_ticks']==2
            assert abs(ext['best_liquidation_net']-(5*tick*q*mult-trade[8]-trade[9]))<1e-7
            assert ext['best_clock']['row']==3 and ext['profit_given_back']==7*tick*q*mult
            assert mode['first_opposing_trend_before_exit_decision']['row']==4
            assert mode['first_change']['row']==3 and sum(mode['row_counts'].values())==6
            assert detail['category']=='反対TREND観測後も固定stopまで保持'
            assert detail['fill']['adverse_gap_ticks']==1
            assert detail['fill']['actual_RR'] is not None
            checks.extend([f'{symbol}/{side}/清算極値',f'{symbol}/{side}/料込利益返し',
                f'{symbol}/{side}/判断前状態',f'{symbol}/{side}/予定実約定差'])
            mirrored.append(detail)

            late=measured['states']['0.2'].copy();late[:]=-0;late[6]=-2*side
            modes=diagnose.mode_path(record,late,trade,5)
            assert modes['observed_opposing_trend_any_held_row'] and not modes['observed_opposing_trend']
            assert modes['first_opposing_trend_before_exit_decision'] is None
            checks.append(f'{symbol}/{side}/返済後状態を原因にしない')

            invalid=deepcopy(record);invalid['quote_valid'][3]=False
            reduced=diagnose.extrema(invalid,trade)
            assert reduced['MFE_ticks']==3 and reduced['normal_quote_observations']==5
            checks.append(f'{symbol}/{side}/不正気配極値を除く')

            broken=deepcopy(ledger);broken['raw_entry_diagnostics'][0]['episode']['stop_price']=trade[6]
            bad=diagnose.describe(record,measured,broken,trade,config)
            assert bad['fill']['fixed_stop_broken'] and bad['fill']['actual_RR'] is None
            assert bad['category']=='実fill時に固定stop外'
            checks.append(f'{symbol}/{side}/fill破綻RRを保証にしない')

            target_trade=trade.copy();target_trade[13]=10
            target=diagnose.describe(record,measured,ledger,target_trade,config)
            assert target['qualifiers']['target_then_worse'] and target['category']=='中心到達判断後の次quote悪化'
            checks.append(f'{symbol}/{side}/返済判断と次気配を分ける')
        for key in ('net',):assert mirrored[0][key]==mirrored[1][key]
        for key in ('MFE_ticks','MAE_ticks','best_liquidation_net','profit_given_back'):
            assert mirrored[0]['held']['extrema'][key]==mirrored[1]['held']['extrema'][key]
        checks.append(f'{symbol}/買売反射同値')

    groups={}
    for net in (-20.,10.,0.):diagnose.add_group(groups,'同じ観測',{'net':net})
    assert groups['同じ観測']==dict(parents=3,wins=1,losses=1,flat=1,profit=10.,loss=20.,net=-10.)
    checks.append('同特徴の黒字と横ばいを親分母へ含む')
    assert '未取引' not in groups
    checks.append('未取引を勝ちへ加算しない')
    target=diagnose.HERE/'診断器の純解析人工検査.json'
    diagnose.common.write(target,dict(全合格=True,検査件数=len(checks),検査=checks,
        私有人工のみ=True,正式結果読取=0,実入力読取=0,新金融再生=0,原板読取=0,API取得=0,
        source_SHA256={p.relative_to(diagnose.common.ROOT).as_posix():diagnose.common.digest(p)
            for p in (Path(__file__),Path(diagnose.__file__))},
        制約='これは診断の算式・時点・分母の検査であり、手法が利益を生むことの証拠ではない。'))
    print(f'診断器純解析人工 {len(checks)} 件合格、金融再生0',flush=True)


if __name__=='__main__':main()
