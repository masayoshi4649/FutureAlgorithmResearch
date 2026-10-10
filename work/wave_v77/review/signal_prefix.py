"""既往29場の三遅延で、十二入口と共同状態の未来不変性を損益に触れず検査する。"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import socket
import sys
import time

import numpy as np


sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
STUDY=HERE.parent


def module() -> object:
    """機能: 固定済み信号実装を、既存のモジュール名を上書きせず読み込む。

    引数: なし。返り値: 読み込んだsignalsモジュール(object)。実装変更や再生はしない。
    """
    name='二市場十二入口77の未来不変検査';spec=importlib.util.spec_from_file_location(name,STUDY/'signals.py')
    value=importlib.util.module_from_spec(spec);sys.modules[name]=value;spec.loader.exec_module(value);return value


SIGNALS=module()


def deny(*args: object,**kwargs: object) -> None:
    """機能: 保存信号の検査から外部通信を禁止する。

    引数: args(tuple)、kwargs(dict)。返り値: なし(None)。常に例外で停止する。
    """
    raise RuntimeError('未来不変検査では保存特徴と固定信号だけを使う')


def digest(path: Path) -> str:
    """機能: 検査した入力と実装の指紋を一定メモリーで計算する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while data:=stream.read(4*1024*1024):h.update(data)
    return h.hexdigest()


def prefix(value: object,cut: int) -> object:
    """機能: 入れ子の格子素材又は信号の、切断点より前の部分だけを返す。

    引数: value(dict/ndarray/スカラー)、cut(int)。返り値: 同じ構造の切断値(object)。
    元配列を変更せず、各特徴の未来側を計算器へ渡さない。
    """
    if isinstance(value,dict):return {k:prefix(v,cut) for k,v in value.items()}
    if isinstance(value,np.ndarray):return value[:cut]
    return value


def modified_future(value: object,cut: int,name: str='') -> object:
    """機能: 観測済み接頭部分を保ち、以後の全価格・板・OFI・参照行・品質を改変する。

    引数: value(dict/ndarray/スカラー)、cut(int)、name(str:項目名)。
    返り値: 改変された独立コピー(object)。未来格子だけ17秒遅らせ、時刻の単調性は保つ。
    """
    if isinstance(value,dict):return {k:modified_future(v,cut,str(k)) for k,v in value.items()}
    if not isinstance(value,np.ndarray):return value
    a=value.copy()
    if name=='grid':a[cut:]+=17.
    elif np.issubdtype(a.dtype,np.bool_):a[cut:]=~a[cut:]
    elif np.issubdtype(a.dtype,np.integer):a[cut:]=np.arange(len(a)-cut,dtype=a.dtype)+10_000_000
    elif np.issubdtype(a.dtype,np.floating):a[cut:]=np.where(np.isfinite(a[cut:]),-7*a[cut:]-12345.,54321.)
    else:raise AssertionError(f'想定外の配列型: {name}/{a.dtype}')
    np.testing.assert_array_equal(a[:cut],value[:cut])
    return a


def equal(a: object,b: object,path: str='') -> tuple[int,int]:
    """機能: 全出力をNaN込みで厳密照合し、比較配列数と要素数を数える。

    引数: a/b(dict又はndarray)、path(str:検査項目)。返り値: 配列数・要素数(tuple[int,int])。
    long/short許可、イベント、共通方向、反対返済確認、商品別構造線を漏らさない。
    """
    if isinstance(a,dict):
        assert a.keys()==b.keys(),path
        counts=[equal(a[k],b[k],path+'/'+str(k)) for k in a]
        return sum(x[0] for x in counts),sum(x[1] for x in counts)
    np.testing.assert_array_equal(a,b,err_msg=path)
    return 1,np.size(a)


