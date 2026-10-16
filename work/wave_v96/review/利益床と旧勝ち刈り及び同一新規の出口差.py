"""正式全31完了許可後、利益保護と回復勝ち切りを親単位で分解する。"""

from pathlib import Path

import numpy as np

import 共通独立読取 as R


def protection(ledger: dict) -> dict:
    """
    機能: 保護が有効になった親の実損益と、停止線の共存証拠を集計する。
    引数: ledger(dict)は正式保存台帳。
    返り値: dict。activeだけを利確成功又は原因とみなさない。
    """
    names = {name:i for i,name in enumerate(ledger['trend_parent_columns'])}
    parents = ledger['trend_parent_diagnostics']
    trades = {int(trade[0]):trade for trade in ledger['trades'] if int(trade[1]) == 0}
    assert len(parents) == len(trades)
    groups = {name:[] for name in ('保護有効','保護未達','床が最強線','初期線が最強線',
              '追尾線が最強線','床有効なのに純損失','床線に到達した返済','予定床より悪い約定')}
    details = []
    for parent in parents:
        values = {name:float(parent[i]) for name,i in names.items()}
        trade = trades[int(values['parent_id'])]
        assert trade[2] == values['entry_row'] and trade[3] == values['exit_row']
        assert trade[11] == values['net'] and trade[7] == values['exit_price']
        active = values['protection_active'] == 1
        owner = int(values['effective_line_owner'])
        memberships = ['保護有効' if active else '保護未達']
        if owner & 12:
            memberships.append('床が最強線')
        if owner & 1:
            memberships.append('初期線が最強線')
        if owner & 2:
            memberships.append('追尾線が最強線')
        if active and trade[11] < 0:
            memberships.append('床有効なのに純損失')
        if values['protection_line_hit'] == 1:
            memberships.append('床線に到達した返済')
        if active and trade[4]*(trade[7]-values['protection_floor']) < 0:
            memberships.append('予定床より悪い約定')
        for name in memberships:
            groups[name].append(trade)
        if active:
            details.append(dict(親=int(trade[0]),判断行=int(trade[15]),新規行=int(trade[2]),
                返済行=int(trade[3]),方向=int(trade[4]),純額円=float(trade[11]),
                費用円=float(trade[8]+trade[9]),分類=memberships,出口証拠=values))
    empty = np.empty((0,16))
    return dict(分類={name:R.totals(np.asarray(values).reshape((-1,16)) if values else empty)
                      for name,values in groups.items()},保護有効親の詳細=details,
        注意='分類は重複する。原因はreason1/2だけで判断せずowner bitと各hitを併用する。')


def shared_parents(first: dict, second: dict, fixed: dict) -> dict:
    """
    機能: 厳密同一実新規だけを元勝ち・元負け別へ分ける。
    引数: first/second(dict)は全62台帳、fixed(dict)は固定場。
    返り値: dict。取得又は数量が異なる同判断親は管理差から除き別表示。
    """
    answer = {}
    for symbol in R.SYMBOLS:
        groups = {name:dict(親=0,元純額円=0.,新純額円=0.,差円=0.)
                  for name in ('元利益親','元損失親','元ゼロ親')}
        details, changed = [], []
        for session in fixed['全31']:
            a = R.parent_map(first[session,symbol],0)
            b = R.parent_map(second[session,symbol],0)
            for key in a.keys() & b.keys():
                old, new = a[key], b[key]
                if not np.array_equal(old[[2,4,5,6,8,15]],new[[2,4,5,6,8,15]]):
                    changed.append(dict(場=session,判断行=int(old[15]),元新規行=int(old[2]),
                        新新規行=int(new[2]),元価格=float(old[6]),新価格=float(new[6])))
                    continue
                label = '元利益親' if old[11] > 0 else '元損失親' if old[11] < 0 else '元ゼロ親'
                value = groups[label]
                value['親'] += 1
                value['元純額円'] += float(old[11])
                value['新純額円'] += float(new[11])
                value['差円'] += float(new[11]-old[11])
                details.append(dict(場=session,判断行=int(old[15]),新規行=int(old[2]),方向=int(old[4]),
                    枚数=int(old[5]),価格=float(old[6]),元親=int(old[0]),新親=int(new[0]),
                    元返済行=int(old[3]),新返済行=int(new[3]),
                    元純額円=float(old[11]),新純額円=float(new[11]),差円=float(new[11]-old[11]),
                    元勝ちを新損失にした=old[11]>0>new[11],
                    元負けを新利益にした=new[11]>0>old[11]))
        answer[symbol] = dict(厳密同一実新規の元結果別=groups,
            勝ち刈り親=[v for v in details if v['元勝ちを新損失にした']],
            負け救済親=[v for v in details if v['元負けを新利益にした']],
            厳密同一実新規の全親=details,同判断だが取得変更=changed)
    return answer


def main() -> None:
    """
    機能: 根許可後のみ全18の床及び一軸管理差を保存する。
    引数: --根許可後(bool)はroot全31完了通知後のみ指定する。
    返り値: None。新策略又は反事実親の損益は再生しない。
    """
    R.permission()
    fixed, assembled = R.validate()
    ledgers, floors = {}, {}
    for cfg in fixed['条件']:
        ident = cfg['id']
        values = R.load_ledgers(ident)
        floors[ident] = {symbol:{session:protection(values[session,symbol])
            for session in fixed['全31']} for symbol in R.SYMBOLS}
        ledgers[ident] = {key:{'trades':ledger['trades']} for key,ledger in values.items()}
    pairs = [(a,b) for b,refs in assembled['comparison_pairs'].items() for a in refs]
    pairs += [(f'S{stop}_M1_{hold}',f'S{stop}_M2_{hold}') for stop in (10,20,40) for hold in ('H30','UNL')]
    pairs += [(f'S20_M{mode}_{hold}',f'S10_M{mode}_{hold}') for mode in (0,1,2) for hold in ('H30','UNL')]
    pairs = list(dict.fromkeys(pairs))
    pairs += [(fixed['対照'],fixed['主'])]
    differences = {f'{a}→{b}':shared_parents(ledgers[a],ledgers[b],fixed)
                   for a,b in dict.fromkeys(pairs)}
    R.save('全18の利益床と旧勝ち刈り及び同一実新規の出口差.json',dict(
        全合格=True,条件数=18,口座=1116,主=fixed['主'],全18利益床=floors,
        一軸同一実新規の元利益元損失別=differences,
        注意=['床有効の純損益は選択された親の事後分類。将来entryへ回さない。',
             '同一新規の管理差だけでは策略全体の差にならない。旧/新固有親は別レビューの恒等分解へ結ぶ。',
             'reason2でも初期線が最強のまま止まる場合がある。床/追尾/初期が同価格ならownerを重複記録する。'],
        計算コードSHA256=R.digest(Path(__file__)),**R.provenance()))
    print('全18の利益床と元勝ち元負け管理差を独立分類しました。',flush=True)


if __name__ == '__main__':
    main()
