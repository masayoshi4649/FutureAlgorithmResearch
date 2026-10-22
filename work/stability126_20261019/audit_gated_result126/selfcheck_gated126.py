"""市場を読まず独立監査器の通知・Q・同値指紋と反例検出を確認する。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
TASK=HERE.parent
sys.path.insert(0,str(HERE));sys.path.insert(0,str(TASK/'gated_bbo126'))
import audit_gated126 as audit
import catalog126g
import feed_filter126 as source
from policy126 import policy_parameters


def fixture() -> tuple[dict,dict,dict]:
    """
    機能: 二方向の親通知を持つ人工入力を作る。
    引数: なし。
    返り値: tuple[dict,dict,dict]は元通知・価格・気配。
    """
    orders=np.array([[2,1,1,1,5,100,1,1],[8,7,1,-1,5,105,9,0],
                     [10,9,2,-1,5,100,1,1],[14,13,2,1,5,95,9,0]],float)
    cycles=np.zeros((2,10));cycles[:,0]=[1,2];cycles[:,5]=[4,6]
    paper=dict(orders=orders,cycles=cycles)
    ready=dict(seq=np.arange(16),time_s=np.arange(16.)+100,last=np.full(16,100.),atr=np.full(16,9.))
    quotes=dict(seq=ready['seq'].copy(),time_s=ready['time_s'].copy(),bid=np.full(16,99.),ask=np.full(16,101.),quote_valid=np.ones(16,bool))
    return paper,ready,quotes


def main() -> None:
    """
    機能: 独立数式と凍結公開関数を人工だけで照合し、改変検出も試す。
    引数: なし。
    返り値: None。市場・金融・APIの利用は零。
    """
    checks=[]
    def ok(name: str, condition: bool=True) -> None:
        """
        機能: 一人工条件の成立を保存する。
        引数: name(str)は条件名、condition(bool)は成立。
        返り値: None。不成立は停止する。
        """
        assert condition,name
        checks.append(name)
    for index in range(18):
        paper,ready,quotes=fixture()
        if index==1:quotes['ask'][2]=101.00000001
        if index==2:quotes['ask'][2]=103.
        if index==3:quotes['bid'][2]=98.;quotes['ask'][2]=102.
        if index==4:quotes['bid'][2]=98.;quotes['ask'][2]=102.0000001
        if index==5:quotes['quote_valid'][2]=False
        if index==6:quotes['bid'][2]=np.nan
        if index==7:quotes['ask'][2]=np.inf
        if index==8:quotes['bid'][2]=101.
        if index==9:quotes['bid'][2]=102.
        if index==10:ready['last'][2]=np.nan
        if index==11:ready['last'][2]=0.
        if index==12:quotes['bid'][10]=97.;quotes['ask'][10]=103.
        if index==13:quotes['bid'][10]=96.9999999;quotes['ask'][10]=103.
        if index==14:quotes['bid'][2]=93.;quotes['ask'][2]=95.
        if index==15:quotes['bid'][10]=104.;quotes['ask'][10]=106.
        if index==16:quotes['bid'][3:9]=20.;quotes['ask'][3:9]=180.
        if index==17:paper['cycles'][:,3]=[1e8,-1e8];paper['cycles'][:,2]=[1e6,1e6]
        selected,traces=audit.quote_filter(paper,ready,quotes)
        expected,expected_traces=source.filter_paper(paper,ready,quotes)
        ok(str(index)+'_Q診断一致',traces==expected_traces)
        ok(str(index)+'_採用通知全値一致',np.array_equal(selected['orders'],expected['orders']))
        ok(str(index)+'_固定初回ATR通知一致',np.array_equal(audit.feed(paper),source.make_feed(paper)))
        for side in (1,-1):
            transformed=deepcopy(paper);transformed['orders'][:,3]*=side
            transformed_ready=deepcopy(ready);transformed_ready['last']=200.-ready['last'] if side<0 else ready['last'].copy()
            transformed_quotes=deepcopy(quotes)
            if side<0:
                transformed_quotes['bid']=200.-quotes['ask'];transformed_quotes['ask']=200.-quotes['bid']
            own,trace=audit.quote_filter(transformed,transformed_ready,transformed_quotes)
            target,target_trace=source.filter_paper(transformed,transformed_ready,transformed_quotes)
            ok(str(index)+'_方向'+str(side)+'採否一致',trace==target_trace and np.array_equal(own['orders'],target['orders']))
    paper,ready,quotes=fixture()
    for config in catalog126g.catalog():
        own=audit.parameters(config);expected=policy_parameters(config)
        ok(config['id']+'_数値方策一致',np.array_equal(own,expected))
        ok(config['id']+'_通知方策指紋一致',audit.identity(audit.feed(paper),own)==source.economic_key(source.make_feed(paper),expected))
    original=audit.feed(paper);changed=original.copy();changed[0,9]+=.1
    ok('初回ATR改変は別指紋',audit.identity(original,np.zeros(4))!=audit.identity(changed,np.zeros(4)))
    ok('連続配置だけの違いは同指紋',audit.identity(original,np.zeros(4))==audit.identity(np.asfortranarray(original),np.zeros(4)))
    a=np.arange(12.,dtype=np.float64).reshape(3,4)
    ok('全配列値改変検出',audit.array_hash(a)!=audit.array_hash(a+1))
    ok('全配列型改変検出',audit.array_hash(a)!=audit.array_hash(a.astype(np.float32)))
    ok('全配列形改変検出',audit.array_hash(a)!=audit.array_hash(a.reshape(4,3)))
    previous=audit.meta(TASK/'audit_bbo_result126/全千三百十二BBO会計と全行清算の独立監査.json')
    ok('再利用独立会計源は旧1312監査時と同bytes',previous['source_sha256']==audit.sha(audit.math_path))
    ok('市場の監査読取零',not audit.READS and not audit.SEEN)
    proof=dict(passed=True,checks=checks,count=len(checks),original_market_reads=0,saved_market_reads=0,financial_replays=0,
        sources={str(p.relative_to(audit.ROOT).as_posix()):audit.sha(p) for p in (Path(audit.__file__),Path(__file__),audit.math_path)},
        scope='人工Q/通知/固定a/同値指紋/全配列改変。1312監査済み独立数式の源も拘束。')
    target=HERE/'監査器の独立人工と改変検出_修正後.json'
    audit.save(target,proof)
    print(json.dumps(dict(passed=True,checks=len(checks),sha256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':main()
