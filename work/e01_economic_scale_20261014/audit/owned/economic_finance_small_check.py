"""完成小結果だけから924会計と実親net・全場平均及び新目標を独立検算する。"""

import hashlib
import json
import math
from collections import Counter
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
import statistics
import traceback

OWN = Path(__file__).resolve().parent
ROOT = OWN.parents[3]
ENGINE = ROOT / 'work/e01_economic_scale_20261014/engine'
CAP = {'TOPIX': 10, 'NK225': 20}
MULT = {'TOPIX': 1000, 'NK225': 10}
TICK = {'TOPIX': .5, 'NK225': 10}
FEES = {'TOPIX': Decimal('41.8'), 'NK225': Decimal('11')}
READS = {}
COUNTS = Counter()


def read(path: Path) -> dict:
    """
    機能: 完成小結果と固定metadataだけを同bytes一目的一読で扱う。
    引数: path(Path) は根が完成後に許可したJSON位置。
    返り値: dict はJSON辞書。入力/台帳本文の自動探索をしない。
    """
    key = path.relative_to(ROOT).as_posix()
    assert key not in READS, key
    raw = path.read_bytes(); READS[key] = hashlib.sha256(raw).hexdigest()
    return json.loads(raw.decode('utf-8-sig'))


def same(actual: object, expected: object, label: str) -> None:
    """
    機能: 未定義を保持し、有限金額と個数の独立期待値を照合する。
    引数: actual/expected(object)、label(str) は保存値/期待値と論点。
    返り値: None。不一致は保存Falseとして停止する。
    """
    if expected is None or isinstance(expected, (bool, str, list, dict)):
        assert actual == expected, (label, actual, expected)
    else:
        assert isinstance(actual, (int, float)) and math.isfinite(actual)
        assert math.isclose(actual, expected, rel_tol=1e-11, abs_tol=1e-4), (label, actual, expected)
    COUNTS['小算術照合'] += 1


def fee(quantity: int, symbol: str) -> int:
    """
    機能: 実注文ごとの料金を独立Decimalで円未満切捨てする。
    引数: quantity(int)、symbol(str) は約定数量と商品。
    返り値: int は片道料。別注文同士を合算しない。
    """
    return int((Decimal(quantity) * FEES[symbol]).to_integral_value(rounding=ROUND_FLOOR))


def metric(values: list[float]) -> dict:
    """
    機能: 完結親又は実玉netを正負別に独立集計する。
    引数: values(list[float]) は同定義の保存損益。
    返り値: dict は主金額/個数/平均勝敗。未定義を0で救済しない。
    """
    wins = [v for v in values if v > 0]; losses = [-v for v in values if v < 0]
    gain, loss = sum(wins), sum(losses)
    return {'利益': gain, '損失': loss, '収支': sum(values), '親数': len(values),
            '勝ち親': len(wins), '負け親': len(losses), '零親': len(values) - len(wins) - len(losses),
            'PF': gain / loss if loss else None, '利益割合': gain / (gain + loss) if gain + loss else None,
            '平均利益': gain / len(wins) if wins else None, '平均損失': loss / len(losses) if losses else None,
            '平均損益比': gain / len(wins) / (loss / len(losses)) if wins and losses else None}


def compare_mapping(saved: dict, expected: dict, label: str) -> None:
    """
    機能: 同じ定義の辞書を項目ごとに独立値へ照合する。
    引数: saved/expected(dict)、label(str) は保存辞書/独立辞書と範囲。
    返り値: None。追加保存項目を架空の期待値で埋めない。
    """
    for key, value in expected.items():
        same(saved[key], value, label + '/' + key)


