"""101の新正式損益を開かず、私有人工で増玉の現金・実源・優先順を反証する。"""

from copy import deepcopy
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import pickle
import sys

os.environ['NUMBA_DISABLE_JIT'] = '1'
sys.dont_write_bytecode = True
import numpy as np

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
PATTERN = [0., 1., 1., 5., 5., 13., 13., 21., 21., 16., 16.]
OLD_ARRAYS = ('orders', 'trades', 'curve', 'source_curve', 'target_trace', 'events', 'stats', 'slots',
    'range_state_trace', 'risk_state_trace', 'range_parent_diagnostics', 'price_source_trace',
    'loss_reentry_events', 'trend_exit_state_trace', 'trend_parent_diagnostics', 'watch_state_trace',
    'entry_parent_diagnostics', 'entry_wait_events', 'entry_policy_state_trace', 'entry_policy_events',
    'entry_cap_state_trace', 'entry_cap_parent_diagnostics', 'entry_support_state_trace')


def module(name: str, path: Path) -> object:
    """
    機能: mainと正式素材を開かず局所実装だけを読み込む。
    引数: name(str)、path(Path)。
    返り値: object。バイトコード及びJITを過去領域へ保存しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def digest(path: Path) -> str:
    """
    機能: 結果前の実装及び固定純数理を内容指紋へ結び付ける。
    引数: path(Path)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(value: object) -> str:
    """
    機能: 私有人工の共有入力と設定に副作用がないことを検査する。
    引数: value(object)。
    返り値: strはpickle内容指紋。
    """
    return hashlib.sha256(pickle.dumps(value, protocol=5)).hexdigest()


def fee(quantity: int, unit: float) -> int:
    """
    機能: 片道一注文の料金を独立した十進有理数で切捨てる。
    引数: quantity(int)、unit(float)。
    返り値: int。追加を合算した新規一注文へ置換しない。
    """
    return math.floor(quantity * Fraction(str(unit)))


def round_line(price: Fraction, side: int, tick: float) -> float:
    """
    機能: 有理数の価格全体を保護方向へ丸める独立oracle。
    引数: price(Fraction)、side(int)、tick(float)。
    返り値: float。買ceil・売floorで不利に緩めない。
    """
    quantum = Fraction(str(tick))
    units = price / quantum
    return float((math.ceil(units) if side == 1 else math.floor(units)) * quantum)


def fixture(config: dict, symbol: str, side: int, ticks: list[float] | None = None,
            times: list[float] | None = None, opening: float | None = None, change: object = None) -> dict:
    """
    機能: 正常両BBOと方向別支持を持つ短い私有人工を独立作成する。
    引数: config(dict)、symbol(str)、side(int)、ticks/times(list[float]|None)、opening(float|None)、change(callable|None)。
    返り値: dictはprepared。支持bool注入はLP原本窓の正解又は実配信順の認定ではない。
    """
    progress = np.asarray(PATTERN if ticks is None else ticks, float)
    n = len(progress)
    stamps = np.asarray(times if times is not None else np.arange(n) + 300., float)
    tick, base, peer_tick, peer_base = (.5, 4000., 10., 70000.) if symbol == 'TOPIX' else (10., 70000., .5, 4000.)
    base = base if opening is None else opening
    quote = base + side * progress * tick
    bid = quote - tick if side == 1 else quote.copy()
    ask = quote.copy() if side == 1 else quote + tick
    record = dict(symbol=symbol, tick=tick, start=0., limit=10000., time_s=stamps,
        price=.5 * (bid + ask), bid=bid, ask=ask, price_valid=np.ones(n, bool),
        quote_valid=np.ones(n, bool), seq=np.arange(n, dtype=np.int64) + 100)
    peer_bid = peer_base + side * progress * peer_tick
    peer = np.column_stack((np.arange(n), np.arange(n) + 200, stamps - .25,
        peer_bid, peer_bid + peer_tick, np.ones(n)))
    event = np.zeros(n, np.int8); event[0] = side
    width = max(2, math.ceil(base * .001 / tick - 1e-10)) * tick
    signal = dict(grid=stamps.copy(), mapped=np.arange(n), mode=np.zeros(n, np.int8),
        event=event, quality=np.ones(n, bool), reset=np.zeros(n, bool),
        trend_width=max(2, math.ceil(base * .004 / tick - 1e-10)) * tick, peer_tick=peer_tick,
        entry_wait_width=width, entry_advance_width=0., entry_pullback_width=0., entry_recovery_width=0.,
        entry_j2_long=np.full(n, side == 1, bool), entry_j2_short=np.full(n, side == -1, bool),
        wait_opposite_long=np.zeros(n, bool), wait_opposite_short=np.zeros(n, bool), entry_peer_bbo=peer)
    basis = np.full((n, 59), np.nan)
    basis[:, 0] = np.arange(n); basis[:, 1] = stamps
    value = dict(record=record, signal=signal, reference_open=base,
        trend_lp_allowed={1: np.full(n, side == 1, bool), -1: np.full(n, side == -1, bool)},
        entry_support_base=basis)
    if change is not None: change(value)
    return {('2000-01-03_人工', symbol): value}


