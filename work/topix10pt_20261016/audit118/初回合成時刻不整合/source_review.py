"""実入力を合成stubへ差し替え、分割・学習・公開・先着・選択の接続を監査する。"""

from __future__ import annotations

from contextlib import contextmanager,redirect_stdout
from collections import Counter
from copy import deepcopy
from fractions import Fraction
from io import StringIO
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np


OWN=Path(__file__).resolve().parent
HERE=OWN.parent
sys.path.insert(0,str(HERE))
sys.dont_write_bytecode=True
import run as subject
import features
import learner
import plan
import artificial_input

CHECKS=0


def check(condition: bool) -> None:
    """
    機能: 純人工の独立期待の成立を数える。
    引数: condition(bool)。
    返り値: None。
    """
    global CHECKS
    assert condition
    CHECKS+=1


@contextmanager
def replaced(changes: list[tuple]):
    """
    機能: このプロセスの合成I/Oだけを一時差替し、終了後は元へ戻す。
    引数: changes(list[tuple[object,str,object]]) はmodule・属性・置換。
    返り値: contextmanager。sourceファイルは変更しない。
    """
    previous=[]
    try:
        for obj,name,value in changes:
            previous.append((obj,name,getattr(obj,name)));setattr(obj,name,value)
        yield
    finally:
        for obj,name,value in reversed(previous):setattr(obj,name,value)


def arithmetic_cases() -> dict:
    """
    機能: 率、共通lock、両方向・空足adapter、選択資格を独立期待へ照合する。
    引数: なし。
    返り値: dict は小結果。原価格や登録台帳を読まない。
    """
    counted=subject.counts(np.array([1,1,-1,0,2,-2],np.int8))
    check(counted['n']==6 and counted['resolved']==3)
    check(counted['全候補順先率']==float(Fraction(1,3)))
    check(counted['解決内順先率']==float(Fraction(2,3)) and counted['解決率']==.5)
    empty=subject.counts(np.empty(0,np.int8))
    check(all(empty[k] is None for k in ('全候補順先率','解決内順先率','解決率')))
    bars=dict(pub_raw_row=np.arange(10,71,10,dtype=np.int64),anchor=np.full(7,100.),t_s=np.arange(7,dtype=float)*60,
        pub_price_time_s=np.arange(7,dtype=float)*60,valid=np.ones(7,bool))
    label=dict(common_lock_end=np.array([30,40,50,60,60,60,70],np.int64))
    signal=np.array([1,-1,1,-1,1,-1,1],np.int8)
    check(subject.selected_rows(signal,bars,label,np.ones(7,bool)).tolist()==[0,3,6])
    missing={key:value.copy() for key,value in bars.items()};missing['anchor'][2]=np.nan
    normalized=subject.target_bars(missing)
    check(missing['pub_raw_row'][2]==30 and normalized['pub_raw_row'][2]==-1)
    valid,ml=subject.entry_masks(bars,3000.)
    check(valid.all() and not ml.any())
    delayed={key:value.copy() for key,value in bars.items()};delayed['pub_price_time_s'][1]=121
    check(not subject.entry_masks(delayed,3000.)[0][1])
    summaries=[]
    def candidate(identity: str,family: str,gain: float,n: int=12,active: int=4,buy: int=3,sell: int=9) -> dict:
        """
        機能: 選択六場の資格境界だけを表す合成候補を作る。
        引数: identity/family(str)、gain(float)、n/active/buy/sell(int)。
        返り値: dict。別枠の成績は意図的な極端値でも選択に使わせない。
        """
        return dict(id=identity,family=family,periods={'選択':dict(予兆数=n,活動場数=active,買い数=buy,売り数=sell,
            対固定方向改善=gain,主評価={'全体':{'全候補順先率':.6}}),
            '学習':{'結果':-1e99},'時系列別枠':{'結果':1e99},'追加別枠':{'結果':1e99}})
    summaries=[candidate('A1','A',.2),candidate('A2','A',.3),candidate('B1','B',.15),candidate('C1','C',.1),
        candidate('N11','D',.9,n=11),candidate('ACTIVE3','E',.9,active=3),
        candidate('BUY2','F',.9,buy=2),candidate('SELL2','G',.9,sell=2)]
    selected=subject.choose(summaries)
    check(selected['正式候補']==['A2','B1','C1'] and selected['合格条件数']==4)
    changed=deepcopy(summaries)
    for row in changed:
        for k in ('学習','時系列別枠','追加別枠'):row['periods'][k]={'結果':-1e100}
    check(subject.choose(changed)==selected)
    negative=subject.choose([candidate('NEG','単独',-.2)])
    check(negative['正式候補']==['NEG'] and '資格合格は予測優位の合格ではない' in negative['留保'])
    # 既知30分の価格を0へ丸めず、未決を固定方向の勝ちにも入れない。
    n=7;target={key:np.zeros((n,2,3),dtype=np.int8 if key=='labels' else np.int64)
        for key in ('labels','terminal_raw_row')}
    target['common_lock_end']=label['common_lock_end']
    target['labels'][:,0]=np.array([1,-1,0],np.int8)
    target['labels'][:,1]=np.array([-1,1,2],np.int8)
    target.update(first_10_raw_row=np.full((n,2),-1,np.int64),first_10_time_s=np.full((n,2),np.nan),
        mfe=np.full((n,2),np.nan),mae=np.full((n,2),np.nan),mae_before_first_10=np.full((n,2),np.nan))
    account=subject.account(dict(session='合成',bars=bars,target=target,eligible=np.ones(n,bool)),signal,
        dict(id='検査',family='人工',name='人工'))
    check(account['採用予兆数']==3 and account['買い数']==2 and account['売り数']==1)
    check(account['risks'][1]['順先']==1 and account['risks'][1]['逆先']==2)
    merged=subject.merge([account,deepcopy(account)])
    check(merged['予兆数']==6 and merged['主評価']['全体']['全候補順先率']==1/3)
    check(merged['主評価']['常時買い']['全候補順先率']==0. and merged['主評価']['常時売り']['全候補順先率']==1.)
    return dict(合格=True,選択期以外の改変で選択不変=True,共通lock=[0,3,6])


