"""保存原板の少数接頭部を再抽出し、旧候補から新待機までの未来参照を独立検査する。"""

from copy import deepcopy
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import types

import numba
import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
AUDIT = WORK / 'audit'
SYMBOLS = ('TOPIX', 'NK225')
REPRESENTATIVES = ('A0_X3', 'A1_X3', 'A2_X3', 'A5_X3', 'A7_X3')
sys.dont_write_bytecode = True


def cache() -> None:
    """
    機能: 新規にコンパイルする監査キャッシュを新97の読取検査領域へ限定する。
    引数: なし。
    返り値: None。旧研究や旧入力へ書き込まない。
    """
    os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'jit')
    numba.config.CACHE_DIR = os.environ['NUMBA_CACHE_DIR']


def module(name: str, path: Path) -> object:
    """
    機能: 新本体又は検証済み旧入力関数を固有名で読み取る。
    引数: name(str)、path(Path)。
    返り値: objectは読取モジュール。main関数は呼ばない。
    """
    cache()
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    cache()
    return value


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 検査中のネットワーク接続を拒絶する。
    引数: args(tuple)、kwargs(dict)。
    返り値: None。接続を要求した場合は例外で停止する。
    """
    raise RuntimeError('保存原板の接頭部だけを検査します')


def clipped(value: object, size: int, count: int) -> object:
    """
    機能: 指定軸長を持つ配列を接頭部へ切り、源indexを再番号化しない。
    引数: value(object)、size/count(int)。
    返り値: objectは切断した構造。その他の値は読み取りのまま共有する。
    """
    if isinstance(value, dict):
        return {key: clipped(item, size, count) for key, item in value.items()}
    if isinstance(value, np.ndarray) and value.ndim and len(value) == size:
        return value[:count].copy()
    return value


def raw_variants(record: dict, count: int, profiles: dict, board: object, instant: object) -> tuple[dict, dict]:
    """
    機能: 保存原本を保持seqの順に読み、原板及び未来価格・同時計後続の三系統を再抽出する。
    引数: record(dict)、count(int)、profiles(dict)は各自己判断に対応する未来境界、board/instant(object)。
    返り値: tuple[dict,dict]は各接頭部別のready/book/snapshotと原本前方読取指紋。
    """
    session, symbol = record['session'], record['symbol']
    path = ROOT / 'book' / symbol / (session + '.jsonl')
    times, sequences = record['time_s'][:count], record['seq'][:count]
    for value in profiles.values():
        assert 0 < value['future'] < count and 0 < value['sameclock'] < count
        assert times[value['sameclock'] - 1] == times[value['sameclock']], '同clock後続を持つ接頭部を要求します'
    variants = {}
    names = ['base'] + [f'{kind}_{token}' for token in profiles for kind in ('future', 'sameclock')]
    states = {kind: board.ReplenishmentState(board.MULTIPLIER[symbol]) for kind in names}
    for kind in states:
        book = {name: np.full(count, np.nan) for name in board.FLOAT_COLUMNS}
        book.update(valid=np.zeros(count, bool), reset=np.zeros(count, bool), reset_reason=np.zeros(count, np.uint8))
        snap = {name: np.full(count, np.nan) for name in instant.SNAPSHOT_FIELDS}
        snap['valid'] = np.zeros(count, bool)
        variants[kind] = dict(book=book, snapshot=snap)
    pointer, raw_rows = 0, 0
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for sequence, line in enumerate(stream):
            if pointer == count:
                break
            h.update(line)
            raw_rows += 1
            if sequence != sequences[pointer]:
                continue
            raw = json.loads(line)
            assert datetime.fromisoformat(raw['CurrentPriceTime']).timestamp() == times[pointer]
            assert float(raw['CurrentPrice']) == record['price'][pointer]
            for kind, state in states.items():
                family, token = ('base', '') if kind == 'base' else kind.split('_', 1)
                boundary = -1 if kind == 'base' else profiles[token][family]
                shifted = ((kind.startswith('future_') and pointer >= boundary)
                           or (kind.startswith('sameclock_') and pointer >= boundary
                               and times[pointer] == times[boundary - 1]))
                current = raw
                if shifted:
                    offset = record['tick'] * 100.
                    current = dict(raw, CurrentPrice=float(raw['CurrentPrice']) + offset)
                    for label in ('Buy', 'Sell'):
                        for depth in range(1, 11):
                            name = f'{label}{depth}'
                            if isinstance(raw.get(name), dict) and isinstance(raw[name].get('Price'), (int, float)):
                                current[name] = dict(raw[name], Price=raw[name]['Price'] + offset)
                observation = board.snapshot(current)
                row, _ = state.step(observation, int(sequence), times[pointer], pointer)
                for name, number in row.items():
                    variants[kind]['book'][name][pointer] = number
                values = instant.snapshot_values(current, record['tick'])
                for name, number in values.items():
                    variants[kind]['snapshot'][name][pointer] = number
            pointer += 1
    assert pointer == count
    for kind, value in variants.items():
        value['ready'] = dict(seq=sequences.copy(), time_s=times.copy(), last=value['book']['last'].copy(),
            session=session, symbol=symbol, start=record['start'], limit=record['limit'], tick=record['tick'])
        value['record'] = clipped(record, len(record['time_s']), count)
        for key, name in (('price', 'last'), ('bid', 'bid'), ('ask', 'ask')):
            value['record'][key] = value['book'][name].copy()
        value['book'].update(seq=sequences.copy(), time_s=times.copy())
        value['snapshot'].update(seq=sequences.copy(), time_s=times.copy())
    for name in ('bid', 'ask'):
        np.testing.assert_array_equal(variants['base']['book'][name], record[name][:count])
    return variants, dict(原本=str(path.relative_to(ROOT)), 原本前方SHA256=h.hexdigest(),
        読取原行数=raw_rows, 保持原行数=count, 接頭部別={token:dict(未来開始行=value['future'],
        同clock先頭原seq=int(sequences[value['sameclock'] - 1]),
        同clock未来原seq=int(sequences[value['sameclock']]),
        時計=float(times[value['sameclock'] - 1])) for token,value in profiles.items()})


def rebuild(material: dict, session: str, extracted: dict, variants: dict, count: dict,
            grid: np.ndarray, core: object, legacy: object, signals: object, data: object) -> dict:
    """
    機能: 原本再抽出の板から共通格子・J1発火・密J2を再構成して新待機へ渡す。
    引数: material/extracted/variants/count(dict)、session(str)、grid(ndarray)、core/legacy/signals/data(object)。
    返り値: dictは一保存場の部分material。実行結果・損益・将来MFEを使わない。
    """
    ready, books, snapshots, prices, features = {}, {}, {}, {}, {}
    for symbol in SYMBOLS:
        key = session, symbol
        value = extracted[symbol][variants[symbol]]
        n = len(value['ready']['time_s'])
        ready[key] = clipped(value['ready'], n, count[symbol])
        books[key] = clipped(value['book'], n, count[symbol])
        snapshots[key] = clipped(value['snapshot'], n, count[symbol])
        prices[key] = clipped(value['record'], n, count[symbol])
        b = books[key]
        features[key] = dict(quality=b['valid'] & (b['bid'] > 0) & (b['ask'] > b['bid'])
            & (b['ask'] - b['bid'] <= 2 * prices[key]['tick'] + 1e-9), reset=b['reset'])
    gridded = dict(grid=grid, markets={symbol: core.market_features(grid, 1, ready[session, symbol],
        books[session, symbol], snapshots[session, symbol]) for symbol in SYMBOLS})
    ticks = {symbol: prices[session, symbol]['tick'] for symbol in SYMBOLS}
    entry = signals.session_state(gridded, ticks)
    candidate_grid = grid[::3]
    stats = {symbol: legacy.features(candidate_grid, 1, 300, 30, ready[session, symbol], books[session, symbol]) for symbol in SYMBOLS}
    candidates = {}
    for symbol in SYMBOLS:
        peer = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
        own, other = stats[symbol], stats[peer]
        valid = own['valid'] & other['valid']
        states = np.zeros(len(candidate_grid), np.int8)
        for side in (-1, 1):
            condition = (valid & (side * own['ret'] >= 3.) & (own['confirmation'] == side)
                & (side * other['ret'] >= 3.) & (side * other['short_ret'] >= 0))
            states[condition] = side
        pulse = legacy.event_pulses(candidate_grid, states, valid)
        key = session, symbol
        candidates[key] = dict(candidates=legacy.map_pulses(candidate_grid, pulse, own, other, ready[key], books[key]),
            states=states, valid=valid, pulse=pulse, own_source=own['now'], peer_source=other['now'])
    old_grid = material['grids'][session]['grid']
    grid_count = len(grid)
    lp = clipped(material['trend_prices']['I3'][session], len(old_grid), grid_count)
    lp['grid'] = grid
    lane = gridded
    return dict(prices=prices, grids={session: gridded}, features=features, legacy=candidates,
        entries={session: entry}, metadata=material['metadata'], price_lanes={'I0': {session: lane}},
        trend_prices={'I3': {session: lp}}, raw_last_records={key: material['raw_last_records'][key] for key in prices},
        execution_lp_index={key: material['execution_lp_index'][key][:count[key[1]]] for key in prices})


def compare_past(short: dict, longer: dict, cut: int, label: str) -> None:
    """
    機能: 実接頭部の公表状態・注文・候補45親を未来改変後の同区間へ照合する。
    引数: short/longer(dict)、cut(int)、label(str)。
    返り値: None。完了前のfill/netを当時既知として比較しない。
    """
    for name in ('curve', 'source_curve', 'target_trace', 'range_state_trace', 'risk_state_trace',
                 'price_source_trace', 'trend_exit_state_trace', 'watch_state_trace'):
        np.testing.assert_array_equal(short[name], longer[name][:cut], err_msg=label+'/'+name)
    for name in ('orders', 'events', 'loss_reentry_events', 'entry_wait_events'):
        np.testing.assert_array_equal(short[name], longer[name][longer[name][:, 0] < cut], err_msg=label+'/'+name)
    for name, column in (('trades', 3), ('trend_parent_diagnostics', 2)):
        np.testing.assert_array_equal(short[name], longer[name][longer[name][:, column] < cut], err_msg=label+'/'+name)
    parents = longer['entry_parent_diagnostics'][longer['entry_parent_diagnostics'][:, 28] < cut].copy()
    for p in parents:
        if np.isfinite(p[37]) and p[37] >= cut:
            p[37:42] = np.nan
        if np.isfinite(p[42]) and p[42] >= cut:
            p[42:44] = np.nan
    np.testing.assert_array_equal(short['entry_parent_diagnostics'], parents, err_msg=label+'/公表45親')


def main() -> None:
    """
    機能: 前16デイと後15ナイトの実候補後を切り、原板未来及び同時計後続へ毒を入れる。
    引数: なし。
    返り値: Noneは指紋付き因果証跡。完結した新条件セッションや正式損益を計算しない。
    """
    socket.socket.connect = deny
    socket.create_connection = deny
    data = module('実待機接頭の入力97', WORK / 'data.py')
    strategy = module('実待機接頭の戦略97', WORK / 'strategy.py')
    catalog = module('実待機接頭の条件97', WORK / 'catalog.py')
    core = module('旧格子77の実接頭再生成97', ROOT / 'work/wave_v77/inputs/core.py')
    instant = core.LEGACY
    board = module('旧原板57の実接頭再生成97', ROOT / 'work/wave_v57/features.py')
    package = types.ModuleType('inputs')
    package.__path__ = []
    old_inputs, old_core = sys.modules.get('inputs'), sys.modules.get('inputs.core')
    sys.modules['inputs'] = package
    sys.modules['inputs.core'] = module('旧同期75の実接頭再生成97', ROOT / 'work/wave_v75/inputs/core.py')
    try:
        legacy = module('旧J1の実接頭再生成97', ROOT / 'work/wave_v75/signals.py')
    finally:
        for name, previous in (('inputs', old_inputs), ('inputs.core', old_core)):
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    signals = module('旧密J2の実接頭再生成97', ROOT / 'work/wave_v77/signals.py')
    sys.modules['common'] = module('common', AUDIT / 'common.py')
    cache()
    sys.modules['watch'] = module('watch', AUDIT / 'watch.py')
    independent = module('独立watchと出口の実接頭照合97', AUDIT / 'independent.py')
    conditions = {value['id']: value for value in catalog.catalog()}
    print('保存入力と旧候補だけを読取開始。正式損益は開きません。', flush=True)
    material = data.load_inputs()
    prepared = strategy.prepare(material, conditions['A0_X3'])
    sessions = material['metadata']['sessions']
    selected = [next(s for s in sessions[:16] if s.endswith('_Day') and all(np.any(prepared[s, m]['signal']['event']) for m in SYMBOLS)),
                next(s for s in sessions[16:] if s.endswith('_Night') and all(np.any(prepared[s, m]['signal']['event']) for m in SYMBOLS))]
    rows, raw_proofs = [], []
    counts = dict(実接頭部=0, 独立待機出口=0, 自己未来源=0, 相手未来源=0, 自己同時計後続=0,
                  相手同時計後続=0, 実待機原行=0, 実候補受理=0, 実新規予約=0)
    for session in selected:
        boundaries, starts, repeated_rows = {}, [], {}
        for symbol in SYMBOLS:
            value = prepared[session, symbol]
            r, signal = value['record'], value['signal']
            first = int(np.flatnonzero(signal['event'])[0])
            starts.append(r['time_s'][first])
            repeated_rows[symbol] = np.flatnonzero(r['time_s'][1:] == r['time_s'][:-1])
        start = max(starts)
        clocks = {}
        for symbol in SYMBOLS:
            r = prepared[session, symbol]['record']
            choices = [repeated_rows[symbol][(r['time_s'][repeated_rows[symbol]] > start + offset)
                & (r['time_s'][repeated_rows[symbol]] < start + offset + 50.)] for offset in (5., 90.)]
            assert all(len(values) for values in choices), '同clock接頭境界がありません'
            boundaries[symbol] = [int(values[0]) + 1 for values in choices]
            clocks[symbol] = [r['time_s'][cut-1] for cut in boundaries[symbol]]
            assert clocks[symbol][-1] + 25. < r['limit'] - 300.
        end_clock = max(clock for values in clocks.values() for clock in values) + 25.
        extracted = {}
        for symbol in SYMBOLS:
            record = prepared[session, symbol]['record']
            count = int(np.searchsorted(record['time_s'], end_clock, side='right'))
            profiles = {}
            for target in SYMBOLS:
                for cut_index, cut_clock in enumerate(clocks[target]):
                    token = target + str(cut_index)
                    if target == symbol:
                        profiles[token] = dict(future=boundaries[symbol][cut_index], sameclock=boundaries[symbol][cut_index])
                    else:
                        future = int(np.searchsorted(record['time_s'], cut_clock, side='left'))
                        after = repeated_rows[symbol][record['time_s'][repeated_rows[symbol]] >= cut_clock]
                        assert len(after)
                        profiles[token] = dict(future=future, sameclock=int(after[0]) + 1)
            extracted[symbol], raw_proof = raw_variants(record, count, profiles, board, instant)
            raw_proofs.append(raw_proof)
            print(session+'/'+symbol+': 原本から前方特徴と自己未来源・同clock変形を再抽出', flush=True)
        grid = material['grids'][session]['grid']
        grid = grid[grid < end_clock]
        full_count = {s: len(extracted[s]['base']['ready']['time_s']) for s in SYMBOLS}
        rebuilt = rebuild(material, session, extracted, {s:'base' for s in SYMBOLS}, full_count, grid, core, legacy, signals, data)
        base_prepared = strategy.prepare(rebuilt, conditions['A0_X3'])
        for symbol in SYMBOLS:
            key = session, symbol
            n = full_count[symbol]
            for name in ('event', 'mapped', 'quality', 'reset'):
                np.testing.assert_array_equal(base_prepared[key]['signal'][name], prepared[key]['signal'][name][:n])
            for name in ('entry_j2_long', 'entry_j2_short', 'wait_opposite_long', 'wait_opposite_short', 'entry_peer_bbo', 'mode'):
                np.testing.assert_array_equal(base_prepared[key]['signal'][name], prepared[key]['signal'][name][:len(grid)])
        for symbol in SYMBOLS:
            key = session, symbol
            peer = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
            for cut_index, cut in enumerate(boundaries[symbol]):
                clock = prepared[key]['record']['time_s'][cut-1]
                small_count = {symbol: cut, peer: int(np.searchsorted(extracted[peer]['base']['ready']['time_s'], clock, side='right'))}
                small_grid = grid[grid <= clock]
                shortened = rebuild(material, session, extracted, {s:'base' for s in SYMBOLS}, small_count, small_grid, core, legacy, signals, data)
                short_prepared = strategy.prepare(shortened, conditions['A0_X3'])
                for ident in REPRESENTATIVES:
                    config = conditions[ident]
                    short = strategy.play(config, key, short_prepared, finish=False)
                    v = short_prepared[key]
                    complete_view = dict(short, trend_parent_diagnostics=short['trend_parent_diagnostics'][np.isfinite(short['trend_parent_diagnostics'][:, 2])])
                    check = independent.compare(v['record'], v['signal'], config, v['reference_open'], complete_view)
                    counts['独立待機出口'] += 1
                    longer = strategy.play(config, key, base_prepared, finish=False)
                    compare_past(short, longer, cut, ident+'/切断')
                    counts['実接頭部'] += 1
                    counts['実待機原行'] += int(np.count_nonzero(short['watch_state_trace'][:, 0]))
                    counts['実候補受理'] += check['候補受理']
                    counts['実新規予約'] += check['触発']
                    token = symbol + str(cut_index)
                    for changed_symbol, kind, name in ((symbol, f'future_{token}', '自己未来源'),
                        (peer, f'future_{token}', '相手未来源'), (symbol, f'sameclock_{token}', '自己同時計後続'),
                        (peer, f'sameclock_{token}', '相手同時計後続')):
                        modes = {s:'base' for s in SYMBOLS}
                        modes[changed_symbol] = kind
                        changed_material = rebuild(material, session, extracted, modes, full_count, grid, core, legacy, signals, data)
                        changed_prepared = strategy.prepare(changed_material, conditions['A0_X3'])
                        changed = strategy.play(config, key, changed_prepared, finish=False)
                        compare_past(short, changed, cut, ident+'/'+name)
                        counts[name] += 1
                    rows.append(dict(場=session, 商品=symbol, 条件=ident, 接頭部行数=cut, 時計=float(clock),
                        独立検査=check, 切断一致=True, 原本未来四変形一致=True))
                print(session+'/'+symbol+f': cut{cut}まで5代表の独立待機出口と原本未来が一致', flush=True)
    assert counts['実待機原行'] > 0 and counts['実候補受理'] > 0
    paths = [Path(__file__), WORK / 'engine.py', WORK / 'strategy.py', WORK / 'catalog.py', WORK / 'data.py',
        AUDIT / 'common.py', AUDIT / 'watch.py', AUDIT / 'independent.py',
        ROOT / 'work/wave_v57/features.py', ROOT / 'work/wave_v76/inputs/core.py',
        ROOT / 'work/wave_v77/inputs/core.py', ROOT / 'work/wave_v77/signals.py',
        ROOT / 'work/wave_v75/signals.py', ROOT / 'work/wave_v75/inputs/core.py']
    proof = dict(全合格=True, 代表=list(REPRESENTATIVES), 対象場=selected, 検査件数=counts,
        原本前方再抽出=raw_proofs, 旧候補と密J2及び公表BBOの再生成一致=True,
        未完親接口='独立出口の27列は完了親だけ。実orders・23列保有状態・45列入口親・予約は未完のまま保持。未来で埋まる45列fill/netは接頭部公表時点へ射影して比較。',
        独立LP='P0で使用しないI3価格laneは既存因果素材をそのまま共有し、原本未来の新規分類へ流用しない。活動する中値・板flow・Q・J1候補・密J2・執行BBOは再生成。',
        限界='代理時計と保存seqの因果性の検査。真の受信時刻や実ミニ・マイクロ全量約定の証明ではない。',
        完結した新条件口座=0, 正式97損益閲覧=0, 正式97損益実行=0, API取得=0, 実注文=0,
        SHA256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    destination = HERE / '5代表の実待機接頭と原本再生成及び自己相手未来源と同clock未来不変.json'
    destination.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps({key:value for key,value in proof.items() if key not in ('SHA256', '原本前方再抽出')},ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
