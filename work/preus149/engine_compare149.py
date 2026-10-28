"""生成済みC00と保存145の注文を読み取り比較する。新たな金融再生は行わない。"""

from pathlib import Path
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
import json
import pickle
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
JST = timezone(timedelta(hours=9))


def clock(seconds):
    """秒数を日本時間へ変換する。

    引数: seconds(float)。返り値: strは日時。
    """
    return datetime.fromtimestamp(float(seconds), JST).isoformat()


def semantic(row):
    """内部IDの差を除く注文比較キーを返す。

    引数: row(dict)。返り値: tupleは担当・新旧・方向・枚数・価格・時計。
    """
    return tuple(row[k] for k in ('owner', 'action', 'side', 'qty', 'price', 'decision', 'fill'))


def main():
    """完成した場だけ読んで最初の分岐と会計差を保存する。

    引数: なし。返り値: None。
    """
    records = []
    for path in sorted((HERE / 'results_go').glob('*_Night.json')):
        if path.stem == '2026-10-26_Night':
            continue
        result = json.loads(path.read_text(encoding='utf-8'))
        go = next(c for c in result['cases'] if c['config']['id'] == 'C00')
        payload = pickle.loads((ROOT / 'work/preus148/inputs' / f'{path.stem}.pkl').read_bytes())
        times = payload['data']['ready']['time_s']
        old_orders = payload['baseline']
        input_counts=dict(old_rows=len(times),current_rows=result['counts']['NK225_採用'],
                          old_invalid_quotes=int(np.sum(~payload['data']['quotes']['quote_valid'])),
                          current_invalid_quotes=go['diagnostics']['継続/core'].get('異常気配',0))
        input_counts['row_difference']=input_counts['current_rows']-input_counts['old_rows']
        input_counts['difference_equals_invalid_quotes']=input_counts['row_difference']==input_counts['current_invalid_quotes']
        old = []
        for o in old_orders:
            old.append(dict(owner=('core', 'addon', 'episode')[int(o[2] // 10_000_000)],
                            action='new' if o[7] else 'close', side=int(o[3]), qty=int(o[4]), price=float(o[5]),
                            decision=float(times[int(o[1])]), fill=float(times[int(o[0])]),
                            decision_jst=clock(times[int(o[1])]), fill_jst=clock(times[int(o[0])]), reason=int(o[6]),
                            source_index=int(o[1]), fill_index=int(o[0]), parent=int(o[2])))
        new = []
        for o in go['events'] or []:
            s, f = o['signal'], o['fill']
            new.append(dict(owner=s['owner'], action=s['action'], side=s['side'], qty=f['Quantity'], price=f['Price'],
                            decision=s['time'], fill=f['Time'], decision_jst=clock(s['time']), fill_jst=clock(f['Time']),
                            reason=s['reason_code'], source_index=o['decision_index'], fill_index=o['fill_index'], parent=s['campaign']))
        roles = []
        for role in ('core', 'addon', 'episode'):
            a, b = [o for o in old if o['owner'] == role], [o for o in new if o['owner'] == role]
            prefix = 0
            for x, y in zip(a, b):
                if semantic(x) != semantic(y):
                    break
                prefix += 1
            matcher = SequenceMatcher(a=[semantic(o) for o in a], b=[semantic(o) for o in b], autojunk=False)
            changes = [dict(kind=tag, old=a[i:j], current=b[k:l]) for tag, i, j, k, l in matcher.get_opcodes() if tag != 'equal']
            old_cash = sum(-o['side'] * o['qty'] * o['price'] * 100 for o in a)
            new_cash = sum(-o['side'] * o['qty'] * o['price'] * 100 for o in b)
            roles.append(dict(role=role, old_orders=len(a), current_orders=len(b), common_prefix=prefix,
                              old_net=old_cash, current_net=new_cash, difference=new_cash-old_cash,
                              first_old=a[prefix] if prefix < len(a) else None,
                              first_current=b[prefix] if prefix < len(b) else None, changes=changes,
                              current_diagnostics=go['diagnostics'].get('継続/' + role, {})))
        old_net = float(-np.sum(old_orders[:, 3] * old_orders[:, 4] * old_orders[:, 5]) * 100)
        records.append(dict(session=path.stem, old_net=old_net, current_net=go['Gross'], difference=go['Gross']-old_net,
                            old_orders=len(old), current_orders=len(new), roles=roles, raw_counts=result['counts'],input_counts=input_counts))
    target = HERE / 'engine現Goと保存145の注文差149.json'
    target.write_text(json.dumps(dict(rows=records, financial_replays=0), ensure_ascii=False, indent=2), encoding='utf-8')
    for r in records:
        print(r['session'], r['old_net'], r['current_net'], r['difference'], [(x['role'], x['difference'], x['common_prefix']) for x in r['roles']])


if __name__ == '__main__':
    main()
