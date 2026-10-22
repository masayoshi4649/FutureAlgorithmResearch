"""既存経済実装を固定し、追加ナイトと入口部品の実行可能損益を再生する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent/'wave_v44'))
import runner as previous
sys.path.insert(0, str(HERE))
import component_signals as entry
sys.path.insert(0, str(HERE.parent/'wave_v35'))
import deterioration_signals as mid

INPUTS, FEATURES, MID = {}, {}, {}
NEW_SESSION = '2026-09-29_Night'
BASE_IDS = ('A0__V000', 'G000_F25_N1__V000', 'G150_F50_N1__V000')


def save(path: Path, value: object) -> None:
    """機能: 今作業領域だけへ有限JSONを原子的に保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_bytes(gzip.compress(raw, mtime=0) if path.suffix == '.gz' else raw)
    temp.replace(path)


def initialize(mode: str) -> None:
    """機能: 通信を拒否し、保存入力と旧経済実装だけを読み込む。

    引数: mode(str)はnew又はentry。返り値: なし(None)。
    """
    global INPUTS, FEATURES, MID
    previous.initialize()
    socket.socket.connect = previous.old.reject_network
    socket.create_connection = previous.old.reject_network
    if mode == 'new':
        all_inputs = pickle.loads((HERE/'inputs.pkl').read_bytes())
        all_features = pickle.loads((HERE/'features_depth.pkl').read_bytes())
        INPUTS = {k:v for k,v in all_inputs.items() if k[0] in (NEW_SESSION, '2026-09-29_Day')}
        FEATURES = {k:all_features[k] for k in INPUTS}
        entry.set_root(ROOT)
        states = entry.build(entry.specification(), INPUTS, FEATURES)
        mid.clear_cache()
        for code in ('B00', 'B01'):
            condition = next(s for s in mid.catalog() if s['id'] == code)
            MID[code] = mid.build(condition, INPUTS, FEATURES)
        MID['entry'] = states
    else:
        INPUTS = previous.INPUTS
    assert len(INPUTS) == (4 if mode == 'new' else 26)


def valid_column(value: dict) -> np.ndarray:
    """機能: 公開イベントの品質を原本行へ対応させる。

    引数: value(dict)は方向生成結果。返り値: 有効公開列(ndarray[bool])。
    """
    index = value['source_event_index']
    output = np.zeros(len(index), bool)
    keep = index >= 0
    output[keep] = value['events']['valid'].to_numpy(bool)[index[keep]]
    return output


def new_columns(spec: dict, key: tuple) -> tuple:
    """機能: 新ナイトにも旧と同じ公開順の10列を用意する。

    引数: spec(dict)、key(tuple[str,str])。返り値: 10列と悪化有効列(tuple)。
    """
    state = MID['entry'][key]
    zero = np.zeros(len(state), np.int8)
    source = np.full(len(state), -1, np.int64)
    invalid = np.zeros(len(state), bool)
    if spec['policy']['kind'] != 'dynamic':
        return (state,zero,source,zero,source,invalid,zero,source,invalid,zero), invalid
    bad, branch = MID['B00'][key], MID['B01'][key]
    valid, bv = valid_column(bad), valid_column(branch)
    return (state,bad['direction'],bad['source_row'],bad['direction'],bad['source_row'],valid,
            branch['direction'],branch['source_row'],bv,zero), valid


