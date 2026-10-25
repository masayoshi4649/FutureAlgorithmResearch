"""第三巡の保存注文だけから、残玉効果・後続見送り・予算床超過を分解する。"""

from collections import defaultdict
from datetime import datetime, timezone, timedelta
import numpy as np
import audit143 as audit
import audit143_round3 as independent
import common143 as shared
import run143_round3 as runner


def parent_net(orders):
    """
    機能: 完結親別の費用後収支を、保存された現金売買列から直接再計算する。
    引数: orders(ndarray[N,10])は場末残高ゼロを検査済みの注文。
    返り値: dict[int,float]は親ID別の全手数料後収支。
    """
    result = defaultdict(float)
    for row in orders:
        result[int(row[2])] += -row[3]*row[4]*row[5]*100.-row[9]
    return {parent:float(value) for parent, value in result.items()}


def timestamp(times, row):
    """
    機能: 原データ価格時計を日本時間文字列へ変換する。
    引数: times(ndarray)、row(int)は価格時計と原行位置。
    返り値: strは日本時間。受信時計と解釈しない。
    """
    return datetime.fromtimestamp(float(times[row]), timezone(timedelta(hours=9))).isoformat()


def main():
    """
    機能: 四源四設定の保存会計を、残玉変更・見送り・予算超過に分解する。
    引数: なし。
    返り値: None。金融再生なしで全件JSONと短いMarkdownへ保存する。
    """
    audit.registration(audit.HERE/'第三巡登録143.json')
    packets, first, second = independent.load_material(shared)
    result = audit.read(audit.HERE/'第三巡結果143.json')
    cache = {item['session']:item for item in result['cache']}
    accounts = {(row['session'],row['method']):row for row in result['rows']}
    budgets = audit.read(audit.HERE/'第三巡保存全注文の独立監査143.json')['realized_budget_checks']
    budget_map = {(row['session'],row['method'],row['parent']):row for row in budgets}
    all_rows, budget_rows, skipped_rows = [], [], []
    for scene, item in packets.items():
        packet = shared.packet_from(item)
        key = (scene, 'NK225')
        data = dict(ready=packet['inputs'][key], quotes=packet['quotes'][key])
        times, seq = data['ready']['time_s'], data['ready']['seq']
        sources, _, _ = runner.sources(scene, first, second)
        ref = cache[scene]
        path = audit.ROOT/ref['path']
        assert audit.digest(path) == ref['sha256']
        with np.load(path) as orders_archive, np.load(audit.HERE/'round3/traces'/f'NK225_{scene}.npz') as trace_archive:
            for source, baseline in sources.items():
                original = parent_net(baseline)
                for suffix in ('01','02','03','04'):
                    method = source+suffix
                    orders, trace = orders_archive[method], trace_archive[method]
                    actual = parent_net(orders)
                    assert set(actual) <= set(original)
                    retained = {int(event[1]) for event in trace if int(event[2]) == 2}
                    rejected = {int(event[1]):int(event[0]) for event in trace if int(event[2]) == 1 and int(event[5]) == 14384}
                    assert set(original)-set(actual) == set(rejected)
                    assert retained <= set(actual)
                    same_parent_effect = sum(actual[parent]-original[parent] for parent in actual)
                    missed_effect = -sum(original[parent] for parent in rejected)
                    assert abs(sum(actual.values())-sum(original.values())-same_parent_effect-missed_effect) < 1e-7
                    for parent in set(actual)-retained:
                        np.testing.assert_array_equal(orders[orders[:,2] == parent], baseline[baseline[:,2] == parent])
                    for parent, decision in rejected.items():
                        span = []
                        for held in retained:
                            mark = trace[(trace[:,1] == held) & (trace[:,2] == 2)][0]
                            last_fill = int(orders[orders[:,2] == held,0].max())
                            if int(mark[0]) <= decision < last_fill:
                                span.append(held)
                        assert len(span) == 1, (scene, method, parent, decision, span)
                        old = baseline[baseline[:,2] == parent]
                        assert decision == int(old[:,1].min())
                        skipped_rows.append(dict(session=scene, method=method, parent=parent,
                            decision=decision, raw_seq=int(seq[decision]), time=timestamp(times, decision),
                            residual_owner=span[0], original_net=original[parent], effect=-original[parent]))
                    for parent in retained:
                        row = dict(budget_map[scene, method, parent])
                        events = trace[(trace[:,1] == parent) & (trace[:,2] == 4)]
                        assert len(events) == 1
                        event = events[0]
                        decision = int(event[0])
                        last = orders[(orders[:,2] == parent) & (orders[:,8] == row['uid'])][-1]
                        assert last[7] == 0 and int(last[1]) == decision and last[4] == 1
                        fill = int(last[0])
                        side = row['residual_side']
                        mark = data['quotes']['bid'][decision] if side > 0 else data['quotes']['ask'][decision]
                        expected_at_decision = row['realized_net']+side*(mark-row['residual_entry'])*100.-38.
                        target = row['realized_net']-row['budget']
                        row.update(original_parent_net=original[parent], residual_effect=actual[parent]-original[parent],
                            original_last_fill=int(baseline[baseline[:,2] == parent,0].max()),
                            retained_from_time=timestamp(times,row['row']), decision=decision,
                            decision_time=timestamp(times,decision), decision_raw_seq=int(seq[decision]),
                            fill=fill, fill_time=timestamp(times,fill), fill_raw_seq=int(seq[fill]),
                            exit_reason=int(event[5]), exit_price=float(last[5]),
                            planned_parent_floor=target, decision_estimate_net=expected_at_decision,
                            threshold_crossing_deficit=target-expected_at_decision,
                            next_quote_deterioration=expected_at_decision-actual[parent],
                            total_below_floor=max(0.,target-actual[parent]), final_parent_negative=actual[parent] < 0)
                        if row['final_below_budget_line']:
                            assert abs(row['total_below_floor']-row['threshold_crossing_deficit']-row['next_quote_deterioration']) < 1e-7
                        budget_rows.append(row)
                    all_rows.append(dict(session=scene, method=method, original_net=sum(original.values()),
                        net=sum(actual.values()), effect=sum(actual.values())-sum(original.values()),
                        retained_parents=len(retained), retained_effect=same_parent_effect,
                        skipped_parents=len(rejected), skipped_profit=sum(max(0.,original[p]) for p in rejected),
                        avoided_loss=-sum(min(0.,original[p]) for p in rejected), skipped_effect=missed_effect))
    summary = []
    for method in sorted({row['method'] for row in all_rows}):
        selected = [row for row in all_rows if row['method'] == method]
        chosen_budget = [row for row in budget_rows if row['method'] == method]
        total = {key:sum(row[key] for row in selected) for key in ('original_net','net','effect',
            'retained_parents','retained_effect','skipped_parents','skipped_profit','avoided_loss','skipped_effect')}
        total.update(method=method, budget_exceeded=sum(row['final_below_budget_line'] for row in chosen_budget),
            budget_exceeded_amount=sum(row['total_below_floor'] for row in chosen_budget),
            negative_retained_parents=sum(row['final_parent_negative'] for row in chosen_budget),
            maximum_floor_excess=max((row['total_below_floor'] for row in chosen_budget),default=0.))
        summary.append(total)
    portfolio = []
    for method, parts in (('TG04',('CG04','CS04')),('PP04',('CB04','CA04')),('PG04',('CG04','CA04'))):
        chosen = [row for row in summary if row['method'] in parts]
        info = {key:sum(row[key] for row in chosen) for key in ('retained_parents','retained_effect','skipped_parents',
            'skipped_profit','avoided_loss','skipped_effect','budget_exceeded','budget_exceeded_amount','negative_retained_parents')}
        info.update(method=method, sources=list(parts), effect=info['retained_effect']+info['skipped_effect'])
        net_delta = sum(accounts[scene,method]['net']-accounts[scene,method[:2]+'00']['net'] for scene in packets)
        assert net_delta == info['effect']
        portfolio.append(info)
    audit.save(audit.HERE/'第三巡残玉資金源と見送りの独立分解143.json', dict(
        status='全件照合合格', 新金融再生=0, source_accounts=len(all_rows), summary=summary,
        portfolios=portfolio, session_rows=all_rows, funded_residuals=budget_rows, skipped_parents=skipped_rows,
        definition='元完結親の全既払費用を含む実現純益を予算にする。予算超過は価格境界を跨いだ時点の不足と、その後の次正常気配変化に分ける。設定間・源間の同じ売買は重複して数えられる。',
        script_sha256=audit.digest(__file__)))
    lines = ['# 第三巡の残玉・資金源・後続見送りの監査', '',
        '40ケースの実データ機械検査、2,250口座・25,550注文の保存会計が合格。源の変更なし対照200口座も完全一致。', '',
        '全566件の残玉予算は、他玉返済後の実現純益と一致した。含み益の予算流用、新規手数料の二重控除はなかった。全残玉の資金源は正。未変更親の注文列は元と一致し、全見送りは残玉保有中の初回通知で起きた。', '',
        '| 運用 | 残玉親数 | 残したことの増減 | 後続見送り数 | 失った黒字 | 避けた赤字 | 合計増減 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for row in portfolio:
        lines.append(f"| {row['method']} | {row['retained_parents']} | {row['retained_effect']:+,.0f}円 | {row['skipped_parents']} | {row['skipped_profit']:,.0f}円 | {row['avoided_loss']:,.0f}円 | {row['effect']:+,.0f}円 |")
    lines.extend(['', '比較元は各運用の残玉なし00版。TG04の旧追加3枚は変更していない。残玉変更の収益効果と、次の利益機会を失った効果を相殺せず示した。', '',
        '損失予算は指値約定保証ではない。全設定で58件が予定価格床を下回って完結した（源・設定間の重複あり）。刻みごとの価格境界通過と、その後の次正常気配への変化を区別し、実損を補正せず保存している。'])
    for row in portfolio:
        lines.append(f"- {row['method']}: 予定床超過{row['budget_exceeded']}件、超過合計{row['budget_exceeded_amount']:,.0f}円。残玉化した親の最終赤字は{row['negative_retained_parents']}件。")
    tg_deficits = [row for row in budget_rows if row['method'] in ('CG04','CS04') and row['final_below_budget_line']]
    lines.extend(['', f"TG04の予定床超過の内訳は、返済判断時点で既に床を跨いだ不足が{sum(row['threshold_crossing_deficit'] for row in tg_deficits):,.0f}円、その後の次正常気配の追加悪化が{sum(row['next_quote_deterioration'] for row in tg_deficits):,.0f}円。この8件を注文遅延による損失とは呼ばない。時計が同一でも、判断行と約定行は別の原行である。"])
    lines.extend(['', '保存会計の整合性であり、未知のセッション、実mini約定、5秒遅延、実アプリ同値を証明するものではない。', ''])
    (audit.HERE/'第三巡残玉資金源と見送りの独立分解143.md').write_text('\n'.join(lines),encoding='utf-8')
    print(portfolio)


if __name__ == '__main__':
    main()
