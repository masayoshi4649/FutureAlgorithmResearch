"""固定した74入力から因果特徴と十ポイントの先着を一回だけ測定する。"""

from io import BytesIO
import json
from pathlib import Path

import numpy as np

import features
import input as raw_input
import learner
import plan
import targets


OUT=plan.HERE/'measurement'
RISKS=(2.5,5.,10.)
STATUS={1:'順先',-1:'逆先',0:'窓末未決',2:'EOF未決',-2:'基準不可'}

# ----------------------------------------


def guard() -> dict:
    """
    機能: 正式固定・十源・入力小目録・照合成功を市場読取前に照合する。
    引数: なし。
    返り値: dict は入力目録。旧結果や失敗があれば自動再試行しない。
    """
    assert not OUT.exists()
    frozen=plan.read(plan.HERE/'正式固定.json')
    proposal=plan.read(plan.HERE/'試行計画.json')
    fixed=plan.read(plan.HERE/'入力目録と時系列分割.json')
    assert frozen['全合格'] and frozen['source_SHA256']==plan.sources()==proposal['spec']['implementation']
    assert frozen['input_SHA256']==plan.digest(plan.HERE/'入力目録と時系列分割.json')
    assert frozen['proposal_SHA256']==plan.digest(plan.HERE/'試行計画.json')
    assert frozen['audit_SHA256']==plan.digest(plan.HERE/'実測前の検査.json')
    audit=plan.read(plan.HERE/'実測前の検査.json')
    assert audit['全合格'] and audit['source_SHA256']==plan.sources()
    for row in audit['evidence']:assert plan.digest(plan.ROOT/row['path'])==row['SHA256']
    assert frozen['thresholds']==plan.THRESHOLDS and frozen['model_groups']==plan.MODEL_GROUPS and frozen['ridge']==plan.RIDGE
    assert proposal['spec']['entry']['規則']==features.specifications()
    assert proposal['spec']['data']['sessions']==fixed['sessions'] and proposal['spec']['data']['splits']==fixed['splits']
    assert proposal['spec']['data']['inputs']==fixed['inputs']
    assert list(fixed['splits'])==['学習','選択','時系列別枠','追加別枠']
    assert [len(v) for v in fixed['splits'].values()]==[21,6,6,4]
    assert sum(fixed['splits'].values(),[])==fixed['sessions']
    assert len(set(sum(fixed['splits'].values(),[])))==37
    for label in ('正式照合','正式登録'):
        value=plan.read(plan.HERE/(label+'の全出力.json'))
        assert value['終了コード']==0
        if label=='正式照合':assert json.loads(value['stdout'])['proposal_complete'] is True
    assert len(fixed['inputs'])==74 and len(set(fixed['sessions']))==37
    assert set((v['session'],v['symbol']) for v in fixed['inputs'])=={(s,y) for s in fixed['sessions'] for y in ('TOPIX','NK225')}
    return fixed


def peer_features(own: dict,peer: dict) -> dict:
    """
    機能: 一分以上前かつ自己公開前に確定済みのNK履歴だけを合わせる。
    引数: own/peer(dict) は因果確定bars。
    返り値: dict は同型NのNK終値・過去リターン・効率・known。未知を現行値へ埋めない。
    """
    matched=raw_input.strict_peer_join(own,peer)
    n=len(matched);m=len(peer['close'])
    r3=np.full(m,np.nan);r10=np.full(m,np.nan);er10=np.full(m,np.nan)
    close=peer['close'];valid=peer['valid']
    for row in range(m):
        if row>=3 and valid[row-3:row+1].all():r3[row]=close[row]/close[row-3]-1
        if row>=10 and valid[row-10:row+1].all():
            r10[row]=close[row]/close[row-10]-1
            total=np.abs(np.diff(close[row-10:row+1])).sum()
            if total>0:er10[row]=abs(close[row]-close[row-10])/total
    result={name:np.full(n,np.nan) for name in ('matchedNKclose','return3','return10','efficiency10','matchedNKt_s')}
    known=matched>=0;indexes=matched[known]
    result['matchedNKclose'][known]=close[indexes]
    result['return3'][known]=r3[indexes];result['return10'][known]=r10[indexes]
    result['efficiency10'][known]=er10[indexes];result['matchedNKt_s'][known]=peer['t_s'][indexes]
    result['matchedNKknown']=known&np.isfinite(result['return3'])&np.isfinite(result['return10'])&np.isfinite(result['efficiency10'])
    assert np.all(result['matchedNKt_s'][known]<=own['t_s'][known]-60)
    assert np.all(peer['pub_price_time_s'][indexes]<=own['pub_price_time_s'][known])
    return result


