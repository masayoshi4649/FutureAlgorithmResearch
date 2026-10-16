"""原本を再読せず、固定36条件の当時方向票と候補可用性を一回保存する。"""

import argparse
from collections import Counter
import gzip
import hashlib
import io
import json
from pathlib import Path
import pickle
import socket
import time

import numpy as np

import common
import catalog
import policy
import selection
import votes


OLD_METADATA=common.ROOT/'work/wave_v106/range_price/全33場の価格境界反発準備.json'
RAW_METADATA=(common.ROOT/'work/wave_v103/input_v2/metadata.json',common.ROOT/'work/wave_v104/holdout_input/metadata.json')
FIELDS=('raw_seq','price_time_s','last','bid','ask','volume','volume_time_s','volume_delta',
        'volume_delta_usable','volume_reset_reason','price_reset_reason','execution_to_raw_index')
FIXED=common.HERE/'入力測定前の固定.json'
TARGET=common.HERE/'全33場の取引更新代理準備.json'


def sources() -> dict:
    """
    機能: 新観測・固定数学複製と直接入力由来sourceの指紋を準備前に固定する。
    引数: なし。
    返り値: dict[str,str]はroot相対位置とSHA256。金融結果は読まない。
    """
    names=('policy.py','votes.py','prepare.py','data.py','artificial.py','common.py','catalog.py','features.py','selection.py','interface.py','engine/core.py')
    paths=[common.HERE/name for name in names]
    paths += [common.ROOT/name for name in ('work/wave_v103/input_v2/入力schema.json','work/wave_v106/regime_price/features.py')]
    return {p.relative_to(common.ROOT).as_posix():common.digest(p) for p in paths}


def clone_checks() -> dict:
    """
    機能: R計算・選択・金融執行の私有複製が旧sourceと完全同bytesであることを確認する。
    引数: なし。
    返り値: dictは源と複製の一致。旧sourceや旧JITは変更しない。
    """
    result={}
    for name in ('common.py','catalog.py','features.py','selection.py','interface.py','engine/core.py'):
        own=common.HERE/name;old=common.ROOT/'work/wave_v106/range_price'/name
        assert own.read_bytes()==old.read_bytes(),name
        result[name]=dict(source=old.relative_to(common.ROOT).as_posix(),SHA256=common.digest(old),exact_bytes=True)
    return result


def fix() -> None:
    """
    機能: 新目的の全33packet/66NPZ manifestと不明拒否仕様を、大型入力読取前に固定する。
    引数: なし。
    返り値: None。人工証跡を確認し、金融やAPIを使わず新JSONへ保存する。
    """
    meta=common.read(OLD_METADATA);old,additional=(common.read(p) for p in RAW_METADATA)
    assert meta['全合格'] and len(meta['sessions'])==33 and old['全合格'] and additional['全合格']
    proof_path=common.HERE/'取引更新方向票とscope及び接頭の人工検査.json';proof=common.read(proof_path)
    assert proof['全合格'] and proof['金融再生']==proof['大型入力読取']==0
    raw={}
    for session in meta['sessions']:
        source=old if session in old['sessions'] else additional
        for symbol in ('TOPIX','NK225'):
            item=source['accounts'][session+'|'+symbol]
            raw[session+'|'+symbol]=dict(path=item['出力位置'],SHA256=item['出力SHA256'],raw_rows=item['raw_rows'],normal_rows=item['normal_execution_rows'])
    value=dict(全合格=True,trial_id=policy.TRIAL_ID,sessions=meta['sessions'],configs=policy.configs(),source_SHA256=sources(),
        exact_math=clone_checks(),input_manifests=[dict(path=p.relative_to(common.ROOT).as_posix(),sha256=common.digest(p)) for p in (OLD_METADATA,*RAW_METADATA)],
        packet_inputs=meta['cache'],raw_inputs=raw,人工SHA256=common.digest(proof_path),
        用途='新R/C/BOTH入口確認の非金融可用性。損益や成功ラベルは読まない。',
        条件='(candidate CurrentPriceTime−W,candidate CurrentPriceTime]かつ原seq<=候補。窓観測開始を確認し、seq/highwater逆行/時計欠測、volume reset/usable不明はUNKNOWN。',
        票='usable出来高正増の行で原Last>=直前raw askは+1、<=直前raw bidは−1、内側は票0。1更新1票で増加量は方向へ配賦しない。',
        受付='既知方向票2以上かつside*(買票−売票)/(買票＋売票)>=0.25。0票・未知は確認対象の新規だけ拒否。',
        範囲='R/C/BOTH。未対象入口・元pending・全保有出口は不変。新しいpending取消や事後取引削除を加えない。',
        限界=['W秒はCurrentPriceTime代理窓で、真の受信経過秒ではない。別volume時計の停滞を出来高0に読み替えない。',
            'Last対直前BBOは攻撃側代理。正出来高全体の売買側や真の攻撃注文は同定しない。',
            '気配反発の同row更新なしは実約定を伴ったことが未確認という観測差。虚偽反発とは断定しない。'],
        原book読取=0,現在snapshot読取=0,API取得=0,新金融再生=0,金融結果読取=0)
    common.write(FIXED,value);print('新目的36条件を入力読取前に固定しました。')


