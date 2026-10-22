"""既存の独立会計射影から、両側上限と固定買売建値差だけを集計する。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
OUT = HERE/'result'
MAIN_SHA = 'e5661b12b3ff52979136fdc6ed5adcbde19a8e145406fb2922cd8a6fd5cb3a3d'


def summarize(method: str, cases: list) -> dict:
    """
    機能: 一条件四十場の飽和数と同枚数時の固定建値差を要約する。
    引数: method(str)は条件ID、cases(list[dict])は独立会計で確認した在庫状態。
    返り値: dictは全40分母と上限到達場だけの条件付き統計。
    """
    assert len(cases) == 40
    saturated = [row for row in cases if row['both_caps']]
    balanced = [row for row in cases if row['balanced']]
    average_difference = [row['sell_minus_buy_average'] for row in saturated]
    return dict(method=method,sessions=40,both_cap_sessions=len(saturated),balanced_sessions=len(balanced),
        negative_fixed_basis_at_cap=sum(row['locked_basis_gross'] < 0 for row in saturated),
        zero_fixed_basis_at_cap=sum(row['locked_basis_gross'] == 0 for row in saturated),
        positive_fixed_basis_at_cap=sum(row['locked_basis_gross'] > 0 for row in saturated),
        both_cap_total_net=sum(row['net'] for row in saturated),
        fixed_average_sell_minus_buy_min=min(average_difference) if saturated else None,
        fixed_average_sell_minus_buy_max=max(average_difference) if saturated else None,
        first_cap_case=min(saturated,key=lambda row:row['session']) if saturated else None)


def main() -> None:
    """
    機能: 新720の保存射影と旧40の既監査小会計から飽和統計を追加保存する。
    引数: なし。元市場・元結果・新旧NPZの追加読取をしない。
    返り値: None。主合格JSONを不変のまま追加診断を保存する。
    """
    main_path = OUT/'新七百二十口座と旧四十引用の独立会計監査.json'
    assert hashlib.sha256(main_path.read_bytes()).hexdigest() == MAIN_SHA
    data = json.loads((OUT/'owned/完成結果.json').read_text(encoding='utf-8'))
    projection_path = OUT/'十九条件の全四十場統計と両側上限固定建値差.json'
    projection_raw = projection_path.read_bytes()
    projection = json.loads(projection_raw)
    cases = list(projection['saturation'])
    # ----------------------------------------
    # 旧3/3は配列を再読せず、既監査の各側netと参照BBOから平均建値を逆算する。
    baseline_cases = []
    for row in data['baseline']['rows']:
        long,short = int(row['max_long']),int(row['max_short'])
        case = dict(session=row['session'],method='I3_G3',long=long,short=short,
            both_caps=long==short==10,balanced=long==short and long>0,
            basis='既監査の各側小会計とBBOから逆算。旧NPZの追加読取なし。')
        assert long+short == row['entries']
        if case['balanced']:
            qty = long
            context = row['context']
            bid,ask = context['reference_bid'],context['reference_ask']
            buy_sum = qty*bid-(row['long_net']+82*qty)/1000
            sell_sum = qty*ask+(row['short_net']+82*qty)/1000
            difference = sell_sum-buy_sum
            spread = ask-bid
            net = difference*1000-qty*spread*1000-82*(long+short)
            assert net == row['net']
            case.update(buy_average=buy_sum/qty,sell_average=sell_sum/qty,
                sell_minus_buy_average=difference/qty,locked_basis_gross=difference*1000,
                terminal_spread=spread,spread_liability=qty*spread*1000,
                fees=82*(long+short),net=net)
        baseline_cases.append(case)
    cases.extend(baseline_cases)
    summaries = {spec['id']:summarize(spec['id'],[row for row in cases if row['method']==spec['id']])
                 for spec in data['specs']}
    assert summaries['I3_G10']['both_cap_sessions'] == 0
    assert summaries['I3_G1']['both_cap_sessions'] == 38
    proof = dict(passed=True,main_audit_sha256=MAIN_SHA,
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        previous_projection_sha256=hashlib.sha256(projection_raw).hexdigest(),
        summaries=summaries,baseline_cases=baseline_cases,
        恒等式='買売が各q枚の間はnet=(売建値合計−買建値合計)×1000−q×(終端ask−bid)×1000−82×2q。共通価格水準の移動は相殺し、気配幅と固定建値差と料が残る。',
        解釈='両側10枚へ早く達する狭間隔では、売平均が買平均より低いまま固定される場がある。一方I3_G10は両側10枚到達0/40でも28赤字なので、飽和だけが損失の理由ではない。',
        留保='上限到達場だけの建値差は条件付き説明で予測正答率ではない。新720の建値差は保存注文から独立照合済み、旧40は既監査小会計に委譲した逆算。共通価格をBBO気配幅と混同しない。',
        raw_market_reads=0,original_result_reads=0,npz_reads=0,financial_replay=0,
        registry_changes=0,main_audit_changes=0)
    target = OUT/'十九条件の両側飽和場数と固定建値差の独立集計.json'
    assert not target.exists()
    payload = (json.dumps(proof,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    target.write_bytes(payload)
    assert hashlib.sha256(main_path.read_bytes()).hexdigest() == MAIN_SHA
    compact = {name:{key:row[key] for key in ('both_cap_sessions','balanced_sessions',
        'negative_fixed_basis_at_cap','both_cap_total_net','fixed_average_sell_minus_buy_min',
        'fixed_average_sell_minus_buy_max')} for name,row in summaries.items()}
    print(json.dumps(dict(passed=True,sha256=hashlib.sha256(payload).hexdigest(),summaries=compact,
        first_I3_G1=summaries['I3_G1']['first_cap_case'],first_baseline=summaries['I3_G3']['first_cap_case']),ensure_ascii=False))


if __name__ == '__main__':
    main()
