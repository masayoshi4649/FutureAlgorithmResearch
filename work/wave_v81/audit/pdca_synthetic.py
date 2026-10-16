"""入口と価格出口の整合、単独対照の中立扱い、再準備の因果性を確認する。"""

import json
import numpy as np

from accounts import HERE,WORK,study,pdca
from engine_synthetic import arguments,run


def data_from(args: list) -> tuple:
    """機能: 人工引数を改修ラッパー用の2方向資料へ変換する。

    引数: args(list)。返り値: 1口座の原価格・気配・方向・行番号(tuple)。
    """
    key=('人工','TOPIX');n=len(args[0])
    ready={key:dict(time_s=args[0],tick=args[12],start=args[13],limit=args[14])}
    books={key:dict(bid=args[1],ask=args[2])}
    direction={key:dict(states_self=np.stack([args[7],args[32]]),states_peer=np.stack([args[26],args[33]]),
        valid_self=np.stack([args[27],args[34]]),valid_peer=np.stack([args[28],args[35]]),
        age_peer=np.ones(n),price_valid=args[3],entry_reset=args[4],
        source_self=args[8],source_peer=args[9],bid=args[10],ask=args[11])}
    return ready,books,direction,{key:args[5]}


def main() -> None:
    """機能: 改修の状態整合と、単独対照の出口だけを人工例で検査する。

    引数: なし。返り値: なし(None)。監査JSONだけ保存する。
    """
    records=[];key=('人工','TOPIX')
    config=dict(model=0,exit_model=1,entry_gate=1,entry_mode=0,exit_mode=1,solo=0,repair=0,freshness=10)
    base=arguments([0,5,6,11,12,13,18],[100]*7)
    base += [np.array([1,1,-1,1,0,1,1],dtype=np.int8),base[26].copy(),base[27].copy(),base[28].copy()]
    materials=data_from(base)
    args=pdca.arguments(config,key,materials,5)
    np.testing.assert_array_equal(args[7],[1,1,0,1,0,1,1])
    np.testing.assert_array_equal(args[27],True)
    np.testing.assert_array_equal(args[32],base[32])
    out=run(list(args))
    assert sum(out[4][:,2]==20)==2
    guarded=pdca.arguments(dict(config,repair=1),key,materials,5)
    protected=run(list(guarded))
    starts=protected[4][protected[4][:,2]==20,3]
    np.testing.assert_array_equal(starts,[0,13])
    records.append('入口矛盾は有効中立・出口は別状態・gate後支持の解消で再準備')
    for part in [0,1]:
        altered=data_from(base)
        target='valid_self' if part==0 else 'valid_peer'
        altered[2][key][target][1,4]=False
        changed=pdca.arguments(dict(config,repair=1),key,altered,5)
        assert not changed[27 if part==0 else 28][4]
        np.testing.assert_array_equal(run(list(changed))[4][run(list(changed))[4][:,2]==20,3],[0])
    records.append('自他いずれか価格欠測なら有効中立として再準備しない')
    for solo in [0,1]:
        for mode in [0,1,2]:
            a=arguments([0,5,6,11,16],[100]*5,own=[1,1,0,0,0])
            a += [a[7],a[26],a[27],a[28]]
            cfg=dict(config,model=0,exit_model=0,entry_gate=0,exit_mode=mode,solo=solo)
            wrapped=pdca.arguments(cfg,key,data_from(a),5)
            result=run(list(wrapped))
            assert len(result[1])==(1 if mode==0 else 0)
            np.testing.assert_array_equal(wrapped[27],True)
            assert bool(wrapped[34][2])==(not solo or mode==0)
    records.append('共同版と単独版ともX0だけ中立で返済・X1/X2は反対まで保持')
    for solo in [0,1]:
        for mode in [0,1,2]:
            a=arguments([0,5,6,11],[100]*4,own=[1,1,-1,-1])
            a += [a[7],a[26],a[27],a[28]]
            cfg=dict(config,model=0,exit_model=0,entry_gate=0,exit_mode=mode,solo=solo)
            result=run(list(pdca.arguments(cfg,key,data_from(a),5)))
            assert len(result[1])==1
    records.append('反対成立時は全出口定義が返済し、単独対照も同じ判断時計')
    for cut in range(1,len(base[0])):
        edited=data_from(base)
        for field in ['states_self','states_peer']:
            edited[2][key][field][:,cut:]*=-1
        for field in ['valid_self','valid_peer']:
            edited[2][key][field][:,cut:]=~edited[2][key][field][:,cut:]
        modified=pdca.arguments(config,key,edited,5)
        for column in [7,26,27,28,32,33,34,35]:
            np.testing.assert_array_equal(modified[column][:cut],args[column][:cut])
    records.append('未来の双方状態と有効性改変は過去の入口出口配列へ影響しない')
    result=dict(合格=True,独立条件照合=records,未来改変地点=6,単独出口比較=12,
        pdca_SHA256=study.digest(WORK/'pdca.py'),engine_SHA256=study.digest(WORK/'engine.py'))
    (HERE/'改修の入口出口分離と単独対照人工監査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