def load(item: dict, raw: bool=False) -> dict:
    """
    機能: 許可された保存入力を一回読み、同bytesでSHAを照合する。
    引数: item(dict)はpath/SHA256、raw(bool)は原行NPZかpacketか。
    返り値: dictは必要原field又は旧packet。生bookや現在snapshotは拒否する。
    """
    path=common.ROOT/item['path'];assert path.resolve().is_relative_to((common.ROOT/'work').resolve())
    saved=path.read_bytes();assert hashlib.sha256(saved).hexdigest()==item['SHA256'],path
    if not raw:return pickle.loads(gzip.decompress(saved))
    with np.load(io.BytesIO(saved),allow_pickle=False) as source:
        value={name:source[name] for name in FIELDS}
    return value


def activity(normal: dict, features: dict, record: dict, quiet: dict, scope: str) -> dict:
    """
    機能: 保有や勝敗を使わず、scope別の当時候補と拒否内訳を数える。
    引数: normal/features/record/quiet(dict)、scope(str:R/C/BOTH)は旧入力と当時票。
    返り値: dictは買売・C/R・受付内の可用性。無発火を勝ちに含めない。
    """
    mask,reasons=votes.entry_filter(normal,features,scope);time=record['time_s']
    reception=(time>=record['start']+300)&(time<record['limit']-300)&~quiet['active']&record['quote_valid']
    result={}
    for name,code in (('C',1),('R',2)):
        chosen=(normal['entry_families']==code)&reception;rows=np.flatnonzero(chosen)
        targeted=scope=='BOTH' or scope==name
        result[name]=dict(元受付内候補=int(len(rows)),確認後候補=int(np.count_nonzero(chosen&mask)),
            確認後買=int(np.count_nonzero(chosen&mask&(normal['event']==1))),確認後売=int(np.count_nonzero(chosen&mask&(normal['event']==-1))),
            unknown=int(sum(not features[int(r)]['known'] for r in rows)) if targeted else 0,
            票2未満=int(sum(features[int(r)]['known'] and features[int(r)]['direction_votes']<2 for r in rows)) if targeted else 0,
            方向釣合い不足=int(np.count_nonzero(chosen&(reasons==201))),
            不明理由=dict(Counter(str(features[int(r)]['reason']) for r in rows if targeted and not features[int(r)]['known'])))
    return result


