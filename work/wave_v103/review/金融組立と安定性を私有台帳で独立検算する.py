"""正式金融を読まず、root実組立経路を私有経済台帳で検算する。"""

from copy import deepcopy
from decimal import Decimal, ROUND_FLOOR
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import pickle
import sys
from types import SimpleNamespace

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WAVE = HERE.parent


def load(name: str, path: Path) -> object:
    """
    機能: 金融組立sourceと会計列定義を固有名で読む。
    引数: name(str)、path(Path)はモジュール名と位置。
    返り値: objectは部品。正式金融・base・activityのcacheを開かない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def digest(path: Path) -> str:
    """
    機能: 小source又は私有台帳の指紋を求める。
    引数: path(Path)は対象。
    返り値: strはSHA256。原本、新公式損益及び旧結果を読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ----------------------------------------

def fee(quantity: int, symbol: str) -> int:
    """
    機能: 二進floatや本体fee関数を使わず、実注文枚数ごとの片道料金を計算する。
    引数: quantity(int)、symbol(str)は実枚数と商品。
    返り値: intは税込単価合計の1円未満切捨て額。
    """
    unit = Decimal('41.8') if symbol == 'TOPIX' else Decimal('11')
    return int((unit * quantity).to_integral_value(rounding=ROUND_FLOOR))


def row(columns: list[str], values: dict) -> np.ndarray:
    """
    機能: 公開列名へ人工経済値を対応させる。
    引数: columns(list[str])、values(dict)は列と明示値。
    返り値: ndarray[float64]は一行。列番号を台帳から逆算しない。
    """
    return np.array([values.get(name, 0) for name in columns], np.float64)


def economic_output(symbol: str, side: int, quantity: int, columns: object) -> dict:
    """
    機能: 明示した2注文・1完結親の私有経済台帳を作る。
    引数: symbol(str)、side/quantity(int)、columns(object)は商品、方向、枚数と列定義。
    返り値: dictはsourceと同型の小台帳。旧出口の再生や入口の有用性を表すものではない。
    """
    opening, tick, multiplier = (4000., .5, 1000) if symbol == 'TOPIX' else (50000., 10., 10)
    charge = fee(quantity, symbol)
    entry = opening + tick if side == 1 else opening
    liquidation = opening + 3 * tick if side == 1 else opening + 4 * tick
    gross = side * quantity * (liquidation - entry) * multiplier
    net = gross - 2 * charge
    orders = np.array([
        row(columns.ORDER_COLUMNS, dict(row=2, decision_row=1, parent_id=1, source=0,
            action_side=side, quantity=quantity, price=entry, is_entry=1, reason=1, fee=charge,
            decision_time=301, fill_time=302, uid=1, source_entry_side=side)),
        row(columns.ORDER_COLUMNS, dict(row=4, decision_row=3, parent_id=1, source=0,
            action_side=-side, quantity=quantity, price=liquidation, is_entry=0, reason=3, fee=charge,
            decision_time=2102, fill_time=2103, uid=2, source_entry_side=side))])
    trades = np.array([row(columns.TRADE_COLUMNS, dict(parent_id=1, source=0, entry_row=2,
        exit_row=4, side=side, quantity=quantity, entry_price=entry, exit_price=liquidation,
        entry_fee=charge, exit_fee=charge, gross=gross, net=net, entry_reason=1, exit_reason=3,
        entry_decision_row=1))])
    cohorts = np.array([row(columns.GROWTH_COHORT_COLUMNS, dict(parent_id=1, cohort_id=1, source=0,
        side=side, quantity=quantity, decision_row=1, decision_seq=101, decision_time=301,
        entry_row=2, entry_seq=102, entry_time=302, entry_price=entry, entry_fee=charge,
        order_uid=1, exit_row=4, exit_seq=104, exit_time=2103, exit_price=liquidation,
        exit_fee_share=charge, gross=gross, net=net, initial_quantity=quantity,
        parent_final_quantity=quantity))])
    curve = np.array([0, 0, -tick * quantity * multiplier - 2 * charge, net, net, net], float)
    trace = np.zeros((6, 6), float)
    col = 0 if side == 1 else 1
    trace[1, col + 2] = quantity
    trace[1, 4] = quantity
    trace[2:4, col] = trace[2:4, col + 2] = quantity
    trace[3, 5] = quantity
    stats = np.zeros(len(columns.STAT_COLUMNS), float)
    stats[:4] = trace[:, :4].max(axis=0)
    stats[8] = quantity
    stats[13] = 1
    stats[-1] = net
    return dict(orders=orders, order_columns=columns.ORDER_COLUMNS,
        trades=trades, trade_columns=columns.TRADE_COLUMNS,
        growth_cohorts=cohorts, growth_cohort_columns=columns.GROWTH_COHORT_COLUMNS,
        events=np.zeros((0, len(columns.EVENT_COLUMNS))), event_columns=columns.EVENT_COLUMNS,
        stats=stats, stat_columns=columns.STAT_COLUMNS, curve=curve,
        source_curve=np.column_stack((curve, np.zeros(6))), target_trace=trace,
        trace_columns=columns.TRACE_COLUMNS,
        raw_entry_diagnostics=[dict(parent_id=1, order_uid=1, decision_row=1, fill_row=2,
            quantity=quantity, side=side, fee=charge, episode=dict(人工専用=True))])


