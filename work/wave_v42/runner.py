"""原本全行の数量観測260条件を固定原本で再生し、全注文を独立に再構成する。"""

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
import sys
import time
import numpy as np
import design
import entry_signals

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
LEGACY=HERE.parent/'wave_v39'
sys.path.append(str(LEGACY))
import engine_single as engine
import execution_audit
import trade_statistics as statistics
import event_response

for module,expected in ((design,HERE/'design.py'),(entry_signals,HERE/'entry_signals.py'),
    (engine,LEGACY/'engine_single.py'),(execution_audit,LEGACY/'execution_audit.py'),
    (statistics,LEGACY/'trade_statistics.py'),(event_response,LEGACY/'event_response.py')):
    assert Path(module.__file__).resolve()==expected.resolve(),str(module.__file__)

INPUTS=DEPTH=BANDS=PANEL=PEERS=FIXED=None
PRIOR=HERE.parent/'wave_v40'


def digest(path: Path) -> str:
    """機能: 保存物の全内容を指紋化する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    value=hashlib.sha256()
    with path.open('rb') as stream:
        while block:=stream.read(8*1024*1024):value.update(block)
    return value.hexdigest()


def read(path: Path) -> object:
    """機能: 通常又は圧縮JSONを読む。

    引数: path (Path)。返り値: 保存内容 (object)。
    """
    payload=path.read_bytes()
    return json.loads(gzip.decompress(payload) if path.suffix=='.gz' else payload)


def save(path: Path,value: object) -> None:
    """機能: 有限な日本語JSONを途中書込みと区別して保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    path.parent.mkdir(parents=True,exist_ok=True)
    payload=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_bytes(gzip.compress(payload,mtime=0) if path.suffix=='.gz' else payload)
    temporary.replace(path)


def fingerprint(value: np.ndarray) -> dict:
    """機能: 全原本行を含む数値配列を形・型・指紋で識別する。

    引数: value (ndarray)。返り値: 内容指紋 (dict)。
    """
    return dict(shape=list(value.shape),dtype=str(value.dtype),SHA256=hashlib.sha256(value.tobytes()).hexdigest())


def freeze() -> dict:
    """機能: 旧帯・新全行観測・全260条件と監査済み実装を損益前に固定する。

    引数: なし。返り値: 起動可能な固定記録 (dict)。完了証拠の不足は停止する。
    """
    refs=dict(read(PRIOR/'探索条件の固定.json')['実装と入力SHA256'])
    for relative,sha in refs.items():assert digest(ROOT/relative)==sha,relative
    def bind(path: Path,expected: str | None=None) -> None:
        """機能: 旧指紋を現在値で上書きせず、同じ実体だけを固定へ追加する。

        引数: path (Path)、expected (str|None)。返り値: なし (None)。
        """
        actual=digest(path);relative=path.relative_to(ROOT).as_posix()
        assert expected is None or actual==expected,relative
        assert relative not in refs or refs[relative]==actual,relative
        refs[relative]=actual
    old_done=read(PRIOR/'完備監査.json')
    assert old_done['検証完了'] and old_done['全条件数']==281
    assert old_done['固定SHA256']==digest(PRIOR/'探索条件の固定.json')
    for name in design.LEGACY_EQUIVALENTS.values():
        path=PRIOR/'ledgers'/(name+'.json.gz')
        bind(path,old_done['参照資料SHA256'][path.relative_to(ROOT).as_posix()])
    material=read(HERE/'trial_observation_fixed.json')
    assert material['全合格'] and material['全セル数']==260
    for relative,sha in material['SHA256'].items():bind(ROOT/relative,sha)
    for name in ('trial_observation_audit.json','check_entry_signals.json','check_assessment.json'):
        proof=read(HERE/name);assert proof['全合格'],name
        for mapping in ('参照SHA256','出力SHA256','SHA256'):
            for relative,sha in proof.get(mapping,{}).items():
                path=ROOT/relative if relative.startswith(('work/','book/','candle_')) else HERE/relative
                bind(path,sha)
        bind(HERE/name)
    observation=read(HERE/'trial_observation_audit.json')
    assert (observation['全セル数'],observation['prefix数'],observation['future数'],observation['reflection数'])==(260,520,520,260)
    assert observation['原本不変'] and not observation['売買再生']
    entrance=read(HERE/'check_entry_signals.json')
    assert (entrance['条件数'],entrance['入力数'],entrance['全比較入力数'],entrance['旧入口再現数'])==(260,26,6760,104)
    assert entrance['旧4方式26入力完全再現'] and not entrance['新売買計算']
    assert entrance['検査数']=={'全入口列独立一致':6760,'既確定候補の公開投影':2704,
        '未来側確定比率変更':2704,'固定帯と公開比率の上下反射':1352,
        '乱数同候補時刻':4992,'同品質対照の比較可能母集団一致':468}
    assert observation['API取得数']==entrance['API取得数']==0
    frequency=read(HERE/'候補頻度の事前確認.json')
    assert frequency['全20基本頻度確認'] and frequency['収支前の頻度確認']
    assert not frequency['基礎活動基準変更'] and not frequency['新売買再生']
    old=read(LEGACY/'check_engine_adversarial.json')
    assert old['入力契約を含む全合格'] and old['外部独立監査も全一致']
    for relative,sha in old['SHA256'].items():
        bind(LEGACY/relative,sha)
    raw=read(LEGACY/'探索条件の固定.json')['原本78SHA256']
    for relative,sha in raw.items():assert digest(ROOT/relative)==sha,relative
    for path in [*(HERE/name for name in ('runner.py','design.py','entry_signals.py','assessment.py',
        'trial_observation.py','check_trial_observation.py','published_reference.py','trial_panel.pkl',
        'trial_observation_fixed.json','check_entry_signals.py','check_assessment.py','assessment_fixed.json','complete.py',
        '候補頻度の事前確認.json','record_candidate_frequency.py')),
        *(LEGACY/name for name in ('engine_single.py','execution_audit.py','trade_statistics.py','event_response.py','check_engine_adversarial.json')),
        *(PRIOR/'ledgers'/(name+'.json.gz') for name in design.LEGACY_EQUIVALENTS.values()),
        PRIOR/'探索条件の固定.json',PRIOR/'完備監査.json',HERE.parent/'wave_v23/inputs.pkl']:
        bind(path)
    for relative,sha in refs.items():assert digest(ROOT/relative)==sha,relative
    value=dict(主条件=design.catalog(),補助条件=design.supplementary(),規則=design.rules(),
        実装と入力SHA256=refs,原本78SHA256=raw,全条件数=260,全入力数=6760,
        共通帯設定数=10,全原本既知=True,全13を評価=True,現在API取得数=0,保存ライブ使用=False,
        実相場新収支の計算前=True,候補頻度は事前確認済み=True,旧注文器の変更=False,
        旧4対照=design.LEGACY_EQUIVALENTS,旧帯生成変更=False)
    path=HERE/'探索条件の固定.json'
    if path.exists():
        old_value=read(path);assert {k:v for k,v in old_value.items() if k!='固定時刻'}==value
        return old_value
    value['固定時刻']=datetime.now().astimezone().isoformat();save(path,value)
    return value


