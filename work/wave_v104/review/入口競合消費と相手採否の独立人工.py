"""自己根拠の一回消費と相手gateの採否を、金融を呼ばず反証する。"""

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
    機能: 新104の小さい入口APIを固有名で読み込む。
    引数: name(str)は識別名、path(Path)は新source。
    返り値: objectはモジュール。保存入力や金融は呼び出さない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def sha(path: Path) -> str:
    """
    機能: 直接読んだ小さいsourceの指紋を保存する。
    引数: path(Path)はsource又は自身の人工。
    返り値: strはSHA256。旧原本や金融台帳は読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ----------------------------------------


def competition_fixture(center: float, reflected: bool) -> tuple[dict, dict]:
    """
    機能: 消費済み競合・新根拠だけ支持・複数同方向を固定9行へ作る。
    引数: center(float)は人工価格、reflected(bool)は買売の鏡像。
    返り値: tuple[dict,dict]は人工accountとraw。未来値は使わない。
    """
    n = 9
    raw = dict(raw_seq=np.arange(100, 100+n, dtype=np.int64), price_time_s=np.arange(n, dtype=float),
               qualified=np.ones(n, bool))
    schedule = {
        'C': [(0, 1, 0, 5), (1, 1, 0, 5), (2, 1, 0, 5), (3, 1, 0, 5),
              (5, 1, 5, 3), (6, 1, 5, 3), (7, 1, 7, 4), (8, -1, 8, -3)],
        'R': [(1, 1, 1, -5), (2, 1, 1, -5), (3, -1, 3, 0), (4, -1, 3, 0),
              (5, -1, 3, 0), (7, 1, 7, 1), (8, -1, 8, 2)]}
    packets, pulses = {}, {}
    for family, transitions in schedule.items():
        ready, anchor = np.zeros((n, 2), bool), np.full((n, 2), -1, np.int64)
        events, event_anchors, original_rows, seen = [], [], [], set()
        for row, initial_side, origin, distance in transitions:
            side = -initial_side if reflected else initial_side
            column = 0 if side == 1 else 1
            ready[row, column], anchor[row, column] = True, int(raw['raw_seq'][origin])
            key = origin, side
            if key in seen:
                continue
            seen.add(key)
            event = np.zeros(25)
            event[0], event[2] = row, side
            event[6:12] = origin
            level = center-distance if reflected else center+distance
            # C列17を支持に取り違えれば、この人工は失敗する。
            event[15], event[17] = (level, center+123) if family == 'C' else (center+456, level)
            events.append(event)
            event_anchors.append(int(raw['raw_seq'][origin]))
            original_rows.append((row, side, origin))
        packet = dict(config=dict(family=family), qualified=np.ones(n, bool), ready=ready,
            anchor_raw_seq=anchor, events=np.asarray(events), event_anchor_raw_seq=np.array(event_anchors, np.int64))
        packets[family+'1'] = packet
        event = np.zeros(n, np.int8)
        decisions = []
        for row, side, origin in original_rows:
            event[row] = side
            intent = side if family == 'C' else -side
            decisions.append(dict(row=row, side=side, raw_seq=int(raw['raw_seq'][row]),
                episode=(family, intent, int(raw['raw_seq'][origin]))))
        pulses[family+'_OWN'] = dict(event=event, decisions=decisions)
    return dict(packets=packets, pulses=pulses), raw


def peer_fixture(state: int, fresh: bool) -> tuple[dict, dict, dict, dict]:
    """
    機能: 既知支持・反対・中立・曖昧・不明・古い支持のAPI境界を作る。
    引数: state(int)は独立窓で検査済の分類、fresh(bool)は相手age資格。
    返り値: tuple[dict,dict,dict,dict]は自己・相手・窓・選択。金融は含まない。
    """
    own = dict(price_time_s=np.array([100.]))
    peer = dict(raw_seq=np.array([90, 100], np.int64), price_time_s=np.array([89., 99.]),
                bid=np.array([1000., 1001.]), ask=np.array([1001., 1002.]))
    windows = {}
    for window in (3, 10, 30):
        value = dict(direction_t1=np.array([3, state], np.int8),
            unknown_reason=np.array([1, 1 if state == 3 else 0], np.uint16),
            ambiguous_spread=np.array([False, state == 2]), ambiguous_sign=np.zeros(2, bool),
            bid_change_ticks=np.array([np.nan, 1.]), ask_change_ticks=np.array([np.nan, 1.]),
            reference_raw_row=np.array([-1, 0], np.int64), reference_public_index=np.array([-1, 0], np.int64))
        if window == 10:
            value['direction_t2'] = value['direction_t1'].copy()
        windows[str(window)] = value
    selection = dict(public_indexes=np.array([1], np.int64), rows=np.array([1], np.int64),
                     ages=np.array([1. if fresh else 16.]), fresh=np.array([fresh]))
    return own, peer, dict(windows=windows), selection


# ----------------------------------------


def main() -> None:
    """
    機能: U競合消費、19gate買売採否、同原行normal投影を独立期待値で検査する。
    引数: なし。
    返り値: None。reviewへ小JSONを保存する。正式素材、金融、APIは読まない。
    """
    paths = [ROOT/'peer/core.py', ROOT/'peer/api.py', ROOT/'peer/prices.py', ROOT/'catalog.py', Path(__file__)]
    before = {str(path.relative_to(ROOT)): sha(path) for path in paths}
    api = load('104独立入口接口', ROOT/'peer/api.py')
    core = api.core
    union_checks, single_checks, gate_checks = 0, 0, 0
    examples = []
    for symbol, center in (('TOPIX', 4000.), ('NK225', 60000.)):
        for reflected in (False, True):
            account, raw = competition_fixture(center, reflected)
            result = core.union_candidates(account, raw)
            assert [value['row'] for value in result] == [0, 1, 4, 6, 7, 8]
            directions = [1, 1, -1, 1, 1, -1]
            supports = [center+5, center-5, center, center+3, center+4, center-3]
            for value, side, support in zip(result, directions, supports):
                if reflected:
                    side, support = -side, 2*center-support
                assert value['side'] == side and value['support_price'] == support
                union_checks += 1
            assert len(result[1]['episodes']) == 1 and len(result[1]['competition_ready_episodes']) == 2
            assert len(result[4]['episodes']) == len(result[5]['episodes']) == 2
            all_episodes = [tuple(ep) for value in result for ep in value['episodes']]
            assert len(all_episodes) == len(set(all_episodes))
            for family in ('C', 'R'):
                single = core.single_candidates(account, raw, family)
                original = account['pulses'][family+'_OWN']
                assert [v['row'] for v in single] == [v['row'] for v in original['decisions']]
                for value in single:
                    assert value['self_lineages'][0]['support_price'] == value['support_price']
                    single_checks += 1
            examples.append(dict(商品=symbol, 買売鏡像=reflected,
                U候補原行=[value['row'] for value in result],
                説明='行3と5は消費済みreadyの反対方向で保留。行1の新R根拠へ消費済みCの近い支持を混ぜない。'))
    configs = core.entries()
    assert len(configs) == 19
    for config in configs:
        gate = config['gate']
        for side in (1, -1):
            for source_state, fresh in ((1, True), (-1, True), (0, True), (2, True), (3, True), (1, False), (-1, False)):
                own, peer, feature, selection = peer_fixture(source_state, fresh)
                result = api.gate_decision(dict(row=0, side=side), gate, own, peer, feature, selection)
                state = source_state if fresh else 3
                support = state == side
                neutral = state == 0
                expected = True if gate == 'OWN' else support or (gate.startswith('N') and neutral)
                assert result['accepted'] == expected, (config['id'], side, source_state, fresh)
                assert result['peer_used'] == (gate != 'OWN')
                if gate != 'OWN':
                    specification = api.prices.gate_spec(gate)
                    assert result['peer']['window_seconds'] == (10 if gate == 'P10T2' else int(gate[1:]))
                    assert specification['threshold'] == (2 if gate == 'P10T2' else 1)
                    assert result['status'] == ('SUPPORT' if state == side else 'OPPOSE' if state == -side else api.prices.STATUS_NAMES[state])
                gate_checks += 1
            own, peer, feature, selection = peer_fixture(1, True)
            selection = dict(public_indexes=np.array([-1], np.int64), rows=np.array([-1], np.int64),
                             ages=np.array([np.nan]), fresh=np.array([False]))
            result = api.gate_decision(dict(row=0, side=side), gate, own, peer, feature, selection)
            assert result['accepted'] == (gate == 'OWN')
            gate_checks += 1
    # 正常でない候補を後の正常原行へ移さない直接投影。
    own = dict(raw_seq=np.array([100, 101, 102], np.int64), price_time_s=np.array([100., 101., 102.]),
        qualified=np.ones(3, bool), entry_reset=np.zeros(3, bool), entry_quality=np.array([False, True, True]),
        execution_to_raw_index=np.array([1, 2], np.int64), normal_execution_row=np.array([-1, 0, 1], np.int64))
    normal = dict(entry_quality=np.ones(2, bool), entry_reset=np.zeros(2, bool))
    candidate = dict(row=0, raw_seq=100, price_time_s=100., side=1, support_price=1000.,
        self_lineages=[dict(family='C', anchor_raw_seq=100, support_price=1000.)])
    projected = api.filter_case(dict(id='C_OWN', gate='OWN'), [candidate], own, {}, {}, {}, normal)
    assert projected['raw']['event'][0] == 1 and not projected['normal']['event'].any()
    assert projected['normal']['decisions'] == [] and len(projected['candidates']) == 1
    assert projected['raw']['entry_id'] == projected['normal']['entry_id'] == 'C_OWN'
    np.testing.assert_array_equal(projected['normal']['execution_to_raw_index'], own['execution_to_raw_index'])
    after = {str(path.relative_to(ROOT)): sha(path) for path in paths}
    assert before == after, '人工中にsourceが変更されました。'
    proof = dict(全合格=True, scope='104金融前の入口APIだけ。実金融成績や全状態の合格を意味しない。',
        検査件数=dict(U候補独立期待値=union_checks, 同初回自己候補=single_checks,
            全19gate買売採否=gate_checks, 非normal未来移動禁止=1), SHA256=before,
        競合の例=examples, 結論='消費済みreadyは反対方向競合に残り、新支持には採用されない。UNKNOWN/AMBIGUOUSはN/Pとも拒否する。',
        実行=dict(正式104金融=0, 原本読取=0, 保存cache読取=0, API=0, 実注文=0))
    target = HERE/'入口競合消費と相手採否の独立人工.json'
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査件数=proof['検査件数'], 証跡=str(target), SHA256=sha(target)), ensure_ascii=False))


if __name__ == '__main__':
    main()