def run() -> None:
    """
    機能: 固定33packet/66NPZを各一読し、36確認の同normal・特徴・非金融活動を保存する。
    引数: なし。
    返り値: None。source始終不変を確認し、金融/API/原本は使わない。
    """
    fixed=common.read(FIXED);assert fixed['source_SHA256']==sources() and fixed['configs']==policy.configs()
    for item in fixed['input_manifests']:assert common.digest(common.ROOT/item['path'])==item['sha256']
    base_catalog={c['id']:c for c in catalog.catalog()};base_ids=sorted({c['baseline_id'] for c in fixed['configs']})
    cache={};summaries={};checks=Counter();started=time.monotonic()
    for session in fixed['sessions']:
        old=load(fixed['packet_inputs'][session]);checks['旧range入力一読']+=1
        current=dict(schema_version=1,session=session,prepared={},normals={i:{} for i in base_ids},trade_features={})
        summary={}
        for symbol in ('TOPIX','NK225'):
            raw=load(fixed['raw_inputs'][session+'|'+symbol],True);checks['旧NPZ一読']+=1
            p=old['prepared'][symbol];record=p['record'];mapping=raw['execution_to_raw_index']
            for field,name in (('raw_seq','seq'),('price_time_s','time_s'),('last','price'),('bid','bid'),('ask','ask')):
                np.testing.assert_array_equal(raw[field][mapping],record[name]);checks['原field正常対応']+=1
            current['prepared'][symbol]=dict(record=record,reference_open=p['reference_open'],signal=dict(trend_width=p['signal']['trend_width']))
            originals={i:selection.build(old,symbol,base_catalog[i]) for i in base_ids}
            rows=sorted({int(d['row']) for normal in originals.values() for d in normal['decisions']})
            ctx=votes.context(raw)
            current['trade_features'][symbol]={str(w):{row:votes.measure(raw,ctx,int(mapping[row]),w,int(originals[next(i for i in base_ids if originals[i]['event'][row])]['event'][row])) for row in rows} for w in (10,30,60)}
            # 同じ当時rowは4基準の間でも入口方向が同じ。新条件の損益からsideを選ばない。
            for row in rows:
                sides={int(normal['event'][row]) for normal in originals.values() if normal['event'][row]}
                assert len(sides)==1
            for identifier,normal in originals.items():current['normals'][identifier][symbol]=normal
            summary[symbol]={}
            for config in fixed['configs']:
                normal=originals[config['baseline_id']]
                features=current['trade_features'][symbol][str(config['trade_window_seconds'])]
                summary[symbol][config['id']]=activity(normal,features,record,old['quiet'][symbol],config['gate_scope'])
            del raw,ctx
        path=common.HERE/'input'/(session+'.pkl.gz');common.write(path,current)
        cache[session]=dict(path=path.relative_to(common.ROOT).as_posix(),SHA256=common.digest(path));summaries[session]=summary
        del old,current
        print(json.dumps(dict(完了場=session,完了場数=len(cache)),ensure_ascii=False),flush=True)
    assert sources()==fixed['source_SHA256']
    total={}
    for config in fixed['configs']:
        total[config['id']]={}
        for symbol in ('TOPIX','NK225'):
            fields={}
            for family in ('C','R'):
                rows=[summaries[s][symbol][config['id']][family] for s in fixed['sessions']]
                keys=('元受付内候補','確認後候補','確認後買','確認後売','unknown','票2未満','方向釣合い不足')
                fields[family]={key:sum(r[key] for r in rows) for key in keys}
                fields[family]['確認後候補あり場数']=sum(r['確認後候補']>0 for r in rows)
                fields[family]['不明理由']=dict(sum((Counter(r['不明理由']) for r in rows),Counter()))
            total[config['id']][symbol]=fields
    result=dict(全合格=True,sessions=fixed['sessions'],configs=fixed['configs'],cache=cache,activity=summaries,aggregate=total,
        source_SHA256=fixed['source_SHA256'],exact_math=fixed['exact_math'],開始終端source一致=True,
        事前固定SHA256=common.digest(FIXED),一致検査=dict(checks),新金融再生=0,金融結果読取=0,原book読取=0,現在snapshot読取=0,API取得=0,
        処理秒=time.monotonic()-started,資格='候補当時proxy値と同normalだけ。新規採否は外部mask、pending/保有exitに追加条件なし。')
    common.write(TARGET,result);print(json.dumps(dict(全合格=True,metadata_SHA256=common.digest(TARGET),一致検査=dict(checks)),ensure_ascii=False))


def main() -> None:
    """
    機能: 結果前固定又は根が許可した一回の非金融入力準備を開始する。
    引数: CLI --fix-only/--root-trade-input-reviewed(bool)。
    返り値: None。失敗を保持し自動再実行しない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--fix-only',action='store_true');parser.add_argument('--root-trade-input-reviewed',action='store_true')
    args=parser.parse_args();assert args.fix_only!=args.root_trade_input_reviewed
    if args.fix_only:fix();return
    assert not TARGET.exists() and not (common.HERE/'入力準備False.json').exists()
    def denied(*args: object, **kwargs: object) -> None:
        """
        機能: 非金融保存入力準備のネットワーク接続を拒否する。
        引数: args/kwargs(object)は接続要求。
        返り値: None。常に例外で拒否する。
        """
        raise RuntimeError('保存取引更新準備はAPI禁止')
    socket.create_connection=denied;socket.socket.connect=denied
    try:run()
    except Exception as error:
        common.write(common.HERE/'入力準備False.json',dict(全合格=False,例外=repr(error),金融再生=0,API取得=0,自動再試行=0));raise


if __name__=='__main__':main()
