"""損益を参照せず、固定済み即時板入力の過去不変性と観測範囲を検査する。"""

import copy
import json
from pathlib import Path

import numpy as np

import core
import prepare


HERE=Path(__file__).resolve().parent


def assert_equal(left: object,right: object) -> int:
    """機能: 入れ子の特徴配列を欠損込みで厳密に照合する。

    引数: left/right(dict又はndarray)。返り値: 照合した配列数(int)。
    """
    if isinstance(left,dict):
        assert left.keys()==right.keys()
        return sum(assert_equal(left[key],right[key]) for key in left)
    np.testing.assert_array_equal(left,right)
    return 1


def slice_arrays(value: dict,cut: int) -> dict:
    """機能: 準備系列の将来側を除いた独立の入力辞書を作る。

    引数: value(dict)、cut(int)。返り値: 過去部分だけのdict。
    """
    return {k:v[:cut] if isinstance(v,np.ndarray) and v.ndim else v for k,v in value.items()}


def snapshot_fixture() -> dict:
    """機能: 表示数量の偏り、鏡像、欠損処理を人工板で検査する。

    引数: なし。返り値: 人工検査の要約(dict)。
    """
    raw={}
    for depth in range(1,11):
        raw[f'Buy{depth}']={'Price':101.-depth,'Qty':30.}
        raw[f'Sell{depth}']={'Price':100.+depth,'Qty':10.}
    value=core.snapshot_values(raw,1.)
    assert value['valid'] and value['microprice']==100.75
    np.testing.assert_allclose([value['best_imbalance'],value['depth_imbalance']],[.5,.5])
    np.testing.assert_allclose(value['weighted_bid_qty'],30*sum(1/d for d in range(1,11)))
    mirror={}
    for depth in range(1,11):
        mirror[f'Buy{depth}']={'Price':201.-raw[f'Sell{depth}']['Price'],'Qty':raw[f'Sell{depth}']['Qty']}
        mirror[f'Sell{depth}']={'Price':201.-raw[f'Buy{depth}']['Price'],'Qty':raw[f'Buy{depth}']['Qty']}
    other=core.snapshot_values(mirror,1.)
    for field in ('best_imbalance','depth_imbalance','micro_offset_ticks'):
        np.testing.assert_allclose(other[field],-value[field])
    broken=copy.deepcopy(raw);broken['Buy2']['Price']=raw['Buy1']['Price']
    assert not core.snapshot_values(broken,1.)['valid']
    broken=copy.deepcopy(raw);del broken['Sell10']
    assert not core.snapshot_values(broken,1.)['valid']
    broken=copy.deepcopy(raw);broken['Buy3']['Qty']=-1.
    assert not core.snapshot_values(broken,1.)['valid']
    broken=copy.deepcopy(raw);broken['Buy1']['Qty']=0.
    assert not core.snapshot_values(broken,1.)['valid']
    broken=copy.deepcopy(raw);broken['Buy3']['Qty']=0.
    assert core.snapshot_values(broken,1.)['valid']
    return dict(厚い買板のmicroは売板寄り=True,距離重み式=True,左右鏡像=True,
        価格逆転欠損負数量最良数量ゼロ拒否=True,遠方数量ゼロ許可=True)


def asof_fixture() -> dict:
    """機能: 同時計先頭、厳密過去、相手停止の扱いを人工時系列で検査する。

    引数: なし。返り値: 同期検査の要約(dict)。
    """
    times=np.array([10.,10.,20.,20.,40.]);valid=np.array([True,True,False,True,True])
    reset=np.zeros(5,bool)
    indices,ages=core.asof_indices(np.array([10.,11.,20.,21.,40.,41.,80.]),times,valid,reset,30.)
    np.testing.assert_array_equal(indices,[-1,0,0,-1,-1,4,-1])
    assert np.isnan(ages[[0,3,4,6]]).all()
    missing=core.empty_market(7,(5,15,30,60))
    assert (missing['current']['index']==-1).all() and not missing['current']['valid'].any()
    for window in missing['windows'].values():
        assert not window['valid'].any() and not window['zero_ofi_denominator'].any()
    return dict(同時刻後続行による不正救済なし=True,同時刻は参照しない=True,鮮度超過拒否=True,欠測は中立ではない=True)


def window_fixture() -> dict:
    """機能: 同一行、ゼロ分母、不正区間、イベント件数を人工窓で検査する。

    引数: なし。返り値: 窓検査の要約(dict)。
    """
    ready={'time_s':np.array([0.,10.,20.,30.,40.]),'tick':1.}
    book={'valid':np.ones(5,bool),'reset':np.zeros(5,bool),'bid':np.full(5,100.),
          'ask':np.full(5,101.),'mid':np.full(5,100.5),'best_ofi':np.zeros(5)}
    snapshot={field:np.zeros(5) for field in core.SNAPSHOT_FIELDS};snapshot['valid']=np.ones(5,bool)
    same=core.market_features(np.array([16.]),1,ready,book,snapshot,(2,))['windows'][2]
    assert same['same_row'][0] and not same['source_valid'][0] and not same['valid'][0]
    zero=core.market_features(np.array([32.]),1,ready,book,snapshot,(20,))['windows'][20]
    assert zero['source_valid'][0] and zero['zero_ofi_denominator'][0] and not zero['valid'][0]
    book['best_ofi']=np.array([0.,5.,-2.,3.,0.])
    flow=core.market_features(np.array([42.]),1,ready,book,snapshot,(40,))['windows'][40]
    assert flow['valid'][0] and flow['nonzero_ofi_count'][0]==3
    assert flow['ofi_sum'][0]==6 and flow['ofi_abs_sum'][0]==10 and flow['ofi_ratio'][0]==.6
    book['reset'][2]=True
    broken=core.market_features(np.array([42.]),1,ready,book,snapshot,(40,))['windows'][40]
    assert broken['reset_or_invalid_cross'][0] and not broken['source_valid'][0]
    book['reset'][2]=False;book['best_ofi'][2]=np.nan
    missing=core.market_features(np.array([42.]),1,ready,book,snapshot,(40,))['windows'][40]
    assert missing['source_valid'][0] and missing['missing_ofi'][0] and not missing['valid'][0]
    return dict(同一行は無効=True,ゼロ分母は未知=True,三非ゼロイベント計数=True,
        途中reset拒否=True,OFI欠損と証拠不足を区別=True)


