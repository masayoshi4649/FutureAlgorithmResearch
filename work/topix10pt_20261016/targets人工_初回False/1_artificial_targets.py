"""十pt採点を価格列の直走査とFractionで照合するSOURCE_ONLY人工。"""

from __future__ import annotations

from fractions import Fraction
import hashlib
import json
from pathlib import Path

import numpy as np

import targets


HERE=Path(__file__).resolve().parent
CHECKS=0
FIXTURES=0
PREFIXES=0
REJECTIONS=0
ARRAY_FIELDS=('labels','terminal_raw_row','mfe','mae','first_10_raw_row',
    'first_10_time_s','mae_before_first_10','common_lock_end')


def source_hashes() -> dict:
    """
    機能: この人工と対象二源の現在指紋を作る。
    引数: なし。
    返り値: dict[str,str]。市場入力は読まない。
    """
    return {name:hashlib.sha256((HERE/name).read_bytes()).hexdigest()
        for name in ('targets.py','artificial_targets.py')}


def fixture(values: list[float],publications: list[int] | None=None,
            raw_rows: list[int] | None=None,times: list[float] | None=None) -> tuple[dict,dict]:
    """
    機能: 合成価格だけから公開基準と採用済み原順を用意する。
    引数: values(list[float])、publications/raw_rows(list[int]|None)、times(list[float]|None)。
    返り値: tuple[dict,dict] はbars/prices。公開基準はその原行の現在値に固定。
    """
    n=len(values)
    raw=np.array(list(range(n)) if raw_rows is None else raw_rows,dtype=np.int64)
    t=np.array([60.*(i+1) for i in range(n)] if times is None else times,dtype=np.float64)
    indices=list(range(n)) if publications is None else publications
    bars=dict(anchor=np.array([values[i] for i in indices],dtype=np.float64),
        pub_raw_row=raw[indices].copy(),t_s=t[indices].copy())
    prices=dict(last=np.array(values,dtype=np.float64),raw_row_index=raw,price_time_s=t)
    return bars,prices


def oracle(bars: dict,prices: dict,complete: bool) -> dict:
    """
    機能: 木・binary searchを使わず、公開後価格を一つずつ分数算術で採点する。
    引数: bars/prices(dict)、complete(bool)。
    返り値: dict は八配列。基準値を未来価格から作り直さない。
    """
    n=len(bars['anchor']);out=dict(
        labels=np.full((n,2,3),-2,np.int8),terminal_raw_row=np.full((n,2,3),-1,np.int64),
        mfe=np.full((n,2),np.nan),mae=np.full((n,2),np.nan),
        first_10_raw_row=np.full((n,2),-1,np.int64),first_10_time_s=np.full((n,2),np.nan),
        mae_before_first_10=np.full((n,2),np.nan),common_lock_end=np.full(n,-1,np.int64))
    for i,(anchor,pub) in enumerate(zip(bars['anchor'],bars['pub_raw_row'])):
        if pub<0:continue
        a=Fraction(float(anchor));future=[j for j,row in enumerate(prices['raw_row_index']) if row>pub]
        last_row=int(prices['raw_row_index'][future[-1]]) if future else int(pub)
        lock=next((int(prices['raw_row_index'][j]) for j in future if abs(Fraction(float(prices['last'][j]))-a)>=10),last_row)
        out['common_lock_end'][i]=lock
        for side_index,side in enumerate((1,-1)):
            scores=[side*(Fraction(float(prices['last'][j]))-a) for j in future]
            if scores:
                out['mfe'][i,side_index]=float(max(scores));out['mae'][i,side_index]=float(min(scores))
            ten=next((k for k,score in enumerate(scores) if score>=10),None)
            if ten is not None:
                j=future[ten];out['first_10_raw_row'][i,side_index]=prices['raw_row_index'][j]
                out['first_10_time_s'][i,side_index]=prices['price_time_s'][j]
                if ten:out['mae_before_first_10'][i,side_index]=float(min(scores[:ten]))
            for risk_index,risk in enumerate((Fraction(5,2),Fraction(5),Fraction(10))):
                label=0 if complete else 2;at=last_row
                for j,score in zip(future,scores):
                    if score>=10:label=1;at=int(prices['raw_row_index'][j]);break
                    if score<=-risk:label=-1;at=int(prices['raw_row_index'][j]);break
                out['labels'][i,side_index,risk_index]=label;out['terminal_raw_row'][i,side_index,risk_index]=at
    return out


