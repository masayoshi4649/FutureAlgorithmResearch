"""保存された広い進行入口を同時点で順逆にし、既存kernelで出口と費用を再判定する。"""

from io import BytesIO
from datetime import datetime,timezone,timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo

import numpy as np


HERE=Path(__file__).resolve().parent
BASE=HERE.parent
ROOT=BASE.parents[1]
os.environ['NUMBA_CACHE_DIR']=str(HERE/'jit_cache')
sys.dont_write_bytecode=True
sys.path.insert(0,str(BASE))
sys.path.insert(0,str(BASE/'v2'))
import engine119
import engine_v2
import run_v2


POLICY_KEYS=('entry','exit_long','exit_short','width','valid')
FAMILIES=('COMMON','OPEN','LAG')
SOURCE_IDS=tuple(f'{family}_L20_X0_E0_G0' for family in FAMILIES)
RESULT_NAME='広い進行条件の順逆比較と全四十場.json'
JST=timezone(timedelta(hours=9))
NEW_YORK=ZoneInfo('America/New_York')


def quiet_rows(publication_times: np.ndarray) -> np.ndarray:
    """
    機能: 当時既知の価格公開時計だけから、毎日の日本・米国の固定警戒窓を判定する。
    引数: publication_times(ndarray[float64,N])は足を公開した価格時計のepoch秒。
    返り値: ndarray[bool,N]はJP08:45以上09:15未満又はNY08:15–08:45/09:15–09:45。
        休日例外は設けず、NYの夏時間はZoneInfoに従う。未知時計を未来行で補完しない。
    """
    result=np.zeros(len(publication_times),bool)
    for i,epoch in enumerate(publication_times):
        if not np.isfinite(epoch):continue
        jp=datetime.fromtimestamp(float(epoch),JST);ny=jp.astimezone(NEW_YORK)
        jp_seconds=jp.hour*3600+jp.minute*60+jp.second+jp.microsecond/1e6
        ny_seconds=ny.hour*3600+ny.minute*60+ny.second+ny.microsecond/1e6
        result[i]=(31500<=jp_seconds<33300) or (29700<=ny_seconds<31500) or (33300<=ny_seconds<35100)
    return result


def build_variants(base: dict,publication_times: np.ndarray) -> dict:
    """
    機能: 元三入口の順逆・二出口・二執行・既知固定時刻窓の有無で48条件にする。
    引数: base(dict)は三入口と五配列、publication_times(ndarray[float64,N])は公開価格時計。
    返り値: dictは固定specs48と配列[K=48,N]。元配列を上書きしない。
    """
    assert tuple(s['id'] for s in base['specs'])==SOURCE_IDS
    arrays={key:np.asarray(base[key]) for key in POLICY_KEYS}
    n=arrays['entry'].shape[1]
    assert np.asarray(publication_times).shape==(n,)
    quiet=quiet_rows(publication_times)
    assert all(value.shape==(3,n) for value in arrays.values())
    assert arrays['entry'].dtype==np.int8 and np.isin(arrays['entry'],[-1,0,1]).all()
    assert all(arrays[key].dtype==np.bool_ for key in ('exit_long','exit_short','valid'))
    assert arrays['width'].dtype==np.float64
    specs=[];values={key:[] for key in POLICY_KEYS}
    for index,family in enumerate(FAMILIES):
        original=base['specs'][index]
        for direction in ('direct','reverse'):
            reverse=direction=='reverse'
            for exit_mode in (5,4):
                for execution in (0,3):
                    for time_mode in (0,1):
                        ident=f'{family}20_'+('REV' if reverse else 'DIR')+f'_X{exit_mode}_P{execution}_T{time_mode}'
                        thought='保存された元候補と同じ公開時点で'+('元と反対方向へ参加する。' if reverse else '元と同じ方向へ参加する。')
                        specs.append(dict(id=ident,family=family+'20',entry_id=family+'20',
                            name=original['name']+'・'+('逆方向' if reverse else '順方向')+'・'+('時刻回避' if time_mode else '全時間'),
                            description=thought,source_description=original['description'],source_policy_id=SOURCE_IDS[index],
                            direction_mode=direction,exit_mode=exit_mode,execution_mode=execution,time_mode=time_mode,guard=2))
                        entry=(-arrays['entry'][index] if reverse else arrays['entry'][index]).copy()
                        exit_long=arrays['exit_short' if reverse else 'exit_long'][index].copy()
                        exit_short=arrays['exit_long' if reverse else 'exit_short'][index].copy()
                        valid=arrays['valid'][index].copy()
                        if time_mode:
                            entry[quiet]=0;valid[quiet]=False;exit_long[quiet]=True;exit_short[quiet]=True
                        values['entry'].append(entry);values['exit_long'].append(exit_long);values['exit_short'].append(exit_short)
                        values['width'].append(arrays['width'][index].copy());values['valid'].append(valid)
    result=dict(specs=specs,**{key:np.asarray(value) for key,value in values.items()})
    assert len(specs)==48 and len({s['id'] for s in specs})==48
    assert all(result[key].shape==(48,n) for key in POLICY_KEYS)
    result['time_quiet']=quiet
    return result


