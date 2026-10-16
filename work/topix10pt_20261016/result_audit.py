"""保存済み予兆・モデル・採点から集計だけを独立再加算する。原価格の再測定は行わない。"""

import argparse
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path

import numpy as np


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OWN=HERE/'result_audit'
SOURCES=('plan.py','input.py','artificial_input.py','features.py','artificial_features.py',
    'targets.py','artificial_targets.py','learner.py','artificial_learner.py','run.py')
SELF=('result_audit.py','artificial_result_audit.py')
RISKS=(2.5,5.,10.)
CODES={1:'順先',-1:'逆先',0:'窓末未決',2:'EOF未決',-2:'基準不可'}
GROUPS={'L01_価格':['price'],'L02_多数MA':['price','ma'],
    'L03_MA活動板':['price','ma','volume','book'],
    'L04_MA活動板二市場':['price','ma','volume','book','peer']}
THRESHOLDS=(.45,.55,.65)
REQUIRED=('X','signals','eligible','ml_eligible','bars__valid','bars__anchor','bars__t_s',
    'bars__pub_raw_row','bars__pub_price_time_s','target__labels','target__terminal_raw_row',
    'target__mfe','target__mae','target__first_10_raw_row','target__first_10_time_s',
    'target__mae_before_first_10','target__common_lock_end')


def fingerprints(names: tuple=SOURCES) -> dict:
    """
    機能: 読取対象でないソースだけの現在指紋を得る。
    引数: names(tuple[str]) は所有域のソース名。
    返り値: dict[str,str] はルート相対pathとSHA256。
    """
    return {(HERE/name).relative_to(ROOT).as_posix():hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in names}


def write_new(path: Path,value: dict) -> None:
    """
    機能: 成功又はFalseを有限JSONとして新規保存する。
    引数: path(Path)、value(dict) は所有出力。
    返り値: None。旧証跡の上書きを禁止する。
    """
    assert path.resolve().is_relative_to(OWN) and not path.exists()
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


class Checker:
    """機能: 名前付きの比較数を保存する。引数: なし。返り値: Checkerインスタンス。"""

    def __init__(self):
        """
        機能: 検査数を初期化する。
        引数: なし。
        返り値: None。
        """
        self.count=0

    def require(self,condition: bool,name: str) -> None:
        """
        機能: 条件の成否を数え、不一致で停止する。
        引数: condition(bool)、name(str) は条件と説明。
        返り値: None。
        """
        self.count+=1
        if not bool(condition):raise AssertionError(name)

    def equal(self,actual,expected,name: str='比較') -> None:
        """
        機能: 保存値を独立期待へ再帰比較する。
        引数: actual/expected(any)、name(str) は値と位置。
        返り値: None。整数/None/文字は厳密、率の丸めだけ1e−13まで許す。
        """
        if isinstance(expected,dict):
            self.require(isinstance(actual,dict) and set(actual)==set(expected),name+'項目')
            for key,value in expected.items():self.equal(actual[key],value,name+'/'+str(key))
        elif isinstance(expected,list):
            self.require(isinstance(actual,list) and len(actual)==len(expected),name+'長さ')
            for i,value in enumerate(expected):self.equal(actual[i],value,name+'/'+str(i))
        elif isinstance(expected,float):
            self.require(isinstance(actual,(int,float)) and not isinstance(actual,bool) and math.isfinite(actual)
                and math.isclose(actual,expected,rel_tol=1e-12,abs_tol=1e-13),name)
        else:self.require(actual==expected and type(actual) is type(expected),name)


def tally(values) -> dict:
    """
    機能: ラベルを一つずつ数え、分子/全体/解決内を分ける。
    引数: values(iterable[int]) は既保存の先着ラベル。
    返り値: dict は五状態件数と率。未決を失敗又は成功へ置換しない。
    """
    counts={name:0 for name in CODES.values()};n=0
    for value in values:
        code=int(value);assert code in CODES;counts[CODES[code]]+=1;n+=1
    resolved=counts['順先']+counts['逆先']
    return dict(**counts,n=n,resolved=resolved,全候補順先率=counts['順先']/n if n else None,
        解決内順先率=counts['順先']/resolved if resolved else None,解決率=resolved/n if n else None)


