"""保有中票の新目的で、保存E01input33と原行NPZ66を各一読する。"""

import argparse
import gc
import hashlib
import io
import pickle
import time
import traceback

import numpy as np

import common
import catalog
import features
import votes

FIELDS=('raw_seq','price_time_s','last','bid','ask','volume_delta','volume_delta_usable','volume_reset_reason','execution_to_raw_index')


def fix() -> None:
    """
    機能: 候補行票を保有中へ流用しない新目的・66NPZ・33既E01cacheを本文前に固定する。
    引数: なし。
    返り値: None。全normal人工と修正代理exactを結ぶ。金融は未実行。
    """
    rawpath=common.ROOT/'work/wave_v106/trade_gate/入力測定前の固定_v2.json'
    inputpath=common.ROOT/'work/wave_v106/e01_trade_gate/全33場のE01取引更新準備.json'
    raw,old=common.read(rawpath),common.read(inputpath)
    art=common.read(common.HERE/'全normal票と逆票損失退出の人工検査.json')
    assert raw['全合格'] and old['全合格'] and art['全合格'] and len(old['sessions'])==33
    assert raw['sessions']==old['sessions'] and art['source_SHA256']==common.source_hashes()
    assert (common.HERE/'votes.py').read_bytes()==(common.ROOT/'work/wave_v106/trade_gate/votes.py').read_bytes()
    assert (common.HERE/'daily.py').read_bytes()==(common.ROOT/'work/wave_v106/e01_daily/core.py').read_bytes()
    common.write(common.HERE/'入力測定前の固定.json',dict(全合格=True,sessions=old['sessions'],configs=catalog.configs(),
        input_cache=old['cache'],raw_inputs=raw['raw_inputs'],source_SHA256=common.source_hashes(),
        input_manifests=[dict(path=p.relative_to(common.ROOT).as_posix(),sha256=common.digest(p)) for p in
            (rawpath,inputpath,common.HERE/'全normal票と逆票損失退出の人工検査.json')],
        目的='元公開行票には保有中の情報がないため、新用途としてnormal全行の当時代理票を原NPZから測る。',
        原NPZ予定読取=66,旧E01input予定読取=33,元paper再生=0,新金融=0,原book=0,API=0))


def load(item: dict, raw: bool=False) -> dict:
    """
    機能: 固定cache又はNPZを一回bytes読取り、同bytesで照合する。
    引数: item(dict)、raw(bool)は位置/指紋と原行形式。
    返り値: dictは保存入力又は必要原列。現在API/生bookへ接続しない。
    """
    path=common.ROOT/item['path'];assert path.resolve().is_relative_to(common.ROOT/'work')
    saved=path.read_bytes();assert hashlib.sha256(saved).hexdigest()==item['SHA256'],path
    if not raw:return pickle.loads(common.gzip.decompress(saved))
    with np.load(io.BytesIO(saved),allow_pickle=False) as source:return {n:source[n] for n in FIELDS}


def run() -> None:
    """
    機能: 各33/66入力を一読し、正常全行のW10/30/60当時票だけを保存する。
    引数: なし。
    返り値: None。GU注文と勝敗は未読、保有時機の選択は金融前にしない。
    """
    fixed=common.read(common.HERE/'入力測定前の固定.json');assert fixed['source_SHA256']==common.source_hashes()
    for i in fixed['input_manifests']:assert common.digest(common.ROOT/i['path'])==i['sha256']
    cache={};availability={};raw_reads=old_reads=0;scalar_checks=0;started=time.monotonic()
    for session in fixed['sessions']:
        old=load(fixed['input_cache'][session]);old_reads+=1
        packet=dict(schema_version=1,session=session,accounts={});availability[session]={}
        for symbol in ('TOPIX','NK225'):
            a=old['accounts'][symbol];r=load(fixed['raw_inputs'][session+'|'+symbol],True);raw_reads+=1
            mapping=r['execution_to_raw_index'];q=a['quotes'];record=a['record']
            for rawname,name in (('raw_seq','seq'),('price_time_s','time_s'),('last','price')):np.testing.assert_array_equal(r[rawname][mapping],record[name])
            for name in ('bid','ask'):np.testing.assert_array_equal(r[name][mapping],q[name])
            ctx=votes.context(r);observed={};availability[session][symbol]={}
            for w in (10,30,60):
                z=features.all_normal(r,ctx,mapping,w);observed[str(w)]=z
                indices=np.unique(np.linspace(0,len(mapping)-1,min(17,len(mapping)),dtype=np.int64))
                for ni in indices:
                    truth=votes.measure(r,ctx,int(mapping[ni]),w,1)
                    assert z['known'][ni]==truth['known'] and int(z['reason'][ni])==truth['reason']
                    assert int(z['up_votes'][ni])==truth.get('measured_up_votes',0)
                    assert int(z['down_votes'][ni])==truth.get('measured_down_votes',0)
                    if truth['balance'] is not None:assert z['balance'][ni]==truth['balance']
                    scalar_checks+=1
                total=z['up_votes'].astype(np.int64)+z['down_votes']
                availability[session][symbol][str(w)]=dict(normal行数=len(mapping),既知行数=int(z['known'].sum()),
                    既知2票以上行数=int(np.count_nonzero(z['known']&(total>=2))))
            packet['accounts'][symbol]=dict(symbol=symbol,quotes=q,record=record,votes=observed)
            del r,ctx
        path=common.HERE/f'input/{session}.pkl.gz';common.write(path,packet)
        cache[session]=dict(path=path.relative_to(common.ROOT).as_posix(),SHA256=common.digest(path))
        del packet,old;gc.collect();print(session+' 全normal保有票準備完了、金融0',flush=True)
    assert raw_reads==66 and old_reads==33 and common.source_hashes()==fixed['source_SHA256']
    common.write(common.HERE/'全33場の保有中取引更新票.json',dict(全合格=True,sessions=fixed['sessions'],cache=cache,
        availability=availability,source_SHA256=fixed['source_SHA256'],開始終端source一致=True,
        事前固定SHA256=common.digest(common.HERE/'入力測定前の固定.json'),原NPZ読取=66,保存E01input読取=33,
        実素材scalar同値照合数=scalar_checks,元paper再生=0,新金融=0,原book=0,API=0,経過秒=time.monotonic()-started))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--fix-only',action='store_true');parser.add_argument('--root-input-reviewed',action='store_true')
    args=parser.parse_args();assert args.fix_only!=args.root_input_reviewed
    if args.fix_only:fix()
    else:
        assert not (common.HERE/'入力準備False.json').exists() and not (common.HERE/'全33場の保有中取引更新票.json').exists()
        try:run()
        except Exception:
            common.write(common.HERE/'入力準備False.json',dict(全合格=False,原因=traceback.format_exc(),source_SHA256=common.source_hashes(),金融=0,自動再開始=False));raise
