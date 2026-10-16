"""学習と追加場適用を人工数列だけで検査する。"""

import hashlib
import json
from pathlib import Path

import numpy as np

import learner


def main() -> None:
    """
    機能: 方向反転・定数列・外挿・学習固定・状態再公開を確認する。
    引数: なし。
    返り値: None。原価格・金融を読まず人工証跡を保存する。
    """
    here=Path(__file__).resolve().parent
    rng=np.random.default_rng(118)
    x=rng.normal(size=(500,4));x[:,3]=7
    y=(x[:,0]-.5*x[:,1]+rng.normal(size=500)*.3>0).astype(float)
    before=x.copy();weight=np.ones(500)
    model=learner.fit(x,y,weight)
    p=learner.predict(model,x)
    assert np.mean((p>=.5)==y)>.85 and 3 not in model['active']
    np.testing.assert_array_equal(x,before)
    mirror=learner.fit(x,1-y,weight)
    np.testing.assert_allclose(learner.predict(mirror,x),1-p,atol=1e-7)
    fixed=json.dumps(model,ensure_ascii=False,allow_nan=False)
    extended=np.vstack((x,x*1000))
    np.testing.assert_allclose(learner.predict(model,extended)[:len(x)],p)
    assert json.dumps(model,ensure_ascii=False,allow_nan=False)==fixed
    constant=learner.fit(np.ones((10,3)),np.array([0.,1.]*5),np.ones(10))
    np.testing.assert_allclose(learner.predict(constant,np.ones((5,3))),.5)
    one=learner.fit(x,np.ones(500),weight)
    assert (learner.predict(one,x)>.99).all()
    long=np.array([.4,.7,.8,.6,.4,.7,.2,.1])
    short=np.array([.3,.2,.1,.2,.3,.1,.7,.8])
    eligible=np.ones(8,bool)
    result=learner.publications(long,short,eligible,.55)
    np.testing.assert_array_equal(result,[0,1,0,0,0,1,-1,0])
    for n in range(1,9):
        np.testing.assert_array_equal(learner.publications(long[:n],short[:n],eligible[:n],.55),result[:n])
    target=here/'学習と固定適用の人工検証.json'
    assert not target.exists()
    target.write_text(json.dumps(dict(全合格=True,source_SHA256={name:hashlib.sha256((here/name).read_bytes()).hexdigest()
        for name in ('learner.py','artificial_learner.py')},人工行=500,接頭=8,実本文=0,金融=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('学習・反転・固定適用・再公開の人工検査合格。実本文0。')


if __name__=='__main__':main()