def probabilities(model: dict,X: np.ndarray) -> np.ndarray:
    """
    機能: 固定モデルを別式の安定logisticで評価する。
    引数: model(dict)、X(ndarray[N,P]) は学習済み係数と当時特徴。
    返り値: ndarray[float,N]。学習・係数更新・追加場での再標準化を行わない。
    """
    active=np.asarray(model['active'],np.int64);mean=np.asarray(model['mean'],float);scale=np.asarray(model['scale'],float)
    assert X.ndim==2 and X.shape[1]==model['input_columns'] and np.isfinite(X).all()
    assert active.shape==mean.shape==scale.shape and np.all(scale>0)
    assert len(active)==len(set(active.tolist())) and np.all((active>=0)&(active<X.shape[1]))
    coef=np.asarray(model['coefficient'],float);assert coef.shape==(len(active)+1,) and np.isfinite(coef).all()
    standardized=np.minimum(8.,np.maximum(-8.,(X[:,active]-mean)/scale))
    score=coef[0]+standardized@coef[1:];result=np.empty(len(X));positive=score>=0
    result[positive]=1./(1.+np.exp(-score[positive]));exp=np.exp(score[~positive]);result[~positive]=exp/(1.+exp)
    return result


def publications(long: np.ndarray,short: np.ndarray,eligible: np.ndarray,threshold: float) -> np.ndarray:
    """
    機能: 閾値・0.1差・前状態を逐次判定し、状態変化だけを公開する。
    引数: long/short(ndarray)、eligible(ndarray[bool])、threshold(float)。
    返り値: ndarray[int8]。不適格で中立へ戻し、同方向持続中に連射しない。
    """
    assert long.shape==short.shape==eligible.shape and eligible.dtype==bool
    out=np.zeros(len(long),np.int8);previous=0
    for row,(buy,sell,ok) in enumerate(zip(long,short,eligible)):
        state=0
        if ok:
            if buy>=threshold and buy-sell>=.1:state=1
            elif sell>=threshold and sell-buy>=.1:state=-1
        if state!=previous:out[row]=state
        previous=state
    return out


def chosen_rows(signal: np.ndarray,eligible: np.ndarray,published: np.ndarray,lock: np.ndarray) -> list[int]:
    """
    機能: 公開順に共通±10pt終端まで重複を止める。
    引数: signal/eligible/published/lock(ndarray) は当時信号・資格・原行・保存終端。
    返り値: list[int] は採用足。終端と同じ行の再候補は採らない。
    """
    selected=[];locked=-1
    for row in range(len(signal)):
        if bool(eligible[row]) and int(signal[row]) and int(published[row])>locked:
            selected.append(row);locked=int(lock[row]);assert locked>=int(published[row])
    return selected


def finite(value: float):
    """
    機能: 保存極値の未知をNoneとして扱う。
    引数: value(float) は保存済み観測値。
    返り値: float|None。未知を0へ補完しない。
    """
    return float(value) if np.isfinite(value) else None


def account(session: str,data: dict,signal: np.ndarray,spec: dict,eligible: np.ndarray|None=None) -> dict:
    """
    機能: 保存信号と保存ラベルから一場一規則を独立再集計する。
    引数: session(str)、data(dict)、signal(ndarray)、spec(dict)、eligible(ndarray|None)。
    返り値: dict は全三幅・方向・同時点固定対照と実際に選んだ予兆記録。
    """
    mask=data['eligible'] if eligible is None else eligible
    selected=chosen_rows(signal,mask,data['bars__pub_raw_row'],data['target__common_lock_end'])
    risks=[]
    for risk_index,risk in enumerate(RISKS):
        whole=[];buy=[];sell=[];always_buy=[];always_sell=[]
        for row in selected:
            si=0 if signal[row]>0 else 1;label=int(data['target__labels'][row,si,risk_index])
            whole.append(label);(buy if si==0 else sell).append(label)
            always_buy.append(int(data['target__labels'][row,0,risk_index]));always_sell.append(int(data['target__labels'][row,1,risk_index]))
        risks.append(dict(逆行幅=risk,**tally(whole),買い=tally(buy),売り=tally(sell),常時買い=tally(always_buy),常時売り=tally(always_sell)))
    records=[]
    for row in selected:
        si=0 if signal[row]>0 else 1
        records.append(dict(bar_row=row,公開原row=int(data['bars__pub_raw_row'][row]),公開秒=float(data['bars__pub_price_time_s'][row]),
            確定分末=float(data['bars__t_s'][row]),方向=int(signal[row]),基準=float(data['bars__anchor'][row]),
            labels=[int(v) for v in data['target__labels'][row,si]],終端原row=[int(v) for v in data['target__terminal_raw_row'][row,si]],
            十pt到達原row=int(data['target__first_10_raw_row'][row,si]),十pt到達秒=finite(data['target__first_10_time_s'][row,si]),
            MFE=finite(data['target__mfe'][row,si]),MAE=finite(data['target__mae'][row,si]),十pt到達前MAE=finite(data['target__mae_before_first_10'][row,si])))
    return dict(session=session,id=spec['id'],family=spec['family'],name=spec['name'],
        公開候補数=sum(bool(ok) and int(value)!=0 for ok,value in zip(mask,signal)),採用予兆数=len(selected),
        買い数=sum(int(signal[row])>0 for row in selected),売り数=sum(int(signal[row])<0 for row in selected),risks=risks,records=records)