def entry_masks(bars: dict,end: float) -> tuple[np.ndarray,np.ndarray]:
    """
    機能: 現在の予測起点と遅れ・窓末、機械学習の連続準備本数を判定する。
    引数: bars(dict)、end(float) は確定足と観測窓末。
    返り値: tuple[bool[N],bool[N]] は共通入口と30連続本の学習入口。
    """
    valid=bars['valid'];run=np.zeros(len(valid),np.int64)
    for row in range(len(valid)):run[row]=(run[row-1]+1 if row else 1) if valid[row] else 0
    known=valid&np.isfinite(bars['anchor'])&(bars['pub_raw_row']>=0)
    delay=bars['pub_price_time_s']-bars['t_s']
    eligible=known&np.isfinite(delay)&(delay>=0)&(delay<=60)&(bars['pub_price_time_s']<end-300)
    return eligible,eligible&(run>=30)


def target_bars(bars: dict) -> dict:
    """
    機能: 公開済空足の公開履歴を残しつつ、予測起点なしをtargetsへ正規化する。
    引数: bars(dict) は入力ownerの確定足。
    返り値: dict はtargets専用三列。元配列を書き換えない。
    """
    return dict(anchor=bars['anchor'],t_s=bars['t_s'],
        pub_raw_row=np.where(np.isfinite(bars['anchor']),bars['pub_raw_row'],-1).astype(np.int64))


def save_npz(path: Path,arrays: dict) -> dict:
    """
    機能: 非pickle配列を新規保存し、同じbytesの指紋を得る。
    引数: path(Path)、arrays(dict[str,ndarray])。
    返り値: dict は保存path・指紋・型とshape。NaNは欠測として保持する。
    """
    assert not path.exists() and path.resolve().is_relative_to(OUT)
    assert all(isinstance(v,np.ndarray) and v.dtype!=object for v in arrays.values())
    memory=BytesIO();np.savez_compressed(memory,**arrays);data=memory.getvalue()
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    import hashlib
    return dict(path=path.relative_to(plan.ROOT).as_posix(),SHA256=hashlib.sha256(data).hexdigest(),bytes=len(data),
        arrays={name:dict(dtype=str(v.dtype),shape=list(v.shape)) for name,v in arrays.items()})

# ----------------------------------------


def counts(labels: np.ndarray) -> dict:
    """
    機能: 五状態の分母を分け、未決と無信号を成功へ含めない。
    引数: labels(ndarray[int8]) は一方向・一逆行幅のラベル。
    返り値: dict は件数と全候補/解決内の率。
    """
    assert np.isin(labels,tuple(STATUS)).all()
    c={name:int(np.count_nonzero(labels==code)) for code,name in STATUS.items()}
    n=len(labels);resolved=c['順先']+c['逆先']
    return dict(**c,n=n,resolved=resolved,全候補順先率=c['順先']/n if n else None,
        解決内順先率=c['順先']/resolved if resolved else None,解決率=resolved/n if n else None)


def selected_rows(signal: np.ndarray,bars: dict,labels: dict,eligible: np.ndarray) -> np.ndarray:
    """
    機能: 同じ候補の公開後±10ptの共通終端まで連続予兆の重複を除く。
    引数: signal(int8[N])、bars/labels(dict)、eligible(bool[N])。
    返り値: ndarray[int64] は予兆足index。勝敗を見て公開行を選び直さない。
    """
    assert signal.shape==eligible.shape and np.isin(signal,(-1,0,1)).all()
    result=[];locked=-1
    for row in np.flatnonzero(eligible&(signal!=0)):
        if bars['pub_raw_row'][row]>locked:
            result.append(int(row));locked=int(labels['common_lock_end'][row])
    return np.array(result,np.int64)


