"""新正式損益を開かず支持計算と入力配線の局所境界を別々に反証する。"""

import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
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


def module(name: str, path: Path) -> object:
    """
    機能: mainや正式素材を開かず定義又は既存人工fixtureだけを取り込む。
    引数: name(str)、path(Path)。
    返り値: objectは読取モジュール。JIT保存と旧ファイル変更をしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def digest(path: Path) -> str:
    """
    機能: 実装と設計を現在の内容指紋へ結び付ける。
    引数: path(Path)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(value: object) -> str:
    """
    機能: private人工preparedの共有配列と設定が書き替わらないことを調べる。
    引数: value(object)。
    返り値: strはpickle内容指紋。
    """
    return hashlib.sha256(pickle.dumps(value, protocol=5)).hexdigest()


def decision(output: dict) -> int | None:
    """
    機能: 人工出力の最初の新規約定に対応する発注判断行を得る。
    引数: output(dict)。
    返り値: int|None。未約定を利益としない。
    """
    rows = output['orders'][output['orders'][:, 7] == 1]
    return int(rows[0, 1]) if len(rows) else None


def lp_oracle(price: dict, execution: dict, side: int) -> np.ndarray:
    """
    機能: L1支持を対象関数へ委譲せず両市場の価格資格と旧OFIから独立算出する。
    引数: price/execution(dict)、side(int:1/-1)。
    返り値: ndarray[bool]。未知OFIを支持又は追加拒否へ代用しない。
    """
    result = np.zeros(len(price['grid']), bool)
    for g in range(len(result)):
        returns, good = [], True
        for symbol in ('TOPIX', 'NK225'):
            market, book = price['markets'][symbol], execution['markets'][symbol]
            current, window, flow = market['current'], market['windows'][300], book['flow'][15]
            progress = side * window['ret_bp'][g]
            good &= bool(book['current']['valid'][g] and current['valid'][g]
                and np.isfinite(current['value'][g]) and current['value'][g] > 0
                and window['source_valid'][g] and np.isfinite(progress) and progress > 0)
            returns.append(progress)
            sufficient = bool(flow['source_valid'][g] and flow['valid'][g]
                and not flow['missing_ofi'][g] and flow['nonzero_ofi_count'][g] >= 3
                and np.isfinite(flow['ofi_ratio'][g]))
            good &= not (sufficient and side * flow['ofi_ratio'][g] <= -.1)
        good &= min(returns) >= .25 * max(returns)
        result[g] = bool(good)
    return result


