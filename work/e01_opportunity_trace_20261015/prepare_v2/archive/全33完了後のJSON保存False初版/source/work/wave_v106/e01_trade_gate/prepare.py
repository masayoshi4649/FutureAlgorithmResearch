"""保存紙上feedと原行NPZを各一読し、E01公開時の票だけを準備する。"""

import argparse
from collections import Counter
import gc
import gzip
import hashlib
import io
import pickle
import time
import traceback

import numpy as np

import common
import catalog
import policy
import votes

FIELDS=('raw_seq','price_time_s','last','bid','ask','volume_delta','volume_delta_usable',
        'volume_reset_reason','execution_to_raw_index')


def fix() -> None:
    """
    機能: 修正済み方向票・人工・33cache/66NPZ/Q資料を大型読取前に固定する。
    引数: なし。
    返り値: None。新金融・原paper再計算・APIを行わない。
    """
    pending_path=common.ROOT/'work/wave_v106/e01_pending_price/全33場の待機取消準備.json'
    raw_path=common.ROOT/'work/wave_v106/trade_gate/入力測定前の固定_v2.json'
    qpath=common.ROOT/'work/wave_v106/e01_reference/prepared/入力準備の完了.json'
    pending,raw,qmeta=(common.read(p) for p in (pending_path,raw_path,qpath))
    art=common.read(common.HERE/'E01公開maskとUID料金及び接頭の人工検査.json')
    assert all(v['全合格'] for v in (pending,raw,qmeta,art))
    assert pending['sessions']==raw['sessions'] and len(pending['sessions'])==33
    source=common.ROOT/'work/wave_v106/trade_gate/votes.py'
    assert source.read_bytes()==(common.HERE/'votes.py').read_bytes()
    assert 'start=first' in source.read_text(encoding='utf-8')
    for p,h in art['source_SHA256'].items():assert common.digest(common.ROOT/p)==h,p
    voteproof=common.ROOT/'work/wave_v106/trade_gate/窓内資格境界訂正と旧人工委譲_v2.json'
    assert common.read(voteproof)['全合格']
    manifests=[dict(path=p.relative_to(common.ROOT).as_posix(),sha256=common.digest(p))
               for p in (pending_path,raw_path,qpath,voteproof,common.HERE/'E01公開maskとUID料金及び接頭の人工検査.json')]
    quotes=dict(path='work/wave_v106/e01_reference/prepared/quotes.pkl',SHA256=qmeta['全気配SHA256'])
    common.write(common.HERE/'入力測定前の固定.json',dict(全合格=True,sessions=pending['sessions'],
        configs=catalog.configs(),source_SHA256=common.sources(),input_manifests=manifests,
        pending_inputs=pending['cache'],raw_inputs=raw['raw_inputs'],quotes=quotes,
        direction_proxy_source=dict(path=source.relative_to(common.ROOT).as_posix(),SHA256=common.digest(source)),
        原paper再計算=0,新金融=0,原book=0,API=0,
        差分='旧代理の同clock窓外reset走査不備は修正後exact clone。W/2票/.25と代理思想は不変。'))


def load(item: dict, raw: bool=False) -> dict:
    """
    機能: 許可された保存cache又は原行NPZを各一読し同bytesで照合する。
    引数: item(dict)はpath/SHA256、raw(bool)はNPZ読取か。
    返り値: dictは保存値又は必要原列。生book・現在APIへ接続しない。
    """
    path=common.ROOT/item['path'];assert path.resolve().is_relative_to(common.ROOT/'work')
    saved=path.read_bytes();assert hashlib.sha256(saved).hexdigest()==item['SHA256'],path
    if not raw:return pickle.loads(gzip.decompress(saved))
    with np.load(io.BytesIO(saved),allow_pickle=False) as source:return {n:source[n] for n in FIELDS}


def activity(account: dict, window: int, mode: str) -> dict:
    """
    機能: 紙上公開候補の票可用性と採否だけを、保有や勝敗を使わず数える。
    引数: account(dict)、window(int)、mode(str)は同一保存feedと確認条件。
    返り値: dictは候補数・買売・未知理由。公開許可を実約定や勝ちと呼ばない。
    """
    entries=account['feed'][account['feed'][:,7]==1];features=account['trade_features'][str(window)]
    values=[features[int(o[0])] for o in entries];decisions=[policy.verdict(v,mode)[0] for v in values]
    return dict(紙上公開新規数=len(entries),公開許可数=int(sum(decisions)),
        公開許可買=int(sum(ok and o[3]>0 for ok,o in zip(decisions,entries))),
        公開許可売=int(sum(ok and o[3]<0 for ok,o in zip(decisions,entries))),
        未知数=sum(not v['known'] for v in values),
        既知2票未満=sum(v['known'] and v['direction_votes']<2 for v in values),
        不明理由=dict(Counter(str(v['reason']) for v in values if not v['known'])))


