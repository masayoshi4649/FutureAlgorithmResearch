"""追加ナイトを保存原本だけで準備し、旧13セッションと区別する。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import socket
import sys

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SESSION = '2026-09-29_Night'
SYMBOLS = ('TOPIX','NK225')


def module(name: str, path: Path):
    """機能: 旧実装を変更せず独立名で読み込む。

    引数: name(str)、path(Path)。返り値: モジュール(object)。
    """
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);sys.modules[name]=value
    spec.loader.exec_module(value)
    return value


def digest(path: Path) -> str:
    """機能: 大きな原本も分割して指紋を得る。

    引数: path(Path)。返り値: SHA256(str)。
    """
    result=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):result.update(block)
    return result.hexdigest()


def save(path: Path, value: object) -> None:
    """機能: 新47の領域だけへ日本語JSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')


def reject_network(*args, **kwargs):
    """機能: 保存データの再生中の外部接続を拒否する。

    引数: 任意の接続引数。返り値: なし(None)。常に例外を送出する。
    """
    raise RuntimeError('今回の調査は保存原本だけを使用します')


def freeze() -> dict:
    """機能: 新しい損益を見る前に既存五方式と新旧原本を固定する。

    引数: なし。返り値: 条件・指紋・既読境界(dict)。
    """
    path=HERE/'追加ナイト照合の固定.json'
    if path.exists():return json.loads(path.read_text(encoding='utf-8'))
    previous=json.loads((HERE.parent/'wave_v45/探索条件の固定.json').read_text(encoding='utf-8'))
    ids=('A0__V000','G000_F25_N1__V000','G150_F25_N1__V000',
         'G150_F50_N1__V000','G000_F50_N1__V000')
    specs={s['id']:s for s in previous['conditions']}
    selected=[specs[i] for i in ids]
    old=json.loads((HERE.parent/'wave_v23/入力確認.json').read_text(encoding='utf-8'))['原本SHA256']
    paths=[ROOT/name for name in old]
    paths += [ROOT/folder/symbol/(SESSION+suffix) for folder,suffix in
              (('book','.jsonl'),('candle_1min','.csv'),('candle_5min','.csv')) for symbol in SYMBOLS]
    with ThreadPoolExecutor(max_workers=4) as pool:
        fingerprints=dict(zip([p.relative_to(ROOT).as_posix() for p in paths],pool.map(digest,paths)))
    assert len(old)==78 and len(fingerprints)==84
    assert all(fingerprints[name]==sha for name,sha in old.items()),'旧原本も変更されています'
    record=json.loads((HERE.parent/'wave_v27/live/一回取得開始.json').read_text(encoding='utf-8'))
    result=dict(既存固定五方式=selected,対象=SESSION,旧セッション数=13,追加セッション数=1,
        原本SHA256=fingerprints,旧原本78不変=True,以前の既読締切=record['共通締切'],
        位置付け='21時までは過去の一回照合で既読。追加ナイト全体を完全未見とは呼ばず、その後の拡張を区別する。',
        新方式選抜に使わない=True,新損益確認前=True,現在API追加取得数=0,
        固定仕様元SHA256=digest(HERE.parent/'wave_v45/探索条件の固定.json'))
    save(path,result)
    return result


def extract_one(symbol: str) -> tuple:
    """機能: 一銘柄の全原本行と公開済み板特徴を既存抽出器で作る。

    引数: symbol(str)。返り値: 特徴表と監査(tuple)。売買は計算しない。
    """
    reference=module('v47_data_reference_'+symbol,HERE.parent/'wave_v16/reference.py')
    extractor=module('v47_raw_'+symbol,HERE.parent/'wave_v8/raw_features.py')
    depth=module('v47_depth_'+symbol,HERE.parent/'wave_v23/depth_features.py')
    path=ROOT/'book'/symbol/(SESSION+'.jsonl');quotes=[]
    frame,extraction=extractor.extract_features(path,symbol,SESSION,quotes=quotes)
    extractor.write_features(frame,extraction,HERE/'features',quotes=quotes)
    audit,raw=reference.previous.data.scan_book(path,collect_prices=True)
    tape_path=HERE/'features'/f'約定系列_{symbol}_{SESSION}.npz'
    tape=dict(np.load(tape_path,allow_pickle=False));indices=tape['seq'].astype(int)
    tape['last']=raw['last'][indices];tape['volume']=raw['volume'][indices]
    tape['current_price']=tape['last'].copy()
    np.savez_compressed(tape_path,**tape)
    features,depth_audit=depth.extract(path,symbol,SESSION,frame)
    candle=reference.previous.data.candle_consistency(SESSION,symbol,raw)
    return features,dict(銘柄=symbol,原本=audit,抽出=extraction,追加板特徴=depth_audit,足一致=candle)


