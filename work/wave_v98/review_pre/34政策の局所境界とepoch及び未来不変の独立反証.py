"""正常gapと別epochの少数反例を人工で検査し、新正式損益を開かない。"""

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
OLD = ROOT / 'work/wave_v97'


def module(name: str, path: Path) -> object:
    """
    機能: 検査対象又は旧人工素材をmainなしで読みJIT保存を避ける。
    引数: name(str)、path(Path)。
    返り値: objectは読取モジュール。正式入力と損益は開かない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def fingerprint(value: object) -> str:
    """
    機能: 人工配列と設定の共有参照が変更されないことを検査する。
    引数: value(object)。
    返り値: strはpickle指紋。
    """
    return hashlib.sha256(pickle.dumps(value, protocol=5)).hexdigest()


def digest(path: Path) -> str:
    """
    機能: 読取コードと設計を実行時の指紋へ結び付ける。
    引数: path(Path)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def first_decision(output: dict) -> int | None:
    """
    機能: 最初の人工新規約定から実発注判断行を取り出す。
    引数: output(dict)。
    返り値: int|None。未約定を利益又は成功に数えない。
    """
    orders = output['orders'][output['orders'][:, 7] == 1]
    return int(orders[0, 1]) if len(orders) else None


def rows_for(output: dict, code: int) -> list[int]:
    """
    機能: 新policy診断の特定イベント行を独立に取り出す。
    引数: output(dict)、code(int)。
    返り値: list[int]は保存された原行番号。
    """
    rows = output['entry_policy_events']
    return [int(value) for value in rows[rows[:, 1] == code, 0]]


