"""正式登録後だけ、追加一場を旧固定少額E01の二商品で測定する。"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import time

import numpy as np

import adapter_v6 as adapter
import csv_view124
import legacy_runtime as legacy
from source_v6 import HERE, ROOT, MIRROR, SESSIONS, SYMBOLS, read, save, digest, sources


def guard(manifest: dict, fixed: dict, registered: dict) -> dict:
    """
    機能: 登録と源・人工・新一場入力の正式拘束を、入力本文読取前に確認する。
    引数: manifest/fixed/registered(dict)は根が作る固定資料と登録全出力。
    返り値: dictは今回E01領域の源指紋。不一致は実行を拒否する。
    """
    assert manifest['passed'] and manifest['sessions']==list(SESSIONS)
    assert len(manifest['inputs'])==6
    expected={(SESSIONS[0],s,k) for s in SYMBOLS for k in ('book','candle_1min','candle_5min')}
    assert {(i['session'],i['symbol'],i['kind']) for i in manifest['inputs']}==expected
    current=sources()
    assert registered['終了コード']==0
    row=json.loads(registered['stdout'])
    assert row['spec']['implementation']==fixed['sources']
    for path,value in current.items():
        assert fixed['sources'][path]==value, path
    meta=fixed['input_manifest']
    assert digest(ROOT/meta['path'])==meta['sha256']
    assert read(ROOT/meta['path'])==manifest
    assert meta in row['spec']['data']['input_manifests']
    proof=fixed['e01_artificial']
    assert digest(ROOT/proof['path'])==proof['sha256']
    checked=read(ROOT/proof['path'])
    assert checked['passed'] and checked['sources']==current
    for item in manifest['inputs']:
        target=(ROOT/item['staged_path']).resolve()
        assert target.is_relative_to(HERE.parent/'inputs')
        assert target.stat().st_size==item['bytes'] and len(item['sha256'])==64
    return current


def stage(manifest: dict) -> list[dict]:
    """
    機能: 根が一回保存した6素材だけから旧consumer用表示を新所有域へ作る。
    引数: manifest(dict)は新一場の所有入力目録。
    返り値: list[dict]は読取と時計資格の記録。元原本追加読取は0。
    """
    output=[]
    for item in manifest['inputs']:
        origin=ROOT/item['staged_path'];target=MIRROR/item['path']
        assert not target.exists()
        target.parent.mkdir(parents=True,exist_ok=True)
        start,end=adapter.bounds(item['session'])
        qualification=None;csv_clock=None
        if item['kind']=='book':
            qualification=adapter.clock_adapter.write_view(origin,target,item['sha256'],start,end)
            save(HERE/'clock_masks'/item['symbol']/(item['session']+'.json'),
                dict(qualification,session=item['session'],symbol=item['symbol']))
            actual=qualification['original_SHA256']
        else:
            payload=origin.read_bytes();actual=hashlib.sha256(payload).hexdigest()
            assert actual==item['sha256']
            csv_view=csv_view124.write(payload,target,item['sha256'],start,end)
            csv_clock=adapter.clock_adapter.validate_csv(target,start,end)
            csv_clock['consumer_view']=csv_view
        assert actual==item['sha256']
        output.append(dict(item,owned_path=target.relative_to(ROOT).as_posix(),
            clock_qualification=qualification,csv_clock_guard=csv_clock,original_reads=0,
            staged_copy_reads=1))
    return output


def packet(path: Path, value: dict) -> dict:
    """
    機能: 新二口座の入力又は台帳を同一性付きで保存する。
    引数: path(Path)、value(dict)は所有位置と内容。
    返り値: dictは位置・SHA256・bytes。旧cacheを変更しない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(), str(path)
    payload=gzip.compress(pickle.dumps(value,protocol=5),compresslevel=4,mtime=0)
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(payload)
    return dict(path=path.relative_to(ROOT).as_posix(),SHA256=hashlib.sha256(payload).hexdigest(),bytes=len(payload))


def scope_guard(fixed: dict) -> None:
    """
    機能: 実行されたrepo数値源とJIT保存先を今回の固定所有域へ限定する。
    引数: fixed(dict[str,str])は今回E01の源指紋。
    返り値: None。旧module直接実行と未固定依存を拒否する。
    """
    import sys
    from numba.core.registry import CPUDispatcher
    for module in tuple(sys.modules.values()):
        name=getattr(module,'__file__',None)
        if not name:continue
        path=Path(name).resolve()
        if path.suffix!='.py' or not path.is_relative_to(ROOT/'work'):continue
        assert path.is_relative_to(HERE), ('所有域外module',str(path))
        assert path.relative_to(ROOT).as_posix() in fixed, ('未固定module',str(path))
        for function in vars(module).values():
            if isinstance(function,CPUDispatcher):
                locator=getattr(getattr(getattr(function,'_cache',None),'_impl',None),'_locator',None)
                if locator is not None:
                    assert Path(locator._cache_path).resolve().is_relative_to(HERE),str(locator._cache_path)


def normalize_orders(result: dict, account: dict) -> list[dict]:
    """
    機能: 実注文の原seq・価格時計・両気配・料金とUIDを小結果にも保存する。
    引数: result/account(dict)は完成実政策とその入力。
    返り値: list[dict]は当時保存値。約定時刻や欠測を推測しない。
    """
    rows=[]
    for index,order in enumerate(result['orders']):
        row=int(order[0])
        rows.append(dict(index=index,order=order.tolist(),uid=int(result['order_uids'][index]),
            fee=int(result['order_fees'][index]),raw_seq=int(account['record']['seq'][row]),
            price_time_s=float(account['record']['time_s'][row]),bid=float(account['quotes']['bid'][row]),
            ask=float(account['quotes']['ask'][row]),quote_valid=bool(account['quotes']['quote_valid'][row])))
    return rows


def execute(fixed_path: Path, registration_path: Path) -> None:
    """
    機能: 根の正式登録後、追加一場2金融だけを一回実行して保存する。
    引数: fixed_path/registration_path(Path)は根の固定と登録全出力。
    返り値: None。旧40会計は再生も引用集計も行わない。
    """
    fixed=read(fixed_path);manifest=read(ROOT/fixed['input_manifest']['path'])
    before=guard(manifest,fixed,read(registration_path))
    assert not (HERE/'measurement').exists() and not (HERE/'実行開始.json').exists()
    save(HERE/'実行開始.json',dict(start=time.time(),sources=before,new_financial_accounts=2,
        original_reads=0,old_financial_accounts=0))
    logs=stage(manifest)
    save(HERE/'所有六素材のconsumer資格表示.json',dict(passed=True,read_log=logs,original_reads=0))
    rows=[];details=[];cache=[]
    assert not (HERE/'jit_financial').exists(), '金融専用JITは未使用でなければならない'
    legacy.CACHE=str(HERE/'jit_financial')
    with legacy.isolated(discover=False):
        rt=legacy.runtime();modules=adapter.engine_modules();selected=adapter.selected_configs(modules)
        scope_guard(before)
        for scene in SESSIONS:
            folder=MIRROR/'work/v6_prepared'/scene
            folder.mkdir(parents=True,exist_ok=False)
            rt['extractor'].HERE=folder
            ready_inputs,depth=rt['extractor'].extract(scene)
            signals=rt['extractor'].signal_audit(ready_inputs,depth)
            assert read(folder/'信号監査.json')['全合格']
            features=legacy.inject(rt,ready_inputs,signals)
            assert set(features)==set(ready_inputs)=={(scene,s) for s in SYMBOLS}
            for symbol in SYMBOLS:
                with np.load(folder/'features'/f'約定系列_{symbol}_{scene}.npz',allow_pickle=False) as source:
                    tape={k:source[k] for k in source.files}
                ready=ready_inputs[scene,symbol];quotes=adapter.quote_mapping(ready,tape)
                account,diagnosis=adapter.make_account(rt,scene,symbol,ready,quotes,features[scene,symbol])
                scope_guard(before)
                saved_input=packet(HERE/'measurement/input'/symbol/(scene+'.pkl.gz'),account)
                raw=modules['interface'].execute(account,selected[symbol]['entry_id'],selected[symbol]['execution_id'])
                ctx=modules['interface'].prepared(scene,account,raw['values'],finish=True)
                result=modules['interface'].apply(ctx,selected[symbol],raw['gate'],fak_events=raw['fak_events'])
                assert result['summary']['全会計合格']
                assert not result['long_qty'][-1] and not result['short_qty'][-1]
                row=adapter.account_row(scene,symbol,result)
                row['origin']='00124追加一場の固定二設定'
                assert np.isclose(row['profit']-row['loss'],row['net'],atol=1e-5,rtol=1e-12)
                saved_ledger=packet(HERE/'measurement/ledger'/symbol/(scene+'.pkl.gz'),result)
                rows.append(row)
                details.append(adapter.primitive(dict(session=scene,symbol=symbol,actual_config=adapter.ACTUAL[symbol],
                    summary=result['summary'],goal_anchor=result['goal_anchor'],exit_boundary=result['exit_boundary'],
                    control=result['control'],parent=result['parent'],actual_legs=result['actual_legs'],
                    uid_accounts=result['uid_accounts'],orders=normalize_orders(result,account),
                    gate_diagnostics=raw['gate']['diagnostics'],fak_columns=result['fak_columns'],
                    fak_events=result['fak_events'],diagnosis=diagnosis)))
                cache.append(dict(session=scene,symbol=symbol,input=saved_input,ledger=saved_ledger))
                print(scene+' '+symbol+' 固定一会計を保存',flush=True)
        scope_guard(before)
    assert sources()==before and len(rows)==2
    save(HERE/'追加一場の固定少額E01二商品.json',dict(passed=True,sessions=list(SESSIONS),
        actual_config=adapter.ACTUAL,rows=rows,accounts=details,cache=cache,sources=before,
        financial_accounts=2,original_market_reads=0,old_financial_accounts=0,API=0,real_orders=0,
        limitations='旧40は別保存引用。追加一場で安定性確立とはしない。実小型板と真受信順は未観測。'))


def main() -> None:
    """
    機能: 根専用フラグと明示固定・登録資料を必要とする実行入口。
    引数: なし。コマンド引数は--fixed、--registration、--root-run。
    返り値: None。準備や人工からはこの入口を呼ばない。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--fixed',type=Path,required=True)
    parser.add_argument('--registration',type=Path,required=True)
    parser.add_argument('--root-run',action='store_true',required=True)
    args=parser.parse_args();assert args.root_run
    execute(args.fixed,args.registration)


if __name__=='__main__':
    main()
