"""固定後だけ追加五十三条件を接続し、同一金融計算を保存引用する。"""

import argparse
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import pickle
import sys
import time

import numpy as np

from common_gated126 import HERE,TASK,ROOT,ARRAY_FIELDS,RESULT_NAME,read,save,sha,sources


def bound_payload(item: dict) -> bytes:
    """
    機能: 指定保存資料を一回読み、同じbytesのSHAを照合する。
    引数: item(dict)はpath/sha256を持つ参照。
    返り値: bytesは照合済み内容。原本と現在市場は開かない。
    """
    path = (ROOT/item['path']).resolve()
    assert path.is_relative_to(ROOT/'work')
    payload = path.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == item['sha256'],item['path']
    return payload


def load_papers(fixed: dict, baseline: dict, make_feed: object) -> tuple[dict,list[dict]]:
    """
    機能: 原版二十三保存源とＧ・ＧＵ統合一源を一読し、全通知を事前検査する。
    引数: fixed/baseline(dict)、make_feed(object)は固定資料と因果変換関数。
    返り値: tuple[dict,list[dict]]は三入口×八十二口座の注文と実読取記録。
    """
    papers, logs = {}, []
    first = fixed['paper_caches'][0]
    with np.load(io.BytesIO(bound_payload(first)),allow_pickle=False) as arrays:
        for row in baseline['rows']:
            scene,symbol = row['session'],row['symbol']
            prefix = symbol+'_'+scene
            papers['E01',scene,symbol] = {name:arrays[prefix+'__'+name] for name in ('orders','cycles')}
    logs.append(dict(**first,reads=1,accounts=60))
    for item in fixed['paper_caches'][1:]:
        key = 'E01',item['session'],item['symbol']
        assert key not in papers
        with np.load(io.BytesIO(bound_payload(item)),allow_pickle=False) as arrays:
            papers[key] = {name:arrays['E01__'+name] for name in ('orders','cycles')}
        logs.append(dict(**item,reads=1,accounts=1))
    item = fixed['gated_cache']
    with np.load(io.BytesIO(bound_payload(item)),allow_pickle=False) as arrays:
        for source in ('G','GU'):
            for scene in fixed['sessions']:
                for symbol in ('TOPIX','NK225'):
                    prefix = source+'_'+symbol+'_'+scene
                    papers[source,scene,symbol] = {name:arrays[prefix+'__'+name] for name in ('orders','cycles')}
    logs.append(dict(**item,reads=1,accounts=164))
    expected = {(source,scene,symbol) for source in ('E01','G','GU') for scene in fixed['sessions'] for symbol in ('TOPIX','NK225')}
    assert set(papers) == expected and len(papers) == 246
    for key,paper in papers.items():
        feed = make_feed(paper)
        assert np.isfinite(feed).all() and not np.any(feed[:,6] == 32.),key
    return papers,logs


def normalize(result: dict, ready: dict, method: str, scene: str, normalizer: object) -> dict:
    """
    機能: 実約定会計を既存ＢＢＯと同じ欄へ合わせる。
    引数: result/ready(dict)、method/scene(str)、normalizer(object)は固定数値会計。
    返り値: dictは費用零の返済脚・親組・方向別会計。
    """
    row = normalizer(result,ready)
    mult = 1000. if ready['symbol'] == 'TOPIX' else 10.
    trades = result['trades']
    row.update(method=method,session=scene,model='next_normal_bbo',
        entry_orders=row.pop('entries'),entry_quantity=row.pop('new_lots'),closed_quantity=row.pop('settled_lots'),
        groups=row.pop('campaigns'),winning_quantity=row.pop('winning_lots'),losing_quantity=row.pop('losing_lots'),
        parent_wins=row.pop('winning_campaigns'),parent_losses=row.pop('losing_campaigns'),
        max_long=float(result['stats'][2]),max_short=float(result['stats'][3]),
        long_net=float(trades[trades[:,2] == 1.,10].sum()*mult),
        short_net=float(trades[trades[:,2] == -1.,10].sum()*mult))
    assert row['entry_quantity'] == row['closed_quantity'] and row['unclosed'] == 0
    assert np.isclose(row['long_net']+row['short_net'],row['net'],atol=1e-5,rtol=1e-12)
    cap = 10 if ready['symbol'] == 'TOPIX' else 20
    assert row['max_long'] <= cap and row['max_short'] <= cap
    return row