def learner_cases() -> dict:
    """
    機能: 標準化の学習限定、場重み、独立sideの目的と固定予測を検査する。
    引数: なし。
    返り値: dict。モデル確率の的中率や校正済みの主張はしない。
    """
    x=np.array([[0.,7.],[2.,7.],[10.,7.]])
    y=np.array([0.,0.,1.]);weights=np.array([1.,1.,2.])
    model=learner.fit(x,y,weights)
    check(model['active']==[0] and model['mean']==[5.5])
    check(math.isclose(model['scale'][0],math.sqrt(20.75),rel_tol=1e-14))
    check(model['training_rows']==3 and model['training_rate']==.5)
    before=json.dumps(model,sort_keys=True);prediction=learner.predict(model,x)
    extended=learner.predict(model,np.vstack((x,[[1e100,7.],[-1e100,7.]])))
    np.testing.assert_array_equal(extended[:3],prediction);check(json.dumps(model,sort_keys=True)==before)
    opposite=learner.fit(x,1-y,weights)
    np.testing.assert_allclose(learner.predict(opposite,x),1-prediction,atol=1e-9)
    check(True)
    state=learner.publications(np.array([.5,.75,.8,.55,.4,.75,.2]),
        np.array([.3,.4,.3,.5,.6,.25,.8]),np.array([True,True,True,False,True,True,True]),.65)
    check(state.tolist()==[0,1,0,0,0,1,-1])
    return dict(学習平均=5.5,学習分散=20.75,別枠極端値による再標準化=False)


