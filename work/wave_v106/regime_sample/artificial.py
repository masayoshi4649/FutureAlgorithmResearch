"""6点・排他選択・中心返済と単一口座を、未来を見ない小人工で確認する。"""

from copy import deepcopy
from pathlib import Path
import time
import traceback

import numpy as np

import catalog
import common
import features
import interface
import selection

HERE=Path(__file__).resolve().parent
FIXTURE=common.module('106レジームの小人工素材',common.WAVE/'time_guard/fixture.py')
CHECKS={}


def check(name: str, value: bool) -> None:
    """
    機能: 人工期待値の一致を件数へ記録する。
    引数: name(str)、value(bool)は名前と一致。
    返り値: None。不一致のsourceとFalseを保持する。
    """
    assert value,name;CHECKS[name]=CHECKS.get(name,0)+1


def raw_fixture(values: list, peer: bool=False) -> dict:
    """
    機能: 60秒境界で指定した中値を持つ一秒公表の小人工を作る。
    引数: values(list[float])は6中値、peer(bool)は相手clockを0.1秒前へずらす。
    返り値: dictは価格時計と同原seq/BBO。正式入力は読まない。
    """
    n=402;times=np.arange(n,dtype=float);points=np.array([60,120,180,240,300,360])
    mid=np.interp(times,points,values);bid=mid-.25;ask=mid+.25
    return dict(raw_seq=np.arange(n,dtype=np.int64),price_time_s=times-(.1 if peer else 0),bid=bid,ask=ask,
        qualified=np.ones(n,bool),bbo_valid=np.ones(n,bool),price_reset_reason=np.zeros(n,np.uint16))