def same(expected: np.ndarray,actual: np.ndarray) -> None:
    """
    機能: dtype・shape・NaNを含め、合成の全値を厳密照合する。
    引数: expected/actual(ndarray)。
    返り値: None。比較項目数を増やす。
    """
    global CHECKS
    assert expected.dtype==actual.dtype and expected.shape==actual.shape
    np.testing.assert_allclose(actual,expected,rtol=0,atol=0,equal_nan=True)
    CHECKS+=expected.size


def inspect(bars: dict,prices: dict,complete: bool=False) -> dict:
    """
    機能: 木の結果を別直走査と照合し、入力配列の不変更も確認する。
    引数: bars/prices(dict)、complete(bool)。
    返り値: dict は対象measureの結果。
    """
    global FIXTURES,CHECKS
    before={(name,key):(value.dtype,value.shape,value.tobytes()) for name,data in (('bars',bars),('prices',prices))
        for key,value in data.items() if isinstance(value,np.ndarray)}
    expected=oracle(bars,prices,complete);actual=targets.measure(bars,prices,complete)
    for name in ARRAY_FIELDS:same(expected[name],actual[name])
    assert actual['sides'].tolist()==[1,-1] and actual['adverse_points'].tolist()==[2.5,5.,10.]
    assert actual['favorable_points']==10. and actual['window_complete'] is complete
    assert actual['counts']==dict(基準数=len(bars['anchor']),公開基準あり=int(np.sum(bars['pub_raw_row']>=0)),
        公開基準なし=int(np.sum(bars['pub_raw_row']<0)),採用済み価格数=len(prices['last']))
    after={(name,key):(value.dtype,value.shape,value.tobytes()) for name,data in (('bars',bars),('prices',prices))
        for key,value in data.items() if isinstance(value,np.ndarray)}
    assert before==after
    CHECKS+=6;FIXTURES+=1
    return actual


def hand_cases() -> None:
    """
    機能: 等号・純future・原行間引き・空・窓末・正のMAE等の手計算境界を検査する。
    引数: なし。
    返り値: None。
    """
    b,p=fixture([100.,97.5,95.,90.,110.],[0])
    r=inspect(b,p)
    assert r['labels'][0,0].tolist()==[-1,-1,-1] and r['terminal_raw_row'][0,0].tolist()==[1,2,3]
    assert r['first_10_raw_row'][0].tolist()==[4,3] and r['mae_before_first_10'][0].tolist()==[-10.,2.5]
    assert r['common_lock_end'][0]==3
    b,p=fixture([100.,102.5,105.,110.],[0]);r=inspect(b,p,True)
    assert r['mae'][0].tolist()==[2.5,-10.] and r['mfe'][0].tolist()==[10.,-2.5]
    assert r['mae_before_first_10'][0,0]==2.5 and np.isnan(r['mae_before_first_10'][0,1])
    b,p=fixture([100.,110.,90.],[0],raw_rows=[4,9,99],times=[60.,60.,60.]);r=inspect(b,p)
    assert r['first_10_raw_row'][0].tolist()==[9,99] and r['first_10_time_s'][0].tolist()==[60.,60.]
    assert np.isnan(r['mae_before_first_10'][0,0]) and r['common_lock_end'][0]==9
    b,p=fixture([100.],[0],raw_rows=[17]);r=inspect(b,p)
    assert np.all(r['labels']==2) and np.all(r['terminal_raw_row']==17) and np.isnan(r['mfe']).all()
    assert r['common_lock_end'].tolist()==[17]
    assert np.all(inspect(b,p,True)['labels']==0)
    b,p=fixture([],[]);inspect(b,p)
    b=dict(anchor=np.array([np.nan]),pub_raw_row=np.array([-1],np.int64),t_s=np.array([60.]))
    p=dict(last=np.array([],np.float64),raw_row_index=np.array([],np.int64),price_time_s=np.array([],np.float64))
    r=inspect(b,p,True);assert np.all(r['labels']==-2) and r['common_lock_end'][0]==-1
    b,p=fixture([100.,112.5,87.5],[0]);inspect(b,p)
    b,p=fixture([100.,100.,101.,99.],[0]);inspect(b,p)
    b,p=fixture([100.,100.],[1]);inspect(b,p)
    # OHLCは追加の列があっても採点基準に使わず、未来の高安を見ない。
    original=inspect(b,p)
    b['high']=np.array([999999.]);b['low']=np.array([-999999.])
    changed=inspect(b,p)
    for name in ARRAY_FIELDS:same(original[name],changed[name])
    # 複数の空minuteが一つの後続観測で公開される場合の同一pubを許す。
    b,p=fixture([100.,102.,110.],[1]);b={key:np.repeat(value,2) for key,value in b.items()}
    b['t_s']=np.array([60.,120.]);inspect(b,p)


