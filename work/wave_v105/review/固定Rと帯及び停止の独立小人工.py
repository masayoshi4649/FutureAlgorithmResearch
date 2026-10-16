"""固定Rの数理と損失帯・当時停止・入力未知を私有人工だけで点検する。"""

from copy import deepcopy
from decimal import Decimal, ROUND_CEILING
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
WAVE = HERE.parent
ROOT = WAVE.parents[1]
sys.dont_write_bytecode = True


def module(name: str, path: Path) -> object:
    """
    機能: 自分のsnapshotと読み取り純inputだけを接続する。
    引数: name(str)、path(Path)は識別名とsource。
    返り値: object。正式素材又は金融を呼ばない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def ceil_tick(value: Decimal, tick: Decimal) -> Decimal:
    """
    機能: 独立十進数の価格幅を呼値へ切り上げる。
    引数: value/tick(Decimal)は幅と呼値。
    返り値: Decimalは呼値の整数倍。
    """
    return (value/tick).to_integral_value(rounding=ROUND_CEILING)*tick


def fixture(symbol: str, side: int, offsets: list, events: dict, sequence_base: int = 9007199254741000) -> tuple[dict, dict]:
    """
    機能: 同じ相対呼値と大きなint64原seqを持つ正常原行を作る。
    引数: symbol(str)、side(int)、offsets(list[float])、events(dict)は気配と候補、sequence_base(int)は整数境界。
    返り値: tuple[dict,dict]は人工recordと当時signal。
    """
    tick, reference = (.5, 1000.) if symbol == 'TOPIX' else (10., 10000.)
    n = len(offsets)
    # ----------------------------------------
    # 符号付き清算quoteを基準にし、buy/sellの鏡像を同じ条件で作る。
    quote = reference+side*np.array(offsets)*tick
    bid = quote if side == 1 else quote-tick
    ask = quote+tick if side == 1 else quote
    times = 300.+np.arange(n)*40.
    times[-1] = 1000.
    sequence = sequence_base+np.arange(n, dtype=np.int64)
    record = dict(symbol=symbol, session='独立状態人工', 人工素材=True, tick=tick, start=0., limit=1000., end=1000.,
        time_s=times, seq=sequence, bid=bid, ask=ask, quote_valid=np.ones(n, bool), price_valid=np.ones(n, bool), price=(bid+ask)*.5)
    event = np.zeros(n, np.int8)
    support = np.full(n, np.nan)
    anchors = np.full(n, -1, np.int64)
    decisions = []
    for row, value in events.items():
        price, anchor = value
        event[row], support[row], anchors[row] = side, price, int(sequence_base+anchor)
        decisions.append(dict(row=row, normal_row=row, raw_row=row, raw_seq=int(sequence[row]), side=side, support_price=price))
    signal = dict(event=event, support_price=support, entry_quality=np.ones(n, bool), entry_reset=np.zeros(n, bool),
        anchor_raw_seq=anchors, entry_filter=np.ones(n, bool), filter_reason=np.zeros(n, np.int32),
        decisions=decisions, execution_to_raw_index=np.arange(n), reference_open=reference,
        trend_width=8*tick)
    return record, signal


def settings(kind: str, quantity: int) -> dict:
    """
    機能: 数学境界だけを比較する人工設定を作る。
    引数: kind(str)、quantity(int)はR型又はT対照と実枚数。
    返り値: dictは105の同じ部品契約。正式51条件は変更しない。
    """
    return dict(id=kind, quantity=quantity, support_ticks=4 if kind.startswith('R') else 2,
        profit_trail=kind == 'T2', r_profit=kind.startswith('R'), alpha=2. if kind != 'R32' else 3., beta=1. if kind != 'R32' else 2.,
        reentry_band=False, session_brake=False, session_budget_multiple=1., initial_stop_fraction=.001,
        cooldown_seconds=30., start_offset=300., cut_offset=300., force_offset=60.)


def main() -> None:
    """
    機能: R丸めと実料、帯解除の厳密整数、ブレーキ及び未知入力を人工検算する。
    引数: なし。
    返り値: None。新金融と旧巨大入力を読まず、独立所見を保存する。
    """
    original = WAVE/'engine/core.py'
    snapshot = HERE/'105執行数学の人工用不変複製.py'
    if not snapshot.exists():
        snapshot.write_bytes(original.read_bytes())
    assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == hashlib.sha256(original.read_bytes()).hexdigest()
    core = module('105独立人工の状態数学複製', snapshot)
    counts, issues = {}, []
    math_count, prefix_count = 0, 0
    for symbol, cap in (('TOPIX', 10), ('NK225', 20)):
        tick, reference, multiplier = (.5, 1000., 1000) if symbol == 'TOPIX' else (10., 10000., 10)
        for side in (1, -1):
            for quantity in (1, cap):
                fee = int(Decimal(quantity)*Decimal('41.8' if symbol == 'TOPIX' else '11'))
                # ----------------------------------------
                # 初期線は2呼値、費用幅切上げ1呼値、Rは料金を含め3呼値になる。
                exact_fee = Decimal(2*fee)/Decimal(quantity*multiplier)
                fee_width = ceil_tick(exact_fee, Decimal(str(tick)))
                risk = ceil_tick(Decimal(2)*Decimal(str(tick))+exact_fee, Decimal(str(tick)))
                for kind in ('R21', 'R32'):
                    alpha, beta = (2, 1) if kind == 'R21' else (3, 2)
                    trigger = float((fee_width+alpha*risk)/Decimal(str(tick)))
                    width = float(beta*risk/Decimal(str(tick)))
                    # entry清算0、entry約定1。最大順行はtriggerへexact到達させる。
                    path = [0, 0, 1+trigger-1, 1+trigger, 1+trigger+2, 1+trigger+2-width, 1+trigger+2-width, 0]
                    record, signal = fixture(symbol, side, path, {0: (reference, 0)})
                    cfg = settings(kind, quantity)
                    output = core.execute(record, signal, cfg, python=True)
                    cc = {name: i for i, name in enumerate(output['control_columns'])}
                    first = output['control_judgments'][output['control_judgments'][:, cc['row']] == 1][0]
                    assert abs(first[cc['risk_R']]-float(risk)) < 1e-8
                    assert abs(first[cc['exact_fee_width']]-float(exact_fee)) < 1e-8
                    assert abs(first[cc['profit_trail_width']]-float(beta*risk)) < 1e-8
                    assert abs(first[cc['profit_floor_margin']]-float(fee_width+(alpha-beta)*risk)) < 1e-8
                    jc = {name: i for i, name in enumerate(output['judgment_columns'])}
                    active = output['judgments'][output['judgments'][:, jc['profit_active']] == 1]
                    assert len(active) and int(active[0, jc['row']]) == 3
                    assert output['orders'][0, 9] == output['orders'][1, 9] == fee
                    assert output['trades'][0, 11] > 0
                    for limit in (2, 4, 5):
                        reduced_record = {name: value[:limit] if isinstance(value, np.ndarray) else value for name, value in record.items()}
                        reduced_signal = {name: value[:limit] if isinstance(value, np.ndarray) else value for name, value in signal.items()}
                        reduced_signal['decisions'] = [row for row in signal['decisions'] if row['row'] < limit]
                        prefix = core.execute(reduced_record, reduced_signal, cfg, finish=False, python=True)
                        np.testing.assert_array_equal(prefix['curve'], output['curve'][:limit])
                        np.testing.assert_array_equal(prefix['target_trace'], output['target_trace'][:limit])
                        np.testing.assert_array_equal(prefix['orders'], output['orders'][output['orders'][:, 0] < limit])
                        assert prefix['target_trace'][-1, :2].sum() == quantity
                        prefix_count += 1
                    math_count += 1
    counts.update(R21_R32両市場買売実枚数の十進数境界=math_count, 人工保有接頭の未来清算なし=prefix_count)
    zone_count, brake_count = 0, 0
    for symbol, cap in (('TOPIX', 10), ('NK225', 20)):
        tick, reference = (.5, 1000.) if symbol == 'TOPIX' else (10., 10000.)
        for side in (1, -1):
            # ----------------------------------------
            # Loss→順方向escape→古いanchor拒否→strict新anchorでrelease。
            record, signal = fixture(symbol, side, [0, 0, -1, -1, 0, 4, 4, 4, 4, 4, 4],
                {0: (reference, 0), 5: (reference+side*4*tick, 4), 6: (reference+side*4*tick, 5),
                 7: (reference+side*4*tick, 5), 8: (reference+side*4*tick, 6)})
            cfg = settings('R21', cap)
            cfg['reentry_band'] = True
            output = core.execute(record, signal, cfg, python=True)
            events = output['control_integer_events']
            creation_rows = output['control_events'][(output['control_events'][:, 4] == 3)&(output['control_events'][:, 3] == 1), 0]
            assert len(creation_rows) == 1
            candidates = output['candidate_integer_keys']
            controls = output['candidate_controls']
            assert [bool(controls[i, 5]) for i in range(len(controls))] == [True, False, False, False, True]
            assert candidates[2, 2] == candidates[2, 3] and candidates[-1, 2] > candidates[-1, 3]
            assert candidates.dtype == events.dtype == np.int64 and int(candidates[0, 1]) > 2**53
            assert np.sum(output['control_events'][:, 4] == 6) == 1
            zone_count += 1
            # ----------------------------------------
            # 利益追尾の次fillで小損失→再entryのspread料でsession予算を突破。
            record, signal = fixture(symbol, side, [0, 0, 4, 2, 0, 0, 0, 0, 0, 0],
                {0: (reference, 0), 5: (reference, 5), 8: (reference, 8)})
            cfg = settings('T2', cap)
            cfg['session_brake'] = True
            output = core.execute(record, signal, cfg, python=True)
            assert len(output['trades']) == 2
            assert int(output['trades'][1, 13]) == 7
            assert output['orders'][2, 0] == 6 and output['orders'][3, 0] == 7
            assert output['control_stats'][2] == 1 and int(output['control_stats'][3]) == 6
            assert output['candidate_controls'][-1, 6] == 8
            assert output['curve'][-1] < -output['control_stats'][1]
            brake_count += 1
    counts.update(大int64の帯解除厳密新anchor=zone_count, fill料金後brakeと次quote返済=brake_count)
    input_fixture = module('105独立input境界の人工生成だけ', WAVE/'input/artificial.py')
    feature = module('105独立inputの当時計算', WAVE/'input/features.py')
    # ----------------------------------------
    # 正常非対応baselineはUNKNOWNのまま、後続normalへ移動して救済しない。
    packet = input_fixture.fixture()
    candidate = packet['cases']['C_OWN']['TOPIX']['candidates'][0]
    measured = feature.candidate_features(packet, 'TOPIX', candidate)
    public = deepcopy(measured['own']['30'])
    baseline = int(public['baseline']['raw_row'])
    altered = deepcopy(packet)
    altered['raw']['TOPIX']['normal_execution_row'][baseline] = -1
    public['observed_known'], public['known'], public['legacy_unknown_reason'] = False, False, 4
    try:
        unknown = feature.normal_path_measure(altered, 'TOPIX', candidate, public)
        assert not unknown['known'] and not unknown['observed_known'] and unknown['path_source'] is None
        counts['非対応baselineをUNKNOWN保持'] = 1
    except AssertionError:
        issues.append('旧inputはUNKNOWN公表baselineのnormal非対応でassertする。根/input担当が局所訂正中。')
    # ----------------------------------------
    # 現仕様ではsame-clockのaskだけ拡大してもmid効率は高くなり得る。
    times = 1000.+np.arange(65, dtype=float)
    times[44] = times[43]
    packet = input_fixture.fixture(walk=np.zeros(65), times=times)
    raw, record = packet['raw']['TOPIX'], packet['normal']['TOPIX']['record']
    raw['ask'][44] += 20*record['tick']
    record['ask'][44] = raw['ask'][44]
    measured = feature.candidate_features(packet, 'TOPIX', packet['cases']['C_OWN']['TOPIX']['candidates'][0])
    value = measured['own_normal']['30']
    assert value['known'] and value['efficiency'] == 1 and value['directional_net_ticks'] == 10
    counts['sameclock片側spreadでmid効率上昇する仕様限界'] = 1
    target = HERE/'固定Rと帯及び停止と入力未知の独立小人工.json'
    assert not target.exists()
    paths = [Path(__file__), original, WAVE/'engine/interface.py', WAVE/'input/features.py', WAVE/'input/core.py', WAVE/'input/data.py']
    result = dict(全合格=not issues, scope='実金融未読の人工数理。原本/NPZ/旧巨大入力再読なし。',
        検査件数=counts, 未解決=issues, source_SHA256={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
        所見=['Rはfill時の当時有効線と実注文料で固定。新型の2R発動はF+2R価格進行、費用後利益として2R。',
            '帯中心は元support、半径は初回Rであり、診断のentry±2呼値再参加とは同一条件でない。',
            'brake予算はS*q*m。料とspread込み清算時価で到達し、次quote返済で予算超過はあり得る。',
            'own_normalはPUBLIC窓の曖昧資格を継承。sameclock片側spreadがmid効率を押し上げる限界は、追加閾値を作らない現仕様として保持。'],
        正式金融再生=0, 正式金融読取=0, 原本読取=0, NPZ読取=0, API取得=0, goal操作=0)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=not issues, 検査件数=counts, 未解決=issues, SHA256=hashlib.sha256(target.read_bytes()).hexdigest()), ensure_ascii=False))


if __name__ == '__main__':
    main()
