"""出口・約定対照の収支差を、共通入口と入れ替わった入口の会計へ分ける。"""

import json
from pathlib import Path
import pickle

import numpy as np

import run as common


HERE = Path(__file__).resolve().parent


def groups(round_name: str, name: str, symbol: str) -> dict:
    """機能: 全flat組を元の新規判断seqと方向で対応付ける。

    引数: round_name/name/symbol(str)。
    返り値: 組の一意キーから損益・費用・保有へ対応する辞書(dict)。
    指値と成行の実際の約定行が異なっても、元の発注判断が同じ場合だけ共通とする。
    """
    data = pickle.loads((HERE / round_name / 'ledgers' / f'{name}.pkl').read_bytes())
    found = {}
    for key, ledger in data.items():
        if key[1] != symbol:
            continue
        trades = ledger['trades']
        for group_id in np.unique(trades[:, 21]):
            rows = trades[trades[:, 21] == group_id]
            initial = rows[rows[:, 23] == 1]
            assert len(initial) == 1
            row = initial[0]
            identity = (key[0], int(row[18]), int(row[2]))
            assert identity not in found
            found[identity] = dict(net=float(rows[:, 8].sum()), gross=float(rows[:, 6].sum()),
                                   fee=float(rows[:, 7].sum()), hold=(rows[:, 1].max() - row[0]) / 60.)
    return found


def compare(round_name: str, baseline: str, target: str, symbol: str) -> dict:
    """機能: 共通・追加・除外された入口により全体損益差を厳密分解する。

    引数: round_name/baseline/target/symbol(str)。
    返り値: 合計差と構成要素の集計(dict)。出口の純粋な因果効果とは解釈しない。
    """
    base, new = groups(round_name, baseline, symbol), groups(round_name, target, symbol)
    shared = set(base) & set(new)
    added, removed = set(new) - set(base), set(base) - set(new)
    delta = sum(v['net'] for v in new.values()) - sum(v['net'] for v in base.values())
    shared_delta = sum(new[k]['net'] - base[k]['net'] for k in shared)
    added_net = sum(new[k]['net'] for k in added)
    removed_net = sum(base[k]['net'] for k in removed)
    assert abs(delta - (shared_delta + added_net - removed_net)) < 1e-5
    return dict(round=round_name, baseline=baseline, target=target, symbol=symbol,
                合計収支差=delta, 共通入口数=len(shared), 共通入口の収支差=shared_delta,
                共通入口の費用前差=sum(new[k]['gross'] - base[k]['gross'] for k in shared),
                共通入口の費用差=sum(new[k]['fee'] - base[k]['fee'] for k in shared),
                追加入口数=len(added), 追加入口収支=added_net,
                除外入口数=len(removed), 除外入口収支=removed_net)


def main() -> None:
    """機能: 事前固定の出口・約定対照だけを事後会計し、選別による差を明示する。

    引数: なし。
    返り値: なし(None)。売買条件・パラメータは一切変更しない。
    """
    contrasts = [
        ('round1', 'R1_P1_N_T', 'R1_P1_N_C'), ('round1', 'R1_P1_N_T', 'R1_P1_N_R'),
        ('round1', 'R1_P2_F_T', 'R1_P2_F_C'), ('round1', 'R1_P2_F_T', 'R1_P2_F_R'),
        ('round1', 'R1_P2_N_C', 'R1_P2_F_C'),
        ('round2', 'R2_P2_C_quote', 'R2_P2_C_passive'),
        ('round2', 'R2_B1_C_quote', 'R2_B1_C_passive'),
    ]
    results = [compare(round_name, baseline, target, symbol)
               for round_name, baseline, target in contrasts for symbol in ('TOPIX', 'NK225')]
    common.save(HERE / '出口と約定の共通入口比較.json', {
        '定義': '新規判断の原本seq・方向・場が同じ組だけを共通入口とする。指値は約定時刻と価格が変わる。',
        '限定': '返済変更は保有時間と後続の取引機会を変える。共通入口差だけを全体の因果効果としない。',
        '会計恒等式': '全体差＝共通入口差＋新しく入った組収支−入らなくなった組収支',
        '比較': results})
    print(json.dumps(results, ensure_ascii=False))


if __name__ == '__main__':
    main()
