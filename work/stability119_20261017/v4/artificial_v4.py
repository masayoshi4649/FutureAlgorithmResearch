"""実市場を読まず、元入口の順逆接続・時刻窓・未来接頭を最小の人工で確認する。"""

from copy import deepcopy
from datetime import datetime,timezone,timedelta
import hashlib
import json
from pathlib import Path

import numpy as np

import run_v4 as V


HERE=Path(__file__).resolve().parent
COUNTS={}


def check(value: bool,label: str) -> None:
    """
    機能: 人工期待の一致を件数付きで記録する。
    引数: value(bool)は期待条件、label(str)は検査名。
    返り値: None。不一致で停止する。
    """
    assert value,label
    COUNTS[label]=COUNTS.get(label,0)+1


def base_fixture(n: int=7) -> dict:
    """
    機能: 非対称の元entry・撤回・幅・資格を持つ三入口を合成する。
    引数: n(int)は公開bar数。
    返り値: dictは三入口五配列。市場保存値を含まない。
    """
    entry=np.tile(np.resize(np.array([1,0,-1,0],np.int8),n),(3,1))
    long=np.tile(np.arange(n)%3==0,(3,1));short=np.tile(np.arange(n)%4==0,(3,1))
    width=np.tile(10.+np.arange(n),(3,1));valid=np.ones((3,n),bool);valid[:,3::4]=False
    return dict(specs=[dict(id=ident,name='合成入口'+str(i),description='合成の元条件。') for i,ident in enumerate(V.SOURCE_IDS)],
        entry=entry,exit_long=long,exit_short=short,width=width,valid=valid)


