"""同じ三ポイント入口の保持を二終端で測り、通常約定と代理会計を分離する。"""

from io import BytesIO
import hashlib
import json
from pathlib import Path
import sys
import time
import numpy as np
import engine122 as E
from register122 import HERE,ROOT,read,save,sha,specifications
import runtime122

sys.path.insert(0,str(HERE.parent/'stability120_20261017'))
from catalog120 import settings


def main() -> None:
    """
    機能: 事前固定した全80会計を一回だけ測定して全注文・代理玉を保存する。
    引数: なし。
    返り値: None。原市場と現在APIを読まず、未測定をゼロ収支に置かない。
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
    save(HERE/'実行プロセスの人工確認.json',runtime122.verify())
    meta=read(ROOT/fixed['input_manifest']['path']);specs=specifications();assert specs==fixed['specs']
    out=HERE/'measurement';assert not out.exists();out.mkdir()
    runs=[];cache=[];clock=time.monotonic()

    # ----------------------------------------
    # 二条件に同じ入力と新規締切を渡し、入口が全件同値であることも照合する。
    for number,item in enumerate(meta['inputs']):
        raw=(ROOT/item['path']).read_bytes();assert hashlib.sha256(raw).hexdigest()==item['sha256']
        with np.load(BytesIO(raw),allow_pickle=False) as source:
            quotes={key:source['quotes__'+key].copy() for key in ['row','time','last','bid','ask']}
        del raw
        values=[];arrays={};reference_entries=None
        for index,spec in enumerate(specs):
            o,l,c,summary,proxy,context=E.evaluate(quotes,settings('TOPIX',item['session']),spec['kind'])
            entries=o[o[:,1]==1]
            assert len(entries)>0 and summary['max_long']<=10 and summary['max_short']<=10
            if reference_entries is None:reference_entries=entries.copy()
            else:assert np.array_equal(entries,reference_entries)
            if spec['kind']=='CLOSE_PROXY':
                assert context['reference_row']==item['terminal_proxy']['row']
                assert context['reference_time']==item['terminal_proxy']['epoch']
                assert context['reference_bid']==item['terminal_proxy']['bid']
                assert context['reference_ask']==item['terminal_proxy']['ask']
                assert len(l)==0 and len(proxy)==len(entries) and context['measured']
                netvalues=proxy[:,12];sides=proxy[:,1]
            else:
                assert summary['unclosed']==0 and len(l)==len(entries)
                netvalues=l[:,13];sides=l[:,1]
            assert summary['net']==sum(netvalues)==summary['profit']-summary['loss']
            row=dict(symbol='TOPIX',session=item['session'],method=spec['id'],**summary,
                long_net=float(netvalues[sides==1].sum()),short_net=float(netvalues[sides==-1].sum()),
                context=context,proxy_count=len(proxy),regular_closed=len(l))
            values.append(row);runs.append(row)
            for key,array in [('orders',o),('lots',l),('curves',c),('proxy_lots',proxy)]:
                arrays[f'{index}__{key}']=array
        path=out/(item['session']+'.npz')
        np.savez_compressed(path,**arrays,**{'quotes__'+key:value for key,value in quotes.items()})
        ref=dict(path=path.relative_to(ROOT).as_posix(),sha256=sha(path),session=item['session'],input_path=item['path'],input_sha256=item['sha256'])
        cache.append(ref);save(out/(item['session']+'.json'),dict(runs=values,reference=ref))
        print(f'{number+1}/40 {item["session"]} / {time.monotonic()-clock:.1f}秒',flush=True)

    # ----------------------------------------
    # 別台帳を保ったまま合計と出典を完成結果へ固定する。
    for path,value in fixed['sources'].items():assert sha(ROOT/path)==value,path
    save(HERE/'途中利確なしと引け一括の全四十場.json',dict(passed=True,sessions=meta['sessions'],specs=specs,
        runs=runs,cache=cache,baseline=fixed['baseline'],sources=fixed['sources'],
        order_columns=E.BASE.ORDER_COLUMNS,lot_columns=E.BASE.LOT_COLUMNS,curve_columns=E.BASE.CURVE_COLUMNS,
        proxy_columns=E.PROXY_COLUMNS,financial_accounts=80,reused_baseline_accounts=40,original_market_reads=0,API=0,実注文=0,
        留保='引け40場は全て終値代理。正常BBOの実時刻を参照し予定引け時刻の実約定と混同しない。同じ既知40場の開発。'))
    print('二終端80会計を保存。引け代理と通常返済を別台帳で完了。',flush=True)


if __name__=='__main__':
    main()