def main() -> None:
    """
    機能: 34政策の必要局所境界、C0旧null、未来切断と入力非変更を人工検査する。
    引数: なし。本体初版完成後だけ使用する。
    返り値: None。独立証跡をreview_preへ保存し、新正式再生/APIは呼ばない。
    """
    source_paths = [BASE / 'engine.py', BASE / 'strategy.py', BASE / 'catalog.py', BASE / '結果前の設計案.json']
    before_sources = {str(path.relative_to(ROOT)): digest(path) for path in source_paths}
    engine = module('時計政策98の局所独立人工', BASE / 'engine.py')
    old_engine = module('時計政策98から旧97の局所読取', OLD / 'engine.py')
    catalog = module('時計政策98の局所条件読取', BASE / 'catalog.py')
    fixture_module = module('旧97の修正済み局所人工だけ読取98',
        OLD / 'review_pre/36仕様の局所状態境界と源及び共有入力の独立反証.py')
    configs = {value['id']: value for value in catalog.catalog()}
    assert len(configs) == 34 and catalog.PRIMARY == 'C1_A7_X3'
    evidence = []

    def run(ident: str, side: int, values: list[float], times: list[float] | None = None,
            change: object = None) -> dict:
        """
        機能: 当該局所境界の人工だけを実行し共有入力非変更を照合する。
        引数: ident(str)、side(int)、values/times(list[float]|None)、change(callable|None)。
        返り値: dictは人工出力。保存実板・正式損益を読まない。
        """
        record, signal = fixture_module.fixture(configs[ident], side, values, times)
        if change is not None:
            change(record, signal)
        before = fingerprint((record, signal, configs[ident]))
        output = engine.execute(record, signal, configs[ident], finish=False)
        assert fingerprint((record, signal, configs[ident])) == before
        return output

    # ----------------------------------------
    # 正常gap行の条件成立と二市場時計の等号を買売反射で確認する。
    for side in (-1, 1):
        c0 = run('C0_A3_X1', side, [0., 6., 6.5], [300., 320., 321.])
        c1 = run('C1_A3_X1', side, [0., 6., 6.5], [300., 320., 321.])
        assert first_decision(c0) is None and first_decision(c1) == 1
        assert c1['orders'][0, 0] == 2 and rows_for(c1, 1) == [1]
        assert int(c1['watch_state_trace'][1, 48]) & 4 == 0
        def phase_equal(record: dict, signal: dict) -> None:
            """
            機能: 公表済みpeerの最初の新時計を自己phaseと等しくする。
            引数: record/signal(dict)。
            返り値: None。未来peer又は同時計末尾は使わない。
            """
            signal['entry_peer_bbo'][:, 2] = np.array([299.75, 300., 301., 302.])
        ordinary = run('C1_A1_X1', side, [0., 1., 1.5, 2.], change=phase_equal)
        relative = run('C2_A1_X1', side, [0., 1., 1.5, 2.], change=phase_equal)
        assert first_decision(ordinary) == 2 and first_decision(relative) == 1
        def accepted_after_gap(record: dict, signal: dict) -> None:
            """
            機能: 最初の候補を正常gap行へ置く。
            引数: record/signal(dict)。
            返り値: None。受理のgap行禁止が追加されないか確認する。
            """
            signal['event'][:] = 0; signal['event'][1] = side
        accepted = run('C1_A1_X1', side, [0., 0., 1., 1.5],
            [300., 320., 321., 322.], accepted_after_gap)
        assert accepted['watch_state_trace'][1, 0] == 1 and first_decision(accepted) == 2
        assert not np.any(accepted['entry_wait_events'][:, 1] == 3)
        evidence.append(dict(方向=side, C1正常gap行発注=True, C1gap行候補受理=True,
            C2共通phaseでなく各anchor基準=True))

    def unknown_first(record: dict, signal: dict) -> None:
        """
        機能: 候補peerだけ不明、正常復帰の時計は自己phaseと同値にする。
        引数: record/signal(dict)。
        返り値: None。最初正常pairは基準だけであることを確認する。
        """
        signal['entry_peer_bbo'][0, 5] = 0.
        signal['entry_peer_bbo'][:, 2] = np.array([299.75, 300., 301., 302., 303.])
    fallback = run('C2_A3_X1', 1, [0., 4., 4.5, 5., 5.5], change=unknown_first)
    assert first_decision(fallback) == 2
    assert list(fallback['entry_wait_events'][fallback['entry_wait_events'][:, 1] == 7, 0]) == [1.]
    def same_clock(record: dict, signal: dict) -> None:
        """
        機能: 同自己時計の二行を同じpeer格子源へ写し真の新peerを捏造しない。
        引数: record/signal(dict)。
        返り値: None。自己seqだけの更新で発注できるとは仮定しない。
        """
        signal['grid'] = np.array([300., 301., 302.])
        signal['mapped'] = np.array([0, 0, 1, 2], np.int64)
        signal['entry_peer_bbo'] = signal['entry_peer_bbo'][[0, 2, 3]].copy()
        for field in ('entry_j2_long', 'entry_j2_short', 'wait_opposite_long', 'wait_opposite_short'):
            signal[field] = signal[field][[0, 2, 3]].copy()
    same = run('C2_A1_X1', 1, [0., 1., 1.5, 2.], [300., 300., 301., 302.], same_clock)
    assert first_decision(same) == 2
    def future_peer(record: dict, signal: dict) -> None:
        """
        機能: 自己現在時計より後のpeer時計を置く。
        引数: record/signal(dict)。
        返り値: None。seq進行があっても未来peerを使わせない。
        """
        signal['entry_peer_bbo'][1:, 2] = record['time_s'][1:] + 1.
    future = run('C2_A3_X1', 1, [0., 4., 4.5, 5.], change=future_peer)
    assert first_decision(future) is None
    evidence.append(dict(C2fallback最初行発注なし=True, 自己sameClockではpeer源固定=True, 未来peer拒否=True))

    # ----------------------------------------
    # C3は旧resetを救済せずgapだけのepochを経て幾何を再準備する。
    for side in (-1, 1):
        rearm = run('C3_A7_X3', side, [0., 12., 8., 6., 9., 5., 7., 7.5],
            [300., 301., 320., 321., 322., 323., 324., 325.])
        assert rows_for(rearm, 2) == [2] and rows_for(rearm, 4) == [3]
        assert first_decision(rearm) == 6 and rearm['orders'][0, 0] == 7
        columns = {name: i for i, name in enumerate(rearm['watch_state_columns'])}
        assert rearm['watch_state_trace'][2, columns['favorable_peak']] == 4000. + side * 12.
        assert rearm['watch_state_trace'][3, columns['favorable_peak']] == 4000. + side * 6.
        assert rearm['watch_state_trace'][3, columns['opposite_extreme']] == 4000. + side * 6.
        assert rearm['watch_state_trace'][3, columns['phase']] == 1
        assert rearm['watch_state_trace'][3, columns['phase_row']] == 3
        assert rearm['target_trace'][:6, 4].max() == 8 and rearm['target_trace'][:6, :2].max() == 0
        assert rearm['target_trace'][6, 4] == 8 and rearm['target_trace'].max() == 8
        original = run('C3_A3_X1', side, [0., 6., 6.5, 7., 7.5], [300., 320., 321., 322., 323.])
        assert rows_for(original, 4) == [2] and first_decision(original) == 3
        assert original['entry_parent_diagnostics'][0, 5] == 4000.
        assert original['watch_state_trace'][2, columns['candidate_quote']] == 4000.
        evidence.append(dict(方向=side, gap行幾何凍結=True, 再準備に方向quote進行は不要=True,
            A7arm解除と新peak極値=True, A3元quote保持=True, 再準備同行発注なし=True, 枠二重なし=True))
    def epoch_unknown(record: dict, signal: dict) -> None:
        """
        機能: gap行のpeerを不明にし、次のpeer時計をepochと同値にする。
        引数: record/signal(dict)。
        返り値: None。未知epoch基準と再準備を別の原行にする。
        """
        signal['entry_peer_bbo'][1, 5] = 0.
        signal['entry_peer_bbo'][2, 2] = 320.
    unknown = run('C3_A1_X1', 1, [0., 6., 6., 6., 6., 7., 7.5],
        [300., 320., 321., 322., 323., 324., 325.], epoch_unknown)
    assert rows_for(unknown, 3) == [3] and rows_for(unknown, 4) == [4]
    assert first_decision(unknown) == 5
    def quality_pause(record: dict, signal: dict) -> None:
        """
        機能: 最初のepoch後一行だけqualityを落として再準備を遅らせる。
        引数: record/signal(dict)。
        返り値: None。追加gapでも元期限を延ばさない。
        """
        signal['quality'][2] = False
    repeated = run('C3_A3_X1', 1, [0., 6., 6.5, 7., 7.5, 8., 8.5],
        [300., 320., 321., 340., 341., 342., 343.], quality_pause)
    assert rows_for(repeated, 2) == [1, 3] and rows_for(repeated, 4) == [4]
    assert first_decision(repeated) == 5
    assert repeated['watch_state_trace'][4, 8] == 600.
    evidence.append(dict(C3未知epoch正常基準行と再準備行を分離=True, 追加gapで期限非延長=True))

    # mandatory取消と旧側優先を維持し、rawseqに独自の取消を足さない。
    for policy in ('C0', 'C1', 'C2', 'C3'):
        def expiry_pulse(record: dict, signal: dict) -> None:
            """
            機能: TTL到達行へ新しい反対候補を置く。
            引数: record/signal(dict)。
            返り値: None。行頭watch占有による候補消費を確認する。
            """
            signal['event'][2] = -1
        expiry = run(policy + '_A3_X1', 1, [0., 0., 6., 6.5], [300., 301., 600., 601.], expiry_pulse)
        assert first_decision(expiry) is None
        assert np.any((expiry['entry_wait_events'][:, 1] == 3) & (expiry['entry_wait_events'][:, 2] == 2))
        assert np.any((expiry['entry_wait_events'][:, 1] == 2) & (expiry['entry_wait_events'][:, 2] == 7))
        assert not rows_for(expiry, 2) and not rows_for(expiry, 4)
        for fault, expected in (('reset', 4), ('quote_valid', 5)):
            def broken(record: dict, signal: dict) -> None:
                """
                機能: gap行に旧reset又は自己qok不正を加える。
                引数: record/signal(dict)。
                返り値: None。C3を価格故障修復へ拡大しない。
                """
                if fault == 'reset':
                    signal['reset'][1] = True
                else:
                    record['quote_valid'][1] = False
            bad = run(policy + '_A3_X1', 1, [0., 6., 6.5], [300., 320., 321.], broken)
            wanted = 3 if policy == 'C0' else expected
            assert first_decision(bad) is None
            assert np.any((bad['entry_wait_events'][:, 1] == 3) & (bad['entry_wait_events'][:, 2] == wanted))
            assert not rows_for(bad, 2)
        def sequence_gap(record: dict, signal: dict) -> None:
            """
            機能: 人工の原seqだけ欠番にし旧reset旗は与えられたままとする。
            引数: record/signal(dict)。
            返り値: None。上流品質救済ではなく新cancelを足さない局所反証。
            """
            record['seq'][1:] += 1
        seq_only = run(policy + '_A3_X1', 1, [0., 4., 4.5], change=sequence_gap)
        assert first_decision(seq_only) == 1
    evidence.append(dict(TTLとgap同時は取消先行=True, 解除同行候補消費=True,
        C0旧gap取消優先=True, C1以降resetとqok取消保持=True, 新seq欠番cancelなし=True))

    # ----------------------------------------
    # 旧18出力のnullと、過去状態・注文が未来の入力から変わらないことを確認する。
    old_names = ('orders', 'trades', 'curve', 'source_curve', 'target_trace', 'events', 'stats', 'slots',
        'range_state_trace', 'risk_state_trace', 'range_parent_diagnostics', 'price_source_trace',
        'loss_reentry_events', 'trend_exit_state_trace', 'trend_parent_diagnostics', 'watch_state_trace',
        'entry_parent_diagnostics', 'entry_wait_events')
    null_count = 0
    for ident, config in configs.items():
        if config['entry_clock_policy'] != 'C0':
            continue
        for side in (-1, 1):
            record, signal = fixture_module.fixture(config, side, [0., 12., 8., 10., 10.5],
                [300., 301., 320., 321., 322.])
            value = engine.execute(record, signal, config, finish=False)
            old = old_engine.execute(record, signal, catalog.PREVIOUS[config['previous_id']], finish=False)
            for name in old_names:
                np.testing.assert_array_equal(value[name], old[name])
            null_count += 1
    prefix_count = 0
    for policy in ('C1', 'C2', 'C3'):
        ident = policy + '_A7_X3'
        record, signal = fixture_module.fixture(configs[ident], 1,
            [0., 12., 8., 6., 9., 5., 7., 7.5, 8.], [300., 301., 320., 321., 322., 323., 324., 325., 326.])
        whole = engine.execute(record, signal, configs[ident], finish=False)
        for cut in (2, 3, 4, 6, 7, 8):
            part = {k: (v[:cut].copy() if isinstance(v, np.ndarray) else v) for k, v in record.items()}
            sig = {k: (v[:cut].copy() if isinstance(v, np.ndarray) else v) for k, v in signal.items()}
            truncated = engine.execute(part, sig, configs[ident], finish=False)
            poison = deepcopy(record); poison['bid'][cut:] += 100.; poison['ask'][cut:] += 100.
            poison['price'][cut:] += 100.
            altered = deepcopy(signal); altered['entry_peer_bbo'][cut:, 3:5] += 1000.
            changed = engine.execute(poison, altered, configs[ident], finish=False)
            for name in ('curve', 'target_trace', 'watch_state_trace', 'entry_policy_state_trace'):
                np.testing.assert_array_equal(truncated[name], whole[name][:cut])
                np.testing.assert_array_equal(changed[name][:cut], whole[name][:cut])
            for name in ('orders', 'events', 'entry_wait_events', 'entry_policy_events'):
                expected = whole[name][whole[name][:, 0] < cut]
                np.testing.assert_array_equal(truncated[name], expected)
                np.testing.assert_array_equal(changed[name][changed[name][:, 0] < cut], expected)
            prefix_count += 1
    tree = ast.parse((BASE / 'engine.py').read_text(encoding='utf-8'))
    body = next(value for value in tree.body if isinstance(value, ast.FunctionDef) and value.name == 'simulate')
    params = {arg.arg for arg in body.args.args}
    violations = []
    for node in ast.walk(body):
        if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store):
            target = node.value
            while isinstance(target, ast.Subscript):
                target = target.value
            if isinstance(target, ast.Name) and target.id in params:
                violations.append(target.id)
    assert not violations
    after_sources = {str(path.relative_to(ROOT)): digest(path) for path in source_paths}
    assert after_sources == before_sources, '検査中に本体変更があった場合は指紋を確定して再実行してください'
    path = HERE / '34政策の局所境界とepoch及び未来不変の独立反証.json'
    path.write_text(json.dumps(dict(全合格=True, 種類='人工だけの局所独立検査', 条件数=34,
        主=catalog.PRIMARY, 必要境界=evidence, 旧18配列null人工=null_count,
        prefix及び未来変形=prefix_count, 共有入力非変更=True, simulate配列引数Storeなし=True,
        コードSHA256=before_sources, 計算コードSHA256=digest(Path(__file__)),
        期待値SHA256=digest(HERE / '34指定仕様の独立反証と局所人工の事前期待値.json'),
        未保証='真受信時計と二市場の実受信因果順は未観測。旧proxy asofを維持した計算上の検査。',
        新正式損益閲覧=0, 新正式売買実行=0, API取得=0, 実注文=0, 旧固定編集=0),
        ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('34政策の局所境界・旧18配列null・未来不変が人工だけで合格。正式PLは0。', flush=True)


if __name__ == '__main__':
    main()