def inspect(item: tuple) -> dict:
    """機能: 一場で保存信号一致と二地点の切断・未来改変不変性を検査する。

    引数: item(tuple:場名、素材、商品別tick、保存信号)。返り値: 場別証跡(dict)。
    損益台帳・結果JSON・追加ナイトは読まない。
    """
    session,raw,ticks,saved=item;base=SIGNALS.session_state(raw,ticks)
    original_count=equal(base,saved);n=len(raw['grid']);cuts=sorted({n//3,2*n//3})
    assert len(cuts)==2 and min(cuts)>0 and max(cuts)<n
    rows=[]
    for cut in cuts:
        expected=prefix(base,cut)
        truncated=SIGNALS.session_state(prefix(raw,cut),ticks)
        truncate_count=equal(expected,truncated)
        changed=SIGNALS.session_state(modified_future(raw,cut),ticks)
        future_count=equal(expected,prefix(changed,cut))
        rows.append(dict(切断格子数=cut,最後の既知格子=float(raw['grid'][cut-1]),最初の改変格子=float(raw['grid'][cut]),
            途中切断不変=True,未来値改変不変=True,途中切断比較配列数=truncate_count[0],
            未来改変比較配列数=future_count[0],比較要素数=truncate_count[1]+future_count[1]))
    return dict(セッション=session,格子数=n,保存信号との完全一致=True,
                保存信号比較配列数=original_count[0],保存信号比較要素数=original_count[1],切断検査=rows)


def artificial() -> dict:
    """機能: 準備破棄、期限切れ、双方の更新が必要であることを人工系列で再確認する。

    引数: なし。返り値: 四つの検査結果(dict)。価格採点や損益計算はしない。
    """
    n=50;grid=np.arange(n,dtype=float)*5
    markets={}
    for symbol in ('TOPIX','NK225'):
        markets[symbol]=dict(current=dict(valid=np.ones(n,bool),index=np.arange(n)),
            windows={300:dict(source_valid=np.ones(n,bool),ret_bp=np.full(n,4.)),
                     30:dict(source_valid=np.ones(n,bool),ret_bp=np.ones(n),bid_change_ticks=np.ones(n),ask_change_ticks=np.ones(n))})
    raw=dict(grid=grid,markets=markets)
    for m in markets.values():m['windows'][30]['ret_bp'][1:4]=-1
    event,_,_=SIGNALS.recovery_events(raw,30);assert np.flatnonzero(event).tolist()==[6]
    for m in markets.values():m['windows'][300]['ret_bp'][4]=0
    event,_,_=SIGNALS.recovery_events(raw,30);assert not np.any(event)
    for m in markets.values():
        m['windows'][300]['ret_bp'][:]=4;m['windows'][30]['ret_bp'][:]=1;m['windows'][30]['ret_bp'][1:40]=-1
    event,_,_=SIGNALS.recovery_events(raw,30);assert not np.any(event)
    for m in markets.values():
        m['windows'][30]['ret_bp'][:]=1;m['windows'][30]['ret_bp'][1:4]=-1;m['current']['index'][:]=0
    event,_,_=SIGNALS.recovery_events(raw,30);assert not np.any(event)
    return dict(反落後10秒再開で一度だけ入口=True,共通方向消失で準備破棄=True,
                同じ反落を180秒超で自動延長しない=True,双方参照更新なしでは確認不成立=True)


def main() -> None:
    """機能: 既往29場×三遅延×二地点を独立に切断・改変し、全出力一致の証跡を保存する。

    引数: CLI --workers(int:最大6)。返り値: なし(None)。公開・固定信号・原本は変更しない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=6);args=parser.parse_args()
    socket.socket.connect=deny;socket.create_connection=deny
    start=time.perf_counter();meta_path=STUDY/'inputs/metadata.json';meta=json.loads(meta_path.read_text(encoding='utf8'))
    sessions=meta['existing29'];assert len(sessions)==29 and meta['unseen_session'] not in sessions
    ticks={(r['session'],r['symbol']):r['tick'] for r in meta['rows']}
    hashes={str(meta_path.relative_to(STUDY)):digest(meta_path),'signals.py':digest(STUDY/'signals.py')}
    delay_rows=[]
    for delay in (1,5,15):
        raw_path=STUDY/f'inputs/grids_delay{delay}.pkl';saved_path=STUDY/f'prepared/signals_delay{delay}.pkl'
        raw=pickle.loads(raw_path.read_bytes());saved=pickle.loads(saved_path.read_bytes())
        todo=[(s,raw[s],{p:ticks[(s,p)] for p in ('TOPIX','NK225')},saved[s]) for s in sessions]
        with ThreadPoolExecutor(max_workers=max(1,min(6,args.workers))) as pool:rows=list(pool.map(inspect,todo))
        hashes[str(raw_path.relative_to(STUDY))]=digest(raw_path);hashes[str(saved_path.relative_to(STUDY))]=digest(saved_path)
        delay_rows.append(dict(遅延秒=delay,場数=len(rows),場別=rows))
        del raw,saved,todo
        print(f'遅延{delay}秒: 既往29場の二地点切断・未来改変が全一致',flush=True)
    array_count=sum(c['途中切断比較配列数']+c['未来改変比較配列数'] for d in delay_rows for r in d['場別'] for c in r['切断検査'])
    element_count=sum(c['比較要素数'] for d in delay_rows for r in d['場別'] for c in r['切断検査'])
    proof=dict(合格=True,検査範囲='既往29セッションのみ・遅延1/5/15秒・各場1/3と2/3地点',
        十二入口を含む=True,比較項目=['J0-J3/Q0-Q3/P0-P3の売買許可とイベント','有効性','共通方向',
            '買建玉/売建玉に対する反対合意確認','商品別の180秒安値−呼値/高値＋呼値','格子時刻'],
        切断組数=29*3*2,切断又は未来改変試験数=29*3*2*2,
        厳密比較配列総数=array_count,厳密比較要素総数=element_count,人工状態検査=artificial(),遅延別=delay_rows,
        限界='rawから格子への因果はinputs/check.pyの別証跡。この検査は固定格子素材から入口・途中判断まで。共通受信時計が無く、代理時計上の未来不参照であり実受信順の因果証明ではない。',
        損益閲覧=0,損益再生=0,追加ナイト損益再生=0,API取得=0,実注文=0,条件変更=False,
        所要秒=time.perf_counter()-start,SHA256=hashes,検査器SHA256=digest(Path(__file__)))
    (HERE/'12入口と共同状態の未来不変検査.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    print(f'合格: {array_count}配列・{element_count}要素の厳密未来不変検査',flush=True)


if __name__=='__main__':
    main()
