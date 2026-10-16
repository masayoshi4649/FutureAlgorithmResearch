"""独立集計器を合成保存配列だけへ接続し、市場読取前に分母と順位を固定する。"""

from copy import deepcopy
from datetime import datetime,timedelta,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

import result_audit as audit


HERE=Path(__file__).resolve().parent


def source_module(name: str):
    """
    機能: 所有人工の期待側として、source関数だけを読み込む。
    引数: name(str) は既存所有源のstem。
    返り値: module。main/guard/市場IO関数は呼び出さない。
    """
    spec=importlib.util.spec_from_file_location('期待用_'+name,HERE/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def synthetic_dataset(session: str,index: int,n: int=100) -> dict:
    """
    機能: first-hit計算を含まない保存採点fixtureを生成する。
    引数: session(str)、index/n(int) は人工場名・番号・足数。
    返り値: dict は独立集計に必要なprepared列だけ。全値が合成。
    """
    day=datetime.fromisoformat(session[:10]).replace(tzinfo=timezone(timedelta(hours=9)))
    end=day+timedelta(hours=15,minutes=40) if session.endswith('_Day') else day+timedelta(days=1,hours=5,minutes=55)
    row=np.arange(n);time=end.timestamp()-(n+10-row)*60.;pub=row.astype(np.int64)*3+1
    valid=np.ones(n,bool);eligible=np.ones(n,bool);ml=row>=29
    X=np.column_stack((np.sin(row*.17+index*.13),np.cos(row*.07-index*.1),
        row/100.,(row%7)/7.,np.ones(n),np.sin(row*.04+index*.2)))
    signals=np.zeros((n,32),np.int8)
    for k in range(32):
        for r in range(k%5,n,7+k%3):signals[r,k]=1 if (r//7+k+index)%2 else -1
    labels=np.empty((n,2,3),np.int8)
    for r in range(n):
        for side in range(2):
            for risk in range(3):labels[r,side,risk]=(1,-1,0,2)[(r+side+index+risk)%4]
    labels[0,0,0]=-2
    terminal=np.broadcast_to((pub+2)[:,None,None],(n,2,3)).copy()
    return dict(X=X,signals=signals,eligible=eligible,ml_eligible=ml,bars__valid=valid,
        bars__anchor=np.full(n,4000.),bars__t_s=time,bars__pub_raw_row=pub,bars__pub_price_time_s=time+60.,
        target__labels=labels,target__terminal_raw_row=terminal,target__mfe=np.full((n,2),12.),
        target__mae=np.full((n,2),-6.),target__first_10_raw_row=np.tile((pub+5)[:,None],(1,2)),
        target__first_10_time_s=np.tile((time+90)[:,None],(1,2)),
        target__mae_before_first_10=np.full((n,2),-3.),target__common_lock_end=pub+4)


def root_dataset(session: str,data: dict) -> dict:
    """
    機能: 合成保存fixtureをsource accountの入力名へ写す。
    引数: session(str)、data(dict) は人工prepared。
    返り値: dict は同じ人工値のview。原データ読取を含まない。
    """
    return dict(session=session,bars={name.removeprefix('bars__'):value for name,value in data.items() if name.startswith('bars__')},
        target={name.removeprefix('target__'):value for name,value in data.items() if name.startswith('target__')},
        eligible=data['eligible'],ml_eligible=data['ml_eligible'],X=data['X'],signals=data['signals'])


def main() -> None:
    """
    機能: 全37場44規則の合成再集計と、閾値・順位・False境界を検査する。
    引数: なし。
    返り値: None。人工証跡だけを新規保存し、市場結果は開かない。
    """
    initial=audit.fingerprints();own=audit.fingerprints(audit.SELF);checker=audit.Checker()
    root=source_module('run');learner=source_module('learner')
    # ----------------------------------------
    # 五状態を全候補/解決内/未決の別分母で数える。
    checker.equal(audit.tally([1,-1,0,2,-2]),dict(順先=1,逆先=1,窓末未決=1,EOF未決=1,基準不可=1,
        n=5,resolved=2,全候補順先率=.2,解決内順先率=.5,解決率=.4),'五状態')
    checker.equal(audit.tally([]),dict(順先=0,逆先=0,窓末未決=0,EOF未決=0,基準不可=0,
        n=0,resolved=0,全候補順先率=None,解決内順先率=None,解決率=None),'分母なし')
    for sequence in ([1]*10,[-1]*7,[0,2,-2],[1,-1]*5+[2]*8):checker.equal(audit.tally(sequence),root.counts(np.array(sequence,np.int8)),'率の独立照合')
    # ----------------------------------------
    # 固定logisticの別式、閾値・差・状態edge・接頭を分離する。
    X=np.array([[-100.,0.,1.],[0.,0.,1.],[100.,0.,1.]])
    model=dict(input_columns=3,active=[0],mean=[0.],scale=[1.],coefficient=[0.,1.])
    expected=np.array([1/(1+np.exp(8)),.5,1/(1+np.exp(-8))])
    checker.require(np.allclose(audit.probabilities(model,X),expected,atol=1e-15),'clipとsigmoid手計算')
    checker.require(np.allclose(audit.probabilities(model,X),learner.predict(model,X),atol=1e-15),'別式predict')
    long=np.array([.4,.7,.8,.8,.7,.1,.1,.7,.4,.7,.65,.65,.65000000001])
    short=np.array([.2,.1,.1,.1,.1,.7,.8,.1,.4,.1,.55,.54999999999,.55])
    eligible=np.ones(len(long),bool);eligible[3]=False
    for threshold in audit.THRESHOLDS:
        expected=learner.publications(long,short,eligible,threshold)
        got=audit.publications(long,short,eligible,threshold)
        checker.require(np.array_equal(got,expected),'閾値差edge全行')
        for end in range(len(long)+1):
            checker.require(np.array_equal(audit.publications(long[:end],short[:end],eligible[:end],threshold),got[:end]),'edge接頭不変')
    checker.require(np.array_equal(audit.publications(np.array([.75,.75,.75]),np.array([.5,.5,.5]),np.array([1,1,1],bool),.65),[1,0,0]),'同状態連射なし')
    # 共通lock等号は次候補不可。三幅に別の採用群を作らない。
    checker.equal(audit.chosen_rows(np.array([1,-1,1,1,-1]),np.ones(5,bool),np.array([1,3,4,5,9]),np.array([4,4,5,9,9])),[0,3],'lock等号除外')
    # ----------------------------------------
    # 合成37場。学習21だけからmodelを生成し、集計器は再fitしない。
    sessions=[]
    for i in range(37):
        day=datetime(2020,1,1)+timedelta(days=i//2)
        sessions.append(day.date().isoformat()+('_Day' if i%2==0 else '_Night'))
    splits=dict(学習=sessions[:21],選択=sessions[21:27],時系列別枠=sessions[27:33],追加別枠=sessions[33:])
    data={s:synthetic_dataset(s,i) for i,s in enumerate(sessions)}
    names=['price_a','price_b','ma_a','volume_a','book_a','peer_a'];groupmap=dict(zip(names,['price','price','ma','volume','book','peer']))
    models={}
    for identifier,groups in audit.GROUPS.items():
        columns=[i for i,name in enumerate(names) if groupmap[name] in groups];sides=[]
        for side in range(2):
            xx=[];yy=[];ww=[]
            for session in splits['学習']:
                v=data[session];lab=v['target__labels'][:,side,1];mask=v['ml_eligible']&(np.arange(len(lab))%5==0)&np.isin(lab,(-1,1));n=int(mask.sum())
                if n:xx.append(v['X'][mask][:,columns]);yy.append((lab[mask]==1).astype(float));ww.append(np.full(n,1/n))
            sides.append(learner.fit(np.vstack(xx),np.concatenate(yy),np.concatenate(ww),10.))
        models[identifier]=dict(columns=columns,names=[names[i] for i in columns],sides=sides,train_sessions=splits['学習'])
    specs=[]
    families=('整列継続','収束拡散','変化点','レンジ離脱','押し戻り','反発','二市場','板')
    for prefix,family in zip(('T','S','C','B','P','R','M','Q'),families):
        for i in range(1,5):specs.append(dict(id=prefix+str(i).zfill(2),family=family,name='人工'+prefix+str(i)))
    for identifier in audit.GROUPS:
        for threshold in audit.THRESHOLDS:specs.append(dict(id=identifier+'_P'+str(int(round(threshold*100))),family='学習',name='人工学習',model_id=identifier,threshold=threshold))
    accounts=[]
    for session in sessions:
        v=data[session];dataset=root_dataset(session,v);probs={}
        for identifier,model in models.items():
            probs[identifier]=[learner.predict(side,v['X'][:,model['columns']]) for side in model['sides']]
        for index,spec in enumerate(specs):
            signal=v['signals'][:,index] if index<32 else learner.publications(*probs[spec['model_id']],v['ml_eligible'],spec['threshold'])
            accounts.append(root.account(dataset,signal,spec))
    periods=audit.period_sessions(splits,sessions);summaries=[]
    for spec in specs:
        own_rows=[v for v in accounts if v['id']==spec['id']]
        summaries.append(dict(**spec,periods={name:root.merge([v for v in own_rows if v['session'] in pool]) for name,pool in periods.items()}))
    result=dict(sessions=sessions,splits=splits,periods=periods,specifications=specs,models=models,
        accounts=accounts,summaries=summaries,selection=root.choose(summaries),feature_names=names,feature_groups=groupmap)
    checked=audit.audit(result,data,checker)
    checker.require(checked['全合格'] and len(checked['全44集計'])==44,'37場44規則全接口')
    # ----------------------------------------
    # 率平均・別枠混入・family重複・符号消失等の反例を明示する。
    unequal=[deepcopy(accounts[0]),deepcopy(accounts[1])]
    unequal[0]['採用予兆数']=1;unequal[1]['採用予兆数']=9
    for row,sequence in zip(unequal,([1],[-1]*9)):
        row['買い数']=len(sequence);row['売り数']=0
        for cell in row['risks']:
            cell.update(audit.tally(sequence));cell['買い']=audit.tally(sequence);cell['売り']=audit.tally([])
            cell['常時買い']=audit.tally(sequence);cell['常時売り']=audit.tally(sequence)
    checker.equal(audit.merge(unequal)['主評価']['全体']['全候補順先率'],.1,'場率平均.5へ置換しない')
    selection_rows=[]
    for i,(family,improvement) in enumerate((('同族',.4),('同族',.3),('別族',.2),('三族',.1))):
        cell=deepcopy(summaries[0]['periods']['選択']);cell.update(予兆数=12,活動場数=4,買い数=6,売り数=6,対固定方向改善=improvement)
        cell['主評価']['全体']['全候補順先率']=.6
        selection_rows.append(dict(id='人工'+str(i),family=family,periods={'選択':cell,'別枠10':{'成績':999}}))
    selected,trace=audit.ranking(selection_rows);checker.equal(selected['正式候補'],['人工0','人工2','人工3'],'異family三')
    for row in selection_rows:row['periods']['別枠10']={'成績':-999999}
    checker.equal(audit.ranking(selection_rows)[0],selected,'別枠成績に選択依存0')
    checker.equal(audit.period_sessions(splits,sessions)['別枠デイ'],[s for s in sessions[27:] if s.endswith('_Day')],'別枠昼だけ')
    # 資格の独立再計算と末5分・遅延・欠分30本の境界。
    session=sessions[0];v=data[session];day=datetime.fromisoformat(session[:10]).replace(tzinfo=timezone(timedelta(hours=9)))
    audit.validate_dataset(v,dict(end=(day+timedelta(hours=15,minutes=40)).timestamp()),checker)
    bad=deepcopy(v);bad['eligible'][10]=False;rejected=False
    try:audit.validate_dataset(bad,dict(end=(day+timedelta(hours=15,minutes=40)).timestamp()),checker)
    except AssertionError:rejected=True
    checker.require(rejected,'保存eligible不一致を拒否')
    bad=deepcopy(result);bad['selection']['正式候補']=['別枠を見た架空候補'];rejected=False
    try:
        actual=audit.ranking(summaries)[0];checker.equal(bad['selection'],actual,'不正選択')
    except AssertionError:rejected=True
    checker.require(rejected,'不正選択を拒否')
    checker.require(initial==audit.fingerprints() and own==audit.fingerprints(audit.SELF),'有効源始終不変')
    evidence=dict(全合格=True,検査数=checker.count,合成場=37,合成規則=44,合成場規則=37*44,
        source_SHA256=initial,audit_source_SHA256=own,
        実本文読取=dict(結果=0,保存prepared=0,原raw=0,原event=0,金融=0,API=0),
        範囲='合成だけ。source関数と独立別式/逐走査の集計同値。原価格first-hitは再測定しない。')
    path=audit.OWN/'保存採点再加算と固定モデル及び選択期の純人工.json';audit.write_new(path,evidence)
    print(json.dumps(dict(全合格=True,検査数=checker.count,SHA256=hashlib.sha256(path.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':main()
