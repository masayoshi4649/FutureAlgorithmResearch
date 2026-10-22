"""00106の既公開33場だけを再集計し、小利益型を否定済みと誤記しない。"""

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SELECTED = {'TOPIX': 'E01_ADAPT_G50_ADAPT75_P1', 'NK225': 'E01_ADAPT_G25_ADAPT100_P1'}


def main() -> None:
    """
    機能: 既所有の公開JSONから数量・活動・利益粒度と同gate価格対照を検算する。
    引数: なし。市場・原cache・金融本文又は売買エンジンを実行しない。
    返り値: None。既知33場の記述だけを新しい私有JSONへ保存する。
    """
    source = HERE/'00106公開会計の同bytes参照.json'
    payload = source.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == '7241003ddbc89329f2382e4c52321e64e6a6c99fd999878ad7b428947eb87df3'
    data = json.loads(payload)
    result, checks = {}, 0
    for symbol, mid in SELECTED.items():
        case = data['cases'][mid]
        rows = [r for r in case['rows'] if r['symbol'] == symbol]
        active = [r for r in rows if r['campaigns']]
        full = case['metrics'][symbol]['full']
        assert len(rows) == 33 and sum(r['net'] for r in rows) == full['net']
        assert sum(r['net'] > 0 for r in rows) == full['positive']
        assert sum(r['net'] < 0 for r in rows) == full['negative']
        assert sum(r['campaigns'] for r in rows) == full['campaigns']
        assert sum(r['fees'] for r in rows) == full['fees']
        checks += 6
        fee, cap = (41.8, 10) if symbol == 'TOPIX' else (11., 20)
        for row in active:
            q = row['winning_lots']
            assert row['campaigns'] == row['winning_campaigns'] == 1 and row['losing_lots'] == 0
            assert row['fees'] == 2*math.floor(q*fee+1e-9)
            checks += 2
        boundary = [b for b in case['boundary'] if b['symbol'] == symbol and b['session'] in {r['session'] for r in active}]
        assert len(boundary) == len(active)
        assert all(b['停止判断']['種別'] == '利益目標' for b in boundary)
        checks += 2
        gate = 'G50' if symbol == 'TOPIX' else 'G25'
        comparisons = {mid: {k: full[k] for k in ('net', 'positive', 'negative', 'no_trade')}}
        for execution in ('FAK0', 'FAK1'):
            key = f'E01_FAK_{gate}_{execution}_P1'
            f = data['cases'][key]['metrics'][symbol]['full']
            comparisons[key] = {k: f[k] for k in ('net', 'positive', 'negative', 'no_trade')}
        result[symbol] = dict(id=mid, total_net=full['net'], black=full['positive'], red=full['negative'], no_trade=full['no_trade'],
            mean_all=full['net']/33, median_all=statistics.median(r['net'] for r in rows),
            mean_active=statistics.mean(r['net'] for r in active), median_active=statistics.median(r['net'] for r in active),
            minimum_active_net=min(r['net'] for r in active), maximum_active_net=max(r['net'] for r in active),
            actual_quantity_distribution=dict(Counter(str(r['winning_lots']) for r in active)),
            mean_actual_quantity=statistics.mean(r['winning_lots'] for r in active),
            average_initial_cap_fraction=statistics.mean(r['winning_lots']/cap for r in active),
            initial_goal_distribution=dict(Counter(str(b['目標円']) for b in boundary)),
            maximum_observed_parent_liquidation_loss=case['risk'][symbol]['maximum_fee_liquidation_MAE_yen'],
            without_top3_net=case['metrics'][symbol]['top3']['net'],
            day=case['metrics'][symbol]['day'], night=case['metrics'][symbol]['night'],
            same_gate_price_comparisons=comparisons, fak_policy_summary=case['fak_summary'][symbol])
    files = [ROOT/'work/e01_adaptive_price_20261014/engine'/name for name in
             ('catalog.py', 'entry_policy.py', 'sizing_engine.py', 'interface.py', 'context.py', 'daily.py')]
    proof = dict(全合格=True, 検算数=checks, 公開source_SHA256=hashlib.sha256(payload).hexdigest(),
        公開原本目的別読取=1, 以後所有copy参照=True, 市場=0, 原cache=0, 金融本文=0, 新金融=0, API=0,
        selected=result, 実装source_SHA256={p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        留保='既知33場での既選択を記述するだけ。数量分布は各活動場1完結親・勝ち新規枚数と往復料の一致から照合。未来40場の成績ではない。')
    path = HERE/'00106の活動と実数量及び同入口価格対照の小検算.json'
    assert not path.exists()
    path.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検算数=checks), ensure_ascii=False))


if __name__ == '__main__':
    main()
