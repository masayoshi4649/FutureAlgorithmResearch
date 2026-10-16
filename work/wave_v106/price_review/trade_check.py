"""取引更新代理の窓・原行接頭・scopeだけを、金融結果なしの独立算式で点検する。"""

from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
import sys

import numpy as np

from range_engine_check import load,digest,fixture,economy


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v106/trade_gate'


def fixture_raw() -> dict:
    """
    機能: 同clock窓外に出来高reset、窓内には二つの正増買票を持つ人工原行を作る。
    引数: なし。
    返り値: dictは44列の必要部分だけ。実NPZや市場原本は読まない。
    """
    return dict(raw_seq=np.arange(7,dtype=np.int64),price_time_s=np.array([0.,10.,10.,10.,20.,20.,21.]),
        bid=np.full(7,100.),ask=np.full(7,101.),last=np.array([100.,100.,100.,100.,101.,101.,101.]),
        volume=np.array([10.,10.,9.,9.,10.,11.,11.]),volume_time_s=np.array([0.,10.,10.,10.,20.,20.,21.]),
        volume_delta=np.array([np.nan,0.,np.nan,0.,1.,1.,0.]),volume_delta_usable=np.array([False,True,False,True,True,True,True]),
        volume_reset_reason=np.array([1,0,32,0,0,0,0],np.uint16))


def oracle(raw: dict, row: int, window: int, side: int) -> dict:
    """
    機能: 候補までの原行だけを逐次走査し、票と未知資格を同じstrict窓へ数える。
    引数: raw(dict)、row/window/side(int)は原行、代理秒幅、方向。
    返り値: dictはknown/reason/買売票/採否。実装のprefix配列を使わない。
    """
    if row<0 or row>=len(raw['raw_seq']) or not np.isfinite(raw['price_time_s'][row]):
        return dict(known=False,reason=2,up=0,down=0,accepted=False)
    stamp=float(raw['price_time_s'][row]);cut=stamp-window;maximum=-np.inf;public=[];flags=[];votes=[]
    for i in range(row+1):
        time=raw['price_time_s'][i];finite=np.isfinite(time);reverse=finite and time<maximum
        if finite and time>maximum:public.append(i)
        if finite:maximum=max(maximum,float(time))
        common=not finite or reverse or i==0 or (i>0 and (raw['raw_seq'][i]!=raw['raw_seq'][i-1]+1 or not np.isfinite(raw['price_time_s'][i-1])))
        volume=bool(raw['volume_delta_usable'][i] and raw['volume_reset_reason'][i]==0)
        increased=bool(volume and np.isfinite(raw['volume_delta'][i]) and raw['volume_delta'][i]>0)
        last=raw['last'][i];prior_valid=i>0 and np.isfinite(raw['bid'][i-1]) and np.isfinite(raw['ask'][i-1]) and 0<raw['bid'][i-1]<raw['ask'][i-1]
        last_valid=np.isfinite(last) and last>0;flag=(4 if common else 0)|(0 if volume else 8)|(16 if increased and not (last_valid and prior_valid) else 0)
        direction=0
        if increased and last_valid and prior_valid and not common:
            direction=1 if last>=raw['ask'][i-1] else -1 if last<=raw['bid'][i-1] else 0
        flags.append(flag);votes.append(direction)
    prior=[i for i in public if raw['price_time_s'][i]<=cut];first=[i for i in public if raw['price_time_s'][i]>cut]
    reason=0 if prior else 1;begin=first[0] if first else row+1
    for flag in flags[begin:]:reason|=flag
    up=sum(v==1 for v in votes[begin:]);down=sum(v==-1 for v in votes[begin:]);total=up+down
    accepted=reason==0 and total>=2 and Fraction(side*(up-down),total)>=Fraction(1,4)
    return dict(known=reason==0,reason=reason,up=up,down=down,accepted=bool(accepted))