def run() -> None:
    """
    機能: 固定33紙上cache/66NPZ/Q一資料を各一読し、全12条件共通の票cacheを保存する。
    引数: なし。
    返り値: None。全後続feedを保存し、新金融・旧paper計算は0のままにする。
    """
    fixed=common.read(common.HERE/'入力測定前の固定.json');assert fixed['source_SHA256']==common.sources()
    for m in fixed['input_manifests']:assert common.digest(common.ROOT/m['path'])==m['sha256']
    qspec=fixed['quotes'];saved=(common.ROOT/qspec['path']).read_bytes()
    assert hashlib.sha256(saved).hexdigest()==qspec['SHA256'];quotes=pickle.loads(saved);del saved
    caches={};summaries={};checks=Counter();started=time.monotonic()
    for session in fixed['sessions']:
        old=load(fixed['pending_inputs'][session]);checks['旧E01cache一読']+=1
        packet=dict(schema_version=1,session=session,accounts={});summaries[session]={}
        for symbol in ('TOPIX','NK225'):
            a=old['accounts'][symbol];raw=load(fixed['raw_inputs'][session+'|'+symbol],True);checks['原行NPZ一読']+=1
            record=a['normal_record'];q=quotes[session,symbol];mapping=raw['execution_to_raw_index']
            for field,name in (('raw_seq','seq'),('price_time_s','time_s'),('last','price')):
                np.testing.assert_array_equal(raw[field][mapping],record[name]);checks['原行normal一致']+=1
            for name in ('seq','time_s'):np.testing.assert_array_equal(record[name],q[name])
            for name in ('bid','ask'):np.testing.assert_array_equal(raw[name][mapping],q[name])
            entries=a['feed'][a['feed'][:,7]==1];assert np.all(entries[:,4]==catalog.QUANTITY[symbol])
            ctx=votes.context(raw)
            feature={str(w):{int(o[0]):votes.measure(raw,ctx,int(mapping[int(o[0])]),w,int(o[3]))
                            for o in entries} for w in (10,30,60)}
            own=dict(symbol=symbol,record=record,quotes=q,feed=a['feed'],quiet=a['quiet'],quiet_force=a['quiet_force'],
                     quiet_windows=a['quiet_windows'],paper_SHA256=a['paper_SHA256'],mapping=mapping,
                     trade_features=feature)
            packet['accounts'][symbol]=own
            summaries[session][symbol]={f'{w}_{mode}':activity(own,w,mode) for w in (10,30,60) for mode in ('CONFIRM','VETO')}
            del raw,ctx
        path=common.HERE/f'input/{session}.pkl.gz';common.write(path,packet)
        caches[session]=dict(path=path.relative_to(common.ROOT).as_posix(),SHA256=common.digest(path))
        del packet,old;gc.collect();print(session+' E01公開票準備完了、金融0',flush=True)
    assert checks['旧E01cache一読']==33 and checks['原行NPZ一読']==66 and common.sources()==fixed['source_SHA256']
    total={}
    for symbol in ('TOPIX','NK225'):
        total[symbol]={}
        for key in summaries[fixed['sessions'][0]][symbol]:
            rows=[summaries[s][symbol][key] for s in fixed['sessions']]
            total[symbol][key]={k:sum(v[k] for v in rows) for k in rows[0] if k!='不明理由'}
            total[symbol][key]['公開許可あり場数']=sum(v['公開許可数']>0 for v in rows)
            total[symbol][key]['不明理由']=dict(sum((Counter(v['不明理由']) for v in rows),Counter()))
    common.write(common.HERE/'全33場のE01取引更新準備.json',dict(全合格=True,sessions=fixed['sessions'],cache=caches,
        activity=summaries,aggregate=total,source_SHA256=fixed['source_SHA256'],開始終端source一致=True,
        事前固定SHA256=common.digest(common.HERE/'入力測定前の固定.json'),一致検査=dict(checks),Q資料一読=1,
        原paper再計算=0,新金融=0,原book=0,API=0,経過秒=time.monotonic()-started))
    print('全33場E01公開票準備完了、金融0',flush=True)


def main() -> None:
    """
    機能: 結果前固定又は根が許可済みの非金融入力準備を一回だけ開始する。
    引数: CLI --fix-only/--root-input-reviewed(bool)。
    返り値: None。失敗を保持し、自動再開始はしない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--fix-only',action='store_true');parser.add_argument('--root-input-reviewed',action='store_true')
    args=parser.parse_args();assert args.fix_only!=args.root_input_reviewed
    if args.fix_only:fix();return
    assert not (common.HERE/'全33場のE01取引更新準備.json').exists()
    assert not (common.HERE/'入力準備False.json').exists()
    try:run()
    except Exception:
        common.write(common.HERE/'入力準備False.json',dict(全合格=False,原因=traceback.format_exc(),新金融=0,自動再開始=False));raise


if __name__=='__main__':main()