def reflected_cases() -> None:
    """
    機能: 価格鏡映で買売を入れ替えた全八配列が一致することを確認する。
    引数: なし。
    返り値: None。
    """
    generator=np.random.default_rng(11810)
    for case in range(40):
        values=100.+np.cumsum(generator.integers(-32,33,size=65))/4
        b,p=fixture(values.tolist(),list(range(0,65,4)))
        r=inspect(b,p,bool(case%2))
        rb={key:value.copy() for key,value in b.items()};rp={key:value.copy() for key,value in p.items()}
        rb['anchor']=1000.-rb['anchor'];rp['last']=1000.-rp['last']
        mirror=inspect(rb,rp,bool(case%2))
        for name in ARRAY_FIELDS:
            expected=r[name] if name=='common_lock_end' else r[name][:,::-1]
            same(expected,mirror[name])


def prefix_cases() -> None:
    """
    機能: 各採用原順prefixで直走査一致と解決済み初到達の後続不変を確認する。
    引数: なし。
    返り値: None。未解決labelと全終端MFEは後続追加で変わり得る。
    """
    global PREFIXES,CHECKS
    values=[100.,101.,97.5,103.,110.,109.,112.,106.,99.,96.,90.,94.,100.,110.,115.]
    b,p=fixture(values)
    full=inspect(b,p)
    for cut in range(1,len(values)+1):
        pb={key:value[:cut].copy() for key,value in b.items()}
        pp={key:value[:cut].copy() for key,value in p.items()}
        current=inspect(pb,pp)
        for i in range(cut):
            for side in range(2):
                for risk in range(3):
                    label=int(current['labels'][i,side,risk])
                    if label in (-1,1):
                        assert full['labels'][i,side,risk]==label
                        assert full['terminal_raw_row'][i,side,risk]==current['terminal_raw_row'][i,side,risk]
                        CHECKS+=2
                if current['first_10_raw_row'][i,side]>=0:
                    for name in ('first_10_raw_row','first_10_time_s','mae_before_first_10'):
                        same(current[name][i:i+1,side:side+1],full[name][i:i+1,side:side+1])
            if current['common_lock_end'][i]<p['raw_row_index'][cut-1]:
                assert current['common_lock_end'][i]==full['common_lock_end'][i];CHECKS+=1
        PREFIXES+=1
    # 公開後だけを極端に改変すると結果は変わるが、基準と公開以前を再計算しない。
    b,p=fixture([100.,100.,100.,100.],[1])
    before=inspect(b,p)
    p['last'][2:]=[112.,87.]
    after=inspect(b,p)
    assert np.all(before['labels']==2) and np.any(after['labels']!=2)
    assert b['anchor'].tolist()==[100.] and b['pub_raw_row'].tolist()==[1]


