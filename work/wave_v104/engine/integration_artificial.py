"""最終peer normal接口をO/B/Tへ直接結び、共通入口資格を人工だけで確認する。"""

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np

import interface


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PEER = HERE.parent / 'peer'


def old_signal(record: dict, opening: float) -> dict:
    """
    機能: 小さい人工normal時刻に対応した旧出口用の準備済み信号を作る。
    引数: record(dict)、opening(float)は人工保存始値。
    返り値: dict。入口は後で同じpeer normal列へ置換される。
    """
    n, tick = len(record['seq']), record['tick']
    grid = np.arange(300., record['limit'] + 5., 5.)
    mapped = np.full(n, -1, np.int32)
    for index, stamp in enumerate(grid):
        row = int(np.searchsorted(record['time_s'], stamp, side='left'))
        if row < n and record['time_s'][row] - stamp <= 5.:
            mapped[row] = index
    return dict(grid=grid, mapped=mapped, quality=np.ones(n, bool), reset=np.zeros(n, bool), event=np.zeros(n, np.int8),
        mode=np.zeros(len(grid), np.int8), trend_width=max(2, math.ceil(opening * .004 / tick - 1e-10)) * tick,
        entry_j2_long=np.zeros(len(grid), bool), entry_j2_short=np.zeros(len(grid), bool),
        wait_opposite_long=np.ones(len(grid), bool), wait_opposite_short=np.ones(len(grid), bool))


def main() -> None:
    """
    機能: 実計算した人工C/R状態から、最終19入口と旧O及び新B/Tを閉じて接続する。
    引数: なし。
    返り値: None。原本・正式cache・新104金融を読まず結合人工証跡を保存する。
    """
    target = HERE / '19入口normalとO及び支持出口の結合人工.json'
    assert not target.exists()
    fixture_path, state_path = HERE / 'peer_fixture_snapshot.py', HERE / 'state_fixture_source.py'
    assert fixture_path.read_bytes() == (PEER / 'artificial.py').read_bytes()
    assert state_path.read_bytes() == (PEER / 'state_fixture_source.py').read_bytes()
    refs = [Path(__file__), HERE / 'core.py', HERE / 'interface.py', HERE / 'adapter.py', HERE / 'old_finance_snapshot.py',
        fixture_path, state_path, PEER / 'api.py', PEER / 'core.py', PEER / 'prices.py', PEER / 'artificial.py',
        HERE.parent / 'catalog.py', HERE.parent / '数値設計案.json']
    before = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in refs}
    api = interface.module('104結合人工のpeer接口', PEER / 'api.py')
    sys.modules['api'] = api
    fixtures = interface.module('104結合人工の読取peerfixture', PEER / 'artificial.py')
    fixtures.STATE = interface.module('104結合人工の専用状態複製', state_path)
    counts = dict(人工状態素材=0, 商品正常接続=0, 根19入口shape=0, 三出口共通入口列=0,
                  同一入口判断及び実fill=0, 原seq及び当時支持lineage=0, 不明入口boolの共通拒否=0)
    for family in ('C', 'R'):
        for reflect in (False, True):
            for tick in (.5, 10.):
                payload, execution = fixtures.activity_fixture(family, reflect, tick)
                prepared_peer = api.prepared_session(payload, execution)
                counts['人工状態素材'] += 1
                for symbol, source_record in execution.items():
                    if tick != (.5 if symbol == 'TOPIX' else 10.):
                        continue
                    record = dict(source_record, 人工素材=True)
                    opening = float(record['price'][0])
                    prepared = dict(record=record, signal=old_signal(record, opening), reference_open=opening)
                    counts['商品正常接続'] += 1
                    for ident, per_symbol in prepared_peer['cases'].items():
                        case = per_symbol[symbol]['normal']
                        assert case['entry_id'] == ident
                        assert len(case['event']) == len(record['seq'])
                        assert case['execution_to_raw_index'].dtype == np.int64
                        counts['根19入口shape'] += 1
                    for ident in (family + '_OWN', family + '_N10', family + '_P10', 'U_OWN'):
                        case = prepared_peer['cases'][ident][symbol]['normal']
                        output = {}
                        for exit_id in ('O', 'B2', 'T2'):
                            signal, _ = interface.connect(prepared, case, exit_id)
                            assert np.array_equal(signal['event'], case['event'])
                            assert np.array_equal(signal['entry_quality'], case['entry_quality'])
                            assert np.array_equal(signal['entry_reset'], case['entry_reset'])
                            counts['三出口共通入口列'] += 1
                            output[exit_id] = interface.play(prepared, case, exit_id, finish=False, python=True)
                        entries = {key: value['orders'][value['orders'][:, 7] == 1] for key, value in output.items()}
                        for name in ('B2', 'T2'):
                            for column in (0, 1, 4, 5, 6, 9, 10, 11):
                                np.testing.assert_array_equal(entries['O'][:, column], entries[name][:, column])
                        counts['同一入口判断及び実fill'] += 1
                        for name, value in output.items():
                            for diagnostic in value['raw_entry_diagnostics']:
                                row = diagnostic['decision_row']
                                original = next(decision for decision in case['decisions'] if decision['row'] == row)
                                assert diagnostic['decision_raw_seq'] == original['raw_seq']
                                assert diagnostic['episode']['support_price'] == original['support_price']
                                assert diagnostic['episode']['self_lineages'] == original['self_lineages']
                                counts['原seq及び当時支持lineage'] += 1
                        if np.any(case['event']):
                            bad = deepcopy(case)
                            bad['entry_quality'][:] = False
                            bad['entry_reset'][:] = True
                            for exit_id in ('O', 'B2', 'T2'):
                                rejected = interface.play(prepared, bad, exit_id, finish=False, python=True)
                                assert not len(rejected['orders'])
                                counts['不明入口boolの共通拒否'] += 1
    after = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in refs}
    assert before == after
    proof = dict(全合格=True, 人工専用=True, 検査件数=counts, 開始終端source一致=True,
        開始SHA256=before, SHA256=after, 新104正式金融=0, 正式activity読取=0, 原本読取=0, API取得=0,
        契約='api.prepared_sessionのcases[id][symbol].normalをそのままinterface.playへ渡す。O/B/Tは同event/entry_quality/entry_resetを使う。Oはqualifiedやresetを別経路で再生成しない。',
        範囲='小人工53前後の原行・finish=False。TOPIXは0.5呼値、NKは10呼値のみを旧Oにも渡す。入口とlineageの結合確認であり、正式場末flatや収益性の検査ではない。')
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査件数=counts, 証跡SHA256=hashlib.sha256(target.read_bytes()).hexdigest()), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