def main() -> None:
    """機能: 追加二入力を準備し、旧26入力との統合は新しいファイルだけに保存する。

    引数: なし。返り値: なし(None)。旧の入力・特徴・API保存物は編集しない。
    """
    HERE.mkdir(exist_ok=True);fixed=freeze()
    socket.socket.connect=reject_network;socket.create_connection=reject_network
    features,audits={},[]
    # ----------------------------------------
    # 旧モジュールの一部に共有キャッシュがあるため抽出は銘柄順で行う。
    for symbol in SYMBOLS:
        features[(SESSION,symbol)],audit=extract_one(symbol);audits.append(audit)
        print(symbol+' 新ナイト入力抽出完了',flush=True)
    reference=module('v47_prepared_reference',HERE.parent/'wave_v16/reference.py')
    reference.previous.OUT=HERE
    inputs=reference.previous.build_inputs([SESSION],roots={SESSION:(ROOT,HERE/'features')})
    assert len(inputs)==len(features)==2
    coverage=[]
    cutoff=datetime.fromisoformat(fixed['以前の既読締切']).timestamp()
    for key,ready in inputs.items():
        assert ready['time_s'][-1]>ready['limit']
        assert np.all(np.diff(ready['seq'])>0) and np.all(np.diff(ready['time_s'])>=0)
        coverage.append(dict(session=key[0],symbol=key[1],原本行数=len(ready['seq']),
            既読締切以前の行数=int(np.sum(ready['time_s']<cutoff)),
            追加時刻の行数=int(np.sum(ready['time_s']>=cutoff)),
            最終時刻=float(ready['time_s'][-1]),場内返済期限=float(ready['limit'])))
    for name,value in (('new_inputs.pkl',inputs),('new_features_depth.pkl',features)):
        (HERE/name).write_bytes(pickle.dumps(value,pickle.HIGHEST_PROTOCOL))
    old_inputs=pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    old_features=pickle.loads((HERE.parent/'wave_v23/features_depth.pkl').read_bytes())
    assert len(old_inputs)==len(old_features)==26 and not (set(inputs)&set(old_inputs))
    for name,value in (('inputs.pkl',dict(old_inputs,**{})|inputs),('features_depth.pkl',old_features|features)):
        assert len(value)==28
        (HERE/name).write_bytes(pickle.dumps(value,pickle.HIGHEST_PROTOCOL))
    assert all(digest(ROOT/name)==sha for name,sha in fixed['原本SHA256'].items())
    sources={}
    for value in tuple(sys.modules.values()):
        name=getattr(value,'__file__',None)
        if name:
            p=Path(name).resolve()
            if p.suffix=='.py' and p.is_relative_to(ROOT/'work'):sources[p.relative_to(ROOT).as_posix()]=digest(p)
    save(HERE/'追加ナイト入力監査.json',dict(全合格=True,対象数=2,全保存入力数=28,入力被覆=coverage,
        原本監査=audits,元原本84SHA256=fixed['原本SHA256'],実装SHA256=sources,
        出力SHA256={p.relative_to(ROOT).as_posix():digest(p) for p in
          [HERE/name for name in ('new_inputs.pkl','new_features_depth.pkl','inputs.pkl','features_depth.pkl')]},
        新売買再生=False,新損益読取=False,現在API追加取得数=0))
    print('新2入力・統合28入力の保存と原本不変確認完了',flush=True)


if __name__=='__main__':main()
