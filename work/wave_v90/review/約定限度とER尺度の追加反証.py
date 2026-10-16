"""第1段の巨額損失を、限度価格の悲観約定と状態分類の尺度に分けて確かめる。"""

import importlib.util
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
SPEC = importlib.util.spec_from_file_location('独立診断90読取', HERE/'独立選定と原因診断.py')
REVIEW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REVIEW)


def distribution(values):
    """
    機能: 予測や採否へ戻さない説明用分布を集計する。
    引数: values(list | ndarray[float])。
    返り値: dict は件数、分位値と最大値。
    """
    values = np.asarray(values, np.float64)
    values = values[np.isfinite(values)]
    return dict(count=len(values), minimum=float(values.min()) if len(values) else None,
                q10=float(np.quantile(values, .1)) if len(values) else None,
                median=float(np.median(values)) if len(values) else None,
                q90=float(np.quantile(values, .9)) if len(values) else None,
                q99=float(np.quantile(values, .99)) if len(values) else None,
                maximum=float(values.max()) if len(values) else None)


def limit_cost(parents, record):
    """
    機能: 約定時の市場性指値が当時の気配より不利な価格を払った差額を取り出す。
    引数: parents(list[dict])、record(dict)。
    返り値: dict は指値差額、価格だけ改善した診断集計と大差額例。
    決済時刻・価格・数量は固定し、再バックテストや改善戦略の損益とは呼ばない。
    """
    value = 1000 if record['symbol'] == 'TOPIX' else 10
    selected = [parent for parent in parents if parent['source'] == 1]
    changed, examples = [], []
    charge = negative_charge = 0.
    gaps, crossing_stop, instant_stop = [], 0, 0
    for parent in selected:
        row, side = parent['entry_row'], parent['side']
        available = record['ask'][row] if side == 1 else record['bid'][row]
        distance = side * (parent['entry_price']-available)
        assert distance >= -1e-9
        distance = max(distance, 0.)
        money = distance * parent['quantity'] * value
        charge += money
        if parent['net'] < 0:
            negative_charge += money
        gaps.append(distance / record['tick'])
        improved = dict(parent, entry_price=float(available), gross=parent['gross']+money, net=parent['net']+money)
        changed.append(improved)
        if side * (record['price'][row]-parent['entry_price']) <= -8*record['tick']:
            crossing_stop += 1
        if parent['exit_decision_row'] == row+1 and parent['exit_reason'] == 6:
            instant_stop += 1
        examples.append(dict(parent_id=parent['parent_id'], source='O06', side=side,
            new_decision_time=REVIEW.stamp(parent['decision_time']), entry_time=REVIEW.stamp(parent['entry_time']),
            original_limit=parent['entry_price'], current_price=float(record['price'][row]),
            executable_quote=float(available), bid=float(record['bid'][row]), ask=float(record['ask'][row]),
            excess_ticks=distance/record['tick'], excess_money=money,
            actual_parent_net=parent['net'], price_only_counterfactual_net=parent['net']+money,
            exit_decision_time=REVIEW.stamp(parent['exit_decision_time']), exit_time=REVIEW.stamp(parent['exit_time']),
            exit_reason=parent['exit_reason']))
    actual = REVIEW.totals(selected)
    diagnostic = REVIEW.totals(changed)
    assert abs(diagnostic['net']-actual['net']-charge) < 1e-4
    return dict(actual=actual, total_limit_excess_money=charge,
        limit_excess_on_losing_parents=negative_charge,
        limit_excess_over_actual_loss=negative_charge/actual['loss'] if actual['loss'] else None,
        excess_ticks=distribution(gaps), already_beyond_stop_at_entry=crossing_stop,
        stopped_on_first_next_row=instant_stop, price_only_counterfactual=diagnostic,
        largest_examples=sorted(examples, key=lambda example: example['excess_money'], reverse=True)[:5])


def subsampled_er(record, market, grid):
    """
    機能: 同じ300秒窓の端点を保ち、内部を5秒格子中値だけに間引いたERを計算する。
    引数: record/market(dict)、grid(ndarray[float])。
    返り値: tuple[ndarray, ndarray] は元ERと間引きERの有効対。
    全格子で現在端点が有効な窓だけ比較し、欠測を補間しない。
    """
    current, window = market['current'], market['windows'][300]
    valid = current['valid'] & np.isfinite(current['mid'])
    invalid_prefix = np.r_[0, np.cumsum(~valid)]
    middle = (record['bid']+record['ask'])/2
    original, sampled = [], []
    for index in np.flatnonzero(window['source_valid'] & np.isfinite(window['efficiency'])):
        left = int(np.searchsorted(grid, grid[index]-300, side='left'))
        if grid[index]-grid[left] < 300-1e-8 or invalid_prefix[index+1]-invalid_prefix[left] != 0:
            continue
        old, now = int(window['old'][index]), int(window['now'][index])
        points = current['index'][left:index+1]
        points = points[(points >= old) & (points <= now)]
        values = np.r_[middle[old], middle[points], middle[now]]
        variation = np.abs(np.diff(values)).sum()
        if variation <= 0:
            continue
        assert variation <= window['total_variation'][index]+1e-8
        efficiency = abs(middle[now]-middle[old])/variation
        assert efficiency <= 1+1e-9
        original.append(window['efficiency'][index])
        sampled.append(efficiency)
    return np.asarray(original), np.asarray(sampled)