def evaluate_case(spec: dict, ready: dict, columns: tuple, valid: np.ndarray, causal: bool) -> tuple:
    """機能: 一入力の会計・源行・予算・場内返済を監査して経済成果を返す。

    引数: spec/ready(dict)、columns(tuple)、valid(ndarray)、causal(bool)。
    返り値: セッション集計・台帳・監査・時価系列(tuple)。
    """
    config = previous.old.base.managers.make_config(previous.old.FIXED['manager'], ready['symbol'], ready)
    actual = previous.play(spec, ready, columns, config, gate_valid=valid)
    result, effective, evidence = actual
    row, curves, proof, basic = previous.audit.inspect(spec, ready, result, config, effective)
    assert all(proof[flag] is True for flag in previous.PROOF_FLAGS), proof
    other = previous.old.session_row(spec['id'], ready, result, config, effective[1], basic, curves)
    previous.audit.statistics.equal(other, row, '別経路集計')
    fp = previous.old.fingerprints(result)
    ledger = dict(session=ready['session'], symbol=ready['symbol'], config=config,
        **{field:result[field].tolist() for field in previous.STORED}, result_fingerprints=fp,
        shadow_cycles=result['shadow']['cycles'].tolist(), shadow_orders=result['shadow']['orders'].tolist())
    if causal:
        proof['因果'] = previous.causal_check(spec,ready,columns,config,actual,valid)
    proof.update(session=ready['session'],symbol=ready['symbol'])
    if ready['session'] == NEW_SESSION:
        cutoff = datetime.fromisoformat('2026-09-29T21:00:00+09:00').timestamp()
        index = np.searchsorted(ready['time_s'], cutoff, side='left')-1
        assert index >= 0
        equity = curves['equity'] * config['point_value']
        # ----------------------------------------
        # 21時で建玉はリセットしない。既知区間境界の含み損益を引いた時価差分を別表示する。
        row['既知21時直前時価円'] = float(equity[index])
        row['追加21時以降時価差分円'] = float(equity[-1]-equity[index])
        assert abs(equity[-1]-row['net_yen']) < 1e-6
    return row, ledger, proof, curves['equity']


def run_new() -> None:
    """機能: 固定五方式を旧日中で完全再現後に追加ナイトへ一度適用する。

    引数: なし。返り値: なし(None)。追加結果を方式選抜へ使わない。
    """
    fixed = previous.read(HERE/'追加ナイト照合の固定.json')
    specs = fixed['既存固定五方式']
    initialize('new')
    records, proofs, ledgers, calibration = [], [], [], []
    for spec in specs:
        prior = {(r['session'],r['symbol']):r for r in previous.read(
            HERE.parent/'wave_v45/ledgers'/(spec['id']+'.json.gz'))}
        for symbol in ('TOPIX','NK225'):
            key = ('2026-09-29_Day',symbol)
            columns, valid = new_columns(spec,key)
            stored = previous.columns_for(spec,key)
            for left,right in zip(columns,stored):
                np.testing.assert_array_equal(left,right)
            np.testing.assert_array_equal(valid,previous.quality_for(spec,key))
            row,ledger,proof,curve = evaluate_case(spec,INPUTS[key],columns,valid,False)
            assert ledger['result_fingerprints'] == prior[key]['result_fingerprints'], (spec['id'],key)
            calibration.append(dict(id=spec['id'],session=key[0],symbol=symbol,全15指紋一致=True))
    assert len(calibration) == 10
    print('新入力用変換器：旧9/29デイ両銘柄×五方式の全方向・全経済指紋一致',flush=True)
    for spec in specs:
        for symbol in ('TOPIX','NK225'):
            key = (NEW_SESSION,symbol)
            columns,valid = new_columns(spec,key)
            row,ledger,proof,curve = evaluate_case(spec,INPUTS[key],columns,valid,True)
            records.append(row); ledgers.append(dict(id=spec['id'],**ledger)); proofs.append(dict(id=spec['id'],**proof))
            path = HERE/'new_curves'/(spec['id']+'_'+symbol+'.npz')
            path.parent.mkdir(exist_ok=True)
            np.savez_compressed(path,equity=curve)
        print(spec['id']+' 追加ナイト両銘柄監査完了',flush=True)
    save(HERE/'new_sessions.json',records)
    save(HERE/'new_ledgers.json.gz',ledgers)
    save(HERE/'new_audits.json',dict(全合格=True,旧照合=calibration,新監査=proofs,API取得数=0,
        方式選択への追加損益使用=False,実装SHA256=previous.digest(Path(__file__))))
    print('固定五方式：全10新入力・全10因果監査完了',flush=True)