def reject_cases() -> None:
    """
    機能: 不整合公開基準・価格順・非有限・dtype・時刻等を受理しないことを確認する。
    引数: なし。
    返り値: None。
    """
    global REJECTIONS
    changes=[
        ('bars','anchor',np.array([np.inf,101.,110.])),
        ('bars','anchor',np.array([np.nan,101.,110.])),
        ('bars','anchor',np.array([99.,101.,110.])),
        ('bars','pub_raw_row',np.array([0,1,9],np.int64)),
        ('bars','pub_raw_row',np.array([0.,1.,2.])),
        ('bars','t_s',np.array([60.,60.,180.])),
        ('bars','t_s',np.array([61.,120.,180.])),
        ('bars','t_s',np.array([60.,np.nan,180.])),
        ('prices','raw_row_index',np.array([0,1,1],np.int64)),
        ('prices','raw_row_index',np.array([0,2,1],np.int64)),
        ('prices','raw_row_index',np.array([-1,1,2],np.int64)),
        ('prices','raw_row_index',np.array([0,1,2],np.int32)),
        ('prices','last',np.array([100.,np.nan,110.])),
        ('prices','last',np.array([100.,np.inf,110.])),
        ('prices','last',np.array([100.,0.,110.])),
        ('prices','price_time_s',np.array([60.,59.,180.])),
        ('prices','price_time_s',np.array([60.,120.,np.inf])),
    ]
    for group,name,value in changes:
        b,p=fixture([100.,101.,110.]);target=b if group=='bars' else p;target[name]=value
        try:targets.measure(b,p,False)
        except AssertionError:REJECTIONS+=1
        else:raise AssertionError('不整合を受理: '+group+'/'+name)
    b,p=fixture([100.,101.],[0])
    try:targets.measure(b,p,1)
    except AssertionError:REJECTIONS+=1
    else:raise AssertionError('bool以外の窓資格を受理')


def main() -> None:
    """
    機能: 実入力なしの全人工を実行し、source指紋と件数を保存する。
    引数: なし。
    返り値: None。所有二源以外を変更せず、実測・金融は呼び出さない。
    """
    start=source_hashes()
    hand_cases();reflected_cases();prefix_cases();reject_cases()
    assert source_hashes()==start
    value=dict(全合格=True,source_SHA256=start,比較項目=CHECKS,合成素材=FIXTURES,接頭数=PREFIXES,
        不整合拒否=REJECTIONS,金融=0,実本文=0,原NPZ=0,event入力=0,API=0,
        範囲='最大最小木とFractionの価格直走査。純future/公開現在値/±方向/三逆行幅/等号/原順/同時計後行/鏡映/接頭/未知/空/入力不変更。',
        留保='MFE/MAEは全観測終端まで。解決済み初到達だけ後続追加で不変で、未解決labelと極値は変化し得る。観測価格先着であり金融会計ではない。')
    path=HERE/'十ポイント先着と公開基準及び純future極値の人工検査.json'
    assert not path.exists();path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(value,ensure_ascii=False))


if __name__=='__main__':
    try:main()
    except BaseException as error:
        archive=HERE/'targets人工_初回False';archive.mkdir(exist_ok=True)
        number=len(list(archive.glob('*.json')))+1
        for name in ('targets.py','artificial_targets.py'):
            (archive/(str(number)+'_'+name)).write_bytes((HERE/name).read_bytes())
        failure=dict(全合格=False,例外型=type(error).__name__,例外=str(error),source_SHA256=source_hashes(),
            比較項目=CHECKS,合成素材=FIXTURES,金融=0,実本文=0)
        (archive/(str(number)+'_False.json')).write_text(json.dumps(failure,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise
