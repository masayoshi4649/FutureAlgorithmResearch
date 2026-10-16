"""既存B4とのoff同値、途中確認と未来不変を最小の人工素材で検査する。"""

import ast
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import sys
import types

import numpy as np

import interface
import peer


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def load_functions(path: Path, names: set[str], namespace: dict) -> dict:
    """
    機能: 不変旧sourceの必要な純人工関数だけをcache無しで読む。
    引数: path(Path)、names(set[str])、namespace(dict)は出典・対象・依存値。
    返り値: dictは検査用関数。旧moduleのJIT設定や金融mainを実行しない。
    """
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    selected = []
    for value in tree.body:
        if isinstance(value, ast.FunctionDef) and value.name in names:
            value.decorator_list = []
            selected.append(value)
        elif isinstance(value, ast.Assign) and all(isinstance(t, ast.Name)
                and t.id.isupper() and t.id not in ('HERE', 'ROOT') for t in value.targets):
            selected.append(value)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


def observation(record: dict, side: int) -> dict:
    """
    機能: strict過去で新鮮な相手逆方向を保有判断へ与える人工列を作る。
    引数: record(dict)は自己正常行、side(int)は保有方向。
    返り値: dictは自己/相手の正常資格と当時整数系譜。
    """
    n = len(record['seq'])
    floats = np.zeros((n, 6))
    floats[:, 0], floats[:, 1] = record['time_s'] - 1., 1.
    floats[:, 2:4], floats[:, 4], floats[:, 5] = -side, record['time_s'] - 11., 1.
    integers = np.full((n, 4), 2**53 + 41, np.int64)
    return dict(self_known=np.ones(n, bool), direction=np.full(n, -side, np.int8),
        known=np.ones(n, bool), float_lineage=floats, integer_lineage=integers)