def merge(accounts: list[dict]) -> dict:
    """
    機能: 場の率を平均せず、五状態の整数分母から期間率を再作成する。
    引数: accounts(list[dict]) は同候補の対象場。
    返り値: dict は全幅/買売/固定方向、活動数、10対5の固定対照改善。
    """
    risks=[]
    for ri,risk in enumerate(RISKS):
        groups={}
        for group in ('全体','買い','売り','常時買い','常時売り'):
            counts={name:0 for name in CODES.values()}
            for row in accounts:
                cell=row['risks'][ri] if group=='全体' else row['risks'][ri][group]
                for name in counts:counts[name]+=cell[name]
            n=sum(counts.values());resolved=counts['順先']+counts['逆先']
            groups[group]=dict(**counts,n=n,resolved=resolved,全候補順先率=counts['順先']/n if n else None,
                解決内順先率=counts['順先']/resolved if resolved else None,解決率=resolved/n if n else None)
        risks.append(dict(逆行幅=risk,**groups))
    primary=risks[1];n=sum(v['採用予兆数'] for v in accounts)
    improvement=None if not n else primary['全体']['全候補順先率']-max(primary['常時買い']['全候補順先率'],primary['常時売り']['全候補順先率'])
    return dict(場数=len(accounts),活動場数=sum(v['採用予兆数']>0 for v in accounts),無信号場数=sum(v['採用予兆数']==0 for v in accounts),
        予兆数=n,買い数=sum(v['買い数'] for v in accounts),売り数=sum(v['売り数'] for v in accounts),主評価=primary,risks=risks,対固定方向改善=improvement)


def ranking(summaries: list[dict]) -> tuple[dict,list[dict]]:
    """
    機能: 選択6場の固定優先順だけで異family三候補を選ぶ。
    引数: summaries(list[dict]) は全期間を持つ44規則。
    返り値: tuple[dict,list] は正式選択/比較参照と、選択期だけの全順位根拠。
    """
    qualified=[];reference=[];trace=[]
    for summary in summaries:
        cell=summary['periods']['選択'];n=cell['予兆数']
        if not n:continue
        score=(cell['対固定方向改善'],cell['主評価']['全体']['全候補順先率'],cell['活動場数'],n)
        okay=n>=12 and cell['活動場数']>=4 and cell['買い数']>=3 and cell['売り数']>=3
        item=dict(id=summary['id'],family=summary['family'],score=list(score),資格=okay,
            買い数=cell['買い数'],売り数=cell['売り数'])
        reference.append((score,summary['id'],summary['family']));trace.append(item)
        if okay:qualified.append((score,summary['id'],summary['family']))

    def take(rows: list) -> list[str]:
        """
        機能: 同点ID逆順を含む固定順でfamily重複を避ける。
        引数: rows(list[tuple]) はスコア・ID・family。
        返り値: list[str] は最大三候補。
        """
        used=set();out=[]
        for _,identifier,family in sorted(rows,reverse=True):
            if family in used:continue
            used.add(family);out.append(identifier)
            if len(out)==3:break
        return out

    selected=dict(選択期='選択',正式候補=take(qualified),比較参照=take(reference),合格条件数=len(qualified),
        留保='件数資格合格は予測優位の合格ではない。改善が負又は別枠で失敗なら未発見とする。')
    trace.sort(key=lambda v:(v['score'],v['id']),reverse=True)
    return selected,trace


