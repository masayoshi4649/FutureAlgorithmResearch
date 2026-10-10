"""既知の450条件を再探索せず、銘柄別首位の偶然性を仮定付きで診断する。"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np


HERE=Path(__file__).resolve().parent
PRIOR=HERE.parent/'wave_v61'
sys.path.insert(0,str(PRIOR))
from analyze import load, accounts, aggregate

CANDIDATES=(('D4_H30_W20_A1','TOPIX'),('D3_H120_W20_A2','NK225'))
REPEATS=20000


def save(name: str, value: dict) -> None:
    """機能: 診断仕様と計算結果を日本語UTF-8のJSONに保存する。

    引数: name(str)、value(dict)。返り値: なし(None)。
    """
    (HERE/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def digest(path: Path) -> str:
    """機能: 入力結果と実装のSHA256を求める。

    引数: path(Path)。返り値: SHA256(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def indices(rng: np.random.Generator, count: int, days: int, length: int) -> np.ndarray:
    """機能: 連続日を確率的に継続する定常ブートストラップ添字を作る。

    引数: rng(Generator)、count/days/length(int)。返り値: 日添字(ndarray)。
    同じ添字を全条件・全銘柄へ適用し、日内と横断の関連を残す。
    """
    out=np.empty((count,days),dtype=np.int64)
    out[:,0]=rng.integers(days,size=count)
    for k in range(1,days):
        start=rng.random(count)<1/length
        out[:,k]=np.where(start,rng.integers(days,size=count),(out[:,k-1]+1)%days)
    return out


def diagnose(matrix: np.ndarray, selected: list[int], length: int, seed: int) -> dict:
    """機能: 中心化した平均と900系列最大値を共通ブロック再抽出で比較する。

    引数: matrix(ndarray、日×条件銘柄)、selected(list[int])、length/seed(int)。
    返り値: 仮定付き片側診断と選択未補正の平均区間(dict)。
    分母は原標本の標準偏差に固定し、t分布の確率とは解釈しない。
    """
    n=matrix.shape[0]
    mean=matrix.mean(axis=0)
    deviation=matrix.std(axis=0,ddof=1)
    valid=deviation>1e-10
    assert all(valid[i] for i in selected)
    scale=np.where(valid,np.sqrt(n)/np.maximum(deviation,1e-10),0)
    observed=mean*scale
    rng=np.random.default_rng(seed)
    null_selected=[]
    null_max=[]
    sample_selected=[]
    for begin in range(0,REPEATS,500):
        ix=indices(rng,min(500,REPEATS-begin),n,length)
        sampled=matrix[ix].mean(axis=1)
        centered=(sampled-mean)*scale
        null_selected.append(centered[:,selected])
        null_max.append(centered[:,valid].max(axis=1))
        sample_selected.append(sampled[:,selected])
    null_selected=np.concatenate(null_selected)
    null_max=np.concatenate(null_max)
    sample_selected=np.concatenate(sample_selected)
    output=[]
    for offset,column in enumerate(selected):
        low,high=np.quantile(sample_selected[:,offset],[.025,.975])
        raw=(1+np.count_nonzero(null_selected[:,offset]>=observed[column]))/(REPEATS+1)
        adjusted=(1+np.count_nonzero(null_max>=observed[column]))/(REPEATS+1)
        assert adjusted>=raw
        output.append(dict(候補列=column,平均日収支=float(mean[column]),
            平均日収支の基本法95区間=[float(2*mean[column]-high),float(2*mean[column]-low)],
            単独片側参考p=float(raw),全900系列最大値調整参考p=float(adjusted),標準化観測値=float(observed[column])))
    return dict(日数=n,平均ブロック日数=length,反復数=REPEATS,seed=seed,
        変動あり系列数=int(valid.sum()),候補=output)


def main() -> None:
    """機能: 元の売買条件を変更せず、日集計・集中度・再標本化診断を作る。

    引数: なし。返り値: なし(None)。APIアクセス・追加売買探索はない。
    """
    HERE.mkdir(exist_ok=True)
    target=HERE/'診断仕様.json'
    if target.exists():
        raise RuntimeError('固定済みです。成績に合わせて診断を再固定しません。')
    sources={str(PRIOR/b/'集計結果.json'):digest(PRIOR/b/'集計結果.json') for b in ('directional','inventory')}
    save('診断仕様.json',dict(固定時刻=datetime.now(timezone.utc).isoformat(),入力SHA=sources,
        実装SHA=digest(Path(__file__)),候補=CANDIDATES,反復数=REPEATS,ブロック日数=[1,2,4],
        対象='主気配450条件×2銘柄。日付ラベルのDay/Nightをまとめる。最後のDayのみの日を除く感度も計算。',
        限界='全データと首位は既知。統計設計も事後。過去の全探索は900系列に含まれず、独立検証や偶然でない証明とは呼ばない。'))
    methods=load('directional')+load('inventory')
    sessions=sorted(a['session'] for a in accounts(methods[0],'TOPIX'))
    dates=sorted({s[:10] for s in sessions})
    complete=[d for d in dates if sum(s.startswith(d) for s in sessions)==2]
    series=[(m['id'],symbol) for m in methods for symbol in ('TOPIX','NK225')]
    matrix=np.zeros((len(dates),len(series)))
    detail=[]
    for column,(method_id,symbol) in enumerate(series):
        method=next(m for m in methods if m['id']==method_id)
        aa=accounts(method,symbol)
        for a in aa:
            matrix[dates.index(a['session'][:10]),column]+=a['net']
        if (method_id,symbol) in CANDIDATES:
            weeks=sorted({a['week'] for a in aa})
            values=aggregate(aa)
            detail.append(dict(条件ID=method_id,銘柄=symbol,列=column,集計=values,
                週=[dict(週=w,収支=sum(a['net'] for a in aa if a['week']==w)) for w in weeks],
                最大黒字日除外=float(matrix[:,column].sum()-max(0,matrix[:,column].max())),
                日=[dict(日=d,収支=float(matrix[k,column])) for k,d in enumerate(dates)]))
    assert len(dates)==13 and len(complete)==12 and len(series)==900
    np.savez_compressed(HERE/'日別損益行列.npz',matrix=matrix,dates=np.array(dates),series=np.array(series))
    chosen=[series.index(c) for c in CANDIDATES]
    results=[]
    for label,positions in (('13日・25場',list(range(len(dates)))),('12日・24場', [dates.index(d) for d in complete])):
        for length in (1,2,4):
            result=diagnose(matrix[positions],chosen,length,20261008+length+len(positions)*100)
            result['対象']=label
            results.append(result)
    save('偶然性の診断.json',dict(候補=detail,再標本化=results,日数=len(dates),系列数=len(series),入力SHA=sources,
        結論='有限の既知標本による仮定付き補助診断であり、将来収益・偶然でないことの証明ではない。'))
    print(json.dumps(dict(候補=detail,再標本化=results),ensure_ascii=False))


if __name__=='__main__':
    main()
