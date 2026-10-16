"""検証済み旧30場の指紋を保持し追加場を独立復元して全31会計を検査する。"""

from pathlib import Path

import common
import full
import state_checks


def main():
    """
    機能: 旧2280口座の完了監査を照合し追加76口座と全532商品期間を独立検算する。
    引数: なし。
    返り値: None。既存凍結コード又は監査を変更せず省略範囲を指紋で保証する。
    """
    import sys
    sys.path.insert(0,str(common.WORK))
    import data,strategy
    fixed=full.read(common.WORK/'事前固定.json')
    for name,digest in fixed['SHA256'].items(): assert common.sha(common.ROOT/name)==digest,name
    old_proof_path=common.HERE/'全38条件旧30場の先行独立会計検算.json'
    old_proof=full.read(old_proof_path)
    assert old_proof['全合格'] and old_proof['検査件数']['口座']==38*60
    for name,digest in old_proof['SHA256'].items(): assert common.sha(common.ROOT/name)==digest,name
    selection=full.read(common.WORK/'前16参考代表.json')
    assert selection['追加Day完結損益前選定'] and selection['固定SHA256']==common.sha(common.WORK/'事前固定.json')
    for name,digest in selection['結果SHA256'].items(): assert common.sha(common.ROOT/name)==digest,name
    selection_proof=full.read(common.HERE/'追加場未参照の旧前16参考代表の注文会計による独立再選定.json')
    assert selection_proof['全合格'] and selection_proof['参考代表']==selection['selected']
    for name,digest in selection_proof['SHA256'].items(): assert common.sha(common.ROOT/name)==digest,name
    material=data.load_inputs()
    period_map={'全31':fixed['全31'],'旧30':fixed['旧30'],'前16':fixed['前16'],'後14':fixed['後14'],
                '追加1':fixed['追加1'],'デイ':[value for value in fixed['全31'] if value.endswith('_Day')],
                'ナイト':[value for value in fixed['全31'] if value.endswith('_Night')]}
    aggregate_path=common.WORK/'analysis/比較結果.json'
    published=full.read(aggregate_path)
    expected_results=published['results']
    assert set(expected_results)=={value['id'] for value in fixed['条件']}
    counters=dict(追加口座=0,検証済み旧口座=38*60,全口座=38*62,全商品期間=0,追加格子状態と反対確認=0)
    extra_counts={}; fingerprints={}; verified={}
    for config in fixed['条件']:
        ident=config['id']
        old_path=common.WORK/'results'/f'{ident}.json'
        old_ledger_path=common.WORK/'ledgers'/f'{ident}.pkl'
        extra_path=common.WORK/'extra/results'/f'{ident}.json'
        extra_ledger_path=common.WORK/'extra/ledgers'/f'{ident}.pkl'
        assert str(old_path.relative_to(common.ROOT)) in old_proof['SHA256']
        assert str(old_ledger_path.relative_to(common.ROOT)) in old_proof['SHA256']
        old=full.read(old_path); extra=full.read(extra_path); ledgers=full.read(extra_ledger_path)
        assert old['config']==extra['config']==config
        assert common.sha(extra_ledger_path)==extra['ledger_SHA256']
        assert set(ledgers)=={(session,symbol) for session in fixed['追加1'] for symbol in common.SYMBOLS}
        prepared=strategy.prepare(material,config)
        rows=list(old['rows'])
        new_rows=[]
        for session in fixed['追加1']:
            restored=state_checks.restore(material['grids'][session],material['entries'][session],config)
            reverse=state_checks.reversal(material['grids'][session],material['entries'][session],config)
            for symbol in common.SYMBOLS:
                actual=prepared[session,symbol]['signal']
                common.same(restored,{name:actual[name] for name in restored})
                common.same(reverse,{name:actual[name] for name in reverse})
                counters['追加格子状態と反対確認']+=1
        for key in sorted(ledgers):
            row,counts=full.account(key,prepared[key]['record'],prepared[key]['signal'],config,ledgers[key])
            new_rows.append(row)
            for name,count in counts.items(): extra_counts[name]=extra_counts.get(name,0)+count
            counters['追加口座']+=1
        common.same(new_rows,extra['rows'])
        rows.extend(new_rows)
        rows.sort(key=lambda value:(value['session'],value['symbol']))
        formal=expected_results[ident]
        assert formal['config']==config
        common.same(rows,formal['rows'])
        periods={}
        for period,sessions in period_map.items():
            periods[period]={symbol:full.aggregate(rows,symbol,sessions) for symbol in common.SYMBOLS}
            common.same(periods[period],formal['periods'][period])
            if period=='追加1': common.same(periods[period],extra['periods'][period])
            elif period in old['periods']: common.same(periods[period],old['periods'][period])
            counters['全商品期間']+=2
        verified[ident]=dict(rows=rows,periods=periods)
        fingerprints.update(common.fingerprint([old_path,old_ledger_path,extra_path,extra_ledger_path]))
        del prepared,ledgers
        print(f'{ident} 旧指紋保持・追加2口座・全31の7期間集計に独立一致',flush=True)
    assert counters['追加口座']==76 and counters['全商品期間']==532
    both80=[ident for ident,result in verified.items() if all(result['periods']['全31'][symbol]['profit_share'] is not None
                 and result['periods']['全31'][symbol]['profit_share']>=.8 for symbol in common.SYMBOLS)]
    fingerprints.update(common.fingerprint([Path(__file__),common.HERE/'full.py',common.HERE/'protocol.py',old_proof_path,
                     common.HERE/'追加場未参照の旧前16参考代表の注文会計による独立再選定.json',
                     common.WORK/'事前固定.json',common.WORK/'前16参考代表.json',aggregate_path]))
    common.save('全38条件全31場の仮説と最初返済及び全原板清算会計の独立検算.json',
                dict(全合格=True,検査範囲='38条件×31場×2銘柄＝2356口座。旧2280口座は完了監査指紋を保持して再利用、追加76口座を同じ独立会計で復元。全532商品期間を独立合算。',
                     検査件数=counters,追加全原板会計件数=extra_counts,旧全原板会計件数=old_proof['検査件数'],
                     全31独立会計={ident:result['periods']['全31'] for ident,result in verified.items()},
                     両銘柄の金額利益80パーセント=both80,SHA256=fingerprints,
                     旧又は凍結変更=0,現在API取得=0,実注文=0,無取引を勝ち扱い=False,
                     追加場が選定へ混入=False,原板順と時計の代理モデル=True))
    print('全2356口座と532商品期間が独立合格。',flush=True)


if __name__=='__main__':
    main()
