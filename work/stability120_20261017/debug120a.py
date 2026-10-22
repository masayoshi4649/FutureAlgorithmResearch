"""停止した日経一入力だけを、同じ経済源で保存先行の独立診断にかける。"""

from io import BytesIO
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

import catalog120
import engine120
import plan120 as P


HERE = P.HERE / 'recovery_a'


def main() -> None:
    """
    機能: 数値条件を変えず全四十八条件を保存し、現金恒等式の差を測る。
    引数: なし。120aの事前照合・登録実体を起動前に結合する。
    返り値: None。診断を新しい収益根拠に数えず、元の停止証跡を残す。
    """
    proposal = P.read(HERE/'試行計画.json')
    fixed = P.read(HERE/'固定計画.json')
    actual = P.read(HERE/'正式登録の全出力.json')
    checked = P.read(HERE/'事前照合の全出力.json')
    assert actual['終了コード'] == checked['終了コード'] == 0
    assert json.loads(checked['stdout'])['提案完全']
    row = json.loads(actual['stdout'])
    assert row['id'] == proposal['id'] and row['spec'] == proposal['spec']
    assert row['spec']['implementation'] == fixed['sources']
    for path, sha in fixed['sources'].items():
        assert P.digest(P.ROOT/path) == sha
    meta = P.read(HERE/'入力目録.json')
    item = meta['inputs'][0]
    out = HERE/'measurement'
    assert not out.exists()
    out.mkdir()
    payload = (P.ROOT/item['path']).read_bytes()
    assert hashlib.sha256(payload).hexdigest() == item['sha256']
    with np.load(BytesIO(payload),allow_pickle=False) as source:
        q = {key:source['quotes__'+key].copy() for key in ('row','time','last','bid','ask')}
    summaries=[]
    for spec in catalog120.specifications():
        o,l,c,a = engine120.replay(q['row'],q['time'],q['last'],q['bid'],q['ask'],
            **catalog120.settings(item['symbol'],item['session']),fraction=spec['fraction'],
            mode=spec['mode'],trail=spec['trail'])
        v = dict(zip(engine120.SUMMARY_COLUMNS,a.tolist()))
        details=dict(method=spec['id'],summary=v,entry_count=len(o[o[:,1]==1]),exit_count=len(o[o[:,1]==2]),
            cash_minus_lot_net=float(v['cash']-l[:,13].sum()),
            net_minus_profit_loss=float(v['net']-(v['profit']-v['loss'])),
            net_minus_cash=float(v['net']-v['cash']),
            fees_from_orders=float(o[:,8].sum()),fees_from_lots=float(l[:,12].sum()))
        P.save(out/(spec['id']+'.json'),details)
        np.savez_compressed(out/(spec['id']+'.npz'),orders=o,lots=l,curves=c)
        summaries.append(details)
    np.savez_compressed(out/'停止場の所有気配.npz',**q)
    P.save(out/'停止場の四十八会計を保存した診断.json',dict(runs=summaries,sources=fixed['sources'],
        financial_accounts=48,reused_input_reads=1,original_market_reads=0,
        注意='同じ停止場を不具合切分けのため再生。独立した将来成功や新有効性に数えない。'))
    print(json.dumps([dict(method=r['method'],difference=r['net_minus_profit_loss'],
        cash_diff=r['cash_minus_lot_net'],unclosed=r['summary']['unclosed'])
        for r in summaries if abs(r['net_minus_profit_loss'])>1e-8],ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
