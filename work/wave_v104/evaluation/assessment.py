"""結果前に固定する、両商品の活動資格と日々の損失抑制の判定。"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path


HERE = Path(__file__).resolve().parent
EPSILON = 1e-5
SYMBOLS = ('TOPIX', 'NK225')
METRICS = ('losing_active_rate', 'downside_rms_units', 'worst_session_loss_units')
METRIC_NAMES = dict(losing_active_rate='活動セッション赤字率',
                    downside_rms_units='配置予算単位の下方偏差',
                    worst_session_loss_units='配置予算単位の最大セッション赤字')
ADDITIVE = ('profit', 'loss', 'net', 'campaigns', 'winning_campaigns',
            'losing_campaigns', 'flat_campaigns')


def _catalog() -> tuple[list[dict], str]:
    """
    機能: 確定した121条件と事前指定の主を、金融結果と分離して読み込む。
    引数: なし。
    返り値: tuple[list[dict], str]は条件一覧と主ID。ファイル入出力はこのソース読取だけ。
    """
    spec = importlib.util.spec_from_file_location('104安定性判定用条件', HERE.parent/'catalog.py')
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.catalog(), module.PRIMARY


def _number(value: object, label: str, nonnegative: bool = False) -> float:
    """
    機能: 比較に使用する金額や指標が有限数値であることを確認する。
    引数: value(object)は対象値、label(str)は項目名、nonnegative(bool)は非負の要求。
    返り値: floatは検査済み数値。不明を0や無限大へ置換せず、不正入力はValueError。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(label+'が有限数値ではありません')
    answer = float(value)
    if nonnegative and answer < 0:
        raise ValueError(label+'が負です')
    return answer


def _count(value: object, label: str) -> int:
    """
    機能: 親数とセッション数を非負整数として検査する。
    引数: value(object)は件数、label(str)は項目名。
    返り値: intは検査済み件数。不正入力はValueError。
    """
    result = _number(value, label, True)
    if result != int(result):
        raise ValueError(label+'が整数ではありません')
    return int(result)


def _same(actual: object, expected: float | int | None, label: str) -> None:
    """
    機能: 与えられた集計値を、会計行から再計算した値と照合する。
    引数: actual(object)は入力値、expected(float | int | None)は検算値、label(str)は項目名。
    返り値: None。Noneを0扱いせず、有限値は丸め誤差だけを許して照合する。
    """
    if expected is None:
        if actual is not None:
            raise ValueError(label+'は未定義のはずです')
        return
    value = _number(actual, label)
    if not math.isclose(value, float(expected), rel_tol=1e-10, abs_tol=EPSILON):
        raise ValueError(label+'が会計行からの検算と一致しません')


def _quantity(config: dict, symbol: str) -> int:
    """
    機能: 配分型では両腿合計、単一型では設定枚数を取得する。
    引数: config(dict)は確定条件、symbol(str)は商品名。
    返り値: intは配置枚数。配置予算の分母は実リスク等価の根拠にはしない。
    """
    value = sum(config['allocations'][symbol]) if config['kind'] == 'portfolio' else config['quantity'][symbol]
    quantity = _count(value, symbol+'設定枚数')
    if quantity == 0:
        raise ValueError(symbol+'設定枚数が0です')
    return quantity