def aggregate(rows: list[dict], parents: list[dict]) -> dict:
    """
    機能: 各場netと全実親正負から全範囲の集計を独立に求める。
    引数: rows/parents(list[dict]) は同商品同期間の小会計。
    返り値: dict は活動/黒赤/枚数/料金と上位正net三場除外。
    """
    active = [r for r in rows if r['親数']]
    positive = sorted([r['収支'] for r in rows if r['収支'] > 0], reverse=True)
    out = metric([p['net_yen'] for p in parents])
    out.update(全場=len(rows), 活動場=len(active), 黒字場=len(positive), 赤字場=sum(r['収支'] < 0 for r in rows),
               無取引場=len(rows) - len(active), 中央値=statistics.median(r['収支'] for r in rows),
               活動場中央値=statistics.median(r['収支'] for r in active) if active else None,
               上位3利益場除外収支=sum(r['収支'] for r in rows) - sum(positive[:3]),
               最大場損失=max([0] + [-r['収支'] for r in rows]), 全33黒字=len(positive) == len(rows))
    for key in ('費用', '新規枚数', '勝ち枚数', '負け枚数', '零枚数'):
        out[key] = sum(r[key] for r in rows)
    return out


def economy(rows: list[dict], parents: list[dict], symbol: str) -> dict:
    """
    機能: 全場分母の純平均と参考親平均を別に集計する。
    引数: rows/parents(list[dict])、symbol(str) は同商品範囲の完成会計。
    返り値: dict は平均/容量換算。NK円床は未指定のまま保持する。
    """
    net = sum(r['収支'] for r in rows); quantity = sum(p['entry_quantity'] for p in parents)
    meanq = quantity / len(parents) if parents else None
    average = net / len(rows) if rows else None
    return dict(session_count=len(rows), mean_session_net_yen=average, parent_count=len(parents),
                mean_parent_net_yen=net / len(parents) if parents else None, mean_initial_quantity=meanq,
                maximum_same_direction_quantity=max([0] + [max(r['最大買枚数'], r['最大売枚数']) for r in rows]),
                mean_initial_capacity_ratio=meanq / CAP[symbol] if meanq is not None else None,
                net_capacity_points=net / (CAP[symbol] * MULT[symbol]),
                target_floor_yen=100000 if symbol == 'TOPIX' else None, target_floor_specified=symbol == 'TOPIX',
                target_mean_success=average is not None and average >= 100000 if symbol == 'TOPIX' else None)


def stability(rows: list[dict], e: dict) -> dict:
    """
    機能: 全場33赤字率・親金額割合・平均黒字場補填力と円床を独立判定する。
    引数: rows(list[dict])、e(dict) は同じ範囲の場会計と経済尺度。
    返り値: dict は主三基準とTOPのみの平均円床。
    """
    positive = [r['収支'] for r in rows if r['収支'] > 0]; negative = [-r['収支'] for r in rows if r['収支'] < 0]
    active = sum(r['親数'] > 0 for r in rows); gain = sum(r['利益'] for r in rows); loss = sum(r['損失'] for r in rows)
    share = gain / (gain + loss) if gain + loss else None
    mean = sum(positive) / len(positive) if positive else None; worst = max([0] + negative)
    red = len(negative) / len(rows); a = share is not None and share >= .65; b = red <= .2; c = mean is not None and worst <= mean
    classic = a and b and c
    return dict(session_count=len(rows), active_sessions=active, positive_sessions=len(positive), losing_sessions=len(negative),
                no_trade_sessions=len(rows) - active, flat_active_sessions=active - len(positive) - len(negative),
                red_full_rate=red, red_active_rate=len(negative) / active if active else None, profit_share=share,
                mean_positive_session_net_yen=mean, worst_negative_session_abs_yen=worst,
                target65=a, target_red20=b, target_worst_mean=c, all_targets=classic,
                target_mean_session_net=e['target_mean_success'],
                all_economic_targets=classic and (e['target_mean_success'] if e['target_floor_specified'] else True),
                monetary_floor_applies=e['target_floor_specified'])


