"""旧quote資格の用途分離とO/B/Tの同入口接続を、金融非実行で検査する。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def load(name: str, path: Path) -> object:
    """
    機能: 新104の小さい入口又は出口接口を固有名で読む。
    引数: name(str)、path(Path)は読み込むソース。
    返り値: objectは読取モジュール。保存市場や正式金融は呼ばない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def sha(path: Path) -> str:
    """
    機能: 小さい直接sourceと既に完成した私有証跡の指紋を作る。
    引数: path(Path)は対象資料。
    返り値: strはSHA256。原本と巨大台帳は再hashしない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ----------------------------------------


def quote_fixture(symbol: str, case: str) -> tuple[dict, dict]:
    """
    機能: 数量不明・quote不明・非normalを分ける3原行を作る。
    引数: symbol/case(str)は商品と固定境界。
    返り値: tuple[dict,dict]は人工活動accountと旧執行record。
    """
    base, tick = (4000., .5) if symbol == 'TOPIX' else (60000., 10.)
    n = 3
    mapping = np.array([0, 2] if case == '非normal' else [0, 1, 2], np.int64)
    reverse = np.full(n, -1, np.int32)
    reverse[mapping] = np.arange(len(mapping), dtype=np.int32)
    times, seq = np.array([0., 5., 10.]), np.array([100, 101, 102], np.int64)
    bid, ask = base+tick*np.arange(n), base+tick*(np.arange(n)+1)
    source = dict(raw_seq=seq, price_time_s=times, volume_time_s=times.copy(), qualified=np.ones(n, bool),
        execution_to_raw_index=mapping, normal_execution_row=reverse)
    for name in ('price_reset_reason', 'depth_reset_reason', 'lp_reset_reason', 'volume_reset_reason'):
        source[name] = np.zeros(n, np.uint16)
    if case == '量だけの欠測':
        source['qualified'][1], source['volume_reset_reason'][1] = False, 16
    if case == '数値BBO不正':
        ask[1] = bid[1]
    record = dict(seq=seq[mapping].copy(), time_s=times[mapping].copy(), bid=bid[mapping].copy(),
        ask=ask[mapping].copy(), price=(bid[mapping]+ask[mapping])/2,
        start=0., end=10., limit=10., tick=tick, symbol=symbol, session='独立接口人工')
    execution = dict(record, quote_valid=np.ones(len(mapping), bool), price_valid=np.ones(len(mapping), bool))
    if case == '旧quote資格だけ不正':
        execution['quote_valid'][1] = False
    return dict(source=source, normal_record=record, item=dict(symbol=symbol, tick=tick)), execution


def capture_fixture(symbol: str) -> tuple[dict, dict]:
    """
    機能: 旧common資格と新normal資格が異なる接続専用人工を作る。
    引数: symbol(str)は商品。
    返り値: tuple[dict,dict]はpreparedとnormal_case。金融実行素材ではない。
    """
    base, tick = (4000., .5) if symbol == 'TOPIX' else (60000., 10.)
    n = 4
    record = dict(symbol=symbol, seq=np.arange(900, 900+n, dtype=np.int64), time_s=np.array([300., 301., 302., 1000.]),
        bid=np.full(n, base), ask=np.full(n, base+tick), tick=tick, start=0., limit=1000., end=1000.,
        quote_valid=np.ones(n, bool), price_valid=np.ones(n, bool), 人工素材=True)
    old = dict(trend_width=base*.004, quality=np.ones(n, bool), reset=np.zeros(n, bool), event=np.zeros(n, np.int8))
    event, support = np.array([1, 0, -1, 0], np.int8), np.array([base, np.nan, base+tick, np.nan])
    mapping = np.array([10, 11, 12, 13], np.int64)
    case = dict(entry_id='C_OWN', event=event, support_price=support,
        entry_quality=np.array([False, True, True, True]), entry_reset=np.array([True, False, False, False]),
        execution_to_raw_index=mapping,
        decisions=[dict(row=row, normal_row=row, raw_row=int(mapping[row]), raw_seq=int(record['seq'][row]),
            side=int(event[row]), support_price=float(support[row])) for row in (0, 2)])
    return dict(record=record, signal=old, reference_open=base), case


# ----------------------------------------


def main() -> None:
    """
    機能: 最新quote資格とO/B/T同入口契約を実execute非実行で独立に照合する。
    引数: なし。
    返り値: None。reviewへ小JSONを保存する。原本、cache、金融は読まない。
    """
    paths = [ROOT/'peer/core.py', ROOT/'peer/prices.py', ROOT/'engine/interface.py', ROOT/'engine/core.py',
        ROOT/'engine/adapter.py', ROOT/'engine/old_finance_snapshot.py', ROOT/'catalog.py', Path(__file__)]
    before = {str(path.relative_to(ROOT)): sha(path) for path in paths}
    core, prices = load('104旧quote独立復元', ROOT/'peer/core.py'), load('104旧quote独立窓', ROOT/'peer/prices.py')
    interface = load('104旧quote独立金融接口', ROOT/'engine/interface.py')
    counts = dict(正常quote用途分離=0, 相手途中不明=0, mandatory資格欠測拒否=0,
                  O_B_T同一資格接続=0, O直接旧execute捕捉=0)
    for symbol in ('TOPIX', 'NK225'):
        for case in ('正常', '旧quote資格だけ不正', '量だけの欠測', '数値BBO不正', '非normal'):
            account, execution = quote_fixture(symbol, case)
            actual = core.restore_account(account, execution)
            raw = actual['raw']
            expected_bbo = np.array([True, case in ('正常', '量だけの欠測'), True])
            np.testing.assert_array_equal(raw['bbo_valid'], expected_bbo)
            np.testing.assert_array_equal(raw['entry_quality'], raw['qualified'] & expected_bbo)
            feature = prices.build(raw, account['item'], core.publications(raw),
                dict(max_public_gap_seconds=15., baseline_extra_age_seconds=15., spread_max_ticks=2., spread_increment_ticks=1.))
            state = feature['windows']['10']['direction_t1'][-1]
            assert state == (1 if case in ('正常', '量だけの欠測') else 3)
            counts['正常quote用途分離'] += 1
            counts['相手途中不明'] += 1
            for required in ('quote_valid', 'price_valid'):
                missing = dict(execution)
                del missing[required]
                missing['valid'] = np.ones(len(execution['seq']), bool)
                try:
                    core.restore_account(account, missing)
                except AssertionError:
                    counts['mandatory資格欠測拒否'] += 1
                else:
                    raise AssertionError('旧valid列で必須列の欠測を救済しました。')
        prepared, case = capture_fixture(symbol)
        for exit_id in ('O', 'B1', 'B2', 'B4', 'T2', 'T4'):
            signal, config = interface.connect(prepared, case, exit_id, quantity=1)
            np.testing.assert_array_equal(signal['event'], case['event'])
            np.testing.assert_array_equal(signal['entry_quality'], case['entry_quality'])
            np.testing.assert_array_equal(signal['entry_reset'], case['entry_reset'])
            counts['O_B_T同一資格接続'] += 1
        old = interface.module('104専用の不変103金融snapshot', ROOT/'engine/old_finance_snapshot.py')
        adapter = old.adapter
        engine = adapter.module('103新入口の読取102固定出口', adapter.PREVIOUS/'engine.py')
        saved = engine.execute
        captured = []

        def capture(record: dict, signal: dict, config: dict, finish: bool = True) -> dict:
            """
            機能: 旧executeへの実引数を捕捉し、金融を実行せず空物理出力を返す。
            引数: record/signal/config(dict)、finish(bool)はinterfaceの接続契約。
            返り値: dictは診断が読める空出力。これは会計検算ではない。
            """
            assert record is prepared['record'] and finish is False
            np.testing.assert_array_equal(signal['event'], case['event'])
            np.testing.assert_array_equal(signal['quality'], case['entry_quality'])
            np.testing.assert_array_equal(signal['reset'], case['entry_reset'])
            assert signal['trend_initial_stop_width'] == prepared['reference_open']*.001
            captured.append(True)
            return dict(orders=np.zeros((0, 17)), entry_parent_diagnostics=np.zeros((0, 45)))

        try:
            engine.execute = capture
            result = interface.play(prepared, case, 'O', quantity=1, finish=False)
        finally:
            engine.execute = saved
        assert len(captured) == 1 and result['raw_entry_diagnostics'] == []
        assert result['entry_case_id'] == case['entry_id']
        counts['O直接旧execute捕捉'] += 1
    after = {str(path.relative_to(ROOT)): sha(path) for path in paths}
    assert before == after, '独立接口人工の途中でsourceが変わりました。'
    proof = dict(全合格=True, scope='quote_valid資格と最新版O/B/T接続の人工。O経済null・金融本体は既証跡とは別。',
        検査件数=counts, SHA256=before,
        結論='旧quote_valid=Falseの中間原行は相手窓UNKNOWN。量だけcommonqualified=Falseだが正常quoteは入口と用途を分ける。Oも新normal資格を旧qualifiedで再生成しない。',
        実行=dict(新104正式金融=0, 金融body実行=0, 原本読取=0, 保存cache読取=0, API=0, 実注文=0))
    target = HERE/'旧気配資格と同出口接続の独立人工.json'
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査件数=counts, 証跡=str(target), SHA256=sha(target)), ensure_ascii=False))


if __name__ == '__main__':
    main()
