"""短期支持の窓・元行・公開行・他市場の厳密過去対応を保存素材から独立確認する。"""

import hashlib
import pickle
import numpy as np
from diagnose import ROOT,HERE,save
from boundaries import module

ROUND=ROOT/'work/wave_v87/round3'


def main():
    """
    機能: 全60口座の30秒支持値を独立再計算し、将来イベント削除後も同じ特徴か確認する。
    引数: なし。
    返り値: None。売買・損益を再生しない。
    """
    path=ROUND/'prepared/short.pkl'
    data=pickle.loads(path.read_bytes())
    prepare=module('監査87短期入力85',ROOT/'work/wave_v85/prepare.py')
    signals=module('監査87短期特徴',ROUND/'signals.py')
    inputs,_,_=prepare.load_inputs(verify=False);records=[]
    for key,ready in sorted(inputs.items()):
        model=data['events'][key];actual=data['expanded'][key]
        peer=(key[0],'TOPIX' if key[1]=='NK225' else 'NK225');other=data['events'][peer]
        prior=np.searchsorted(model['release'],model['release']-30.,side='right')-1
        assert np.array_equal(prior,model['prior_event'])
        ix=np.searchsorted(ready['seq'],model['seq'],side='right')-1
        atr=np.where(ix>=0,ready['atr'][np.maximum(ix,0)],np.nan)
        np.testing.assert_array_equal(atr,model['atr'])
        value=np.full(len(prior),np.nan);ok=prior>=0
        ok &= np.isfinite(atr)&(atr>0)&np.isfinite(model['mid'])&(model['mid']>0)
        ok &= np.isfinite(model['mid'][np.maximum(prior,0)])&(model['mid'][np.maximum(prior,0)]>0)
        value[ok]=(model['mid'][ok]-model['mid'][prior[ok]])/atr[ok]
        np.testing.assert_array_equal(value,model['value']);np.testing.assert_array_equal(ok,model['valid'])
        assert np.all(model['source_seq']<model['seq'])
        assert np.all(model['source_time']<=model['release'])
        selected=actual['self_release_seq']>=0
        assert np.all(actual['self_release_seq'][selected]<=ready['seq'][selected])
        selected=actual['peer_release_seq']>=0
        assert np.all(actual['peer_release_time'][selected]<ready['time_s'][selected])
        # ----------------------------------------
        # 未来の公開イベント自体を削除してから再対応させる。
        comparisons=0
        for count in (max(2,len(ready['last'])//3),max(2,len(ready['last'])*2//3)):
            shortened={name:v[:count] if isinstance(v,np.ndarray) and len(v)==len(ready['last']) else v for name,v in ready.items()}
            ownmask=model['seq']<=shortened['seq'][-1]
            peermask=other['release']<shortened['time_s'][-1]
            assert np.any(ownmask) and np.any(peermask)
            own={name:v[ownmask] for name,v in model.items()}
            foreign={name:v[peermask] for name,v in other.items()}
            obtained=signals.expand(shortened,own,foreign)
            for name,value in actual.items():
                np.testing.assert_array_equal(obtained[name],value[:count],err_msg=str((key,count,name)))
                comparisons+=1
        records.append(dict(セッション=key[0],商品=key[1],公開イベント数=len(model['seq']),
            原本行数=len(ready['last']),支持値とATR独立一致=True,相手厳密過去=True,
            未来イベント削除地点数=2,配列一致数=comparisons))
    save('最新支持特徴の独立公開順と未来イベント切断.json',dict(全合格=True,口座数=len(records),
        公開イベント数=sum(r['公開イベント数'] for r in records),
        原本行数=sum(r['原本行数'] for r in records),
        未来イベント削除地点数=sum(r['未来イベント削除地点数'] for r in records),
        配列一致数=sum(r['配列一致数'] for r in records),検査=records,
        入力SHA256=hashlib.sha256(path.read_bytes()).hexdigest(),
        注記='30秒は保存特徴の公開時刻を基準とした窓であり、真の受信時計の30秒とは断定しない。新しい遅延・鮮度閾値をここで追加していない。'))
    print('全60口座の特徴値・公開順・未来イベント切断一致',flush=True)


if __name__=='__main__':
    main()