def real_prefix(ready: dict,books: dict,snapshots: dict) -> dict:
    """機能: 全口座で未来切断と未来側改変が過去の特徴を変えないか検査する。

    引数: ready/books/snapshots(dict)。返り値: 口座別照合証跡と件数(dict)。
    同時計の先頭を切断位置にし、参照期限が切断時刻以下の判断だけを対象とする。
    """
    rows=[];count=0
    for key,r in sorted(ready.items()):
        times=r['time_s'];cut=int(np.searchsorted(times,times[len(times)//2],side='left'))
        cutoff=times[cut];b=books[key];s=snapshots[key]
        rshort=slice_arrays(r,cut);bshort=slice_arrays(b,cut);sshort=slice_arrays(s,cut)
        bchanged={k:v.copy() if isinstance(v,np.ndarray) else v for k,v in b.items()}
        schanged={k:v.copy() if isinstance(v,np.ndarray) else v for k,v in s.items()}
        for k in ('bid','ask','mid','best_ofi'):
            bchanged[k][cut:]=np.nan
        bchanged['valid'][cut:]=False;bchanged['reset'][cut:]=True
        for k in core.SNAPSHOT_FIELDS:schanged[k][cut:]=np.nan
        schanged['valid'][cut:]=False
        cases=0;points=0
        for delay in (1,5,15):
            grid=np.arange(r['start']+300,r['limit']-60.+1e-6,5.)
            grid=grid[grid-delay<=cutoff]
            baseline=core.market_features(grid,delay,r,b,s)
            cases+=assert_equal(baseline,core.market_features(grid,delay,rshort,bshort,sshort))
            cases+=assert_equal(baseline,core.market_features(grid,delay,r,bchanged,schanged))
            points+=len(grid)
        count+=cases
        rows.append(dict(session=key[0],symbol=key[1],cut_i=cut,cut_time=float(cutoff),
            判定点=points,厳密一致配列=cases,未来切断不変=True,未来価格板OFI不正改変不変=True))
    return dict(accounts=len(rows),rows=rows,厳密一致配列数=count)


def elapsed_statistics(grids: dict) -> list[dict]:
    """機能: 予定窓と実参照時計差の分布を全場から集計する。

    引数: grids(dict)。返り値: 遅延・窓・銘柄別の観測分布(list[dict])。
    損益を集計せず、双方の始終点が有効な判断に限定する。
    """
    rows=[]
    for delay,records in grids.items():
        for window in (5,15,30,60):
            for symbol in ('TOPIX','NK225'):
                values=[]
                for record in records.values():
                    markets=record['markets'];a=markets['TOPIX']['windows'][window];b=markets['NK225']['windows'][window]
                    clean=a['source_valid']&b['source_valid']
                    values.append(markets[symbol]['windows'][window]['actual_seconds'][clean])
                combined=np.concatenate(values)
                rows.append(dict(delay=delay,window=window,symbol=symbol,n=len(combined),
                    quantile=[float(x) for x in np.quantile(combined,[0,.05,.5,.95,1])],
                    想定窓と同秒=int((combined==window).sum())))
    return rows


def main() -> None:
    """機能: 固定入力の検査だけを実行し、担当領域へ証跡を保存する。

    引数: なし。返り値: なし(None)。旧入力・原本・特徴生成コードは編集しない。
    """
    ready,books=prepare.base_material();snapshots=prepare.load(HERE/'snapshots.pkl')
    evidence=dict(人工snapshot=snapshot_fixture(),人工同期=asof_fixture(),人工窓=window_fixture(),
        原本全口座の過去不変性=real_prefix(ready,books,snapshots),
        限定='代理時計上の前方参照を検査。実受信時刻がないため実時間因果を証明したものではない。',
        API取得=0,実注文=0,損益閲覧=0)
    del ready,books,snapshots
    evidence['実窓長分布']=elapsed_statistics(prepare.load(HERE/'grids.pkl'))
    evidence['固定ファイルSHA256']={n:prepare.digest(HERE/n) for n in ('core.py','prepare.py','snapshots.pkl','grids.pkl')}
    prepare.save('固定入力の因果検査.json',evidence)
    print(json.dumps({k:v for k,v in evidence.items() if k not in ('原本全口座の過去不変性','実窓長分布')},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
