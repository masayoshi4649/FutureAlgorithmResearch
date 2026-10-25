"""別登録後だけ、保存原版影を使う十六条件の次原行ＢＢＯ運転を一回実行する。"""

import argparse
import hashlib
import io
import json
import os
import pickle
import sys
import time

import numpy as np

from common_bbo126 import HERE,TASK,ROOT,sha,read,save,sources


def bound_payload(item: dict) -> bytes:
    """
    機能: 明示した保存入力を一回読み、同じbytesの指紋を照合する。
    引数: item(dict)はpath/sha256を持つ固定参照。
    返り値: bytesは保存内容。不一致を欠測や零損益へ補完しない。
    """
    path = (ROOT/item['path']).resolve()
    assert path.is_relative_to(ROOT/'work')
    payload = path.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == item['sha256'],item['path']
    return payload


def load_papers(fixed: dict, baseline: dict, last: dict, make_feed: object) -> tuple[dict,list[dict]]:
    """
    機能: 旧三十場引用と追加十一場原版の注文だけを一読し、新金融前に全通知を検査する。
    引数: fixed/baseline/last(dict)、make_feed(object)は固定参照と因果通知関数。
    返り値: tuple[dict,list[dict]]は全八十二原版紙上口座と実読取記録。
    """
    papers,logs = {},[]
    old = fixed['paper_caches'][0]
    with np.load(io.BytesIO(bound_payload(old)),allow_pickle=False) as arrays:
        for row in baseline['rows']:
            key = row['session'],row['symbol']
            prefix = row['symbol']+'_'+row['session']
            papers[key] = {name:arrays[prefix+'__'+name] for name in ('orders','cycles')}
    logs.append(dict(path=old['path'],sha256=old['sha256'],reads=1,accounts=60))
    for item in fixed['paper_caches'][1:]:
        key = item['session'],item['symbol']
        assert key not in papers
        with np.load(io.BytesIO(bound_payload(item)),allow_pickle=False) as arrays:
            papers[key] = {name:arrays['E01__'+name] for name in ('orders','cycles')}
        logs.append(dict(path=item['path'],sha256=item['sha256'],reads=1,accounts=1))
    expected = {(scene,symbol) for scene in fixed['sessions'] for symbol in ('TOPIX','NK225')}
    assert set(papers) == expected and len(papers) == 82
    for key,paper in papers.items():
        feed = make_feed(paper)
        assert not np.any(feed[:,6] == 32.),key
        assert np.isfinite(feed).all(),key
    actual = {(r['session'],r['symbol']) for r in last['rows'] if r['method'] == 'E01'}
    assert actual == expected
    return papers,logs


def normalize(result: dict, ready: dict, method: str, scene: str, normalize_base: object) -> dict:
    """
    機能: 実返済脚と親組の粗損益をLast比較と同じ場列へ合わせる。
    引数: result/ready(dict)、method/scene(str)、normalize_base(object)はＢＢＯ集計関数。
    返り値: dictは費用零の実場会計と方向別収支。
    """
    row = normalize_base(result,ready)
    mult = 1000. if ready['symbol'] == 'TOPIX' else 10.
    trades = result['trades']
    row.update(method=method,session=scene,model='next_normal_bbo',
        entry_orders=row.pop('entries'),entry_quantity=row.pop('new_lots'),
        closed_quantity=row.pop('settled_lots'),groups=row.pop('campaigns'),
        winning_quantity=row.pop('winning_lots'),losing_quantity=row.pop('losing_lots'),
        parent_wins=row.pop('winning_campaigns'),parent_losses=row.pop('losing_campaigns'),
        max_long=float(result['stats'][2]),max_short=float(result['stats'][3]),
        long_net=float(trades[trades[:,2] == 1.,10].sum()*mult),
        short_net=float(trades[trades[:,2] == -1.,10].sum()*mult),
        origin='保存原版Last影と実建値予算による次正常原行BBOの別金融')
    assert row['entry_quantity'] == row['closed_quantity']
    assert np.isclose(row['long_net']+row['short_net'],row['net'],atol=1e-5,rtol=1e-12)
    cap = 10 if ready['symbol'] == 'TOPIX' else 20
    assert row['max_long'] <= cap and row['max_short'] <= cap
    return row


