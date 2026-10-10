"""固定した新しい板入口を保存原本だけで再生し、全注文を独立検算する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import socket
import time
import numpy as np
import design
import engine_single as engine
import entry_signals as signals
import execution_audit
import trade_statistics as stats
import event_response

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
INPUTS=EVENTS=FORECASTS=FIXED=None


def digest(path: Path) -> str:
    """機能: ファイルを内容指紋で識別する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):value.update(block)
    return value.hexdigest()


def read(path: Path) -> object:
    """機能: 通常又はgzip形式の有限JSONを読む。

    引数: path (Path)。返り値: 保存内容 (object)。
    """
    payload=path.read_bytes()
    return json.loads(gzip.decompress(payload) if path.suffix=='.gz' else payload)


def save(path: Path,value: object) -> None:
    """機能: 結果を途中書込みと区別して原子的に保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    path.parent.mkdir(parents=True,exist_ok=True)
    payload=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_bytes(gzip.compress(payload,mtime=0) if path.suffix=='.gz' else payload)
    temp.replace(path)


def fingerprint(value: np.ndarray) -> dict:
    """機能: 数値配列の形・型・全要素を指紋化する。

    引数: value (ndarray)。返り値: 指紋記録 (dict)。
    """
    return dict(shape=list(value.shape),dtype=str(value.dtype),SHA256=hashlib.sha256(value.tobytes()).hexdigest())


def freeze() -> dict:
    """機能: 成績計算前の全240条件、検査、全78原本を固定する。

    引数: なし。返り値: 固定内容 (dict)。既存固定の上書きを拒否する。
    """
    model=read(HERE/'モデル学習の固定.json')
    refs=dict(model['SHA256'])
    for name in ('runner.py','design.py','entry_signals.py','engine_single.py','execution_audit.py',
        'trade_statistics.py','assessment.py','event_response.py','check_engine_single.py','check_engine_adversarial.py',
        'check_assessment.py','check_entry_signals.py','モデル学習の固定.json',
        '単発出口の人工検査.json','check_engine_adversarial.json','check_assessment.json','入口配線の因果検査.json'):
        path=HERE/name;refs[path.relative_to(ROOT).as_posix()]=digest(path)
    for relative,sha in refs.items():assert digest(ROOT/relative)==sha,relative
    for name in ('単発出口の人工検査.json','check_engine_adversarial.json','check_assessment.json','入口配線の因果検査.json'):
        for relative,sha in read(HERE/name)['SHA256'].items():
            path=ROOT/relative if relative.startswith('work/') else HERE/relative
            assert digest(path)==sha,(name,relative)
    engine_proof=read(HERE/'check_engine_adversarial.json')
    assert engine_proof['入力契約を含む全合格'] and engine_proof['外部独立監査も全一致']
    assert read(HERE/'check_assessment.json')['全合格']
    assert read(HERE/'入口配線の因果検査.json')['全合格']
    raw=read(HERE.parent/'wave_v38/adaptive_accounting_fixed.json')['原本78SHA256']
    for relative,sha in raw.items():assert digest(ROOT/relative)==sha,relative
    value=dict(主条件=design.catalog(),補助条件=design.supplementary(),規則=design.rules(),
        実装と入力SHA256=refs,原本78SHA256=raw,全条件数=240,全入力数=6240,
        実相場新収支を計算する前=True,候補頻度は事前確認済み=True,現在API取得数=0,
        保存ライブ使用=False,既知13セッション=True,初期2セッション学習専用=True)
    path=HERE/'探索条件の固定.json'
    if path.exists():
        old=read(path);assert {k:v for k,v in old.items() if k!='固定時刻'}==value
        return old
    value['固定時刻']=datetime.now().astimezone().isoformat();save(path,value)
    return value


def no_network(*args: object,**kwargs: object) -> None:
    """機能: 実データ再生中のネットワーク取得を拒否する。

    引数: 任意args/kwargs (object)。返り値: なし (None)。常に例外。
    """
    raise RuntimeError('保存原本の検証中にネットワークは使用しません')


def initialize() -> None:
    """機能: 各workerで同じ保存入力とモデルを一度だけ読み込む。

    引数: なし。返り値: なし (None)。条件ごとの再学習は行わない。
    """
    global INPUTS,EVENTS,FORECASTS,FIXED
    socket.create_connection=no_network;socket.socket=no_network
    FIXED=read(HERE/'探索条件の固定.json')
    for relative,sha in FIXED['実装と入力SHA256'].items():assert digest(ROOT/relative)==sha,relative
    INPUTS=pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    EVENTS=pickle.loads((HERE/'released_minutes.pkl').read_bytes())
    FORECASTS={lag:pickle.loads((HERE/f'model_outputs_lag{lag}.pkl').read_bytes()) for lag in (1,3,6)}
    assert len(INPUTS)==26 and set(INPUTS)==set(EVENTS)


def causal(ready: dict,pulse: np.ndarray,result: dict,spec: dict) -> dict:
    """機能: 実原本代表4入力で過去部分・将来差替・上下反射を確かめる。

    引数: ready/result/spec (dict)、pulse (ndarray)。返り値: 照合証拠 (dict)。
    """
    n=len(pulse);end=int(n*.37);future=int(n*.73)
    part={k:(v[:end].copy() if isinstance(v,np.ndarray) and v.shape and len(v)==n else v) for k,v in ready.items()}
    limited=engine.run(part,pulse[:end],spec['delay'],spec['observed'],False)
    np.testing.assert_array_equal(limited['curve'],result['curve'][:end])
    np.testing.assert_array_equal(limited['orders'],result['orders'][result['orders'][:,0]<end])
    np.testing.assert_array_equal(limited['trades'],result['trades'][result['trades'][:,1]<end])
    changed=dict(ready);changed['last']=ready['last'].copy();changed['last'][future:]+=17*ready['tick']
    changed['atr']=ready['atr'].copy();changed['atr'][future:]*=3
    altered_pulse=pulse.copy();altered_pulse[future:]*=-1
    altered=engine.run(changed,altered_pulse,spec['delay'],spec['observed'])
    np.testing.assert_array_equal(altered['curve'][:future],result['curve'][:future])
    np.testing.assert_array_equal(altered['orders'][altered['orders'][:,0]<future],result['orders'][result['orders'][:,0]<future])
    mirrored=dict(ready);mirrored['last']=2*(float(ready['last'].max())+10*ready['tick'])-ready['last']
    mirror=engine.run(mirrored,-pulse,spec['delay'],spec['observed'])
    np.testing.assert_allclose(mirror['curve'][:,[0,1,3]],result['curve'][:,[0,1,3]],rtol=0,atol=1e-7)
    np.testing.assert_array_equal(mirror['orders'][:,[0,1,3,5,6]],result['orders'][:,[0,1,3,5,6]])
    return dict(過去部分一致=True,未来改変一致=True,上下反射一致=True,prefix行=end,future行=future)


def execute(spec: dict) -> str:
    """機能: 固定1条件の全26入力を再生し、独立会計と因果を保存する。

    引数: spec (dict)。返り値: 完了した条件ID (str)。未完備の結果を成功再利用しない。
    """
    identifier=spec['id'];rows=[];ledger=[];proofs=[];responses=[];start=time.monotonic()
    for key,ready in sorted(INPUTS.items()):
        pulse,signal_info=signals.make(spec,key,INPUTS,EVENTS,FORECASTS)
        result=engine.run(ready,pulse,spec['delay'],spec['observed'])
        evidence=execution_audit.check(ready,pulse,result,spec['delay'],spec['observed'])
        if key[0] in ('2026-09-24_Night','2026-09-29_Day'):
            evidence['代表因果']=causal(ready,pulse,result,spec)
        row=stats.session(ready,result);rows.append(row)
        responses.append(dict(session=key[0],symbol=key[1],評価専用未来反応=event_response.measure(ready,pulse)))
        ledger.append(dict(session=key[0],symbol=key[1],
            trades=result['trades'].tolist(),orders=result['orders'].tolist(),stats=result['stats'].tolist(),
            全結果指紋={k:fingerprint(v) for k,v in result.items()},入口パルス指紋=fingerprint(pulse),入口根拠=signal_info))
        proofs.append(dict(session=key[0],symbol=key[1],**evidence))
    summary=dict(id=identifier,spec=spec,
        symbols={symbol:stats.aggregate([r for r in rows if r['symbol']==symbol]) for symbol in ('TOPIX','NK225')},
        固定SHA256=digest(HERE/'探索条件の固定.json'),経過秒=round(time.monotonic()-start,3))
    save(HERE/'sessions'/(identifier+'.json.gz'),rows)
    save(HERE/'ledgers'/(identifier+'.json.gz'),ledger)
    save(HERE/'responses'/(identifier+'.json.gz'),responses)
    save(HERE/'audits'/(identifier+'.json.gz'),dict(id=identifier,全独立会計合格=True,全入力数=26,
        全原本行数=sum(p['原本行数'] for p in proofs),因果入力数=sum('代表因果' in p for p in proofs),検査=proofs))
    save(HERE/'summaries'/(identifier+'.json'),summary)
    saved={}
    for folder,suffix in (('sessions','.json.gz'),('ledgers','.json.gz'),('responses','.json.gz'),('audits','.json.gz'),('summaries','.json')):
        path=HERE/folder/(identifier+suffix);saved[path.relative_to(ROOT).as_posix()]=digest(path)
    save(HERE/'completed'/(identifier+'.json'),dict(id=identifier,spec=spec,保存SHA256=saved,
        固定SHA256=digest(HERE/'探索条件の固定.json')))
    return identifier


def main() -> None:
    """機能: 固定後に全240条件を実行し、全集合の完了だけを保存する。

    引数: --freeze (bool)、--workers (int)。返り値: なし (None)。API不使用。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--freeze',action='store_true');parser.add_argument('--workers',type=int,default=6)
    args=parser.parse_args();fixed=freeze()
    if args.freeze:print('全240条件と独立検査を新収支前に固定。',flush=True);return
    assert 1<=args.workers<=8
    specs=fixed['主条件']+fixed['補助条件']
    with ProcessPoolExecutor(max_workers=args.workers,initializer=initialize) as pool:
        futures=[pool.submit(execute,spec) for spec in specs]
        for count,future in enumerate(as_completed(futures),1):print(f'{count}/240 {future.result()} 全注文独立一致',flush=True)
    index={};references={};total_rows=0
    expected={(r['session'],r['symbol']) for r in pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes()).values()}
    assert len(expected)==26
    for spec in specs:
        value=read(HERE/'summaries'/(spec['id']+'.json'));assert value['spec']==spec
        assert value['固定SHA256']==digest(HERE/'探索条件の固定.json')
        certificate=read(HERE/'completed'/(spec['id']+'.json'))
        assert certificate['spec']==spec and certificate['固定SHA256']==value['固定SHA256']
        assert len(certificate['保存SHA256'])==5
        for relative,sha in certificate['保存SHA256'].items():
            assert digest(ROOT/relative)==sha;references[relative]=sha
        evidence=read(HERE/'audits'/(spec['id']+'.json.gz'))
        assert evidence['全独立会計合格'] and evidence['全入力数']==26 and evidence['因果入力数']==4
        assert len(evidence['検査'])==26 and {(r['session'],r['symbol']) for r in evidence['検査']}==expected
        for proof in evidence['検査']:
            assert proof['全注文の成立脱落一致'] and proof['全原本行会計一致'] and proof['場内返済']
            if '代表因果' in proof:assert all(proof['代表因果'][field] for field in ('過去部分一致','未来改変一致','上下反射一致'))
        total_rows+=evidence['全原本行数']
        index[spec['id']]=value
    for relative,sha in fixed['実装と入力SHA256'].items():assert digest(ROOT/relative)==sha
    for relative,sha in fixed['原本78SHA256'].items():assert digest(ROOT/relative)==sha
    save(HERE/'全条件の期間集計.json.gz',index)
    save(HERE/'主再生の完了.json',dict(全条件数=240,全入力数=6240,因果入力数=960,
        全原本行会計数=total_rows,全独立会計合格=True,現在API取得数=0,
        固定SHA256=digest(HERE/'探索条件の固定.json'),参照SHA256=references))
    print('全240条件・6240入力の独立注文と会計を完了。',flush=True)


if __name__=='__main__':main()
