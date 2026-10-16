"""改修の入口差替えが過去状態だけで決まり、欠測で再準備しないことを確認する。"""

import json
import numpy as np

from accounts import HERE,WORK,study,pdca


def main() -> None:
    """機能: 同方向一度・瞬時入口・反転の人工境界と途中切断を検査する。

    引数: なし。返り値: なし(None)。損益は評価しない。
    """
    checks=0
    grid=np.arange(40.,80.)
    for gap in [False,True]:
        for neutral_length in [10,11]:
            state=np.ones(40,dtype=np.int8);valid=np.ones(40,dtype=bool)
            state[5:5+neutral_length]=0
            if gap:valid[10]=False
            result=pdca.once_per_wave(state,valid,grid)
            expected=np.zeros(40,dtype=np.int8);expected[0]=1
            if neutral_length==11 and not gap:expected[16]=1
            np.testing.assert_array_equal(result,expected);checks+=1
    state=np.r_[np.ones(5),-np.ones(5),np.ones(30)].astype(np.int8)
    valid=np.ones(40,dtype=bool);out=pdca.once_per_wave(state,valid,grid)
    expected=np.zeros(40,dtype=np.int8);expected[[0,5,10]]=[1,-1,1]
    np.testing.assert_array_equal(out,expected);checks+=1
    data=dict(grid=grid,valid=valid,states=np.stack([state]*8),raw_states=np.stack([-state]*8))
    for mode in [0,1,2]:
        for inverse in [False,True]:
            c=dict(signal=0,state_mode=mode,invert=inverse)
            full=pdca.altered_states(c,data)
            desired=(-state if mode==1 else out if mode==2 else state)*(-1 if inverse else 1)
            np.testing.assert_array_equal(full,desired);checks+=1
            for cut in [1,4,6,11,25,39]:
                prefix={k:v[:,:cut] if v.ndim==2 else v[:cut] for k,v in data.items()}
                np.testing.assert_array_equal(pdca.altered_states(c,prefix),full[:cut]);checks+=1
    result=dict(合格=True,人工比較数=checks,改修実装SHA256=study.digest(WORK/'pdca.py'),
        中立の定義='validかつ確認済みstateが0。確認待ちや弱い信号も含み、両板の均衡を直接表すものではない。',
        注意='raw入口は3秒持続待ちだけを省く。情報源の代理時計・現在age10秒は同じで、実受信速度の改善を証明しない。')
    (HERE/'改修入口の人工境界と未来監査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
