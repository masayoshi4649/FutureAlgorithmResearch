"""事前登録した三条件を保存済みTOPIX四十場で一回だけ測る。"""

from io import BytesIO
import hashlib
import json
from pathlib import Path
import time
import numpy as np
import engine121 as E
from catalog121 import specifications,settings
from register121 import read,save,sha,ROOT,HERE
import runtime121


def main() -> None:
    """
    機能: 指紋と非空人工確認後に三条件の全注文・全玉・時価を保存する。
    引数: なし。
    返り値: None。同じ出力先への二度目の金融再生を拒否する。
    """
    fixed=read(HERE/'固定計画.json')
    proposal=read(HERE/'試行計画.json')
    checked=read(HERE/'事前照合の全出力.json')
    registered=read(HERE/'正式登録の全出力.json')
    assert checked['終了コード']==registered['終了コード']==0
    assert json.loads(checked['stdout'])['提案完全'] is True
    actual=json.loads(registered['stdout'])
    assert actual['id']==proposal['id'] and actual['spec']==proposal['spec']
    for path,value in fixed['sources'].items():
        assert sha(ROOT/path)==value,path
    assert sha(ROOT/fixed['input_manifest']['path'])==fixed['input_manifest']['sha256']
    assert sha(ROOT/fixed['artificial_audit']['path'])==fixed['artificial_audit']['sha256']
    meta=read(HERE/'入力目録.json')
    assert sha(ROOT/meta['baseline']['path'])==meta['baseline']['sha256']
    specs=specifications()
    assert specs==fixed['specs']
    save(HERE/'実行プロセスの通常高速全配列確認.json',runtime121.verify())

    # ----------------------------------------
    # 保存気配だけを各一回読み、新三条件を全場同じ固定値で測る。
    out=HERE/'measurement'
    assert not out.exists(),'同一金融の再実行を止めます'
    out.mkdir()
    runs=[];cache=[];clock=time.monotonic()
    for number,item in enumerate(meta['inputs']):
        raw=(ROOT/item['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==item['sha256']
        with np.load(BytesIO(raw),allow_pickle=False) as source:
            quotes={key:source['quotes__'+key].copy() for key in ('row','time','last','bid','ask')}
        del raw
        assert np.all(np.diff(quotes['row'])>0)
        setting=settings('TOPIX',item['session'])
        orders=[];lots=[];curves=[];scene=[]
        for index,spec in enumerate(specs):
            o,l,c,n=E.replay(quotes['row'],quotes['time'],quotes['last'],quotes['bid'],quotes['ask'],
                **setting,unit=1.,mode=2,trail=spec['trail'],spacing=spec['spacing'],reset_after_profit=spec['reset_after_profit'])
            summary=dict(zip(E.SUMMARY_COLUMNS,n.tolist()))
            assert summary['unclosed']==0 and summary['entries']==summary['closed_lots']==len(l)
            assert summary['cash']==summary['net']==summary['profit']-summary['loss']==np.sum(l[:,13])
            assert summary['max_long']<=10 and summary['max_short']<=10
            assert len(o)==2*len(l)
            term=l[:,14]==9
            row=dict(symbol='TOPIX',session=item['session'],method=spec['id'],**summary,
                forced_loss=float(np.maximum(-l[term,13],0).sum()),forced_profit=float(np.maximum(l[term,13],0).sum()),
                trail_net=float(l[l[:,14]==1,13].sum()),long_net=float(l[l[:,1]==1,13].sum()),short_net=float(l[l[:,1]==-1,13].sum()))
            runs.append(row);scene.append(row)
            for a,sink in [(o,orders),(l,lots),(c,curves)]:
                if len(a):sink.append(np.column_stack((np.full(len(a),index),a)))
        target=out/(item['session']+'.npz')
        np.savez_compressed(target,orders=np.concatenate(orders) if orders else np.empty((0,19)),
            lots=np.concatenate(lots) if lots else np.empty((0,20)),
            curves=np.concatenate(curves) if curves else np.empty((0,9)),
            **{'quotes__'+key:value for key,value in quotes.items()})
        reference=dict(path=target.relative_to(ROOT).as_posix(),sha256=sha(target),session=item['session'],
            source=item['path'],source_sha256=item['sha256'])
        cache.append(reference)
        save(out/(item['session']+'.json'),dict(runs=scene,reference=reference))
        with (out/'入力読取と会計保存.jsonl').open('a',encoding='utf-8') as handle:
            handle.write(json.dumps(dict(session=item['session'],numerical_input_reads=1,
                new_financial_accounts=3,original_market_reads=0),ensure_ascii=False)+'\n')
        print(f'{number+1}/40 {item["session"]} / {time.monotonic()-clock:.1f}秒',flush=True)
    # ----------------------------------------
    # 経済源の不変と完了した全口座を一つの小会計へ保存する。
    for path,value in fixed['sources'].items():assert sha(ROOT/path)==value,path
    save(HERE/'三ポイント間隔と五ポイント追尾の全四十場.json',dict(passed=True,sessions=meta['sessions'],
        specs=specs,runs=runs,cache=cache,baseline=meta['baseline'],sources=fixed['sources'],
        order_columns=E.ORDER_COLUMNS,lot_columns=E.LOT_COLUMNS,curve_columns=E.CURVE_COLUMNS,
        financial_accounts=len(runs),reused_baseline_accounts=40,original_market_reads=0,API=0,実注文=0,
        留保='同じ既知40場の開発検証。新たな未見相場の成功証明ではない。'))
    print('TOPIX新三条件120会計を保存。旧基準40会計は保存結果を再利用。',flush=True)


if __name__=='__main__':
    main()
