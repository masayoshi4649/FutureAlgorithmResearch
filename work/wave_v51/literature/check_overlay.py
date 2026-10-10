"""重ね合わせ方式の損益公開順を独立した時系列イベントで監査する。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
TARGET = HERE.parent / 'overlay' / 'research.py'


def main() -> None:
    """機能: 原研究器と返済時だけ損益を更新する別実装を比較する。

    引数: なし。返り値: なし(None)。確認結果だけを同じ監査フォルダへ保存する。
    """
    spec = importlib.util.spec_from_file_location('overlay_review_target', TARGET)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    inputs, ledgers = module.load()
    models = {key: module.bar_model(key) for key in inputs}
    total_cases = event_checks = tie_cases = 0
    all_results = []
    for condition in module.catalog():
        for key, ready in sorted(inputs.items()):
            ledger = ledgers[key]
            orders = np.asarray(ledger['orders'], float).reshape(-1, 8)
            trades = np.asarray(ledger['trades'], float).reshape(-1, 11)
            events = []
            cycles = {int(cycle[0]): cycle for cycle in ledger['cycles']}
            for cid, cycle in cycles.items():
                opening = orders[(orders[:, 2] == cid) & (orders[:, 7] == 1)]
                assert len(opening) == 1
                source, fill = int(opening[0, 1]), int(opening[0, 0])
                close = int(cycle[2])
                assert source < fill <= close
                assert ready['time_s'][source] <= ready['time_s'][fill] <= ready['time_s'][close]
                tie_cases += int(ready['time_s'][source] == ready['time_s'][fill])
                assert abs(cycle[4] - ledger['config']['initial_qty'] * cycle[5]) < 1e-7
                actual = trades[trades[:, 0] == cid, 10].sum()
                assert abs(actual - cycle[3]) < 1e-7
                events.extend([(source, 0, cid), (close, 1, cid)])
            # ----------------------------------------
            # 新規準備では選択だけ、全返済イベントで初めて組損益を状態へ加える。
            state = dict(r=0., losses=0, until=0.)
            selected, released = set(), set()
            previous_source = -1
            peer = key[0], 'NK225' if key[1] == 'TOPIX' else 'TOPIX'
            for index, kind, cid in sorted(events):
                at = float(ready['time_s'][index])
                cycle = cycles[cid]
                if kind == 0:
                    assert index > previous_source
                    assert all(int(cycles[c][2]) < index for c in released)
                    own = module.snapshot(models[key], at)
                    other = module.snapshot(models[peer], at, 60)
                    if module.allow_entry(condition, own, other, int(cycle[8]), state, at):
                        selected.add(cid)
                    previous_source = index
                    event_checks += 1
                elif cid in selected:
                    released.add(cid)
                    pnl = trades[trades[:, 0] == cid, 10].sum()
                    state['r'] += pnl / cycle[4]
                    state['losses'] = state['losses'] + 1 if pnl < 0 else 0
                    if condition['risk'] == 'loss2pause45' and state['losses'] >= 2:
                        state['until'] = at + 2700
                        state['losses'] = 0
            kept = trades[np.isin(trades[:, 0], list(selected))]
            net = float(kept[:, 10].sum()) * ledger['config']['point_value']
            target = module.evaluate(condition, ready, ledger, models)
            assert abs(net - target['net_yen']) < 1e-7
            assert len(selected) == target['cycles']
            assert abs(state['r'] - target['r']) < 1e-7
            total_cases += 1
            all_results.append(dict(条件=condition['id'], セッション=key[0], 銘柄=key[1], 組数=len(selected), 収支円=net))
    result = dict(合格=True, 条件口座比較数=total_cases, 計画源行検査数=event_checks,
                  同一約定時刻内の後続行約定数_条件重複込み=tie_cases,
                  確認='返済時のみ損益を更新する独立イベント実装と32条件×46口座で一致。指標計算と仮想E01自体は元実装を継承。',
                  比較=all_results)
    (HERE / 'overlay独立会計.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k: v for k, v in result.items() if k != '比較'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