def main() -> None:
    """
    機能: v1Falseを保ちv2を独立oracleへ照合、金融部へのmask接続を小人工で確認する。
    引数: なし。大型入力、金融結果、現Night、API、registryを読まない。
    返り値: Noneは純人工と最終source束縛の独立証跡。金融本体の書換えなし。
    """
    destination=HERE/'trade_v2の窓資格と入口scope及びdriverの独立人工.json';assert not destination.exists()
    names=('votes.py','prepare.py','data.py','policy.py','runner.py','common.py','catalog.py','features.py','selection.py','interface.py','engine/core.py','engine/accounting.py')
    before={str((SOURCE/name).relative_to(ROOT)):digest(SOURCE/name) for name in names}
    V=load('独立取引更新v2',SOURCE/'votes.py');oldpath=SOURCE/'archive/初版_窓外基準尾部の資格検査/votes.py';old=load('独立取引更新v1保持',oldpath)
    raw=fixture_raw();current=V.measure(raw,V.context(raw),6,10,1);prior=old.measure(raw,old.context(raw),6,10,1)
    assert not prior['known'] and prior['reason']==8 and current['known'] and current['accepted'] and current['direction_votes']==2
    false=HERE/'trade_窓外resetが窓内票を未知へ変えるFalse.json'
    false_payload=dict(全合格=False,scope='保存した修正前sourceへの純人工境界反例。実市場損益ではない。',
        source=dict(path=str(oldpath.relative_to(ROOT)),SHA256=digest(oldpath)),price_times=raw['price_time_s'].tolist(),
        reset_row=2,candidate_row=6,window=10,仕様上の窓='11<price_time<=21、原row<=6',仕様上の正常買票=2,
        修正前=prior,修正後=current,新金融=0,元板NPZ=0,API=0)
    if false.exists():
        assert json.loads(false.read_text(encoding='utf8'))==false_payload
    else:false.write_text(json.dumps(dict(全合格=False,scope='保存した修正前sourceへの純人工境界反例。実市場損益ではない。',
        source=dict(path=str(oldpath.relative_to(ROOT)),SHA256=digest(oldpath)),price_times=raw['price_time_s'].tolist(),
        reset_row=2,candidate_row=6,window=10,仕様上の窓='11<price_time<=21、原row<=6',仕様上の正常買票=2,
        修正前=prior,修正後=current,新金融=0,元板NPZ=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    count=0
    for mirror in (False,True):
        for bad in ('none','withinreset','outsidegap','withingap','clockreverse','clocknan','inside','lastnan','priorasknan','unequalclock'):
            value=deepcopy(raw)
            if mirror:value['bid'],value['ask'],value['last']=200.-raw['ask'],200.-raw['bid'],200.-raw['last']
            if bad=='withinreset':value['volume_reset_reason'][4]=32;value['volume_delta_usable'][4]=False
            if bad=='outsidegap':value['raw_seq'][2:]+=1
            if bad=='withingap':value['raw_seq'][5:]+=1
            if bad=='clockreverse':value['price_time_s'][5]=19.
            if bad=='clocknan':value['price_time_s'][5]=np.nan
            if bad=='inside':value['last'][4]=100.5 if not mirror else 99.5
            if bad=='lastnan':value['last'][4]=np.nan
            if bad=='priorasknan':value['ask'][3]=np.nan
            if bad=='unequalclock':value['volume_time_s'][4:6]=[19.,19.]
            for row in (3,4,5,6):
                for window in (10,30,60):
                    for side in (-1,1):
                        actual=V.measure(value,V.context(value),row,window,side);expected=oracle(value,row,window,side)
                        assert actual['known']==expected['known'] and actual['reason']==expected['reason'] and actual.get('measured_up_votes',0)==expected['up'] and actual.get('measured_down_votes',0)==expected['down'] and actual['accepted']==expected['accepted'];count+=1
                        prefix={k:v[:row+1] for k,v in value.items()};assert actual==V.measure(prefix,V.context(prefix),row,window,side);count+=1
    # ----------------------------------------
    # scope外の入口と元pending/heldを守る。独立Mathコピー上のPython小人工のみ。
    previous={k:sys.modules.get(k) for k in ('common','votes','catalog','data','policy','interface')}
    C=load('独立取引確認common',SOURCE/'common.py');cat=load('独立取引確認catalog',SOURCE/'catalog.py')
    sys.modules.update(common=C,votes=V,catalog=cat)
    try:
        D=load('独立取引確認data',SOURCE/'data.py');P=load('独立取引確認policy',SOURCE/'policy.py');I=load('独立取引確認interface',SOURCE/'interface.py')
        sys.modules.update(data=D,policy=P,interface=I);R=load('独立取引確認driver',SOURCE/'runner.py')
    finally:
        for k,v in previous.items():
            if v is None:sys.modules.pop(k,None)
            else:sys.modules[k]=v
    snapshot=HERE/'trade_engine_snapshot.py';snapshot.write_bytes((SOURCE/'engine/core.py').read_bytes());engine=load('trade_engine_snapshot',snapshot);I.module=lambda name,path:engine
    configs=P.configs();assert len(configs)==36 and len({c['id'] for c in configs})==36
    accounts=0
    for symbol in ('TOPIX','NK225'):
        for side in (-1,1):
            for family in (1,2):
                p,normal,_=fixture(symbol,side,2,'LIMIT');normal['entry_families'][1]=family
                for scope in ('R','C','BOTH'):
                    config=deepcopy(next(c for c in configs if c['gate_scope']==scope and c['trade_window_seconds']==10 and c['margin_ticks']==1 and c['range_entry']=='LIMIT'))
                    config.update(start_offset=0.,cut_offset=2.,force_offset=1.)
                    features={1:dict(known=True,reason=0,accepted=False,direction_votes=2)}
                    packet=dict(normals={config['baseline_id']:{symbol:normal}},trade_features={symbol:{'10':features}})
                    selected=D.for_case(packet,symbol,config);mask,reasons=selected['entry_filter'],selected['filter_reason'];targeted=scope=='BOTH' or scope==('C' if family==1 else 'R')
                    assert mask[1]==(not targeted) and np.all(mask[2:])
                    for field in ('event','entry_quality','entry_reset','support_price','execution_to_raw_index','range_pending_trend'):np.testing.assert_array_equal(selected['normal'][field],normal[field]);count+=1
                    assert selected['normal']['entry_id']==config['id'] and normal['entry_id']=='私有R人工'
                    baseline=I.play(p,normal,config,quantity=config['quantity'][symbol],python=True)
                    actual=I.play(p,selected['normal'],config,quantity=config['quantity'][symbol],python=True,entry_filter=mask,filter_reason=reasons);accounts+=1
                    if targeted:assert len(actual['orders'])==len(actual['trades'])==0 and actual['curve'].sum()==0
                    else:
                        for key in ('orders','trades','growth_cohorts','curve','source_curve','target_trace'):np.testing.assert_array_equal(actual[key],baseline[key]);count+=1
                    count+=economy(p['record'],actual)
                    allowed=np.ones(len(mask),bool);allowed[2:]=False;future=I.play(p,normal,config,quantity=config['quantity'][symbol],python=True,entry_filter=allowed)
                    for key in ('orders','trades','growth_cohorts','curve','source_curve','target_trace'):np.testing.assert_array_equal(future[key],baseline[key]);count+=1
                    fp=R.execution_fingerprint(p,normal,config,mask,reasons);changed=deepcopy(config);changed['id']='表示IDだけ変更';changed['trade_window_seconds']=60
                    assert fp==R.execution_fingerprint(p,normal,changed,mask,reasons);count+=1
                    denied=mask.copy();denied[1]=not denied[1];assert fp!=R.execution_fingerprint(p,normal,config,denied,reasons);count+=1
    # ----------------------------------------
    # 新金融源は同bytes、四引数会計、八部品/spec exact、v2指紋の登録前固定を静的確認。
    for name in ('common.py','catalog.py','features.py','selection.py','interface.py','engine/core.py','engine/accounting.py'):
        assert digest(SOURCE/name)==digest(ROOT/'work/wave_v106/range_price'/name);count+=1
    text=(SOURCE/'runner.py').read_text(encoding='utf8');assert "registered[0]['spec']==plan['spec']" in text and 'ACCOUNT.inspect((session,symbol),record,output,normal)' in text
    plan=json.loads((SOURCE/'試行計画_v2.json').read_text(encoding='utf8'));fixed=json.loads((SOURCE/'金融開始前の固定_v2.json').read_text(encoding='utf8'))
    assert set(plan['spec'])=={'entry','management','exit','allocation','costs','execution','data','implementation'}
    assert fixed['configs']==configs and fixed['source_SHA256']==plan['spec']['implementation']
    assert digest(SOURCE/'試行計画_v2.json')==fixed['plan_SHA256']
    assert all(digest(ROOT/name)==sha for name,sha in fixed['source_SHA256'].items())
    assert before=={str((SOURCE/name).relative_to(ROOT)):digest(SOURCE/name) for name in names}
    proof=dict(全合格=True,scope='取引更新gate v2の非金融sourceと独立人工。NPZ/入力packet/金融結果を読まない。',
        独立検査数=count,人工経済口座=accounts,修正前FalseSHA256=digest(false),source_SHA256=before,source開始終端一致=True,
        レビューsource_SHA256=digest(Path(__file__)),私有engineSHA256=digest(snapshot),部品8のcosts適合=True,
        正式入力読取=0,新金融=0,金融結果読取=0,現NightAPI=0,registry変更=0,
        制約=['volume_delta_usableは量時計<=価格時計を許す。時刻同値は票の資格に追加していない。したがって代理票は同clockの真の約定方向を確定しない。',
            '1更新1票で量100でも1でも同じ。Lastと直前raw BBOは取消/補充や隠れ注文、集計量の全方向を同定しない。',
            'scope外の入口規則はexactでも、共有保有を通じた後続の実取引数や収支は変わり得る。未対象商品の全P/L不変とは主張しない。',
            '窓はCurrentPriceTime代理で受信時間ではない。同clock後半は候補rawrow以下だけ数える。',
            '同全執行入力のreuseは独立した金融成功数ではない。新mask/理由が違えばreuseしない。'])
    destination.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print('trade v2独立人工合格',count,'検査',accounts,'人工口座',flush=True)


if __name__=='__main__':main()