def period_sessions(splits: dict,sessions: list[str]) -> dict:
    """
    機能: 固定四分割と別枠10の昼夜を、場名だけから区別する。
    引数: splits(dict)、sessions(list[str]) は時系列区分。
    返り値: dict は根と同順の八期間。選択期へ別枠を混ぜない。
    """
    periods=dict(splits);test=splits['時系列別枠']+splits['追加別枠'];periods['別枠10']=test
    periods['別枠デイ']=[v for v in test if v.endswith('_Day')]
    periods['別枠ナイト']=[v for v in test if v.endswith('_Night')]
    periods['全37']=sessions
    return periods


def validate_dataset(data: dict,meta: dict,checker: Checker) -> None:
    """
    機能: 保存採点と資格のshape/符号/当時公開・共通終端契約を確認する。
    引数: data(dict)、meta(dict)、checker(Checker) は保存配列・場メタ・比較器。
    返り値: None。first-hitを原価格から再計測する処理は持たない。
    """
    n=len(data['bars__t_s']);valid=data['bars__valid'];pub=data['bars__pub_raw_row'];anchor=data['bars__anchor']
    checker.require(data['X'].ndim==2 and len(data['X'])==n and np.isfinite(data['X']).all(),'有限X')
    checker.require(data['signals'].shape==(n,32) and data['signals'].dtype==np.int8 and np.isin(data['signals'],(-1,0,1)).all(),'信号32')
    checker.require(valid.shape==(n,) and valid.dtype==bool and np.all(np.diff(data['bars__t_s'])==60),'足資格')
    for name in ('eligible','ml_eligible'):checker.require(data[name].shape==(n,) and data[name].dtype==bool,name)
    checker.require(data['target__labels'].shape==(n,2,3) and np.isin(data['target__labels'],tuple(CODES)).all(),'三幅二方向ラベル')
    checker.require(data['target__terminal_raw_row'].shape==(n,2,3),'終端shape')
    for name in ('target__mfe','target__mae','target__first_10_raw_row','target__first_10_time_s','target__mae_before_first_10'):
        checker.require(data[name].shape==(n,2),name)
    checker.require(np.all(pub>=-1) and np.all(np.diff(pub[pub>=0])>=0),'公開原順')
    delay=data['bars__pub_price_time_s']-data['bars__t_s'];end=meta['end']
    expected=valid&np.isfinite(anchor)&(pub>=0)&np.isfinite(delay)&(delay>=0)&(delay<=60)&(data['bars__pub_price_time_s']<end-300)
    checker.require(np.array_equal(data['eligible'],expected),'共通資格の独立再計算')
    run=0;ml=[]
    for ok,allowed in zip(valid,expected):run=run+1 if ok else 0;ml.append(bool(allowed and run>=30))
    checker.require(np.array_equal(data['ml_eligible'],np.array(ml,bool)),'30連続ML資格')
    known=np.isfinite(anchor)&(pub>=0)
    checker.require(data['target__common_lock_end'].shape==(n,) and np.all(data['target__common_lock_end'][known]>=pub[known]),'共通lock下限')
    checker.require(np.all(data['target__labels'][~known]==-2),'基準なしを未決と混同しない')


