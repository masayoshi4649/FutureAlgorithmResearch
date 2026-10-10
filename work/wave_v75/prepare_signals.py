"""二市場の入力だけから共同候補と対照候補を作り、取引損益を見ずに件数を確認する。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import pickle
import socket

import signals


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def load(path: Path) -> object:
    """機能: 保存入力を読み取り専用で読み込む。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix=='.pkl' else json.loads(path.read_text(encoding='utf8'))


def material() -> tuple[dict,dict,dict,dict]:
    """機能: 旧結果でなく、同じ原本から抽出した両市場の価格・板を接続する。

    引数: なし。返り値: 価格、板、共通同期、参照metadata(tuple[dict,...])。
    """
    metadata=load(ROOT/'work/wave_v74/inputs/refmetadata.json')
    sources=[]
    for kind in ('ready','features'):
        merged={}
        for name in metadata['input_paths'][kind]:
            current=load(ROOT/name)
            assert not set(merged)&set(current)
            merged.update(current)
        sources.append(merged)
    return sources[0],sources[1],load(HERE/'inputs/sync_fresh30.pkl'),metadata


def deny(*args: object,**kwargs: object) -> None:
    """機能: 入口検証中の通信を禁止する。

    引数: args(tuple)、kwargs(dict)。返り値: なし(None)、例外を送出する。
    """
    raise RuntimeError('保存入力だけから計算します')


def main() -> None:
    """機能: 指定遅延の全入口根拠と、結果を使わない入力件数を保存する。

    引数: --delay(int)。返り値: なし(None)。API・売買損益は参照しない。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--delay',type=int,default=5)
    args=parser.parse_args()
    assert args.delay in (1,5,15,60)
    socket.socket.connect=deny
    socket.create_connection=deny
    out=HERE/'prepared'
    out.mkdir(parents=True,exist_ok=True)
    target=out/f'signals_delay{args.delay}.pkl'
    assert not target.exists(),'生成済みの入口は上書きしません'
    ready,books,sync,meta=material()
    candidates=signals.build(ready,books,sync,args.delay,30)
    target.write_bytes(pickle.dumps(candidates,protocol=pickle.HIGHEST_PROTOCOL))
    counts=[]
    for ident,accounts in candidates.items():
        for symbol in signals.SYMBOLS:
            pairs=[(key,a) for key,a in accounts.items() if key[1]==symbol]
            counts.append(dict(入口=ident,銘柄=symbol,候補数=sum(len(a['candidates']) for _,a in pairs),
                発火数=sum(int((a['pulse']!=0).sum()) for _,a in pairs),
                活動場数=sum(len(a['candidates'])>0 for _,a in pairs),
                有効状態点数=sum(int(a['valid'].sum()) for _,a in pairs)))
    data=dict(遅延秒=args.delay,鮮度上限秒=30,場数=len(sync),口座数=len(ready),損益参照=False,
        候補会計=counts,signal_SHA256=hashlib.sha256(target.read_bytes()).hexdigest(),
        signals_code_SHA256=hashlib.sha256((HERE/'signals.py').read_bytes()).hexdigest(),API取得=0,実注文=0)
    (out/f'入口件数_delay{args.delay}.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(data,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
