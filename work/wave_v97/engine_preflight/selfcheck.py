"""待機入口の人工境界、PythonとJIT、旧即時入口の全15台帳を照合する。"""

import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from support import HERE, ROOT, WORK, fixture, load


OLD_NAMES = ('orders', 'trades', 'curve', 'source_curve', 'target_trace', 'events', 'stats', 'slots',
             'range_state_trace', 'risk_state_trace', 'range_parent_diagnostics', 'price_source_trace',
             'loss_reentry_events', 'trend_exit_state_trace', 'trend_parent_diagnostics')
NEW_NAMES = ('watch_state_trace', 'entry_parent_diagnostics', 'entry_wait_events')


def immutable(left: object, right: object) -> None:
    """
    機能: 共通preparedの配列及び辞書が実行で変化しないことを確認する。
    引数: left/right(object)は実行前後の同じ構造。
    返り値: None。共有入力変更が一つでもあれば失敗する。
    """
    if isinstance(left, dict):
        assert left.keys() == right.keys()
        for key in left:
            immutable(left[key], right[key])
    elif isinstance(left, np.ndarray):
        np.testing.assert_array_equal(left, right)
    else:
        assert left == right


def execute(strategy: object, config: dict, symbol: str, side: int, profile: str,
            mutate: object = None, python: bool = False) -> tuple[dict, dict]:
    """
    機能: 人工原板だけを実行し、共通入力の不変性と診断の実約定対応を確認する。
    引数: strategy(object)、config(dict)、symbol/profile(str)、side(int)、mutate(callable又はNone)、python(bool)。
    返り値: tuple[dict,dict]は出力と人工prepared。正式損益を保存しない。
    """
    record, signal, opening = fixture(symbol, side, profile)
    if mutate is not None:
        mutate(record, signal)
    key = ('2000-01-03_人工', symbol)
    prepared = {key: dict(record=record, signal=signal, reference_open=opening)}
    before = copy.deepcopy(prepared)
    compiled = strategy.ENGINE.simulate
    try:
        if python:
            strategy.ENGINE.simulate = compiled.py_func
        output = strategy.play(config, key, prepared)
    finally:
        strategy.ENGINE.simulate = compiled
    immutable(before, prepared)
    trace = output['target_trace']
    cap = 10 if symbol == 'TOPIX' else 20
    assert (trace[:, 2:4] <= cap).all()
    for parent in output['entry_parent_diagnostics']:
        orders = output['orders'][output['orders'][:, 2] == parent[0]]
        entry = orders[orders[:, 7] == 1]
        if parent[41] == 1:
            assert len(entry) == 1
            assert parent[37] == entry[0, 0] > parent[28]
            assert parent[39] == entry[0, 11] and parent[40] == entry[0, 6]
        if np.isfinite(parent[42]):
            trade = output['trades'][output['trades'][:, 0] == parent[0]]
            assert len(trade) == 1 and parent[43] == trade[0, 11]
    return output, prepared


def reservations(output: dict) -> list[int]:
    """
    機能: 新しい入口診断から市場予約の判断原行だけを抽出する。
    引数: output(dict)。
    返り値: list[int]はtrigger原行。実fillの原行と混同しない。
    """
    return [int(row) for row in output['entry_parent_diagnostics'][:, 28]]


