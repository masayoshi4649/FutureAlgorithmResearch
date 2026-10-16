"""共通30場の固定M3方向と、旧C03品質を保持した過去観測を準備する。"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import pickle
import sys
import numpy as np
import pandas as pd

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=HERE/'prepared'
os.environ['NUMBA_CACHE_DIR']=str(HERE/'cache')


def module(name,path):
    """
    機能: 元実装を固有名で読取専用importする。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    if name in sys.modules:return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);sys.modules[name]=value;spec.loader.exec_module(value)
    return value


@contextmanager
def aliases(values):
    """
    機能: 旧import名を処理中だけ割当て、既存モジュールを復元する。
    引数: values(dict[str,module])。
    返り値: contextmanager。
    """
    saved={name:sys.modules.get(name) for name in values}
    sys.modules.update(values)
    try:yield
    finally:
        for name,value in saved.items():
            if value is None:sys.modules.pop(name,None)
            else:sys.modules[name]=value


def sha(path):
    """
    機能: ファイル内容を分割して指紋化する。
    引数: path(Path)。
    返り値: str のSHA256。
    """
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def save(path,value):
    """
    機能: 今回の素材又は証拠だけを書き出す。
    引数: path(Path)、value(dict)。
    返り値: None。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


prepare85=module('wave88_prepare85',ROOT/'work/wave_v85/prepare.py')
variants=module('wave88_legacy19_signals',ROOT/'work/wave_v19/signal_variants.py')
extract=module('wave88_legacy52_extract',ROOT/'work/wave_v52/measurement/extract.py')
observe=module('wave88_c03_observe',HERE/'c03_observe.py')
replay=module('wave88_legacy52_replay',ROOT/'work/wave_v52/replay.py')
export=module('wave88_legacy52_export',ROOT/'work/wave_v52/export.py')
analyze=module('wave88_legacy52_analyze',ROOT/'work/wave_v52/theory/analyze.py')
with aliases(dict(replay=replay,export=export,analyze=analyze)):
    backtest=module('wave88_legacy52_backtest',ROOT/'work/wave_v52/backtest.py')
import numba
numba.config.CACHE_DIR=str(HERE/'cache')


def m3_directions(inputs):
    """
    機能: 旧S00のM3だけを同じ補助関数で計算する。M2・未来収支を使わない。
    引数: inputs(dict[tuple,dict]) は両商品を含む途中切断可能な入力。
    返り値: tuple[dict,dict] の原本行方向と公開元モデル。
    """
    parameters=variants._parameters(variants.variant_specs()[0])
    models={key:variants._minute_model(ready,parameters) for key,ready in inputs.items()}
    states={}
    for key,ready in inputs.items():
        peer=key[0],'NK225' if key[1]=='TOPIX' else 'TOPIX'
        own,other=models[key],models[peer]
        checks=variants._minute_checks(ready);times=ready['time_s'][checks]
        a=variants._expand_times(own['time_s'],own['states'],times)
        b=variants._expand_times(other['time_s']+parameters['peer_delay_seconds'],other['states'],times)
        agree=np.where((a==b)&(a!=0),a,0).astype(np.int8)
        confirmed,_=variants._confirmed(agree,times,parameters['m3_confirmations'])
        states[key]=(-variants._at_rows(checks,confirmed,len(ready['seq']))).astype(np.int8)
    return states,models


def prepare(workers=4):
    """
    機能: 旧46口座の観測を照合再利用し、追加14口座だけ生板から同じ品質で生成する。
    引数: workers(int) は読取抽出の同時数。
    返り値: dict の準備証拠。売買成績は再生しない。
    """
    OUT.mkdir(parents=True,exist_ok=True)
    assert not (OUT/'源素材の固定.json').exists(),'固定済み素材を上書きしません'
    inputs,_,fingerprints=prepare85.load_inputs(verify=True)
    rawproof=json.loads((ROOT/'work/wave_v83/prepared/価格入力の照合.json').read_text(encoding='utf-8'))
    rawhash={(v['session'],v['symbol']):v['原本SHA256'] for v in rawproof['各口座']}
    fixed=json.loads((ROOT/'work/wave_v52/売買仕様固定.json').read_text(encoding='utf-8'))
    oldframes=pickle.loads((ROOT/'work/wave_v52/measurement/features.pkl').read_bytes())
    oldobs=pd.read_pickle(ROOT/'work/wave_v52/theory/観測.pkl')
    oldready=pickle.loads((ROOT/'work/wave_v67/prepared/old23/new_inputs.pkl').read_bytes())
    quality=[];observations={};frames={}
    for key,frame in sorted(oldframes.items()):
        ready=inputs[key]
        for name in ('time_s','seq','last','atr'):np.testing.assert_array_equal(ready[name],oldready[key][name])
        current,check=observe.build_account(frame,ready)
        previous=oldobs.loc[(oldobs.session==key[0])&(oldobs.symbol==key[1])]
        pd.testing.assert_frame_equal(current.reset_index(drop=True),previous[list(current.columns)].reset_index(drop=True),check_dtype=False)
        observations[key]=current
        quality.append(dict(session=key[0],symbol=key[1],種類='旧観測全列一致',**check))
    print('旧C03 46口座の観測品質と全列一致',flush=True)
    # ----------------------------------------
    pending=sorted(set(inputs)-set(oldframes))
    def one(key):
        """
        機能: 追加1口座の過去特徴だけを作る。
        引数: key(tuple[str,str])。
        返り値: tuple のキー・公開特徴・観測・品質。
        """
        name=f'{key[0]}_{key[1]}.pkl';path=OUT/'追加C03'/name
        if path.exists():
            blob=pickle.loads(path.read_bytes())
        else:
            raw=ROOT/'book'/key[1]/(key[0]+'.jsonl')
            frame,audit=extract.extract(raw,inputs[key])
            expected=rawhash[key]
            assert audit['原本SHA256']==expected,(key,'元原本の指紋が異なる')
            observation,check=observe.build_account(frame,inputs[key])
            blob=dict(frame=frame,observation=observation,audit=audit,quality=check)
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(pickle.dumps(blob,pickle.HIGHEST_PROTOCOL))
        print('C03追加素材 '+str(key),flush=True)
        return key,blob
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for key,blob in pool.map(one,pending):
            frames[key]=blob['frame'];observations[key]=blob['observation']
            quality.append(dict(session=key[0],symbol=key[1],種類='追加・旧品質維持',**blob['quality'],原本照合=blob['audit']))
    # ----------------------------------------
    decisions={};traces={}
    for key,ready in inputs.items():
        decision,trace=backtest.build_signals(ready,observations[key],'C03',fixed['尺度'])
        decisions[key]=decision;traces[key]=trace
    oldsignals=pickle.loads((ROOT/'work/wave_v52/signals.pkl').read_bytes())['C03']
    for key,value in oldsignals.items():np.testing.assert_array_equal(value,decisions[key])
    directions,models=m3_directions(inputs)
    oldstates=pickle.loads((ROOT/'work/wave_v17/主方向状態.pkl').read_bytes())
    for key,value in oldstates.items():np.testing.assert_array_equal(directions[key],-value['M3'])
    package=dict(m3=directions,m3_models=models,c03=decisions,c03_observations=observations,c03_traces=traces)
    target=OUT/'sources.pkl';target.write_bytes(pickle.dumps(package,pickle.HIGHEST_PROTOCOL))
    refs=['work/wave_v52/measurement/features.pkl','work/wave_v52/theory/観測.pkl','work/wave_v52/signals.pkl',
          'work/wave_v52/売買仕様固定.json','work/wave_v17/主方向状態.pkl','M3_逆_A00_360分版/固定条件.json']
    refhash={name:sha(ROOT/name) for name in refs}
    generated={p.relative_to(ROOT).as_posix():sha(p) for p in OUT.rglob('*.pkl')}
    code={p.relative_to(ROOT).as_posix():sha(p) for p in [Path(variants.__file__),Path(extract.__file__),Path(observe.__file__),Path(backtest.__file__),Path(replay.__file__),Path(__file__)]}
    proof=dict(全30=sorted({k[0] for k in inputs}),口座数=len(inputs),旧C03一致口座=len(oldsignals),旧M3方向一致口座=len(oldstates),
        原入力SHA256=fingerprints,原本SHA256={f'book/{k[1]}/{k[0]}.jsonl':v for k,v in rawhash.items()},旧参照SHA256=refhash,生成物SHA256=generated,実装SHA256=code,各口座=quality,
        将来ラベル='読取も生成もしない。旧観測器の未来ラベル分岐を除去し、旧46口座の観測全列・売買決定と一致。',
        固定尺度=fixed['尺度'],主約定='紙上CurrentPrice約定を公開し、実口座はその次の有効共通観測で追従。',
        損益評価='ここでは特徴だけ。新源全場の売買・損益比較を行わない。')
    save(OUT/'源素材の固定.json',proof)
    return proof


def load(verify=True):
    """
    機能: 固定済み源素材を読み、指紋を検証する。
    引数: verify(bool)。
    返り値: tuple[dict,dict] の特徴と固定証拠。
    """
    proof=json.loads((OUT/'源素材の固定.json').read_text(encoding='utf-8'))
    if verify:
        expected=proof['旧参照SHA256']|proof['生成物SHA256']|proof['実装SHA256']
        for name,digest in expected.items():assert sha(ROOT/name)==digest,name
    return pickle.loads((OUT/'sources.pkl').read_bytes()),proof


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=4)
    prepare(parser.parse_args().workers)