def validate_training(models: dict,datasets: dict,result: dict,checker: Checker) -> None:
    """
    機能: モデルの行数・場均等平均・標準化を学習21場の保存Xだけで照合する。
    引数: models/datasets/result(dict)、checker(Checker)。
    返り値: None。係数の再fit・別枠のラベル利用を行わない。
    """
    names=result['feature_names'];groups=result['feature_groups'];train=result['splits']['学習']
    checker.equal(list(models),list(GROUPS),'四モデル群')
    for identifier,allowed in GROUPS.items():
        model=models[identifier];columns=[i for i,name in enumerate(names) if groups[name] in allowed]
        checker.equal(model['columns'],columns,'モデル列');checker.equal(model['names'],[names[i] for i in columns],'モデル特徴名')
        checker.equal(model['train_sessions'],train,'学習期21だけ')
        checker.require(len(model['sides'])==2,'方向別モデル')
        for si,side in enumerate(model['sides']):
            xx=[];rates=[];raw_weights=[]
            for session in train:
                data=datasets[session];lab=data['target__labels'][:,si,1]
                rows=[row for row in range(len(lab)) if data['ml_eligible'][row] and row%5==0 and int(lab[row]) in (-1,1)]
                if not rows:continue
                xx.append(data['X'][rows][:,columns]);rates.append(sum(int(lab[row])==1 for row in rows)/len(rows))
                raw_weights.extend([1/len(rows)]*len(rows))
            x=np.concatenate(xx);w=np.asarray(raw_weights);mean=np.sum(x*w[:,None],axis=0)/w.sum()
            variance=np.sum((x-mean)**2*w[:,None],axis=0)/w.sum();active=np.flatnonzero(variance>1e-12)
            checker.equal(side['active'],active.tolist(),'学習21場だけの分散選択')
            checker.require(np.allclose(side['mean'],mean[active],rtol=1e-10,atol=1e-10),'場均等学習平均')
            checker.require(np.allclose(side['scale'],np.sqrt(variance[active]),rtol=1e-10,atol=1e-10),'場均等学習尺度')
            checker.equal(side['training_rows'],len(x),'学習行数');checker.equal(side['training_rate'],sum(rates)/len(rates),'場均等学習目的率')
            checker.equal(side['input_columns'],len(columns),'入力列数');checker.equal(side['ridge'],10.,'固定L2');checker.equal(side['clipping'],8.,'標準化clip')
            checker.require(0<=side['iterations']<=50,'Newton反復上限')


def audit(result: dict,datasets: dict,checker: Checker) -> dict:
    """
    機能: 37保存preparedから44規則の全場/全期間/選択を独立再作成する。
    引数: result(dict)、datasets(dict[str,dict])、checker(Checker)。
    返り値: dict は小さな全規則集計と上位三の別枠/買売/昼夜。採点値自体の正しさは別監査。
    """
    sessions=result['sessions'];splits=result['splits'];checker.equal(list(splits),['学習','選択','時系列別枠','追加別枠'],'四分割順')
    checker.equal([len(v) for v in splits.values()],[21,6,6,4],'分割数');checker.equal(sum(splits.values(),[]),sessions,'分割は時間順で重複なし')
    checker.require(len(sessions)==len(set(sessions))==37 and sorted(sessions)==sessions,'時系列37場')
    checker.equal(set(datasets),set(sessions),'保存37場')
    periods=period_sessions(splits,sessions)
    checker.equal(result['periods'],periods,'全八期間')
    specs=result['specifications'];checker.require(len(specs)==44 and len({s['id'] for s in specs})==44,'44比較')
    expected_ids=[prefix+str(i).zfill(2) for prefix in ('T','S','C','B','P','R','M','Q') for i in range(1,5)]
    checker.equal([v['id'] for v in specs[:32]],expected_ids,'事前32ID')
    for position,(identifier,_) in enumerate(GROUPS.items()):
        for offset,threshold in enumerate(THRESHOLDS):
            spec=specs[32+position*3+offset]
            checker.equal(spec['id'],identifier+'_P'+str(int(round(threshold*100))),'ML固定ID')
            checker.equal(spec['model_id'],identifier,'ML群');checker.equal(spec['threshold'],threshold,'ML閾値')
            checker.equal(spec['family'],'学習','MLfamily')
    validate_training(result['models'],datasets,result,checker)
    accounts=[];original={(v['session'],v['id']):v for v in result['accounts']}
    checker.require(len(original)==len(result['accounts'])==37*44,'場×規則重複なし')
    all_reference=[]
    for session in sessions:
        data=datasets[session];learned={}
        checker.require(data['X'].shape[1]==len(result['feature_names']) and set(result['feature_names'])==set(result['feature_groups']),'X列と保存名')
        for model_id,model in result['models'].items():
            learned[model_id]=[probabilities(side,data['X'][:,model['columns']]) for side in model['sides']]
        for index,spec in enumerate(specs):
            signal=data['signals'][:,index] if index<32 else publications(*learned[spec['model_id']],data['ml_eligible'],spec['threshold'])
            own=account(session,data,signal,spec);checker.equal(original[session,spec['id']],own,'場集計/'+session+'/'+spec['id']);accounts.append(own)
            # 参考全候補は非重複と分け、保存ラベルからだけ再加算する。
            selected=np.flatnonzero(data['eligible']&(signal!=0));si=(signal[selected]<0).astype(int)
            all_reference.append(dict(session=session,id=spec['id'],risks=[tally(data['target__labels'][selected,si,ri]) for ri in range(3)]))
    summaries=[];original_summary={v['id']:v for v in result['summaries']}
    checker.require(len(original_summary)==len(result['summaries'])==44,'要約44')
    for spec in specs:
        rows=[v for v in accounts if v['id']==spec['id']]
        summary=dict(**spec,periods={name:merge([v for v in rows if v['session'] in selected]) for name,selected in periods.items()})
        checker.equal(original_summary[spec['id']],summary,'期間集計/'+spec['id']);summaries.append(summary)
    selected,trace=ranking(summaries);checker.equal(result['selection'],selected,'選択6場の順位と異family3')
    changed=[]
    for summary in summaries:
        item=dict(summary);item['periods']=dict(item['periods']);item['periods']['別枠10']={'故意の未来改変':True}
        item['periods']['時系列別枠']={};item['periods']['追加別枠']={};changed.append(item)
    checker.equal(ranking(changed)[0],selected,'別枠10成績の改変で選択不変')
    chosen=selected['正式候補'];reference=selected['比較参照']
    selected_details={}
    for identity in dict.fromkeys(chosen+reference):
        rows=[v for v in accounts if v['id']==identity];test=[v for v in rows if v['session'] in periods['別枠10']]
        selected_details[identity]=dict(periods=next(v['periods'] for v in summaries if v['id']==identity),
            別枠10_昼=merge([v for v in test if v['session'].endswith('_Day')]),
            別枠10_夜=merge([v for v in test if v['session'].endswith('_Night')]))
    compact=[]
    for summary in summaries:
        selected_rows=[v for v in all_reference if v['id']==summary['id']]
        reference_periods={}
        for name,pool in periods.items():
            cells=[]
            for ri in range(3):
                counts={key:sum(v['risks'][ri][key] for v in selected_rows if v['session'] in pool) for key in CODES.values()}
                values=[code for code,key in CODES.items() for _ in range(counts[key])]
                cells.append(tally(values))
            reference_periods[name]=cells
        compact.append(dict(id=summary['id'],family=summary['family'],非重複=summary['periods'],参考全候補=reference_periods))
    return dict(全合格=True,検査数=checker.count,規則32=32,学習条件12=12,場数=37,場規則数=37*44,
        selection=selected,選択期だけの全順位=trace,選択候補別枠と方向昼夜=selected_details,全44集計=compact,
        範囲='保存signals/固定model/X/targetからの再集計。原raw・first-hit価格再測定・特徴再生成・モデル再fit・金融0。',
        分母='非重複主評価と全候補参考を分離。窓末/EOF/基準不可、買売、固定方向を分ける。',
        極値='MFE/MAEと十pt到達前MAEは保存recordsへ照合するだけ。十pt到達した全件を先着勝ちへ置換しない。')


