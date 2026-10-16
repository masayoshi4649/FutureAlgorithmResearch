"""先に固定した一paper八十実親の期待を完成coreの小bufferへ接続する。"""

import hashlib
import json
import math
from pathlib import Path
import sys
import numpy as np
from protect_state_reference import Reference, Row
from protect_source_check import execute_actual


def main() -> None:
    """
    機能: 実親/注文/UIDが紙上件数を超える動的拡張を両商品で独立確認する。
    引数: なし。既署名私有sourceと先行純80親人工だけを利用する。
    返り値: None。source/板/金融/保存入力に変更を加えない。
    """
    here=Path(__file__).resolve().parent;root=here.parents[3];engine=root/'work/e01_protect_reentry_20261014/engine'
    target=here/'一paper八十実親の完成source動的buffer独立接続.json';assert not target.exists()
    binding=json.loads((here/'現在票と十二実親出口の独立純期待及び完成14源接続_v3.json').read_text(encoding='utf-8'))
    source={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in engine.glob('*.py')}
    assert binding['全合格'] and source==binding['所有最終source_SHA256']
    sys.dont_write_bytecode=True;sys.path.insert(0,str(here/'private_protect_core'))
    import common,core,catalog
    observations=[]
    for symbol in ('TOPIX','NK225'):
        base=4000. if symbol=='TOPIX' else 65000.;tick=.5 if symbol=='TOPIX' else 10.
        def point(clock: float, shift: float=0., opposed: bool=False) -> Row:
            """
            機能: 容量人工の当時気配と明示票を作る。
            引数: clock/shift(float)、opposed(bool) は時計/移動/両反対か。
            返り値: Row は人工当行値。票数式の原相場測定とは別。
            """
            vote=dict(known=True,count=4,balance=-1 if opposed else 1)
            return Row(clock,base+shift,base+shift,base+shift+tick,True,vote,vote)
        rows=[point(0),point(300)];clock,shift=301.,0.
        for cycle in range(80):
            rows.append(point(clock,shift));clock+=1
            shift+=3*tick if cycle%2==0 else 0.
            rows.append(point(clock,shift,True));clock+=1
            rows.append(point(clock,shift));clock+=1
            if cycle<79:
                shift+=math.ceil(base*.00025/tick)*tick;rows.append(point(clock,shift));clock+=1
        rows.append(point(1000,shift))
        events={1:[dict(new=True,cid=0,side=1,q=5 if symbol=='TOPIX' else 10,price=base)]}
        ref=Reference(symbol,'BREAK','TARGET')
        for i,row in enumerate(rows):ref.step(i,row,events.get(i,[]))
        assert len(ref.parents)==80 and len(ref.orders)==160
        py=execute_actual(core,catalog,symbol,'BREAK','TARGET',rows,events,False)
        compiled=execute_actual(core,catalog,symbol,'BREAK','TARGET',rows,events,True)
        for a,b in zip(py[:8],compiled[:8]):np.testing.assert_allclose(a,b,equal_nan=True,atol=1e-5,rtol=1e-12)
        expected=np.array([[o[k] for k in ('row','source','cid','side','q','price')]+[int(o['new'])] for o in ref.orders],float)
        np.testing.assert_array_equal(py[0][:,[0,1,2,3,4,5,7]],expected)
        np.testing.assert_array_equal(py[1],[o['uid'] for o in ref.orders])
        np.testing.assert_allclose(py[2][:,1],[r['liquidation'] for r in ref.curve],atol=1e-5,rtol=1e-12)
        assert py[8]==compiled[8] and py[8]>32 and len(py[6])==80
        assert len(set(py[6][:,0]))==80 and len(set(py[6][:,13]))==80 and set(py[6][:,1])=={0.}
        assert py[2][-1,4]==py[2][-1,5]==0
        observations.append(dict(symbol=symbol,実親数=80,注文数=160,一紙上親=True,buffer容量=int(py[8]),
                                 収支=float(ref.realized),全実料=ref.paid,実CID_UID八十独立=True,全返済済=True))
    value=dict(全合格=True,最終source_SHA256=source,観測=observations,人工口座=2,配列照合=24,
               純参照source_SHA256={n:hashlib.sha256((here/n).read_bytes()).hexdigest() for n in ('protect_state_reference.py','dynamic_buffer_source_check.py')},
               scope='source初期buffer=2で試行、各一paper80actual親/160orders。票は状態専用明示人工で精度の証拠ではない。',
               金融=0,保存入力=0,台帳=0,API=0)
    target.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('動的bufferの独立接続合格 '+hashlib.sha256(target.read_bytes()).hexdigest())


if __name__=='__main__':main()
