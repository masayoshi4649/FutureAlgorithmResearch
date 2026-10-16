"""実損益を一切読まず、採用基準の境界と順位だけを人工会計で検査する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

import assessment


HERE = Path(__file__).resolve().parent
SESSIONS = [f'人工日{index//2:02d}_'+('Day' if index % 2 == 0 else 'Night') for index in range(32)]
SYMBOLS = ('TOPIX', 'NK225')


def _digest(path: Path) -> str:
    """
    機能: 人工検査が参照したソースの指紋を計算する。
    引数: path(Path)はソース又は数値基準のファイル。
    返り値: strはSHA256。金融結果、原本、APIは参照しない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _aggregate(rows: list[dict]) -> dict:
    """
    機能: 人工の親会計行を商品内で足し、割合と平均金額を独立に作る。
    引数: rows(list[dict])は人工の同一商品会計。
    返り値: dictは検査に必要な集計。assessmentの計算関数を再利用しない。
    """
    fields = ('profit', 'loss', 'net', 'campaigns', 'winning_campaigns', 'losing_campaigns', 'flat_campaigns')
    totals = {key: sum(row[key] for row in rows) for key in fields}
    aw = totals['profit']/totals['winning_campaigns'] if totals['winning_campaigns'] else None
    al = totals['loss']/totals['losing_campaigns'] if totals['losing_campaigns'] else None
    totals.update(average_win=aw, average_loss=al, payoff=aw/al if aw is not None and al is not None else None,
                  profit_share=totals['profit']/(totals['profit']+totals['loss']) if totals['profit']+totals['loss'] else None,
                  session_count=len(rows), active_sessions=sum(row['campaigns'] > 0 for row in rows),
                  no_trade_sessions=sum(row['campaigns'] == 0 for row in rows),
                  positive_sessions=sum(row['net'] > 1e-5 for row in rows),
                  losing_sessions=sum(row['net'] < -1e-5 for row in rows),
                  all_sessions_profitable=bool(rows) and all(row['net'] > 1e-5 for row in rows))
    return totals


def _stability(rows: list[dict], quantity: int) -> dict:
    """
    機能: 人工配置予算100円/設定枚を使い、場別の損失指標を独立に作る。
    引数: rows(list[dict])は人工同商品会計、quantity(int)は配置枚数。
    返り値: dictは既存stabilityと同形の判定用値。実リスクの模倣ではない。
    """
    active = [row for row in rows if row['campaigns'] > 0]
    negative = [row for row in active if row['net'] < -1e-5]
    positive = [row for row in active if row['net'] > 1e-5]
    unit = quantity*100.
    best = max(rows, key=lambda row: row['net'])
    return dict(session_count=len(rows), active_sessions=len(active), no_trade_sessions=len(rows)-len(active),
        positive_sessions=len(positive), losing_sessions=len(negative),
        flat_active_sessions=len(active)-len(positive)-len(negative),
        losing_active_rate=len(negative)/len(active) if active else None,
        downside_rms_units=math.sqrt(sum(min(row['net']/unit, 0.)**2 for row in active)/len(active)) if active else None,
        worst_session_loss_yen=max((-row['net'] for row in negative), default=0.),
        worst_session_loss_units=max((-row['net']/unit for row in negative), default=0.),
        configured_quantity=quantity,
        activity_adequate=len(active) >= 16 and sum(row['campaigns'] for row in active) >= 20,
        best_session=best['session'],
        without_best_session_net=sum(row['net'] for row in rows if row['session'] != best['session']))


def _case(config: dict, nets: list[float] | dict[str, list[float]],
          counts: list[int] | None = None, flat_active: bool = False) -> dict:
    """
    機能: 32場両商品の人工会計、期間集計、安定性を作成する。
    引数: config(dict)は確定条件、nets(list[float] | dict)は人工収支、counts(list[int] | None)は親数。
          flat_active(bool)は収支0の場にも横ばい親を与える指定。
    返り値: dictはresearchからassessmentへ渡す形と同じ人工入力。
    """
    by_symbol = nets if isinstance(nets, dict) else {symbol: nets for symbol in SYMBOLS}
    rows = []
    for symbol in SYMBOLS:
        for index, net in enumerate(by_symbol[symbol]):
            number = counts[index] if counts is not None else int(abs(net) > 1e-5 or flat_active)
            rows.append(dict(session=SESSIONS[index], symbol=symbol, profit=max(net, 0.), loss=max(-net, 0.),
                net=float(net), campaigns=number, winning_campaigns=number if net > 1e-5 else 0,
                losing_campaigns=number if net < -1e-5 else 0,
                flat_campaigns=number if abs(net) <= 1e-5 else 0))
    periods, stability = {}, {}
    for name, scope in (('前16', SESSIONS[:16]), ('後16', SESSIONS[16:]), ('全32', SESSIONS)):
        periods[name], stability[name] = {}, {}
        for symbol in SYMBOLS:
            selected = [row for row in rows if row['symbol'] == symbol and row['session'] in scope]
            quantity = sum(config['allocations'][symbol]) if config['kind'] == 'portfolio' else config['quantity'][symbol]
            periods[name][symbol] = _aggregate(selected)
            stability[name][symbol] = _stability(selected, quantity)
    return dict(config=deepcopy(config), rows=rows, periods=periods, stability=stability, ledgers={})


