"""追加場を実行せず、凍結後の旧30場台帳だけを独立検算する。"""

from pathlib import Path

import common
import full


def main():
    """
    機能: 旧38条件の全旧台帳を先行検査し追加場損益の先読みを避ける。
    引数: なし。
    返り値: None。追加場 execute 又は追加結果の読取を行わない。
    """
    import sys
    sys.path.insert(0,str(common.WORK))
    import data,strategy
    fixed = full.read(common.WORK/'事前固定.json')
    for name,digest in fixed['SHA256'].items(): assert common.sha(common.ROOT/name)==digest,name
    value = data.load_inputs()
    counters = {}
    fingerprints = {}
    for config in fixed['条件']:
        result_path = common.WORK/'results'/f'{config["id"]}.json'
        ledger_path = common.WORK/'ledgers'/f'{config["id"]}.pkl'
        expected,ledgers = full.read(result_path),full.read(ledger_path)
        assert common.sha(ledger_path)==expected['ledger_SHA256']
        assert set(ledgers)=={(session,symbol) for session in fixed['旧30'] for symbol in common.SYMBOLS}
        prepared = strategy.prepare(value,config)
        rows=[]
        for key in sorted(ledgers):
            row,counts = full.account(key,prepared[key]['record'],prepared[key]['signal'],config,ledgers[key])
            rows.append(row)
            for name,count in counts.items(): counters[name]=counters.get(name,0)+count
        common.same(rows,expected['rows'])
        for period in ('旧30','前16','後14'):
            for symbol in common.SYMBOLS:
                common.same(full.aggregate(rows,symbol,fixed[period]),expected['periods'][period][symbol])
                counters['商品期間集計']=counters.get('商品期間集計',0)+1
        counters['口座']=counters.get('口座',0)+60
        fingerprints.update(common.fingerprint([result_path,ledger_path]))
        del prepared,ledgers
        print(f'{config["id"]} 旧30の全親と全原板時価の独立検算合格',flush=True)
    common.save('全38条件旧30場の先行独立会計検算.json',dict(全合格=True,検査件数=counters,
                追加場損益計算=0,追加場損益閲覧=0,旧変更=0,凍結コード変更=0,
                SHA256=dict(common.fingerprint([Path(__file__),common.HERE/'full.py',common.HERE/'protocol.py',common.WORK/'事前固定.json']),**fingerprints)))


if __name__=='__main__':
    main()