def execute(fixed_path: Path, registered_path: Path) -> None:
    """
    機能: 独立人工と別登録を拘束し、五十三条件を商品場内の厳密同値引用で実行する。
    引数: fixed_path/registered_path(Path)は親が登録した計画と登録証跡。
    返り値: None。原本・現在ＡＰＩ・実注文・旧同値金融の再計算は零。
    """
    fixed,registered = read(fixed_path),read(registered_path)
    assert registered['終了コード'] == 0
    assert json.loads(registered['stdout'])['spec']['implementation'] == fixed['sources']
    assert sources() == fixed['sources']
    for item in fixed['bindings']:
        if item['kind'] == 'metadata':
            assert sha(ROOT/item['path']) == item['sha256'],item['path']
    proof = read(ROOT/fixed['artificial']['path'])
    assert proof.get('passed',proof.get('全合格',False))
    baseline,previous = read(ROOT/fixed['baseline']['path']),read(ROOT/fixed['previous']['path'])
    assert previous['passed'] and len(previous['rows']) == 1312
    # ----------------------------------------
    # 既存結果seedは、全市場packetと数値源が同じと証明できる同一商品場だけへ閉じる。
    expected_packets = {(p['path'],p['sha256']) for p in fixed['packets']}
    assert {(p['path'],p['sha256']) for p in previous['input_reads']} == expected_packets
    assert {(p['path'],p['sha256']) for p in previous['paper_reads']} == {
        (p['path'],p['sha256']) for p in fixed['paper_caches']}
    for relative,digest in previous['sources'].items():
        if relative in fixed['numerical_sources']:
            assert digest == fixed['numerical_sources'][relative]
    cache = HERE/'jit_financial'
    assert not cache.exists() and not (HERE/'measurement').exists() and not (HERE/'金融実行開始.json').exists()
    os.environ['NUMBA_CACHE_DIR'] = str(cache)
    sys.path.insert(0,str(TASK/'engine'))
    sys.path.insert(0,str(TASK/'engine/bbo_next'))
    import numba
    numba.config.CACHE_DIR = str(cache)
    from catalog126g import catalog,policies
    from feed_filter126 import filter_paper,economic_key
    import policy_bbo126 as policy
    from policy126 import policy_parameters
    assert catalog() == fixed['specs'] and len(catalog()) == 53
    old_policies = policies()[:16]
    assert old_policies == previous['specs']
    papers,paper_reads = load_papers(fixed,baseline,policy.make_feed)
    save(HERE/'全三入口通知の因果事前検査.json',dict(passed=True,accounts=246,paper_reads=paper_reads,
        reason32_count=0,financial_accounts=0,scope='初回ATRのみ。将来最終損益・終了時刻・極値未使用。'))
    save(HERE/'金融実行開始.json',dict(start=time.time(),displayed_accounts=4346,sources=fixed['sources'],
        original_market_reads=0,API=0,real_orders=0,dedup='同一商品場の同通知bytesと四方策bytesだけ'))
    out = HERE/'measurement'
    out.mkdir()
    old_cache = {(p['session'],p['symbol']):p for p in fixed['previous_caches']}
    old_rows = {(r['session'],r['symbol'],r['method']):r for r in previous['rows']}
    rows,caches,input_reads,old_reads,metadata,traces,aliases = [],[],[],[],[],[],[]
    unique_count,old_count,new_alias_count = 0,0,0
    for item in fixed['packets']:
        packet = pickle.loads(bound_payload(item))
        scene = packet['session']
        assert scene == item['session']
        input_reads.append(dict(path=item['path'],sha256=item['sha256'],reads=1))
        for symbol in ('TOPIX','NK225'):
            key = scene,symbol
            ready,quotes,market = packet['inputs'][key],packet['quotes'][key],packet['markets'][key]
            reference = old_cache[key]
            # このmemoを商品場の外へ持ち出さない。end/cap/全市場入力は同一packetで固定。
            memo = {}
            base_feed = policy.make_feed(papers['E01',scene,symbol])
            with np.load(io.BytesIO(bound_payload(reference)),allow_pickle=False) as old_arrays:
                for config in old_policies:
                    signature = economic_key(base_feed,policy_parameters(config))
                    result = {name:old_arrays[config['id']+'__'+name] for name in ARRAY_FIELDS}
                    result['paper_feed'] = base_feed
                    summary = deepcopy(old_rows[scene,symbol,config['id']])
                    memo[signature] = dict(result=result,row=summary,origin='previous',canonical=config['id'])
            old_reads.append(dict(**reference,reads=1,accounts=16))
            filtered = {}
            for source in ('E01','G','GU'):
                selected,trace = filter_paper(papers[source,scene,symbol],ready,quotes,enabled=True)
                filtered[source] = selected
                traces.append(dict(session=scene,symbol=symbol,paper_source=source,parents=trace,
                    accepted=sum(v['accepted'] for v in trace),rejected=sum(not v['accepted'] for v in trace)))
            arrays = {}
            for config in catalog():
                method,source = config['id'],config['paper_source']
                paper = filtered[source] if config['quote_gate_enabled'] else papers[source,scene,symbol]
                feed = policy.make_feed(paper)
                signature = economic_key(feed,policy_parameters(config))
                if signature in memo:
                    found = memo[signature]
                    result,row = found['result'],deepcopy(found['row'])
                    reuse = '保存旧十六条件引用' if found['origin'] == 'previous' else '今回同値条件引用'
                    old_count += found['origin'] == 'previous'
                    new_alias_count += found['origin'] == 'new'
                    canonical = found['canonical']
                else:
                    result = policy.play(config,ready,quotes,market,paper)
                    row = normalize(result,ready,method,scene,policy.normalized_summary)
                    memo[signature] = dict(result=result,row=deepcopy(row),origin='new',canonical=method)
                    unique_count += 1
                    reuse,canonical = '新規金融',method
                for name in ARRAY_FIELDS:
                    assert np.isfinite(result[name]).all(),(scene,symbol,method,name)
                    arrays[method+'__'+name] = result[name]
                row.update(method=method,session=scene,paper_source=source,policy_id=config['policy_id'],
                    quote_gate_enabled=config['quote_gate_enabled'],economic_key=signature,
                    calculation_origin=reuse,canonical_method=canonical,
                    origin='凍結済み次原行BBO核。入口源・公開気配予算・利益床を分離。')
                rows.append(row)
                aliases.append(dict(session=scene,symbol=symbol,method=method,economic_key=signature,
                    canonical_method=canonical,origin=reuse,packet_sha256=item['sha256'],
                    end=float(ready['limit']),cap=10 if symbol == 'TOPIX' else 20))
            target = out/(symbol+'_'+scene+'.npz')
            assert not target.exists()
            np.savez_compressed(target,**arrays)
            caches.append(dict(session=scene,symbol=symbol,path=target.relative_to(ROOT).as_posix(),sha256=sha(target)))
            metadata.append(deepcopy(next(r for r in previous['metadata'] if r['session'] == scene and r['symbol'] == symbol)))
        save(out/(scene+'.json'),dict(rows=[r for r in rows if r['session'] == scene],completed_accounts=len(rows),
            unique_new_financial_accounts=unique_count,reused_previous_accounts=old_count,reused_within_stage_accounts=new_alias_count))
        print(scene+' 五十三表示条件を保存 '+str(len(rows))+' 会計／新金融 '+str(unique_count),flush=True)
    assert len(rows) == 4346 and len(caches) == 82 and len(input_reads) == 41 and len(old_reads) == 82
    assert unique_count+old_count+new_alias_count == 4346
    assert len({(r['method'],r['session'],r['symbol']) for r in rows}) == 4346
    assert sources() == fixed['sources']
    save(HERE/RESULT_NAME,dict(passed=True,rows=rows,cache=caches,metadata=metadata,
        specs=fixed['specs'],sessions=fixed['sessions'],sources=fixed['sources'],
        input_reads=input_reads,paper_reads=paper_reads,previous_cache_reads=old_reads,quote_gate_traces=traces,
        aliases=aliases,displayed_accounts=4346,new_financial_accounts=unique_count,
        reused_previous_accounts=old_count,reused_within_stage_accounts=new_alias_count,
        previous_result=fixed['previous'],original_market_reads=0,API=0,real_orders=0,
        accounting='手数料零。全玉場内返済。返済脚と親組は別集計。',
        limitations='全41場は既知開発。ラージBBO代理、ミニ・マイクロの実板・部分約定・実受信遅延は未再現。'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixed',type=Path,default=HERE/'固定計画.json')
    parser.add_argument('--registered',type=Path,default=HERE/'正式登録の全出力.json')
    parser.add_argument('--root-run',action='store_true',required=True)
    args = parser.parse_args()
    assert args.root_run
    execute(args.fixed.resolve(),args.registered.resolve())
