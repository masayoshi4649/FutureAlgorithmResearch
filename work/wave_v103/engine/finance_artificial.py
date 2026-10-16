"""活動cacheから旧固定出口への金融接口を、少量人工だけで検査する。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import traceback

import numpy as np

import adapter
import artificial


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
COUNTS = {}
_spec = importlib.util.spec_from_file_location('103金融接口の人工対象', HERE / 'finance_adapter.py')
finance = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = finance
_spec.loader.exec_module(finance)


def check(name: str, condition: bool) -> None:
    """
    機能: 金融接口の独立期待条件と件数を記録する。
    引数: name(str)、condition(bool)。
    返り値: None。違反はAssertionErrorで止め、False履歴を保持する。
    """
    assert condition, name
    COUNTS[name] = COUNTS.get(name, 0) + 1


def fixture(symbol: str) -> tuple[dict, dict, dict, float]:
    """
    機能: oldnormalの間に非対応raw一行を置き、活動cacheと同じ接口を作る。
    引数: symbol(str)はTOPIX/NK225。
    返り値: tuple[dict,dict,dict,float]。人工活動口座、旧record、準備済み信号、保存始値。
    """
    record, signal, opening = artificial.fixture(symbol, 1)
    m = len(record['seq'])
    mapping = np.delete(np.arange(m + 1, dtype=np.int64), 331)
    reverse = np.full(m + 1, -1, np.int32)
    reverse[mapping] = np.arange(m, dtype=np.int32)
    raw_seq = np.arange(m + 1, dtype=np.int64) + 1000
    raw_time = np.insert(record['time_s'], 331, 330.5)
    record['seq'] = raw_seq[mapping].copy()
    source = dict(raw_seq=raw_seq, price_time_s=raw_time, volume_time_s=raw_time.copy(),
                  normal_execution_row=reverse, execution_to_raw_index=mapping,
                  qualified=np.ones(m + 1, bool))
    for name in finance.RESET_FIELDS:
        source[name] = np.zeros(m + 1, np.uint16)
    item = {name: record[name] for name in ('start', 'end', 'limit', 'tick', 'symbol')}
    account = dict(item=item, source=source, normal_record=deepcopy(record), pulses={})
    return account, record, signal, opening


def install(account: dict, case_id: str, normal_pulses: list[tuple[int, int]],
            extra_raw: list[tuple[int, int]] | None = None) -> None:
    """
    機能: 状態側で既に一度消費された人工pulseと当時lineageを保存する。
    引数: account(dict)、case_id(str)、normal_pulses/extra_raw(list[tuple[int,int]]|None)。
    返り値: None。非normal候補はその原行にだけ置き、将来normalへ移さない。
    """
    source = account['source']
    event = np.zeros(len(source['raw_seq']), np.int8)
    for normal, side in normal_pulses:
        event[source['execution_to_raw_index'][normal]] = side
    for raw, side in extra_raw or []:
        event[raw] = side
    decisions = []
    for raw in np.flatnonzero(event):
        normal = int(source['normal_execution_row'][raw])
        decisions.append(dict(row=int(raw), normal_row=None if normal < 0 else normal,
            raw_seq=int(source['raw_seq'][raw]), side=int(event[raw]), price_time=float(source['price_time_s'][raw]),
            in_reception=300. <= source['price_time_s'][raw] < 2000.,
            lineage=[dict(family=case_id[:1], own=dict(anchor_raw_seq=int(source['raw_seq'][raw - 1])),
                          peer=dict(raw_seq=222, price_time=float(source['price_time_s'][raw]) - .1))]))
    account['pulses'][case_id] = dict(event=event, normal_event=event[source['execution_to_raw_index']].copy(),
        decisions=decisions, normal_decisions=[value for value in decisions if value['normal_row'] is not None])


def replay(account: dict, record: dict, signal: dict, previous: dict, opening: float,
           case_id: str = 'C1') -> dict:
    """
    機能: 同じ旧準備済み素材を人工金融接口へ渡す。
    引数: account/record/signal/previous(dict)、opening(float)、case_id(str)。
    返り値: dict。人工仮想注文。正式cache又はbaseを読まない。
    """
    return finance.replay_single(account, case_id, record, signal, previous, opening, python=True)


def main() -> None:
    """
    機能: 非normal投影、受付消費、cut、品質悪化、各実数量料金とflatを検査する。
    引数: なし。
    返り値: None。少量人工証跡だけ保存し、全32損益は実行しない。
    """
    target = HERE / '活動normal投影と旧固定出口の金融接口人工検査_呼出統一.json'
    assert not target.exists()
    refs = [Path(__file__), HERE / 'finance_adapter.py', HERE / 'adapter.py', HERE / 'artificial.py',
            ROOT / 'work/wave_v102/engine.py', ROOT / 'work/wave_v102/catalog.py', ROOT / 'work/wave_v102/accounting.py']
    beginning = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in refs}
    previous = adapter.reference_config()
    quantities = []
    accounting = adapter.module('103金融接口人工だけの旧会計', ROOT / 'work/wave_v102/accounting.py')
    for symbol in ('TOPIX', 'NK225'):
        for side in (1, -1):
            account, record, old, opening = fixture(symbol)
            install(account, 'C1', [(330, side)])
            connected, settings, decisions = finance.connect(account, 'C1', record, old, previous, opening)
            check('旧Dは準備済みsignalの同値を保持', connected['trend_width'] == old['trend_width'])
            expected_s = max(2, int(np.ceil(opening * previous['trend_initial_stop_bp'] / 10000. / record['tick'] - 1e-10))) * record['tick']
            check('旧Sは保存始値と旧bp及び呼値式を保持', connected['trend_initial_stop_width'] == expected_s)
            check('固定1枚30分出口と増玉なし保持', settings['trend_initial_quantity'] == 1
                  and settings['trend_hold_seconds'] == 1800. and settings['trend_growth_mode'] == 0)
            output = replay(account, record, old, previous, opening)
            prepared = dict(record=record, signal=old, reference_open=opening, 人工Python=True)
            wrapped = finance.play(prepared, account, 'C1')
            check('根共通play接口は物理注文親玉時価が一致', all(np.array_equal(output[name], wrapped[name], equal_nan=True)
                  for name in ('orders', 'trades', 'growth_cohorts', 'target_trace', 'curve')))
            unfinished_record = deepcopy(record)
            for name, value in list(unfinished_record.items()):
                if isinstance(value, np.ndarray) and value.ndim and len(value) == len(record['time_s']):
                    unfinished_record[name] = value[:400].copy()
            unfinished = deepcopy(account)
            source, length = unfinished['source'], 401
            for name, value in list(source.items()):
                source[name] = value[:400].copy() if name == 'execution_to_raw_index' else value[:length].copy()
            unfinished['normal_record'] = deepcopy(unfinished_record)
            install(unfinished, 'C1', [(330, side)])
            prefix_signal = deepcopy(old)
            for name in ('mapped', 'quality', 'reset', 'event'):
                prefix_signal[name] = prefix_signal[name][:400].copy()
            unfinished_output = finance.play(dict(record=unfinished_record, signal=prefix_signal, reference_open=opening, 人工Python=True), unfinished, 'C1', finish=False)
            check('finishFalse不使用未来場末清算', len(unfinished_output['orders']) == 1
                  and not len(unfinished_output['trades']) and unfinished_output['target_trace'][-1, 0 if side == 1 else 1] == 1)
            row = output['raw_entry_diagnostics'][0]
            check('判断normalとraw及び実1枚を分離', row['decision_normal_row'] == 330 and row['decision_raw_row'] == 330
                  and row['fill_normal_row'] == 331 and row['fill_raw_row'] == 332 and row['quantity'] == 1)
            check('当時自己相手lineageを保持', row['episode']['lineage'] == account['pulses']['C1']['normal_decisions'][0]['lineage'])
            check('初回fillから同30分期限返済', output['orders'][1, 1] == 2131 and output['orders'][1, 0] == 2132)
            check('全玉時価の終端と親及び玉会計一致', accounting.account(('人工接口', symbol), output)['net'] == output['curve'][-1]
                  and not output['target_trace'][-1].any())

            # ----------------------------------------
            # 非対応候補は将来のnormalへ移さず、保有中候補も後で補充しない。
            nonnormal = deepcopy(account)
            install(nonnormal, 'C1', [], [(331, side)])
            no_order = replay(nonnormal, record, old, previous, opening)
            check('非normalpulseは未来へ移さない', not len(no_order['orders']) and not no_order['curve'].any()
                  and no_order['projection_diagnostics']['non_normal_pulses'] == 1)
            held = deepcopy(account)
            install(held, 'C1', [(330, side), (350, side)])
            consumed = replay(held, record, old, previous, opening)
            check('保有中消費候補を後へ補充しない', len(consumed['raw_entry_diagnostics']) == 1
                  and consumed['projection_diagnostics']['consumed_without_entry'] == 1)
            damaged = deepcopy(account)
            install(damaged, 'C1', [], [(331, side)])
            damaged['pulses']['C1']['normal_event'][331] = side
            try:
                finance.connect(damaged, 'C1', record, old, previous, opening)
            except AssertionError:
                check('別normal行へ移された候補を拒否', True)
            else:
                raise AssertionError('別normal行へ移された候補を受理しました')

            # ----------------------------------------
            # 外側pulseも入力へ残し、同じ旧executeの受付とcut優先で拒否する。
            outside = deepcopy(account)
            install(outside, 'C1', [(299, side), (2000, side)])
            no_order = replay(outside, record, old, previous, opening)
            check('受付外pulseは旧execute自身が拒否', not len(no_order['orders'])
                  and no_order['projection_diagnostics']['normal_pulses'] == 2)
            cutoff = deepcopy(account)
            install(cutoff, 'C1', [(1999, side)])
            no_order = replay(cutoff, record, old, previous, opening)
            check('cut取消は次行約定より先', not len(no_order['orders']) and np.any(no_order['events'][:, 3] == 6))
            late_record, late_account = deepcopy(record), deepcopy(account)
            late_record['quote_valid'][331:340] = False
            late_account['normal_record']['quote_valid'][331:340] = False
            later = late_account['source']['execution_to_raw_index'][331:]
            late_account['source']['qualified'][later] = False
            late_account['source']['lp_reset_reason'][later] = 1
            delayed = replay(late_account, late_record, old, previous, opening)
            check('予約後qualityreset悪化を未来取消へ使わない', delayed['orders'][0, 1] == 330 and delayed['orders'][0, 0] == 340)
            flags = deepcopy(account)
            for index, name in enumerate(finance.RESET_FIELDS):
                flags['source'][name][flags['source']['execution_to_raw_index'][10 + index]] = 1
            flag_signal = finance.connect(flags, 'C1', record, old, previous, opening)[0]
            check('normal_resetは四理由のOR', flag_signal['reset'][10:14].all())

        # ----------------------------------------
        # 配分は同一候補の実数量で再生し、注文毎の料金と片方向上限を保持する。
        choices = ((2, 8), (5, 5), (8, 2)) if symbol == 'TOPIX' else ((4, 16), (10, 10), (16, 4))
        for allocation in choices:
            for opposite in (False, True):
                account, record, old, opening = fixture(symbol)
                install(account, 'C1', [(330, 1)])
                install(account, 'R1', [(330, -1 if opposite else 1)])
                output = finance.replay_portfolio(account, record, old, previous, opening, allocation, python=True)
                row = accounting.account(('人工接口', symbol), output)
                check('各腿の実量と実料金で合算', row['lots'] == sum(allocation) and row['campaigns'] == 2
                      and output['legs']['C']['orders'][0, 5] == allocation[0] and output['legs']['R']['orders'][0, 5] == allocation[1])
                check('同時heldと予約込み片方向上限', np.all(output['target_trace'][:, :4] <= sum(allocation)))
                check('配分終端flatと含み損込み時価会計', not output['target_trace'][-1].any() and row['net'] == output['curve'][-1])
                if symbol == 'TOPIX' and allocation == (5, 5):
                    check('TOPIX5枚一注文209円の料金丸め', np.all(output['orders'][:, 9] == 209.))
                quantities.append(dict(商品=symbol, 配分=allocation, 両建て=opposite, 実料金=row['fees'], 決済枚数=row['lots']))
    ending = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in refs}
    check('source開始終端一致', beginning == ending)
    proof = dict(全合格=True, 人工専用=True, 検査件数=COUNTS, 実数量例=quantities,
        開始終端source一致=True, 開始SHA256=beginning, SHA256=ending, 全32金融再生=0, base読取=0,
        activity正式cache読取=0, 全raw読取=0, API取得=0, 実注文=0,
        限界='準備済みbaseとreference signalの金融接口検査のみ。正式活動の数又は安定黒字を認定しない。Dは旧prepared trend_width、Sは旧設定bpと保存始値/呼値から算定。受付外を含むpulseを旧executeの同じ受付で拒否。')
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査件数=COUNTS, 実数量例数=len(quantities),
                         証跡SHA256=hashlib.sha256(target.read_bytes()).hexdigest()), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        folder = HERE / ('金融接口人工False_' + time.strftime('%Y%m%d_%H%M%S'))
        folder.mkdir(exist_ok=False)
        sources = {}
        for name in ('finance_artificial.py', 'finance_adapter.py'):
            content = (HERE / name).read_bytes()
            (folder / name).write_bytes(content)
            sources[name] = hashlib.sha256(content).hexdigest()
        (folder / 'False.json').write_text(json.dumps(dict(全合格=False, 例外=str(error), traceback=traceback.format_exc(),
            完了確認件数=COUNTS, 原sourceSHA256=sources, 全32金融再生=0), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        raise
