"""旧監査済み板ブロックを照合し、保存済み追加場だけを同じ仕様で拡張する。"""

from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OLD=HERE.parent/'wave_v52'/'measurement'
BASE=HERE.parent/'wave_v60'


def digest(path: Path) -> str:
    """機能: 既知入力と原本の同一性を照合するSHAを求める。

    引数: path(Path)。返り値: SHA256(str)。
    """
    h=hashlib.sha256()
    with path.open('rb') as f:
        while chunk:=f.read(4*1024*1024):
            h.update(chunk)
    return h.hexdigest()


def extract_one(args: tuple) -> tuple:
    """機能: 追加保存場の板だけを監査済み旧抽出器で順方向に処理する。

    引数: args(tuple:場キー、入力dict)。返り値: 場キー・特徴表・監査(tuple)。
    旧抽出器のATR出力欄は互換性のためゼロを注入し、売買には使わない。
    """
    key,ready=args
    spec=importlib.util.spec_from_file_location('fixed_board_extract',OLD/'extract.py')
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    compatible=dict(ready,atr=np.zeros(len(ready['seq'])))
    frame,audit=module.extract(ROOT/'book'/key[1]/f'{key[0]}.jsonl',compatible)
    frame['atr']=0.
    return key,frame,audit


def main() -> None:
    """機能: 50口座の1秒公開板を原本と時刻・行番号で照合して保存する。

    引数: なし。返り値: なし(None)。原本編集・APIアクセスはしない。
    """
    HERE.mkdir(exist_ok=True)
    target=HERE/'board_features.pkl'
    assert not target.exists(),'板特徴は既に作成済みです'
    inputs=pickle.loads((BASE/'inputs.pkl').read_bytes())
    quotes=pickle.loads((BASE/'quotes.pkl').read_bytes())
    source_prices=pickle.loads((HERE.parent/'wave_v59'/'inputs.pkl').read_bytes())
    source_prices.update(pickle.loads((HERE.parent/'wave_v59'/'holdout'/'inputs.pkl').read_bytes()))
    board=pickle.loads((OLD/'features.pkl').read_bytes())
    old_audit=json.loads((OLD/'監査.json').read_text(encoding='utf-8'))
    hashes={(Path(a['原本']).stem,Path(a['原本']).parent.name):a['原本SHA256'] for a in old_audit['原本別']}
    existing=[]
    for key in sorted(board):
        assert key in inputs
        expected=hashes[key]
        assert digest(ROOT/'book'/key[1]/f'{key[0]}.jsonl')==expected
        existing.append(dict(セッション=key[0],銘柄=key[1],原本SHA=expected,再抽出=False))
    missing=sorted(set(inputs)-set(board))
    for key in missing:
        assert np.array_equal(inputs[key]['seq'],source_prices[key]['seq'])
        assert np.array_equal(inputs[key]['time_s'],source_prices[key]['time_s'])
        inputs[key]=dict(inputs[key],last=source_prices[key]['last'])
    print(f'原本照合済み{len(existing)}口座・追加抽出{len(missing)}口座',flush=True)
    with ProcessPoolExecutor(max_workers=4) as pool:
        for key,frame,audit in pool.map(extract_one,[(k,inputs[k]) for k in missing]):
            board[key]=frame
            existing.append(dict(セッション=key[0],銘柄=key[1],原本SHA=audit['原本SHA256'],再抽出=True,旧抽出監査=audit))
            print(f'{key}: {len(frame):,}公開板ブロック',flush=True)
    audits=[]
    for key in sorted(inputs):
        ready,frame=inputs[key],board[key]
        q=quotes[key]
        indices=np.searchsorted(ready['seq'],frame['seq'].to_numpy())
        assert np.array_equal(ready['seq'][indices],frame['seq'])
        assert np.array_equal(ready['time_s'][indices],frame['time_s'])
        assert np.array_equal(q['bid'][indices],frame['bid'])
        assert np.array_equal(q['ask'][indices],frame['ask'])
        assert (frame['source_last_seq']<frame['seq']).all()
        assert (frame['source_time_s']<frame['time_s']).all()
        frame['atr']=0.
        audits.append(dict(セッション=key[0],銘柄=key[1],公開ブロック数=len(frame),公開元行は過去=True,公開板と共通気配一致=True))
    assert len(board)==len(inputs)==50
    target.write_bytes(pickle.dumps(board,protocol=pickle.HIGHEST_PROTOCOL))
    manifest=dict(作成時刻=datetime.now(timezone.utc).isoformat(),合格=True,現在API取得=0,
        ATR参照=False,既知50口座=True,公開定義='CurrentPriceTimeが進んだ最初の行で、直前時刻の集計だけを公開。板の受信時刻とは別。',
        抽出器SHA=digest(OLD/'extract.py'),旧特徴SHA=digest(OLD/'features.pkl'),出力SHA=digest(target),
        原本=existing,口座別=audits)
    (HERE/'板特徴の照合.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('全50口座の板特徴と元気配が一致',flush=True)


if __name__=='__main__':
    main()
