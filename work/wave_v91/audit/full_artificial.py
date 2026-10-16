"""全場監査器の保存台帳接続を人工結果だけで実損益前に検査する。"""

from pathlib import Path

import numpy as np

import common
import full
from execution_checks import sample


def ledger(result):
    """
    機能: 人工結果を正式保存台帳と同じ列・全行指紋の形へ変換する。
    引数: result (dict)。
    返り値: dict。取引実装の台帳関数を呼ばない。
    """
    fields = ('orders','trades','events','stats','slots','order_columns','trade_columns','trace_columns',
              'event_columns','stat_columns','slot_columns','reasons','event_codes')
    trace = result['target_trace']
    changed = np.unique(np.r_[0,np.flatnonzero(np.any(np.diff(trace,axis=0)!=0,axis=1))+1,len(trace)-1])
    value = {field:result[field] for field in fields}
    value.update(trace_changes=np.column_stack((changed,trace[changed])), input_rows=len(trace),
                 curve_SHA256=full.array_sha(result['curve']), source_curve_SHA256=full.array_sha(result['source_curve']),
                 source_curve_column_SHA256=[full.array_sha(result['source_curve'][:,i]) for i in range(2)],
                 target_trace_SHA256=full.array_sha(trace))
    return value


def main():
    """
    機能: 全38条件の人工台帳から全時価指紋と正式会計列を独立検算する。
    引数: なし。
    返り値: None。保存済み実セッションの損益は計算しない。
    """
    import sys
    sys.path.insert(0,str(common.WORK))
    import strategy,catalog
    source_accounting = common.module('正式会計91人工接続',common.WORK/'accounting.py')
    counts = dict(人工保存台帳=0, 注文=0, 決済親=0, 全原板行=0)
    for config in catalog.catalog():
        for symbol in common.SYMBOLS:
            for scenario in ('通常往復','不明を跨ぎ指値保持','共同方向で取消競合','利益発動後に半幅反落'):
                for reflected in (False,True):
                    record,signal = sample(symbol,scenario,reflected,config)
                    result = strategy.ENGINE.execute(record,signal,config)
                    row,checked = full.account((record['session'],symbol),record,signal,config,ledger(result))
                    common.same(row,source_accounting.account((record['session'],symbol),result))
                    counts['人工保存台帳'] += 1
                    for name in ('注文','決済親','全原板行'): counts[name] += checked[name]
        print(f'{config["id"]} 全場監査器の人工保存台帳接続合格',flush=True)
    common.save('全38条件の人工保存台帳と全場監査器の接続検査.json',
                dict(全合格=True,条件数=38,検査件数=counts,新完結実損益計算=0,新完結実損益閲覧=0,
                     SHA256=common.fingerprint([Path(__file__),Path(common.__file__),Path(full.__file__),
                                               common.HERE/'protocol.py',common.HERE/'execution_checks.py',common.WORK/'accounting.py'])))


if __name__ == '__main__':
    main()