def main() -> None:
    """
    機能: 商品反射・0/5秒・中断・従来停止優先・後続再参加を人工検査する。
    引数: なし。
    返り値: None。所有域の小証跡のみ保存し、正式packetや金融結果は読まない。
    """
    fixture = load_functions(ROOT/'work/wave_v106/engine/artificial.py',
        {'config', 'fixture', 'set_event', 'quote_from'}, dict(np=np, math=math, deepcopy=deepcopy))
    old = load_functions(ROOT/'work/wave_v106/engine/core.py',
        {'append_event', 'control_event', 'current_equity', 'simulate', 'execute'}, dict(np=np, math=math))
    old['simulate'].py_func = old['simulate']
    checked = []
    for symbol in ('TOPIX', 'NK225'):
        for side in (1, -1):
            prepared, case = fixture['fixture'](symbol, side)
            tick = prepared['record']['tick']
            support = case['support_price'][330]
            fixture['quote_from'](prepared, 333, support - side*tick, side)
            case['thesis_peer'] = observation(prepared['record'], side)
            base = fixture['config']()
            signal, settings = interface.connect(prepared, case, base, 1)
            reference = old['execute'](prepared['record'], signal, settings, python=True)
            off = interface.play(prepared, case, base, python=True)
            for key in ('orders', 'trades', 'growth_cohorts', 'events', 'curve', 'target_trace',
                        'stats', 'judgments', 'candidate_diagnostics', 'control_judgments'):
                np.testing.assert_array_equal(reference[key], off[key])
            checked.append(symbol+str(side)+'部品off同値')
            for seconds, decision in ((0., 333), (5., 338)):
                config = fixture['config'](thesis_enabled=True, thesis_confirm_seconds=seconds)
                result = interface.play(prepared, case, config, python=True)
                trade = result['trades'][0]
                assert trade[13] == 9 and int(result['orders'][1, 1]) == decision
                assert int(trade[3]) == decision + 1
                assert int(result['thesis_integer_keys'][0, 2]) == 2**53 + 41
                checked.append(symbol+str(side)+f'{int(seconds)}秒当時確認と次quote')
            altered = deepcopy(prepared)
            fixture['quote_from'](altered, 350, support+side*20*tick, side)
            config = fixture['config'](thesis_enabled=True, thesis_confirm_seconds=0.)
            original = interface.play(prepared, case, config, python=True)
            future = interface.play(altered, case, config, python=True)
            np.testing.assert_array_equal(original['orders'], future['orders'])
            np.testing.assert_array_equal(original['trades'], future['trades'])
            checked.append(symbol+str(side)+'退出後未来差替え不変')
            interrupted = deepcopy(case)
            interrupted['thesis_peer']['known'][335] = False
            config = fixture['config'](thesis_enabled=True, thesis_confirm_seconds=5.)
            result = interface.play(prepared, interrupted, config, python=True)
            assert int(result['orders'][1, 1]) == 341
            checked.append(symbol+str(side)+'UNKNOWNは中断し即退出しない')
            neutral = deepcopy(case)
            neutral['thesis_peer']['direction'][335] = 0
            result = interface.play(prepared, neutral, config, python=True)
            assert int(result['orders'][1, 1]) == 341
            checked.append(symbol+str(side)+'中立は反対へ補完しない')
            same = deepcopy(prepared)
            same['record']['time_s'][333:338] = 333.
            same_case = deepcopy(case)
            same_case['thesis_peer'] = observation(same['record'], side)
            result = interface.play(same, same_case, config, python=True)
            assert int(result['orders'][1, 1]) == 338
            checked.append(symbol+str(side)+'同時計は確認秒を増やさない')
            priority = deepcopy(prepared)
            fixture['quote_from'](priority, 333, support-side*4*tick, side)
            result = interface.play(priority, case, config, python=True)
            assert result['trades'][0, 13] != 9
            checked.append(symbol+str(side)+'元支持停止優先')
            again = deepcopy(case)
            fixture['set_event'](prepared, again, 380, side, support, 378)
            config = fixture['config'](thesis_enabled=True, thesis_confirm_seconds=0.)
            result = interface.play(prepared, again, config, python=True)
            assert len(result['trades']) == 2
            checked.append(symbol+str(side)+'早期返済後の新状態で再参加')
    # ----------------------------------------
    # 公表窓をstrict過去で投影し、同時刻と15秒超過を使わない。
    record = dict(seq=np.arange(3, dtype=np.int64)+100, time_s=np.array([10., 11., 40.]),
        bid=np.array([100., 100., 100.]), ask=np.array([101., 101., 101.]), quote_valid=np.ones(3, bool))
    raw = dict(raw_seq=record['seq'], price_time_s=record['time_s'], bid=record['bid'], ask=record['ask'],
        execution_to_raw_index=np.arange(3), bbo_valid=np.ones(3, bool), price_reset_reason=np.zeros(3, np.uint16),
        clock_or_sequence_invalid=np.zeros(3, bool))
    win = dict(source_time_s=np.array([0., 10., 20.]), public_rows=np.arange(3),
        reference_raw_row=np.arange(3), source_raw_seq=np.array([1, 2, 3], np.int64),
        reference_raw_seq=np.array([0, 1, 2], np.int64), direction_t1=np.array([1, -1, 1], np.int8),
        unknown_reason=np.zeros(3, np.uint16), ambiguous=np.zeros(3, bool),
        bid_change_ticks=np.ones(3), ask_change_ticks=np.ones(3),
        reference_time_s=np.array([-10., 0., 10.]), current_spread_ticks=np.ones(3))
    packet = dict(raw={'TOPIX':raw}, peer_features={'NK225':dict(windows={'10':win})})
    projected = peer.project(packet, record, 'TOPIX', 10)
    assert projected['direction'].tolist() == [1, -1, 1]
    assert projected['integer_lineage'][:, 0].tolist() == [1, 2, 3]
    assert projected['known'].tolist() == [True, True, False]
    checked.append('相手同clockは旧公開を採り年齢20秒は不明')
    proof = dict(全合格=True, 検査群=checked, 件数=len(checked), 正式packet読取=0, 新金融再生=0,
        原本読取=0, API取得=0, 旧source変更=0,
        source_SHA256={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in sorted(HERE.glob('*.py'))})
    target = HERE/'支持破れと相手逆進行の人工検査.json'
    assert not target.exists()
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps(dict(全合格=True, 件数=len(checked)), ensure_ascii=False))


if __name__ == '__main__':
    main()
