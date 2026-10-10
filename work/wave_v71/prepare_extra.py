"""追加デイの入力だけを既存抽出器で準備し、未選定の追試用へ保存する。"""

import hashlib
import importlib.util
from pathlib import Path
import pickle
import socket
import sys

import numpy as np
import pandas as pd

import study

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TARGET = HERE/'prepared'
SESSION = '2026-10-09_Day'


def module(name: str, path: Path) -> object:
    """機能: 過去実装を変更せず固有名で読み込む。

    引数: name(str)、path(Path)。返り値: 読込モジュール(object)。
    """
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m)
    return m


def main() -> None:
    """機能: 新規原本の気配・入口部品・板特徴を保存し、価格結果と損益を見ない。

    引数: なし。返り値: なし(None)。API取得・実注文は行わない。
    """
    socket.socket.connect=study.deny;socket.create_connection=study.deny
    TARGET.mkdir(parents=True,exist_ok=True)
    assert not (TARGET/'extra_inputs.pkl').exists()
    app=module('追加入力71',ROOT/'work/wave_v50/update_20261001_day/replay_added_session.py')
    previous=app.previous;previous.HERE=TARGET;app.HERE=TARGET
    inputs,depth=previous.extract(SESSION)
    signals=previous.signal_audit(inputs,depth)
    extract=module('板抽出71',ROOT/'work/wave_v57/features.py')
    ticks=module('ティック入口71',ROOT/'work/wave_v69/signals/core.py')
    prepare=module('旧入口接続71',ROOT/'work/wave_v70/inputs/prepare.py')
    features,events={},{}
    audits=[]
    for key,ready in sorted(inputs.items()):
        f,ev,proof=extract.extract_one(key,ready)
        features[key],events[key]=f,ev;audits.append(proof)
        for k in ('seq','time_s','last'):
            np.testing.assert_array_equal(ready[k],f[k])
    models={k:prepare.model(r,pd.read_csv(ROOT/'candle_1min'/k[1]/(SESSION+'.csv'))) for k,r in inputs.items()}
    base={}
    for key,r in sorted(inputs.items()):
        f,e=features[key],events[key]
        eight=ticks.candidate_signals(f['bid'],f['ask'],f['bid_qty'],f['ask_qty'],f['best_ofi'],f['valid'],f['reset'],r['time_s'],
            e['i'],e['side'],e['qty'],e['bestqty'],e['price'],r['tick'],r['start'])
        peer=key[0],'NK225' if key[1]=='TOPIX' else 'TOPIX'
        old=signals['entry'][key]
        own=prepare.expand(models[key],r['time_s'],0.);other=prepare.expand(models[peer],r['time_s'],60.)
        base[key]=np.vstack((eight[[1,2,5,6]],prepare.pulse(old),prepare.pulse(prepare.rearm(old,own,other))))
    for name,data in (('extra_inputs.pkl',inputs),('extra_features.pkl',features),('extra_base_signals.pkl',base),('extra_events.pkl',events)):
        study.save(TARGET/name,data)
    raw={str(ROOT/'book'/symbol/(SESSION+'.jsonl')):hashlib.sha256((ROOT/'book'/symbol/(SESSION+'.jsonl')).read_bytes()).hexdigest() for symbol in study.SYMBOLS}
    study.save(TARGET/'追加デイの入力照合.json',dict(合格=True,対象=SESSION,口座数=2,有効原本行数=sum(len(r['seq']) for r in inputs.values()),
        原本SHA256=raw,気配行順時計一致=True,旧入口因果監査実施=True,抽出=audits,損益再生前=True,API取得=0,実注文=0,
        SHA256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(TARGET.glob('extra_*.pkl'))}))
    print('追加デイ2銘柄の入口・板特徴を準備完了',flush=True)


if __name__=='__main__':
    main()