def verify_run_contract() -> tuple[dict,dict,dict]:
    """
    機能: 正式照合・登録された同じspecと固定sourceだけで運転できることを確認する。
    引数: なし。市場本文は読まない。
    返り値: tuple[dict,dict,dict]は固定計画、入力目録、正式試行計画。
    """
    fixed=run_v2.read(HERE/'固定計画.json')
    proposal=run_v2.read(HERE/'試行計画.json')
    check=run_v2.read(HERE/'正式照合の全出力.json')
    registered=run_v2.read(HERE/'正式登録の全出力.json')
    assert check['終了コード']==registered['終了コード']==0
    assert json.loads(check['stdout'])['proposal_complete'] is True
    enrolled=json.loads(registered['stdout'])
    assert enrolled['id']==proposal['id'] and enrolled['spec']==proposal['spec']
    for path,sha in fixed['sources'].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==sha,path
    assert proposal['spec']['implementation']==fixed['sources']
    manifest=fixed['input_manifest'];path=ROOT/manifest['path']
    assert proposal['spec']['data']['input_manifests']==[manifest],'登録した入力目録そのものへ接続する。'
    assert path.resolve()==(HERE/'入力目録.json').resolve()
    assert hashlib.sha256(path.read_bytes()).hexdigest()==manifest['sha256']
    meta=run_v2.read(path)
    assert meta['sessions']==proposal['spec']['data']['sessions']
    assert len(meta['sessions'])==len(set(meta['sessions']))==40
    assert len(meta['inputs'])==80 and {(i['session'],i['symbol']) for i in meta['inputs']}=={(s,k) for s in meta['sessions'] for k in ('TOPIX','NK225')}
    assert tuple(meta['source_ids'])==SOURCE_IDS and tuple(s['id'] for s in meta['source_specs'])==SOURCE_IDS
    return fixed,meta,proposal


