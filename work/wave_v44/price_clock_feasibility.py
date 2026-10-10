"""次の入口仮説のため、価格移動量だけを測る。新しい売買は再生しない。"""

from __future__ import annotations

import pickle

import numpy as np

import runner

HERE = runner.HERE


def inspect() -> dict:
    """機能: セッション先頭20分の校正可能性と、その後の価格時計速度を集計する。

    引数: なし。返り値: 全26入力の価格変動診断(dict)。新戦略の損益は参照しない。
    """
    path=HERE.parent/'wave_v23/inputs.pkl'
    fixed=runner.read(HERE/'探索条件の固定.json')
    assert runner.digest(path)==fixed['参照資料SHA256'][path.relative_to(runner.ROOT).as_posix()]
    inputs=pickle.loads(path.read_bytes()); rows=[]
    for key,ready in sorted(inputs.items()):
        price=np.asarray(ready['last']); atr=np.asarray(ready['atr']); time=np.asarray(ready['time_s'])
        valid=(np.isfinite(price[1:]) & np.isfinite(price[:-1]) & (price[1:]>0) & (price[:-1]>0) &
               np.isfinite(atr[:-1]) & (atr[:-1]>0))
        distance=np.zeros(len(price)); distance[1:][valid]=np.abs(np.diff(price)[valid])/atr[:-1][valid]
        valid_rows=np.r_[False,valid]
        changes=np.r_[False,(np.diff(price)!=0)&valid]
        seconds=np.r_[0.,np.diff(time)]
        elapsed=time-ready['start']; first=(elapsed>=0)&(elapsed<1200)
        rate=float(distance[first].sum()/20)
        bands=[]
        for left in range(0,int(max(elapsed[-1],0))+1,1800):
            mask=(elapsed>=left)&(elapsed<left+1800)
            if not mask.any(): continue
            minutes=min(1800,max(0,float(elapsed[-1]-left)))/60
            if minutes<=0:continue
            current=float(distance[mask].sum()/minutes)
            bands.append(dict(開始後分=left/60,実時間分=minutes,観測行数=int(mask.sum()),
                ATR価格の有効隣接区間数=int((mask&valid_rows).sum()),
                有効隣接区間秒=float(seconds[mask&valid_rows].sum()),
                有効価格変更数=int(changes[mask].sum()),
                ATR距離毎分=current,先頭20分比=None if rate<=0 else current/rate))
        rows.append(dict(session=key[0],symbol=key[1],原本行数=len(price),価格変更数=int(changes.sum()),
            先頭20分観測数=int(first.sum()),先頭20分ATR距離毎分=rate,距離分子が正=bool(rate>0),
            先頭20分有効隣接区間秒=float(seconds[first&valid_rows].sum()),
            先頭20分有効価格変更数=int(changes[first].sum()),
            最初のATR価格有効区間の開始後秒=float(elapsed[np.flatnonzero(valid_rows)[0]]) if valid_rows.any() else None,
            全有効隣接区間の同価格割合=float(1-changes.sum()/max(1,valid_rows.sum())),三十分区間=bands))
    result=dict(全入力数=len(rows),結果=rows,全先頭距離分子正=all(r['距離分子が正'] for r in rows),
        新実相場損益=False,新売買=False,将来値での校正=False,
        説明='未実装の入力診断。速度分母は固定20分で、有効ATR区間秒ではない。分子正を校正品質合格とは呼ばない。後半の集計は記述だけで規則へ戻さない。ATRは価格差の一行前。',
        入力SHA256=runner.digest(path),実装SHA256=runner.digest(HERE/'price_clock_feasibility.py'))
    runner.save(HERE/'価格時計の入力診断.json',result)
    return result


if __name__=='__main__':
    result=inspect()
    print(f"{result['全入力数']}入力の価格距離と有効区間を診断。新売買なし。",flush=True)