def verify_economics(output: dict, symbol: str) -> dict:
    """
    機能: 注文だけから現金損益、実料金、枚数及び識別子を独立算数で照合する。
    引数: output(dict)、symbol(str)は人工口座と商品。
    返り値: dictは独立の費用後利益・損失・収支。accountingの集計を期待値に使わない。
    """
    orders = output['orders']
    positions = {name: index for index, name in enumerate(output['order_columns'])}
    multiplier = 1000 if symbol == 'TOPIX' else 10
    parents = sorted({int(order[positions['parent_id']]) for order in orders})
    totals, total_fee = [], 0
    for order in orders:
        expected_fee = fee(int(order[positions['quantity']]), symbol)
        assert order[positions['fee']] == expected_fee
        total_fee += expected_fee
    for parent in parents:
        matching = [order for order in orders if int(order[positions['parent_id']]) == parent]
        quantity_balance = sum(int(order[positions['action_side']]) * int(order[positions['quantity']]) for order in matching)
        assert quantity_balance == 0
        cash = sum(-int(order[positions['action_side']]) * int(order[positions['quantity']])
                   * Decimal(str(order[positions['price']])) * multiplier
                   - Decimal(int(order[positions['fee']])) for order in matching)
        totals.append(float(cash))
    assert len(set(orders[:, positions['uid']])) == len(orders)
    expected = dict(profit=sum(value for value in totals if value > 0),
                    loss=-sum(value for value in totals if value < 0), net=sum(totals), fees=total_fee)
    assert math.isclose(output['curve'][-1], expected['net'], abs_tol=1e-8)
    np.testing.assert_allclose(output['source_curve'].sum(axis=1), output['curve'], atol=1e-8, rtol=0)
    assert not output['target_trace'][-1].any()
    return expected


# ----------------------------------------

