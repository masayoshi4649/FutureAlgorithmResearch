"""追撃停止幅の単独変更を、市場入力を使わず独立人工で検査する。"""

import json
from pathlib import Path
import numpy as np
import overlay137
import overlay_wide137
from test_overlay137 import fixture, source_hash

HERE=Path(__file__).resolve().parent


def call(data, width, initial=2, mode=2, adaptive=False, previous=False):
    """
    機能: 人工親へ停止幅だけを与える。
    引数: data(dict)、width(float)、initial/mode(int)、adaptive/previous(bool)は人工条件。
    返り値: ndarrayは保存形式の注文。
    """
    args=[data[k] for k in ('times','bid','ask','qok','atr','market','phase','original')]
    args.extend([initial,mode,.25,15.,adaptive])
    return overlay137.campaign(*args) if previous else overlay_wide137.campaign(*args,width)


def main():
    """
    機能: 元0.5幅との同値、広幅と元玉不変、未来置換不変を人工確認する。
    引数: なし。
    返り値: None。市場読取・金融再生は行わない。
    """
    checks=[]
    d=fixture();d['bid'][3:50]=106.;d['ask'][3:50]=107.
    d['bid'][50:55]=94.;d['ask'][50:55]=95.
    d['bid'][55:60]=89.;d['ask'][55:60]=90.
    d['bid'][60:]=86.;d['ask'][60:]=87.;d['original'][-1,5]=86.
    for side in (1,-1):
        e={k:v.copy() for k,v in d.items()}
        if side<0:
            e['bid']=300.-d['ask'];e['ask']=300.-d['bid'];e['market'][:,4:8]*=-1
            e['original'][:,3]*=-1;e['original'][:,5]=300.-d['original'][:,5]
        for initial in (1,2,3,5):
            for mode in (0,1,2):
                for adaptive in (False,True):
                    a=call(e,.5,initial,mode,adaptive,True);b=call(e,.5,initial,mode,adaptive)
                    assert np.array_equal(a,b)
                    checks.append(f'元0.5幅一致:方向{side}初回{initial}方式{mode}配分{adaptive}')
    baseline=call(d,.5)
    for width,expected in ((.5,51),(.75,56),(1.,61),(0.,None)):
        result=call(d,width)
        stops=result[result[:,6]==902]
        assert (len(stops)==0) if expected is None else (len(stops)==1 and stops[0,0]==expected)
        assert np.array_equal(result[result[:,8]==0],baseline[baseline[:,8]==0])
        assert np.array_equal(result[result[:,7]==1],baseline[baseline[:,7]==1])
        checks.extend([f'停止幅{width}の外部期待返済行',f'停止幅{width}で元玉と新規列不変'])
        for cut in (10,47,48,53,58,63):
            changed={k:v.copy() for k,v in d.items()}
            changed['bid'][cut+1:]=200.;changed['ask'][cut+1:]=201.
            changed['market'][cut+1:,4:8]=-.5;changed['original'][-1,5]=200.
            alternate=call(changed,width)
            assert np.array_equal(result[result[:,0]<=cut],alternate[alternate[:,0]<=cut])
            checks.append(f'停止幅{width}・接頭{cut}の未来置換不変')
    evidence=dict(passed=True,checks=len(checks),items=checks,
        sources={p.name:source_hash(p) for p in (HERE/'overlay137.py',HERE/'overlay_wide137.py',HERE/'round3_137.py')},
        market_files_read=0,financial_replays=0,api=0)
    (HERE/'audit_wide_artificial137.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,checks=len(checks)),ensure_ascii=False))


if __name__=='__main__':
    main()
