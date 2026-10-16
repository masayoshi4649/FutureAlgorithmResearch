"""独立枠の同枚数源単独と併用を、相殺せず全注文・源別全行時価で照合する。"""

from pathlib import Path
import argparse
import numpy as np

import common
import full


def compare(first,second,source):
    """
    機能: 親番号・全体注文番号だけを除外して、同枚数の源別注文を完全比較する。
    引数: first/second(dict)、source(int)。
    返り値: intの注文数。
    """
    a,b = np.asarray(first['orders'],float),np.asarray(second['orders'],float)
    a,b = a[a[:,3]==source],b[b[:,3]==source]
    columns = [column for column in range(17) if column not in (2,16)]
    common.same(a[:,columns],b[:,columns])
    if 'source_curve' in first:
        common.same(first['source_curve'][:,source],second['source_curve'][:,source])
    else:
        assert first['source_curve_column_SHA256'][source]==second['source_curve_column_SHA256'][source]
    if source==1:
        if 'range_state_trace' in first:
            common.same(first['range_state_trace'],second['range_state_trace'])
            common.same(first['risk_state_trace'],second['risk_state_trace'])
        else:
            assert first['range_state_SHA256']==second['range_state_SHA256']
            assert first['risk_state_SHA256']==second['risk_state_SHA256']
        d1,d2 = np.asarray(first['range_parent_diagnostics'],float),np.asarray(second['range_parent_diagnostics'],float)
        common.same(d1[:,1:],d2[:,1:])
    return len(a)


def main():
    """
    機能: 凍結前は人工のみ、正式指示後は全31保存台帳で配分源の独立性を検算する。
    引数: CLI --formal(bool)。
    返り値: None。売買計算・既存の固定・結果変更はしない。
    """
    import sys
    sys.path.insert(0,str(common.WORK))
    import catalog,strategy
    parser = argparse.ArgumentParser()
    parser.add_argument('--formal',action='store_true')
    args = parser.parse_args()
    checks = []
    fingerprints = common.fingerprint([Path(__file__),common.WORK/'engine.py',common.WORK/'strategy.py',common.WORK/'catalog.py'])
    if args.formal:
        fixed = full.read(common.WORK/'事前固定.json')
        for path,digest in fixed['SHA256'].items():
            assert common.sha(common.ROOT/path)==digest,path
        ledgers = {}
        for ident in ('S00','S02','S03'):
            ledgers[ident] = {}
            for stage in ('front','back'):
                path = common.WORK/stage/'ledgers'/f'{ident}.pkl'
                subset = full.read(path)
                assert not set(ledgers[ident])&set(subset)
                ledgers[ident].update(subset)
                fingerprints.update(common.fingerprint([path]))
        assert len(ledgers['S03'])==62
        for key in sorted(ledgers['S03']):
            for ident,source in (('S00',0),('S02',1)):
                count = compare(ledgers['S03'][key],ledgers[ident][key],source)
                checks.append(dict(場=key[0],商品=key[1],源=source,同数量単独=ident,注文数=count,全原板源時価一致=True))
        fingerprints.update(common.fingerprint([common.WORK/'事前固定.json']))
        name = '独立配分の同数量単独と全31源別注文及び全原板時価の完全一致.json'
    else:
        from execution_checks import sample
        configs = {value['id']:value for value in catalog.catalog()}
        for symbol in common.SYMBOLS:
            for mirror in (False,True):
                for scenario in ('両源同方向予約','両源反対方向予約','通常往復','停止OR両証拠を保存',
                                 '予定距離合格後の次気配飛躍','N4新準備の共同方向Falseは有効'):
                    results = {}
                    for ident in ('S00','S02','S03'):
                        record,signal = sample(symbol,scenario,mirror,configs[ident])
                        results[ident] = strategy.ENGINE.execute(record,signal,configs[ident])
                    for ident,source in (('S00',0),('S02',1)):
                        count = compare(results['S03'],results[ident],source)
                        checks.append(dict(商品=symbol,反射=mirror,人工例=scenario,源=source,注文数=count,独立一致=True))
        name = '独立配分の同数量源単独と人工注文及び全行時価の一致.json'
    common.save(name,dict(全合格=True,全31既知=True,検査=checks,源間相殺=0,枠貸出=0,
                         新完結実損益計算=0,新完結実損益閲覧=0 if not args.formal else None,
                         SHA256=fingerprints,実注文=0,現在API取得=0))


if __name__=='__main__':
    main()