def _facts(case: dict, symbol: str, sessions: list[str]) -> dict:
    """
    機能: 商品別の会計行、全32集計、安定性を照合して判定材料を返す。
    引数: case(dict)はrows/periods/stability/config、symbol(str)は商品、sessions(list[str])は32場。
    返り値: dictは活動・親数・利益割合・損小利大・最大勝ち除外と3安定性指標。
    """
    selected = [row for row in case['rows'] if row['symbol'] == symbol]
    by_session = {row['session']: row for row in selected}
    if len(selected) != 32 or len(by_session) != 32 or set(by_session) != set(sessions):
        raise ValueError(symbol+'は全32セッション各1会計行が必要です')
    total = {key: 0. for key in ADDITIVE}
    for row in selected:
        label = symbol+'/'+row['session']+'/'
        values = {key: _number(row[key], label+key, key != 'net') for key in ADDITIVE}
        for key in ADDITIVE[3:]:
            values[key] = _count(row[key], label+key)
        _same(values['net'], values['profit']-values['loss'], label+'収支')
        if values['campaigns'] != sum(values[key] for key in ADDITIVE[4:]):
            raise ValueError(label+'親の勝ち負け横ばい件数が合いません')
        if values['campaigns'] == 0 and (values['profit'] != 0 or values['loss'] != 0 or values['net'] != 0):
            raise ValueError(label+'無取引の会計に損益があります')
        if (values['winning_campaigns'] == 0) != (values['profit'] == 0):
            raise ValueError(label+'利益と勝ち親の件数が合いません')
        if (values['losing_campaigns'] == 0) != (values['loss'] == 0):
            raise ValueError(label+'損失と負け親の件数が合いません')
        for key in ADDITIVE:
            total[key] += values[key]
    for key in ADDITIVE[3:]:
        total[key] = int(total[key])
    active = [row for row in selected if row['campaigns'] > 0]
    losing = [row for row in active if row['net'] < -EPSILON]
    positive = [row for row in active if row['net'] > EPSILON]
    average_win = total['profit']/total['winning_campaigns'] if total['winning_campaigns'] else None
    average_loss = total['loss']/total['losing_campaigns'] if total['losing_campaigns'] else None
    payoff = average_win/average_loss if average_win is not None and average_loss is not None else None
    share = total['profit']/(total['profit']+total['loss']) if total['profit']+total['loss'] > 0 else None
    count_values = dict(session_count=32, active_sessions=len(active), no_trade_sessions=32-len(active),
                        positive_sessions=len(positive), losing_sessions=len(losing))
    aggregate = case['periods']['全32'][symbol]
    for key, value in dict(total, **count_values, average_win=average_win, average_loss=average_loss,
                           payoff=payoff, profit_share=share).items():
        _same(aggregate[key], value, symbol+'/全32/'+key)
    all_profitable = len(positive) == 32
    if aggregate['all_sessions_profitable'] is not all_profitable:
        raise ValueError(symbol+'全32黒字フラグが会計行と一致しません')
    # ----------------------------------------
    # 最大利益日は使わず、同じ日の日夜でも一セッションだけを除く。
    best = max(selected, key=lambda row: row['net'])
    without_best = sum(row['net'] for row in selected if row['session'] != best['session'])
    activity_adequate = len(active) >= 16 and total['campaigns'] >= 20
    stable = case['stability']['全32'][symbol]
    expected_stability = dict(count_values, flat_active_sessions=len(active)-len(positive)-len(losing),
                              losing_active_rate=len(losing)/len(active) if active else None,
                              worst_session_loss_yen=max((-row['net'] for row in losing), default=0.),
                              without_best_session_net=without_best,
                              configured_quantity=_quantity(case['config'], symbol))
    for key, value in expected_stability.items():
        _same(stable[key], value, symbol+'/安定性/'+key)
    if stable['best_session'] != best['session'] or stable['activity_adequate'] is not activity_adequate:
        raise ValueError(symbol+'最大勝ちセッション又は活動資格が合いません')
    metrics = {}
    for key in METRICS:
        value = stable[key]
        if not active and key in ('losing_active_rate', 'downside_rms_units'):
            if value is not None:
                raise ValueError(symbol+'無取引の'+key+'はNoneが必要です')
            metrics[key] = None
        else:
            metrics[key] = _number(value, symbol+'/'+key, True)
    if metrics['losing_active_rate'] is not None and metrics['losing_active_rate'] > 1:
        raise ValueError(symbol+'活動赤字率が1を超えています')
    if not losing and (metrics['worst_session_loss_units'] != 0 or (active and metrics['downside_rms_units'] != 0)):
        raise ValueError(symbol+'赤字場がないのに負の収支指標があります')
    zero_loss_positive = total['loss'] == 0 and total['profit'] > EPSILON and total['winning_campaigns'] > 0
    payoff_gt_one = payoff is not None and payoff > 1.
    return dict(total, **count_values, average_win=average_win, average_loss=average_loss, payoff=payoff,
                profit_share=share, activity_adequate=activity_adequate,
                zero_loss_positive=zero_loss_positive, payoff_gt_one=payoff_gt_one,
                payoff_status=('無損失利益正・比率未定義' if zero_loss_positive else
                               '平均利益/平均損失' if payoff is not None else '比率未定義'),
                net_positive=total['net'] > EPSILON,
                profit_share_80=share is not None and share >= .8 and total['profit'] > EPSILON,
                best_session=best['session'], best_session_net=float(best['net']),
                without_best_session_net=float(without_best),
                without_best_session_positive=without_best > EPSILON,
                all32_profitable=all_profitable, metrics=metrics,
                configured_quantity=expected_stability['configured_quantity'])


