"""候補の母集団・同秒順序・相手公開境界を売買前に検査する。"""

from pathlib import Path
import hashlib
import json
import pickle
import numpy as np
import design
import entry_signals as signals

HERE=Path(__file__).resolve().parent


def crop(values: dict, mask: np.ndarray) -> dict:
    """機能: イベント行対応列だけを同じマスクで切断する。

    引数: values (dict)、mask (ndarray[bool])。返り値: 切断辞書 (dict)。
    """
    return {k:(v[mask].copy() if isinstance(v,np.ndarray) and len(v)==len(mask) else v) for k,v in values.items()}


def main() -> None:
    """機能: 共通自己候補・独立価格・再準備・過去不変を照合する。

    引数: なし。返り値: なし (None)。取引損益・将来価格ラベルは作らない。
    """
    inputs=pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    events=pickle.loads((HERE/'released_minutes.pkl').read_bytes())
    forecasts={lag:pickle.loads((HERE/f'model_outputs_lag{lag}.pkl').read_bytes()) for lag in (1,3,6)}
    specs=design.catalog()+design.supplementary();byid={s['id']:s for s in specs}
    score=np.array([1.2,1.3,.4,1.1,1.4,-1.2,-1.4])
    change=np.array([-.1,.1,0,.1,.1,-.1,-.1])
    result,_=signals.candidate_events(score,np.ones(7,bool),change,1.,.5,.05)
    assert result.tolist()==[0,0,0,1,0,-1,0]
    checks=[];counts=[]
    examples=[byid[s] for s in ('I00','I01','I03','I05','I06','I19','I13','I14','I00_R00','I05_R63')]
    for key,ready in sorted(inputs.items()):
        baseline,binfo=signals.make(byid['I00'],key,inputs,events,forecasts)
        for identifier in ('I05','I06'):
            filtered,info=signals.make(byid[identifier],key,inputs,events,forecasts)
            assert info['自己候補行']==binfo['自己候補行']
            assert np.all((filtered==0)|(filtered==baseline))
        # ----------------------------------------
        # I19は板値・板の有効性・全予測値を変えても同一でなければならない。
        original,_=signals.make(byid['I19'],key,inputs,events,forecasts)
        altered=dict(forecasts)
        for lag in (1,3,6):
            altered[lag]=dict(forecasts[lag]);other={k:v.copy() for k,v in forecasts[lag][key].items()}
            for column in ('observed','prediction','residual'):other[column][:]=np.nan
            other['forecast_valid'][:]=False;other['common_valid'][:]=False
            altered[lag][key]=other
        modified,info=signals.make(byid['I19'],key,inputs,events,altered)
        np.testing.assert_array_equal(original,modified)
        for spec in specs:
            dense,info=signals.make(spec,key,inputs,events,forecasts)
            assert np.isin(dense,[-1,0,1]).all()
            assert not np.any(dense[ready['time_s']>=ready['limit']-300])
            counts.append(dict(id=spec['id'],session=key[0],symbol=key[1],候補数=info['最終候補数'],
                自己候補数=len(info['自己候補行']),有効区間数=info['共通有効区間数']))
        for spec in examples:
            dense,info=signals.make(spec,key,inputs,events,forecasts)
            for fraction in (.37,.73):
                end=max(2,int(len(ready['seq'])*fraction));limitseq=ready['seq'][end-1]
                shortened=dict(inputs)
                shortened[key]={k:(v[:end].copy() if isinstance(v,np.ndarray) and v.shape and len(v)==len(ready['seq']) else v) for k,v in ready.items()}
                small_events=dict(events);small_events[key]=crop(events[key],events[key]['seq']<=limitseq)
                small_forecasts={lag:dict(forecasts[lag]) for lag in (1,3,6)}
                for lag in (1,3,6):small_forecasts[lag][key]=crop(forecasts[lag][key],forecasts[lag][key]['seq']<=limitseq)
                partial,_=signals.make(spec,key,shortened,small_events,small_forecasts)
                np.testing.assert_array_equal(partial,dense[:end])
                # 自市場の将来原本価格と、相手の未公開推定を同時に変えても過去は不変。
                future_inputs=dict(inputs);future_inputs[key]=dict(ready)
                future_inputs[key]['last']=ready['last'].copy();future_inputs[key]['last'][end:]+=123
                future_forecasts={lag:dict(forecasts[lag]) for lag in (1,3,6)}
                peer_key=(key[0],'TOPIX' if key[1]=='NK225' else 'NK225')
                for lag in (1,3,6):
                    for changed_key,boundary in ((key,ready['time_s'][end-1]),(peer_key,ready['time_s'][end-1]-60)):
                        item={k:v.copy() for k,v in forecasts[lag][changed_key].items()}
                        mask=item['time_s']>boundary
                        for column in ('observed','prediction','residual'):item[column][mask]*=-100
                        future_forecasts[lag][changed_key]=item
                altered,_=signals.make(spec,key,future_inputs,events,future_forecasts)
                np.testing.assert_array_equal(altered[:end],dense[:end])
            checks.append(dict(id=spec['id'],session=key[0],symbol=key[1],過去切断数=2,未来改変数=2))
    # ----------------------------------------
    # 全モデルの上下反射は既に別監査済み。ここでは入口側の反射配線を検査する。
    mirrors={}
    for key,ready in inputs.items():
        mirrors[key]=dict(ready);mirrors[key]['last']=2*(float(ready['last'].max())+10)-ready['last']
    reflected={lag:{} for lag in (1,3,6)}
    for lag in (1,3,6):
        for key,value in forecasts[lag].items():
            reflected[lag][key]={k:(-v if k in ('observed','prediction','residual') else v) for k,v in value.items()}
    for key in inputs:
        for spec in examples:
            original,_=signals.make(spec,key,inputs,events,forecasts)
            mirror,_=signals.make(spec,key,mirrors,events,reflected)
            np.testing.assert_array_equal(mirror,-original)
    paths=[Path(__file__),Path(signals.__file__),Path(design.__file__),HERE/'モデル学習の固定.json']
    result=dict(全合格=True,全条件数=len(specs),全候補検査数=len(counts),因果検査数=len(checks),
        各因果検査=checks,候補集計=counts,独立価格の板無関係=True,両市場自己母集団一致=True,
        価格不一致の機会消費=True,上下反射数=len(inputs)*len(examples),実相場損益未実施=True,
        SHA256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    (HERE/'入口配線の因果検査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(全合格=True,全候補検査数=len(counts),因果検査数=len(checks)),ensure_ascii=False))


if __name__=='__main__':main()
