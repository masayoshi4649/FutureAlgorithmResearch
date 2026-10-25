"""巡回特徴の現在行境界と早期準備を人工データだけで検査する。"""

import json
from pathlib import Path
import numpy as np
from patrol_features142 import rolling_range,prepare


def main():
    """
    機能: 窓高安の同秒後続排除・未来不変・厳密過去の相手接続を確認する。
    引数: なし。
    返り値: None。人工確認JSONを書き出す。
    """
    t=np.array([0.,1.,1.,2.,4.]);p=np.array([10.,11.,30.,13.,14.]);good=np.ones(5,np.bool_)
    np.testing.assert_array_equal(rolling_range(t,p,good,2.),np.array([0.,1.,20.,20.,1.]))
    base={};times=np.arange(1000,dtype=float)
    for symbol,center,tick in (('NK225',65000.,10.),('TOPIX',4000.,.5)):
        a=np.full((1000,30),np.nan);price=center+tick*np.sin(times/60.)
        a[:,10]=price;a[:,11]=tick*2
        q=dict(bid=price-tick/2,ask=price+tick/2,quote_valid=np.ones(1000,np.bool_))
        base[symbol]=dict(ready=dict(time_s=times.copy(),atr=np.full(1000,np.nan),tick=tick),quotes=q,features=a)
    result=prepare({},base)
    assert np.isfinite(result['NK225']['features'][121,13])
    assert np.isnan(result['NK225']['features'][0,22])
    assert result['NK225']['features'][1,22]==0.
    changed={}
    for symbol,item in base.items():
        changed[symbol]=dict(item,features=item['features'].copy())
        changed[symbol]['features'][600:,10]+=9999
    latter=prepare({},changed)
    for symbol in base:np.testing.assert_allclose(result[symbol]['features'][:600],latter[symbol]['features'][:600],equal_nan=True)
    target=Path(__file__).with_name('巡回特徴の人工検査142.json')
    target.write_text(json.dumps(dict(同秒後続排除=True,現在原行窓=True,未来不変=True,相手同時刻排除=True,早期短期準備=True),ensure_ascii=False,indent=2),encoding='utf-8')
    print('巡回特徴の人工検査合格')


if __name__=='__main__':
    main()