def main() -> None:
    """
    機能: 根担当の正式登録後に限り、既所有80入力を各一読して固定48条件を一回運転する。
    引数: なし。原市場・APIは読まず、既存運転結果の符号反転は行わない。
    返り値: None。全小会計・17列台帳・公開時資産・方針配列を新規保存する。
    """
    fixed,meta,proposal=verify_run_contract()
    output=HERE/'measurement';assert not output.exists()
    output.mkdir()
    lookup={(i['session'],i['symbol']):i for i in meta['inputs']}
    assert len(lookup)==80 and len(meta['sessions'])==40
    all_rows=[];all_episodes=[];all_specs=None;reads=[];caches=[];clock=time.monotonic()
    for scene_number,scene in enumerate(meta['sessions']):
        for symbol in ('TOPIX','NK225'):
            item=lookup[scene,symbol]
            payload=(ROOT/item['owned_path']).read_bytes()
            assert len(payload)==item['bytes'] and hashlib.sha256(payload).hexdigest()==item['SHA256']
            with np.load(BytesIO(payload),allow_pickle=False) as source:
                bars={key[6:]:source[key].copy() for key in source.files if key.startswith('bars__')}
                quotes={key[8:]:source[key].copy() for key in source.files if key.startswith('quotes__')}
                base=dict(specs=meta['source_specs'],**{key:source['policies__'+key][meta['source_indexes']].copy() for key in POLICY_KEYS})
            model=build_variants(base,bars['pub_price_time_s']);specs=model['specs']
            if all_specs is None:all_specs=specs
            assert all_specs==specs
            events=engine119.market_events(bars,quotes)
            ledgers=[];equity=[];positions=[];scene_rows=[];scene_episodes=[]
            for index,spec in enumerate(specs):
                policy={key:model[key][index] for key in POLICY_KEYS}
                config=run_v2.settings(symbol,scene,spec['execution_mode'],spec['exit_mode'],2)
                result=engine_v2.run_policy(bars,quotes,policy,config,events)
                row=dict(session=scene,symbol=symbol,method=spec['id'],signals=int(np.count_nonzero(policy['entry'])),**run_v2.clean(result['summary']))
                all_rows.append(row);scene_rows.append(row)
                trades=run_v2.episodes(result['ledger'],quotes,bars,config['multiplier'])
                episode=dict(session=scene,symbol=symbol,method=spec['id'],parents=trades)
                all_episodes.append(episode);scene_episodes.append(episode)
                if len(result['ledger']):ledgers.append(np.column_stack((np.full(len(result['ledger']),index),result['ledger'])))
                equity.append(result['equity']);positions.append(result['position'])
            path=output/symbol/(scene+'.npz');path.parent.mkdir(parents=True,exist_ok=True)
            assert not path.exists()
            memory=BytesIO()
            np.savez_compressed(memory,ledger=np.concatenate(ledgers) if ledgers else np.empty((0,17)),
                equity=np.asarray(equity),position=np.asarray(positions),
                time_quiet=model['time_quiet'],**{'policies__'+key:model[key] for key in POLICY_KEYS})
            saved=memory.getvalue();path.write_bytes(saved)
            caches.append(dict(path=path.relative_to(ROOT).as_posix(),SHA256=hashlib.sha256(saved).hexdigest(),symbol=symbol,session=scene))
            run_v2.save(output/symbol/(scene+'.json'),dict(rows=scene_rows,episodes=scene_episodes))
            reads.append(dict(symbol=symbol,session=scene,source=item['owned_path'],SHA256=item['SHA256'],bytes=len(payload),original_market_reads=0))
            with (output/'保存入力読取.jsonl').open('a',encoding='utf8') as stream:stream.write(json.dumps(reads[-1],ensure_ascii=False)+'\n')
        print(f'{scene_number+1}/40 {scene} / 既所有入力{len(reads)} / {time.monotonic()-clock:.1f}秒',flush=True)
    assert len(reads)==len(caches)==80 and len(all_rows)==3840 and len(all_specs)==48
    for path,sha in fixed['sources'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==sha,path
    run_v2.save(output/RESULT_NAME,dict(sessions=meta['sessions'],splits=meta['splits'],specs=all_specs,runs=all_rows,
        episodes=all_episodes,cache=caches,source_SHA256=fixed['sources'],trial=proposal['id'],reads=reads,
        原市場追加読取=0,API=0,実注文=0,
        留保='既知40場の事後開発。同じ元候補公開時点の順逆対照であり、実受理集合・出口・再参加は異なり得る。未知成功と呼ばない。'))
    print('順逆と既知時刻回避の48政策・両商品40場の会計を保存しました。',flush=True)


if __name__=='__main__':
    main()