def named(row: np.ndarray, columns: list[str]) -> dict:
    """
    機能: 独立照合で固定位置と意味を混同しないよう保存列を名前へ写す。
    引数: row(ndarray[float])、columns(list[str])。
    返り値: dict[str,float]。未知値を他源で救済しない。
    """
    assert len(row) == len(columns)
    return dict(zip(columns, row))


def run(strategy: object, config: dict, prepared: dict) -> dict:
    """
    機能: 私有人工だけを実行して共有入力の非変更を確認する。
    引数: strategy(object)、config/prepared(dict)。
    返り値: dictは人工出力。新正式成績を生成しない。
    """
    key = next(iter(prepared))
    before = fingerprint((config, prepared))
    output = strategy.play(config, key, prepared, finish=False)
    assert fingerprint((config, prepared)) == before
    return output


def growth_entries(output: dict) -> np.ndarray:
    """
    機能: 同じ親の初回及び追加の実新規を実注文から抽出する。
    引数: output(dict)。
    返り値: ndarray。未約定予約を実保有へ混ぜない。
    """
    return output['orders'][output['orders'][:, 7] == 1]


def verify_cash(output: dict, prepared: dict, config: dict) -> dict:
    """
    機能: 全cohort・全実注文・親と全行実保有の現金及び非緩和線を独立照合する。
    引数: output/prepared/config(dict)は私有人工だけ。
    返り値: dictは検査件数と例。実曲線の全原本再構成又は収益性の証明ではない。
    """
    key = next(iter(prepared)); record = prepared[key]['record']
    symbol, tick = key[1], record['tick']
    multiplier, unit, maximum = (1000., 41.8, 8) if symbol == 'TOPIX' else (10., 11., 16)
    cohorts = output['growth_cohorts']
    columns = output['growth_cohort_columns']
    states = output['growth_state_trace']; state_columns = output['growth_state_columns']
    assert cohorts.shape[1] == len(columns) == 25
    assert states.shape[1] == len(state_columns) == 70
    assert len(states) == len(record['time_s'])
    by_parent = {}
    orders = output['orders']
    for row in cohorts:
        d = named(row, columns)
        pid, q = int(d['parent_id']), int(d['quantity'])
        assert q > 0 and int(d['entry_seq']) == record['seq'][int(d['entry_row'])]
        assert d['entry_time'] == record['time_s'][int(d['entry_row'])]
        side = int(d['side'])
        assert d['entry_price'] == record['ask' if side == 1 else 'bid'][int(d['entry_row'])]
        assert d['entry_fee'] == fee(q, unit)
        matching = orders[orders[:, 16] == d['order_uid']]
        assert len(matching) == 1 and matching[0, 5] == q and matching[0, 7] == 1
        assert matching[0, 2] == pid and matching[0, 6] == d['entry_price']
        by_parent.setdefault(pid, []).append(d)
    for pid, group in by_parent.items():
        assert [int(d['cohort_id']) for d in group] == sorted(int(d['cohort_id']) for d in group)
        traded = output['trades'][output['trades'][:, 0] == pid]
        if not len(traded): continue
        assert len(traded) == 1
        trade = traded[0]
        total_q = sum(int(d['quantity']) for d in group)
        assert total_q == trade[5] <= maximum
        weighted = sum(d['quantity'] * d['entry_price'] for d in group) / total_q
        assert weighted == trade[6] and sum(d['entry_fee'] for d in group) == trade[8]
        assert sum(d['exit_fee_share'] for d in group) == trade[9] == fee(total_q, unit)
        close_fee = int(trade[9])
        allocation = [close_fee * int(d['quantity']) // total_q for d in group]
        remaining = close_fee - sum(allocation)
        ranking = sorted(range(len(group)), key=lambda i: (-(close_fee * int(group[i]['quantity']) % total_q), i))
        for i in ranking[:remaining]: allocation[i] += 1
        assert allocation == [int(d['exit_fee_share']) for d in group]
        for d in group:
            gross = int(d['side']) * (d['exit_price'] - d['entry_price']) * d['quantity'] * multiplier
            assert d['gross'] == gross and d['net'] == gross - d['entry_fee'] - d['exit_fee_share']
        assert sum(d['gross'] for d in group) == trade[10]
        assert sum(d['net'] for d in group) == trade[11]
    previous = {}
    active_rows = 0
    for row, values in enumerate(states):
        d = named(values, state_columns)
        if not np.isfinite(d['parent_id']) or d['parent_id'] <= 0 or d['held_quantity'] <= 0: continue
        pid, q = int(d['parent_id']), int(d['held_quantity'])
        group = [c for c in by_parent[pid] if c['entry_row'] <= row]
        assert sum(int(c['quantity']) for c in group) == q
        assert q + d['pending_quantity'] <= maximum
        initial_q = config['trend_initial_quantity'] or maximum
        assert d['initial_quantity'] == initial_q and d['maximum_quantity'] == maximum
        actual_cash = sum(c['quantity'] * c['entry_price'] * multiplier for c in group)
        actual_fees = sum(c['entry_fee'] for c in group)
        full_fee = fee(q, unit)
        assert d['entry_cash'] == actual_cash and d['entry_fees'] == actual_fees
        assert d['exit_fee_estimate'] == full_fee and d['total_fees'] == actual_fees + full_fee
        assert d['weighted_entry'] == actual_cash / (q * multiplier)
        first = by_parent[pid][0]
        initial_width = max(2, math.ceil(prepared[key]['reference_open'] * .001 / tick - 1e-10)) * tick
        expected_risk = initial_q * initial_width * multiplier + 2 * fee(initial_q, unit)
        assert d['risk_budget'] == expected_risk
        assert d['initial_line'] == first['entry_price'] - first['side'] * initial_width
        if config['trend_hold_seconds']:
            assert d['deadline'] == first['entry_time'] + config['trend_hold_seconds']
        if record['quote_valid'][row]:
            side = int(first['side'])
            liquidation = record['bid' if side == 1 else 'ask'][row]
            net = side * (q * liquidation * multiplier - actual_cash) - actual_fees - full_fee
            assert abs(d['current_net'] - net) < 1e-7
            raw_budget = Fraction(str(actual_cash)) / (q * Fraction(str(multiplier))) \
                - side * Fraction(str(expected_risk - actual_fees - full_fee)) / (q * Fraction(str(multiplier)))
            assert d['budget_line'] == round_line(raw_budget, side, tick)
            if pid in previous:
                assert side * (d['effective_stop'] - previous[pid]['effective_stop']) >= 0
                assert not previous[pid]['protection_active'] or d['protection_active']
            previous[pid] = d
        active_rows += 1
    return dict(cohort数=len(cohorts), 現金全行照合=active_rows, 親数=len(output['trades']),
        親内相殺後の黒字かつ赤字cohortあり=sum(trade[11] > 0 and any(c['net'] < 0 for c in by_parent[int(trade[0])])
            for trade in output['trades']))


def main() -> None:
    """
    機能: 完成本体の独立局所反証を実行し、自担当新規証跡だけ保存する。
    引数: なし。正式101のfront/back/analysis/原本を開く機能はない。
    返り値: None。人工のみの合格又は不一致を残す。
    """
    paths = [BASE / name for name in ('engine.py', 'strategy.py', 'catalog.py', '結果前の設計案.json', '実装前の仕様明確化.json')]
    paths += [HERE / '20条件の予算固定増玉と費用及び予約競合の損益前独立反証.json',
        HERE / '予算と費用の純数理を反証する.py', HERE / '新しい101実装反証_事前期待値.json',
        ROOT / 'work/wave_v100/engine.py', ROOT / 'work/wave_v100/strategy.py']
    before = {path.relative_to(ROOT).as_posix(): digest(path) for path in paths}
    assert before['work/wave_v101/結果前の設計案.json'] == '5db0b6b44360855ede7d439b740845d68bd4d47ba970914b0fae83dfb65de6cc'
    assert before['work/wave_v101/review_pre/20条件の予算固定増玉と費用及び予約競合の損益前独立反証.json'] == '5368660920eaf0e7bf74c64a983d5eae955e1015ff39055f4bb091dee0ac4ab6'
    strategy = module('101実装の私有人工反証', BASE / 'strategy.py')
    old = module('旧100の全量局所nullだけ読取101', ROOT / 'work/wave_v100/strategy.py')
    catalog = module('101数量20の局所固定定義', BASE / 'catalog.py')
    configs = {config['id']: config for config in catalog.catalog()}
    counts = dict(全20買売両商品=0, 旧全量局所null=0, 実保有仮状態の分離=0,
        active及びcohort隠れ損失=0, 未知peer復帰=0, 同fillrow禁止=0, 予約後資格悪化=0,
        初回期限と追加cut分離=0, 実追加fill後即stop=0, 人工prefix未来=0,
        数理全線統合及び未保有peak=0)
    findings = []

    # ----------------------------------------
    # 全有限条件の絶対数量及びcohort/親/占有枠を人工だけで照合する。
    for config in configs.values():
        for symbol in ('TOPIX', 'NK225'):
            for side in (-1, 1):
                data = fixture(config, symbol, side, ticks=PATTERN + [-50., -50.])
                output = run(strategy, config, data)
                check = verify_cash(output, data, config)
                entries = growth_entries(output)
                assert len(entries) and entries[0, 5] == (config['trend_initial_quantity'] or (8 if symbol == 'TOPIX' else 16))
                assert int(output['stats'][2]) == int(output['target_trace'][:, 2].max())
                assert int(output['stats'][3]) == int(output['target_trace'][:, 3].max())
                if config['trend_growth_mode'] == 0: assert len(entries) == 1
                counts['全20買売両商品'] += 1
                if config['trend_initial_quantity'] is None:
                    key = next(iter(data))
                    previous = old.play(catalog.PREVIOUS[config['previous_price_cap_id']], key, data, finish=False)
                    for name in OLD_ARRAYS: np.testing.assert_array_equal(output[name], previous[name])
                    assert output['entry_support_input_SHA256'] == previous['entry_support_input_SHA256']
                    counts['旧全量局所null'] += 1
    assert counts['全20買売両商品'] == 80 and counts['旧全量局所null'] == 8

    # ----------------------------------------
    # 仮予約は実保有へ加えず、実fill後の追加だけがcohortと費用・停止線を更新する。
    for symbol in ('TOPIX', 'NK225'):
        for side in (-1, 1):
            config = configs['G1_Q1_X3']
            data = fixture(config, symbol, side)
            output = run(strategy, config, data)
            verify_cash(output, data, config)
            names = {name: i for i, name in enumerate(output['growth_state_columns'])}
            states = output['growth_state_trace']
            assert states[3, names['held_quantity']] == 1 and states[3, names['pending_quantity']] == 1
            assert states[4, names['held_quantity']] == 2 and states[4, names['pending_quantity']] == 0
            assert states[3, names['entry_cash']] == states[2, names['entry_cash']]
            assert states[3, names['entry_fees']] == states[2, names['entry_fees']]
            assert states[3, names['effective_stop']] != states[3, names['proposed_stop']]
            counts['実保有仮状態の分離'] += 1
            events = output['growth_events']
            additions = events[events[:, 1] == 2, 0].astype(int)
            fills = output['growth_cohorts'][:, 8].astype(int)
            assert not set(additions) & set(fills)
            counts['同fillrow禁止'] += 1
            assert len(output['trades']) == 1 and output['trades'][0, 11] > 0
            assert np.any(output['growth_cohorts'][:, 20] < 0)
            assert np.all(np.diff(states[states[:, names['held_quantity']] > 0, names['risk_budget']]) == 0)
            findings.append(dict(種類='親黒字でもcohortに赤字', 商品=symbol, 方向=side,
                親純額=float(output['trades'][0, 11]),
                cohort純額=output['growth_cohorts'][:, 20].tolist(),
                検算='親及び注文費用合計一致。金額80%の合格とは呼ばない。'))
            counts['active及びcohort隠れ損失'] += 1

            # 実追加fill行がpeer未知なら基準を無効化し、正常復帰行は基準のみとする。
            def unknown_peer(value: dict) -> None:
                """
                機能: 初回実fill行のpeerだけを不明にする。
                引数: value(dict)。
                返り値: None。正常自己quoteによる実fillを取り消さない。
                """
                value['signal']['entry_peer_bbo'][2, 5] = 0.
            fallback_data = fixture(config, symbol, side, change=unknown_peer)
            fallback = run(strategy, config, fallback_data)
            verify_cash(fallback, fallback_data, config)
            assert fallback['growth_state_trace'][2, names['anchor_valid']] == 0
            baseline = fallback['growth_events'][fallback['growth_events'][:, 1] == 5]
            assert len(baseline) and int(baseline[0, 0]) == 3
            assert not np.any((fallback['growth_events'][:, 0] == 3) & (fallback['growth_events'][:, 1] == 2))
            assert int(growth_entries(fallback)[1, 1]) > 3
            counts['未知peer復帰'] += 1

            # 予約後は当時の追加判断を取り消さず、現在normal自己気配で実fillする。
            for failure in ('peer', 'support', 'reset'):
                def deteriorate(value: dict) -> None:
                    """
                    機能: 既予約の追加fill行へ参加資格だけの悪化を与える。
                    引数: value(dict)。
                    返り値: None。実自己BBOは正常のまま。
                    """
                    if failure == 'peer': value['signal']['entry_peer_bbo'][4, 5] = 0.
                    elif failure == 'support': value['trend_lp_allowed'][side][4] = False
                    else: value['signal']['reset'][4] = True
                altered_data = fixture(config, symbol, side, change=deteriorate)
                altered = run(strategy, config, altered_data)
                verify_cash(altered, altered_data, config)
                assert growth_entries(altered)[1, 0] == 4 and growth_entries(altered)[1, 5] == 1
                counts['予約後資格悪化'] += 1

    # ----------------------------------------
    # 初回期限/静的forceは追加をfill前に取消し、entry_cutだけは既予約追加を取消さない。
    for side in (-1, 1):
        config = configs['G1_Q1_X1']
        for event_kind, times, limit, filled in (
            ('期限', [300., 301., 302., 303., 2102., 2103.], 10000., False),
            ('force', [300., 301., 302., 303., 604., 605.], 664., False),
            ('entrycut後の既予約', [300., 301., 302., 363., 364., 365.], 664., True)):
            def restrict(value: dict) -> None:
                """
                機能: 所定の既知運用区切りを私有入力へ設定する。
                引数: value(dict)。
                返り値: None。未来価格で閾値を選ばない。
                """
                value['record']['limit'] = limit
            data = fixture(config, 'TOPIX', side, ticks=[0., 1., 1., 5., 5., 5.], times=times, change=restrict)
            output = run(strategy, config, data)
            verify_cash(output, data, config)
            assert len(growth_entries(output)) == (2 if filled else 1)
            if not filled:
                assert np.any((output['growth_events'][:, 0] == 4) & (output['growth_events'][:, 1] == 4))
            else:
                assert growth_entries(output)[1, 0] == 4
            counts['初回期限と追加cut分離'] += 1

        # 合法予約の次normalは悪いquoteでも約定を残し、初停止も実fill後に判断する。
        def bad_fill(value: dict) -> None:
            """
            機能: 追加予約の次normalでspreadを広げて買高/売安の実約定を作る。
            引数: value(dict)。
            返り値: None。旧qokに上限spread条件を勝手に追加しない。
            """
            quote = 4000. + side * 10.
            if side == 1: value['record']['ask'][4] = quote
            else: value['record']['bid'][4] = quote
            value['record']['price'][4] = .5 * (value['record']['bid'][4] + value['record']['ask'][4])
        data = fixture(config, 'TOPIX', side, ticks=[0., 1., 1., 5., 5., 5.], change=bad_fill)
        output = run(strategy, config, data)
        verify_cash(output, data, config)
        assert len(growth_entries(output)) == 2 and growth_entries(output)[1, 0] == 4
        closing = output['orders'][output['orders'][:, 7] == 0]
        assert len(closing) == 1 and closing[0, 1] == 4 and closing[0, 0] == 5 and closing[0, 5] == 2
        assert -output['trades'][0, 11] > output['growth_parent_diagnostics'][0, 7]
        counts['実追加fill後即stop'] += 1

    # ----------------------------------------
    # helperは旧有効線/X3費用床を統合し、過去の未保有peakを現在grossへ代入しない。
    for side in (-1, 1):
        reflect = lambda price: price if side == 1 else 8000. - price
        cash = 4000. + 7. * 4010.5
        if side == -1: cash = 8. * 8000. - cash
        budget, protected, stop, active = strategy.ENGINE.growth_lines(side, 8, cash * 1000., 666., 4082.,
            reflect(3996.), reflect(4011.), 16., reflect(4008.5), True, reflect(4010.), 1, 4., 1000., .5, 1)
        assert budget == reflect(4009.) and protected == stop == reflect(4010.) and active
        assert side * (reflect(4010.) - budget) >= .5
        assert side * (reflect(4010.) - stop) < .5
        actual_cash = 4000. + 4006.5
        if side == -1: actual_cash = 2. * 8000. - actual_cash
        result = strategy.ENGINE.growth_lines(side, 2, actual_cash * 1000., 165., 4082.,
            reflect(3996.), reflect(4007.), 16., reflect(3996.), False, reflect(4006.), 1, 4., 1000., .5, 1)
        assert result[3] is False or result[3] == False
        counts['数理全線統合及び未保有peak'] += 1

    # ----------------------------------------
    # 途中の経済と実保有状態は未来に不変。cohortの後日net/返済欄は発注時情報へ戻さない。
    config = configs['G1_Q1_X3']
    whole_input = fixture(config, 'TOPIX', 1)
    whole = run(strategy, config, whole_input)
    key = next(iter(whole_input))
    for cut in (3, 4, 5, 6, 7, 9, 10):
        prefix_input = deepcopy(whole_input)
        for name, array in prefix_input[key]['record'].items():
            if isinstance(array, np.ndarray): prefix_input[key]['record'][name] = array[:cut].copy()
        for name in ('mapped', 'event', 'quality', 'reset'):
            prefix_input[key]['signal'][name] = prefix_input[key]['signal'][name][:cut].copy()
        prefix = run(strategy, config, prefix_input)
        poison_input = deepcopy(whole_input)
        poison_input[key]['record']['bid'][cut:] += 100.
        poison_input[key]['record']['ask'][cut:] += 100.
        poison_input[key]['signal']['entry_peer_bbo'][cut:, 3:5] += 1000.
        poison_input[key]['trend_lp_allowed'][1][cut:] = False
        poison = run(strategy, config, poison_input)
        for name in ('curve', 'source_curve', 'target_trace', 'watch_state_trace', 'entry_policy_state_trace',
                     'entry_cap_state_trace', 'growth_state_trace'):
            np.testing.assert_array_equal(prefix[name], whole[name][:cut])
            np.testing.assert_array_equal(poison[name][:cut], whole[name][:cut])
        for name in ('orders', 'events', 'entry_wait_events', 'entry_policy_events', 'growth_events'):
            expected = whole[name][whole[name][:, 0] < cut]
            np.testing.assert_array_equal(prefix[name], expected)
            np.testing.assert_array_equal(poison[name][poison[name][:, 0] < cut], expected)
        creation = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 21, 22, 23]
        expected = whole['growth_cohorts'][whole['growth_cohorts'][:, 8] < cut][:, creation]
        np.testing.assert_array_equal(prefix['growth_cohorts'][:, creation], expected)
        np.testing.assert_array_equal(poison['growth_cohorts'][poison['growth_cohorts'][:, 8] < cut][:, creation], expected)
        counts['人工prefix未来'] += 1
    assert before == {path.relative_to(ROOT).as_posix(): digest(path) for path in paths}
    result = dict(全合格=True, 種類='新しい101実装の損益前局所独立反証', 条件数=20, 主=catalog.PRIMARY,
        検査件数=counts, 数量と現金及びcohort説明=findings, 共有prepared及び設定非変更=True,
        現金scope='私有人工全20の注文/全cohort/親及び全行実保有E,Q,Fを独立計算。正式全原板時価は未認定。',
        状態scope='LP支持は方向別bool注入。実入力窓の生成と真受信順を認定しない。'
                  'prior返済と追加の両pendingは合法経路で同時成立させず、静的取消先行を別確認する。',
        未来scope='代理公開順仮定内の人工prefix/未来変形。cohort後日net/返済欄は閉鎖後診断で初回時点の情報ではない。',
        未保証='R0は理論線の全玉net予算で、成行約定の実損失限界ではない。収益性や未知期間の安定を認定しない。',
        SHA256=dict(before, **{Path(__file__).relative_to(ROOT).as_posix(): digest(Path(__file__))}),
        既存pure編集=0, 過去成果編集=0, 正式101損益閲覧=0, 正式101売買実行=0, API取得=0, 実注文=0)
    target = HERE / '新しい101実装反証_局所状態と現金及び未来.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('101局所の数量・現金・源・競合・追加fill悪化と人工未来不変が合格。新正式PL0。', flush=True)


if __name__ == '__main__':
    main()