def _symbol_assessment(facts: dict, baseline: dict) -> dict:
    """
    機能: 一商品の活動資格と旧G0への3指標比較を判定する。
    引数: facts(dict)は候補の検算済み値、baseline(dict)は同商品の旧G0値。
    返り値: dictは資格・非悪化・採用部品と日本語理由。不明同士を非悪化にしない。
    """
    reasons = []
    if facts['active_sessions'] < 16:
        reasons.append('実活動16/32セッション未満')
    if facts['campaigns'] < 20:
        reasons.append('完結親20件未満')
    if not facts['net_positive']:
        reasons.append('合計収支が黒字ではない')
    if not facts['payoff_gt_one'] and not facts['zero_loss_positive']:
        reasons.append('平均利益/平均損失が1を超えない、又は利益を伴う比率が未定義')
    eligible = facts['activity_adequate'] and facts['net_positive'] and (facts['payoff_gt_one'] or facts['zero_loss_positive'])
    comparisons = {}
    for key in METRICS:
        current, reference = facts['metrics'][key], baseline['metrics'][key]
        known = current is not None and reference is not None
        comparisons[key] = dict(value=current, baseline=reference, comparable=known,
                                delta=current-reference if known else None,
                                non_worsening=known and current <= reference)
        if not known:
            reasons.append(METRIC_NAMES[key]+'を旧G0と比較できない')
        elif current > reference:
            reasons.append(METRIC_NAMES[key]+'が旧G0より悪化')
    if not facts['profit_share_80']:
        reasons.append('相殺前金額利益割合80%未達')
    if not facts['without_best_session_positive']:
        reasons.append('最大利益セッション除外後が黒字ではない')
    return dict(facts, eligible=bool(eligible), comparisons=comparisons,
                stability_non_worsening=all(value['non_worsening'] for value in comparisons.values()),
                reasons=reasons)


