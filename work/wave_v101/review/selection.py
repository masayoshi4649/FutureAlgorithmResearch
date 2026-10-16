"""実新規注文と建玉群から前16の参考選定を独立検算する。正式段階の許可前は読まない。"""

import argparse
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import pickle
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
SYMBOLS = ('TOPIX', 'NK225')
EPSILON = 1e-5


def read(path: Path) -> object:
    """
    機能: 許可段階で指定された保存資料だけを読み取る。
    引数: path (Path) はJSON又はpickleの保存先。
    返り値: object は保存された内容。モジュール読込時には実行しない。
    """
    with path.open('rb') as stream:
        return pickle.load(stream) if path.suffix == '.pkl' else json.loads(stream.read().decode('utf-8'))


def digest(path: Path) -> str:
    """
    機能: 台帳と固定根拠の指紋を分割読込で求める。
    引数: path (Path) は実在ファイル。
    返り値: str はSHA256の16進表現。
    """
    answer = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            answer.update(block)
    return answer.hexdigest()


def close(actual: object, expected: object, name: str = '') -> None:
    """
    機能: 保存金融値と独立会計を照合する。判定又は順位の閾値へ公差は足さない。
    引数: actual/expected (object) は数値又はNone等、name (str) は診断名。
    返り値: None。一致しなければ例外で停止する。
    """
    if expected is None or actual is None:
        assert actual is expected, name
    elif isinstance(expected, (int, float)):
        assert math.isfinite(float(actual)) and math.isfinite(float(expected)), name
        assert math.isclose(float(actual), float(expected), rel_tol=1e-10, abs_tol=1e-7), name
    else:
        assert actual == expected, name


def guard(base: Path, fixed: dict, require_selected: bool = True) -> None:
    """
    機能: 全20前16保存と根select完了及び後15未作成を確認する。
    引数: base (Path)、fixed (dict)、require_selected (bool) は人工時にも段階を選べる。
    返り値: None。後15成果又は不完全前16を見つけた場合は金融内容を読む前に拒否する。
    """
    identifiers = {config['id'] for config in fixed['条件']}
    assert len(identifiers) == len(fixed['条件']) == 20
    assert len(fixed['前16']) == len(set(fixed['前16'])) == 16
    assert {p.stem for p in (base / 'front/results').glob('*.json')} == identifiers
    assert {p.stem for p in (base / 'front/ledgers').glob('*.pkl')} == identifiers
    assert not list((base / 'back').rglob('*.json')), '後15のJSON作成後は前16選定を認定しません'
    assert not list((base / 'back').rglob('*.pkl')), '後15の台帳作成後は前16選定を認定しません'
    if require_selected:
        assert (base / '前16参考代表.json').is_file(), '根selectの完了前です'


# ----------------------------------------


def fee(quantity: int, symbol: str) -> int:
    """
    機能: 注文ごとの立会手数料を十進有理数から切り捨てる。
    引数: quantity (int) は正の実約定枚数、symbol (str) はTOPIX又はNK225。
    返り値: int は当該注文の実料金。複数注文の料を単一注文へ置換しない。
    """
    assert symbol in SYMBOLS and quantity > 0
    unit = Fraction('41.8') if symbol == 'TOPIX' else Fraction(11)
    return math.floor(quantity * unit)


def totals(items: list[tuple[float, float, int, int]], cohort: bool = False) -> dict:
    """
    機能: 相殺前の親又は建玉群の費用後損益と枚数を集計する。
    引数: items (list[tuple[float,float,int,int]]) はgross、net、料、枚数。cohort (bool) は建玉群名を選ぶ。
    返り値: dict はG/L・費用・平均勝負額・金額割合と実決済枚数。
    """
    wins = [item for item in items if item[1] > EPSILON]
    losses = [item for item in items if item[1] < -EPSILON]
    flat = [item for item in items if abs(item[1]) <= EPSILON]
    profit = sum(item[1] for item in wins)
    loss = -sum(item[1] for item in losses)
    noun = 'cohorts' if cohort else 'campaigns'
    average_win = profit / len(wins) if wins else None
    average_loss = loss / len(losses) if losses else None
    return dict(profit=profit, loss=loss, net=profit - loss,
                gross=sum(item[0] for item in items), fees=sum(item[2] for item in items),
                **{noun: len(items), 'winning_' + noun: len(wins), 'losing_' + noun: len(losses),
                   'flat_' + noun: len(flat)},
                winning_lots=sum(item[3] for item in wins), losing_lots=sum(item[3] for item in losses),
                flat_lots=sum(item[3] for item in flat), lots=sum(item[3] for item in items),
                profit_share=profit / (profit + loss) if profit + loss > 0 else None,
                average_win=average_win, average_loss=average_loss,
                payoff=average_win / average_loss if average_win is not None and average_loss is not None
                and average_loss > 0 else None)


