"""96の固定出口だけを人工入力と数理で反証し、正式損益を読まない。"""

import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import pickle
import sys
from types import SimpleNamespace

os.environ['NUMBA_DISABLE_JIT'] = '1'
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
import numpy as np


def module(name: str, path: Path) -> object:
    """
    機能: 書込及び正式再生を伴わず対象モジュールを読む。
    引数: name(str)は固有名、path(Path)はコード。
    返り値: objectは読取モジュール。JITは無効、バイトコードも作らない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def digest(value: object) -> str:
    """
    機能: 人工共有入力の変更を検出する。
    引数: value(object)は辞書又は配列。
    返り値: strはpickle内容のSHA256。
    """
    return hashlib.sha256(pickle.dumps(value, protocol=5)).hexdigest()


def fixture(symbol: str, side: int, width: float, progress: list[float],
            times: list[float] | None = None, invalid: tuple[int, ...] = ()) -> tuple[dict, dict]:
    """
    機能: 二商品の合法呼値で、入口一回だけの局所人工入力を作る。
    引数: symbol(str)、side(int)、width(float)、progress(list[float])、times(list|None)、invalid(tuple[int])。
    返り値: tuple[dict,dict]はrecord及びsignal。正式保存入力は読まない。
    """
    entry, tick = (4000., .5) if symbol == 'TOPIX' else (70000., 10.)
    n = len(progress)
    quote = entry + side * np.asarray(progress)
    bid = quote if side == 1 else quote - tick
    ask = quote + tick if side == 1 else quote
    stamps = np.asarray(times if times is not None else np.arange(n) + 300., dtype=float)
    valid = np.ones(n, bool)
    valid[list(invalid)] = False
    record = dict(symbol=symbol, tick=tick, start=0., limit=10000., time_s=stamps,
                  price=(bid+ask)/2, bid=bid, ask=ask, price_valid=valid.copy(),
                  quote_valid=valid, seq=np.arange(n))
    event = np.zeros(n, np.int8)
    event[0] = side
    signal = dict(grid=stamps.copy(), mapped=np.arange(n), mode=np.zeros(n, np.int8),
                  event=event, quality=np.ones(n, bool), reset=np.zeros(n, bool),
                  trend_width=width)
    return record, signal


def expected_offsets(s: float, d: float, c: float, tick: float, p: float) -> list[float]:
    """
    機能: 単調順行時の最大線を実装から独立した数式で求める。
    引数: s/d/c/tick/p(float)は停止幅、追尾幅、費用床、呼値、最大順行。
    返り値: list[float]はM0/M1/M2の方向付き停止幅。
    """
    first = max(-s, p-d)
    second = max(first, c) if p >= 2*s else first
    third = max(second, math.floor(.5*p/tick)*tick) if p >= 2*s else first
    return [first, second, third]


def main() -> None:
    """
    機能: 局所人工・数学・静的構造を確認し、review_preだけへ証跡を保存する。
    引数: なし。
    返り値: None。不合格は例外。API、原本、新96正式損益へ接続しない。
    """
    engine = module('局所独立反証の実装96', BASE/'engine.py')
    catalog = module('局所独立反証の条件96', BASE/'catalog.py')
    strategy = module('局所独立反証の浅いコピー96', BASE/'strategy.py')
    conditions = catalog.catalog()
    assert len(conditions) == 18 and catalog.PRIMARY == 'S10_M1_UNL'
    assert catalog.CONTROL == 'S40_M0_H30'
    assert all(v['trend_source'] == 'P0' and v['loss_reentry_kind'] == 'none'
               and v['trend_budget'] == 8 and v['range_budget'] == 0 for v in conditions)
    assert all(v['trend_width_fraction'] == .004 for v in conditions)
    mathematical = synthetic = prefix = null = 0
    fees = {}

    # ----------------------------------------
    # 費用、方向付き丸め、閾値、床の実装を局所人工へ結びつける。
    outputs = {}
    for symbol, opening, tick, quantity, multiplier, unit in (
            ('TOPIX', 4000., .5, 8, 1000., 41.8), ('NK225', 70000., 10., 16, 10., 11.)):
        fee = math.floor(quantity*unit + 1e-8)
        fee_width = 2*fee/(quantity*multiplier)
        c = math.ceil(fee_width/tick)*tick + tick
        d = max(2, math.ceil(opening*.004/tick-1e-10))*tick
        fees[symbol] = dict(片道円=fee, 往復円=2*fee, 費用幅=fee_width, 保護床幅=c)
        for bp in (10, 20, 40):
            s = max(2, math.ceil(opening*bp/10000/tick-1e-10))*tick
            assert c <= s and s <= d
            for k in range(201):
                values = expected_offsets(d,d,c,tick,k*tick)
                assert values[0] == values[1] == values[2]
                mathematical += 1
            for side in (-1, 1):
                for cfg in (v for v in conditions if v['trend_initial_stop_bp'] == bp):
                    key = (symbol, side, cfg['id'])
                    progress = [-tick, -tick, 2*s-tick, 2*s, 2*s+tick, 2*d, 2*d+tick]
                    record, signal = fixture(symbol,side,d,progress)
                    signal['trend_initial_stop_width'] = s
                    before = digest((record, signal, cfg))
                    out = engine.execute(record,signal,cfg,finish=False)
                    assert before == digest((record,signal,cfg))
                    trace = out['trend_exit_state_trace']
                    mode = cfg['trend_protection_mode']
                    entry = opening
                    assert len(out['orders']) == 1 and out['orders'][0,0] == 1
                    for i in range(2,len(progress)):
                        observed_peak = max(0., *progress[2:i+1])
                        expected = expected_offsets(s,d,c,tick,observed_peak)[mode]
                        assert side*(trace[i,17]-entry) == expected, (key,i,trace[i].tolist(),expected)
                        assert trace[i,14] == (mode != 0 and observed_peak >= 2*s)
                        assert side*(trace[i,17]-trace[i-1,17]) >= 0
                    assert trace[1,12] == entry + side*c
                    assert trace[1,19] == (cfg['trend_hold_seconds'] > 0)
                    outputs[key] = out
                    synthetic += 1
                    # 切断及び以後の自己価格変更で、過去配列を変えない。
                    for cut in (3,4,6):
                        part = {k:(v[:cut].copy() if isinstance(v,np.ndarray) else v)
                                for k,v in record.items()}
                        sig = {k:(v[:cut].copy() if isinstance(v,np.ndarray) else v)
                               for k,v in signal.items()}
                        truncated = engine.execute(part,sig,cfg,finish=False)
                        poisoned = deepcopy(record)
                        poisoned['bid'][cut:] += 100*tick
                        poisoned['ask'][cut:] += 100*tick
                        altered = engine.execute(poisoned,signal,cfg,finish=False)
                        for name in ('curve','source_curve','target_trace','trend_exit_state_trace'):
                            np.testing.assert_array_equal(truncated[name],out[name][:cut])
                            np.testing.assert_array_equal(altered[name][:cut],out[name][:cut])
                        prefix += 1
                    # 欠測中の価格をpeakへ使わず、再開した正常返済気配だけ使う。
                    missing, ms = fixture(symbol,side,d,[-tick,-tick,4*d,0.,-s,-s-tick],invalid=(2,))
                    ms['trend_initial_stop_width'] = s
                    mo = engine.execute(missing,ms,cfg,finish=False)
                    assert mo['trend_exit_state_trace'][2,9] == opening
                    assert mo['trend_exit_state_trace'][2,14] == 0
                    assert mo['orders'][-1,0] == 5 and mo['trades'][-1,3] == 5
                    synthetic += 1
                    # 発火後に床を越えるgap。実fillは希望床価格でない。
                    gap, gs = fixture(symbol,side,d,[-tick,-tick,2*s,c-tick,-2*s])
                    gs['trend_initial_stop_width'] = s
                    go = engine.execute(gap,gs,cfg,finish=False)
                    if mode:
                        assert go['trades'][0,3] == 4 and go['orders'][-1,1] == 3
                        assert side*(go['trades'][0,7]-opening) == -2*s
                        parent = go['trend_parent_diagnostics'][0]
                        assert parent[14] == 3 and parent[26] == 3
                        assert parent[20] == 1
                    synthetic += 1
                    # 0秒を即返済にせず、30分比較だけを有効化する。
                    timed, ts = fixture(symbol,side,d,[-tick,-tick,0.,0.,0.],
                        times=[300.,301.,302.,2101.,2102.])
                    ts['trend_initial_stop_width'] = s
                    to = engine.execute(timed,ts,cfg,finish=False)
                    if cfg['trend_hold_seconds'] == 0:
                        assert len(to['trades']) == 0 and to['slots'][0,0] == 2
                    else:
                        assert to['trades'][0,13] == 3 and to['trades'][0,3] == 4
                    synthetic += 1

        for side in (-1,1):
            for hold in ('H30','UNL'):
                control = outputs[symbol,side,'S40_M0_'+hold]
                for mode in (1,2):
                    other = outputs[symbol,side,f'S40_M{mode}_{hold}']
                    for name in ('orders','trades','curve','source_curve','target_trace','events','stats','slots'):
                        np.testing.assert_array_equal(control[name],other[name])
                    null += 1

    # ----------------------------------------
    # playの浅いコピーは、条件固有幅を共通信号へ埋め込まない。
    saved_engine = strategy.ENGINE
    captured = []
    strategy.ENGINE = SimpleNamespace(execute=lambda record,signal,config,finish: captured.append(signal))
    common = {('人工','TOPIX'):dict(record={'tick':.5},reference_open=4000.,
                                  signal={'trend_width':16.,'event':np.array([1],np.int8)})}
    old_digest = digest(common)
    for cfg in conditions:
        strategy.play(cfg,('人工','TOPIX'),common,finish=False)
    strategy.ENGINE = saved_engine
    assert digest(common) == old_digest
    assert len(captured) == 18 and all(v is not common['人工','TOPIX']['signal'] for v in captured)
    assert all(v['event'] is common['人工','TOPIX']['signal']['event'] for v in captured)
    assert 'trend_initial_stop_width' not in common['人工','TOPIX']['signal']

    # simulateの引数配列へ代入していないことを静的にも確認。
    source = (BASE/'engine.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    function = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name == 'simulate')
    inputs = {arg.arg for arg in function.args.args}
    stores = []
    for node in ast.walk(function):
        if isinstance(node,ast.Subscript) and isinstance(node.ctx,ast.Store):
            base = node.value
            while isinstance(base,ast.Subscript):
                base = base.value
            if isinstance(base,ast.Name) and base.id in inputs:
                stores.append((base.id,node.lineno))
    assert not stores
    design = json.loads((BASE/'結果前の設計案.json').read_text(encoding='utf-8'))
    assert design['予定条件数'] == 18 and design['理論主'] == catalog.PRIMARY
    paths = [BASE/'engine.py',BASE/'strategy.py',BASE/'catalog.py',BASE/'結果前の設計案.json',
             BASE/'セッション安定性の事前評価.json',ROOT/'work/wave_v96_design/18出口対照の損益前独立反証と全31安定性評価.json']
    evidence = dict(全合格=True, 段階='正式結果前の局所独立反証。正式再生/API/原本読取なし。',
        数理反証点=mathematical, 人工実装ケース=synthetic, 人工接頭未来不変=prefix,
        S40同期限mode経済null=null, 共有play浅いコピー条件=18, 引数配列代入=stores,
        費用=fees, 主=catalog.PRIMARY, 旧対照=catalog.CONTROL,
        原板全件を検査したか=False, 正式96損益計算=0, 正式96損益閲覧=0, API取得=0, 実注文=0,
        必須前提=[
          '全62旧対照完全一致、実入力prefix/peer未来変形、全18人工の独立oracleは担当監査の別証跡で必要。局所合格を全正式再生済みとは呼ばない。',
          '旧reason1/2はpeakが建値から動いたかで決まり、狭Sの初期線のまま停止もreason2になり得る。原因分類はline ownerと各line hitを併用する。',
          '場末予約のdecision_row=i−1とforce_timeは既知時刻の予定。観測気配はdecision_observation_row=iから取得し、予約予定時刻の板であるとは呼ばない。',
          'S40三modeは新床フラグが異なっても経済null。18列を18独立手法として数えない。',
          '利益床は次正常気配の約定を保証しない。回復勝ち切りと返済後の新規連鎖を正式診断へ含める。'],
        SHA256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    target = HERE/'初期停止と利益床の局所独立反証.json'
    text = json.dumps(evidence,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    target.write_text(text,encoding='utf-8')
    assert json.loads(target.read_text(encoding='utf-8')) == evidence
    print(json.dumps({k:v for k,v in evidence.items() if k not in ('必須前提','SHA256')},ensure_ascii=False))


if __name__ == '__main__':
    main()
