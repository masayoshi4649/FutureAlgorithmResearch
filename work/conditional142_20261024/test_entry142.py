"""金融再生ではない人工特徴で入口選択の因果・上下対称性を確認する。"""

import json
from pathlib import Path
import numpy as np
from entry_selector142 import choose_entry, allow_add


def main():
    """
    機能: 方向反転・純粋性・条件境界・失敗後の確認強化を検査する。
    引数: なし。
    返り値: None。人工検査の件数をJSONへ保存する。
    """
    rng=np.random.default_rng(142);count=0
    cols=[3,4,12,13,14,15,20,21,24,25,26,27,28,29]
    for _ in range(500):
        a=rng.normal(size=30);a[9]=a[18]=1.;b=a.copy();b[cols]*=-1
        original=a.copy()
        for policy in (1,2,3):
            for failed in (0,1,2):
                assert choose_entry(policy,a,1,failed)==choose_entry(policy,b,-1,failed)
                count+=1
        for policy in (1,2):
            assert allow_add(policy,a,1,-.5)==allow_add(policy,b,-1,-.5)
        np.testing.assert_array_equal(a,original)
    a=np.ones(30);a[4]=a[15]=-1
    assert choose_entry(1,a,1,0)[0]==2
    assert choose_entry(2,a,1,0)[0]==0
    a[28]=a[29]=-1
    assert choose_entry(2,a,1,0)[0]==2
    assert not allow_add(2,a,1,-.5)
    assert allow_add(2,a,1,.1)
    target=Path(__file__).with_name('入口選択の人工検査142.json')
    target.write_text(json.dumps(dict(上下対称件数=count,状態不変=500,境界=5,成功=True),ensure_ascii=False,indent=2),encoding='utf-8')
    print('入口選択の人工検査合格',count)


if __name__=='__main__':
    main()