def parent_checks(p: dict, config: dict, origins: dict, scene: float | None) -> list[dict]:
    """
    機能: 新規/全返済の実BBO・料・局所net・初fill名目と線を独立に計算する。
    引数: p/config(dict)、origins(dict)、scene(float|None) は小射影と同場起点。
    返り値: list[dict] は独立実玉net。中間normal気配を再取得しない。
    """
    symbol = p['symbol']; side = p['side']; entry = p['entry']; qty = p['entry_quantity']; exits = p['exits']
    assert side in (-1, 1) and isinstance(qty, int) and 0 < qty <= CAP[symbol]
    same(entry['quantity'], qty, '実新規q'); same(entry['reason'], 90, '実新規理由')
    same(entry['price'], entry['ask' if side > 0 else 'bid'], '実新規正BBO')
    same(entry['fee_yen'], fee(qty, symbol), '実新規floor料')
    assert entry['source_row'] < entry['row'] and entry['source_raw_seq'] <= entry['raw_seq']
    assert entry['source_normal'] and 0 < entry['source_bid'] < entry['source_ask'] and 0 < entry['bid'] < entry['ask']
    same(entry['source_raw_seq'], p['publication_raw_seq'], '公開seq')
    same(entry['source_price_time_s'], p['publication_price_time_s'], '公開価格代理時計')
    cap = p['published_price_cap']; allowance = p['published_adverse_ticks']
    same(cap, entry['source_ask'] + allowance * TICK[symbol] if side > 0 else entry['source_bid'] - allowance * TICK[symbol], '公開固定価格cap')
    assert entry['price'] <= cap if side > 0 else entry['price'] >= cap
    gate, strong = config['entry_parameters'][symbol]
    assert p['published_direction_votes'] >= 2 and p['published_balance'] >= (0.25 if gate == 'G25' else 0.5)
    same(allowance, int(p['published_balance'] >= strong), '公開支持だけで0/1T固定')
    same(p['capacity'], CAP[symbol], '商品容量'); same(p['capacity_initial_ratio'], qty / CAP[symbol], '初回容量使用率')
    same(p['maximum_held_quantity'], qty, '実一新規親の最大同時q')
    if config['quantity_mode'] != 'RISK': same(qty, config['quantity'][symbol], '固定実q')
    N = entry['price'] * qty * MULT[symbol]
    same(p['notional_yen'], N, '初実fill名目N'); same(p['parent_stop_yen'], N * config['parent_stop_fraction'], '親損失線')
    same(p['target_yen'], N * config['parent_target_fraction'], '目標線又は参考線')
    same(p['target_active'], config['exit_id'] == 'TARGET', '目標有効種別')
    same(p['trail_active'], config['exit_id'] in ('TRAIL', 'PARTIAL'), '追尾有効種別')
    same(p['reference_only_target_for_other_exits'], config['exit_id'] != 'TARGET', '参考目標を実目標へ混ぜない')
    origin = origins[p['parent']]
    for index, value in ((0, p['parent']), (1, entry['row']), (2, entry['source_row']), (3, side), (4, qty),
                         (5, entry['price']), (6, N), (8, p['published_atr']), (9, cap), (10, allowance)):
        same(origin[index], value, '実起点列' + str(index))
    assert int(origin[11]) == origin[11] and origin[11] >= 0
    remaining = qty; gross = 0.; charges = fee(qty, symbol); legs = []; partial_count = 0
    for ex in exits:
        amount = ex['quantity']; assert isinstance(amount, int) and 0 < amount <= remaining
        assert entry['row'] <= ex['source_row'] < ex['row'] and ex['source_raw_seq'] <= ex['raw_seq']
        assert 0 < ex['bid'] < ex['ask']; same(ex['price'], ex['bid' if side > 0 else 'ask'], '実返済正BBO')
        cost = fee(amount, symbol); same(ex['fee_yen'], cost, '実返済注文別floor料')
        g = side * amount * (ex['price'] - entry['price']) * MULT[symbol]
        legs.append(dict(net=g - fee(qty, symbol) * amount / qty - cost, quantity=amount, side=side))
        gross += g; charges += cost; remaining -= amount
        assert ex['reason'] in (91, 92, 93, 140, 141, 142, 143, 144)
        if ex['reason'] == 144:
            partial_count += 1; same(amount, math.floor(qty * config['partial_fraction']), '一度だけ初q1/4floor部分')
            assert config['exit_id'] == 'PARTIAL' and ex['source_parent_liquidation_yen'] >= N * config['partial_arm_fraction']
        if ex['reason'] == 140:
            assert config['exit_id'] == 'TARGET'; same(ex['source_target_yen'], N * config['parent_target_fraction'], '目標判断線')
            assert ex['source_parent_liquidation_yen'] >= ex['source_target_yen']
        if ex['reason'] == 141:
            assert ex['source_parent_liquidation_yen'] <= -p['parent_stop_yen']
        if ex['reason'] == 142:
            assert config['exit_id'] in ('TRAIL', 'PARTIAL') and ex['source_parent_peak_yen'] >= N * config['arm_fraction']
            same(ex['source_trail_line_yen'], max(N * config['floor_fraction'], ex['source_parent_peak_yen'] - N * config['draw_fraction']), '追尾線')
            assert ex['source_parent_liquidation_yen'] <= ex['source_trail_line_yen']
        if ex['reason'] == 143: same(ex['source_scene_stop_yen'], scene, '場損失停止線')
        if ex['reason'] == 91: assert config['exit_id'] == 'GU'
        COUNTS['返済小BBO料'] += 1
    assert remaining == 0 and partial_count <= 1
    same(p['net_yen'], gross - charges, '完結親gross-minus-fee')
    same(p['fees_yen'], charges, '親料金合計')
    same(p['parent_mae_yen'], max(0., -p['worst_parent_liquidation_yen']), '事後親MAE')
    same(p['parent_mfe_yen'], p['best_parent_liquidation_yen'], '事後親MFE')
    assert p['worst_parent_liquidation_yen'] <= p['net_yen'] + 1e-4 <= p['best_parent_liquidation_yen'] + 2e-4
    same(p['holding_price_proxy_seconds'], exits[-1]['price_time_s'] - entry['price_time_s'], '保有価格代理秒')
    for kind, value in (('argmin', p['worst_parent_liquidation_yen']), ('argmax', p['best_parent_liquidation_yen'])):
        point = p['first_parent_liquidation_' + kind]
        assert entry['row'] <= point['row'] <= exits[-1]['row'] and point['hindsight_only']
        assert 0 < point['bid'] < point['ask'] and 0 <= point['holding_quantity'] <= qty
        same(point['parent_liquidation_yen'], value, '事後極値保存対応:' + kind)
    same(p['actual_completed_before_paper_exit'], bool(p['paper_exit_rows'] and exits[-1]['row'] < p['paper_exit_rows'][-1]), 'paper未完結でも実完結親を含む')
    assert p['hindsight_only']; COUNTS['実親小会計'] += 1
    return legs


