"""producerの正常執行逆写像をsourceと合成配列だけで確認する。"""

import hashlib
import json
from pathlib import Path

import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUTPUT=HERE/'正常執行行はboolでない逆写像というSOURCE_ONLY確認.json'


def validate(inverse: np.ndarray, mapping: np.ndarray) -> None:
    """
    機能: 原行から正常行への逆写像と正常行から原行への写像を相互照合する。
    引数: inverse(ndarray[int32,N])、mapping(ndarray[int64,M]) はproducerの二配列。
    返り値: None。未対応−1と正常行番号0をbool判定しない。
    """
    assert inverse.ndim==mapping.ndim==1
    assert inverse.dtype==np.int32 and mapping.dtype==np.int64
    n,m=len(inverse),len(mapping)
    assert np.all((mapping>=0)&(mapping<n)) and len(np.unique(mapping))==m
    assert np.all((inverse==-1)|((inverse>=0)&(inverse<m)))
    assert np.count_nonzero(inverse>=0)==m
    np.testing.assert_array_equal(inverse[mapping],np.arange(m,dtype=np.int32))
    assert not len(mapping) or np.all(np.diff(mapping)>0)
    np.testing.assert_array_equal(np.flatnonzero(inverse>=0),mapping)


def main() -> None:
    """
    機能: 型・正常0番・未対応−1・空写像・異常写像の純人工を保存する。
    引数: なし。
    返り値: None。producer source以外の原入力・NPZ・cache・金融を読まない。
    """
    assert not OUTPUT.exists()
    producer=[ROOT/'work/wave_v103/input/core.py',ROOT/'work/wave_v104/holdout_input/core.py']
    source={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in producer}
    checks=0
    for n in range(8):
        for bits in range(1<<n):
            mapping=np.asarray([i for i in range(n) if bits&(1<<i)],np.int64)
            inverse=np.full(n,-1,np.int32);inverse[mapping]=np.arange(len(mapping),dtype=np.int32)
            validate(inverse,mapping);checks+=1
            if len(mapping):
                assert np.count_nonzero(inverse)==n-1;checks+=1
                wrong=inverse.copy();wrong[mapping[0]]=-1
                try:
                    validate(wrong,mapping)
                except AssertionError:
                    checks+=1
                else:
                    raise AssertionError('正常行0の欠落を受理')
    inverse=np.array([0,1,-1,-1,2],np.int32);mapping=np.array([0,1,4],np.int64)
    bads=[(inverse.astype(bool),mapping),(inverse,np.array([0,1,1],np.int64)),
          (inverse,np.array([0,1,5],np.int64)),(inverse,np.array([1,0,4],np.int64)),
          (np.array([0,1,0,-1,2],np.int32),mapping),(np.array([0,1,-2,-1,2],np.int32),mapping)]
    for a,b in bads:
        try:
            validate(a,b)
        except AssertionError:
            checks+=1
        else:
            raise AssertionError('不正な写像を受理')
    proof=dict(全合格=True,source_SHA256=source,検査sourceSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        比較数=checks,実NPZ=0,原板=0,cache=0,金融=0,API=0,
        生成定義='int32[N]を−1で初期化し、indexes上へarange(M)を代入。map=int64[M]のindexes。',
        生成箇所={'103':'input/core.py214–223','104':'holdout_input/core.py286–291'},
        正しい拘束=['mapは範囲内一意・原行順','inv値は−1又は[0,M)','inv[map]==arange(M)',
                    'count_nonzero(inv>=0)==M','flatnonzero(inv>=0)==map'],
        不正拘束='flatnonzero(inv)は未対応−1を採用、正常0番を除外する。M>0なら非零数はN−1。',
        合成例=dict(inverse=inverse.tolist(),mapping=mapping.tolist(),誤ったflatnonzero=np.flatnonzero(inverse).tolist()),
        修正範囲='runnerの入力validateのみ。経済/測定engine及びproducer不変更。',
        限界='実NPZの値を再確認した証拠ではなくproducer定義と合成配列のSOURCE_ONLY確認。')
    OUTPUT.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,比較数=checks,SHA256=hashlib.sha256(OUTPUT.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':
    main()