def prepare_plan() -> None:
    """
    機能: 市場本文読取前に目的・予算・有効源・純人工を固定する。
    引数: なし。
    返り値: None。存在している結果も開かない。
    """
    pure_path=OWN/'保存採点再加算と固定モデル及び選択期の純人工.json'
    pure_bytes=pure_path.read_bytes();pure=json.loads(pure_bytes)
    assert pure['全合格'] and pure['audit_source_SHA256']==fingerprints(SELF) and pure['source_SHA256']==fingerprints()
    write_new(OWN/'実測完了後の独立集計の固定計画.json',dict(全合格=True,source_SHA256=fingerprints(),audit_source_SHA256=fingerprints(SELF),
        純人工_SHA256=hashlib.sha256(pure_bytes).hexdigest(),result_path=(HERE/'measurement/十ポイント予兆の結果.json').relative_to(ROOT).as_posix(),
        予定読取=dict(完成結果JSON=1,同bytes保存prepared=37,原raw=0,原event=0,原金融=0,API=0),
        解除='root完了連絡とexpected-result-shaが揃った時だけ --run を一度実行。False後の自動再実行なし。',
        検査='32保存信号・ML12別predict・状態edge・共通lock・三幅分母・37場全期間・固定買売・選択6場異family3。',
        非対象='first-hitを元raw価格から再計測しない。MLを再fitしない。別枠10を選択へ使わない。'))
    print('独立集計計画を保存。市場結果/保存prepared読取0。')