def synthetic_main(snapshot: dict) -> dict:
    """
    機能: run.mainの原I/Oだけを37合成場へ置換し、74入力から学習・全44条件へ接続する。
    引数: snapshot(dict[str,str]) は完成十源の指紋。
    返り値: dict は入力呼出・fit対象・候補数。元ファイル/登録/市場本文は読まない。
    """
    sessions=[f'合成{i:02d}_Day' for i in range(37)]
    splits=dict(学習=sessions[:21],選択=sessions[21:27],時系列別枠=sessions[27:33],追加別枠=sessions[33:])
    check([len(v) for v in splits.values()]==[21,6,6,4] and len(set(sum(splits.values(),[])))==37)
    inputs=[]
    for i,session in enumerate(sessions):
        for symbol in ('TOPIX','NK225'):
            start=1_000_000.+i*86400
            inputs.append(dict(session=session,symbol=symbol,kind='old_npz' if i<33 else 'jsonl',
                bounds=[start,start+150*60],path='SOURCE_ONLY/'+session+'/'+symbol,
                SHA256='0'*64,bytes=0))
    fixed=dict(sessions=sessions,splits=splits,inputs=inputs,観測T={'TOPIX':.5,'NK225':10.})
    planned=dict(旧原NPZ=66,新JSONL=8,新金融=0,API=0)
    docs={}
    def digest_stub(path: Path) -> str:
        """
        機能: 合成metadata名だけの指紋を作り、実ファイル読取を避ける。
        引数: path(Path)。
        返り値: str は合成識別子。
        """
        if path.parent==HERE and path.name in plan.SOURCES:
            return snapshot[path.relative_to(plan.ROOT).as_posix()]
        return hashlib.sha256(path.name.encode('utf-8')).hexdigest()
    docs['入力目録と時系列分割.json']=fixed
    docs['試行計画.json']=dict(spec=dict(implementation=snapshot,entry={'規則':features.specifications()},data=fixed))
    docs['実測前の検査.json']=dict(全合格=True,source_SHA256=snapshot,evidence=[])
    docs['正式固定.json']=dict(全合格=True,source_SHA256=snapshot,thresholds=plan.THRESHOLDS,
        model_groups=plan.MODEL_GROUPS,ridge=plan.RIDGE,実行予定=planned,
        input_SHA256=digest_stub(Path('入力目録と時系列分割.json')),
        proposal_SHA256=digest_stub(Path('試行計画.json')),audit_SHA256=digest_stub(Path('実測前の検査.json')))
    for label in ('正式照合','正式登録'):docs[label+'の全出力.json']=dict(終了コード=0,stdout='{"proposal_complete":true}')
    def read_stub(path: Path) -> dict:
        """
        機能: 指定した合成metadataだけを返し、予定外readを停止する。
        引数: path(Path)。
        返り値: dict はメモリ上の素材。
        """
        assert path.parent==HERE and path.name in docs
        return docs[path.name]
    calls=[];prepared=[];made=[];captured={};fits=[]
    original_features=features.prepare;original_fit=learner.fit
    def raw_stub(info: dict) -> dict:
        """
        機能: ownerの純record生成だけで有限合成原列を作る。
        引数: info(dict) は合成session/symbol/bounds。
        返り値: dict は74回の架空入力。市場ファイルは存在確認もしない。
        """
        identity=(info['session'],info['symbol']);assert identity not in calls;calls.append(identity)
        start,end=info['bounds'];offset=sessions.index(info['session'])%7
        tick=.5 if info['symbol']=='TOPIX' else 10.
        records=[]
        for minute in range(151):
            phase=(minute+offset)%40
            wave=(phase if phase<20 else 40-phase)-10
            base=(4000. if tick==.5 else 60000.)+wave*(1.5 if tick==.5 else 30.)
            for second,move in ((0,-tick),(20,0.),(40,tick)):
                at=start+minute*60+second
                records.append(artificial_input.record(at,base+move,len(records),tick))
        arrays=artificial_input.arrays(records,start,end)
        if info['kind']=='jsonl':arrays['_read_metadata']=dict(path=info['path'],rows=len(records),SHA256='0'*64,bytes=0)
        return arrays
    def feature_spy(bars: dict,peer: dict) -> dict:
        """
        機能: targetを渡されない実features呼出を記録する。
        引数: bars/peer(dict)。
        返り値: dict は元関数の結果。値の置換はしない。
        """
        result=original_features(bars,peer)
        if len(bars['t_s']):made.append(result)
        return result
    def save_stub(path: Path,arrays: dict) -> dict:
        """
        機能: 本番保存直前の合成配列をメモリで捕捉する。
        引数: path(Path)、arrays(dict)。
        返り値: dict は架空出力目録。NPZは保存しない。
        """
        check(len(made)==len(prepared)+1)
        prepared.append(dict(session=path.stem,arrays=arrays,names=made[-1]['names'],groups=made[-1]['feature_groups']))
        return dict(path='SOURCE_ONLY/'+path.name,SHA256='0'*64,bytes=0,arrays={})
    def fit_spy(x: np.ndarray,y: np.ndarray,weight: np.ndarray,ridge: float) -> dict:
        """
        機能: fitの全実引数を21学習場だけの独立列挙へ照合して元fitを実行する。
        引数: x/y/weight(ndarray)、ridge(float)。
        返り値: dict は実learner.fitのモデル。検証場値を混ぜない。
        """
        position=len(fits);groups=list(plan.MODEL_GROUPS.values())[position//2];side=position%2
        check(len(prepared)==37)
        names=prepared[0]['names'];columns=[j for j,name in enumerate(names) if prepared[0]['groups'][name] in groups]
        xx=[];yy=[];ww=[]
        for record in prepared[:21]:
            a=record['arrays'];labels=a['target__labels'][:,side,1]
            indices=[j for j in range(len(labels)) if j%5==0 and a['ml_eligible'][j] and int(labels[j]) in (-1,1)]
            if indices:
                xx.append(a['X'][indices][:,columns]);yy.extend(float(labels[j]==1) for j in indices)
                ww.extend([1/len(indices)]*len(indices))
        np.testing.assert_array_equal(x,np.vstack(xx));np.testing.assert_array_equal(y,yy);np.testing.assert_array_equal(weight,ww)
        check(ridge==10. and len(xx)==21)
        result=original_fit(x,y,weight,ridge)
        # 標準化の元はfitへ来た学習行のみ。重みの比例正規化は平均・分散を変えない。
        mean=np.array([math.fsum(float(v)*float(w) for v,w in zip(x[:,j],weight))/math.fsum(weight) for j in range(x.shape[1])])
        variance=np.array([math.fsum(float(w)*(float(v)-mean[j])**2 for v,w in zip(x[:,j],weight))/math.fsum(weight) for j in range(x.shape[1])])
        active=np.flatnonzero(variance>1e-12)
        np.testing.assert_array_equal(result['active'],active)
        np.testing.assert_allclose(result['mean'],mean[active],rtol=1e-10,atol=1e-11)
        np.testing.assert_allclose(result['scale'],np.sqrt(variance[active]),rtol=1e-9,atol=1e-10)
        check(True);fits.append(dict(rows=len(x),columns=x.shape[1],side=side,train_only=True))
        return result
    def write_stub(path: Path,value: dict) -> None:
        """
        機能: 合成最終JSONをメモリだけへ保持する。
        引数: path(Path)、value(dict)。
        返り値: None。実measurementや公開へ書かない。
        """
        assert path.parent==subject.OUT and path.name not in captured
        json.dumps(value,ensure_ascii=False,allow_nan=False)
        captured[path.name]=value
    output=OWN/'synthetic_main'
    assert not output.exists()
    changes=[(subject,'OUT',output),(plan,'read',read_stub),(plan,'digest',digest_stub),(plan,'write',write_stub),
        (subject.raw_input,'read_old',raw_stub),(subject.raw_input,'read_jsonl',raw_stub),
        (features,'prepare',feature_spy),(subject,'save_npz',save_stub),(learner,'fit',fit_spy)]
    with replaced(changes):
        # 実guardも合成metadataで実行し、分割の重複・個数・順序を拒否する。
        check(subject.guard() is fixed)
        original=deepcopy(fixed['splits'])
        invalid=[]
        bad=deepcopy(original);bad['学習'][0]=bad['選択'][0];invalid.append(bad)
        bad=deepcopy(original);bad['学習'],bad['選択']=bad['選択'],bad['学習'];invalid.append(bad)
        bad=dict(reversed(list(original.items())));invalid.append(bad)
        for bad in invalid:
            fixed['splits']=bad
            try:subject.guard()
            except AssertionError:check(True)
            else:raise AssertionError('重複/境界/順序を受理')
        fixed['splits']=original
        with redirect_stdout(StringIO()):subject.main()
    check(len(calls)==74 and len(set(calls))==74 and len(fits)==8)
    check('False.json' not in captured and set(captured)=={'十ポイント予兆の結果.json'})
    result=captured['十ポイント予兆の結果.json']
    check(result['counts']==planned and result['全合格'] is True and result['金融'] is False)
    check(len(result['specifications'])==44 and len(result['accounts'])==37*44 and len(result['summaries'])==44)
    check(all(model['train_sessions']==splits['学習'] for model in result['models'].values()))
    chosen=subject.choose(result['summaries']);check(chosen==result['selection'])
    known=[s for s in result['summaries'] if s['id'] in chosen['正式候補']]
    check(len({v['family'] for v in known})==len(known)<=3)
    for row in result['summaries']:
        for period in row['periods'].values():
            check(period['活動場数']+period['無信号場数']==period['場数'])
            for risk in period['risks']:
                for group in ('全体','買い','売り','常時買い','常時売り'):
                    c=risk[group];n=sum(c[name] for name in subject.STATUS.values());resolved=c['順先']+c['逆先']
                    check(c['n']==n and c['resolved']==resolved)
                    check(c['全候補順先率']==(float(Fraction(c['順先'],n)) if n else None))
                    check(c['解決内順先率']==(float(Fraction(c['順先'],resolved)) if resolved else None))
    return dict(合成場=37,架空reader呼出数=74,原reader実行数=0,実fit呼出=fits,
        口座=1628,仕様=44,別枠を学習に使用=False,scope='guardとmainは合成metadata/合成原列。登録台帳・実固定入力は読まず、登録済みの独立監査ではない。')


def main() -> None:
    """
    機能: 完成十源を指紋化し、純境界と合成main接続の証跡を保存する。
    引数: なし。
    返り値: None。実NPZ/JSONL・市場結果・API・金融・登録は呼び出さない。
    """
    snapshot=plan.sources()
    arithmetic=arithmetic_cases();learning=learner_cases();connected=synthetic_main(snapshot)
    check(plan.sources()==snapshot)
    proof=dict(全合格=True,source_SHA256=snapshot,audit_source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        比較項目=CHECKS,率と選択=arithmetic,標準化=learning,接続=connected,
        実NPZ=0,原JSONL=0,旧金融=0,registry大本文=0,金融=0,API=0,
        留保='合成の会計件数は実測結果でない。採用済Last先着は完全テープの初到達・実利益ではない。全10場を未見と呼ばず、既知別枠6と追加4を区別。')
    path=OWN/'証跡/学習分割と純公開及び十ポイント採点の独立SOURCE_ONLY接続.json'
    path.parent.mkdir(parents=True,exist_ok=True);assert not path.exists()
    path.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,比較項目=CHECKS,SHA256=hashlib.sha256(path.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':
    try:main()
    except BaseException as error:
        path=OWN/'証跡/初回False.json';path.parent.mkdir(parents=True,exist_ok=True)
        assert not path.exists()
        path.write_text(json.dumps(dict(全合格=False,例外型=type(error).__name__,例外=str(error),比較項目=CHECKS,
            source_SHA256={name:plan.digest(HERE/name) for name in plan.SOURCES if (HERE/name).is_file()},
            金融=0,実本文=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise
