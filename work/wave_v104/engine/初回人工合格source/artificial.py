"""104の支持境界・利益保険・予約順序を、金融結果を使わない人工で確認する。"""

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import time
import traceback

import numpy as np

import interface


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
COUNTS = {}


def check(name: str, condition: bool) -> None:
    """
    機能: 期待条件を確認し、独立した検査件数を保存する。
    引数: name(str)、condition(bool)。
    返り値: None。違反時はAssertionErrorを出しFalse履歴を残す。
    """
    assert condition, name
    COUNTS[name] = COUNTS.get(name, 0) + 1


def fixture(symbol: str, side: int, entry_id: str = 'C_OWN') -> tuple[dict, dict]:
    """
    機能: 旧準備と同じshapeを持つflat人工気配と単一候補を作る。
    引数: symbol(str)、side(int)、entry_id(str)。
    返り値: tuple[dict,dict]は準備値とnormal_case。正式data/cache/APIは読まない。
    """
    base, tick = (4000., .5) if symbol == 'TOPIX' else (50000., 10.)
    n = 1250
    times, seq = np.arange(n, dtype=np.float64), np.arange(n, dtype=np.int64) + 1000
    bid, ask = np.full(n, base), np.full(n, base + tick)
    record = dict(symbol=symbol, session='人工', time_s=times, seq=seq, bid=bid, ask=ask,
        price=(bid + ask) / 2., price_valid=np.ones(n, bool), quote_valid=np.ones(n, bool),
        tick=tick, start=0., limit=1200., end=1250., 人工素材=True)
    grid = np.arange(300., 1205., 5.)
    mapped = np.full(n, -1, np.int32)
    mapped[grid.astype(int)] = np.arange(len(grid), dtype=np.int32)
    old = dict(grid=grid, mapped=mapped, quality=np.ones(n, bool), reset=np.zeros(n, bool), event=np.zeros(n, np.int8),
        mode=np.zeros(len(grid), np.int8), trend_width=max(2, math.ceil(base * .004 / tick - 1e-10)) * tick,
        entry_j2_long=np.zeros(len(grid), bool), entry_j2_short=np.zeros(len(grid), bool),
        wait_opposite_long=np.ones(len(grid), bool), wait_opposite_short=np.ones(len(grid), bool))
    prepared = dict(record=record, signal=old, reference_open=base)
    event, support = np.zeros(n, np.int8), np.full(n, np.nan)
    event[330], support[330] = side, base if side == 1 else base + tick
    source = dict(raw_seq=seq, price_time_s=times, volume_time_s=times.copy(), execution_to_raw_index=np.arange(n, dtype=np.int64),
        normal_execution_row=np.arange(n, dtype=np.int32), qualified=np.ones(n, bool))
    for name in ('price_reset_reason', 'depth_reset_reason', 'lp_reset_reason', 'volume_reset_reason'):
        source[name] = np.zeros(n, np.uint16)
    item = {name: record[name] for name in ('symbol', 'start', 'end', 'limit', 'tick')}
    case = dict(entry_id=entry_id, event=event, support_price=support, entry_quality=np.ones(n, bool), entry_reset=np.zeros(n, bool),
        execution_to_raw_index=source['execution_to_raw_index'], decisions=[], legacy_account=dict(item=item, source=source, normal_record=record, pulses={}))
    refresh(case, record)
    return prepared, case


def refresh(case: dict, record: dict) -> None:
    """
    機能: 人工の候補変更をnormal/raw当時台帳へ一致させる。
    引数: case/record(dict)は人工だけ。
    返り値: None。未来の支持価格を候補へ挿入しない。
    """
    rows = []
    for row in np.flatnonzero(case['event']):
        rows.append(dict(row=int(row), normal_row=int(row), raw_row=int(case['execution_to_raw_index'][row]),
            raw_seq=int(record['seq'][row]), side=int(case['event'][row]), support_price=float(case['support_price'][row]),
            price_time=float(record['time_s'][row]), self_lineages=[dict(family=case['entry_id'][0], anchor_raw_seq=int(record['seq'][row - 1]))]))
    case['decisions'] = rows
    case['legacy_account']['pulses'][case['entry_id']] = dict(event=case['event'], normal_event=case['event'], decisions=rows, normal_decisions=rows)


