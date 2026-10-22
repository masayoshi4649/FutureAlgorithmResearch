"""公開行だけのQ条件と低利益床、同値キーを独立な人工値で反証する。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

from low_cases126 import test,verify


HERE=Path(__file__).resolve().parent
TASK=HERE.parents[1]
ROOT=HERE.parents[3]
GATED=TASK/'gated_bbo126'
sys.path.insert(0,str(GATED))
import catalog126g as catalog
import feed_filter126 as filtering


def permit(value: tuple, expected: bool, name: str) -> tuple:
    """
    機能: 一親のQ採否と後続返済通知の一貫性を独立期待値へ照合する。
    引数: value(tuple)は人工四値、expected(bool)、name(str)は期待と検査名。
    返り値: tupleはfilteredpaperとtrace。
    """
    ready,quotes,market,paper=value
    filtered,trace=filtering.filter_paper(paper,ready,quotes)
    test.check(name,len(trace)==1 and trace[0]['accepted']==expected)
    test.check(name+'後続親通知を同採否で保持',len(filtered['orders'])==(len(paper['orders']) if expected else 0))
    json.dumps(trace,ensure_ascii=False,allow_nan=False)
    return filtered,trace


def quote_checks(configs: list[dict]) -> list[dict]:
    """
    機能: 公開行・初回ATR・閾値境界・未知・上下対称・次行悪化を反証する。
    引数: configs(list[dict])は実固定五十三条件。
    返り値: list[dict]は境界と実約定の小記録。
    """
    records=[]
    for quantity in (5,10):
        base=test.fixture([100.]*10,[(0,1,8,1)],quantity)
        base[0]['last'][1]=100.;base[1]['bid'][1]=100.;base[1]['ask'][1]=102.
        filtered,trace=permit(base,True,'spread adverseが初回ATR半分と一致_'+str(quantity))
        for side in (1,-1):
            value=base if side>0 else test.mirror(base)
            permit(value,True,'上下対称の等号境界_'+str((quantity,side)))
            wide=deepcopy(value)
            if side>0:wide[1]['bid'][1]-=.0001
            else:wide[1]['ask'][1]+=.0001
            permit(wide,False,'幅だけ境界超過_'+str((quantity,side)))
            adverse=deepcopy(value)
            adverse[1]['bid'][1]+=.0001*side;adverse[1]['ask'][1]+=.0001*side
            permit(adverse,False,'不利差だけ境界超過_'+str((quantity,side)))
        prepwide=deepcopy(base);prepwide[1]['bid'][0]=50.;prepwide[1]['ask'][0]=150.
        permit(prepwide,True,'古い準備行を見ず公開行を判定_'+str(quantity))
        pubwide=deepcopy(base);pubwide[1]['bid'][1]=50.;pubwide[1]['ask'][1]=150.
        permit(pubwide,False,'公開行の幅が広ければ準備行正常でも拒否_'+str(quantity))
        for label,mutate in (
            ('qflag',lambda v:v[1]['quote_valid'].__setitem__(1,False)),
            ('bidnan',lambda v:v[1]['bid'].__setitem__(1,np.nan)),
            ('askinf',lambda v:v[1]['ask'].__setitem__(1,np.inf)),
            ('locked',lambda v:v[1]['bid'].__setitem__(1,v[1]['ask'][1])),
            ('crossed',lambda v:v[1]['bid'].__setitem__(1,v[1]['ask'][1]+1.)),
            ('lastnan',lambda v:v[0]['last'].__setitem__(1,np.nan)),
            ('lastzero',lambda v:v[0]['last'].__setitem__(1,0.))):
            value=deepcopy(base);mutate(value);permit(value,False,'未知又は不正を拒否_'+str(quantity)+'_'+label)
        for atr in (0.,np.nan):
            value=deepcopy(base);value[3]['cycles'][0,5]=atr
            try:filtering.filter_paper(value[3],value[0],value[1])
            except AssertionError:test.check('初回ATR不正は補完せず停止_'+str((quantity,atr)),True)
            else:raise AssertionError('不正初回ATR通過')
        favorable=deepcopy(base);favorable[0]['last'][1]=110.
        permit(favorable,True,'有利な価格差は許可_'+str(quantity))
        permit(test.mirror(favorable),True,'売り側も有利な価格差は許可_'+str(quantity))
        # ----------------------------------------
        # 元入力の現在ATRは参照せず、親初回aだけに固定。
        changed=deepcopy(base);changed[0]['atr'][:]=.00001
        permit(changed,True,'現在ATRへ後付差替しない_'+str(quantity))
        changed=deepcopy(base);changed[3]['cycles'][0,5]=2.
        permit(changed,False,'親初回ATR変更には正しく反応_'+str(quantity))
        # 後続quote/Last・親最終PL/終点・極値を変えても公開時採否は不変。
        future=deepcopy(base);future[0]['last'][2:]+=99999.
        future[1]['bid'][2:]=1.;future[1]['ask'][2:]=100000.;future[1]['quote_valid'][2:]=False
        for column in (1,2,3,4,6,7,8,9):future[3]['cycles'][:,column]=987654321.
        changed,other=filtering.filter_paper(future[3],future[0],future[1])
        test.same('将来quote Last親PL終点改変で通知不変_'+str(quantity),changed['orders'],filtered['orders'])
        test.check('将来情報改変で公開trace不変_'+str(quantity),trace==other)
        cut=5;prefix=deepcopy(base)
        for field in ('seq','time_s','last','atr'):prefix[0][field]=prefix[0][field][:cut]
        for field in prefix[1]:prefix[1][field]=prefix[1][field][:cut]
        prefix[3]['orders']=prefix[3]['orders'][prefix[3]['orders'][:,0]<cut]
        part,pt=filtering.filter_paper(prefix[3],prefix[0],prefix[1])
        test.same('真の未来切断で通知prefix不変_'+str(quantity),filtered['orders'][filtered['orders'][:,0]<cut],part['orders'])
        test.check('真の未来切断で公開trace不変_'+str(quantity),trace==pt)
        # ----------------------------------------
        # 公開時に正常なら、後続実行行が極端に広がっても遡及取消しない。
        widefill=deepcopy(base);widefill[1]['bid'][2]=100.;widefill[1]['ask'][2]=120.
        fp,ft=permit(widefill,True,'未来実行気配で採否を変えない_'+str(quantity))
        qconfig=next(c for c in configs if c['id']=='E01_Q')
        for side in (1,-1):
            v=widefill if side>0 else test.mirror(widefill)
            chosen,trace2=filtering.filter_paper(v[3],v[0],v[1]);v=list(v);v[3]=chosen
            actual=test.run(tuple(v),qconfig)
            test.check('広い次行でも既受理注文を実約定_'+str((quantity,side)),actual['orders'][0,0]==2.)
            test.check('未来fillの損失を隠さない_'+str((quantity,side)),actual['stats'][0]==-20.*quantity)
        records.append(dict(quantity=quantity,decision_row=trace[0]['publication_row'],boundary_accepted=True,wide_next_fill_loss=-20.*quantity))
    return records


def key_checks(configs: list[dict]) -> None:
    """
    機能: 手法名を除き、初回aと実数値方策を含む完全同値キーを反証する。
    引数: configs(list[dict])は実固定目録。
    返り値: None。account境界はI/O源の別静的監査へ委ねる。
    """
    value=test.fixture([100.]*10,[(0,1,8,1)],5);feed=test.interface.make_feed(value[3])
    config=next(c for c in configs if c['id']=='E01_Q');parameters=test.interface.policy_parameters(config)
    key=filtering.economic_key(feed,parameters)
    clone=deepcopy(config);clone['id']='手法名だけ別'
    test.check('同feed別手法IDは同値',key==filtering.economic_key(feed,test.interface.policy_parameters(clone)))
    test.check('連続配置だけの違いは同値',key==filtering.economic_key(np.asfortranarray(feed),parameters))
    changed=deepcopy(value[3]);changed['cycles'][0,5]*=2.
    test.check('親初回a違いは非同値',key!=filtering.economic_key(test.interface.make_feed(changed),parameters))
    alternate=parameters.copy();alternate[0]=.25
    test.check('数値方策違いは非同値',key!=filtering.economic_key(feed,alternate))
    changed=feed.copy();changed[0,0]+=1.
    test.check('通知公開行違いは非同値',key!=filtering.economic_key(changed,parameters))


def execute() -> None:
    """
    機能: 新catalogの低R/Qと同値キーを独立人工へ拘束する。
    引数: なし。
    返り値: None。市場本文・金融再生を使わない。
    """
    paths=[GATED/'catalog126g.py',GATED/'feed_filter126.py',test.BBO/'core126.py',test.BBO/'policy_bbo126.py',
           test.BBO/'bbo_order_kernel126.py',test.ENGINE/'policy126.py',TASK/'design/catalog126.py',Path(__file__),HERE/'low_cases126.py']
    sources={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    configs=catalog.catalog();policies=catalog.policies()
    test.check('固定53条件とpolicy19',len(configs)==53 and len(policies)==19)
    low={c['protect_start_atr']:c for c in policies if c['id'] in ('P025','P050','P075','P01')}
    floors=verify(low);quotes=quote_checks(configs);key_checks(configs)
    assert all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in sources.items())
    proof=dict(passed=True,count=len(test.CHECKS),checks=test.CHECKS,low_floor=floors,quote_cases=quotes,sources=sources,
        account_scope='economic_key単体は商品場IDを含まない。同一accountのpacket/quote/market/end/cap/数値源が同じことはrunnerの局所memo別監査で拘束する。',
        market_reads=0,financial_replays=0,API=0,real_orders=0)
    target=HERE/'低利益床と公開気配及び完全同値キーの独立純人工.json';assert not target.exists()
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,count=len(test.CHECKS)),ensure_ascii=False))


if __name__=='__main__':
    try:execute()
    except Exception as error:
        path=HERE/('独立純人工停止_'+str(time.time_ns())+'.json')
        path.write_text(json.dumps(dict(passed=False,error=repr(error),checks=test.CHECKS,market_reads=0,financial_replays=0),
            ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise
