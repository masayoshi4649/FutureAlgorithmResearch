"""実際の復帰を二価格時計で確認する八条件を、独立両脚と準備系譜で保存する。"""

from datetime import datetime,timezone,timedelta
from io import BytesIO
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

import numpy as np


HERE=Path(__file__).resolve().parent
BASE=HERE.parent
ROOT=BASE.parents[1]
os.environ['NUMBA_CACHE_DIR']=str(HERE/'jit_cache')
sys.dont_write_bytecode=True
import engine_v8


METHODS=('ratio_mr','ols_mr')
LOOKBACKS=(30,60)
SYMBOLS=('NK225','TOPIX')
RESULT_NAME='相対乖離の実際の復帰確認と全四十場.json'


def read(path: Path) -> dict:
    """
    機能: 小目録又は根担当の登録証跡を読む。
    引数: path(Path)はUTF-8 JSON。
    返り値: dict。市場原本を読まない。
    """
    return json.loads(path.read_text(encoding='utf8'))


def clean(value: object) -> object:
    """
    機能: NumPy集計型を標準JSON型へ変換し、未知をnullで保持する。
    引数: value(object)は小会計又は系譜。
    返り値: objectはJSON互換。未知を利益や零へ補完しない。
    """
    if isinstance(value,dict):return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [clean(v) for v in value]
    if isinstance(value,np.ndarray):return clean(value.tolist())
    if isinstance(value,np.generic):return clean(value.item())
    if isinstance(value,float) and not math.isfinite(value):return None
    return value