def main() -> None:
    """
    機能: 実one_sessionの組立・脚再利用・台帳保存と費用後評価を私有人工で検査する。
    引数: なし。
    返り値: None。root source及び正式金融領域を変更せず、reviewへ証跡を保存する。
    """
    destination = HERE / '金融one_session組立と実枚数及び安定性の独立人工.json'
    assert not destination.exists(), '完成検査は上書きしません'
    research_path = WAVE / 'research.py'
    before = digest(research_path)
    research = load('独立金融組立103', research_path)
    catalog = load('独立金融組立条件103', WAVE / 'catalog.py')
    adapter = load('独立金融組立adapter103', WAVE / 'engine' / 'adapter.py')
    accounting = load('独立金融組立会計102', ROOT / 'work' / 'wave_v102' / 'accounting.py')
    columns = load('独立金融組立の公開列102', ROOT / 'work' / 'wave_v102' / 'engine.py')
    calls, templates = [], {}
    session = '私有人工セッション'
    accounts = {symbol: dict(item=dict(symbol=symbol)) for symbol in ('TOPIX', 'NK225')}
    prepared = {(session, symbol): dict(人工専用=True, symbol=symbol) for symbol in accounts}
    old_rows = {(session, symbol): accounting.account((session, symbol), economic_output(symbol, 1, 1, columns))
                for symbol in accounts}

    def artificial_play(value: dict, account: dict, ident: str, quantity: int) -> dict:
        """
        機能: 実組立の金融呼出しを、数量付き私有経済台帳へ限定する。
        引数: value/account(dict)、ident(str)、quantity(int)は明示人工の組立引数。
        返り値: dictは人工台帳。実execute・base・活動cacheへ接続しない。
        """
        assert value['人工専用'] is True
        symbol = account['item']['symbol']
        side = -1 if ident.startswith('R') else 1
        calls.append((symbol, ident, quantity))
        key = symbol, side, quantity
        if key not in templates:
            templates[key] = economic_output(symbol, side, quantity, columns)
        return deepcopy(templates[key])

    def module_stub(name: str, path: Path) -> object:
        """
        機能: 実one_sessionの依存だけを私有fixtureと読取会計へ差し替える。
        引数: name(str)、path(Path)は呼出し情報。
        返り値: objectは明示人工依存。正式cache、旧損益及びengine.executeを呼ばない。
        """
        values = {'103金融の活動cache': SimpleNamespace(load_session=lambda requested: dict(accounts=accounts)),
                  '103金融の接続': SimpleNamespace(play=artificial_play),
                  '103金融の旧接続': adapter, '103金融の会計': accounting}
        assert name in values
        return values[name]

    research.module = module_stub
    outputs, rows_checked, ledgers_checked, economics = [], 0, 0, []
    for label, duplicate in (('条件19', False), ('脚再利用対照', True)):
        private = HERE / '私有金融組立' / label
        private.mkdir(parents=True)
        research.HERE = private
        cases = catalog.catalog()
        if duplicate:
            repeat = deepcopy(next(config for config in cases if config['id'] == 'P20'))
            repeat['id'] = '人工P20再利用'
            cases.append(repeat)
        calls.clear()
        answer = research.one_session(session, prepared, cases, old_rows)
        assert len(answer) == (20 if duplicate else 19)
        assert len(calls) == 42
        for symbol in accounts:
            for family in ('C1', 'R1'):
                quantities = (2, 5, 8) if symbol == 'TOPIX' else (4, 10, 16)
                for quantity in quantities:
                    assert calls.count((symbol, family, quantity)) == 1
        for config in cases:
            output = answer[config['id']]
            assert len(output['rows']) == 2
            rows_checked += 2
            assert len(output['ledgers']) == (0 if config['kind'] == 'previous' else 2)
            if config['kind'] == 'previous':
                continue
            for symbol in accounts:
                artifact = output['ledgers'][session + '|' + symbol]
                path = ROOT / artifact['path']
                assert path.resolve().is_relative_to(private.resolve())
                assert digest(path) == artifact['SHA256']
                with gzip.open(path, 'rb') as stream:
                    ledger = pickle.load(stream)
                assert all(name in ledger for name in ('orders', 'order_columns', 'trades', 'trade_columns',
                    'events', 'event_columns', 'stats', 'stat_columns', 'curve', 'source_curve', 'target_trace',
                    'trace_columns', 'growth_cohorts', 'growth_cohort_columns', 'raw_entry_diagnostics'))
                expected = verify_economics(ledger, symbol)
                actual = next(row for row in output['rows'] if row['symbol'] == symbol)
                for name, value in expected.items():
                    assert math.isclose(actual[name], value, abs_tol=1e-8), (config['id'], symbol, name)
                reproduced = accounting.account((session, symbol), ledger)
                assert reproduced == actual
                if config['kind'] == 'portfolio':
                    allocation = config['allocations'][symbol]
                    assert ledger['pulse_id'] is None and ledger['configured_quantity'] == sum(allocation)
                    assert actual['campaigns'] == 2 and actual['lots'] == sum(allocation)
                    assert np.all(ledger['target_trace'][:, :4] <= sum(allocation))
                    assert set(ledger['trades'][:, 0]) == {2., 3.}
                    assert set(ledger['orders'][:, 16]) == {2., 3., 4., 5.}
                    assert set(ledger['growth_cohorts'][:, 1]) == {2., 3.}
                    assert sorted(row['family'] for row in ledger['raw_entry_diagnostics']) == ['C', 'R']
                    # ----------------------------------------
                    # 一方の利益と他方の損失を相殺して利益割合を作らない。
                    assert actual['profit'] > 0 and actual['loss'] > 0
                    economics.append(dict(条件=config['id'], 商品=symbol, **expected))
                else:
                    assert ledger['pulse_id'] == config['id'] and ledger['configured_quantity'] == 1
                ledgers_checked += 1
        outputs.append(dict(人工=label, 条件数=len(cases), 金融stub呼出し数=len(calls)))
    # ----------------------------------------
    # 活動・赤字頻度・設定合計枚数による単位を独立な小標本で検査する。
    sessions = ['人工利益', '人工損失', '人工同値', '人工未活動']
    evaluation_rows = [dict(session=session, symbol=symbol, campaigns=0 if session == '人工未活動' else 1,
                            net=1000 if session == '人工利益' else -2000 if session == '人工損失' else 0)
                       for symbol in accounts for session in sessions]
    openings = {(session, symbol): 4000 if symbol == 'TOPIX' else 50000
                for symbol in accounts for session in sessions}
    stability_checks = []
    for config in (next(item for item in catalog.catalog() if item['id'] == 'C1'),
                   next(item for item in catalog.catalog() if item['id'] == 'P50')):
        actual = research.stability(evaluation_rows, config, openings, sessions)
        for symbol in accounts:
            result = actual[symbol]
            quantity = (10 if symbol == 'TOPIX' else 20) if config['kind'] == 'portfolio' else 1
            unit = Decimal(str(openings[sessions[0], symbol])) * (1000 if symbol == 'TOPIX' else 10) * quantity * Decimal('.001')
            expected_worst = float(Decimal(2000) / unit)
            assert result['active_sessions'] == 3 and result['no_trade_sessions'] == 1
            assert result['positive_sessions'] == result['losing_sessions'] == result['flat_active_sessions'] == 1
            assert result['losing_active_rate'] == 1 / 3 and not result['activity_adequate']
            assert math.isclose(result['worst_session_loss_units'], expected_worst, abs_tol=1e-12)
            assert math.isclose(result['downside_rms_units'], expected_worst / math.sqrt(3), abs_tol=1e-12)
            assert result['configured_quantity'] == quantity and result['without_best_session_net'] == -2000
            stability_checks.append(dict(条件=config['id'], 商品=symbol, 設定枚数=quantity,
                                         独立最大損失単位=expected_worst, 合格=True))
    no_trade = [dict(session=session, symbol=symbol, campaigns=0, net=0) for symbol in accounts for session in sessions]
    absent = research.stability(no_trade, catalog.catalog()[0], openings, sessions)
    for result in absent.values():
        assert result['losing_active_rate'] is None and result['downside_rms_units'] is None
        assert not result['activity_adequate'] and result['positive_sessions'] == 0
    assert digest(research_path) == before, '検算中にroot sourceが更新されました'
    proof_path = WAVE / 'engine' / '活動normal投影と旧固定出口の金融接口人工検査_呼出統一.json'
    proof = json.loads(proof_path.read_text(encoding='utf-8'))
    assert proof['全合格'] and proof['全32金融再生'] == 0
    for relative, wanted in proof['SHA256'].items():
        assert digest(ROOT / relative) == wanted
    result = dict(全合格=True,
        scope='実research.one_sessionの金融playだけを明示私有経済台帳stubへ差し替えた組立検査。根正式損益や旧結果を読まず、同出口の再生自体は公式接口人工へ委譲。',
        組立=outputs, 会計行照合数=rows_checked, 全curve含む台帳往復検査数=ledgers_checked,
        私有配分の相殺前独立経済値=economics, 配分C_R鍵一致=True,
        実枚数料金Decimal独立検算=True, parent_uid_cohort名前空間衝突なし=True,
        脚再利用対照は同component同quantity一回だけ=True,
        活動最低条件と無取引勝ち除外=True, stabilityの設定総枚数比較=stability_checks,
        限界='設定合計枚数の単位は配置した片方向予算の単位であり、実際の総リスク又は必要証拠金の等価性は保証しない。赤字率と円額も併記する仕様は妥当。未活動で0損失を安定成功にしない。',
        SHA256={str(path.relative_to(ROOT)): digest(path) for path in (Path(__file__), research_path,
            WAVE / '金融結果前の安定性評価.json', WAVE / 'engine' / 'finance_adapter.py',
            WAVE / 'engine' / 'adapter.py', WAVE / 'catalog.py', proof_path,
            ROOT / 'work' / 'wave_v102' / 'accounting.py')},
        正式全32金融=0, 正式activity_cache読取=0, base読取=0, 旧損益読取=0, 新公式損益読取=0,
        原本読取=0, API取得=0, 実注文=0, JIT実行=0, 金融engine_execute実行=0, 他owner_source変更=0)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 会計行照合数=rows_checked, 台帳往復検査数=ledgers_checked,
                         組立=outputs, SHA256=digest(destination)), ensure_ascii=False))


if __name__ == '__main__':
    main()