def run_entry(spec: dict) -> dict:
    """機能: 一入口仕様をA0/C01/G150F50の同じ管理器へ接続する。

    引数: spec(dict)は部品入口仕様。返り値: 完了記録(dict)。
    三管理器を全て保存し、最良だけを抜き出さない。
    """
    started = time.perf_counter()
    bases = {s['id']:s for s in previous.read(HERE/'追加ナイト照合の固定.json')['既存固定五方式']}
    with np.load(HERE/'component_entries'/(spec['id']+'.npz')) as source:
        states = {key:source['|'.join(key)] for key in INPUTS}
    summaries = []
    for base_id in BASE_IDS:
        execution = deepcopy(bases[base_id]); execution['id'] = spec['id']+'__'+base_id
        rows,ledgers,proofs,series = [],[],[],{}
        for key,ready in sorted(INPUTS.items()):
            columns = previous.columns_for(bases[base_id],key)
            columns = (states[key],*columns[1:])
            valid = previous.quality_for(bases[base_id],key)
            row,ledger,proof,curve = evaluate_case(execution,ready,columns,valid,key[0] == '2026-09-29_Day')
            rows.append(row); ledgers.append(ledger); proofs.append(proof); series[key] = curve
        summary = dict(id=execution['id'],entry=spec,base_id=base_id,全合格=True)
        for field,names in [('all_symbols',previous.old.FIXED['全セッション']),
                            ('symbols',previous.old.FIXED['後半7セッション'])]:
            summary[field] = {symbol:previous.audit.statistics.period(rows,series,names,symbol,
                previous.old.base.research.MULT[symbol]) for symbol in ('TOPIX','NK225')}
        if spec == entry.specification():
            prior = previous.read(HERE.parent/'wave_v45/summaries'/(base_id+'.json'))
            for field in ('all_symbols','symbols'):
                previous.audit.statistics.equal(prior[field],summary[field],'基準入口期間一致')
            old_ledgers = {(r['session'],r['symbol']):r for r in previous.read(
                HERE.parent/'wave_v45/ledgers'/(base_id+'.json.gz'))}
            assert all(r['result_fingerprints'] == old_ledgers[r['session'],r['symbol']]['result_fingerprints'] for r in ledgers)
            summary['基準全経済指紋一致'] = True
        for folder,value,suffix in [('entry_sessions',rows,'.json.gz'),('entry_ledgers',ledgers,'.json.gz'),
                ('entry_audits',proofs,'.json.gz'),('entry_summaries',summary,'.json')]:
            save(HERE/folder/(execution['id']+suffix),value)
        summaries.append(summary['id'])
    done = dict(入口=spec['id'],条件=summaries,全合格=True,入力会計数=78,経過秒=time.perf_counter()-started)
    save(HERE/'entry_completed'/(spec['id']+'.json'),done)
    return done


def freeze_entry() -> dict:
    """機能: 入口26×管理3の比較規則と参照を経済結果より先に固定する。

    引数: なし。返り値: 固定書(dict)。
    """
    fixed = dict(入口条件=entry.catalog(),管理条件=BASE_IDS,条件数=78,旧入力数=26,
        新ナイト選抜禁止=True,比較='各部品以外固定。管理器ごとに相手・短期・主時計の対応差を全て表示する。',
        安定性='両銘柄の全13と後半7で黒字・平均勝ち枚損益/平均負け枚損益>1。最大勝ち2組を同時に除外しても黒字。±20%感度は別表示する。',
        統計='全13は反復探索に使用済み。新しい独立検証とは数えない。セッション別対応差で方向を見る。',
        参照SHA256={p.relative_to(ROOT).as_posix():previous.digest(p) for p in (
            Path(__file__),HERE/'component_signals_fixed.json',HERE/'component_signal_audit.json',
            HERE.parent/'wave_v23/inputs.pkl',Path(previous.engine.__file__),Path(previous.audit.__file__))})
    path=HERE/'入口経済比較の固定.json'
    if path.exists():
        previous.audit.statistics.equal(previous.read(path),fixed,'固定内容')
    else:
        save(path,fixed)
    return fixed


def main() -> None:
    """機能: 独立した新ナイト照合又は旧入力入口比較を実行する。

    引数: コマンドラインmode(str)、workers(int)。返り値: なし(None)。
    """
    parser=argparse.ArgumentParser(); parser.add_argument('mode',choices=('new','entry'))
    parser.add_argument('--workers',type=int,default=3)
    args=parser.parse_args()
    if args.mode == 'new':
        run_new(); return
    fixed=freeze_entry()
    with ProcessPoolExecutor(max_workers=args.workers,initializer=initialize,initargs=('entry',)) as pool:
        tasks={pool.submit(run_entry,s):s['id'] for s in fixed['入口条件']}
        for i,future in enumerate(as_completed(tasks),1):
            result=future.result(); print(f"入口 {i}/26 {result['入口']} 完了",flush=True)


if __name__ == '__main__':
    main()
