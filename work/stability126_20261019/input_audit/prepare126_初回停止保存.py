"""保存済み元E01素材を一読し、金融を行わず全41場の所有入力を作る。"""

from io import BytesIO
import hashlib
import json
from pathlib import Path
import pickle
import sys
import time

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ENGINE = HERE.parent / 'engine'
OUT = HERE / 'prepared126'
sys.dont_write_bytecode = True
sys.path.insert(0, str(ENGINE))
import legacy126 as legacy
import policy126 as policy
import source126 as source

READS = []
READ_NAMES = set()
PACKETS = []


def metadata(relative: str) -> dict:
    """
    機能: 小目録を読む。
    引数: relative(str)はプロジェクト相対JSON位置。
    返り値: dictは保存内容。
    """
    return json.loads((ROOT / relative).read_text(encoding='utf-8'))


def save(path: Path, value: dict) -> None:
    """
    機能: 自所有域の未使用位置だけへ有限JSONを保存する。
    引数: path(Path)、value(dict)は保存先と内容。
    返り値: None。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(), str(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def journal(record: dict) -> None:
    """
    機能: 市場派生素材の一回読取を逐次保存する。
    引数: record(dict)は内容指紋・読取位置・資格。
    返り値: None。
    """
    READS.append(record)
    with (HERE/'保存入力の一読履歴.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False)+'\n')


def payload(item: dict, *, kind: str = '保存市場派生') -> bytes:
    """
    機能: 保存素材を重複なく一読し、既存SHAを実bytesと照合する。
    引数: item(dict)はpath/expected_sha256/bytes、kind(str)は読取区分。
    返り値: bytesは照合済み内容。原本3領域は拒否する。
    """
    name = item['path'].replace('\\', '/')
    assert name.startswith('work/') and name not in READ_NAMES, name
    path = ROOT / name
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    journal(dict(path=name, kind=kind, sha256=actual, expected_sha256=item['expected_sha256'],
                 bytes=len(raw), matches=actual==item['expected_sha256'], original_reads=0))
    READ_NAMES.add(name)
    assert actual==item['expected_sha256'] and len(raw)==item['bytes'], name
    return raw


def load(item: dict) -> object:
    """
    機能: 同一性を確認した保存pklを解釈する。
    引数: item(dict)は保存素材目録。
    返り値: objectは元の型・配列を保持した保存値。
    """
    assert item['path'].endswith('.pkl')
    return pickle.loads(payload(item))


def array_digest(value: object) -> str:
    """
    機能: 元配列の型・形・内容を計算改変せず指紋化する。
    引数: value(object)は配列互換値。
    返り値: strはSHA256。
    """
    array = np.ascontiguousarray(value)
    digest = hashlib.sha256(repr((array.dtype.str, array.shape)).encode())
    digest.update(array.tobytes())
    return digest.hexdigest()


def quote_mapping(ready: dict, quotes: dict) -> dict:
    """
    機能: 保存気配を同一原seq・価格時計・Lastだけで元入力へ結合する。
    引数: ready/quotes(dict)は元入力と保存気配。
    返り値: dictは同一原行のbid/ask/quote_valid。正常行への間引きは行わない。
    """
    raw = np.asarray(ready['seq']); saved = np.asarray(quotes['seq'])
    assert len(saved) and np.all(np.diff(saved)>0)
    index = np.searchsorted(saved, raw)
    assert np.all(index<len(saved)) and np.array_equal(raw,saved[index])
    np.testing.assert_array_equal(ready['time_s'],quotes['time_s'][index])
    price = quotes['price'] if 'price' in quotes else quotes['last']
    np.testing.assert_array_equal(ready['last'],price[index])
    bid=np.asarray(quotes['bid'][index],float);ask=np.asarray(quotes['ask'][index],float)
    valid=np.isfinite(bid)&np.isfinite(ask)&(bid>0)&(ask>bid)
    if 'quote_valid' in quotes:valid &= np.asarray(quotes['quote_valid'][index],bool)
    return dict(seq=raw.copy(),time_s=np.asarray(ready['time_s']).copy(),bid=bid,ask=ask,quote_valid=valid)


def ready_record(ready: dict) -> dict:
    """
    機能: 元入力のshape・順序・保存値指紋と後分類用値動きを記録する。
    引数: ready(dict)は元E01入力。
    返り値: dictは金融判断へ逆流させない入力資格・後分類用metadata。
    """
    n=len(ready['last'])
    for name in ('seq','time_s','last','atr'):
        value=np.asarray(ready[name])
        assert value.ndim==1 and len(value)==n, (ready['session'],ready['symbol'],name,value.shape)
    assert n>0 and np.all(np.diff(ready['seq'])>0) and np.all(np.diff(ready['time_s'])>=0)
    assert ready['time_s'][-1]>ready['limit']
    ok=np.isfinite(ready['last'])&(ready['last']>0)
    indices=np.flatnonzero(ok);assert len(indices)
    first,last=int(indices[0]),int(indices[-1])
    a,b=float(ready['last'][first]),float(ready['last'][last]);change=b-a
    return dict(session=ready['session'],symbol=ready['symbol'],rows=n,
        input_arrays={name:array_digest(ready[name]) for name in ('seq','time_s','last','atr')},
        shapes={name:list(np.asarray(ready[name]).shape) for name in ('seq','time_s','last','atr')},
        first_last=a,final_last=b,first_time=float(ready['time_s'][first]),final_time=float(ready['time_s'][last]),
        first_seq=int(ready['seq'][first]),final_seq=int(ready['seq'][last]),
        observed_high=float(np.max(ready['last'][ok])),observed_low=float(np.min(ready['last'][ok])),
        change=change,change_ratio=change/a,direction=int(np.sign(change)),
        large_direction=int(np.sign(change)) if abs(change/a)>=.0025 else 0,
        retrospective_only=True,end_is_official_close=False,
        start=float(ready['start']),limit=float(ready['limit']),last_time=float(ready['time_s'][-1]))


def market_prefix(inputs: dict, full: dict) -> list[dict]:
    """
    機能: 新市場特徴が入力未来尾に依存しないことを非金融で確認する。
    引数: inputs/full(dict)は当場両商品と全長市場特徴。
    返り値: list[dict]は二つの同時価格時刻切断の結果。
    """
    end=min(float(v['time_s'][-1]) for v in inputs.values())
    start=max(float(v['time_s'][0]) for v in inputs.values());proof=[]
    for fraction in (.37,.73):
        cut=start+(end-start)*fraction;short={};counts={}
        for key,ready in inputs.items():
            n=int(np.searchsorted(ready['time_s'],cut,side='left'))
            assert n>0
            counts[key]=n
            short[key]={name:np.asarray(ready[name])[:n] for name in ('time_s','last','atr')}
        calculated=policy.make_market(short)
        for key,n in counts.items():np.testing.assert_array_equal(calculated[key],full[key][:n])
        proof.append(dict(fraction=fraction,cut=cut,passed=True))
    return proof


def packet(rt: dict, scene: str, inputs: dict, signals: dict, quotes: dict,
           references: list[str], signal_proof: dict | None) -> None:
    """
    機能: 元十列と新市場特徴を場ごと一度だけ所有保存する。
    引数: rt(dict)、scene(str)、inputs/signals/quotes(dict)、references(list[str])、signal_proof(dict|None)。
    返り値: None。買売再生・影再生・収支計算は行わない。
    """
    assert set(inputs)=={(scene,symbol) for symbol in ('TOPIX','NK225')}
    records=[ready_record(v) for v in inputs.values()]
    features=policy.original_features(rt,inputs,signals)
    markets=policy.make_market(inputs)
    prefix=market_prefix(inputs,markets)
    for key,ready in inputs.items():
        n=len(ready['last'])
        assert len(signals['entry'][key])==n
        assert all(len(v)==n for v in features[key]['columns'])
        assert features[key]['valid'].shape==(n,)
        assert markets[key].shape==(n,len(policy.MARKET_COLUMNS))
        assert not features[key]['gate'].any() and not features[key]['ema'][3].any()
        for code in ('B00','B01'):
            rows=np.asarray(signals[code][key]['source_row'])
            assert np.all(rows<=np.arange(n))
    target=OUT/(scene+'.pkl');assert not target.exists()
    value=dict(session=scene,inputs=inputs,signals=signals,features=features,markets=markets,
               quotes=quotes,source_refs=references)
    raw=pickle.dumps(value,protocol=5);target.write_bytes(raw)
    row=dict(session=scene,path=target.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(raw).hexdigest(),
             bytes=len(raw),accounts=records,source_refs=references,market_prefix=prefix,
             signal_causal_audit=signal_proof,financial_replays=0)
    PACKETS.append(row)
    save(OUT/(scene+'.json'),row)
    print(scene+' 元入力・元十列・市場特徴を非金融保存',flush=True)


def copy_candles(manifest: dict) -> list[dict]:
    """
    機能: 追加8場用の所有consumer1分足16個だけを同bytes複写する。
    引数: manifest(dict)は今回の保存素材目録。
    返り値: list[dict]は読取・同一性。原CSV・5分足・旧33CSVは読まない。
    """
    old=metadata('work/stability119_20261017/v6_resume/入力目録.json')
    old_hash={(v['session'],v['symbol']):v['SHA256'] for v in old['inputs'] if v['kind']=='candle_1min'}
    new=metadata('work/stability124_20261019/e01c/所有六素材のconsumer資格表示.json')
    new_hash={(v['session'],v['symbol']):v['csv_clock_guard']['consumer_view']['view_sha256']
              for v in new['read_log'] if v['kind']=='candle_1min'}
    result=[]
    for row in manifest['additional_clock_qualification']:
        item=next(v for v in row['csv'] if v['kind']=='candle_1min')
        expected=(new_hash if row['session']=='2026-10-19_Day' else old_hash)[row['session'],row['symbol']]
        raw=payload(dict(item,expected_sha256=expected),kind='所有consumer一分足')
        # 元信号生成器は自己所有mirrorのcandle_1minだけを読む。
        target=HERE/'consumer126/candle_1min'/row['symbol']/(row['session']+'.csv')
        assert not target.exists();target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        result.append(dict(path=target.relative_to(ROOT).as_posix(),sha256=expected,bytes=len(raw)))
    assert len(result)==16
    return result


def execute() -> None:
    """
    機能: 58保存素材を一読・同一性照合し、全41場82口座を非金融準備する。
    引数: なし。
    返り値: None。再生成するのは追加8場の元信号と全場の旧十列・新市場特徴のみ。
    """
    assert not OUT.exists() and not (HERE/'準備開始.json').exists()
    manifest=metadata('work/stability126_20261019/input_audit/原版E01全四十一場の保存入力候補と時計資格.json')
    items={v['path']:v for v in manifest['saved_inputs']};assert len(items)==58
    save(HERE/'準備開始.json',dict(start=time.time(),manifest_sha256=source.digest(HERE/'原版E01全四十一場の保存入力候補と時計資格.json'),
        sources=source.sources(),producer_sha256=source.digest(Path(__file__)),expected_saved_inputs=58,
        original_market_reads=0,financial_replays=0,API=0))
    OUT.mkdir()
    candles=copy_candles(manifest)
    quote_path='work/wave_v106/e01_reference/prepared/quotes.pkl'
    all_quotes=load(items[quote_path])
    before=source.sources();legacy.CACHE=str(HERE/'jit_prepare126')
    with legacy.isolated(discover=False):
        rt=legacy.runtime()
        old=metadata('work/wave_v85/prepared/入力準備の完了.json')
        for pair in old['入力対応']:
            a,b=pair['inputs'].replace('\\','/'),pair['signals'].replace('\\','/')
            inputs,signals=load(items[a]),load(items[b])
            for scene in sorted({key[0] for key in inputs}):
                own={key:value for key,value in inputs.items() if key[0]==scene}
                sig={code:{key:value for key,value in values.items() if key in own} for code,values in signals.items()}
                q={key:quote_mapping(ready,all_quotes[key]) for key,ready in own.items()}
                packet(rt,scene,own,sig,q,[a,b,quote_path],None)
        for scene in manifest['groups']['追加3']:
            base='work/wave_v106/e01_reference/prepared/'+scene+'/'
            names=[base+n for n in ('new_inputs.pkl','signals.pkl','quotes.pkl')]
            inputs,signals,local_quotes=[load(items[name]) for name in names]
            q={key:quote_mapping(ready,all_quotes[key]) for key,ready in inputs.items()}
            for key,ready in inputs.items():
                other=quote_mapping(ready,local_quotes[key])
                for field in q[key]:np.testing.assert_array_equal(q[key][field],other[field])
            packet(rt,scene,inputs,signals,q,names+[quote_path],None)
        del all_quotes
        # ----------------------------------------
        # 旧信号生成器のROOTだけを所有consumerへ注入する。数値式・足値は不変。
        rt['extractor'].ROOT=HERE/'consumer126'
        for scene in manifest['groups']['追加8']:
            group=[v for v in items.values() if v.get('session')==scene]
            inp=next(v for v in group if v['path'].endswith('/new_inputs.pkl'))
            dep=next(v for v in group if v['path'].endswith('/new_features_depth.pkl'))
            inputs,depth=load(inp),load(dep)
            q={}
            for symbol in ('TOPIX','NK225'):
                item=next(v for v in group if v.get('symbol')==symbol and v['path'].endswith('.npz'))
                with np.load(BytesIO(payload(item)),allow_pickle=False) as tape:
                    q[scene,symbol]=quote_mapping(inputs[scene,symbol],dict(tape))
            audit_folder=HERE/'new_signal_audits'/scene
            audit_folder.mkdir(parents=True,exist_ok=False)
            rt['extractor'].HERE=audit_folder
            signals=rt['extractor'].signal_audit(inputs,depth)
            proof=metadata((audit_folder/'信号監査.json').relative_to(ROOT).as_posix())
            assert proof['全合格']
            packet(rt,scene,inputs,signals,q,[v['path'] for v in group],proof)
    assert source.sources()==before, '準備中の数値源変更'
    assert len(PACKETS)==41 and {v['session'] for v in PACKETS}==set(manifest['sessions'])
    assert set(items).issubset(READ_NAMES) and len(READ_NAMES)==74
    result=dict(passed=True,sessions=manifest['sessions'],packets=sorted(PACKETS,key=lambda x:x['session']),
        input_read_log=READS,owned_consumer_candles=candles,sources=before,
        producer_sha256=source.digest(Path(__file__)),market_columns=list(policy.MARKET_COLUMNS),
        saved_market_inputs=58,owned_csv_inputs=16,original_market_reads=0,financial_replays=0,API=0,real_orders=0,
        contract='旧33信号を同値保存、追加8は旧生成器と所有consumer足。ATR再生成0。gate/emaは無効部品用の未知で、原版mask0及び今回16条件以外へ流用禁止。')
    save(HERE/'全四十一場の元入力と新市場特徴の非金融準備.json',result)
    print('全41場82口座の非金融準備完了、58素材と16所有CSVを各一読、原本0・金融0',flush=True)


if __name__=='__main__':
    try:execute()
    except Exception as error:
        failure=HERE/('準備停止_'+str(time.time_ns())+'.json')
        save(failure,dict(passed=False,error=repr(error),read_log=READS,completed_sessions=[v['session'] for v in PACKETS],
                          original_market_reads=0,financial_replays=0,API=0))
        raise