def _fixture(changes: dict[str, dict] | None = None) -> dict:
    """
    機能: 確定121条件を維持したまま、全条件へ人工会計を配置する。
    引数: changes(dict[str,dict] | None)は置換する人工条件。
    返り値: dictは全121条件の入力。未指定新条件は全場無取引で、旧G0だけ活動させる。
    """
    configs, _ = assessment._catalog()
    values = {config['id']: _case(config, [0.]*32) for config in configs}
    old = values['OLD_G0']['config']
    values['OLD_G0'] = _case(old, [100.]*24+[-20.]*8)
    values.update(changes or {})
    return values


def _replace(values: dict, ident: str, nets: list[float] | dict[str, list[float]],
             counts: list[int] | None = None, flat_active: bool = False) -> None:
    """
    機能: 条件や数量を変えず、人工損益パターンだけを置換する。
    引数: values(dict)は全条件入力、ident(str)はID、nets(list[float] | dict)は収支、
          counts(list[int] | None)は親数、flat_active(bool)は横ばい親指定。
    返り値: None。実損益や台帳を読み込まず、人工入力だけを変更する。
    """
    values[ident] = _case(values[ident]['config'], nets, counts, flat_active)


def _reject(values: dict) -> bool:
    """
    機能: 人工的に壊した会計入力が、採用判定へ進めないことを確認する。
    引数: values(dict)は不整合を注入した人工入力。
    返り値: boolはValueErrorで明示的に拒否された場合のみTrue。
    """
    try:
        assessment.assess(values)
    except ValueError:
        return True
    return False


