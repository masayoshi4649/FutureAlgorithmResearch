"""実注文と管理判断の前後を切断し、未来の価格や相手市場を変えても過去が不変か検査する。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json

import numba
import numpy as np

from full_accounts import HERE, study
from independent_account import save


def cut_args(args: tuple, count: int) -> tuple:
    """機能: 既知場末時刻を変えず、原本列と共同格子を切断する。

    引数: args(tuple)、count(int)。返り値: 切断引数(tuple)。
    """
    end=int(np.searchsorted(args[7],args[0][count-1],side='right'));out=list(args)
    for i in range(7):out[i]=args[i][:count].copy()
    for i in (*range(7,14),*range(21,25)):out[i]=args[i][:end].copy()
    assert not np.any(out[6]>=end)
    return tuple(out)


def future_args(args: tuple, count: int, mode: int) -> tuple:
    """機能: 未来の自市場気配又は共同状態を敵対改変する。

    引数: args(tuple)、count/mode(int)。返り値: 改変引数(tuple)。
    """
    out=list(args)
    if mode==0:
        for i in range(1,7):out[i]=args[i].copy()
        tail=len(args[0])-count;level=args[14]*(1000.+70.*(np.arange(tail)%17))
        out[1][count:]=level;out[2][count:]=level+args[14];out[3][count:]=False
        out[4][count:]=True;out[5][count:]=np.where(np.arange(tail)%2,-1,1);out[6][count:]=-1
    else:
        end=int(np.searchsorted(args[7],args[0][count-1],side='right'))
        for i in (*range(8,14),*range(21,25)):out[i]=args[i].copy()
        out[8][end:]=False;out[9][end:]*=-1
        for i in range(10,14):out[i][end:]=True
        out[21][end:]=False;out[22][end:]*=-1;out[23][end:]+=100000;out[24][end:]+=100000
    return tuple(out)


def compare(actual: tuple, full: tuple, count: int) -> int:
    """機能: 確定済み全注文・明細・清算時価・管理判断の全配列一致を要求する。

    引数: actual/full(tuple)、count(int)。返り値: 比較配列数(int)。
    """
    pairs=((actual[0][actual[0][:,0]<count],full[0][full[0][:,0]<count]),
        (actual[1][actual[1][:,2]<count],full[1][full[1][:,2]<count]),
        (actual[2][:count],full[2][:count]),
        (actual[4][actual[4][:,0]<count],full[4][full[4][:,0]<count]))
    for left,right in pairs:np.testing.assert_array_equal(left,right)
    return len(pairs)


def one_case(job: tuple, material: tuple, catalog: dict) -> dict:
    """機能: 一口座の管理発動と注文の前後で切断・未来改変し、保存台帳へ照合する。

    引数: job(tuple)、material(tuple)、catalog(dict)。返り値: 検査計数(dict)。
    """
    ident,key,ledger=job;args=study.arguments(catalog[ident],key,*material);full=study.engine.simulate(*args)
    for name,index in (('orders',0),('trades',1),('stats',3),('events',4)):
        np.testing.assert_array_equal(full[index],ledger[name])
    assert hashlib.sha256(full[2].tobytes()).hexdigest()==ledger['curve_hash']
    n=len(args[0]);cuts={max(1,n//2)}
    for opened in (True,False):
        for row in full[0][full[0][:,7]==opened][:1]:
            for field in (0,1):
                index=int(row[field]);cuts.update((index,index+1))
    for row in full[0][(full[0][:,7]==0)&(full[0][:,6]==6)][:1]:
        for field in (0,1):
            index=int(row[field]);cuts.update((index,index+1))
    seen={}
    for code in (20,21,22,23,24):
        records=full[4][full[4][:,2]==code];seen[str(code)]=len(records)
        if len(records):
            index=int(records[0,0]);cuts.update((index,index+1))
    cuts=sorted(i for i in cuts if 0<i<n);count=open_ends=pending=0
    for length in cuts:
        partial=study.engine.simulate(*cut_args(args,length));count+=compare(partial,full,length)
        open_ends+=int(partial[3][0]!=0);pending+=int(partial[3][1]!=0)
        for mode in (0,1):count+=compare(study.engine.simulate(*future_args(args,length,mode)),full,length)
    return dict(id=ident,session=key[0],symbol=key[1],切断地点数=len(cuts),検査数=len(cuts)*3,
        配列比較数=count,切断未返済数=open_ends,切断発注待数=pending,実管理イベント=seen)


def main() -> None:
    """機能: 全18案の最悪6口座と診断外を6並列で監査する。

    引数: なし。返り値: なし(None)。候補選定は変更しない。
    """
    numba.config.CACHE_DIR=str(HERE/'cache')
    fixed=study.load(HERE.parent/'事前固定.json');ids={c['id'] for c in fixed['条件']}
    catalog={c['id']:c for c in fixed['条件']};material=study.material(5);jobs=[]
    for ident in sorted(ids):
        ledger=study.load(HERE.parent/'ledgers'/f'{ident}.pkl')
        keys={(session,symbol) for symbol in ('TOPIX','NK225') for session in fixed['商品別赤字上位3'][symbol]}
        for symbol in ('TOPIX','NK225'):
            keys.add((fixed['対象外25'][0],symbol))
            choices=[key for key in sorted(ledger) if key[1]==symbol and np.any((ledger[key]['orders'][:,7]==0)&(ledger[key]['orders'][:,6]==6))]
            if choices:keys.add(choices[0])
        jobs.extend((ident,key,ledger[key]) for key in sorted(keys))
    rows=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures=[pool.submit(one_case,job,material,catalog) for job in jobs]
        for index,future in enumerate(as_completed(futures),1):
            rows.append(future.result())
            if index%12==0 or index==len(jobs):print(f'実管理の未来不変 {index}/{len(jobs)}',flush=True)
    rows.sort(key=lambda r:(r['id'],r['session'],r['symbol']))
    totals={name:sum(r[name] for r in rows) for name in ('切断地点数','検査数','配列比較数','切断未返済数','切断発注待数')}
    proof=dict(合格=True,条件数=len(ids),口座数=len(rows),**totals,条件=sorted(ids),口座=rows,
        engine_SHA256=study.digest(HERE.parent/'engine.py'),固定SHA256=study.digest(HERE.parent/'事前固定.json'),
        全30場は既知=True,新規の手法選定なし=True,API取得=0,実注文=0,
        限界='保存素材から作る共同信号の因果性は信号監査を併読。共通受信時刻は保存されていない。')
    save(HERE/'全18防止策の実注文未来不変監査.json',proof)
    print(json.dumps({k:v for k,v in proof.items() if k not in ('口座','条件')},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