def quote_from(prepared: dict, start: int, liquidation: float, side: int) -> None:
    """
    機能: 指定行からの正常買売気配を、同じspreadで変更する。
    引数: prepared(dict)、start/side(int)、liquidation(float)。
    返り値: None。原行順を並替えず人工価格を用意する。
    """
    record, tick = prepared['record'], prepared['record']['tick']
    record['bid'][start:] = liquidation if side == 1 else liquidation - tick
    record['ask'][start:] = liquidation + tick if side == 1 else liquidation
    record['price'][start:] = (record['bid'][start:] + record['ask'][start:]) / 2.


def run(prepared: dict, case: dict, exit_id: str, quantity: int = 1, finish: bool = True) -> dict:
    """
    機能: 同じ人工素材でPython/JITの物理約定と全時価を比較する。
    引数: prepared/case(dict)、exit_id(str)、quantity(int)、finish(bool)。
    返り値: dict。JIT出力。未固定の金融選定や正式全32再生はしない。
    """
    first = interface.play(prepared, case, exit_id, quantity, finish, python=True)
    second = interface.play(prepared, case, exit_id, quantity, finish, python=False)
    for name in ('orders', 'trades', 'growth_cohorts', 'events', 'curve', 'source_curve', 'target_trace', 'judgments', 'candidate_diagnostics', 'stale_equity'):
        check('PythonとJITの人工金融及び途中判断一致', np.array_equal(first[name], second[name], equal_nan=True))
    account = interface.module('104人工の読取旧会計', ROOT / 'work/wave_v102/accounting.py')
    if finish:
        row = account.account(('人工', prepared['record']['symbol']), second)
        check('物理注文親玉料金と終端時価の独立会計一致', abs(row['net'] - second['curve'][-1]) < 1e-5 and not second['target_trace'][-1].any())
    return second


