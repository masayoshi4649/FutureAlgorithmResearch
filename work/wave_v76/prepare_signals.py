"""新しい板特徴から二市場の入口・継続確認を、損益を参照せず保存する。"""

import argparse
import hashlib
import json
from pathlib import Path
import pickle
import socket

import numpy as np

import signals


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def deny(*args,**kwargs):
    """機能: 保存データでの研究中は外部接続を拒否する。

    引数: 任意の位置/名前引数(tuple/dict)。返り値: なし。常にRuntimeError。
    """
    raise RuntimeError('この再生は保存データ専用です')


def main() -> None:
    """機能: 三遅延の状態・確認・イベントを保存する。

    引数: --delay(int:1/5/15)。返り値: なし(None)。保存済み入口を上書きしない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--delay',type=int,default=5);args=parser.parse_args()
    assert args.delay in (1,5,15)
    socket.socket.connect=deny;socket.create_connection=deny
    folder=HERE/'prepared';folder.mkdir(exist_ok=True)
    target=folder/f'signals_delay{args.delay}.pkl';assert not target.exists()
    grids=pickle.loads((HERE/'inputs/grids.pkl').read_bytes())
    value=signals.build(grids[args.delay])
    target.write_bytes(pickle.dumps(value,protocol=5))
    rows=[]
    for ident,sessions in value.items():
        for session,a in sessions.items():
            rows.append(dict(条件=ident,セッション=session,格子数=len(a['grid']),有効数=int(a['valid'].sum()),
                買合意=int((a['strong']==1).sum()),売合意=int((a['strong']==-1).sum()),
                不一致=int(a['disagreement'].sum()),瞬時入口数=int(np.count_nonzero(a['entry'][0])),
                十秒確認入口数=int(np.count_nonzero(a['entry'][10]))))
    proof=dict(損益参照=False,遅延=args.delay,信号条件数=16,セッション数=29,集計=rows,
        signals_SHA256=hashlib.sha256((HERE/'signals.py').read_bytes()).hexdigest(),
        入力SHA256=hashlib.sha256((HERE/'inputs/grids.pkl').read_bytes()).hexdigest(),
        保存SHA256=hashlib.sha256(target.read_bytes()).hexdigest(),API取得=0,実注文=0)
    (folder/f'入口状態_delay{args.delay}.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf8')
    print(f'遅延{args.delay}秒の16条件・29場の状態を保存しました',flush=True)


if __name__=='__main__':
    main()