def execute(expected_sha: str,authorized: bool) -> None:
    """
    機能: 解除済み完成結果1読と保存prepared37各1読で独立集計を実行する。
    引数: expected_sha(str)、authorized(bool) は根の完成SHAと解除。
    返り値: None。読取開始を先に数え、失敗も保存し再試行しない。
    """
    assert authorized and len(expected_sha)==64 and not (OWN/'実行開始.json').exists()
    frozen=json.loads((OWN/'実測完了後の独立集計の固定計画.json').read_bytes())
    assert frozen['source_SHA256']==fingerprints() and frozen['audit_source_SHA256']==fingerprints(SELF)
    initial=fingerprints();tally_read=dict(完成結果JSON=0,同bytes保存prepared=0,原raw=0,原event=0,原金融=0,API=0)
    write_new(OWN/'実行開始.json',dict(予定=frozen['予定読取'],指定結果_SHA256=expected_sha,自動再実行=False))
    try:
        result_path=ROOT/frozen['result_path'];tally_read['完成結果JSON']+=1;body=result_path.read_bytes()
        assert hashlib.sha256(body).hexdigest()==expected_sha
        (OWN/'根完成結果の同bytes参照.json').write_bytes(body);result=json.loads(body);del body
        assert result['全合格'] and result['source_SHA256']==initial
        checker=Checker();checker.equal(result['counts'],dict(旧原NPZ=66,新JSONL=8,新金融=0,API=0),'一次実測の読取計数')
        # 入力boundsは市場本文でなく、source固定の目録列を元結果が保持しないためセッション日付から同定する。
        from datetime import datetime,timedelta,timezone
        datasets={};input_fingerprints=[]
        for info in result['outputs']:
            session=info['session'];path=(ROOT/info['path']).resolve();assert path.is_relative_to(HERE/'measurement/prepared') and session not in datasets
            tally_read['同bytes保存prepared']+=1;memory=path.read_bytes();actual_sha=hashlib.sha256(memory).hexdigest()
            assert actual_sha==info['SHA256'] and len(memory)==info['bytes']
            with np.load(BytesIO(memory),allow_pickle=False) as store:
                assert set(store.files)==set(info['arrays']) and all(name in store for name in REQUIRED)
                data={name:store[name] for name in REQUIRED}
            del memory
            for name,value in data.items():
                assert str(value.dtype)==info['arrays'][name]['dtype'] and list(value.shape)==info['arrays'][name]['shape']
                value.setflags(write=False)
            day=datetime.fromisoformat(session[:10]).replace(tzinfo=timezone(timedelta(hours=9)))
            end=day+timedelta(hours=15,minutes=40) if session.endswith('_Day') else day+timedelta(days=1,hours=5,minutes=55)
            validate_dataset(data,dict(end=end.timestamp()),checker);datasets[session]=data
            input_fingerprints.append(dict(session=session,path=info['path'],SHA256=actual_sha,bytes=info['bytes'],decoded_columns=list(REQUIRED)))
        checker.equal(tally_read,frozen['予定読取'],'事前読取予算')
        checked=audit(result,datasets,checker);checked.update(読取計数=tally_read,指定結果_SHA256=expected_sha,
            source_SHA256=initial,audit_source_SHA256=fingerprints(SELF),保存prepared指紋=input_fingerprints,
            終端源一致=initial==fingerprints())
        assert checked['終端源一致'];write_new(OWN/'四十四条件全場と選択及び固定モデルの独立再集計.json',checked)
        print(json.dumps(dict(全合格=True,検査数=checker.count,selection=checked['selection'],読取計数=tally_read),ensure_ascii=False))
    except BaseException as exc:
        write_new(OWN/'False.json',dict(全合格=False,例外型=type(exc).__name__,例外=str(exc),読取計数=tally_read,
            source_SHA256=initial,source終端=fingerprints(),指定結果_SHA256=expected_sha,自動再実行=False));raise


def main() -> None:
    """
    機能: 事前固定と根SHA解除後の単回監査を分ける。
    引数: CLI --prepare又は--run、--root-measurement-complete、--expected-result-sha。
    返り値: None。市場読取は--runだけ。
    """
    parser=argparse.ArgumentParser();mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare',action='store_true');mode.add_argument('--run',action='store_true')
    parser.add_argument('--root-measurement-complete',action='store_true');parser.add_argument('--expected-result-sha',default='')
    args=parser.parse_args();prepare_plan() if args.prepare else execute(args.expected_result_sha,args.root_measurement_complete)


if __name__=='__main__':main()
