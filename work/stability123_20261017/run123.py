"""新十八間隔条件を保存済みTOPIX四十場で一度だけ測る。"""

from io import BytesIO
import hashlib
import json
import sys
import time
import numpy as np
import engine123 as E
from catalog123 import specifications
from register123 import HERE,ROOT,read,save,sha
import runtime123

sys.path.insert(0,str(HERE.parent/'stability120_20261017'))
from catalog120 import settings


def main() -> None:
    """
    機能: 条件固定と非空人工後に全720会計を保存し、旧基準を再生しない。
    引数: なし。
    返り値: None。未使用出力先に一回だけ実行する。
    """
    fixed=read(HERE/'固定計画.json');proposal=read(HERE/'試行計画.json')
    checked=read(HERE/'事前照合の全出力.json');registered=read(HERE/'正式登録の全出力.json')
    assert checked['終了コード']==registered['終了コード']==0
    assert json.loads(checked['stdout'])['提案完全'] is True
    assert json.loads(registered['stdout'])['spec']==proposal['spec']
    for path,value in fixed['sources'].items():assert sha(ROOT/path)==value,path
    assert sha(ROOT/fixed['input_manifest']['path'])==fixed['input_manifest']['sha256']
    assert sha(ROOT/fixed['artificial_audit']['path'])==fixed['artificial_audit']['sha256']
    assert sha(ROOT/fixed['baseline']['path'])==fixed['baseline']['sha256']
    save(HERE/'実行プロセスの期待線と通常高速確認.json',runtime123.verify())
    meta=read(ROOT/fixed['input_manifest']['path']);specs=specifications();assert specs==fixed['specs']
    out=HERE/'measurement';assert not out.exists();out.mkdir()
    runs=[];cache=[];clock=time.monotonic()

    # ----------------------------------------
    # 一場の気配は一読し、先に定めた十八条件を全て同じ入力で測る。
    for number,item in enumerate(meta['inputs']):
        raw=(ROOT/item['path']).read_bytes();assert hashlib.sha256(raw).hexdigest()==item['sha256']
        with np.load(BytesIO(raw),allow_pickle=False) as source:
            quotes={key:source['quotes__'+key].copy() for key in ['row','time','last','bid','ask']}
        del raw
        scene=[];arrays={}
        for index,spec in enumerate(specs):
            if spec['reused']:continue
            o,l,c,summary,proxy,context=E.evaluate(quotes,settings('TOPIX',item['session']),'CLOSE_PROXY',
                spec['initial'],spec['spacing'])
            assert not len(l) and np.all(o[:,1]==1) and len(o)<=20
            assert len(proxy)==len(o) and summary['unclosed']==0 and context['measured']
            assert summary['max_long']<=10 and summary['max_short']<=10
            assert context['reference_row']==item['terminal_proxy']['row']
            assert context['reference_time']==item['terminal_proxy']['epoch']
            assert context['reference_bid']==item['terminal_proxy']['bid'] and context['reference_ask']==item['terminal_proxy']['ask']
            netvalues=proxy[:,12];sides=proxy[:,1]
            assert summary['net']==sum(netvalues)==summary['profit']-summary['loss']
            row=dict(symbol='TOPIX',session=item['session'],method=spec['id'],**summary,
                long_net=float(netvalues[sides==1].sum()),short_net=float(netvalues[sides==-1].sum()),
                context=context,proxy_count=len(proxy),regular_closed=0)
            scene.append(row);runs.append(row)
            for key,array in [('orders',o),('lots',l),('curves',c),('proxy_lots',proxy)]:arrays[f'{index}__{key}']=array
        path=out/(item['session']+'.npz')
        np.savez_compressed(path,**arrays,**{'quotes__'+key:value for key,value in quotes.items()})
        ref=dict(path=path.relative_to(ROOT).as_posix(),sha256=sha(path),session=item['session'],input_path=item['path'],input_sha256=item['sha256'])
        cache.append(ref);save(out/(item['session']+'.json'),dict(runs=scene,reference=ref))
        print(f'{number+1}/40 {item["session"]} / {time.monotonic()-clock:.1f}秒',flush=True)

    # ----------------------------------------
    # 720の新会計と40の引用を区別して完成内容を保存する。
    for path,value in fixed['sources'].items():assert sha(ROOT/path)==value,path
    assert len(runs)==720 and len(cache)==40
    save(HERE/'途中利確なしの十九間隔と全四十場.json',dict(passed=True,sessions=meta['sessions'],specs=specs,
        runs=runs,cache=cache,baseline=fixed['baseline'],sources=fixed['sources'],
        order_columns=E.BASE.ORDER_COLUMNS,lot_columns=E.BASE.LOT_COLUMNS,curve_columns=E.BASE.CURVE_COLUMNS,
        proxy_columns=E.PROXY_COLUMNS,financial_accounts=720,reused_baseline_accounts=40,original_market_reads=0,API=0,実注文=0,
        留保='全て同じ既知40場の開発。十九設定は独立標本ではない。終端は引け前六分以内BBOの代理精算で実引け約定ではない。'))
    print('十八新条件720会計を保存。旧3/3の40会計は引用だけ。',flush=True)


if __name__=='__main__':
    main()