def main() -> None:
    """
    機能: point/時計不正、同時計救済禁止、RANGE先、実中心出口、単一全後続を人工検算する。
    引数: なし。
    返り値: None。新33場の金融は呼ばない。
    """
    target=HERE/'6点レジームと単一口座中心返済の人工検査.json';assert not target.exists()
    paths=[HERE/n for n in ('common.py','features.py','catalog.py','selection.py','core.py','interface.py','prepare.py','artificial.py')]
    before={str(p.relative_to(common.ROOT)):common.digest(p) for p in paths}
    own=raw_fixture([100,101,102,103,104,105]);peer=raw_fixture([200,202,204,206,208,210],True)
    one=features.sample(own,features.context(own),360.,.5,360,False)
    two=features.sample(peer,features.context(peer),360.,.5,None,True)
    check('過去300秒の6点が全て当時以前、相手厳密過去',one['rows']==[60,120,180,240,300,360] and all(t<360 for t in two['times']))
    check('単調6点ERとreturn独立期待値',one['ER']==1 and abs(one['return_bp']-500)<1e-8)
    check('双方進行のC状態',features.classify({'own':one,'peer':two},3.,.2)=='TREND_UP')
    reverse=deepcopy(two);reverse['return_bp']=-500
    check('二市場逆方向はCへ入らない',features.classify({'own':one,'peer':reverse},3.,.2)=='NEUTRAL')
    # ----------------------------------------
    # 読取未来のprice/BBO/resetを変えても、原行上限より前の6点は不変。
    altered=deepcopy(own);altered['bid'][361:]+=1000;altered['ask'][361:]+=1000;altered['qualified'][361:]=False;altered['price_reset_reason'][361:]=1
    check('未来変化で自己過去測定不変',features.sample(altered,features.context(altered),360.,.5,360)==one)
    bad=deepcopy(own);bad['qualified'][120]=False
    check('公表観測点不正を後続正常点で救済しない',not features.sample(bad,features.context(bad),360.,.5,360)['known'])
    reset=deepcopy(own);reset['price_reset_reason'][125]=1
    check('観測間price resetを跨がない',not features.sample(reset,features.context(reset),360.,.5,360)['known'])
    hidden=deepcopy(own);hidden['bbo_valid'][125]=False
    check('選ばれない非normalBBOだけでは未知へ落とさない',features.sample(hidden,features.context(hidden),360.,.5,360)['known'])
    stale=deepcopy(own);stale['price_time_s'][61:81]=60.
    check('価格clock20秒停滞を板断絶に代用しない',features.sample(stale,features.context(stale),360.,.5,360)['known'])
    start=features.sample(own,features.context(own),299.,.5,299)
    check('初期300秒未準備は未知',not start['known'])
    ranged=dict(one,ER=.1,span_ticks=20,return_bp=5.,centre=104.,high=110.,low=98.)
    check('C条件同時成立でもRANGEが先',features.classify({'own':ranged,'peer':ranged},3,.2)=='RANGE')
    flat=dict(one,ER=None,span_ticks=0,return_bp=0,TV=0)
    check('TV0は往復へ代用しない',features.classify({'own':flat,'peer':flat},3,.2)=='NEUTRAL')
    for symbol in ('TOPIX','NK225'):
        q=10 if symbol=='TOPIX' else 20
        for side in (1,-1):
            p,c=FIXTURE.fixture(symbol,side);r=deepcopy(c);r['entry_id']='R_OWN'
            tick=p['record']['tick'];E=p['record']['ask'][330] if side==1 else p['record']['bid'][330]
            centre=E+side*20*tick
            measure=dict(ranged,centre=centre,high=centre+40*tick,low=centre-40*tick)
            pair=dict(own=measure,peer=measure)
            normal,diag=selection.build(p,{'C_OWN':c,'R_OWN':r},{330:pair},catalog.setting('AUTO',3,.2,'R21'))
            check('同rowのC/RはRだけ一つへ統合',normal['entry_families'][330]==2 and len(normal['decisions'])==1)
            order=diag[0]['range_order'];unit=41.8 if symbol=='TOPIX' else 11.
            check('実枚数料でR予定審査',order['exact_roundtrip_fees']==2*np.floor(q*unit+1e-8) and order['planned_net_profit']>=1.25*order['planned_net_loss'])
            # ----------------------------------------
            # 目標は判断時固定。到達原行後の不利quoteも実返済し、利益を保証しない。
            FIXTURE.quote(p,340,order['target'] if side==1 else order['target']-tick)
            FIXTURE.quote(p,341,E-side*10*tick)
            out=interface.play(p,normal,catalog.setting('AUTO',3,.2,'R21'),quantity=q,python=True)
            check('R中心到達は次正常quote返済',out['orders'][1,1]==340 and out['orders'][1,0]==341 and out['orders'][1,8]==10)
            check('C R21設定でもRは中心出口とB4保険',out['orders'][1,8]==10 and np.all(out['orders'][:,3]==1))
            check('中心後の不利約定を隠さない',out['trades'][0,11]<0)
            np.testing.assert_allclose(out['source_curve'].sum(axis=1),out['curve'],atol=1e-4,rtol=0)
            check('源別の実料と全口座時価一致',True)
            rejected=dict(pair,own=dict(measure,centre=E))
            declined,dd=selection.build(p,{'C_OWN':c,'R_OWN':r},{330:rejected},catalog.setting('AUTO',3,.2,'B4'))
            check('RANGE余地不足をCへ救済しない',not declined['event'].any())
            # ----------------------------------------
            # 選択済み同sourceを、旧B4全後続と同じ経済で再運転する。
            p,c=FIXTURE.fixture(symbol,side);n=len(c['event']);normal=dict(c,entry_families=np.where(c['event']!=0,1,0).astype(np.int8),target_prices=np.full(n,np.nan))
            old=FIXTURE.run_leg(p,c,q);new=interface.play(p,normal,catalog.setting('C_ONLY',3,.2,'B4'),quantity=q,python=True)
            for name in ('orders','trades','curve','growth_cohorts','target_trace'):
                np.testing.assert_array_equal(old[name],new[name])
            check('CだけB4は旧原経済exact一致',True)
            # ----------------------------------------
            # R中心を越える不利新規gapを架空取消しない。
            normal=dict(c,entry_families=np.where(c['event']!=0,2,0).astype(np.int8),target_prices=np.full(n,np.nan));normal['target_prices'][330]=E+side*2*tick
            FIXTURE.quote(p,331,E+side*5*tick if side==1 else E-side*5*tick-tick)
            gap=interface.play(p,normal,catalog.setting('AUTO',3,.2,'B4'),quantity=q,python=True)
            check('実entry悪化後もfillを架空取消しない',len(gap['orders'])==2 and gap['orders'][0,0]==331 and gap['orders'][1,0]==332)
    check('26実条件と10重複表示alias',len(catalog.catalog())==26 and len(catalog.aliases())==10)
    assert before=={p:common.digest(common.ROOT/p) for p in before}
    common.save(target,dict(全合格=True,人工専用=True,検査件数=CHECKS,source_SHA256=before,開始終端source一致=True,
        新金融再生=0,原板読取=0,正式input読取=0,API取得=0))
    print('人工合格 '+str(sum(CHECKS.values()))+'件',flush=True)


if __name__=='__main__':
    try:main()
    except Exception as error:
        folder=HERE/('人工False_'+time.strftime('%Y%m%d_%H%M%S'));folder.mkdir()
        for n in ('artificial.py','features.py','core.py','interface.py','selection.py','catalog.py'):(folder/n).write_bytes((HERE/n).read_bytes())
        common.save(folder/'False.json',dict(全合格=False,例外=str(error),traceback=traceback.format_exc(),完了検査=CHECKS,新金融再生=0))
        raise