def account(dataset: dict,signal: np.ndarray,spec: dict) -> dict:
    """
    機能: 一場・一候補の先着、同時点固定方向対照と具体予兆を集計する。
    引数: dataset(dict)、signal(int8[N])、spec(dict)。
    返り値: dict は三逆行幅と買売別、選択した全予兆記録。収支は作らない。
    """
    bars=dataset['bars'];target=dataset['target']
    chosen=selected_rows(signal,bars,target,dataset['eligible'])
    side=(signal[chosen]<0).astype(int)
    risks=[]
    for ri,risk in enumerate(RISKS):
        scores=target['labels'][chosen,side,ri]
        risks.append(dict(逆行幅=risk,**counts(scores),
            買い=counts(scores[side==0]),売り=counts(scores[side==1]),
            常時買い=counts(target['labels'][chosen,0,ri]),常時売り=counts(target['labels'][chosen,1,ri])))
    records=[]
    for row,si in zip(chosen,side):
        finite=lambda value:float(value) if np.isfinite(value) else None
        records.append(dict(bar_row=int(row),公開原row=int(bars['pub_raw_row'][row]),公開秒=float(bars['pub_price_time_s'][row]),
            確定分末=float(bars['t_s'][row]),方向=int(signal[row]),基準=float(bars['anchor'][row]),
            labels=target['labels'][row,si].tolist(),終端原row=target['terminal_raw_row'][row,si].tolist(),
            十pt到達原row=int(target['first_10_raw_row'][row,si]),十pt到達秒=finite(target['first_10_time_s'][row,si]),
            MFE=finite(target['mfe'][row,si]),MAE=finite(target['mae'][row,si]),十pt到達前MAE=finite(target['mae_before_first_10'][row,si])))
    return dict(session=dataset['session'],id=spec['id'],family=spec['family'],name=spec['name'],
        公開候補数=int(np.count_nonzero(dataset['eligible']&(signal!=0))),採用予兆数=len(chosen),
        買い数=int(np.count_nonzero(side==0)),売り数=int(np.count_nonzero(side==1)),risks=risks,records=records)


def merge(rows: list[dict]) -> dict:
    """
    機能: 指定期間の分子分母をそのまま加算し、場の率の平均で代用しない。
    引数: rows(list[dict]) は同一候補の各場。
    返り値: dict は三幅と活動場・無信号場・対照差。
    """
    out=[]
    for i,risk in enumerate(RISKS):
        merged={}
        for group in ('全体','買い','売り','常時買い','常時売り'):
            selected=[row['risks'][i] if group=='全体' else row['risks'][i][group] for row in rows]
            c={name:sum(cell[name] for cell in selected) for name in STATUS.values()}
            n=sum(c.values());resolved=c['順先']+c['逆先']
            merged[group]=dict(**c,n=n,resolved=resolved,全候補順先率=c['順先']/n if n else None,
                解決内順先率=c['順先']/resolved if resolved else None,解決率=resolved/n if n else None)
        out.append(dict(逆行幅=risk,**merged))
    primary=out[1]
    rate=primary['全体']['全候補順先率'];long=primary['常時買い']['全候補順先率'];short=primary['常時売り']['全候補順先率']
    return dict(場数=len(rows),活動場数=sum(row['採用予兆数']>0 for row in rows),
        無信号場数=sum(row['採用予兆数']==0 for row in rows),予兆数=sum(row['採用予兆数'] for row in rows),
        買い数=sum(row['買い数'] for row in rows),売り数=sum(row['売り数'] for row in rows),
        主評価=primary,risks=out,対固定方向改善=None if rate is None else rate-max(long,short))


