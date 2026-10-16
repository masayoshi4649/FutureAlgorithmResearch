"""保存注文と現在値の区間演算で、入口・最初の返済条件・ドテン方向を独立検算する。"""
from accounts import load,data
from context import *


def first_hit(p: np.ndarray, start: int, stop: int, anchor: float, width: float) -> int:
    """機能: 基準から上下幅に最初に到達した行を配列計算する。

    引数: p(ndarray)、start/stop(int)、anchor/width(float)。返り値: 行番号(int)。
    """
    hit=np.flatnonzero(np.abs(p[start:stop+1]-anchor)>=width)
    assert len(hit),'新規に対応する到達なし'
    return start+int(hit[0])


def inspect(raw: tuple, saved: dict, c: dict) -> dict:
    """機能: 逐次エンジンの変数を借りず、最初の方向到達と押し戻しを求める。

    引数: raw(tuple)、saved/c(dict)。返り値: 検査件数(dict)。
    """
    t,p,bid,ask,seq,source,pok,qok,tick,start,end,limit=raw
    assert pok.all() and qok.all(),'欠測人工境界は別検査、本手順は実有効系列に限定'
    orders=saved['orders'];trades=saved['trades'];f=c['family'];w=c['width_ticks']*tick
    ew=w*[.5,1.,2.][c['variant']]
    opening={int(o[2]):o for o in orders if o[6]}
    closing={int(o[2]):o for o in orders if not o[6]}
    counts=dict(入口=0,即ドテン=0,追加反転=0,反転待ち解除=0,通常返済=0,場末返済=0)
    prior=None
    for trade in trades:
        ticket=int(trade[0]);op=opening[ticket];cl=closing[ticket]
        entry=int(op[0]);exitrow=int(cl[0]);decision=int(cl[1]);side=int(op[3])
        assert int(op[1])==entry and op[9]==t[entry]
        assert np.sum((orders[:,0]==entry)&(orders[:,6]==1))==1
        counts['入口']+=1
        # ----------------------------------------
        if prior is not None and (f==3 or (f==5 and prior[10]>0)):
            assert int(op[7])==21 and entry==int(prior[2]) and side==-int(prior[3])
            counts['即ドテン']+=1
        else:
            anchor_i=0 if prior is None else int(prior[2]);anchor=p[anchor_i]
            if f==4 and prior is not None:
                first=first_hit(p,anchor_i+1,entry,anchor,w)
                expected=-int(prior[3])
                if expected*(p[first]-anchor)>=w:
                    assert entry==first and side==expected and op[7]==22;counts['追加反転']+=1
                else:
                    anchor_i=first;anchor=p[first];counts['反転待ち解除']+=1
                    actual=first_hit(p,anchor_i+1,entry,anchor,w)
                    assert entry==actual and side==np.sign(p[entry]-anchor) and op[7]==20
            else:
                actual=first_hit(p,anchor_i+1,entry,anchor,w)
                sign=np.sign(p[entry]-anchor)*(-1 if f==0 else 1)
                assert entry==actual and side==sign and op[7]==20
        # ----------------------------------------
        # 親が行末約定する実有効系列では、子の監視は次の原本行から。
        eligible=np.arange(entry+1,exitrow+1)
        eligible=eligible[t[eligible]<limit-60.]
        progress=side*(p[eligible]-op[5])
        peak=np.maximum.accumulate(np.r_[0.,progress])[1:]
        stop=progress<=-ew
        hit=stop|((progress>=3*ew) if f<=1 else (peak-progress>=ew))
        where=np.flatnonzero(hit)
        if int(cl[7])==6:
            assert not len(where),'定時前に返済条件が成立していた'
            counts['場末返済']+=1
        else:
            assert len(where) and eligible[where[0]]==decision==exitrow,'最初の返済条件行が違う'
            expected_reason=1 if stop[where[0]] else (2 if f<=1 else 3)
            assert cl[7]==expected_reason
            counts['通常返済']+=1
        prior=trade
    return counts


def main() -> None:
    """機能: 全固定代表の通常・理論対照で判断行と極値の意味を検査する。

    引数: なし。返り値: なし(None)。
    """
    inputs=data.load_data();selection=load(WORK/'前半選定.json');totals={};byfamily={};accounts=0
    for stage in ['final/delay0','ideal_fee','supplement/final','supplement/ideal_fee']:
        names=selection['selected'] if not stage.startswith('supplement') else [p.stem for p in (WORK/stage/'results').glob('*.json')]
        for name in names:
            packet=load(WORK/stage/'results'/f'{name}.json');ledgers=load(WORK/stage/'ledgers'/f'{name}.pkl')
            for key,saved in ledgers.items():
                raw=data.as_tuple(inputs[key]);counts=inspect(raw,saved,packet['config']);accounts+=1
                for k,v in counts.items():totals[k]=totals.get(k,0)+v
                group=f'{stage}/F{packet["config"]["family"]}'
                local=byfamily.setdefault(group,{k:0 for k in counts})
                for k,v in counts.items():local[k]+=v
        print(f'独立判断照合 {stage} 完了',flush=True)
    result=dict(合格=True,口座数=accounts,検査件数=totals,家族別=byfamily,
        エンジンSHA256=digest(WORK/'engine.py'),
        手法='保存約定と原本現在値の別区間演算から、最初の入口到達・順行極値・最初の返済到達・返済後の反転方向を検算。エンジン内部の極値・状態は参照しない。')
    save('全代表の入口極値とドテン判断監査.json',result);print(json.dumps({k:v for k,v in result.items() if k!='家族別'},ensure_ascii=False))


if __name__=='__main__':main()