def main() -> None:
    """
    機能: 根terminal0後だけ、小結果から924場会計・全親・112期間を独立検算する。
    引数: なし。根授権済み結果/計画/固定/独立正式接続JSONだけを読む。
    返り値: None。金融再生・入力/台帳/原板/API取得をしない。
    """
    target = OWN / '十四容量924会計と全実親及び全場十万円床の独立小監査_v2.json'
    assert not target.exists()
    try:
        result = read(ENGINE / 'finance/結果.json'); plan = read(ENGINE / '試行計画.json'); fixed = read(ENGINE / '金融事前固定.json')
        connection = read(OWN / '十四最終17源と八部品及び全場平均の独立接続_正式.json')
        assert result['全合格'] and connection['全合格'] and result['source開始終端一致']
        same(result['source_SHA256'], fixed['source_SHA256'], '金融source固定'); same(result['source_SHA256'], connection['source_SHA256'], '独立正式接続source')
        same(result['case_SHA256'], fixed['case_SHA256'], 'case14指紋'); same(result['configs'], fixed['configs'], '14条件固定')
        same(result['configs'], plan['spec']['entry']['conditions'], '八部品条件同値')
        same(result['sessions'], fixed['sessions'], '33場同一'); same(result['counts'], {'既input一読': 33, '新account金融': 924}, '正式一読実数')
        for key in ('旧GU再利用', '旧台帳本文', '原板', 'NPZ', 'API', '現在入力'): same(result[key], 0, key)
        same(result['新account金融'], 924, '14×2×33')
        same(READS[(ENGINE / '試行計画.json').relative_to(ROOT).as_posix()], fixed['計画SHA256'], '現計画bytesSHA')
        assert len(result['configs']) == len(result['results']) == len(result['actual_parent_diagnostics']) == len(result['boundary']) == 14
        sessions = result['sessions']; evaluation = {}; all_ledgers = set(); selected_candidates = {s: {} for s in CAP}
        for config in result['configs']:
            cid = config['id']; saved = result['results'][cid]; parents = result['actual_parent_diagnostics'][cid]; bounds = result['boundary'][cid]
            assert len(saved['rows']) == len(saved['ledgers']) == len(bounds) == 66
            assert {(r['session'], r['symbol']) for r in saved['rows']} == {(s, product) for s in sessions for product in CAP}
            same(len({(p['session'], p['symbol'], p['parent']) for p in parents}), len(parents), '実親重複無し')
            rows_map = {(r['session'], r['symbol']): r for r in saved['rows']}
            legs_all = []; evaluations_by_symbol = {}
            for b in bounds:
                key = (b['session'], b['symbol']); symbol = b['symbol']; own = [p for p in parents if (p['session'], p['symbol']) == key]
                origins = {int(o[0]): o for o in b['actual_origins']}
                same(len(origins), len(own), '初実fill起点数は完結実親数')
                running = 0.; previous_end = -1; legs = []
                for p in sorted(own, key=lambda p: p['entry']['row']):
                    assert p['entry']['row'] >= previous_end
                    same(origins[p['parent']][7], running, '親局所起点から前親netを排除')
                    current_legs = parent_checks(p, config, origins, b['scene_loss_stop_yen'])
                    for l in current_legs: l.update(session=key[0], symbol=symbol)
                    legs.extend(current_legs); legs_all.extend(current_legs)
                    running += p['net_yen']; previous_end = p['exits'][-1]['row']
                row = rows_map[key]; compare_mapping(row, metric([p['net_yen'] for p in own]), '場完結親net')
                compare_mapping(row, {'費用': sum(p['fees_yen'] for p in own), '新規枚数': sum(p['entry_quantity'] for p in own),
                    '勝ち枚数': sum(l['quantity'] for l in legs if l['net'] > 0), '負け枚数': sum(l['quantity'] for l in legs if l['net'] < 0),
                    '零枚数': sum(l['quantity'] for l in legs if l['net'] == 0), '注文件数': sum(1 + len(p['exits']) for p in own),
                    '最大買枚数': max([0] + [p['entry_quantity'] for p in own if p['side'] > 0]),
                    '最大売枚数': max([0] + [p['entry_quantity'] for p in own if p['side'] < 0])}, '場実枚数/注文/料')
                assert row['全会計合格']; COUNTS['場会計'] += 1
                for judgment in b['judgments']:
                    assert len(judgment) == 12 and judgment[3] in (140, 141, 142, 143, 144)
                    if judgment[2] == 4:
                        same(judgment[3], 143, '場停止観測の理由')
                        same(judgment[7], b['scene_loss_stop_yen'], '場停止観測kind4の場線')
                    elif judgment[2] == 1 and int(judgment[1]) in origins:
                        same(judgment[7], origins[int(judgment[1])][6] * config['parent_stop_fraction'], '残量返済予約kind1の親線')
                    elif judgment[2] == 2 and int(judgment[1]) in origins:
                        same(judgment[7], origins[int(judgment[1])][6] * config['partial_arm_fraction'], '部分予約kind2の親線')
                    if int(judgment[1]) in origins:
                        same(judgment[9], origins[int(judgment[1])][6], '途中判断N固定')
                    COUNTS['途中判断小保存'] += 1
            for symbol in CAP:
                ownrows = [r for r in saved['rows'] if r['symbol'] == symbol]; pp = [p for p in parents if p['symbol'] == symbol]
                excluded = [r['session'] for r in sorted((r for r in ownrows if r['収支'] > 0), key=lambda r: (-r['収支'], r['session']))[:3]]
                scopes = {'全33': sessions, '前16': sessions[:16], '後17': sessions[16:],
                          '上位3正収支場除外': [s for s in sessions if s not in excluded]}
                same(saved['periods'][symbol]['除外場'], excluded, '上位3正net固定除外')
                scope_evaluation = {}
                for label, scope in scopes.items():
                    rr = [r for r in ownrows if r['session'] in scope]; pr = [p for p in pp if p['session'] in scope]
                    old = saved['periods'][symbol][label]; agg = aggregate(rr, pr); e = economy(rr, pr, symbol); st = stability(rr, e)
                    compare_mapping(old['aggregate'], agg, label + '/集計'); compare_mapping(old['economic'], e, label + '/経済')
                    compare_mapping(old['stability'], st, label + '/主三円床'); same(old['sessions'], scope, label + '/場範囲')
                    bysession = {r['session']: r for r in old['economic']['by_session']}; same(len(bysession), len(scope), '個別経済場数')
                    for r in rr:
                        group = [p for p in pr if p['session'] == r['session']]; v = bysession[r['session']]
                        compare_mapping(v, dict(net_yen=r['収支'], parent_count=len(group), mean_parent_net_yen=r['収支'] / len(group) if group else None,
                            mean_initial_quantity=sum(p['entry_quantity'] for p in group) / len(group) if group else None,
                            maximum_same_direction_quantity=max(r['最大買枚数'], r['最大売枚数']), net_capacity_points=r['収支'] / (CAP[symbol] * MULT[symbol]),
                            worst_parent_liquidation_yen=min([0] + [p['worst_parent_liquidation_yen'] for p in group]) if group else None), '各場容量経済')
                    scope_evaluation[label] = dict(**e, **{k: st[k] for k in ('active_sessions', 'positive_sessions', 'losing_sessions', 'no_trade_sessions',
                        'profit_share', 'red_full_rate', 'mean_positive_session_net_yen', 'worst_negative_session_abs_yen', 'all_targets', 'all_economic_targets')},
                        net_yen=agg['収支'], max_parent_mae_yen=max((p['parent_mae_yen'] for p in pr), default=None))
                    COUNTS['商品期間'] += 1
                compare_mapping(saved['symbols'][symbol], aggregate(ownrows, pp), '商品全33symbols')
                compare_mapping(saved['economic'][symbol], economy(ownrows, pp, symbol), '商品全33economic')
                compare_mapping(saved['stability'][symbol], stability(ownrows, economy(ownrows, pp, symbol)), '商品全33stability')
                compare_mapping(saved['actual_leg_symbols'][symbol], metric([l['net'] for l in legs_all if l['symbol'] == symbol]), '実玉副表')
                for direction, side in (('long', 1), ('short', -1)):
                    ps = [p for p in pp if p['side'] == side]; expected = metric([p['net_yen'] for p in ps])
                    expected.update(勝ち枚数=sum(p['entry_quantity'] for p in ps if p['net_yen'] > 0),
                                    負け枚数=sum(p['entry_quantity'] for p in ps if p['net_yen'] < 0), 枚数=sum(p['entry_quantity'] for p in ps))
                    compare_mapping(saved['directional_symbols'][symbol][direction], expected, '実親方向別')
                evaluations_by_symbol[symbol] = scope_evaluation
                full = scope_evaluation['全33']; trim = scope_evaluation['上位3正収支場除外']
                dayactive = sum(r['親数'] > 0 and r['session'].endswith('_Day') for r in ownrows)
                tests = [saved['stability'][symbol][k] for k in ('target65', 'target_red20', 'target_worst_mean')]
                rank = (full['all_economic_targets'], bool(trim['profit_share'] is not None and trim['profit_share'] >= .65 and
                        trim['mean_positive_session_net_yen'] is not None and trim['worst_negative_session_abs_yen'] <= trim['mean_positive_session_net_yen']),
                        full['all_targets'], sum(tests), full['active_sessions'], dayactive, -full['worst_negative_session_abs_yen'])
                selected_candidates[symbol][cid] = dict(rank=rank, max_mae=full['max_parent_mae_yen'])
            evaluation[cid] = evaluations_by_symbol
            for item in saved['ledgers']:
                path = item['path']; assert path not in all_ledgers and path.startswith('work/e01_economic_scale_20261014/engine/finance/ledgers/' + cid + '/')
                assert len(item['SHA256']) == 64 and set(item['SHA256']) <= set('0123456789abcdef')
                all_ledgers.add(path); COUNTS['台帳参照形式'] += 1
        assert COUNTS['場会計'] == COUNTS['台帳参照形式'] == 924 and COUNTS['商品期間'] == 112
        same(result['reused_results'], fixed['reused_results'], '旧小引用固定同値')
        assert len(result['reused_results']) == 2
        selection = {}
        for symbol, cases in selected_candidates.items():
            highest = max(v['rank'] for v in cases.values()); tied = [cid for cid, v in cases.items() if v['rank'] == highest]
            complete = all(cases[cid]['max_mae'] is not None and math.isfinite(cases[cid]['max_mae']) for cid in tied)
            if complete:
                lowest = min(cases[cid]['max_mae'] for cid in tied); tied = [cid for cid in tied if cases[cid]['max_mae'] == lowest]
            selection[symbol] = dict(id=sorted(tied)[0], rank=list(highest), risk_tie_complete=complete)
        both = [cid for cid, by in evaluation.items() if all(by[s]['全33']['all_economic_targets'] for s in CAP)]
        topmean = max(v['TOPIX']['全33']['mean_session_net_yen'] for v in evaluation.values())
        output = dict(全合格=True,読取小資料SHA256=READS,検査=dict(COUNTS),金融source_SHA256=result['source_SHA256'],
            条件評価=evaluation,新主条件両商品合格=both,TOP場平均最大円=topmean,金融前規則の独立選択=selection,
            scope='新14条件924会計/全実親小射影/112商品期間/924台帳参照。旧2は保存小引用同値だけ、選定外。',
            初版False='理由143はkind4場停止観測とkind1親残量返済予約の両方に現れる。7列を場線へ統一したchecker仮定だけを訂正し、初版Falseとsourceを同bytes保存。金融源/結果は不変更。',
            留保=['実台帳bytesと全normalの次気配最短性はこの小監査では再検査しない。',
                  '極値の保存値/原seq/BBOと事後用途は確認するが、全normalからのargmax/argmin再測定はしない。',
                  '現33場の既知内探索。平均十万円は各場十万円の保証ではない。',
                  '大枚数による現実の板深度・FAK部分約定・注文到着時刻は未検証。',
                  '個別金額床が未指定のNKを十万円達成へ補完しない。'],
            金融再実行=0,実入力=0,台帳本文=0,原板=0,NPZ=0,API=0)
    except BaseException:
        output = dict(全合格=False,読取小資料SHA256=READS,検査=dict(COUNTS),原因=traceback.format_exc(),
                      金融再実行=0,実入力=0,台帳本文=0,原板=0,NPZ=0,API=0)
        target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        raise
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True,SHA256=hashlib.sha256(target.read_bytes()).hexdigest(),検査=dict(COUNTS),
                         新主条件両商品合格=both,TOP場平均最大円=topmean,独立選択=selection), ensure_ascii=False))


if __name__ == '__main__':
    main()
