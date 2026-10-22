"""旧数値の所有コピー・修正44列・固定二設定・登録入力を合成だけで接続する。"""

import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

import adapter_v6 as adapter
import legacy_runtime as legacy
import plan_v6 as plan
import run_v6 as runner
from source_v6 import HERE, ROOT, MIRROR, ENGINE_NAMES, read, save, digest


def raw_fixture() -> tuple[list, dict]:
    """
    機能: 正常と不正常原行を含む44列生産用の小JSONを生成する。
    引数: なし。
    返り値: tuple[list,dict]は合成原行と正常map。実市場値は使用しない。
    """
    base = datetime(2026, 10, 14, 9, tzinfo=timezone(timedelta(hours=9)))
    rows = []
    for index in range(80):
        stamp = (base+timedelta(seconds=index)).isoformat()
        raw = dict(Symbol='合成', SymbolName='人工', Exchange=2, CurrentPrice=100.5,
            CurrentPriceTime=stamp, TradingVolume=index*3, TradingVolumeTime=stamp)
        for depth in range(10):
            raw['Buy'+str(depth+1)] = dict(Price=100.-depth*.5, Qty=10.+depth)
            raw['Sell'+str(depth+1)] = dict(Price=100.5+depth*.5, Qty=11.+depth)
        rows.append((index, raw))
    times = np.array([base.timestamp()+i for i in range(80)])
    chosen = np.arange(2,80,2,dtype=np.int64)
    normal = dict(seq=chosen, time_s=times[chosen], price=np.full(len(chosen),100.5),
                  bid=np.full(len(chosen),100.), ask=np.full(len(chosen),100.5))
    return rows, normal


def check_source_math() -> int:
    """
    機能: 数値源の同bytesとcommon位置・初期化一文だけの差を確認する。
    引数: なし。
    返り値: intは確認項目数。金融有効性を検証する標本ではない。
    """
    count = 0
    for relative, item in legacy.provenance().items():
        assert digest(ROOT/relative) == item['SHA256'] == digest(ROOT/item['owned_path'])
        count += 1
    for name in ENGINE_NAMES:
        original = (ROOT/'work/e01_adaptive_price_20261014/engine'/name).read_bytes()
        current = (HERE/'engine'/name).read_bytes()
        if name == 'common.py':
            original = original.replace(b'ROOT=HERE.parents[2]',b'ROOT=HERE.parents[3]')
        assert original == current
        count += 1
    return count


def guard_checks() -> int:
    """
    機能: 合成登録で新14/旧66・42入力・二固定設定・実装の結線と拒否を検査する。
    引数: なし。
    返り値: intは成功と不正拒否の項目数。registry本文は読まない。
    """
    meta=read(HERE/'入力目録.json');current=plan.sources();proposal=plan.make_proposal(meta,current)
    fixed=dict(source_SHA256=current, input_manifest=proposal['spec']['data']['input_manifests'][0],
        inputs=meta['inputs'], sessions=meta['sessions'], new_sessions=meta['new_sessions'],
        actual_config=meta['actual_config'], counters=meta['counters'], old_reference=meta['old_reference'])
    found=[json.loads(json.dumps(proposal,ensure_ascii=False,allow_nan=False))]
    runner.guard(found,fixed,proposal,meta,current)
    checks=1
    for kind in ('登録無し','別ID','別spec','別source','別目録','重複場','入力不足','別銘柄条件','旧引用違い'):
        f,x,p,m,c=deepcopy((found,fixed,proposal,meta,current))
        if kind=='登録無し':f=[]
        elif kind=='別ID':f[0]['id']='合成別'
        elif kind=='別spec':f[0]['spec']['entry']['余計']='未来'
        elif kind=='別source':c[next(iter(c))]='0'*64
        elif kind=='別目録':x['input_manifest']['sha256']='0'*64
        elif kind=='重複場':m['sessions'][-1]=m['sessions'][0]
        elif kind=='入力不足':m['inputs'].pop()
        elif kind=='別銘柄条件':m['actual_config']['TOPIX']=m['actual_config']['NK225']
        else:m['old_reference']['SHA256']='0'*64
        rejected=False
        try:runner.guard(f,x,p,m,c)
        except AssertionError:rejected=True
        assert rejected,kind
        checks+=1
    return checks