def assess(summaries: dict[str, dict]) -> dict:
    """
    機能: 全121条件の両商品採用資格と安定性順位を、事前固定の基準だけで判定する。
    引数: summaries(dict[str,dict])はconfig/rows/periods/stability/ledgersを持つ全121条件。
    返り値: dictはresults、資格内順位、主、対照、未達理由。金融ファイルやAPIは読まない。
    """
    configs, primary = _catalog()
    by_id = {config['id']: config for config in configs}
    if set(summaries) != set(by_id):
        raise ValueError('全121条件が必要で、条件の追加や欠落は許可しません')
    baseline_case = summaries['OLD_G0']
    sessions = [row['session'] for row in baseline_case['rows'] if row['symbol'] == 'TOPIX']
    if len(sessions) != 32 or len(set(sessions)) != 32:
        raise ValueError('旧G0の全32セッションが必要です')
    facts = {}
    for ident, case in summaries.items():
        if case['config']['id'] != ident or case['config']['kind'] != by_id[ident]['kind']:
            raise ValueError(ident+'の条件ID又は種類が一致しません')
        if len(case['rows']) != 64 or any(row['symbol'] not in SYMBOLS for row in case['rows']):
            raise ValueError(ident+'は両商品32場の64会計行が必要です')
        for symbol in SYMBOLS:
            if _quantity(case['config'], symbol) != _quantity(by_id[ident], symbol):
                raise ValueError(ident+'の配置数量が確定条件と一致しません')
        facts[ident] = {symbol: _facts(case, symbol, sessions) for symbol in SYMBOLS}
    # ----------------------------------------
    # 総利益の大きさは順位にも採用理由にも使用しない。
    results, rank_keys = {}, {}
    for ident, value in facts.items():
        symbols = {symbol: _symbol_assessment(value[symbol], facts['OLD_G0'][symbol]) for symbol in SYMBOLS}
        eligible = all(item['eligible'] for item in symbols.values())
        both_80 = all(item['profit_share_80'] for item in symbols.values())
        non_worsening = all(item['stability_non_worsening'] for item in symbols.values())
        without_best = all(item['without_best_session_positive'] for item in symbols.values())
        adoption = eligible and both_80 and non_worsening and without_best
        reasons = [symbol+': '+reason for symbol, item in symbols.items() for reason in item['reasons']]
        if ident == 'OLD_G0':
            reasons.append('旧G0は比較対照であり、新候補の順位に含めない')
        if eligible and ident != 'OLD_G0':
            key = [max(item['metrics'][metric] for item in symbols.values()) for metric in METRICS]
            key += [-min(item['profit_share'] for item in symbols.values()), ident]
            rank_keys[ident] = key
        results[ident] = dict(symbols=symbols, eligible=eligible, both_profit_share_80=both_80,
                             stability_non_worsening=non_worsening,
                             without_best_session_both_positive=without_best,
                             adoption_achieved=adoption, all32_profitable=all(item['all32_profitable'] for item in symbols.values()),
                             comparison_only=ident == 'OLD_G0' or not adoption,
                             rank=None, rank_key=rank_keys.get(ident), reasons=reasons)
    ranking = sorted(rank_keys, key=lambda ident: tuple(rank_keys[ident]))
    for rank, ident in enumerate(ranking, 1):
        results[ident]['rank'] = rank
    return dict(schema_version=1, primary=primary, baseline_id='OLD_G0', session_count=32,
                condition_count=len(summaries), results=results, ranking=ranking,
                adoption_candidates=[ident for ident in ranking if results[ident]['adoption_achieved']],
                comparison_only=[ident for ident in summaries if results[ident]['comparison_only']],
                criteria=dict(min_active_sessions=16, min_completed_campaigns=20, min_profit_share=.8,
                    payoff_strictly_greater_than=1., positive_net_epsilon=EPSILON,
                    zero_loss_positive='比率Noneを維持し別表示した上で損小利大資格に含める',
                    stability_metrics=list(METRICS), all_stability_metrics_both_non_worsening=True,
                    ranking=['悪い商品側の活動赤字率昇順', '悪い商品側の配置予算単位下方偏差昇順',
                             '悪い商品側の配置予算単位最大赤字昇順', '悪い商品側の金額利益割合降順', 'ID昇順'],
                    best_exclusion='商品ごとの最大利益セッション1場。最大利益日ではない',
                    all32_profitable_separate=True),
                limits=['全32は既知で多重比較を含み、将来の安定利益を証明しない',
                        '配置予算単位の比較は実リスク等価を意味しない',
                        '前16/後16は劣化確認に限り、未来検証として扱わない',
                        '原資料の価格代理時計と到着時刻不明の限界を保持する'])
