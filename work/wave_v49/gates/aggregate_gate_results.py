"""見送りの損失回避・逸失利益・新しい時刻の取引を分けて報告する。"""

from __future__ import annotations

import gate_replay as run


def cycles(ledgers: list) -> dict:
    """機能: 初回の原本行・方向・価格・枚数で取引組を識別する。

    引数: ledgers(list[dict])。返り値: 取引組と損益(dict)。
    """
    output = {}
    for ledger in ledgers:
        opens = {int(o[2]): o for o in ledger['orders'] if o[7] == 1 and o[6] == 20}
        for cycle in ledger['cycles']:
            order = opens[int(cycle[0])]
            identity = ledger['session'], ledger['symbol'], int(order[0]), int(order[3]), order[5], int(order[4])
            assert identity not in output
            output[identity] = cycle[3]*ledger['config']['point_value']
    return output


def difference(baseline: dict, alternate: dict, names: list, symbol: str) -> dict:
    """機能: 元の初回が消えた組と新時刻の取引を区別し差額を検算する。

    引数: baseline/alternate(dict)、names(list[str])、symbol(str)。返り値: 差額分解(dict)。
    """
    a = {key: value for key, value in baseline.items() if key[0] in names and key[1] == symbol}
    b = {key: value for key, value in alternate.items() if key[0] in names and key[1] == symbol}
    removed, added, common = set(a)-set(b), set(b)-set(a), set(a)&set(b)
    forgone = sum(max(0, a[key]) for key in removed)
    avoided = sum(max(0, -a[key]) for key in removed)
    fresh = sum(b[key] for key in added)
    changed = sum(b[key]-a[key] for key in common)
    delta = sum(b.values())-sum(a.values())
    assert abs(delta-(avoided-forgone+fresh+changed)) < 1e-5
    return dict(消えた元初回の数=len(removed), 消えた元勝ちの数=sum(a[k]>0 for k in removed),
                消えた元負けの数=sum(a[k]<0 for k in removed), 消えた元勝ちの利益円=forgone,
                消えた元負けの損失円=avoided, 別時刻の新規組数=len(added), 別時刻の新規収支円=fresh,
                同じ初回の組数=len(common), 同じ初回の損益変化円=changed, 収支差円=delta)


def main() -> None:
    """機能: 完了済み二方式×十三条件を全表示用にまとめる。

    引数: なし。返り値: なし(None)。
    """
    rows = []
    fields = ('gross_profit_yen', 'gross_loss_yen', 'net_yen', 'money_ratio', 'average_unit_payoff',
              'average_cycle_payoff', 'drawdown_yen', 'cycles', 'initial_entries', 'active_sessions',
              'win_sessions', 'session_count', 'cycle_wins', 'cycle_losses', 'worst_session', 'max_long', 'max_short')
    for method in run.IDS[:2]:
        baseline = cycles(run.read(run.HERE/'ledgers'/(method+'__G00.json.gz')))
        for gate in run.catalog():
            identifier = method+'__'+gate['id']
            source = run.read(run.HERE/'summaries'/(identifier+'.json'))
            sessions = run.read(run.HERE/'sessions'/(identifier+'.json.gz'))
            alternate = cycles(run.read(run.HERE/'ledgers'/(identifier+'.json.gz')))
            names = sorted({r['session'] for r in sessions})
            periods = {}
            for label, selected in (('旧15', [s for s in names if s != run.NEW]), ('問題Night', [run.NEW]), ('全16', names)):
                periods[label] = {}
                for symbol in ('TOPIX', 'NK225'):
                    data = source['periods'][label][symbol]
                    compact = {field: data[field] for field in fields}
                    compact['元初回との差'] = difference(baseline, alternate, selected, symbol)
                    baseline_net = sum(value for key, value in baseline.items() if key[0] in selected and key[1] == symbol)
                    assert abs(compact['net_yen']-baseline_net-compact['元初回との差']['収支差円']) < 1e-5
                    periods[label][symbol] = compact
            rows.append(dict(id=identifier, method=method, gate=gate, periods=periods,
                sessions=[{field:r[field] for field in ('session','symbol','gross_profit_yen','gross_loss_yen','net_yen','initial_entries','active_session')} for r in sessions]))
    assert len(rows) == 26
    run.save(run.HERE/'見送り条件の比較.json', dict(全合格=True, 条件数=13, 管理方式数=2, 入力口座数=832,
        実施範囲='候補1と候補2の入口見送り12条件+基準。候補3/4は未実施。',
        差額分解の意味='初回行・方向・価格・枚数が完全一致する組で対応。消えた負けを単純削除した利益ではなく、その後に別時刻で入った損益も全計上。',
        費用='手数料・滑り0、指定価格約定', 条件=rows))
    audits = [r for path in sorted((run.HERE/'audits').glob('*.json.gz')) for r in run.read(path)]
    assert len(audits) == 832
    assert sum('因果' in row for row in audits) == 52
    assert sum(row.get('元全指紋一致', False) for row in audits) == 64
    assert all(row['新規許可源全一致'] and row['保有中state依存操作が無効'] for row in audits)
    signals = run.read(run.HERE/'新規見送り信号の因果監査.json')
    orders = run.read(run.HERE/'新規約定直前の許可監査.json')
    assert signals['全合格'] and signals['入力条件数'] == 416
    assert orders['全合格'] and len(orders['結果']) == 26
    inputs = [run.V47/'inputs.pkl', run.V47/'features_depth.pkl']
    for name in ('update_20260930', 'update_20261001'):
        inputs += [run.ROOT/'work/wave_v48'/name/file for file in ('new_inputs.pkl','new_features_depth.pkl')]
    sources = [p for p in run.HERE.glob('*.py')] + [run.HERE/'条件の事前固定.json']
    outputs = [p for p in run.HERE.rglob('*.json*') if p.name != '完了.json']
    run.save(run.HERE/'完了.json', dict(全合格=True, 管理方式数=2, 条件数=13, 全口座会計数=832,
        基準の元指紋一致口座数=64, 新規見送り信号因果監査数=416, 経済因果監査口座数=52,
        全約定直前許可監査済=True, API追加取得数=0,
        入力SHA256={p.relative_to(run.ROOT).as_posix():run.sha(p) for p in inputs},
        実装仕様SHA256={p.relative_to(run.ROOT).as_posix():run.sha(p) for p in sources},
        出力SHA256={p.relative_to(run.ROOT).as_posix():run.sha(p) for p in outputs}))
    print('26条件、832口座の比較と差額分解を検算', flush=True)


if __name__ == '__main__':
    main()