def execute(fixed_path: object, registered_path: object) -> None:
    """
    機能: 別登録・独立人工・源・全入力を拘束し、千三百十二ＢＢＯ会計だけを新規測定する。
    引数: fixed_path/registered_path(Path)は親が確定した別段階の固定と登録出力。
    返り値: None。保存原版Last金融と現在市場の再実行は行わない。
    """
    fixed = read(fixed_path); registered = read(registered_path)
    assert registered['終了コード'] == 0
    row = json.loads(registered['stdout'])
    assert row['spec']['implementation'] == fixed['sources']
    assert sources() == fixed['sources']
    assert fixed['counts']['financial_accounts'] == 1312
    for item in fixed['bindings']:
        if item['kind'] == 'metadata': assert sha(ROOT/item['path']) == item['sha256'],item['path']
    proof = read(ROOT/fixed['artificial']['path'])
    assert proof.get('passed',proof.get('全合格',False))
    last = read(ROOT/fixed['last']['path']); baseline = read(ROOT/fixed['baseline']['path'])
    assert last['passed'] and len(last['rows']) == 1312 and baseline['passed']
    out = HERE/'measurement'
    assert not out.exists() and not (HERE/'金融実行開始.json').exists()
    cache = HERE/'jit_financial'
    assert not cache.exists(),'人工と金融のJITを共用しません'
    os.environ['NUMBA_CACHE_DIR'] = str(cache)
    sys.path.insert(0,str(TASK/'engine'))
    sys.path.insert(0,str(TASK/'design'))
    import numba
    numba.config.CACHE_DIR = str(cache)
    from catalog126 import catalog
    import policy_bbo126 as policy
    assert catalog() == fixed['specs'] and len(catalog()) == 16
    papers,paper_reads = load_papers(fixed,baseline,last,policy.make_feed)
    save(HERE/'全原版通知に実予算返済を混ぜない事前検査.json',dict(passed=True,
        accounts=82,paper_reads=paper_reads,reason32_count=0,financial_accounts=0,
        source_causality='cycles列五の初回固定aだけを使う。終了時刻・最終PL・極値を通知へ読まない。'))
    save(HERE/'金融実行開始.json',dict(start=time.time(),sources=fixed['sources'],financial_accounts=1312,
        original_market_reads=0,old_Last_financial_replays=0,API=0,real_orders=0))
    out.mkdir()
    rows,caches,input_reads,metadata = [],[],[],[]
    for item in fixed['packets']:
        started = time.time()
        packet = pickle.loads(bound_payload(item))
        scene = packet['session']
        assert scene == item['session']
        input_reads.append(dict(path=item['path'],sha256=item['sha256'],reads=1))
        for symbol in ('TOPIX','NK225'):
            key = scene,symbol
            ready,quotes,market = packet['inputs'][key],packet['quotes'][key],packet['markets'][key]
            paper = papers[key]
            arrays = {}
            for config in catalog():
                method = config['id']
                result = policy.play(config,ready,quotes,market,paper)
                for name in ('orders','trades','cycles','curve','stats','execution_events','execution_states','order_uids'):
                    assert np.isfinite(result[name]).all(),(scene,symbol,method,name)
                    arrays[method+'__'+name] = result[name]
                rows.append(normalize(result,ready,method,scene,policy.normalized_summary))
            target = out/(symbol+'_'+scene+'.npz')
            assert not target.exists()
            np.savez_compressed(target,**arrays)
            caches.append(dict(session=scene,symbol=symbol,path=target.relative_to(ROOT).as_posix(),sha256=sha(target)))
            first,last_price = float(ready['last'][0]),float(ready['last'][-1])
            change = last_price/first-1.
            direction = '上昇' if change > 0. else '下落' if change < 0. else '同値'
            metadata.append(dict(session=scene,symbol=symbol,first=first,last=last_price,return_fraction=change,
                regime=direction,strong_regime=direction if abs(change) >= .0025 else '小変動'))
        save(out/(scene+'.json'),dict(rows=[r for r in rows if r['session'] == scene],
             completed_accounts=len(rows),seconds=time.time()-started))
        print(scene+' 次原行BBO十六条件を保存 '+str(len(rows))+' 会計',flush=True)
    assert len(rows) == 1312 and len(caches) == 82 and len(input_reads) == 41
    assert len({(r['method'],r['session'],r['symbol']) for r in rows}) == 1312
    assert sources() == fixed['sources']
    save(HERE/'全十六条件の次原行BBO会計.json',dict(passed=True,rows=rows,cache=caches,
        metadata=metadata,sessions=fixed['sessions'],specs=fixed['specs'],sources=fixed['sources'],
        input_reads=input_reads,paper_reads=paper_reads,new_financial_accounts=1312,
        old_Last_financial_replays=0,original_market_reads=0,API=0,real_orders=0,
        execution=fixed['execution'],accounting='手数料0、実返済脚の正負と親組の正負を別集計、全玉場内返済。',
        limitations='全41場は既知開発。ラージBBO代理の全量模型で、ミニ/マイクロ実板と部分約定は未再現。'))


if __name__ == '__main__':
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixed',type=Path,default=HERE/'固定計画.json')
    parser.add_argument('--registered',type=Path,default=HERE/'正式登録の全出力.json')
    parser.add_argument('--root-run',action='store_true',required=True)
    args = parser.parse_args()
    assert args.root_run
    execute(args.fixed.resolve(),args.registered.resolve())
