"""中期水準の接続を、現在行と相手の厳密過去境界で検査する。"""

from pathlib import Path
import json
import numpy as np
from regime_features142 import prepare


def main():
    """
    機能: 追加列の対応、同時刻相手排除、後続行改変の前方不変を人工確認する。
    引数: なし。
    返り値: None。確認結果をJSONへ保存する。
    """
    scene='人工場';times=np.array([0.,1.,1.,2.,3.,4.]);base={};hist={}
    for symbol in ('NK225','TOPIX'):
        base[symbol]=dict(ready=dict(time_s=times),features=np.zeros((6,36)))
        hist[scene,symbol]=np.arange(90.).reshape(6,15)
    result=prepare(dict(session=scene),base,hist)
    a=result['NK225']['features']
    np.testing.assert_equal(a[:,36:42],hist[scene,'NK225'][:,[0,1,3,4,2,5]])
    np.testing.assert_equal(a[2,42:48],hist[scene,'TOPIX'][0,[0,1,3,4,2,5]])
    assert np.isnan(a[0,42:]).all()
    changed={k:v.copy() for k,v in hist.items()}
    for h in changed.values():h[4:]+=9999
    later=prepare(dict(session=scene),base,changed)
    for symbol in base:np.testing.assert_allclose(result[symbol]['features'][:4],later[symbol]['features'][:4],equal_nan=True)
    Path(__file__).with_name('中期水準特徴の人工検査142.json').write_text(json.dumps(dict(列対応=True,同秒相手除外=True,未来不変=True),ensure_ascii=False),encoding='utf-8')
    print('中期水準特徴の人工検査合格')


if __name__=='__main__':
    main()
