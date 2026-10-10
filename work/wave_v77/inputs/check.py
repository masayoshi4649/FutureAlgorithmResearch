"""損益なしで、価格窓の未来不変性と現在行を除くレンジ境界を検査する。"""

from pathlib import Path

import numpy as np

import core
import prepare


HERE=Path(__file__).resolve().parent


def equal(a: object,b: object) -> int:
    """機能: 入れ子の特徴を欠損込みで厳密照合する。

    引数: a/b(dict又はndarray)。返り値: 照合した配列数(int)。
    """
    if isinstance(a,dict):
        assert a.keys()==b.keys()
        return sum(equal(a[k],b[k]) for k in a)
    np.testing.assert_array_equal(a,b)
    return 1


def clipped(a: dict,cut: int) -> dict:
    """機能: 将来部分を除いた系列を作る。

    引数: a(dict)、cut(int)。返り値: 切断した入力(dict)。
    """
    return {k:v[:cut] if isinstance(v,np.ndarray) and v.ndim else v for k,v in a.items()}


def fixture() -> dict:
    """機能: 同秒後続と現在先頭を、効率と過去レンジへ混入させないか検査する。

    引数: なし。返り値: 人工検査結果(dict)。
    """
    times=np.repeat(np.arange(0.,1201.,10.),2);n=len(times)
    mid=100.+np.repeat(np.arange(n//2,dtype=float),2)
    mid[1::2]=10000.
    r={'time_s':times,'tick':1.}
    b=dict(bid=mid-.5,ask=mid+.5,mid=mid,last=mid,valid=np.ones(n,bool),reset=np.zeros(n,bool),best_ofi=np.ones(n))
    s={k:np.zeros(n) for k in core.LEGACY.SNAPSHOT_FIELDS};s['valid']=np.ones(n,bool)
    value=core.market_features(np.array([1006.]),5,r,b,s)
    current=value['current']['index'][0]
    assert current==200 and value['current']['mid'][0]==200.
    for w in core.WINDOWS:
        a=value['windows'][w]
        assert a['source_valid'][0] and a['efficiency'][0]==1.
    assert value['ranges'][60]['high'][0]==199. and value['ranges'][60]['low'][0]==194.
    assert value['ranges'][60]['position'][0]>1.
    s['valid'][current]=False
    separate=core.market_features(np.array([1006.]),5,r,b,s)
    assert separate['current']['valid'][0] and not separate['current']['q_valid'][0]
    assert separate['windows'][300]['source_valid'][0] and not separate['flow'][30]['source_valid'][0]
    b['reset'][current-10]=True
    broken=core.market_features(np.array([1006.]),5,r,b,s)
    assert not broken['windows'][300]['source_valid'][0] and not broken['ranges'][180]['source_valid'][0]
    b['reset'][:]=False;b['mid'][:]=100.
    flat=core.market_features(np.array([1006.]),5,r,b,s)
    assert flat['windows'][300]['zero_variation'][0] and np.isnan(flat['windows'][300]['efficiency'][0])
    assert flat['ranges'][60]['source_valid'][0] and not flat['ranges'][60]['position_valid'][0]
    return dict(同時計後続をTVとレンジから除外=True,現在先頭を過去レンジから除外=True,
        値幅外の位置を保持=True,価格とQとF可用性を区別=True,途中reset拒否=True,ゼロ総変動と値幅ゼロは不明=True)


def oracle(output: dict,r: dict,b: dict) -> int:
    """機能: 直接過去配列を切り出して総変動と高安を独立検算する。

    引数: output/r/b(dict)。返り値: 検算した特徴件数(int)。
    同時計先頭の行を独立に列挙し、現在先頭も後続もレンジへ含めない。
    """
    times=r['time_s'];first=np.array([i for i,t in enumerate(times) if i==0 or t!=times[i-1]])
    count=0
    for w,a in output['windows'].items():
        good=np.flatnonzero(a['source_valid'])
        for p in good[np.unique(np.linspace(0,len(good)-1,min(5,len(good))).astype(int))] if len(good) else []:
            old,now=int(a['old'][p]),int(a['now'][p]);prices=b['mid'][first[(first>=old)&(first<=now)]]
            variation=float(sum(abs(float(y)-float(x)) for x,y in zip(prices[:-1],prices[1:])))
            np.testing.assert_allclose(a['total_variation'][p],variation,rtol=1e-12,atol=1e-9)
            if variation>0:np.testing.assert_allclose(a['efficiency'][p],abs(prices[-1]-prices[0])/variation,rtol=1e-12,atol=1e-9)
            count+=1
    for w,a in output['ranges'].items():
        good=np.flatnonzero(a['source_valid'])
        for p in good[np.unique(np.linspace(0,len(good)-1,min(5,len(good))).astype(int))] if len(good) else []:
            old,now=int(a['old'][p]),int(a['now'][p]);prices=b['mid'][first[(first>=old)&(first<now)]]
            assert a['high'][p]==max(prices) and a['low'][p]==min(prices) and a['unique_observations'][p]==len(prices)
            assert a['last_time'][p]<times[now]
            count+=1
    return count


def main() -> None:
    """機能: 全60口座で途中切断・未来側改変と直接算式照合を行う。

    引数: なし。返り値: なし(None)。旧原本・結果を参照せず担当領域に証跡保存。
    """
    evidence=dict(人工検査=fixture(),accounts=[],API取得=0,実注文=0,損益閲覧=0)
    ready,books,snapshots=prepare.base_material();array_count=oracle_count=0
    for key,r in sorted(ready.items()):
        b,s=books[key],snapshots[key];t=r['time_s'];cut=int(np.searchsorted(t,t[len(t)//2],side='left'))
        cutoff=t[cut];rs,bs,ss=clipped(r,cut),clipped(b,cut),clipped(s,cut)
        bc={k:v.copy() if isinstance(v,np.ndarray) else v for k,v in b.items()}
        sc={k:v.copy() if isinstance(v,np.ndarray) else v for k,v in s.items()}
        for name in ('bid','ask','mid','best_ofi'):bc[name][cut:]=np.nan
        bc['valid'][cut:]=False;bc['reset'][cut:]=True
        for name in core.LEGACY.SNAPSHOT_FIELDS:sc[name][cut:]=np.nan
        sc['valid'][cut:]=False
        arrays=checks=0
        for delay in prepare.DELAYS:
            grid=np.arange(r['start']+300.,r['limit']-60.+1e-6,5.)
            grid=grid[grid-delay<=cutoff]
            base=core.market_features(grid,delay,r,b,s)
            arrays+=equal(base,core.market_features(grid,delay,rs,bs,ss))
            arrays+=equal(base,core.market_features(grid,delay,r,bc,sc))
            checks+=oracle(base,r,b)
        array_count+=arrays;oracle_count+=checks
        evidence['accounts'].append(dict(session=key[0],symbol=key[1],cut_i=cut,cut_time=float(cutoff),
            配列厳密一致数=arrays,直接検算数=checks,途中切断不変=True,未来価格板OFI改変不変=True))
    evidence.update(口座数=len(ready),配列厳密一致総数=array_count,直接検算総数=oracle_count,
        限定='代理時計上の前方参照禁止の検査。共通受信時計がないため実受信順の因果証明ではない。',
        code_hashes={n:prepare.digest(HERE/n) for n in ('core.py','prepare.py','check.py')})
    prepare.save('価格窓と直前レンジの因果検査.json',evidence)
    print(f'全{len(ready)}口座、{array_count}配列の過去不変・{oracle_count}特徴直接算式一致',flush=True)


if __name__=='__main__':
    main()