def main() -> None:
    """
    機能: 48条件接続と実反対気配の順逆を人工だけで検査し、sourceに束縛する。
    引数: なし。
    返り値: None。新金融・市場cache・登録は0。既kernelはPython本体だけで人工利用。
    """
    target=HERE/'元入口と反転接続及び接頭の純人工.json';assert not target.exists()
    base=base_fixture();before=deepcopy(base)
    stamp=datetime(2032,1,12,12,tzinfo=V.JST).timestamp();times=stamp+np.arange(7)*60
    model=V.build_variants(base,times)
    check(len(model['specs'])==48 and all(model[k].shape==(48,7) for k in V.POLICY_KEYS),'三入口順逆二出口二執行二時刻の四十八形状')
    for i,spec in enumerate(model['specs']):
        source=V.FAMILIES.index(spec['entry_id'][:-2]);flip=spec['direction_mode']=='reverse'
        quiet=V.quiet_rows(times) if spec['time_mode'] else np.zeros(len(times),bool)
        expected=base['entry'][source]*(-1 if flip else 1);expected=expected.copy();expected[quiet]=0
        check(np.array_equal(model['entry'][i],expected),'元同時点方向だけの反転')
        for key,opposite in (('exit_long','exit_short'),('exit_short','exit_long')):
            expected=base[opposite if flip else key][source].copy();expected[quiet]=True
            check(np.array_equal(model[key][i],expected),'撤回左右の交換と窓内退出')
        expected=base['valid'][source].copy();expected[quiet]=False
        check(np.array_equal(model['valid'][i],expected) and np.array_equal(model['width'][i],base['width'][source]),'当時資格と幅の保持')
        check(spec['family']==spec['entry_id'] and spec['guard']==2,'順逆を別家族としない')
    check(all(np.array_equal(base[k],before[k]) for k in V.POLICY_KEYS),'元配列不変')
    # ----------------------------------------
    # 未来suffixだけを変えても過去の48政策は変わらない。
    for cut in range(1,7):
        altered=deepcopy(base)
        altered['entry'][:,cut:]*=-1;altered['valid'][:,cut:]=False;altered['width'][:,cut:]+=123
        altered['exit_long'][:,cut:]=~altered['exit_long'][:,cut:]
        changed_times=times.copy();changed_times[cut:]+=3600*14
        future=V.build_variants(altered,changed_times)
        prefix={k:base[k][:,:cut].copy() for k in V.POLICY_KEYS};prefix['specs']=base['specs']
        shorter=V.build_variants(prefix,times[:cut])
        for key in V.POLICY_KEYS:
            check(np.array_equal(model[key][:,:cut],future[key][:,:cut]) and np.array_equal(model[key][:,:cut],shorter[key]),'未来変更と短接頭の一致')
    # ----------------------------------------
    # 日本時刻とNY夏冬時刻の半開区間を価格に依存せず確認する。
    fixtures=[]
    for month in (7,12):
        for hh,mm,ss,wanted in ((8,14,59,False),(8,15,0,True),(8,44,59,True),(8,45,0,False),(9,14,59,False),(9,15,0,True),(9,44,59,True),(9,45,0,False)):
            fixtures.append((datetime(2032,month,12,hh,mm,ss,tzinfo=V.NEW_YORK).timestamp(),wanted))
    for hh,mm,ss,wanted in ((8,44,59,False),(8,45,0,True),(9,14,59,True),(9,15,0,False)):
        fixtures.append((datetime(2032,7,12,hh,mm,ss,tzinfo=V.JST).timestamp(),wanted))
    for epoch,wanted in fixtures:check(bool(V.quiet_rows(np.array([epoch]))[0])==wanted,'DST夏冬と固定窓境界')
    quiet_time=np.array([datetime(2032,7,12,8,50,tzinfo=V.JST).timestamp()]*7)
    timed=V.build_variants(base,quiet_time)
    for i,spec in enumerate(timed['specs']):
        if spec['time_mode']:
            check(np.all(timed['entry'][i]==0) and not timed['valid'][i].any() and timed['exit_long'][i].all() and timed['exit_short'][i].all(),'窓内マスク四列')
    # ----------------------------------------
    # 新kernelを作らず、旧Python本体で同時点順逆の買ask/売bidを検証する。
    pubs=np.array([0,2,4],np.int64);qt=stamp+np.arange(7)
    bid=100.+np.arange(7);ask=bid+.5
    bars=dict(valid=np.ones(3,bool),anchor=np.array([100.25,102.25,104.25]),pub_raw_row=pubs,
        pub_price_time_s=qt[pubs],t_s=qt[pubs].copy())
    quotes=dict(row=np.arange(7,dtype=np.int64),time=qt,bid=bid,ask=ask,last=(bid+ask)/2)
    mat=base_fixture(3);mat['entry'][:]=np.array([1,0,0],np.int8)
    mat['exit_long'][:]=np.array([False,False,True]);mat['exit_short'][:]=np.array([False,False,True])
    mat['width'][:]=20.;mat['valid'][:]=True
    models=V.build_variants(mat,bars['pub_price_time_s']);old=V.engine_v2.replay;answers={}
    V.engine_v2.replay=old.py_func
    try:
        for mode in ('direct','reverse'):
            k=next(i for i,s in enumerate(models['specs']) if s['entry_id']=='COMMON20' and s['direction_mode']==mode and s['exit_mode']==5 and s['execution_mode']==0 and s['time_mode']==0)
            policy={key:models[key][k] for key in V.POLICY_KEYS}
            config=V.run_v2.settings('TOPIX','2032-01-12_Day',0,5,2)
            answers[mode]=V.engine_v2.run_policy(bars,quotes,policy,config)
        a=answers['direct']['ledger'];b=answers['reverse']['ledger']
        check(a.shape==b.shape==(1,16),'既存十六列の実脚')
        check(a[0,1]==b[0,1]==1 and a[0,2]==b[0,2]==5,'同公開後の別原行約定')
        check(a[0,7]==ask[1] and a[0,8]==bid[5] and b[0,7]==bid[1] and b[0,8]==ask[5],'順逆とも実反対気配')
        check(a[0,12]+b[0,12]==-(ask[1]-bid[1]+ask[5]-bid[5])*10000-4*418,'符号反転では消えない往復気配と料')
        check(answers['direct']['summary']['unclosed']==answers['reverse']['summary']['unclosed']==0,'人工終端の実返済')
    finally:V.engine_v2.replay=old
    sources={p.relative_to(V.ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE/'run_v4.py',HERE/'plan_v4.py',Path(__file__),V.BASE/'v2/engine_v2.py')}
    proof=dict(passed=True,scope='人工のみ。元G0三入口・48形状・順逆接続・DST時刻窓・未来接頭・Python旧本体の反対気配。実市場/既所有cache/金融結果/登録の読取又は実行0。',
        counts=COUNTS,total_checks=sum(COUNTS.values()),source_SHA256=sources,
        留保=['元候補の公開時点が同じでも実受理entry集合と退出は同じではない。','窓開始のtimer退出ではなく窓内bar公開で判断し、同rowquote先の約定は可能。','validFalse化はguard2の最初有効Rも後方へ移し得る。','旧kernelの全境界を再証明したとは言わず、既独立監査へ委譲。'],
        market_reads=0,owned_cache_reads=0,formal_financial_replay=0,API=0,registry_changes=0)
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,checks=sum(COUNTS.values()),sha256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':
    main()