def main() -> None:
    """
    機能: 36対照の買売と少数反例を確認し、現コード指紋付き証跡を保存する。
    引数: なし。
    返り値: None。正式97の全期間損益及びAPIは実行しない。
    """
    strategy = load('待機入口の人工自己検査97', WORK / 'strategy.py')
    catalog = load('待機36の人工読取97', WORK / 'catalog.py')
    configs = {value['id']: value for value in catalog.catalog()}
    results = []
    for symbol in ('TOPIX', 'NK225'):
        for side in (1, -1):
            for config in configs.values():
                output, _ = execute(strategy, config, symbol, side, 'complete')
                assert len(output['trades']) >= 1, config['id']
                results.append(dict(商品=symbol, 方向=side, 条件=config['id'], 予約原行=reservations(output)))
    print('36条件×両商品×買売の人工144経路が完了', flush=True)

    py_count = 0
    for entry in (0, 2, 6, 7):
        for symbol, side in (('TOPIX', 1), ('NK225', -1)):
            config = configs[f'A{entry}_X3']
            py, _ = execute(strategy, config, symbol, side, 'complete', python=True)
            jit, _ = execute(strategy, config, symbol, side, 'complete')
            for name in OLD_NAMES + NEW_NAMES:
                np.testing.assert_array_equal(py[name], jit[name])
            py_count += 1
    print('Python/JITの8人工×18配列が同値', flush=True)

    old = load('旧96即時の人工対照97', WORK.parent / 'wave_v96/strategy.py')
    nulls = 0
    for exit_index in range(4):
        for symbol in ('TOPIX', 'NK225'):
            for side in (1, -1):
                config = configs[f'A0_X{exit_index}']
                actual, prepared = execute(strategy, config, symbol, side, 'complete')
                key = next(iter(prepared))
                compiled = old.ENGINE.simulate
                try:
                    old.ENGINE.simulate = compiled.py_func
                    expected = old.play(config, key, prepared)
                finally:
                    old.ENGINE.simulate = compiled
                for name in OLD_NAMES:
                    np.testing.assert_array_equal(expected[name], actual[name])
                nulls += 1
    print('A0の4出口×両商品×買売は旧96全15台帳と同値', flush=True)

    checks = []
    for symbol in ('TOPIX', 'NK225'):
        for side in (1, -1):
            def stagnant(record: dict, signal: dict) -> None:
                """
                機能: 相手時計と源は更新するが両気配の価格を固定する。
                引数: record/signal(dict)。
                返り値: Noneは人工信号の変更。
                """
                signal['entry_peer_bbo'][:, 3:5] = signal['entry_peer_bbo'][0, 3:5]
            a2, _ = execute(strategy, configs['A2_X3'], symbol, side, 'direct', stagnant)
            a3, _ = execute(strategy, configs['A3_X3'], symbol, side, 'direct', stagnant)
            assert reservations(a2) and not reservations(a3)
            a5, _ = execute(strategy, configs['A5_X3'], symbol, side, 'direct')
            a6, _ = execute(strategy, configs['A6_X3'], symbol, side, 'direct')
            assert reservations(a5) and not reservations(a6)

            def unknown(record: dict, signal: dict) -> None:
                """
                機能: 最初の相手正常ペアを345秒に限定する。
                引数: record/signal(dict)。
                返り値: Noneは人工信号の変更。
                """
                signal['entry_peer_bbo'][signal['grid'] < 345., 5] = 0.
            a2, _ = execute(strategy, configs['A2_X3'], symbol, side, 'direct', unknown)
            a3, _ = execute(strategy, configs['A3_X3'], symbol, side, 'direct', unknown)
            assert reservations(a2) == [345] and reservations(a3)[0] > 345
            baseline = a3['entry_wait_events'][a3['entry_wait_events'][:, 1] == 7]
            assert len(baseline) == 1 and baseline[0, 0] == 345

            def future(record: dict, signal: dict) -> None:
                """
                機能: 公表相手の時計を未来へ改変して正常ペアを拒絶させる。
                引数: record/signal(dict)。
                返り値: Noneは人工信号の変更。
                """
                signal['entry_peer_bbo'][:, 2] += 2000.
            failed, _ = execute(strategy, configs['A2_X3'], symbol, side, 'direct', future)
            assert not reservations(failed)

            def paused(record: dict, signal: dict) -> None:
                """
                機能: resetのない品質不良を340〜349秒に置いて注文だけを停止する。
                引数: record/signal(dict)。
                返り値: Noneは人工信号の変更。
                """
                signal['quality'][340:350] = False
            paused_output, _ = execute(strategy, configs['A2_X3'], symbol, side, 'direct', paused)
            assert reservations(paused_output) == [350]
            assert not (paused_output['entry_wait_events'][:, 1] == 3).any()

            def ttl(record: dict, signal: dict) -> None:
                """
                機能: TTL取消と同じ行に新候補を置き、同一行の復活を拒絶する。
                引数: record/signal(dict)。
                返り値: Noneは人工信号の変更。
                """
                signal['event'][630] = side
            expired, _ = execute(strategy, configs['A3_X3'], symbol, side, 'flat', ttl)
            events = expired['entry_wait_events']
            assert not reservations(expired)
            assert ((events[:, 0] == 630) & (events[:, 1] == 3) & (events[:, 2] == 2)).any()
            assert ((events[:, 0] == 630) & (events[:, 1] == 2) & (events[:, 2] == 7)).any()
            trace = expired['target_trace']
            quantity = 8 if symbol == 'TOPIX' else 16
            assert trace[330, 2 if side == 1 else 3] == quantity and trace[330, 4] == quantity
            assert trace[330, 0] == trace[330, 1] == 0
            assert trace[630, 2] == trace[630, 3] == trace[630, 4] == 0
            checks.append(dict(商品=symbol, 方向=side, A2相手価格不進行でも可=True,
                A3相手価格不進行は不可=True, A5直接進行可A6押し未達不可=True,
                A2初正常同行可BBO確認群は基準のみ=True, 未来相手拒絶=True,
                品質単独は発注停止だけ=True, TTL等号取消と同行候補消費=True,
                待機は保有外の占有予約=True))

    # ----------------------------------------
    # 不足した待機素材を正常な相手進行へ変換しない。
    invalid_inputs = 0
    for field, replacement in (('peer_tick', 0.), ('peer_tick', np.nan),
        ('entry_j2_long', np.ones(2, bool)), ('entry_j2_short', np.ones(161, np.int8)),
        ('wait_opposite_long', np.zeros(160, bool)), ('wait_opposite_short', np.zeros(161, np.int8))):
        def bad(record: dict, signal: dict) -> None:
            """
            機能: 必須素材の型又は長さ又は呼値を不正化する。
            引数: record/signal(dict)。
            返り値: Noneは人工信号の変更。
            """
            signal[field] = replacement
        try:
            execute(strategy, configs['A3_X3'], 'TOPIX', 1, 'direct', bad)
        except AssertionError:
            invalid_inputs += 1
        else:
            raise AssertionError('待機素材の不正を受理しました: ' + field)
    assert invalid_inputs == 6
    paths = (Path(__file__), HERE / 'support.py', WORK / 'engine.py', WORK / 'strategy.py',
             WORK / 'catalog.py', WORK.parent / 'wave_v96/engine.py', WORK.parent / 'wave_v96/strategy.py')
    proof = dict(全合格=True, 全36両商品買売人工経路=len(results), PythonJIT人工=py_count,
        PythonJIT全18配列照合=py_count*18, A0旧96全15台帳同値=nulls,
        境界検査=checks, 不正必須素材拒絶=invalid_inputs, 共有prepared変更=0,
        正式97損益実行=0, API取得=0, 実注文=0, 検査=results,
        SHA256={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths})
    destination = HERE / '人工待機36と旧即時15台帳及びPythonJITの自己検査.json'
    destination.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in proof.items() if key not in ('SHA256', '検査', '境界検査')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