def choose(summaries: list[dict]) -> dict:
    """
    機能: 選択6場だけで件数と両方向を要求し、異familyの最大三候補を固定する。
    引数: summaries(list[dict]) は全44条件の期間集計。
    返り値: dict は正式候補と比較用参照。別枠10場を選択に使わない。
    """
    qualified=[];reference=[]
    for row in summaries:
        s=row['periods']['選択'];p=s['主評価']['全体']
        if s['予兆数']:
            score=(s['対固定方向改善'],p['全候補順先率'],s['活動場数'],s['予兆数'])
            reference.append((score,row))
            if s['予兆数']>=12 and s['活動場数']>=4 and s['買い数']>=3 and s['売り数']>=3:
                qualified.append((score,row))
    def different(ranked: list) -> list[str]:
        """
        機能: family重複を避け、固定した順位で最大三つを返す。
        引数: ranked(list[tuple]) は選択期だけの順位。
        返り値: list[str] は候補ID。
        """
        selected=[];families=set()
        for _,row in sorted(ranked,key=lambda v:(v[0],v[1]['id']),reverse=True):
            if row['family'] not in families:
                families.add(row['family']);selected.append(row['id'])
            if len(selected)==3:break
        return selected
    return dict(選択期='選択',正式候補=different(qualified),比較参照=different(reference),
        合格条件数=len(qualified),留保='件数資格合格は予測優位の合格ではない。改善が負又は別枠で失敗なら未発見とする。')

# ----------------------------------------


