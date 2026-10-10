"""追加ナイトの途中判断列を原素材から再生成して因果性を確かめる。"""

from pathlib import Path
import pickle
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import check_component_signals as helper
import replay_parts as replay
mid=replay.mid


def calculate(inputs: dict,features: dict) -> dict:
    """機能: B00/B01を完成済み方向列からでなく公開価格素材から生成する。

    引数: inputs/features(dict)。返り値: ID別の全入力結果(dict)。
    """
    mid.clear_cache()
    return {code:mid.build(next(s for s in mid.catalog() if s['id']==code),inputs,features) for code in ('B00','B01')}


def compare(old: dict,new: dict,count: int,reflection: bool=False) -> None:
    """機能: 方向・公開源行・公開イベント対応と品質を照合する。

    引数: old/new(dict)、count(int)、reflection(bool)。返り値: なし(None)。
    """
    for name in ('direction','source_row','source_event_index'):
        a=old[name][:count]
        if reflection and name=='direction':a=-a
        np.testing.assert_array_equal(a,new[name][:count],err_msg=name)
    np.testing.assert_array_equal(replay.valid_column(old)[:count],replay.valid_column(new)[:count])


def main() -> None:
    """機能: 新2入力×2信号で切断・未来変更・反射・同秒順を確認する。

    引数: なし。返り値: なし(None)。経済成果や既存固定資料は変更しない。
    """
    inputs=pickle.loads((HERE/'new_inputs.pkl').read_bytes())
    features=pickle.loads((HERE/'new_features_depth.pkl').read_bytes())
    base=calculate(inputs,features);start=max(r['start'] for r in inputs.values());end=min(r['time_s'][-1] for r in inputs.values())
    cut=start+(end-start)*.37;future_cut=start+(end-start)*.73
    counts={k:int(np.searchsorted(r['time_s'],cut,side='left')) for k,r in inputs.items()}
    clipped,cf=helper.slice_inputs(inputs,features,counts);small=calculate(clipped,cf)
    changed,ff,_=helper.transformed(inputs,features,future_cut);future=calculate(changed,ff)
    reflected,rf,_=helper.transformed(inputs,features,None);mirror=calculate(reflected,rf)
    records=[]
    for key,ready in inputs.items():
        n=len(ready['last']);fc=int(np.searchsorted(ready['time_s'],future_cut,side='left'))
        duplicates=np.flatnonzero(np.diff(ready['time_s'])==0)+1
        tied=int(duplicates[np.argmin(abs(duplicates-int(n*.73)))])
        keep={k:len(r['last']) for k,r in inputs.items()};keep[key]=tied
        clipped,cf=helper.slice_inputs(inputs,features,keep);same=calculate(clipped,cf)
        for code in base:
            compare(base[code][key],small[code][key],counts[key])
            compare(base[code][key],future[code][key],fc)
            compare(base[code][key],mirror[code][key],n,True)
            compare(base[code][key],same[code][key],tied)
            records.append(dict(id=code,session=key[0],symbol=key[1],切断一致=True,未来変更一致=True,
                上下反射一致=True,同秒順一致=True,方向公開源品質を再生成=True))
    replay.save(HERE/'new_mid_signal_audit.json',dict(全合格=True,入力信号数=4,結果=records,
        実装SHA256={p.name:helper.sha(p) for p in (Path(__file__),Path(mid.__file__),HERE/'replay_parts.py')},
        入力SHA256={p.name:helper.sha(p) for p in (HERE/'new_inputs.pkl',HERE/'new_features_depth.pkl')},API追加取得数=0))
    print('追加ナイトB00/B01：4信号の素材再生成・公開源・品質の全検査一致。',flush=True)


if __name__=='__main__':main()