def main() -> None:
    """
    機能: 初版確定後に少数の支持数理・配線・優先取消・人工prefixを検査する。
    引数: なし。新正式PLを読む又は再生する機能はない。
    返り値: None。自担当99review_preだけへ証跡を保存する。
    """
    paths = [BASE / name for name in ('engine.py', 'strategy.py', 'catalog.py', '結果前の設計案.json')]
    paths += [BASE / 'engine_preflight/support.py', ROOT / 'work/wave_v98/strategy.py',
        ROOT / 'work/wave_v97/review_pre/36仕様の局所状態境界と源及び共有入力の独立反証.py']
    before = {str(path.relative_to(ROOT)): digest(path) for path in paths}
    assert (BASE / 'engine.py').read_bytes() == (ROOT / 'work/wave_v98/engine.py').read_bytes()
    strategy = module('現在支持99局所配線の独立読取', BASE / 'strategy.py')
    old_strategy = module('旧98局所配線だけ読取99', ROOT / 'work/wave_v98/strategy.py')
    catalog = module('現在支持99局所固定定義', BASE / 'catalog.py')
    fixture = module('旧97短い状態機械人工だけ読取99',
        ROOT / 'work/wave_v97/review_pre/36仕様の局所状態境界と源及び共有入力の独立反証.py')
    helper = module('99明示人工素材だけ読取', BASE / 'engine_preflight/support.py')
    configs = {value['id']: value for value in catalog.catalog()}
    assert len(configs) == 34 and catalog.PRIMARY == 'L1_C1_A7_X3'
    columns = strategy.ENTRY_SUPPORT_COLUMNS
    assert len(columns) == 59
    old_arrays = ('orders', 'trades', 'curve', 'source_curve', 'target_trace', 'events', 'stats', 'slots',
        'range_state_trace', 'risk_state_trace', 'range_parent_diagnostics', 'price_source_trace',
        'loss_reentry_events', 'trend_exit_state_trace', 'trend_parent_diagnostics', 'watch_state_trace',
        'entry_parent_diagnostics', 'entry_wait_events', 'entry_policy_state_trace', 'entry_policy_events')
    evidence = []

    # ----------------------------------------
    # 価格素材から作る支持関数は独立oracleと比較し、配線の入力注入と区別する。
    material_cases = 0
    for side in (-1, 1):
        source_prepared = helper.prepared_fixture(configs['L1_C1_A1_X1'], 'complete', side)
        for key, value in source_prepared.items():
            material = value['artificial_support_material']
            price = material['trend_prices']['I3'][key[0]]
            execution = material['grids'][key[0]]
            for case in ('正常', '比率等号', '比率不足', '価格零', '価格窓不明', 'LP現在不明',
                         '旧執行不明', '十分な逆OFI', '未知OFI', 'OFI少数', 'OFI非有限'):
                p, q = deepcopy(price), deepcopy(execution)
                for symbol, ret in (('TOPIX', 8.), ('NK225', 2.)):
                    p['markets'][symbol]['current']['valid'][:] = True
                    p['markets'][symbol]['current']['value'][:] = 4000. if symbol == 'TOPIX' else 70000.
                    p['markets'][symbol]['windows'][300]['source_valid'][:] = True
                    p['markets'][symbol]['windows'][300]['ret_bp'][:] = side * ret
                    q['markets'][symbol]['current']['valid'][:] = True
                    flow = q['markets'][symbol]['flow'][15]
                    flow['source_valid'][:] = True; flow['valid'][:] = True
                    flow['missing_ofi'][:] = False; flow['nonzero_ofi_count'][:] = 4
                    flow['ofi_ratio'][:] = 0.
                market, book = p['markets']['NK225'], q['markets']['NK225']
                if case == '比率不足': market['windows'][300]['ret_bp'][:] = side * 1.999
                elif case == '価格零': market['windows'][300]['ret_bp'][:] = 0.
                elif case == '価格窓不明': market['windows'][300]['source_valid'][:] = False
                elif case == 'LP現在不明': market['current']['value'][:] = np.nan
                elif case == '旧執行不明': book['current']['valid'][:] = False
                elif case in ('十分な逆OFI', '未知OFI', 'OFI少数', 'OFI非有限'):
                    book['flow'][15]['ofi_ratio'][:] = -side * .1
                    if case == '未知OFI': book['flow'][15]['missing_ofi'][:] = True
                    elif case == 'OFI少数': book['flow'][15]['nonzero_ofi_count'][:] = 2
                    elif case == 'OFI非有限': book['flow'][15]['ofi_ratio'][:] = np.nan
                expected = lp_oracle(p, q, side)
                actual = strategy.lp_allowed(p, q)[side]
                np.testing.assert_array_equal(actual, expected)
                acceptable = case in ('正常', '比率等号', '未知OFI', 'OFI少数', 'OFI非有限')
                assert bool(expected.all()) == acceptable
                assert not lp_oracle(p, q, -side).any()
                material_cases += 1
    evidence.append(dict(種類='支持素材の独立数理', 正負モデル=material_cases,
        scope='資格・変位を直接与えた支持関数境界。原LP系列から窓を生成する独立原本監査とは別。'))

    def artificial(ident: str, side: int, values: list[float], times: list[float] | None = None,
                   old: list[bool] | None = None, lp: list[bool] | None = None,
                   change: object = None) -> dict:
        """
        機能: 短い旧状態機械fixtureへ独立した支持boolを注入して二列の接続を検査する。
        引数: ident(str)、side(int)、values/times(list[float]|None)、old/lp(list[bool]|None)、change(callable|None)。
        返り値: dictのprivate人工prepared。bool注入は価格源生成の正答とは呼ばない。
        """
        record, signal = fixture.fixture(configs[ident], side, values, times)
        n = len(signal['grid'])
        allowed = np.ones(n, bool) if old is None else np.asarray(old, bool)
        signal['entry_j2_long'] = allowed.copy()
        signal['entry_j2_short'] = allowed.copy()
        independent = np.ones(n, bool) if lp is None else np.asarray(lp, bool)
        basis = np.full((n, 59), np.nan)
        basis[:, 0] = np.arange(n); basis[:, 1] = signal['grid']
        value = dict(record=record, signal=signal, reference_open=4000.,
            trend_lp_allowed={1: independent.copy(), -1: independent.copy()}, entry_support_base=basis)
        if change is not None: change(record, signal)
        return {('2000-01-03_人工', 'TOPIX'): value}

    def play(ident: str, prepared: dict) -> dict:
        """
        機能: private人工の入力指紋を維持したまま指定laneの局所出力だけを得る。
        引数: ident(str)、prepared(dict)。
        返り値: dict。診断59の未設定源は未知のまま、bool入力を価格資格から救済しない。
        """
        key = next(iter(prepared))
        initial = fingerprint((prepared, configs[ident]))
        output = strategy.play(configs[ident], key, prepared, finish=False)
        assert fingerprint((prepared, configs[ident])) == initial
        seen = np.unique(prepared[key]['signal']['mapped'][prepared[key]['signal']['mapped'] >= 0])
        assert len(output['entry_support_state_trace']) == len(seen)
        np.testing.assert_array_equal(output['entry_support_state_trace'][:, 0], seen)
        assert output['entry_support_state_trace'].shape[1] == 59
        return output

    # ----------------------------------------
    # 旧と独立支持は互いの上位集合でなく、L1支持だけで新候補を生成しない。
    for side in (-1, 1):
        primary = artificial('L1_C1_A1_X1', side, [0., 1., 1.5, 2., 2.5],
            old=[False]*5, lp=[False, False, True, True, True])
        old = play('L0_C1_A1_X1', primary); new = play('L1_C1_A1_X1', primary)
        assert decision(old) is None and decision(new) == 2
        supported_old = artificial('L0_C1_A1_X1', side, [0., 1., 1.5, 2.], old=[True]*4, lp=[False]*4)
        assert decision(play('L0_C1_A1_X1', supported_old)) == 1
        assert decision(play('L1_C1_A1_X1', supported_old)) is None
        def no_event(record: dict, signal: dict) -> None:
            """
            機能: 支持だけが存在する状態を作り候補の新作を禁止する。
            引数: record/signal(dict)。
            返り値: None。
            """
            signal['event'][:] = 0
        absent = artificial('L1_C1_A1_X1', side, [0., 1., 1.5], change=no_event)
        assert decision(play('L1_C1_A1_X1', absent)) is None
        for label, ident in (('L0', 'L0_C1_A1_X1'), ('L1', 'L1_C1_A1_X1')):
            output = play(ident, primary)
            field = 'entry_j2_long' if side == 1 else 'entry_j2_short'
            expected = primary[next(iter(primary))]['signal'][field] if label == 'L0' else \
                primary[next(iter(primary))]['trend_lp_allowed'][side]
            assert output['entry_support_input_SHA256'][field] == hashlib.sha256(expected.tobytes()).hexdigest()
        evidence.append(dict(方向=side, L1のみ受理=True, L0のみ受理=True, 支持だけで候補生成なし=True,
            scope='支持bool注入の配線境界。追加経済成績又は原本源生成の証明ではない。'))

    def hard_cancel(record: dict, signal: dict) -> None:
        """
        機能: 発注可能行の旧硬い反対をTrueへ置く。
        引数: record/signal(dict)。
        返り値: None。新LP支持で取消が無効にならないか確認する。
        """
        signal['wait_opposite_long'][1] = True
    conflict = artificial('L1_C1_A1_X1', 1, [0., 1., 1.5, 2.], change=hard_cancel)
    result = play('L1_C1_A1_X1', conflict)
    assert decision(result) is None
    assert np.any((result['entry_wait_events'][:, 1] == 3) & (result['entry_wait_events'][:, 2] == 6))
    for policy in ('C0', 'C1', 'C2', 'C3'):
        for fault, reason in (('reset', 4), ('quote_valid', 5)):
            def fail(record: dict, signal: dict) -> None:
                """
                機能: 新LP支持が存在する行へ旧故障を与える。
                引数: record/signal(dict)。
                返り値: None。自己qok/resetは現支持から分離する。
                """
                target = signal if fault == 'reset' else record
                target[fault][1] = True if fault == 'reset' else False
            ident = 'L1_' + policy + '_A1_X1'
            value = play(ident, artificial(ident, 1, [0., 1., 1.5], change=fail))
            assert decision(value) is None
            assert np.any((value['entry_wait_events'][:, 1] == 3) & (value['entry_wait_events'][:, 2] == reason))
    evidence.append(dict(旧硬い反対優先=True, 四時計政策のreset及びqok取消優先=True))

    # C3は支持差によって再準備時刻が変わり、入口だけの変更とは説明できない。
    phase = artificial('L1_C3_A7_X3', 1, [0., 12., 8., 6., 1., 4., 0., 2., 2.5],
        [300., 301., 320., 321., 322., 323., 324., 325., 326.],
        old=[True, True, True, False, False, True, True, True, True], lp=[True]*9)
    legacy = play('L0_C3_A7_X3', phase); current = play('L1_C3_A7_X3', phase)
    legacy_reprepare = legacy['entry_policy_events'][legacy['entry_policy_events'][:, 1] == 4, 0]
    current_reprepare = current['entry_policy_events'][current['entry_policy_events'][:, 1] == 4, 0]
    np.testing.assert_array_equal(legacy_reprepare, [5.]); np.testing.assert_array_equal(current_reprepare, [3.])
    assert decision(legacy) == 7 and decision(current) == 5
    assert current['watch_state_trace'][3, 8] == legacy['watch_state_trace'][5, 8] == 600.
    evidence.append(dict(C3の支持差は再準備にも作用=True, L0再準備行=5, L1再準備行=3,
        L0発注行=7, L1発注行=5, 元期限保持=True, 再準備同行発注なし=True))

    nulls = 0
    for ident, config in configs.items():
        if config['entry_support_lane'] != 'L0': continue
        for side in (-1, 1):
            prepared = artificial(ident, side, [0., 12., 8., 10., 10.5], [300., 301., 320., 321., 322.])
            key = next(iter(prepared))
            value = play(ident, prepared)
            old = old_strategy.play(catalog.PREVIOUS[config['previous_clock_id']], key, prepared, finish=False)
            for name in old_arrays: np.testing.assert_array_equal(value[name], old[name])
            nulls += 1
    assert nulls == 36
    evidence.append(dict(L0及びA0の旧20配列完全一致人工=nulls))

    prefixes = 0
    for policy in ('C1', 'C2', 'C3'):
        ident = 'L1_' + policy + '_A7_X3'
        whole_input = artificial(ident, 1, [0., 12., 8., 6., 9., 5., 7., 7.5, 8.],
            [300., 301., 320., 321., 322., 323., 324., 325., 326.])
        whole = play(ident, whole_input); key = next(iter(whole_input))
        for cut in (2, 3, 4, 6, 7, 8):
            prefix_input = deepcopy(whole_input)
            for name, array in prefix_input[key]['record'].items():
                if isinstance(array, np.ndarray): prefix_input[key]['record'][name] = array[:cut].copy()
            for name in ('mapped', 'event', 'quality', 'reset'):
                prefix_input[key]['signal'][name] = prefix_input[key]['signal'][name][:cut].copy()
            prefix = play(ident, prefix_input)
            poison = deepcopy(whole_input)
            poison[key]['record']['bid'][cut:] += 100.; poison[key]['record']['ask'][cut:] += 100.
            poison[key]['signal']['entry_peer_bbo'][cut:, 3:5] += 1000.
            poison[key]['trend_lp_allowed'][1][cut:] = False
            poison[key]['entry_support_base'][cut:, 11:] = 987654.
            altered = play(ident, poison)
            for name in ('curve', 'target_trace', 'watch_state_trace', 'entry_policy_state_trace'):
                np.testing.assert_array_equal(prefix[name], whole[name][:cut])
                np.testing.assert_array_equal(altered[name][:cut], whole[name][:cut])
            for name in ('orders', 'events', 'entry_wait_events', 'entry_policy_events'):
                expected = whole[name][whole[name][:, 0] < cut]
                np.testing.assert_array_equal(prefix[name], expected)
                np.testing.assert_array_equal(altered[name][altered[name][:, 0] < cut], expected)
            expected_support = whole['entry_support_state_trace'][whole['entry_support_state_trace'][:, 0] < cut]
            np.testing.assert_array_equal(prefix['entry_support_state_trace'], expected_support)
            np.testing.assert_array_equal(altered['entry_support_state_trace'][altered['entry_support_state_trace'][:, 0] < cut], expected_support)
            prefixes += 1
    assert prefixes == 18
    evidence.append(dict(人工自己及びpeer未来改変及び接頭切断=prefixes,
        支持59は公表gridだけ=True, 全grid入力SHAは未来入力変更で変わり得る=True))
    for path in HERE.glob('*.py'): ast.parse(path.read_text(encoding='utf-8'))
    assert before == {str(path.relative_to(ROOT)): digest(path) for path in paths}
    target = HERE / '34現在支持の局所配線と非包摂及び未来不変の独立反証.json'
    target.write_text(json.dumps(dict(全合格=True, 種類='損益前の人工局所独立反証', 条件数=34,
        主=catalog.PRIMARY, 必要反証=evidence, 支持計算の独立正負モデル=material_cases,
        L0旧20配列人工=nulls, 人工接頭及び未来変形=prefixes, 共有入力非変更=True,
        経済本体98byte完全一致=True, コードSHA256=before,
        計算コードSHA256=digest(Path(__file__)),
        期待値SHA256=digest(HERE / '34現在支持源の独立仕様反証と局所人工の事前期待値.json'),
        scope='支持計算は独立数理oracle、状態機械配線はbool注入人工。59列の全原本値と全行の生成過程は別の独立監査。',
        未保証='今回の再生clockはCurrentPriceTime由来。真受信時計及び二市場の共通受信順は未観測。未来不変は代理公開順内。',
        新正式損益閲覧=0, 新正式売買実行=0, API取得=0, 実注文=0, 旧固定編集=0),
        ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('34現在支持の局所配線・旧20配列null・人工未来不変を独立確認。新正式PL0。', flush=True)


if __name__ == '__main__':
    main()