def no_network(*args: object,**kwargs: object) -> None:
    """機能: 再生処理の新しい通信を拒否する。

    引数: 任意args/kwargs (object)。返り値: なし (None)。常に例外。
    """
    raise RuntimeError('保存データの再生中にネットワークは使いません')


def initialize() -> None:
    """機能: workerごとに同じ既知入力・帯・相手公開を一度だけ読む。

    引数: なし。返り値: なし (None)。
    """
    global INPUTS,DEPTH,BANDS,PANEL,PEERS,FIXED
    socket.socket=no_network;socket.create_connection=no_network
    FIXED=read(HERE/'探索条件の固定.json')
    for relative,sha in FIXED['実装と入力SHA256'].items():assert digest(ROOT/relative)==sha
    INPUTS=pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    DEPTH=pickle.loads((PRIOR/'released_depth.pkl').read_bytes())
    BANDS=pickle.loads((PRIOR/'band_cache.pkl').read_bytes())
    PANEL=pickle.loads((HERE/'trial_panel.pkl').read_bytes())
    PEERS={key:entry_signals.peer_prices(events) for key,events in DEPTH.items()}
    assert len(INPUTS)==len(DEPTH)==26 and len(BANDS)==len(PANEL)==10


def causal(ready: dict,pulse: np.ndarray,result: dict,spec: dict) -> dict:
    """機能: 固定入口に対する注文器の過去部分・未来変更・上下反射を検査する。

    引数: ready/result/spec (dict)、pulse (ndarray)。返り値: 一致証跡 (dict)。
    入口生成の因果は別の全公開帯・相手情報検査で確認する。
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
    """機能: 1条件の26口座を全原本行で再生し、注文と会計を独立検算する。

    引数: spec (dict)。返り値: 完了した条件ID (str)。
    """
    identifier=spec['id'];rows=[];ledger=[];proofs=[];responses=[];start=time.monotonic()
    old_id=design.LEGACY_EQUIVALENTS.get(identifier)
    old_ledgers={(r['session'],r['symbol']):r for r in read(PRIOR/'ledgers'/(old_id+'.json.gz'))} if old_id else {}
    for key,ready in sorted(INPUTS.items()):
        peer=(key[0],'TOPIX' if key[1]=='NK225' else 'NK225')
        pulse,signal_info=entry_signals.make(spec,key,INPUTS,BANDS[entry_signals.cache_key(spec)][key],PEERS[peer],panel=PANEL[entry_signals.cache_key(spec)][key])
        result=engine.run(ready,pulse,spec['delay'],spec['observed'])
        proof=execution_audit.check(ready,pulse,result,spec['delay'],spec['observed'])
        if old_id:
            assert {k:fingerprint(v) for k,v in result.items()}==old_ledgers[key]['全結果指紋']
            assert fingerprint(pulse)==old_ledgers[key]['入口パルス指紋']
            proof['旧対照全配列再現']=True
            proof['旧対照ID']=old_id
        if key[0] in ('2026-09-24_Night','2026-09-29_Day'):proof['代表因果']=causal(ready,pulse,result,spec)
        rows.append(statistics.session(ready,result))
        ledger.append(dict(session=key[0],symbol=key[1],trades=result['trades'].tolist(),orders=result['orders'].tolist(),
            stats=result['stats'].tolist(),全結果指紋={k:fingerprint(v) for k,v in result.items()},
            入口パルス指紋=fingerprint(pulse),入口根拠=signal_info))
        responses.append(dict(session=key[0],symbol=key[1],評価専用未来反応=event_response.measure(ready,pulse)))
        proofs.append(dict(session=key[0],symbol=key[1],**proof))
    summary=dict(id=identifier,spec=spec,symbols={symbol:statistics.aggregate([r for r in rows if r['symbol']==symbol])
        for symbol in ('TOPIX','NK225')},固定SHA256=digest(HERE/'探索条件の固定.json'),経過秒=round(time.monotonic()-start,3))
    objects=dict(sessions=rows,ledgers=ledger,responses=responses,summaries=summary,
        audits=dict(id=identifier,全独立会計合格=True,全入力数=26,
            全原本行数=sum(p['原本行数'] for p in proofs),因果入力数=4,検査=proofs))
    saved={}
    for folder,value in objects.items():
        suffix='.json' if folder=='summaries' else '.json.gz';path=HERE/folder/(identifier+suffix)
        save(path,value);saved[path.relative_to(ROOT).as_posix()]=digest(path)
    save(HERE/'completed'/(identifier+'.json'),dict(id=identifier,spec=spec,保存SHA256=saved,
        固定SHA256=digest(HERE/'探索条件の固定.json')))
    return identifier


def main() -> None:
    """機能: 起動前固定を確認して260条件を完走し、全口座の集合だけを完了とする。

    引数: --freeze (bool)、--workers (int)。返り値: なし (None)。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--freeze',action='store_true');parser.add_argument('--workers',type=int,default=6)
    args=parser.parse_args();fixed=freeze()
    if args.freeze:print('260条件を新しい収支の計算前に固定。',flush=True);return
    assert 1<=args.workers<=8
    specs=fixed['主条件']+fixed['補助条件'];assert len({s['id'] for s in specs})==260
    with ProcessPoolExecutor(max_workers=args.workers,initializer=initialize) as pool:
        futures=[pool.submit(execute,spec) for spec in specs]
        for count,future in enumerate(as_completed(futures),1):print(f'{count}/260 {future.result()} 全注文独立一致',flush=True)
    index={};references={};total_rows=0
    expected=set(pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes()))
    for spec in specs:
        identifier=spec['id'];summary=read(HERE/'summaries'/(identifier+'.json'));assert summary['spec']==spec
        certificate=read(HERE/'completed'/(identifier+'.json'))
        assert certificate['spec']==spec and certificate['固定SHA256']==digest(HERE/'探索条件の固定.json')
        assert len(certificate['保存SHA256'])==5
        for relative,sha in certificate['保存SHA256'].items():
            assert digest(ROOT/relative)==sha;references[relative]=sha
        proof=read(HERE/'audits'/(identifier+'.json.gz'))
        assert proof['全独立会計合格'] and proof['全入力数']==26 and proof['因果入力数']==4
        assert len(proof['検査'])==26 and {(r['session'],r['symbol']) for r in proof['検査']}==expected
        for row in proof['検査']:
            assert row['全注文の成立脱落一致'] and row['全原本行会計一致'] and row['場内返済']
            if '代表因果' in row:assert all(row['代表因果'][k] for k in ('過去部分一致','未来改変一致','上下反射一致'))
        total_rows+=proof['全原本行数'];index[identifier]=summary
    for mapping in ('実装と入力SHA256','原本78SHA256'):
        for relative,sha in fixed[mapping].items():assert digest(ROOT/relative)==sha
    save(HERE/'全条件の期間集計.json.gz',index)
    save(HERE/'主再生の完了.json',dict(全条件数=260,全入力数=6760,因果入力数=1040,
        全原本行会計数=total_rows,全独立会計合格=True,現在API取得数=0,
        固定SHA256=digest(HERE/'探索条件の固定.json'),参照SHA256=references))
    print('全260条件・6760入力の独立注文と会計を完了。',flush=True)


if __name__=='__main__':main()