def run() -> None:
    """
    機能: 基準の等号境界、未定義値、両商品要件、最大場除外、安定性順位を人工で検査する。
    引数: なし。
    返り値: None。ソース指紋と全合格をJSONへ保存。正式金融読取・API・金融再生は0。
    """
    sources = [HERE/'assessment.py', HERE/'artificial.py', HERE.parent/'catalog.py',
               HERE.parent/'安定性の採用基準補足.json']
    fingerprints = {str(path.relative_to(HERE.parent)): _digest(path) for path in sources}
    checks = {}
    values = _fixture()
    ident = 'C_OWN_O'
    result = assessment.assess(values)
    empty = result['results'][ident]
    checks['無取引は資格も80%も全32黒字も採用も不成立'] = not any(empty[key] for key in
        ('eligible', 'both_profit_share_80', 'all32_profitable', 'adoption_achieved'))
    checks['無取引の割合と活動赤字率はNone'] = all(empty['symbols'][symbol]['profit_share'] is None and
        empty['symbols'][symbol]['metrics']['losing_active_rate'] is None for symbol in SYMBOLS)
    checks['無取引と旧対照は順位なし'] = empty['rank'] is None and result['results']['OLD_G0']['rank'] is None
    _replace(values, ident, [0.]*32, flat_active=True)
    flat = assessment.assess(values)['results'][ident]
    checks['無損失無利益は勝ちにも80%にも資格にもならない'] = not flat['eligible'] and not flat['both_profit_share_80'] and \
        all(not flat['symbols'][symbol]['zero_loss_positive'] and flat['symbols'][symbol]['payoff'] is None for symbol in SYMBOLS)
    _replace(values, ident, [10.]*32)
    zero_loss = assessment.assess(values)['results'][ident]
    checks['無損失利益正は比率Noneと別表示を維持'] = all(zero_loss['symbols'][symbol]['zero_loss_positive'] and
        zero_loss['symbols'][symbol]['payoff'] is None and zero_loss['symbols'][symbol]['payoff_status'] == '無損失利益正・比率未定義'
        for symbol in SYMBOLS)
    checks['無損失利益正の十分活動は別資格かつ80%全32黒字達成'] = all(zero_loss[key] for key in
        ('eligible', 'both_profit_share_80', 'all32_profitable', 'adoption_achieved'))
    # ----------------------------------------
    # 活動数と完結親数は独立した必要条件。
    _replace(values, ident, [10.]*16+[0.]*16, [2]*4+[1]*12+[0]*16)
    boundary = assessment.assess(values)['results'][ident]
    checks['16活動20親の等号境界は資格あり'] = boundary['eligible']
    _replace(values, ident, [10.]*15+[0.]*17, [2]*5+[1]*10+[0]*17)
    checks['15活動20親は資格なし'] = not assessment.assess(values)['results'][ident]['eligible']
    _replace(values, ident, [10.]*16+[0.]*16, [2]*3+[1]*13+[0]*16)
    checks['16活動19親は資格なし'] = not assessment.assess(values)['results'][ident]['eligible']
    _replace(values, ident, [10.]*24+[-10.]*8)
    checks['平均利益損失比1は厳密不合格'] = not assessment.assess(values)['results'][ident]['eligible']
    _replace(values, ident, [10.0001]*24+[-10.]*8)
    checks['平均利益損失比1超は資格境界合格'] = assessment.assess(values)['results'][ident]['eligible']
    _replace(values, ident, [10.]*24+[-7.5]*8)
    checks['金額80%等号は達成'] = assessment.assess(values)['results'][ident]['both_profit_share_80']
    _replace(values, ident, [10.]*24+[-7.5001]*8)
    checks['金額80%未満は未達'] = not assessment.assess(values)['results'][ident]['both_profit_share_80']
    _replace(values, ident, [10.]*8+[-10.]*24)
    checks['合計赤字は十分活動でも資格なし'] = not assessment.assess(values)['results'][ident]['eligible']
    _replace(values, ident, dict(TOPIX=[40.]*24+[-5.]*8, NK225=[10.]*24+[-7.5001]*8))
    two_products = assessment.assess(values)['results'][ident]
    checks['片商品だけ80%では両商品達成にしない'] = two_products['symbols']['TOPIX']['profit_share_80'] and \
        not two_products['both_profit_share_80'] and not two_products['adoption_achieved']
    # ----------------------------------------
    # 3指標の非悪化は全部必要。最大利益金額は判定にも順位にも使わない。
    _replace(values, ident, [40.]*24+[-5.]*8)
    good = assessment.assess(values)['results'][ident]
    checks['同赤字率で下方偏差最大赤字改善の両商品は採用達成'] = good['adoption_achieved'] and not good['all32_profitable']
    for metric in assessment.METRICS:
        altered = deepcopy(values)
        baseline_metric = altered['OLD_G0']['stability']['全32']['NK225'][metric]
        if metric == 'losing_active_rate':
            _replace(altered, ident, dict(TOPIX=[40.]*24+[-5.]*8, NK225=[100.]*23+[-1.]*9))
        else:
            altered[ident]['stability']['全32']['NK225'][metric] = baseline_metric+.001
        assessed = assessment.assess(altered)['results'][ident]
        checks['一商品だけの'+metric+'悪化を採用成功にしない'] = assessed['eligible'] and \
            not assessed['stability_non_worsening'] and not assessed['adoption_achieved']
    equal = deepcopy(values)
    equal[ident] = _case(equal[ident]['config'], [100.]*24+[-20.]*8)
    checks['安定性3指標の等号は非悪化'] = assessment.assess(equal)['results'][ident]['stability_non_worsening']
    unknown_baseline = deepcopy(values)
    _replace(unknown_baseline, 'OLD_G0', [0.]*32)
    checks['旧対照の活動不明は非悪化に救済しない'] = not assessment.assess(unknown_baseline)['results'][ident]['stability_non_worsening']
    _replace(values, ident, [1000.]+[-2.]*31)
    dependent = assessment.assess(values)['results'][ident]
    checks['最大勝ち一場を除くと赤字なら採用不成立'] = dependent['eligible'] and \
        not dependent['without_best_session_both_positive'] and not dependent['adoption_achieved']
    _replace(values, ident, [100., 90.]+[1.]*30)
    exclusion = assessment.assess(values)['results'][ident]['symbols']['TOPIX']
    checks['同日の日夜でも最大セッション一つだけ除外'] = exclusion['best_session'] == SESSIONS[0] and \
        exclusion['without_best_session_net'] == 120.
    # ----------------------------------------
    # 候補資格内の順位を、金額や片商品の良さから分離する。
    ranked = _fixture()
    ids = ('C_OWN_O', 'R_OWN_O', 'C_N3_O')
    _replace(ranked, ids[0], [10.]*28+[-1.]*4)
    _replace(ranked, ids[1], [1000.]*24+[-.01]*8)
    _replace(ranked, ids[2], dict(TOPIX=[100.]*31+[-.01], NK225=[100.]*23+[-.01]*9))
    ranking = assessment.assess(ranked)
    checks['最大収益より悪い商品側の赤字頻度を優先'] = ranking['ranking'] == list(ids)
    checks['順位の理由に総利益を含めない'] = all(len(ranking['results'][entry]['rank_key']) == 5 for entry in ids)
    for left, right, label, metric_values in (
        ('C_OWN_O', 'R_OWN_O', '下方偏差', ((.01, .1), (.2, .1))),
        ('C_OWN_O', 'R_OWN_O', '最大赤字', ((.1, .1), (.1, .2)))):
        ranked = _fixture()
        for entry, metrics in zip((left, right), metric_values):
            _replace(ranked, entry, [40.]*24+[-5.]*8)
            for symbol in SYMBOLS:
                ranked[entry]['stability']['全32'][symbol]['downside_rms_units'] = metrics[0]
                ranked[entry]['stability']['全32'][symbol]['worst_session_loss_units'] = metrics[1]
        checks[label+'の順序が赤字率同点で優先'] = assessment.assess(ranked)['ranking'] == [left, right]
    ranked = _fixture()
    _replace(ranked, 'R_OWN_O', [50.]*24+[-5.]*8)
    _replace(ranked, 'C_OWN_O', [40.]*24+[-5.]*8)
    checks['赤字率偏差最大赤字同点では利益割合降順'] = assessment.assess(ranked)['ranking'] == ['R_OWN_O', 'C_OWN_O']
    _replace(ranked, 'R_OWN_O', [40.]*24+[-5.]*8)
    checks['全指標同点はID順'] = assessment.assess(ranked)['ranking'] == ['C_OWN_O', 'R_OWN_O']
    portfolio = _fixture()
    _replace(portfolio, 'P20_P10_T2', [40.]*24+[-5.]*8)
    portfolio_result = assessment.assess(portfolio)['results']['P20_P10_T2']
    checks['配分型の配置数量は両腿合計10と20'] = portfolio_result['symbols']['TOPIX']['configured_quantity'] == 10 and \
        portfolio_result['symbols']['NK225']['configured_quantity'] == 20
    # ----------------------------------------
    # 欠落、Noneの偽割合、非有限値や不整合は推測補完せず明示拒否。
    malformed = []
    broken = deepcopy(ranked); del broken['C_N3_O']; malformed.append(('条件欠落', broken))
    broken = deepcopy(ranked); broken['C_OWN_O']['rows'].pop(); malformed.append(('会計行欠落', broken))
    broken = deepcopy(ranked); broken['C_OWN_O']['rows'][1] = deepcopy(broken['C_OWN_O']['rows'][0]); malformed.append(('セッション重複', broken))
    broken = deepcopy(ranked); broken['C_OWN_O']['periods']['全32']['TOPIX']['profit_share'] = None; malformed.append(('利益正でNone割合', broken))
    broken = deepcopy(ranked); broken['C_OWN_O']['stability']['全32']['TOPIX']['downside_rms_units'] = float('nan'); malformed.append(('非有限偏差', broken))
    broken = deepcopy(ranked); broken['C_OWN_O']['stability']['全32']['TOPIX']['without_best_session_net'] += 1.; malformed.append(('最大場除外不整合', broken))
    broken = deepcopy(ranked); broken['C_OWN_O']['config']['quantity']['NK225'] = 2; malformed.append(('配置数量改変', broken))
    for label, broken in malformed:
        checks[label+'を拒否'] = _reject(broken)
    output = dict(全合格=all(checks.values()), 人工専用=True, 正式金融読取=0, 金融再生=0,
                  原本読取=0, NPZ読取=0, API取得=0, goal操作=0,
                  検査件数=len(checks), 検査=checks, SHA256=fingerprints,
                  条件=121, 商品数=2, 人工セッション数=32,
                  限界=['人工会計は判定器の境界検査だけであり、収益性や原板会計を証明しない',
                        '配置予算単位の任意入力は実リスク等価の検査ではない'])
    assert fingerprints == {str(path.relative_to(HERE.parent)): _digest(path) for path in sources}
    (HERE/'安定性採用判定の人工検査.json').write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=output['全合格'], 検査件数=len(checks), 不合格=[key for key, value in checks.items() if not value]), ensure_ascii=False))
    assert output['全合格']


if __name__ == '__main__':
    run()
