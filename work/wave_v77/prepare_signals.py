"""保存入力だけから三遅延の入口・途中判断状態を準備し、損益を見ずに指紋を保存する。"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import socket
import sys

import numpy as np

import signals


sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def deny(*args: object,**kwargs: object) -> None:
    """機能: 状態準備からの外部通信を禁止する。

    引数: args(tuple)、kwargs(dict)。返り値: なし(None)。常に例外で停止する。
    """
    raise RuntimeError('入口状態の準備は保存入力だけを使い、通信しない')


def module(name: str,path: Path) -> object:
    """機能: 同名モジュールと混ざらない形で入力準備器を読み込む。

    引数: name(str)、path(Path)。返り値: 読み込んだモジュール(object)。
    """
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec)
    sys.modules[name]=value;spec.loader.exec_module(value);return value


def material(delay: int) -> tuple:
    """機能: 委任されたinputs.prepare.materialから当該遅延の素材を取得する。

    引数: delay(int:1/5/15)。返り値: ready、grids、metadata(tuple)。板全量は使用後解放する。
    inputs.prepareのcore名は一時的に隔離し、既存のcoreモジュールを上書きしない。
    """
    old=sys.modules.get('core')
    try:
        sys.modules['core']=module('価格素材77専用',HERE/'inputs/core.py')
        prepare=module('保存入力77専用',HERE/'inputs/prepare.py')
        ready,book,snapshot,grids,meta=prepare.material(delay)
        del book,snapshot
        return ready,grids,meta
    finally:
        if old is None:sys.modules.pop('core',None)
        else:sys.modules['core']=old


def digest(path: Path) -> str:
    """機能: 大きな入力・出力資料の指紋を一定メモリーで計算する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    value=hashlib.sha256()
    with path.open('rb') as stream:
        while data:=stream.read(4*1024*1024):value.update(data)
    return value.hexdigest()


def main() -> None:
    """機能: 三遅延から指定一つの十二入口と共通状態を、損益前に保存する。

    引数: CLI --delay(int:1/5/15)。返り値: なし(None)。完成出力は上書きしない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--delay',type=int,default=5);args=parser.parse_args()
    assert args.delay in (1,5,15)
    socket.socket.connect=deny;socket.create_connection=deny
    folder=HERE/'prepared';folder.mkdir(exist_ok=True)
    target=folder/f'signals_delay{args.delay}.pkl';assert not target.exists(),'固定した入口を上書きしない'
    ready,grids,meta=material(args.delay);assert len(grids)==30 and len(ready)==60
    value=signals.build(grids,ready)
    prior_path=ROOT/f'work/wave_v76/prepared/signals_delay{args.delay}.pkl'
    prior=pickle.loads(prior_path.read_bytes())['Q25'];assert len(prior)==29
    rows=[]
    for session,state in value.items():
        # ----------------------------------------
        # 旧Q25を同じ入力で独立呼出しし、Q0の持続確認と入口列の完全一致を確認する。
        qdefinition=next(x for x in signals.LEGACY.definitions() if x['id']=='Q25')
        a,b=(grids[session]['markets'][s] for s in ('TOPIX','NK225'))
        qa,_,va,sa=signals.LEGACY.market_state(qdefinition,signals.q_market(a))
        qb,_,vb,sb=signals.LEGACY.market_state(qdefinition,signals.q_market(b))
        valid=va&vb;strong=np.where(valid&(qa==qb),qa,0).astype(np.int8)
        confirmed=signals.confirmation(state['grid'],strong==1,valid,sa,sb,10.).astype(np.int8)
        confirmed-=signals.confirmation(state['grid'],strong==-1,valid,sa,sb,10.).astype(np.int8)
        expected=signals.pulses(state['grid'],strong,valid,confirmed)
        np.testing.assert_array_equal(state['entries']['Q0']['event'],expected)
        if session in prior:
            np.testing.assert_array_equal(state['grid'],prior[session]['grid'])
            np.testing.assert_array_equal(state['entries']['Q0']['event'],prior[session]['entry'][10])
        for ident,entry in state['entries'].items():
            assert len(entry['event'])==len(state['grid'])
            assert np.isin(entry['event'],(-1,0,1)).all()
            rows.append(dict(セッション=session,入口=ident,格子数=len(state['grid']),有効数=int(state['valid'].sum()),
                買許可数=int(entry['long_allowed'].sum()),売許可数=int(entry['short_allowed'].sum()),
                買イベント数=int((entry['event']==1).sum()),売イベント数=int((entry['event']==-1).sum()),
                J入口は旧イベント適用前=ident.startswith('J')))
        for ident,base in (('Q1','Q0'),('Q2','Q0'),('Q3','Q0'),('P1','P0'),('P3','P2')):
            event=state['entries'][ident]['event'];parent=state['entries'][base]['event']
            assert np.all((event==0)|(event==parent)),(session,ident,'同じ確認完了イベントのみ棄却')
        assert not np.any(state['opposite_long']&state['opposite_short'])
    target.write_bytes(pickle.dumps(value,protocol=5))
    proof=dict(遅延秒=args.delay,入口条件数=12,セッション数=30,口座数=60,定義=signals.defs(),集計=rows,
        共通状態='両300秒3bp以上かつ両30秒同方向進行。反対返済は両30秒進行と両F15方向比率.1以上を双方更新込み30秒確認。',
        反落の準備='30/60秒の両市場反落開始で準備。180秒以内に両市場の短期純移動と両気配各1呼値以上の再進行を10秒確認。無効/共通消失/反転/格子欠落で破棄。',
        除外の適用='Q/Pの追加条件は既存の確認完了イベントを棄却するだけで、持続確認時計と再準備を変えない。',
        構造線='180秒range.source_valid時だけ、銘柄別に直前安値−1ラージ呼値/直前高値＋1ラージ呼値。',
        旧Q25完全一致=True,旧保存信号との完全一致場数=len(prior),旧保存信号との相違格子数=0,
        新Night='特徴・信号だけを準備。前29の代表固定前に追加場の損益を計算しない。',
        時刻限界=meta['時刻'],損益閲覧=0,確率採点=0,損益再生=0,API取得=0,実注文=0,
        SHA256={str(path.relative_to(ROOT)):digest(path) for path in [HERE/'signals.py',HERE/'prepare_signals.py',
            HERE/f'inputs/grids_delay{args.delay}.pkl',HERE/'inputs/metadata.json',prior_path,target]})
    (folder/f'入口状態_delay{args.delay}.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    print(f'遅延{args.delay}秒の12入口・30場を損益閲覧なしで保存しました',flush=True)


if __name__=='__main__':
    main()