def main() -> None:
    """
    機能: 固定74入力各一読で37場を作り、過去学習・選択・別枠採点を完了する。
    引数: なし。
    返り値: None。例外はFalseに残し自動再試行しない。金融・API0。
    """
    fixed=guard();OUT.mkdir()
    tally=dict(旧原NPZ=0,新JSONL=0,新金融=0,API=0)
    prepared=[];outputs=[];diagnostics=[];input_proofs=[]
    try:
        lookup={(row['session'],row['symbol']):row for row in fixed['inputs']}
        for index,session in enumerate(fixed['sessions'],1):
            pair={}
            for symbol in ('TOPIX','NK225'):
                info=lookup[session,symbol]
                if info['kind']=='old_npz':
                    tally['旧原NPZ']+=1;arrays=raw_input.read_old(info)
                    proof=dict(path=info['path'],SHA256=info['SHA256'],bytes=info['bytes'],rows=len(arrays['raw_seq']))
                else:
                    tally['新JSONL']+=1;arrays=raw_input.read_jsonl(info)
                    proof=arrays.pop('_read_metadata')
                pair[symbol]=raw_input.prepare_session(arrays,*info['bounds'],tick=fixed['観測T'][symbol])
                input_proofs.append(dict(session=session,symbol=symbol,**proof))
                diagnostics.append(dict(session=session,symbol=symbol,**pair[symbol]['diagnostics']))
                del arrays
            bars=pair['TOPIX']['bars'];peer=peer_features(bars,pair['NK225']['bars'])
            made=features.prepare(bars,peer)
            assert made['specifications']==features.specifications()
            assert made['signals'].shape==(len(bars['t_s']),32)
            assert made['X'].shape==(len(bars['t_s']),len(made['names'])) and np.isfinite(made['X']).all()
            target=targets.measure(target_bars(bars),pair['TOPIX']['prices'],pair['TOPIX']['diagnostics']['window_complete'])
            eligible,ml_eligible=entry_masks(bars,lookup[session,'TOPIX']['bounds'][1])
            dataset=dict(session=session,bars=bars,target=target,eligible=eligible,ml_eligible=ml_eligible,**made)
            if prepared:
                assert made['names']==prepared[0]['names'] and made['feature_groups']==prepared[0]['feature_groups']
            arrays_to_save={f'bars__{key}':value for key,value in bars.items() if isinstance(value,np.ndarray)}
            arrays_to_save.update({f'prices__{key}':value for key,value in pair['TOPIX']['prices'].items() if isinstance(value,np.ndarray)})
            arrays_to_save.update({f'target__{key}':value for key,value in target.items() if isinstance(value,np.ndarray)})
            arrays_to_save.update(X=made['X'],signals=made['signals'],eligible=eligible,ml_eligible=ml_eligible)
            outputs.append(dict(session=session,**save_npz(OUT/'prepared'/(session+'.npz'),arrays_to_save)))
            prepared.append(dataset)
            del pair,arrays_to_save
            print(json.dumps(dict(入力場=index,session=session,**tally),ensure_ascii=False),flush=True)
        assert tally==plan.read(plan.HERE/'正式固定.json')['実行予定']
        # ----------------------------------------
        # 学習21場だけを読む行集合と標準化。追加10場のラベルは学習しない。
        models={};specs=list(features.specifications())
        train=[v for v in prepared if v['session'] in fixed['splits']['学習']]
        group_map=prepared[0]['feature_groups'];names=prepared[0]['names']
        for model_id,groups in plan.MODEL_GROUPS.items():
            columns=[i for i,name in enumerate(names) if group_map[name] in groups]
            assert columns
            by_side=[]
            for side in range(2):
                xx=[];yy=[];ww=[]
                for v in train:
                    lab=v['target']['labels'][:,side,1]
                    mask=v['ml_eligible']&(np.arange(len(lab))%5==0)&np.isin(lab,(-1,1))
                    count=int(mask.sum())
                    if count:
                        xx.append(v['X'][mask][:,columns]);yy.append((lab[mask]==1).astype(float));ww.append(np.full(count,1/count))
                assert xx and sum(len(a) for a in xx)>=30
                by_side.append(learner.fit(np.vstack(xx),np.concatenate(yy),np.concatenate(ww),plan.RIDGE))
            models[model_id]=dict(columns=columns,names=[names[i] for i in columns],sides=by_side,train_sessions=fixed['splits']['学習'])
            for threshold in plan.THRESHOLDS:
                specs.append(dict(id=model_id+'_P'+str(int(round(threshold*100))),family='学習',
                    name=model_id+'・見込み'+str(int(round(threshold*100)))+'以上',
                    description='学習21場だけで10pt順行対5pt逆行をL2 logisticで両方向別に学習。高い側が閾値以上かつ差0.1以上の初回。',
                    model_id=model_id,threshold=threshold))
        assert len(specs)==44 and len({v['id'] for v in specs})==44
        accounts=[]
        for v in prepared:
            learned={}
            for model_id,model in models.items():
                X=v['X'][:,model['columns']]
                learned[model_id]=[learner.predict(m,X) for m in model['sides']]
            for index,spec in enumerate(specs):
                signal=v['signals'][:,index] if index<32 else learner.publications(*learned[spec['model_id']],v['ml_eligible'],spec['threshold'])
                accounts.append(account(v,signal,spec))
        periods=dict(fixed['splits'])
        periods['別枠10']=periods['時系列別枠']+periods['追加別枠']
        periods['別枠デイ']=[s for s in periods['別枠10'] if s.endswith('_Day')]
        periods['別枠ナイト']=[s for s in periods['別枠10'] if s.endswith('_Night')]
        periods['全37']=fixed['sessions']
        summaries=[]
        for spec in specs:
            own=[v for v in accounts if v['id']==spec['id']]
            summaries.append(dict(**spec,periods={name:merge([v for v in own if v['session'] in sessions]) for name,sessions in periods.items()}))
        selected=choose(summaries)
        assert plan.sources()==plan.read(plan.HERE/'正式固定.json')['source_SHA256']
        plan.write(OUT/'十ポイント予兆の結果.json',dict(全合格=True,金融=False,試行=plan.TRIAL,
            source_SHA256=plan.sources(),counts=tally,sessions=fixed['sessions'],splits=fixed['splits'],periods=periods,
            specifications=specs,feature_names=names,feature_groups=group_map,models=models,
            selection=selected,summaries=summaries,accounts=accounts,outputs=outputs,diagnostics=diagnostics,input_proofs=input_proofs,
            留保='TOPIX観測現在値の先着。実約定/決済勝率/収支でない。前21場の学習内成績と選択期を、別枠10場から分離。'))
        print(json.dumps(dict(全合格=True,候補数=len(specs),選択=selected,**tally),ensure_ascii=False),flush=True)
    except BaseException as exc:
        plan.write(OUT/'False.json',dict(全合格=False,counts=tally,例外型=type(exc).__name__,例外=str(exc),自動再試行=False))
        raise


if __name__=='__main__':main()