def account(stored: dict, symbol: str) -> dict:
    """
    機能: 実新規注文と一括返済から親及び建玉群の会計を独立再構成する。
    引数: stored (dict) は一口座の保存台帳、symbol (str) は商品。
    返り値: dict は親と建玉群の相殺前会計。台帳netや根accountingを正答へ流用しない。
    """
    orders, trades = stored['orders'], stored['trades']
    cohorts, columns = stored['growth_cohorts'], stored['growth_cohort_columns']
    assert orders.ndim == trades.ndim == cohorts.ndim == 2
    assert orders.shape[1] == 17 and trades.shape[1] == 16 and cohorts.shape[1] == len(columns) == 25
    positions = {name: i for i, name in enumerate(columns)}
    multiplier = 1000. if symbol == 'TOPIX' else 10.
    assert len({int(parent[0]) for parent in trades}) == len(trades)
    assert {int(order[2]) for order in orders} == {int(parent[0]) for parent in trades}
    assert {int(row[positions['parent_id']]) for row in cohorts} == {int(parent[0]) for parent in trades}
    assert len(orders) == len(trades) + len(cohorts)
    for order in orders:
        quantity = int(order[5])
        assert quantity == order[5] and quantity > 0 and order[4] in (-1, 1)
        assert order[7] in (0, 1)
        assert order[9] == fee(quantity, symbol), '実注文別の料金'
    parents, groups = [], []
    peak_by_side = {-1: 0, 1: 0}
    for parent in trades:
        ident, side = int(parent[0]), int(parent[4])
        entries = [order for order in orders if int(order[2]) == ident and order[7] == 1]
        exits = [order for order in orders if int(order[2]) == ident and order[7] == 0]
        selected = sorted((row for row in cohorts if int(row[positions['parent_id']]) == ident),
                          key=lambda row: int(row[positions['cohort_id']]))
        assert len(exits) == 1 and len(entries) == len(selected) > 0 and side in (-1, 1)
        assert len({int(row[positions['cohort_id']]) for row in selected}) == len(selected)
        exit_order = exits[0]
        quantity = sum(int(order[5]) for order in entries)
        assert quantity == exit_order[5] == parent[5]
        assert all(order[4] == side for order in entries) and exit_order[4] == -side
        cash = sum(float(order[5]) * float(order[6]) for order in entries)
        entry_fee = sum(int(order[9]) for order in entries)
        exit_fee = int(exit_order[9])
        gross = side * sum(int(order[5]) * (float(exit_order[6]) - float(order[6])) for order in entries) * multiplier
        net = gross - entry_fee - exit_fee
        close(parent[6], cash / quantity, '最終weighted建値')
        close(parent[7], float(exit_order[6]), '実一括返済値')
        close(parent[8], entry_fee, '累計実新規注文料')
        close(parent[9], exit_fee, '単一全量返済料')
        close(parent[10], gross, '親gross')
        close(parent[11], net, '親net')
        assert parent[2] == min(order[0] for order in entries) and parent[3] == exit_order[0]
        assert all(order[0] <= exit_order[0] for order in entries)
        # ----------------------------------------
        # 剰余は整数で判定する。同剰余の配分順は実建玉群IDであり損益ではない。
        allocation = [exit_fee * int(row[positions['quantity']]) // quantity for row in selected]
        remainder = exit_fee - sum(allocation)
        priority = sorted(range(len(selected)), key=lambda i: (
            -(exit_fee * int(selected[i][positions['quantity']]) % quantity),
            int(selected[i][positions['cohort_id']])))
        for i in priority[:remainder]:
            allocation[i] += 1
        parent_groups = []
        used = set()
        for index, row in enumerate(selected):
            matched = [order for order in entries if int(order[16]) == int(row[positions['order_uid']])]
            assert len(matched) == 1
            order = matched[0]
            assert int(order[16]) not in used
            used.add(int(order[16]))
            amount = int(order[5])
            assert amount == row[positions['quantity']] and row[positions['side']] == side
            assert row[positions['entry_row']] == order[0]
            assert row[positions['entry_price']] == order[6]
            assert row[positions['entry_fee']] == order[9]
            assert row[positions['exit_row']] == exit_order[0]
            assert row[positions['exit_price']] == exit_order[6]
            assert row[positions['exit_fee_share']] == allocation[index]
            assert row[positions['parent_final_quantity']] == quantity
            group_gross = side * amount * (float(exit_order[6]) - float(order[6])) * multiplier
            group_net = group_gross - int(order[9]) - allocation[index]
            close(row[positions['gross']], group_gross, '建玉群gross')
            close(row[positions['net']], group_net, '建玉群net')
            parent_groups.append((group_gross, group_net, int(order[9]) + allocation[index], amount))
        close(sum(item[0] for item in parent_groups), gross, '親と建玉群gross合計')
        close(sum(item[1] for item in parent_groups), net, '親と建玉群net合計')
        assert sum(item[2] for item in parent_groups) == entry_fee + exit_fee
        groups.extend(parent_groups)
        parents.append((gross, net, entry_fee + exit_fee, quantity))
        peak_by_side[side] = max(peak_by_side[side], quantity)
    answer = totals(parents)
    answer['cohorts'] = totals(groups, cohort=True)
    answer['actual_peak_quantity'] = max(peak_by_side.values())
    answer['order_count'] = len(orders)
    answer['entry_order_count'] = len(cohorts)
    answer['adding_order_count'] = len(cohorts) - len(trades)
    close(answer['cohorts']['net'], answer['net'], '全親/建玉群net')
    assert answer['cohorts']['fees'] == answer['fees'] == sum(int(order[9]) for order in orders)
    assert answer['cohorts']['lots'] == answer['lots']
    return answer


# ----------------------------------------


def combine(rows: list[dict], cohort: bool = False) -> dict:
    """
    機能: 相殺前の各場会計を期間へ足し、平均勝負額を人数から再計算する。
    引数: rows (list[dict]) は親又は建玉群の会計、cohort (bool) は集計名。
    返り値: dict は期間G/L、枚数、平均勝負額と利益金額割合。
    """
    noun = 'cohorts' if cohort else 'campaigns'
    fields = ('profit', 'loss', 'net', 'gross', 'fees', noun, 'winning_' + noun,
              'losing_' + noun, 'flat_' + noun, 'winning_lots', 'losing_lots', 'flat_lots', 'lots')
    result = {field: sum(row[field] for row in rows) for field in fields}
    wins, losses = result['winning_' + noun], result['losing_' + noun]
    result['average_win'] = result['profit'] / wins if wins else None
    result['average_loss'] = result['loss'] / losses if losses else None
    result['payoff'] = result['average_win'] / result['average_loss'] if wins and losses else None
    result['profit_share'] = result['profit'] / (result['profit'] + result['loss']) \
        if result['profit'] + result['loss'] > 0 else None
    return result


def quantile(values: list[float], probability: float) -> float | None:
    """
    機能: 昇順列の線形分位をNumPy集計へ委譲せず求める。
    引数: values (list[float])、probability (float) は0から1の分位。
    返り値: float | None は線形分位又は空の不明。
    """
    if not values:
        return None
    assert 0 <= probability <= 1
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def summarize(config: dict, rows: list[dict], sessions: list[str], first_prices: dict) -> dict:
    """
    機能: 独立会計から日別依存と共通10/20枚・全16分母の安定性を再計算する。
    引数: config/first_prices (dict)、rows (list[dict])、sessions (list[str])。
    返り値: dict は期間と安定性。未使用枠・活動追加・実ピークで分母を変えない。
    """
    periods, stability = {}, {}
    for symbol in SYMBOLS:
        selected = [next(row for row in rows if row['session'] == session and row['symbol'] == symbol)
                    for session in sessions]
        active = [row for row in selected if row['campaigns'] > 0]
        red = [row for row in active if row['net'] < -EPSILON]
        totals_period = combine(selected)
        totals_period['cohorts'] = combine([row['cohorts'] for row in selected], cohort=True)
        day_nets = {}
        for row in selected:
            day = row['session'][:10]
            day_nets[day] = day_nets.get(day, 0.) + row['net']
        best = max(day_nets, key=day_nets.get) if day_nets else None
        rest = [row for row in selected if row['session'][:10] != best]
        totals_period.update(active_sessions=len(active), best_day=best,
                             without_best_day=combine(rest))
        totals_period['without_best_day']['cohorts'] = combine([row['cohorts'] for row in rest], cohort=True)
        periods[symbol] = totals_period
        # ----------------------------------------
        scale, multiplier = (1, 1000.) if symbol == 'TOPIX' else (2, 10.)
        original = (int(config['trend_budget']) + int(config['range_budget'])) * scale
        quantity = original if config['trend_initial_quantity'] is None else int(config['trend_initial_quantity'])
        cap = 10 * scale
        units = {session: cap * multiplier * float(first_prices[session, symbol]) * .001 for session in sessions}
        assert all(math.isfinite(unit) and unit > 0 for unit in units.values())
        normalized = [row['net'] / units[row['session']] for row in active]
        negatives = [min(value, 0.) for value in normalized]
        red_units = [-row['net'] / units[row['session']] for row in red]
        stability[symbol] = dict(
            configured_quantity=quantity, comparison_cap=cap,
            maximum_configured_quantity=original if config['trend_growth_mode'] else quantity,
            actual_peak_quantity=max((row['actual_peak_quantity'] for row in selected), default=0),
            session_count=len(selected), active_sessions=len(active), no_trade_sessions=len(selected) - len(active),
            losing_sessions=len(red),
            positive_session_rate=sum(row['net'] > EPSILON for row in active) / len(active) if active else None,
            mean_losing_session_yen=sum(-row['net'] for row in red) / len(red) if red else 0.,
            worst_session_loss_yen=max((-row['net'] for row in red), default=0.),
            downside_rms_units=math.sqrt(sum(value * value for value in negatives) / len(selected)) if selected else None,
            active_downside_rms_units=math.sqrt(sum(value * value for value in negatives) / len(active)) if active else None,
            mean_losing_session_units=sum(red_units) / len(red_units) if red else 0.,
            worst_session_loss_units=max(red_units, default=0.),
            active_net_q25_units=quantile(normalized, .25), active_net_median_units=quantile(normalized, .5),
            session_net_q25_yen=quantile([row['net'] for row in selected], .25),
            session_net_median_yen=quantile([row['net'] for row in selected], .5),
            comparison_units_yen=units)
    return dict(config=config, periods=periods, stability=stability)


def ranking(result: dict) -> tuple:
    """
    機能: 宣言済み順に二商品の悪い側の安定指標を独立に並べる。
    引数: result (dict) は独立summary。
    返り値: tuple はRMS・活動黒字率・最大赤字・q25・親/建玉群金額割合・IDの順。
    """
    stable = [result['stability'][symbol] for symbol in SYMBOLS]
    values = [result['periods'][symbol] for symbol in SYMBOLS]
    rms = [row['downside_rms_units'] if row['downside_rms_units'] is not None else 1e300 for row in stable]
    rates = [row['positive_session_rate'] if row['positive_session_rate'] is not None else -1 for row in stable]
    lower = [row['active_net_q25_units'] if row['active_net_q25_units'] is not None else -1e300 for row in stable]
    shares = [min(row['profit_share'], row['cohorts']['profit_share'])
              if row['profit_share'] is not None and row['cohorts']['profit_share'] is not None else -1
              for row in values]
    return (max(rms), -min(rates), max(row['worst_session_loss_units'] for row in stable),
            -min(lower), -min(shares), result['config']['id'])


def choose(results: list[dict]) -> dict:
    """
    機能: 活動・両黒字・親/建玉群損小利大・最大日除外・両金額80%の集合を独立判定する。
    引数: results (list[dict]) は人工又は許可された全条件summary。
    返り値: dict は代表・集合段階・候補ID・独立score。小QのRMSだけを成功とは認定しない。
    """
    assert results
    active = [r for r in results if all(r['periods'][symbol]['campaigns'] >= 20
                                      and r['periods'][symbol]['active_sessions'] >= 8 for symbol in SYMBOLS)]
    positive = [r for r in active if all(r['periods'][symbol]['net'] > 0 for symbol in SYMBOLS)]
    good = [r for r in positive if all(r['periods'][symbol]['payoff'] is not None
                                    and r['periods'][symbol]['payoff'] > 1
                                    and r['periods'][symbol]['cohorts']['payoff'] is not None
                                    and r['periods'][symbol]['cohorts']['payoff'] > 1 for symbol in SYMBOLS)]
    robust = [r for r in good if all(r['periods'][symbol]['without_best_day']['net'] > 0 for symbol in SYMBOLS)]
    target = [r for r in robust if all(r['periods'][symbol]['profit_share'] >= .8
                                    and r['periods'][symbol]['cohorts']['profit_share'] >= .8 for symbol in SYMBOLS)]
    groups = (target, robust, good, positive, active, results)
    level = next(i for i, group in enumerate(groups) if group)
    pool = groups[level]
    return dict(selected=min(pool, key=ranking)['config']['id'], level=level,
                eligible=[r['config']['id'] for r in pool],
                scores={r['config']['id']: ranking(r) for r in pool})


# ----------------------------------------


def inspect(base: Path, fixed: dict, first_prices: dict) -> list[dict]:
    """
    機能: 許可された全20前16の640口座を注文・建玉群から再会計し保存結果へ照合する。
    引数: base (Path)、fixed/first_prices (dict) は保存前16と正常始値。
    返り値: list[dict] は独立summary。根score/select/accountingは呼ばない。
    """
    guard(base, fixed)
    sessions, answers = fixed['前16'], []
    for config in fixed['条件']:
        ledger_path = base / 'front/ledgers' / (config['id'] + '.pkl')
        saved = read(base / 'front/results' / (config['id'] + '.json'))
        assert saved['config'] == config and saved['ledger_SHA256'] == digest(ledger_path)
        ledger = read(ledger_path)
        expected_keys = {(session, symbol) for session in sessions for symbol in SYMBOLS}
        assert set(ledger) == expected_keys
        assert {(row['session'], row['symbol']) for row in saved['rows']} == expected_keys
        assert len(saved['rows']) == len(expected_keys) == 32
        rows = []
        for session in sessions:
            for symbol in SYMBOLS:
                key = (session, symbol)
                computed = account(ledger[key], symbol)
                stored = next(row for row in saved['rows'] if (row['session'], row['symbol']) == key)
                for field, expected in computed.items():
                    if field == 'cohorts':
                        for name, value in expected.items():
                            close(stored['cohorts'][name], value, config['id'] + ' 建玉群 ' + name)
                    elif field == 'actual_peak_quantity':
                        close(max(stored['maximums']['held_long'], stored['maximums']['held_short']), expected,
                              config['id'] + ' 実保有peak')
                    else:
                        close(stored[field], expected, config['id'] + ' 親 ' + field)
                rows.append(dict(session=session, symbol=symbol, **computed))
        summary = summarize(config, rows, sessions, first_prices)
        for symbol in SYMBOLS:
            actual = saved['periods']['前16'][symbol]
            expected = summary['periods'][symbol]
            for field, value in expected.items():
                if field == 'cohorts':
                    for name, amount in value.items():
                        close(actual[field][name], amount, '期間建玉群 ' + name)
                elif field == 'without_best_day':
                    for name, amount in value.items():
                        if name == 'cohorts':
                            for group_name, group_amount in amount.items():
                                close(actual[field][name][group_name], group_amount, '最大日除外建玉群 ' + group_name)
                        else:
                            close(actual[field][name], amount, '最大日除外親 ' + name)
                else:
                    close(actual[field], value, '期間親 ' + field)
            for field, value in summary['stability'][symbol].items():
                if isinstance(value, dict):
                    for session, unit in value.items():
                        close(saved['stability'][symbol][field][session], unit, '共通比較単位')
                else:
                    close(saved['stability'][symbol][field], value, '安定性 ' + field)
        answers.append(summary)
    return answers


def main() -> None:
    """
    機能: 根の前16/select完了・後15未作成の明示通知後だけ正式検算する。
    引数: --root-front-select-complete (bool) は根から当該通知を受領した場合だけ指定する。
    返り値: None。前16参考と親/建玉群会計の独立証跡を新規保存する。売買・API取得はしない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--root-front-select-complete', action='store_true')
    args = parser.parse_args()
    assert args.root_front_select_complete, '前16/select完了の明示通知前は金融結果を読みません'
    fixed_path, selected_path = WORK / '事前固定.json', WORK / '前16参考代表.json'
    fixed = read(fixed_path)
    guard(WORK, fixed)
    selected = read(selected_path)
    assert selected['後15正式損益前選定'] and selected['固定SHA256'] == digest(fixed_path)
    for relative, expected in fixed['SHA256'].items():
        assert digest(ROOT / relative) == expected, relative
    front_paths = sorted((WORK / 'front/results').glob('*.json'))
    assert selected['結果SHA256'] == {str(path.relative_to(ROOT)): digest(path) for path in front_paths}
    # ----------------------------------------
    # 価格は101の保存入力だけから読む。根researchの採点も新売買も実行しない。
    spec = importlib.util.spec_from_file_location('101選定独立入力読取', WORK / 'data.py')
    material_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(material_module)
    material = material_module.load_inputs()
    first_prices = {(session, symbol): float(material['prices'][session, symbol]['price'][0])
                    for session in fixed['前16'] for symbol in SYMBOLS}
    material_paths = list(material['paths'])
    del material
    results = inspect(WORK, fixed, first_prices)
    independent = choose(results)
    assert independent['selected'] == selected['selected'] and independent['level'] == selected['level']
    assert independent['eligible'] == selected['eligible']
    assert set(independent['scores']) == set(selected['scores'])
    for ident, values in independent['scores'].items():
        for index, value in enumerate(values):
            close(selected['scores'][ident][index], value, 'score ' + ident)
    paths = [Path(__file__), fixed_path, selected_path, WORK / 'research.py', WORK / 'accounting.py',
             WORK / 'data.py', WORK / 'セッション安定性の事前評価.json', *material_paths]
    paths += list((WORK / 'front/results').glob('*.json')) + list((WORK / 'front/ledgers').glob('*.pkl'))
    proof = dict(全合格=True, 条件数=20, 前16口座数=640, 参考代表=independent['selected'],
                 段階=independent['level'], 候補集合=independent['eligible'], 独立score=independent['scores'],
                 独立再集計=results,
                 scope='注文別料/累計建料/全量返済料配分/親と建玉群G/L枚数/採点に使う安定性。原本全行の含み時価はこの検査の認定範囲外。',
                 根score及びselect及びaccounting呼出=0, 後15損益閲覧=0, 新売買実行=0, 全31既知=True,
                 共通10及び20枚分母と全16場分母=True,
                 採用保証=False, 数量縮小だけのRMS改善を確度改善と呼ばない=True,
                 SHA256={str(path.relative_to(ROOT)): digest(path) for path in paths}, API取得=0, 実注文=0)
    path = HERE / '後15未作成の全20前16注文と建玉群会計及び独立参考選定.json'
    assert not path.exists()
    path.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in proof.items()
                      if key not in ('SHA256', '独立score', '独立再集計')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
