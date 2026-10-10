"""指定値約定を主条件として保ち、注文執行と信号遅延の弱点を別軸で検証する。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numpy as np

OUT = Path(__file__).resolve().parent
OLD = OUT.parent/'wave_v23'
sys.path.insert(0,str(OLD))
import engine as baseline
import managers
from research import summarize, aggregate


def observed_engine():
    """機能: 逆指値だけを到達観測価格へ変更した隔離コピーを作って読む。

    引数: なし。返り値: 複製エンジンのモジュール (ModuleType)。旧コードは変更しない。
    """
    source = (OLD/'engine.py').read_text(encoding='utf-8')
    assert source.count('fill=level')==1
    assert source.count('anchor=p if pending_market else pending_level')==1
    source = source.replace('fill=level','fill=p if event!=6 else level')
    source = source.replace('anchor=p if pending_market else pending_level','anchor=p')
    source = source.replace('指定価格約定。主玉・カバー合計',
                            '補足検証: 逆指値は到達観測価格、利確指値は指定価格。主玉・カバー合計')
    target = OUT/'engine_observed.py'
    target.write_text(source,encoding='utf-8')
    spec = importlib.util.spec_from_file_location('engine_observed_adversarial',target)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def delayed(ready: dict, state: np.ndarray, seconds: int) -> np.ndarray:
    """機能: 売買方向の到着だけを固定秒数遅らせる。

    引数: ready (dict)、state (ndarray)、seconds (int)。返り値: 遅延した方向 (ndarray[int8])。
    価格・ATR・注文処理の遅延ではない。ゼロ秒は同時刻の未来行を参照せず元列を使う。
    """
    if seconds==0:
        return state.copy()
    lookup = np.searchsorted(ready['time_s'],ready['time_s']-seconds,side='right')-1
    result = np.zeros(len(state),dtype=np.int8)
    valid = lookup>=0
    assert np.all(lookup[valid]<np.flatnonzero(valid))
    result[valid] = state[lookup[valid]]
    return result


def fixture(prices: list[float], states: list[int] | None = None, step: float = 1.) -> tuple[dict,np.ndarray,dict]:
    """機能: 短時間で特定の注文順序を再現する合成入力を作る。

    引数: prices (list[float])、states (list[int]|None)、step (float)。
    返り値: 入力・方向・G08由来の設定 (tuple[dict,ndarray,dict])。
    """
    price = np.asarray(prices,dtype=float)
    ready = {'time_s':np.arange(len(price))*step,'last':price,'atr':np.ones(len(price)),
             'tick':.1,'start':0.,'limit':(len(price)-3)*step,'us_open':np.inf}
    state = np.asarray(states if states is not None else [1]*len(price),dtype=np.int8)
    spec = next(row for row in managers.manager_catalog() if row['id']=='G08')
    cfg = managers.make_config(spec,'TOPIX',ready)
    cfg.update(warmup_min=0.,entry_cutoff_min=0.,cooldown_min=0.)
    return ready,state,cfg


def check(result: dict, cap: int, closed: bool = True) -> None:
    """機能: 売買台帳の会計・次行性・数量上限を検算する。

    引数: result (dict)、cap (int)、closed (bool)。返り値: なし (None)。
    """
    t,c,o,s = (result[k] for k in ('trades','cycles','orders','stats'))
    assert s[6]<1e-7 and max(s[2:4])<=cap
    assert np.all(o[:,0]>o[:,1])
    np.testing.assert_allclose(t[:,10].sum(),s[0],atol=1e-7)
    np.testing.assert_allclose(c[:,3].sum(),s[0],atol=1e-7)
    if closed:
        assert s[9]==0


def synthetic(observed) -> list[dict]:
    """機能: 旧注文、ギャップ、新設返済、場末優先に対する最小反例を作る。

    引数: observed (ModuleType)。返り値: テストと説明の一覧 (list[dict])。
    """
    checks = []
    ready,state,cfg = fixture([100,100.5,100.5,100.5,100.5,100.5,100.5],[1,-1,-1,-1,-1,-1,-1])
    result = baseline.run(ready,state,cfg,True)
    check(result,10)
    assert result['orders'][0,0]==1 and result['orders'][0,1]==0 and result['orders'][0,3]==1
    checks.append({'件名':'逆信号と旧逆指値が同じ観測で成立','確認':True,
                   '結果':'前行で存在する買い注文が先に約定し、現在行の売り信号はその後に観測する。未来参照ではないが、反対信号なら同じ行でも取消できるモデルではない。'})

    # ----------------------------------------
    # 新たに縮めた損切りが現在値を通過していても、過去価格では返済しない。
    ready,state,cfg = fixture([100,100,99.5,99.5,99.4,99.3,99.3],step=60.)
    cfg.update(entry_atr=0.,failure_min=1.,failure_mfe=.5,failure_stop=.25,main_trail=np.inf)
    result = baseline.run(ready,state,cfg,True)
    check(result,10)
    trade = result['trades'][0]
    assert trade[7]==3 and trade[5]==99.5 and trade[9]==1
    checks.append({'件名':'新設ストップの遡及を禁止','確認':True,
                   '結果':'100で買い、現在99.5で許容損失を0.25へ縮めても理論水準99.75（呼値丸め99.7）では約定しない。次行の99.5で返済した。'})

    # ----------------------------------------
    # 許可された指定価格モデルの利益が、観測価格モデルでは損失になる例。
    ready,state,cfg = fixture([100,110,90,90,90,90,90])
    base = baseline.run(ready,state,cfg,True)
    other = observed.run(ready,state,cfg,True)
    check(base,10);check(other,10)
    checks.append({'件名':'価格飛びで指定価格モデルが有利になる例','確認':True,
                   '価格経路':ready['last'].tolist(),'指定価格の損益pt':float(base['stats'][0]),
                   '観測価格の損益pt':float(other['stats'][0]),
                   '指定価格取引':base['trades'].tolist(),'観測価格取引':other['trades'].tolist(),
                   '結果':'費用追加ではなく、同じ逆指値をどの値段で約定させるかの差。指定価格は依頼された主前提であり、その条件内の集計誤りを意味しない。'})

    # ----------------------------------------
    # 場末返済の判断がなされた後は、次行で価格ストップより市場返済を優先。
    ready,state,cfg = fixture([100,100,100,100,100,100,95,95])
    cfg['entry_atr']=0.
    result = baseline.run(ready,state,cfg,True)
    check(result,10)
    assert result['trades'][-1,9]==9 and result['trades'][-1,5]==95
    checks.append({'件名':'場末返済予約の優先順位','確認':True,
                   '結果':'場末で返済予約を作った後の価格飛びは、旧損切り指定価格より次行市場返済を優先する。損失予算を価格保証として使えない。'})
    return checks


def reflection_check(module, ready: dict, state: np.ndarray, cfg: dict, result: dict) -> dict:
    """機能: 価格を鏡映し信号を反転した注文器の対称性を確認する。

    引数: module (ModuleType)、ready/config/result (dict)、state (ndarray)。
    返り値: 数量・行・損益の一致記録 (dict)。信号の再計算ではなく注文器の検査。
    """
    reflected = dict(ready)
    offset = 2*np.ceil(float(ready['last'].max())/ready['tick'])*ready['tick']
    reflected['last'] = offset-ready['last']
    answer = module.run(reflected,-state,cfg,False)
    check(answer,cfg['audit_cap'])
    left,right = result['trades'],answer['trades']
    assert left.shape==right.shape
    np.testing.assert_allclose(left[:,[0,1,3,6,7,8,9,10]],right[:,[0,1,3,6,7,8,9,10]],atol=1e-6)
    np.testing.assert_allclose(left[:,2],-right[:,2],atol=0)
    np.testing.assert_allclose(left[:,4:6]+right[:,4:6],offset,atol=1e-6)
    np.testing.assert_allclose(result['stats'][[0,1,4,5,7,8,9,10]],answer['stats'][[0,1,4,5,7,8,9,10]],atol=1e-6)
    return {'確認':True,'鏡映定数':float(offset),'取引数':len(left)}


def main() -> None:
    """機能: ２戦略×２約定モデル×４信号遅延で全既知区間を同一口座再生する。

    引数: なし。返り値: なし (None)。結果を exec_adversarial.json へ保存する。
    """
    source_hash = hashlib.sha256((OLD/'engine.py').read_bytes()).hexdigest()
    observed = observed_engine()
    tests = synthetic(observed)
    inputs = pickle.loads((OLD/'inputs.pkl').read_bytes())
    base_dirs = pickle.loads((OLD/'directions.pkl').read_bytes())
    switch_dirs = pickle.loads((OLD/'selector_directions.pkl').read_bytes())
    directions = {'F32_G08':base_dirs['F32'],'X05_G08':switch_dirs['X05']}
    del base_dirs,switch_dirs
    manager = next(row for row in managers.manager_catalog() if row['id']=='G08')
    old_ranks = json.loads((OLD/'全条件の期間集計.json').read_text(encoding='utf-8'))
    old_ranks += json.loads((OLD/'選択統合の期間集計.json').read_text(encoding='utf-8'))
    expected = {row['id']:row for row in old_ranks}
    rows,periods,reflections = [],[],[]
    for model_name,module in [('指定価格',baseline),('到達観測価格',observed)]:
        for seconds in (0,1,5,15):
            for identifier,direction in directions.items():
                subset=[]
                for key,ready in inputs.items():
                    session,symbol=key
                    cfg=managers.make_config(manager,symbol,ready)
                    state=delayed(ready,direction[key],seconds)
                    result=module.run(ready,state,cfg,False)
                    check(result,cfg['audit_cap'])
                    row=summarize(result,cfg,symbol,session,identifier)
                    row.update(約定モデル=model_name,信号遅延秒=seconds)
                    openings=result['orders'][result['orders'][:,7]==1]
                    opening_rows=openings[:,0].astype(np.int64)
                    row['新規約定と同じ行で中立化']=int(np.sum(state[opening_rows]==0))
                    row['新規約定と同じ行で反対方向']=int(np.sum(state[opening_rows]==-openings[:,3]))
                    rows.append(row);subset.append(row)
                    if seconds==0:
                        reflection=reflection_check(module,ready,state,cfg,result)
                        reflections.append(dict(手法=identifier,約定モデル=model_name,セッション=session,銘柄=symbol,**reflection))
                for symbol in ('TOPIX','NK225'):
                    total=aggregate([row for row in subset if row['symbol']==symbol])
                    for diagnostic in ('新規約定と同じ行で中立化','新規約定と同じ行で反対方向'):
                        total[diagnostic]=sum(row[diagnostic] for row in subset if row['symbol']==symbol)
                    if model_name=='指定価格' and seconds==0:
                        for metric in ('net_yen','gross_profit_yen','gross_loss_yen','drawdown_yen'):
                            assert abs(total[metric]-expected[identifier]['symbols'][symbol][metric])<.01
                    periods.append(dict(手法=identifier,銘柄=symbol,約定モデル=model_name,信号遅延秒=seconds,**total))
                print(f'{model_name} / 遅延 {seconds}秒 / {identifier} 完了',flush=True)
    assert source_hash==hashlib.sha256((OLD/'engine.py').read_bytes()).hexdigest()
    output={'主前提':'指定価格約定・費用０を維持。到達観測価格と信号遅延は補足感度であり、主前提を否定する根拠として扱わない。',
            '設定':{'戦略':['X05_G08','F32_G08'],'約定モデル':['指定価格','到達観測価格'],'信号遅延秒':[0,1,5,15],
                    '費用追加':False,'注文送信やATRの遅延':False,'信号遅延のみ':True,'原本書込':False,'API取得':False,
                    'v23エンジンSHA256':source_hash,'観測価格コピーSHA256':hashlib.sha256((OUT/'engine_observed.py').read_bytes()).hexdigest()},
            '合成反例':tests,'期間集計':periods,'セッション集計':rows,'反射検査':reflections,
            '会計検査':{'再生数':len(rows),'鏡映再生数':len(reflections),'次行執行':True,'全玉会計一致':True,'場内返済':True,'保有上限':True,'主条件は過去集計と一致':True}}
    (OUT/'exec_adversarial.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


if __name__=='__main__':
    main()
