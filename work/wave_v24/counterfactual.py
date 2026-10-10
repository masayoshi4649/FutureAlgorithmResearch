"""X05の追加価値を、固定化・枝の無効化・無関係な選択で反証する。"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import itertools
import json
from pathlib import Path
import pickle
import sys
import time
from zoneinfo import ZoneInfo

import numpy as np

OUT = Path(__file__).resolve().parent
OLD = OUT.parent/'wave_v23'
sys.path.insert(0,str(OLD))
import engine
import managers
import research
import selector_signals

CHOICES = ['F32','F42','F43','F44']


def save(name: str, value: object) -> None:
    """機能: 敵対検証の有限JSONを新作業領域に保存する。

    引数: name (str)、value (object)。返り値: なし (None)。
    """
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def evaluate(identifier: str, direction: dict, inputs: dict, description: str, group: str) -> dict:
    """機能: 一つの反証条件を同じG08で先頭から売買再生する。

    引数: identifier/description/group (str)、direction/inputs (dict)。返り値: 同銘柄集計と各区間 (dict)。
    """
    spec=next(x for x in managers.manager_catalog()if x['id']=='G08')
    rows=[]
    for key,ready in inputs.items():
        cfg=managers.make_config(spec,key[1],ready)
        replay=engine.run(ready,direction[key],cfg)
        rows.append(research.summarize(replay,cfg,key[1],key[0],identifier))
    return dict(id=identifier,description=description,group=group,
        symbols={s:research.aggregate([r for r in rows if r['symbol']==s])for s in ['TOPIX','NK225']},rows=rows)


def choose_direction(labels: np.ndarray, base: dict, key: tuple) -> np.ndarray:
    """機能: 選択ラベルごとに同時点の基礎方向を使う。

    引数: labels (ndarray[int])、base (dict)、key (tuple)。返り値: 原本行の方向 (ndarray[int8])。
    """
    result=np.zeros(len(labels),np.int8)
    for i,signal in enumerate(CHOICES):
        ok=labels==i
        result[ok]=base[signal][key][ok]
    return result


def random_labels(ready: dict, seed: int, probabilities: np.ndarray) -> np.ndarray:
    """機能: 将来価格を見ず、３分ごとの独立乱数で監視手法を固定する。

    引数: ready (dict)、seed (int)、probabilities (ndarray)。返り値: 選択ラベル (ndarray[int])。
    """
    token=f'{seed}|{ready["session"]}|{ready["symbol"]}'.encode()
    rng=np.random.default_rng(int.from_bytes(hashlib.sha256(token).digest()[:8],'little'))
    stamps=np.arange(ready['start']+1200,np.nextafter(float(ready['time_s'][-1]),np.inf),180.)
    labels=rng.choice(4,size=len(stamps),p=probabilities)
    ix=np.searchsorted(stamps,ready['time_s'],side='right')-1
    result=np.full(len(ix),-1,dtype=np.int8)
    ok=ix>=0
    result[ok]=labels[ix[ok]]
    return result


def main() -> None:
    """機能: 反証条件を先に固定し、元条件を変更せず追加価値を測る。

    引数: なし。返り値: なし (None)。現在APIと旧成果への書込みはない。
    """
    OUT.mkdir(exist_ok=True)
    plan=dict(時刻=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),比較対象='X05_G08',注文管理固定='G08、１枚、費用０・指定価格約定',
        固定化=CHOICES,枝の除去=['wall','near','far'],枝の無効化=['F44','F42','F43','F32'],
        全写像順列数=24,乱数種=list(range(128)),無関係な選択=['３分毎一様４択','３分毎・過去完了区間の監視頻度に比例'],
        感度='refill/pressure/flowを各単独±20%、確認1/3回、保持2/4分',
        解釈='すべて診断。最良の反例を新しい採用候補にしない。固定1,520条件の後で計画したため未知検証ではない。',
        乱数比較='対照もその時点までの情報のみ。128乱数は独立した128期間ではない。写像順列も厳密な無作為割付実験ではない。',
        SHA256={str(p.relative_to(OUT.parent)):hashlib.sha256(p.read_bytes()).hexdigest()for p in [Path(__file__),OLD/'selector_signals.py',OLD/'engine.py',OLD/'managers.py']})
    save('反証の事前固定.json',plan)
    inputs=pickle.loads((OLD/'inputs.pkl').read_bytes())
    features=pickle.loads((OLD/'features_depth.pkl').read_bytes())
    base=pickle.loads((OLD/'directions.pkl').read_bytes())
    original=pickle.loads((OLD/'selector_directions.pkl').read_bytes())['X05']
    controls=selector_signals._controls(inputs,features,base)
    spec=next(s for s in selector_signals.catalog()if s['id']=='X05')
    labels,decisions={},{}
    for key,ready in inputs.items():
        direction,events=selector_signals._select(spec,ready,controls[key],{s:base[s][key]for s in CHOICES})
        np.testing.assert_array_equal(direction,original[key])
        indices=np.array([e['row_index']for e in events])
        selected=np.array([CHOICES.index(e['selected_signal_id'])for e in events],dtype=np.int8)
        ix=np.searchsorted(indices,np.arange(len(ready['last'])),side='right')-1
        value=np.full(len(ix),-1,np.int8);ok=ix>=0;value[ok]=selected[ix[ok]]
        labels[key]=value;decisions[key]=selected
    cases=[]
    cases.append(evaluate('基準_X05',original,inputs,'元の選択と管理をそのまま再現','基準'))
    for signal in CHOICES:
        cases.append(evaluate('固定_'+signal,base[signal],inputs,signal+'だけを常に監視。選択器を外す。','固定'))
    cases.append(evaluate('方向反転',{k:-v for k,v in original.items()},inputs,'元X05の買い売りだけ反転。全決済を再計算。','方向'))
    for signal in CHOICES:
        index=CHOICES.index(signal)
        removed={key:np.where(labels[key]==index,0,original[key]).astype(np.int8)for key in inputs}
        cases.append(evaluate('選択中だけ停止_'+signal,removed,inputs,signal+'を選んだ時間だけ新規中立。既存玉は管理を継続。','休止'))
        only={key:np.where(labels[key]==index,original[key],0).astype(np.int8)for key in inputs}
        cases.append(evaluate('選択中だけ稼働_'+signal,only,inputs,signal+'を選んだ時間だけ新規可能。時価・損切りは常に有効。','単枝'))
        if signal!='F32':
            replaced={key:np.where(labels[key]==index,base['F32'][key],original[key]).astype(np.int8)for key in inputs}
            cases.append(evaluate('枝をF32へ置換_'+signal,replaced,inputs,signal+'の選択タイミングでF32を監視。切替時刻は不変。','置換'))
    variants=[('補充条件なし',{'refill':2.}),('近遠一致条件なし',{'pressure':2.}),('遠方先行条件なし',{'flow':2.})]
    for name in ['refill','pressure','flow']:
        for factor in [.8,1.2]:variants.append((f'{name}_{factor}',{name:spec['params'][name]*factor}))
    variants.extend([('確認１回',{'confirm':1}),('確認３回',{'confirm':3}),('保持２分',{'hold_minutes':2}),('保持４分',{'hold_minutes':4})])
    for name,change in variants:
        alternate=dict(spec,params={**spec['params'],**change})
        directions={key:selector_signals._select(alternate,ready,controls[key],{s:base[s][key]for s in CHOICES})[0]for key,ready in inputs.items()}
        cases.append(evaluate(name,directions,inputs,'選択パラメータだけ変更 '+str(change),'除去'if name.endswith('なし')else'感度'))
    save('枝除去と感度.json',cases)
    permutations=[]
    for perm in itertools.permutations(range(4)):
        new={}
        for key,label in labels.items():
            changed=np.full(len(label),-1,np.int8);ok=label>=0;changed[ok]=np.asarray(perm)[label[ok]]
            new[key]=choose_direction(changed,base,key)
        name='写像_'+'_'.join(CHOICES[v]for v in perm)
        result=evaluate(name,new,inputs,'監視枝の条件と時刻を固定し、使う基礎手法の対応だけ全順列で変更','写像')
        result['mapping']={CHOICES[i]:CHOICES[v]for i,v in enumerate(perm)}
        permutations.append(result)
    save('対応を入れ替える検査.json',permutations)
    counts={key:np.bincount(values,minlength=4).astype(float)for key,values in decisions.items()}
    priors={}
    for key in inputs:
        prior=np.ones(4)
        for past,value in counts.items():
            if past[1]==key[1]and past[0]<key[0]:prior+=value
        priors[key]=prior/prior.sum()
    randoms=[];started=time.monotonic();prefix_checks=0
    for scheme in ['一様','過去頻度']:
        for seed in range(128):
            directions={}
            for key,ready in inputs.items():
                prob=np.ones(4)/4 if scheme=='一様'else priors[key]
                chosen=random_labels(ready,seed,prob)
                directions[key]=choose_direction(chosen,base,key)
                if seed<2:
                    cut=max(1,len(ready['last'])//2)
                    short=dict(ready,time_s=ready['time_s'][:cut])
                    np.testing.assert_array_equal(random_labels(short,seed,prob),chosen[:cut]);prefix_checks+=1
            randoms.append(evaluate(f'{scheme}_{seed:03d}',directions,inputs,f'３分毎に{scheme}で４基礎手法を選ぶ。seed={seed}','無関係な選択'))
            if (seed+1)%32==0:print(f'{scheme} {seed+1}/128、{time.monotonic()-started:.0f}秒',flush=True)
    save('無関係な選択の全結果.json',randoms)
    baseline=cases[0]
    comparisons=[]
    for scheme in ['一様','過去頻度']:
        sample=[v for v in randoms if v['id'].startswith(scheme+'_')]
        by_symbol={}
        for symbol in research.SYMBOLS:
            a=baseline['symbols'][symbol]
            net=np.array([v['symbols'][symbol]['net_yen']for v in sample])
            pf=np.array([v['symbols'][symbol]['money_ratio']or 0 for v in sample])
            by_symbol[symbol]=dict(基準収支=a['net_yen'],収支百分位=np.percentile(net,[0,5,25,50,75,95,100]).tolist(),
                基準以上収支数=int((net>=a['net_yen']).sum()),基準以上PF数=int((pf>=a['money_ratio']).sum()),
                PF百分位=np.percentile(pf,[0,5,25,50,75,95,100]).tolist(),黒字数=int((net>0).sum()))
        comparisons.append(dict(対照=scheme,件数=len(sample),symbols=by_symbol,
            両銘柄で基準収支以上数=sum(all(v['symbols'][s]['net_yen']>=baseline['symbols'][s]['net_yen']for s in research.SYMBOLS)for v in sample),
            両銘柄で基準PF以上数=sum(all((v['symbols'][s]['money_ratio']or 0)>=baseline['symbols'][s]['money_ratio']for s in research.SYMBOLS)for v in sample)))
    save('反証対照の要約.json',dict(基準=baseline,乱数比較=comparisons,乱数prefix一致=prefix_checks,
        書換えなし=True,現在API取得=0,枝除去条件数=len(cases),対応順列数=len(permutations),乱数条件数=len(randoms)))
    print('反証対照を完了しました。',flush=True)


if __name__=='__main__':
    main()