def save(path: Path,value: dict) -> None:
    """
    機能: 計画や金融結果を既存の成果へ重ねず保存する。
    引数: path(Path)、value(dict)は出力先と値。
    返り値: None。UTF-8で新規作成する。
    """
    assert not path.exists(),path
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(clean(value),ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')


def make_specs() -> list[dict]:
    """
    機能: 固定過去モデルの実復帰確認と二退出を八条件として先に定義する。
    引数: なし。
    返り値: list[dict]は比率/OLS×30/60×極値撤回/追尾の固定仕様。
    """
    specs=[]
    for method in METHODS:
        for lookback in LOOKBACKS:
            for exit_mode in (0,1):
                label='極値撤回型' if exit_mode==0 else '残差改善の追尾型'
                specs.append(dict(id=f'{method.upper()}_CONF_L{lookback}_X{exit_mode}',family='confirmed_mr',
                    model_family=method,name=('NT比' if method=='ratio_mr' else '回帰残差')+f'・{lookback}分・'+label,
                    description='過去モデルを乖離2σで固定。極値から0.5σの実復帰を別価格clock2回確認してから相対回帰を予約する。',
                    method=method,lookback=lookback,exit_mode=exit_mode,symbol='PAIR'))
    return specs


def settings(scene: str,spec: dict) -> dict:
    """
    機能: 一つの組口座について固定methodと場内の締切を与える。
    引数: scene(str)は日付とDay/Night、spec(dict)は八固定条件の一つ。
    返り値: dictは核心へ渡す八設定。数量・閾値を成績から変更しない。
    """
    start=datetime.fromisoformat(scene[:10]).replace(tzinfo=timezone(timedelta(hours=9)))
    assert scene.endswith(('_Day','_Night'))
    close=start+(timedelta(days=1,hours=5,minutes=40) if scene.endswith('_Night') else timedelta(hours=15,minutes=20))
    return dict(method=spec['method'],lookback=spec['lookback'],exit_mode=spec['exit_mode'],entry_end=close.timestamp()-1200,close_time=close.timestamp())


def load_market(item: dict) -> tuple[dict,dict]:
    """
    機能: 既所有preparedを一読し、保存済みbarsとquotesだけを射影する。
    引数: item(dict)は目録の位置・SHA・byte数。
    返り値: tuple[dict,dict]は足と気配。旧policy・損益・後続結果を使用しない。
    """
    path=ROOT/item['owned_path'];payload=path.read_bytes()
    assert len(payload)==item['bytes'] and hashlib.sha256(payload).hexdigest()==item['SHA256']
    with np.load(BytesIO(payload),allow_pickle=False) as source:
        bars={key[6:]:source[key].copy() for key in source.files if key.startswith('bars__')}
        quotes={key[8:]:source[key].copy() for key in source.files if key.startswith('quotes__')}
    assert bars and quotes
    return bars,quotes


def verify_run_contract() -> tuple[dict,dict,dict]:
    """
    機能: 登録した入力と実装そのものへ実運転を結合する。
    引数: なし。
    返り値: tuple[dict,dict,dict]は固定・目録・正式計画。未登録や既存結果では停止する。
    """
    fixed=read(HERE/'固定計画.json');proposal=read(HERE/'試行計画.json')
    checked=read(HERE/'正式照合の全出力.json');registered=read(HERE/'正式登録の全出力.json')
    assert checked['終了コード']==registered['終了コード']==0 and json.loads(checked['stdout'])['proposal_complete'] is True
    enrolled=json.loads(registered['stdout']);assert enrolled['id']==proposal['id'] and enrolled['spec']==proposal['spec']
    assert proposal['spec']['implementation']==fixed['sources']
    for path,sha in fixed['sources'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==sha,path
    manifest=fixed['input_manifest'];path=ROOT/manifest['path']
    assert proposal['spec']['data']['input_manifests']==[manifest] and path.resolve()==(HERE/'入力目録.json').resolve()
    payload=path.read_bytes();assert hashlib.sha256(payload).hexdigest()==manifest['sha256']
    meta=json.loads(payload.decode('utf8'))
    assert meta['sessions']==proposal['spec']['data']['sessions'] and len(meta['sessions'])==len(set(meta['sessions']))==40
    assert len(meta['inputs'])==80 and {(i['session'],i['symbol']) for i in meta['inputs']}=={(s,k) for s in meta['sessions'] for k in SYMBOLS}
    assert meta['specs']==make_specs()
    return fixed,meta,proposal


def pack_answer(ident: str,answer: dict,leg_key: str,leg_codes: dict) -> tuple[dict,dict]:
    """
    機能: 核心の組資産・系譜と、各脚の実注文を型を変えず分ける。
    引数: ident(str)、answer(dict)、leg_key(str)は注文列名、leg_codes(dict[str,int])は脚コード。
    返り値: tuple[dict,dict]は組npz用配列と各商品npz用配列。
    """
    arrays={key:np.asarray(answer[key]) for key in ('orders','parents','curve','models','positions','preparations')}
    assert all(value.dtype.kind!='O' for value in arrays.values())
    assert arrays['orders'].ndim==arrays['parents'].ndim==arrays['curve'].ndim==arrays['models'].ndim==arrays['preparations'].ndim==2
    assert arrays['preparations'].shape[1]==len(engine_v8.PREPARATION_COLUMNS)
    assert arrays['orders'].shape[1]==len(engine_v8.ORDER_COLUMNS)
    assert arrays['parents'].shape[1]==len(engine_v8.PARENT_COLUMNS)
    assert arrays['curve'].shape[1]==len(engine_v8.CURVE_COLUMNS) and arrays['models'].shape[1]==len(engine_v8.MODEL_COLUMNS)
    column=engine_v8.ORDER_COLUMNS.index(leg_key)
    assert set(leg_codes)==set(SYMBOLS) and len(set(leg_codes.values()))==2
    assert set(arrays['orders'][:,column]).issubset(set(leg_codes.values()))
    packed={ident+'__'+key:value for key,value in arrays.items()}
    legs={symbol:{ident+'__orders':arrays['orders'][arrays['orders'][:,column]==code].copy()} for symbol,code in leg_codes.items()}
    return packed,legs


def store_npz(path: Path,arrays: dict) -> dict:
    """
    機能: 既存cacheを上書きせず配列とSHAを保存する。
    引数: path(Path)とarrays(dict[str,ndarray])は出力先と配列。
    返り値: dictは相対位置・SHA・byte数。
    """
    assert not path.exists();path.parent.mkdir(parents=True,exist_ok=True)
    memory=BytesIO();np.savez_compressed(memory,**arrays);payload=memory.getvalue();path.write_bytes(payload)
    return dict(path=path.relative_to(ROOT).as_posix(),SHA256=hashlib.sha256(payload).hexdigest(),bytes=len(payload))


def decompose_parents(parents: np.ndarray) -> dict:
    """
    機能: 完結二脚のgrossを相対変化とβ調整後の共通元本差へ厳密分解する。
    引数: parents(ndarray[float64,N,46])は核心が保存した実親。売買判断へ返さない。
    返り値: dictは親別の事後診断と合計。単脚・未清算の二要因は未知のままにする。
    """
    columns={name:i for i,name in enumerate(engine_v8.PARENT_COLUMNS)}
    result=[];totals=dict(paired_parents=0,single_leg_parents=0,unclosed_parents=0,
        relative_gross=0.,common_gross=0.,paired_gross=0.,paired_fees=0.,paired_net=0.,
        single_leg_gross=0.,single_leg_fees=0.,single_leg_net=0.)
    for row in parents:
        value={name:float(row[index]) for name,index in columns.items()}
        gross=value['gross_nk']+value['gross_top'];fees=value['fees_nk']+value['fees_top']
        complete=value['complete']==1.;paired=complete and value['filled_legs']==2.
        relative=common=None
        if paired:
            s=value['side_nk'];a=value['target_quantity_nk']*10.*value['entry_nk']
            b=value['target_quantity_top']*1000.*value['entry_top'];beta=value['beta']
            rn=value['exit_nk']/value['entry_nk']-1.;rt=value['exit_top']/value['entry_top']-1.
            relative=s*a*(rn-beta*rt);common=s*(beta*a-b)*rt
            assert math.isclose(relative+common,gross,rel_tol=1e-10,abs_tol=1e-5),'相対と共通要因のgross和'
            assert math.isclose(gross-fees,value['net'],rel_tol=1e-10,abs_tol=1e-5),'実費用控除後net'
            totals['paired_parents']+=1
            for key,amount in (('relative_gross',relative),('common_gross',common),('paired_gross',gross),('paired_fees',fees),('paired_net',value['net'])):totals[key]+=amount
        elif complete:
            assert value['filled_legs']==1. and math.isclose(gross-fees,value['net'],rel_tol=1e-10,abs_tol=1e-5)
            totals['single_leg_parents']+=1
            for key,amount in (('single_leg_gross',gross),('single_leg_fees',fees),('single_leg_net',value['net'])):totals[key]+=amount
        else:totals['unclosed_parents']+=1
        result.append(dict(parent=int(value['parent']),kind='paired' if paired else 'single_leg' if complete else 'unclosed',
            relative_gross=relative,common_gross=common,gross=gross,fees=fees,net=value['net']))
    return dict(scope='事後会計の恒等式。相対要因が予測できたという証拠ではない。未清算のnetには参考時価を含む。',totals=totals,parents=result)


def main() -> None:
    """
    機能: 根担当の登録後、既所有80入力を一読して八条件×40組を実行する。
    引数: なし。API・原市場・実注文は使用しない。
    返り値: None。320組小会計、40組cache、80脚cacheと実親明細を保存する。
    """
    fixed,meta,proposal=verify_run_contract();output=HERE/'measurement';assert not output.exists();output.mkdir()
    specs=make_specs();lookup={(i['session'],i['symbol']):i for i in meta['inputs']}
    all_rows=[];episodes=[];diagnostics=[];pair_caches=[];leg_caches=[];reads=[];clock=time.monotonic()
    leg_key=meta['order_leg_column'];leg_codes=meta['leg_codes']
    for i,scene in enumerate(meta['sessions']):
        material={}
        for symbol in SYMBOLS:
            item=lookup[scene,symbol];material[symbol]=load_market(item)
            reads.append(dict(session=scene,symbol=symbol,path=item['owned_path'],SHA256=item['SHA256'],original_market_reads=0))
            with (output/'保存入力読取.jsonl').open('a',encoding='utf8') as stream:stream.write(json.dumps(reads[-1],ensure_ascii=False)+'\n')
        paired={};legs={symbol:{} for symbol in SYMBOLS};scene_rows=[];scene_episodes=[]
        for spec in specs:
            ident=spec['id'];answer=engine_v8.run_pair(material['NK225'][0],material['TOPIX'][0],material['NK225'][1],material['TOPIX'][1],settings(scene,spec))
            row=dict(session=scene,symbol='PAIR',method=ident,**clean(answer['summary']),legs=clean(answer['leg_summary']))
            all_rows.append(row);scene_rows.append(row)
            arrays,leg_arrays=pack_answer(ident,answer,leg_key,leg_codes);paired.update(arrays)
            for symbol in SYMBOLS:legs[symbol].update(leg_arrays[symbol])
            decomposition=decompose_parents(answer['parents'])
            diagnostics.append(dict(session=scene,symbol='PAIR',method=ident,**decomposition))
            episode=dict(session=scene,symbol='PAIR',method=ident,parents=clean(answer['parents']),orders=clean(answer['orders']),preparations=clean(answer['preparations']),diagnostics=decomposition)
            episodes.append(episode);scene_episodes.append(episode)
        pair_caches.append(dict(session=scene,**store_npz(output/'PAIR'/(scene+'.npz'),paired)))
        for symbol in SYMBOLS:
            leg_caches.append(dict(session=scene,symbol=symbol,**store_npz(output/symbol/(scene+'.npz'),legs[symbol])))
            save(output/symbol/(scene+'.json'),dict(session=scene,symbol=symbol,rows=[dict(method=row['method'],**row['legs'][symbol]) for row in scene_rows]))
        save(output/'PAIR'/(scene+'.json'),dict(rows=scene_rows,episodes=scene_episodes))
        print(f'{i+1}/40 {scene} / 既所有入力{len(reads)} / {time.monotonic()-clock:.1f}秒',flush=True)
    assert len(all_rows)==len(episodes)==320 and len(reads)==len(leg_caches)==80 and len(pair_caches)==40
    after={path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in fixed['sources']}
    assert after==fixed['sources']
    save(output/RESULT_NAME,dict(sessions=meta['sessions'],splits=meta['splits'],specs=specs,runs=all_rows,episodes=episodes,
        cache=pair_caches,leg_cache=leg_caches,diagnostics=diagnostics,source_SHA256=fixed['sources'],source_end_SHA256=after,reads=reads,trial=proposal['id'],
        columns=dict(orders=engine_v8.ORDER_COLUMNS,parents=engine_v8.PARENT_COLUMNS,curve=engine_v8.CURVE_COLUMNS,models=engine_v8.MODEL_COLUMNS,preparations=engine_v8.PREPARATION_COLUMNS),
        原市場追加読取=0,API=0,実注文=0,留保='全40場は既知開発。二脚の組収支であり、二銘柄単独の黒字成功と混同しない。未約定を勝ちにせず、片脚・未清算を完成ペアの成功と呼ばない。'))
    print('復帰二確認八条件・320組口座、準備系譜と80脚明細を保存しました。',flush=True)


if __name__=='__main__':
    main()