def main():
    """
    機能: 第1段の全27結果だけで約定モデルとER/J2交差を独立に診断する。
    引数: なし。
    返り値: None。第2段の条件損益は読まない。
    """
    fixed = REVIEW.read(WORK/'事前固定.json')
    for relative, expected in fixed['SHA256'].items():
        assert REVIEW.digest(ROOT/relative) == expected
    prices = REVIEW.read(ROOT/'work/wave_v83/prepared/inputs.pkl')
    grids = REVIEW.read(ROOT/'work/wave_v77/inputs/grids_delay1.pkl')
    entries = REVIEW.read(ROOT/'work/wave_v77/prepared/signals_delay1.pkl')
    legacy = REVIEW.read(ROOT/'work/wave_v77/prepared/legacy_delay1.pkl')
    costs, all_parents = {}, {}
    for config in fixed['条件']:
        ident = config['id']
        records = REVIEW.read(WORK/'ledgers'/f'{ident}.pkl')
        account_costs = {}
        accounts = {key: REVIEW.parents_from_orders(key, ledger) for key, ledger in records.items()}
        all_parents[ident] = accounts
        for key, parents in accounts.items():
            account_costs[key] = limit_cost(parents, prices[key])
        costs[ident] = {}
        for symbol in REVIEW.SYMBOLS:
            selected = [item for key, item in account_costs.items() if key[1] == symbol]
            fields = ('total_limit_excess_money', 'limit_excess_on_losing_parents',
                      'already_beyond_stop_at_entry', 'stopped_on_first_next_row')
            summary = {field: sum(item[field] for item in selected) for field in fields}
            parents = [parent for key, rows in accounts.items() if key[1] == symbol for parent in rows if parent['source'] == 1]
            summary['actual'] = REVIEW.totals(parents)
            summary['price_only_counterfactual_net'] = summary['actual']['net']+summary['total_limit_excess_money']
            summary['limit_excess_over_actual_loss'] = summary['limit_excess_on_losing_parents']/summary['actual']['loss'] \
                if summary['actual']['loss'] else None
            summary['largest_examples'] = sorted(
                [dict(example, session=key[0]) for key, item in account_costs.items() if key[1] == symbol
                 for example in item['largest_examples']], key=lambda example: example['excess_money'], reverse=True)[:5]
            costs[ident][symbol] = summary

    # ----------------------------------------
    by_market = {symbol: [] for symbol in REVIEW.SYMBOLS}
    joint = []
    joint_common = []
    high_grid = {symbol: 0 for symbol in REVIEW.SYMBOLS}
    paired_sampled = {symbol: [[], []] for symbol in REVIEW.SYMBOLS}
    candidate_er = {symbol: [] for symbol in REVIEW.SYMBOLS}
    candidate_joint = {symbol: [] for symbol in REVIEW.SYMBOLS}
    candidate_counts = {symbol: dict(all_legacy=0, J2_allowed=0, both_ER_finite=0, both_high_04=0,
                                   both_high_and_common_04=0) for symbol in REVIEW.SYMBOLS}
    for session in fixed['全30']:
        source, entry = grids[session], entries[session]
        grid = source['grid']
        markets = source['markets']
        finite = []
        for symbol in REVIEW.SYMBOLS:
            window = markets[symbol]['windows'][300]
            good = window['source_valid'] & np.isfinite(window['efficiency'])
            finite.append(good)
            values = window['efficiency'][good]
            by_market[symbol].extend(values)
            high_grid[symbol] += int(np.sum(values >= .4))
            old_er, sampled_er = subsampled_er(prices[(session, symbol)], markets[symbol], grid)
            paired_sampled[symbol][0].extend(old_er)
            paired_sampled[symbol][1].extend(sampled_er)
        good_both = finite[0] & finite[1]
        weakest = np.minimum(markets['TOPIX']['windows'][300]['efficiency'], markets['NK225']['windows'][300]['efficiency'])
        joint.extend(weakest[good_both])
        common = entry['common']
        allowed_common = np.zeros(len(grid), bool)
        for side in (-1, 1):
            allowed_common |= (common == side) & entry['entries']['J2']['long_allowed' if side==1 else 'short_allowed']
        joint_common.extend(weakest[good_both & allowed_common])
        for symbol in REVIEW.SYMBOLS:
            record = prices[(session, symbol)]
            sparse = np.full(len(record['time_s']), -1, np.int32)
            for index, row in enumerate(np.searchsorted(record['time_s'], grid, side='left')):
                if row < len(sparse) and record['time_s'][row]-grid[index] <= 10:
                    sparse[row] = index
            for candidate in legacy[(session, symbol)]['candidates']:
                candidate_counts[symbol]['all_legacy'] += 1
                row, side = int(candidate[1]), int(candidate[2])
                index = int(sparse[row])
                if index < 0 or not entry['entries']['J2']['long_allowed' if side==1 else 'short_allowed'][index]:
                    continue
                candidate_counts[symbol]['J2_allowed'] += 1
                for market_name in REVIEW.SYMBOLS:
                    value = markets[market_name]['windows'][300]['efficiency'][index]
                    candidate_er[symbol].append(dict(market=market_name, ER=float(value)))
                if good_both[index]:
                    candidate_counts[symbol]['both_ER_finite'] += 1
                    candidate_joint[symbol].append(weakest[index])
                    if weakest[index] >= .4:
                        candidate_counts[symbol]['both_high_04'] += 1
                        if allowed_common[index]:
                            candidate_counts[symbol]['both_high_and_common_04'] += 1

    def threshold_counts(values):
        """
        機能: ERの観測尺度に対する既定境界の到達件数を示す。
        引数: values(list[float])。
        返り値: dict[str,int] は損益を使わない境界件数。
        """
        values = np.asarray(values, np.float64)
        return {str(boundary): int(np.sum(values >= boundary)) for boundary in (.1, .2, .3, .4, .5)}
    er = dict(市場別全有限分布={symbol: distribution(values) for symbol, values in by_market.items()},
              市場別ER04以上格子=high_grid, 双方弱いER分布=distribution(joint),
              双方弱いER境界件数=threshold_counts(joint),
              共同方向かつJ2許可時の弱いER分布=distribution(joint_common),
              共同方向かつJ2許可のER境界件数=threshold_counts(joint_common),
              J2候補条件交差=candidate_counts,
              J2候補の双方弱いER分布={symbol: distribution(values) for symbol, values in candidate_joint.items()},
              J2候補の市場別ER分布={symbol: {market: distribution([item['ER'] for item in values if item['market']==market])
                                      for market in REVIEW.SYMBOLS} for symbol, values in candidate_er.items()},
              同端点5秒間引き比較={symbol: dict(元全観測=distribution(pair[0]), 格子内点だけ=distribution(pair[1]),
                    ER04以上_元=int(np.sum(np.asarray(pair[0]) >= .4)),
                    ER04以上_間引き=int(np.sum(np.asarray(pair[1]) >= .4)),
                    説明='同じ窓端点を保ち、内部の往復を5秒格子へ間引く。現在端点が全格子で有効な窓のみ。ER上昇は除去された内部往復の尺度差であり、将来予測力の改善ではない。')
                                   for symbol, pair in paired_sampled.items()})
    proof = dict(全合格=True, 第一段のみ=True, 限度価格と当時気配の差額=costs,
        ER尺度と共同条件交差=er,
        結論=[
            'ER0.4を超える格子自体は存在する。J_HIGH無取引は、両市場同時・共同方向・持続・J2入口の条件交差が成立しなかった結果であり、単に全ERが低いからとは言わない。',
            'ゲート待ちで古いanchorから価格が離れた後、当時のask/bidより大幅に不利な元limitで約定させる模型は、実際の限度注文の通常の価格改善を捨てる悲観模型である。巨額損失をそのまま状態選択の否定に使わない。',
            '当時気配と元limitとの差を加え戻す計算は、出口時刻と価格を固定した会計反実仮想に限る。新しい取得価格からの損切り・利確経路が変わるので改善戦略の成績ではない。',
            '全観測ERと5秒間引きERは内部往復の分母が違う。閾値0.4の意味を別の足幅や旧15分研究からそのまま移植できない。',
            '低ERは既往の相殺形状であり、直近の発進や受動注文の逆選択を除いていない。約定模型修正後も別途検証が必要。'],
        第二段新条件損益閲覧=0, 現在API取得=0, 実注文=0, 凍結成果変更=0,
        SHA256={str(path.relative_to(ROOT)): REVIEW.digest(path) for path in
                 [Path(__file__), HERE/'独立選定と原因診断.py', WORK/'事前固定.json']})
    target = HERE/'巨額損失の限度価格模型とER尺度及び条件交差の独立反証.json'
    target.write_text(json.dumps(REVIEW.clean(proof), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(dict(主D_C限度差額=costs['D_C'], ER04格子=high_grid, J2交差=candidate_counts), ensure_ascii=False))


if __name__ == '__main__':
    main()