def run() -> None:
    """
    機能: 入力本文なしで所有源・44列・旧固定二政策とJSON保存を合成接続する。
    引数: なし。
    返り値: None。新金融・登録・原市場・保存cache読取は0。
    """
    before=plan.sources();checks=check_source_math();arrays=0;details=[]
    with legacy.isolated(discover=True):
        rt=legacy.runtime()
        modules=adapter.engine_modules()
        selected=adapter.selected_configs(modules)
        assert {s:c['id'] for s,c in selected.items()}==adapter.ACTUAL
        raw,normal=raw_fixture();start,end=normal['time_s'][0]-10,normal['time_s'][-1]+10
        original,diagnosis=rt['raw_core'].extract_rows(raw,start,end,normal)
        corrected,change=rt['correct_arrays'](original)
        assert change['不変配列数']==42 and len(corrected)==44
        mapping=corrected['execution_to_raw_index'];inverse=corrected['normal_execution_row']
        np.testing.assert_array_equal(mapping,np.flatnonzero(inverse>=0))
        np.testing.assert_array_equal(inverse[mapping],np.arange(len(mapping)))
        assert inverse[0]==-1 and inverse[mapping[0]]==0
        for name in corrected:
            if name not in ('volume_delta','volume_delta_usable'):
                np.testing.assert_array_equal(corrected[name],original[name]);arrays+=1
        for side in (1,-1):
            vote=rt['votes'].measure(corrected,rt['votes'].context(corrected),78,60,side)
            assert vote['known'] and vote['direction_votes']>2 and vote['balance']==side
        checks+=8
        fixture=legacy.function('work/e01_adaptive_price_20261014/engine/artificial.py','fixture',
                                dict(np=np,catalog=modules['catalog'],daily=modules['daily']))
        for symbol in adapter.ACTUAL:
            for side in (1,-1):
                account=fixture(symbol,side,1)
                config=selected[symbol]
                gu=modules['interface'].execute(account,config['entry_id'],config['execution_id'],python=True)
                context=modules['interface'].prepared('純人工_Day',account,gu['values'],True)
                result=modules['interface'].apply(context,config,gu['gate'],python=True,fak_events=gu['fak_events'])
                row=adapter.account_row('純人工_Day',symbol,result)
                assert row['net']==sum(p['収支'] for p in result['parent'])
                assert row['fees']==sum(result['order_fees']) and result['summary']['全会計合格']
                assert row['profit']-row['loss']==row['net']
                assert result['long_qty'][-1]==result['short_qty'][-1]==0
                assert row['actual_config']==adapter.ACTUAL[symbol]
                native=runner.normalize_orders(result,account)
                assert len(native)==len(result['orders'])
                for order in native:
                    d=int(order['order'][3])
                    assert order['order'][5]==order['ask' if d>0 else 'bid']
                    q=int(order['order'][4]);num,den=modules['catalog'].FEE_RATIO[symbol]
                    assert order['fee']==q*num//den
                json.dumps(adapter.primitive(dict(row=row,orders=native,summary=result['summary'],
                    parent=result['parent'],control=result['control'],fak=result['fak_events'])),ensure_ascii=False,allow_nan=False)
                details.append(dict(symbol=symbol,side=side,orders=len(native),parents=len(result['parent']),net=row['net']))
                checks+=8+len(native)*2
        # SOURCE宣言のとき、cacheや市場本文へopenを試みても到達できない。
        for path in (MIRROR/'book/TOPIX/人工.jsonl',ROOT/'book/TOPIX/人工.jsonl',MIRROR/'work/wave_v23/inputs.pkl'):
            rejected=False
            try:path.read_bytes()
            except AssertionError:rejected=True
            assert rejected
            checks+=1
    checks+=guard_checks()
    assert before==plan.sources()
    output=dict(全合格=True,source_SHA256=before,確認項目=checks,不変配列照合=arrays,合成口座=details,
        old_math_provenance=legacy.provenance(), 原市場本文読取=0,保存cache本文読取=0,
        新金融=0,登録=0,API=0,性質='所有接続と人工契約の検査。旧33結果や今回追加七場の有効性標本ではない。')
    save(HERE/'旧源所有と修正四十四列及び固定二設定の純接続.json',output)
    print(f'旧E01所有接続の純人工合格 {checks}項目/{arrays}配列。原市場/金融/登録0。',flush=True)


if __name__=='__main__':
    run()
