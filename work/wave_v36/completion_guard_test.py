"""全条件を再生せず、完備検査が欠落・重複・会計改竄を拒否するか確認する。"""

from copy import deepcopy
import numpy as np

import completion_guard as guard


def main() -> None:
    """機能: 人工の全26証拠と一取引を用いて、代表的な破損を拒否する。

    引数: なし。返り値: なし (None)。実データの損益を読み込まない。
    """
    results = []
    def accept(name: str) -> None:
        """機能: 一つの人工確認の成功を記録する。

        引数: name (str)。返り値: なし (None)。
        """
        results.append(dict(検査=name, 一致=True))
    def reject(name: str, call) -> None:
        """機能: 人工改竄を例外として拒否することを確認する。

        引数: name (str)、call (callable)。返り値: なし (None)。
        """
        try:
            call()
        except (AssertionError, KeyError):
            accept(name)
            return
        raise AssertionError('破損を受理: ' + name)
    inputs = {(f'人工{i:02d}', symbol): dict(last=np.zeros(i + 4)) for i in range(13) for symbol in ('TOPIX', 'NK225')}
    rows = [dict(session=k[0], symbol=k[1], prefix=1, future=1, reflection=1, 原本行会計数=len(r['last'])) for k, r in inputs.items()]
    proof = dict(全入力数=26, 全保存台帳一致=True, 全会計一致=True, 全期間時価一致=True,
        prefix=26, future=26, reflection=26, 原本行会計数=sum(len(r['last']) for r in inputs.values()), 入力別=rows)
    guard.proof_rows(proof, inputs); accept('全26の会計と未来検査を入力長へ接続')
    broken = deepcopy(proof); broken['入力別'].pop()
    reject('総数26のまま入力不足', lambda: guard.proof_rows(broken, inputs))
    broken = deepcopy(proof); broken['入力別'][0] = deepcopy(broken['入力別'][1])
    reject('全26の重複と不足', lambda: guard.proof_rows(broken, inputs))
    for field, value in (('future', 0), ('原本行会計数', 999)):
        broken = deepcopy(proof); broken['入力別'][0][field] = value
        reject('個別証拠改竄:' + field, lambda p=broken: guard.proof_rows(p, inputs))
    for field in ('全保存台帳一致', '全会計一致', '全期間時価一致'):
        broken = deepcopy(proof); broken[field] = False
        reject('独立証拠未合格:' + field, lambda p=broken: guard.proof_rows(p, inputs))
    broken = deepcopy(proof); del broken['入力別'][0]['reflection']
    reject('反射証拠の欠落', lambda: guard.proof_rows(broken, inputs))

    # ----------------------------------------
    # 同値決済と損失脚を隠さず、金額と決済枚数を別に検査する。
    ledger = dict(config=dict(point_value=1000., audit_cap=10),
        trades=[[0,0,1,2,100,105,1,2,0,1,10],[1,0,-1,3,103,105,3,4,0,1,-6],
                [2,0,1,1,104,104,5,6,0,1,0]],
        cycles=[[0,1,2,10,2,1,2,2,1,1],[1,3,4,-6,3,1,3,3,-1,1],[2,5,6,0,1,1,1,1,1,1]], stats=[0] * 11)
    row = dict(gross_profit_yen=10000., gross_loss_yen=6000., net_yen=4000.,
        profit_units=2, loss_units=3, zero_units=1, closed_units=6, cycles=3,
        two_largest_cycle_profits=[10000.], max_long=2, max_short=3)
    ready = dict(last=np.zeros(8))
    guard.session_accounting(row, ledger, ready); accept('利益損失同値の金額と決済枚数')
    for field in ('gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'zero_units', 'closed_units', 'cycles'):
        broken = deepcopy(row); broken[field] += 1
        reject('集計改竄:' + field, lambda r=broken: guard.session_accounting(r, ledger, ready))
    broken = deepcopy(row); broken['two_largest_cycle_profits'] = []
    reject('最大勝ちを隠す', lambda: guard.session_accounting(broken, ledger, ready))
    broken = deepcopy(ledger); broken['stats'][9] = 1
    reject('場末の持越し', lambda: guard.session_accounting(row, broken, ready))
    broken = deepcopy(row); broken['max_short'] = 11
    reject('片方向枚数上限超過', lambda: guard.session_accounting(broken, ledger, ready))
    broken = deepcopy(ledger); broken['cycles'][0][1] = broken['cycles'][0][2]
    reject('同一行の新規返済', lambda: guard.session_accounting(row, broken, ready))
    ready = dict(last=np.array([100.,101.,103.]), seq=np.array([2,5,8]), time_s=np.array([0.,60.,120.]))
    boundary = dict(参照行=1, seq=5, last=101., 買い枚数=2, 売り枚数=0, ネット枚数=2,
        実現損益円=0., 含み損益円=2., 時価損益円=2.)
    saved = dict(boundary, 境界時刻='1970-01-01T00:01:30+00:00', 参照時刻='1970-01-01T00:01:00+00:00')
    guard.boundary_match(boundary, saved, ready, saved['境界時刻']); accept('追加2時刻を原本asofで接続')
    for field, value in (('境界時刻','1970-01-01T00:02:00+00:00'), ('参照時刻','1970-01-01T00:00:00+00:00'), ('seq',6)):
        broken=deepcopy(saved);broken[field]=value
        reject('波境界の時計原本不一致:'+field, lambda b=broken: guard.boundary_match(boundary,b,ready,saved['境界時刻']))
    broken=deepcopy(saved);del broken['参照時刻']
    reject('主境界の参照時刻欠落', lambda: guard.boundary_match(boundary,broken,ready,saved['境界時刻']))
    value = dict(全合格=True, 検査数=len(results), 検査=results,
        新損益読取=False, 売買再生=False, API取得数=0, 現在保存物使用=False,
        ガード実装SHA256=guard.runner.digest(guard.HERE / 'completion_guard.py'))
    guard.runner.save(guard.HERE / 'completion_guard_test.json', value)
    print('完備人工', len(results), '件合格。', flush=True)


if __name__ == '__main__':
    main()