def main() -> None:
    """
    機能: B/T買売、予約悪化、timer、利益床、料金、prefix、旧O経済nullを検査する。
    引数: なし。
    返り値: None。新104金融は実行せず現source人工証跡だけ保存する。
    """
    target = HERE / '支持境界と利益保険及び予約順序の人工検査.json'
    assert not target.exists()
    refs = [Path(__file__), HERE / 'core.py', HERE / 'interface.py', HERE / 'adapter.py', HERE / 'old_finance_snapshot.py',
        HERE.parent / 'catalog.py', HERE.parent / '数値設計案.json', ROOT / 'work/wave_v103/engine/adapter.py',
        ROOT / 'work/wave_v103/engine/finance_adapter.py', ROOT / 'work/wave_v102/engine.py', ROOT / 'work/wave_v102/accounting.py']
    beginning = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in refs}
    check('旧金融snapshot exact bytes', (HERE / 'adapter.py').read_bytes() == (ROOT / 'work/wave_v103/engine/adapter.py').read_bytes()
          and (HERE / 'old_finance_snapshot.py').read_bytes() == (ROOT / 'work/wave_v103/engine/finance_adapter.py').read_bytes())
    for symbol in ('TOPIX', 'NK225'):
        for side in (1, -1):
            for exit_id in ('B1', 'B2', 'B4', 'T2', 'T4'):
                prepared, case = fixture(symbol, side)
                output = run(prepared, case, exit_id)
                check('新規は判断後の別正常quote', output['orders'][0, 1] == 330 and output['orders'][0, 0] == 331)
                check('時間保有せず既知timerの最初正常quote', output['orders'][1, 0] == 1140 and output['orders'][1, 8] == 6
                      and output['orders'][1, 10] == 1140. and output['orders'][1, 1] == 1139)
                k, tick = int(exit_id[1]), prepared['record']['tick']
                initial = output['judgments'][0]
                support_line = case['support_price'][330] - side * k * tick
                entry = output['orders'][0, 6]
                initial_line = entry - side * output['initial_width']
                check('固定支持と初期保険の有利側OR', initial[17] == (max(support_line, initial_line) if side == 1 else min(support_line, initial_line)))
                altered = deepcopy(prepared)
                quote_from(altered, 335, initial[17], side)
                stopped = run(altered, deepcopy(case), exit_id)
                check('線ちょうどで判断し次quote返済', stopped['orders'][1, 1] == 335 and stopped['orders'][1, 0] == 336)
                check('停止線は不利方向へ戻らない', np.all(side * np.diff(stopped['judgments'][:, 17]) >= -1e-8))

            # ----------------------------------------
            # 床とtrailの発動は、fee幅とk呼値を超えた正常清算bestだけに限定する。
            for exit_id in ('T2', 'T4'):
                prepared, case = fixture(symbol, side)
                tick, k = prepared['record']['tick'], int(exit_id[1])
                entry = prepared['record']['ask'][331] if side == 1 else prepared['record']['bid'][331]
                fee_width = tick
                quote_from(prepared, 340, entry + side * (fee_width + k * tick), side)
                quote_from(prepared, 344, entry + side * fee_width, side)
                output = run(prepared, case, exit_id)
                activating = output['judgments'][output['judgments'][:, 0] == 340][0]
                check('T発動は費用幅とk呼値で当時best', activating[15] == 1 and activating[14] == entry + side * fee_width)
                check('fee床と狭trailのtie所有者保持', int(activating[18]) & 8 != 0 and int(activating[18]) & 16 != 0)
                check('利益床で判断しても次quote価格は別', output['orders'][1, 1] == 344 and output['orders'][1, 0] == 345)

            # ----------------------------------------
            # 予約後資格悪化は取消しない。実fill行破綻は同row予約・次quote返済。
            prepared, case = fixture(symbol, side)
            prepared['record']['quote_valid'][331:336] = False
            case['entry_quality'][331:] = False
            case['entry_reset'][331:] = True
            base = case['support_price'][330]
            quote_from(prepared, 336, base - side * 8 * prepared['record']['tick'], side)
            output = run(prepared, case, 'B2')
            check('予約後資格悪化を新規未来取消にしない', output['orders'][0, 0] == 336)
            check('fill行の既存仮説破綻で返済予約', output['orders'][1, 1] == 336 and output['orders'][1, 0] == 337)
            check('保有中120秒や量不明で支持交換しない', output['judgments'][0, 8] == base)
            prepared, case = fixture(symbol, side)
            case['event'][:] = 0
            case['support_price'][:] = np.nan
            case['event'][899], case['support_price'][899] = side, base
            refresh(case, prepared['record'])
            output = run(prepared, case, 'B2')
            check('cut新規取消は当該正常quote約定より先', not len(output['orders']) and np.any(output['events'][:, 3] == 6))
            prepared, case = fixture(symbol, side)
            prepared['record']['quote_valid'][335:340] = False
            quote_from(prepared, 335, case['support_price'][330] - side * 2 * prepared['record']['tick'], side)
            output = run(prepared, case, 'B2')
            check('不明quoteを約定へ補完しない', output['orders'][1, 1] == 340 and output['orders'][1, 0] == 341
                  and output['stale_equity'][335:340].all())
            check('stale時価だけ前の正常清算quoteを使う', np.all(output['curve'][335:340] == output['curve'][334]))

    # ----------------------------------------
    # 各腿実量、料金丸め、両建ての親/玉namespaceと全時価を会計へ渡す。
    quantities = []
    accounting = interface.module('104人工の読取旧会計', ROOT / 'work/wave_v102/accounting.py')
    for symbol in ('TOPIX', 'NK225'):
        allocations = ((2, 8), (5, 5), (8, 2)) if symbol == 'TOPIX' else ((4, 16), (10, 10), (16, 4))
        for allocation in allocations:
            for exit_id in ('B2', 'T2'):
                p, c = fixture(symbol, 1, 'C_P10')
                _, r = fixture(symbol, -1, 'R_P10')
                legs = {family: run(p, case, exit_id, quantity) for family, case, quantity in zip(('C', 'R'), (c, r), allocation)}
                output = interface.join(legs, allocation, symbol)
                totals = accounting.account(('人工', symbol), output)
                check('配分は各腿実数量の注文親玉とfee floor', totals['lots'] == sum(allocation) and totals['campaigns'] == 2)
                check('配分は両方向heldと予約の片方向枠内', np.all(output['target_trace'][:, :4] <= sum(allocation))
                      and output['target_trace'][331, 0] == allocation[0] and output['target_trace'][331, 1] == allocation[1])
                check('配分曲線は同原行の含み損と残玉料を合算', np.array_equal(output['curve'], legs['C']['curve'] + legs['R']['curve']))
                if symbol == 'TOPIX' and allocation == (5, 5):
                    check('TOPIX5枚一注文209円', np.all(output['orders'][:, 9] == 209.))
                quantities.append(dict(商品=symbol, 配分=allocation, 出口=exit_id, 注文料=totals['fees']))

    # ----------------------------------------
    # 接頭はfuture timer清算なし。完全入力扱いにはlimit到達を要求する。
    for symbol in ('TOPIX', 'NK225'):
        p, c = fixture(symbol, 1)
        full = run(p, c, 'B2')
        short, small = deepcopy(p), deepcopy(c)
        length = 400
        for name, value in list(short['record'].items()):
            if isinstance(value, np.ndarray):
                short['record'][name] = value[:length]
        for name in ('event', 'support_price', 'entry_quality', 'entry_reset', 'execution_to_raw_index'):
            small[name] = small[name][:length]
        past = run(short, small, 'B2', finish=False)
        check('接頭注文時価保有は正式人工接頭と一致', np.array_equal(past['orders'], full['orders'][full['orders'][:, 0] < length])
              and np.array_equal(past['curve'], full['curve'][:length]) and np.array_equal(past['target_trace'], full['target_trace'][:length]))
        check('finishFalse端点でfuture timer清算なし', len(past['orders']) == 1 and not len(past['trades']))
        no_event = deepcopy(small)
        no_event['event'][:] = 0
        no_event['decisions'] = []
        try:
            interface.play(short, no_event, 'B2', finish=True, python=True)
        except AssertionError:
            check('flat短prefixを完全入力へ誤認しない', True)
        else:
            raise AssertionError('limit未到達の完全入力を受理しました')

    # ----------------------------------------
    # exact snapshotの旧Oは、同じ人工OWN候補の旧103出力と経済null。
    original = interface.module('104人工nullだけの原103金融', ROOT / 'work/wave_v103/engine/finance_adapter.py')
    original.adapter.HERE = HERE
    for symbol in ('TOPIX', 'NK225'):
        for side in (1, -1):
            p, c = fixture(symbol, side)
            expected = original.play(dict(p, 人工Python=True), c['legacy_account'], c['entry_id'])
            actual = interface.play(p, c, 'O', python=True)
            check('旧Oと103OWN同入口の物理経済null', all(np.array_equal(expected[name], actual[name], equal_nan=True)
                  for name in ('orders', 'trades', 'growth_cohorts', 'curve', 'source_curve', 'target_trace')))
            check('旧O会計と103OWN同値', accounting.account(('人工', symbol), actual) == accounting.account(('人工', symbol), expected))
    ending = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in refs}
    check('参照source開始終端一致', beginning == ending)
    proof = dict(全合格=True, 人工専用=True, 検査件数=COUNTS, 実数量例=quantities,
        開始終端source一致=True, 開始SHA256=beginning, SHA256=ending, 新104正式金融=0,
        旧OWN正式金融null='この人工証跡は人工4例のみ。正式32の旧経済nullは別証跡が必要。',
        API取得=0, 原本読取=0, 現在データ取得=0, 実注文=0,
        signed_risk='停止線での費用後予定損失のsigned値であり、次quoteの実損失上限ではない。')
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査件数=COUNTS, 実数量例数=len(quantities), 証跡SHA256=hashlib.sha256(target.read_bytes()).hexdigest()), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        folder = HERE / ('人工False_' + time.strftime('%Y%m%d_%H%M%S'))
        folder.mkdir(exist_ok=False)
        hashes = {}
        for name in ('artificial.py', 'core.py', 'interface.py'):
            content = (HERE / name).read_bytes()
            (folder / name).write_bytes(content)
            hashes[name] = hashlib.sha256(content).hexdigest()
        (folder / 'False.json').write_text(json.dumps(dict(全合格=False, 例外=str(error), traceback=traceback.format_exc(),
            原sourceSHA256=hashes, 完了確認件数=COUNTS, 新104正式金融=0), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        raise
