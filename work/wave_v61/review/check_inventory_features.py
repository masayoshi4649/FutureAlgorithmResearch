"""在庫系の確定方向材料を原本切断と未来価格改変で独立検査する。"""

import hashlib
import importlib.util
import json
import pickle
from pathlib import Path

import numpy as np

HERE=Path(__file__).resolve().parent
SOURCE=HERE.parent/'inventory'
spec=importlib.util.spec_from_file_location('在庫材料監査',SOURCE/'features.py')
features=importlib.util.module_from_spec(spec)
spec.loader.exec_module(features)


def main() -> None:
    """機能: 全50口座を単独で作り、公開後に限る方向材料の因果性を確認する。

    引数: なし。返り値: なし(None)。新たな売買損益は計算しない。
    """
    old=HERE.parent.parent/'wave_v60'
    inputs=pickle.loads((old/'inputs.pkl').read_bytes())
    quotes=pickle.loads((old/'quotes.pkl').read_bytes())
    checks=events=0
    for key,ready in inputs.items():
        quote=quotes[key];full=features.direction_events(ready,quote)
        for size in (1,len(ready['seq'])//3,len(ready['seq'])*3//4):
            part=dict(ready,seq=ready['seq'][:size],time_s=ready['time_s'][:size])
            qp={name:value[:size] for name,value in quote.items()}
            wanted=full[full[:,0]<size]
            np.testing.assert_array_equal(features.direction_events(part,qp),wanted)
            changed={name:value.copy() for name,value in quote.items()}
            for name in ('mid','bid','ask'):changed[name][size:]+=ready['tick']*300.
            modified=features.direction_events(ready,changed)
            np.testing.assert_array_equal(modified[modified[:,0]<size],wanted)
            checks+=2
        for row in full:
            i=int(row[0]);clock=ready['time_s'][i]
            assert np.floor(clock/300)>np.floor(ready['time_s'][i-1]/300)
            if row[3]:assert clock-ready['start']>=35*60
        events+=len(full)
    result=dict(合格=True,口座数=len(inputs),方向材料数=events,切断改変比較=checks,
                過去他セッション不使用=True,新売買損益未計算=True,
                コードSHA256=hashlib.sha256((SOURCE/'features.py').read_bytes()).hexdigest())
    (HERE/'在庫特徴の独立因果監査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
