"""旧入力関数を読取再利用し、新ナイトの素材だけを売買前に固定する。"""

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pickle
import socket
import sys
import traceback
import types

import numba
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SESSION = '2026-10-12_Night'
SYMBOLS = ('TOPIX', 'NK225')
JST = timezone(timedelta(hours=9))
CACHE = str(HERE / 'numba_cache')
os.environ['NUMBA_CACHE_DIR'] = CACHE
numba.config.CACHE_DIR = CACHE
CODE_NAMES = (
    'work/wave_v77/inputs/core.py', 'work/wave_v76/inputs/core.py',
    'work/wave_v77/inputs/prepare.py', 'work/wave_v8/raw_features.py',
    'work/wave_v57/features.py', 'work/wave_v56/measurement/display_changes.py',
    'work/wave_v77/signals.py', 'work/wave_v76/signals.py',
    'work/wave_v77/prepared/prepare_legacy.py', 'work/wave_v75/signals.py',
    'work/wave_v75/inputs/core.py', 'work/wave_v74/inputs/prepare_refs.py',
    'work/wave_v91/inputs/prepare.py', 'work/wave_v94/prepare_inputs_r1.py',
    'work/wave_v94/inputs_r1/core.py', 'work/wave_v94/inputs_r1/last_price.py',
    'work/wave_v94/inputs_r1/strict_board.py', 'work/wave_v95/prepare_prices.py',
    'work/wave_v95/data.py', 'work/wave_v94/data_r1.py',
)


def module(name: str, path: Path) -> object:
    """
    機能: 読取関数を専用名で接続し、旧成果へキャッシュを書かない。
    引数: name(str)、path(Path)はモジュールの名前と位置。
    返り値: objectは読取モジュール。
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    try:
        spec.loader.exec_module(value)
    finally:
        os.environ['NUMBA_CACHE_DIR'] = CACHE
        numba.config.CACHE_DIR = CACHE
    return value


DATA = module('追加ナイト専用入力の読取', HERE / 'data.py')
digest = DATA.digest


def read(path: Path) -> object:
    """
    機能: 入力及び入力指紋だけを読む。
    引数: path(Path)はJSON又はpickleの位置。
    返り値: objectは保存された入力。金融結果領域の閲覧を拒絶する。
    """
    assert not any(part in ('front', 'back', 'results', 'ledgers', 'analysis', 'review') for part in path.parts)
    with path.open('rb') as stream:
        return pickle.load(stream) if path.suffix == '.pkl' else json.load(stream)


def save(name: str, value: object) -> None:
    """
    機能: 担当する追加入力領域だけへ新規保存する。
    引数: name(str)はファイル名、value(object)は内容。
    返り値: None。完成物の上書き及び担当領域外への保存を拒絶する。
    """
    path = HERE / name
    assert path.resolve().is_relative_to(HERE.resolve()) and not path.exists(), path
    if path.suffix == '.pkl':
        with path.open('wb') as stream:
            pickle.dump(value, stream, protocol=5)
    else:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 素材準備中の外部通信と金融実行を禁止する。
    引数: args(tuple)、kwargs(dict)は呼出し引数。
    返り値: None。常に例外で停止する。
    """
    raise RuntimeError('追加入力の準備では通信、金融再生及び選定を行いません')


def equal(left: object, right: object) -> int:
    """
    機能: ネストした入力を欠損込みで厳密に照合する。
    引数: left/right(object)は辞書、配列又は値。
    返り値: intは一致した配列の個数。
    """
    if isinstance(left, dict):
        assert left.keys() == right.keys(), (left.keys(), right.keys())
        return sum(equal(left[name], right[name]) for name in left)
    if isinstance(left, np.ndarray):
        np.testing.assert_array_equal(left, right)
        return 1
    assert left == right, (left, right)
    return 0


def clipped(record: dict, count: int) -> dict:
    """
    機能: 実入力の将来行を除いた接頭部を作る。
    引数: record(dict)、count(int)は元系列と採用行数。
    返り値: dictは同じ列構造の過去だけの系列。
    """
    return {name: value[:count] if isinstance(value, np.ndarray) and value.ndim else value
            for name, value in record.items()}


def schema_equal(old: object, new: object) -> int:
    """
    機能: 旧素材と列名、型及び列形状を比較し、場の長さを同一視しない。
    引数: old/new(object)は対応する入力欄。
    返り値: intは構造一致した配列数。
    """
    if isinstance(old, dict):
        assert old.keys() == new.keys(), (old.keys(), new.keys())
        return sum(schema_equal(old[name], new[name]) for name in old)
    if isinstance(old, np.ndarray):
        assert old.dtype == new.dtype and old.ndim == new.ndim
        assert old.shape[1:] == new.shape[1:]
        return 1
    assert type(old) is type(new), (type(old), type(new))
    return 0


def artificial(last: object, trend: object) -> dict:
    """
    機能: 同時計後続、不正価格、時計欠測及び未来切断の入力資格を検算する。
    引数: last(object)は旧94独立LP抽出器、trend(object)は旧95過去価格窓。
    返り値: dictは金融再生を伴わない人工検査。
    """
    start = datetime(2000, 1, 3, 17, tzinfo=JST).timestamp()
    offsets = (-5, 0, 5, 5, 10, 15, 20, None, 30)
    rows = [(i, dict(CurrentPriceTime=None if offset is None else datetime.fromtimestamp(start + offset, JST).isoformat(),
                     CurrentPrice=None if i == 5 else 100. + i)) for i, offset in enumerate(offsets)]
    raw = last.extract_last_prices(rows, start, start + 100)
    grid = start + np.asarray([7., 12., 17., 22., 32.])
    result = trend.price_features(grid, raw)
    assert result['current']['raw_seq'].tolist() == [2, 4, -1, 6, -1]
    assert result['current']['valid'].tolist() == [True, True, False, True, False]
    assert raw['reset_reason'][-1] & 4
    prefix = last.extract_last_prices(rows[:5], start, start + 100)
    count = equal(trend.price_features(grid[:2], prefix),
                  dict(current={name: value[:2] for name, value in result['current'].items()},
                       windows={seconds: {name: value[:2] for name, value in item.items()}
                                for seconds, item in result['windows'].items()}))
    changed = [(seq, dict(raw_row, CurrentPrice=9000.) if seq >= 5 or seq == 3 else raw_row)
               for seq, raw_row in rows]
    modified = last.extract_last_prices(changed, start, start + 100)
    count += equal(trend.price_features(grid[:2], modified), trend.price_features(grid[:2], raw))
    return dict(全合格=True, 人工原行数=len(rows), 同時計後続を先頭へ代用しない=True,
                不正価格で古い正常行へ救済しない=True, 時計欠測後断裂を無視しない=True,
                接頭及び未来変更照合配列数=count, 金融再生=0)


def input_prefix_checks(core: object, signal: object, legacy: object, legacy_source: object,
                        trend: object, ready: dict, books: dict, snapshots: dict,
                        material: dict) -> list[dict]:
    """
    機能: 事前に固定した二時点で原板素材、格子、入口、独立LPの過去不変を調べる。
    引数: core/signal/legacy/legacy_source/trend(object)は旧入力関数、
        ready/books/snapshots/material(dict)は追加一場だけの入力。
    返り値: list[dict]は15分及び60分で切断した入力照合。
    """
    checks = []
    start = ready[(SESSION, 'TOPIX')]['start']
    full_grid = material['grids'][SESSION]['grid']
    full_candidates = material['trend_prices']['I3'][SESSION]['candidate_grid']
    for offset in (900., 3600.):
        cutoff = start + offset
        cuts = {key: int(np.searchsorted(value['time_s'], cutoff, side='left')) for key, value in ready.items()}
        rs = {key: clipped(value, cuts[key]) for key, value in ready.items()}
        bs = {key: clipped(value, cuts[key]) for key, value in books.items()}
        ss = {key: clipped(value, cuts[key]) for key, value in snapshots.items()}
        grid = full_grid[full_grid < cutoff]
        made = dict(grid=grid, markets={symbol: core.market_features(grid, 1, rs[(SESSION, symbol)],
                         bs[(SESSION, symbol)], ss[(SESSION, symbol)]) for symbol in SYMBOLS})
        count = equal(made, dict(grid=grid, markets={symbol: {kind:
            ({name: values[:len(grid)] for name, values in content.items()} if kind == 'current' else
             {seconds: {name: values[:len(grid)] for name, values in item.items()} for seconds, item in content.items()})
            for kind, content in material['grids'][SESSION]['markets'][symbol].items()} for symbol in SYMBOLS}))
        built = signal.build({SESSION: made}, rs)[SESSION]
        expected = material['entries'][SESSION]
        count += equal(built, {name: value[:len(grid)] if isinstance(value, np.ndarray) else
                      {sub: {field: values[:len(grid)] for field, values in item.items()} for sub, item in value.items()}
                      for name, value in expected.items()})
        candidate_grid = full_candidates[full_candidates < cutoff]
        generated = legacy.build_extra(legacy_source, candidate_grid, rs, bs, 1)
        for key, value in generated.items():
            old = material['legacy'][key]
            expected = {name: values[:len(candidate_grid)] if name != 'candidates' else
                        values[(values[:, 0] < len(candidate_grid)) & (values[:, 1] < cuts[key])]
                        for name, values in old.items()}
            count += equal(value, expected)
            raw = material['raw_last_records'][key]
            raw_cut = int(np.searchsorted(raw['time_s'], cutoff, side='left'))
            lp = trend.price_features(grid, clipped(raw, raw_cut))
            expected = material['trend_prices']['I3'][SESSION]['markets'][key[1]]
            count += equal(lp, dict(current={name: values[:len(grid)] for name, values in expected['current'].items()},
                             windows={seconds: {name: values[:len(grid)] for name, values in item.items()}
                                      for seconds, item in expected['windows'].items()}))
        checks.append(dict(cutoff=datetime.fromtimestamp(cutoff, JST).isoformat(), 格子数=len(grid),
                           切断行数={'|'.join(key): value for key, value in cuts.items()}, 一致配列数=count))
    return checks


def raw_prefix_check(extract: object, core: object, full: tuple) -> dict:
    """
    機能: 実原本の先頭15分だけを旧逐次板状態で再読取し、後続原本なしの列一致を確かめる。
    引数: extract(object)は旧77抽出部品、core(object)は旧77格子部品、full(tuple)は全場抽出。
    返り値: dictは原本接頭部からのready、板及びsnapshot全列一致の証拠。
    """
    key, ready, books, snapshots, _, _ = full
    symbol = key[1]
    rawmod = extract.module('最良気配抽出77_' + symbol, ROOT / 'work/wave_v8/raw_features.py')
    board = extract.module('逐次板抽出77_' + symbol, ROOT / 'work/wave_v57/features.py')
    state = board.ReplenishmentState(board.MULTIPLIER[symbol])
    cutoff = ready['start'] + 900.
    fields = {name: [] for name in (*board.FLOAT_COLUMNS, 'valid', 'reset', 'reset_reason')}
    instant_fields = {name: [] for name in core.LEGACY.SNAPSHOT_FIELDS}
    seqs, times, lasts, snapshot_valid = [], [], [], []
    prefix_hash = hashlib.sha256()
    scanned = 0
    with (ROOT / 'book' / symbol / (SESSION + '.jsonl')).open('rb') as stream:
        for seq, line in enumerate(stream):
            raw = json.loads(line)
            text = raw.get('CurrentPriceTime')
            if text and datetime.fromisoformat(text).timestamp() >= cutoff:
                break
            prefix_hash.update(line)
            scanned += 1
            if not text:
                continue
            stamp = datetime.fromisoformat(text).timestamp()
            if not ready['start'] <= stamp < cutoff:
                continue
            quote, _ = rawmod.parse_snapshot(raw)
            price = board.finite(raw.get('CurrentPrice'))
            if quote is None or price is None:
                continue
            value, _ = state.step(board.snapshot(raw), seq, stamp, len(seqs))
            instant = core.LEGACY.snapshot_values(raw, ready['tick'])
            seqs.append(seq)
            times.append(stamp)
            lasts.append(price)
            for name in fields:
                fields[name].append(value[name])
            for name in instant_fields:
                instant_fields[name].append(instant[name])
            snapshot_valid.append(instant['valid'])
    count = len(seqs)
    arrays = 0
    for name, value in (('seq', np.asarray(seqs, dtype=np.int64)),
                        ('time_s', np.asarray(times)), ('last', np.asarray(lasts))):
        arrays += equal(value, ready[name][:count])
    for name, values in fields.items():
        arrays += equal(np.asarray(values, dtype=books[name].dtype), books[name][:count])
    for name, values in instant_fields.items():
        arrays += equal(np.asarray(values, dtype=snapshots[name].dtype), snapshots[name][:count])
    arrays += equal(np.asarray(snapshot_valid, bool), snapshots['valid'][:count])
    assert count == np.searchsorted(ready['time_s'], cutoff, side='left')
    return dict(商品=symbol, 原本接頭行数=scanned, 採用板行数=count,
                接頭原本SHA256=prefix_hash.hexdigest(), 一致配列数=arrays,
                切断=datetime.fromtimestamp(cutoff, JST).isoformat(), 後続原本参照なし=True)


def main() -> None:
    """
    機能: 新ナイト一場の原本を登録してから、旧と同じ入力だけを隔離保存する。
    引数: なし。
    返り値: None。損益閲覧、売買再生、候補選定、API及び注文はいずれも0。
    """
    socket.socket.connect = deny
    socket.create_connection = deny
    assert not (HERE / 'metadata.json').exists(), '完成入力を上書きしません'
    source_paths = [ROOT / kind / symbol / (SESSION + extension)
                    for kind, extension in (('book', '.jsonl'), ('candle_1min', '.csv'), ('candle_5min', '.csv'))
                    for symbol in SYMBOLS]
    raw_sha = {str(path.relative_to(ROOT)): digest(path) for path in source_paths}
    code_sha = {name: digest(ROOT / name) for name in CODE_NAMES}
    code_sha.update({str(path.relative_to(ROOT)): digest(path) for path in (Path(__file__), HERE / 'data.py')})
    save('入力準備前の素材登録.json', dict(追加確認場=SESSION, 対象場数=1, 対象商品=list(SYMBOLS),
         元31場との混合=False, 原本SHA256=raw_sha, 直接使用コードSHA256=code_sha,
         素材=[dict(相対位置=str(path.relative_to(ROOT)), バイト数=path.stat().st_size,
                  最終保存=datetime.fromtimestamp(path.stat().st_mtime, JST).isoformat()) for path in source_paths],
         実接頭の事前固定秒=[900, 3600], 原本再抽出の事前固定秒=900,
         入口='旧75/77/91の原板300秒窓及び15秒気配進行。保存足CSVは指紋だけ登録し新規接続しない。',
         新場損益閲覧=0, 新場損益計算=0, 売買実行=0, 選定=0, API取得=0, 実注文=0))
    print('追加一場の原本6ファイルと直接使用コードを損益前登録しました', flush=True)

    # ----------------------------------------
    # 旧の逐次板抽出及び格子・入口関数だけを専用名で再利用する。
    core = module('追加ナイト価格格子77の読取', ROOT / 'work/wave_v77/inputs/core.py')
    previous_core = sys.modules.get('core')
    sys.modules['core'] = core
    try:
        extract = module('追加ナイト原板抽出77の読取', ROOT / 'work/wave_v77/inputs/prepare.py')
    finally:
        if previous_core is None:
            sys.modules.pop('core', None)
        else:
            sys.modules['core'] = previous_core
    extract.EXTRA = SESSION
    helper = module('旧91入力互換関数の読取', ROOT / 'work/wave_v91/inputs/prepare.py')
    signal = module('追加ナイト二市場信号77の読取', ROOT / 'work/wave_v77/signals.py')
    package = types.ModuleType('inputs')
    package.__path__ = [str(ROOT / 'work/wave_v75/inputs')]
    previous_inputs, previous_inputs_core = sys.modules.get('inputs'), sys.modules.get('inputs.core')
    sys.modules['inputs'] = package
    try:
        legacy_core = module('inputs.core', ROOT / 'work/wave_v75/inputs/core.py')
        legacy_source = module('追加ナイト旧75共同入口の読取', ROOT / 'work/wave_v75/signals.py')
        legacy = module('追加ナイト旧77候補の読取', ROOT / 'work/wave_v77/prepared/prepare_legacy.py')
    finally:
        for name, previous in (('inputs', previous_inputs), ('inputs.core', previous_inputs_core)):
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
        numba.config.CACHE_DIR = CACHE
    legacy.EXTRA = SESSION
    # 旧95のprepare_pricesはimport dataするため、入力だけの読取実装へ結ぶ。
    previous_data = sys.modules.get('data')
    prices_data = module('独立LP窓95用入力関数の読取', ROOT / 'work/wave_v95/data.py')
    sys.modules['data'] = prices_data
    try:
        trend = module('追加ナイト独立LP窓95の読取', ROOT / 'work/wave_v95/prepare_prices.py')
    finally:
        if previous_data is None:
            sys.modules.pop('data', None)
        else:
            sys.modules['data'] = previous_data
    last = module('追加ナイト原LP94の読取', ROOT / 'work/wave_v94/inputs_r1/last_price.py')
    art = artificial(last, trend)
    print('人工入力の同時計先頭・欠測・未来不変が一致しました', flush=True)
    extra = [extract.extract_extra(symbol) for symbol in SYMBOLS]
    ready = {value[0]: value[1] for value in extra}
    books = {value[0]: value[2] for value in extra}
    snapshots = {value[0]: value[3] for value in extra}
    prices = {key: helper.price_record(key, ready[key], books[key]) for key in ready}
    features = {key: dict(quality=np.asarray(books[key]['valid'] & prices[key]['quote_valid'] &
                   (prices[key]['ask'] - prices[key]['bid'] <= 2 * prices[key]['tick'] + 1e-9), bool),
                   reset=np.asarray(books[key]['reset'], bool)) for key in ready}
    grid = core.session_features(ready, books, snapshots, SESSION, 1)
    entry = signal.build({SESSION: grid}, ready)[SESSION]
    candidate_grid = legacy_core.session_sync(ready, books, SESSION, delays=(1,), step=15., max_age=30.)['grid']
    candidates = legacy.build_extra(legacy_source, candidate_grid, ready, books, 1)
    print('旧と同じ原板、二市場格子及び入口候補を準備しました', flush=True)

    # ----------------------------------------
    # 修正済み94の価格資格と95の独立LP窓を執行系列から分離して保持する。
    prepare_price = module('追加ナイト価格分離94修正版の読取', ROOT / 'work/wave_v94/prepare_inputs_r1.py')
    lane_helper = module('旧I0価格欄94修正版の読取', ROOT / 'work/wave_v94/data_r1.py')
    lanes = {name: {SESSION: dict(grid=grid['grid'], markets={})} for name in ('I0', 'I1', 'I2', 'I3')}
    raw_records, trend_markets, mapping, price_diagnostics = {}, {}, {}, []
    for key, record in prices.items():
        made = prepare_price.prepare_one(key, record, grid['grid'], grid['markets'][key[1]])
        lanes['I0'][SESSION]['markets'][key[1]] = lane_helper.old_price_channel(grid['markets'][key[1]], record)
        for lane, field in (('I1', 'mid'), ('I2', 'coupled_lp'), ('I3', 'lp')):
            lanes[lane][SESSION]['markets'][key[1]] = made[field]
        raw = made['lp_record']
        raw_records[key] = raw
        lp_features = trend.price_features(grid['grid'], raw)
        for field in ('index', 'raw_seq', 'time_s', 'value', 'valid', 'age', 'actual_age'):
            equal(lp_features['current'][field], made['lp']['current'][field])
        indexes = np.searchsorted(raw['seq'], record['seq'])
        assert (indexes < len(raw['seq'])).all()
        for a, b in (('seq', 'seq'), ('time_s', 'time_s'), ('last', 'price')):
            equal(raw[a][indexes], record[b])
        mapping[key] = indexes.astype(np.int32)
        trend_markets[key[1]] = lp_features
        price_diagnostics.append(made['diagnosis'])
        source_relative = str((ROOT / 'book' / key[1] / (SESSION + '.jsonl')).relative_to(ROOT))
        assert made['diagnosis']['原本SHA256'] == raw_sha[source_relative]
    positions = np.searchsorted(grid['grid'], candidate_grid)
    equal(grid['grid'][positions], candidate_grid)
    trend_prices = {'I3': {SESSION: dict(grid=grid['grid'], markets=trend_markets,
                      candidate_grid=candidate_grid, candidate_positions=positions.astype(np.int32))}}
    material = dict(prices=prices, features=features, grids={SESSION: grid}, entries={SESSION: entry},
                    legacy=candidates, price_lanes=lanes, trend_prices=trend_prices,
                    raw_last_records=raw_records, execution_lp_index=mapping)
    refs = module('追加ナイト始値参照74の読取', ROOT / 'work/wave_v74/inputs/prepare_refs.py')
    old_template = read(ROOT / 'work/wave_v91/inputs/material_extra.pkl')
    old_metadata = read(ROOT / 'work/wave_v91/inputs/metadata.json')
    references, diagnostics = {}, []
    for key, record, book, snapshot, audit, probe in extra:
        opening = refs.opening_ref(key, record, probe)
        assert opening['known_from_i'] == 0
        predecessor = ('2026-10-12_Day', key[1])
        previous = old_template['prices'][predecessor]
        old_audit = next(row for row in old_metadata['extra_raw_audit'] if row['symbol'] == key[1])
        latest = refs.last_current(ROOT / 'book' / key[1] / (predecessor[0] + '.jsonl'),
                                   old_audit['raw_rows'], previous['start'], previous['end'])
        references['|'.join(key)] = dict(session=SESSION, symbol=key[1], ref_open=opening,
            ref_prev=refs.previous_ref(key, record, predecessor,
                     {predecessor: dict(previous, last=previous['price'])},
                     {predecessor: dict(latest=latest, end=previous['end'])}))
        audit['first_time_text'] = datetime.fromtimestamp(audit['first_time'], JST).isoformat()
        audit['last_time_text'] = datetime.fromtimestamp(audit['last_time'], JST).isoformat()
        audit['場末通常清算用の有効気配行数'] = int((record['time_s'] >= record['limit']).sum())
        audit['途中場ではない'] = bool(probe['latest']['time'] >= record['limit'])
        audit['通常終端までの有効気配不足秒'] = float(record['limit'] + 300. - record['time_s'][-1])
        assert audit['途中場ではない'] and audit['場末通常清算用の有効気配行数'] > 0
        diagnostics.append(audit)
    schemas = sum(schema_equal(old_template[name][('2026-10-12_Day', symbol)], material[name][(SESSION, symbol)])
                  for name in ('prices', 'features', 'legacy') for symbol in SYMBOLS)
    schemas += schema_equal(old_template['grids']['2026-10-12_Day'], grid)
    schemas += schema_equal(old_template['entries']['2026-10-12_Day'], entry)
    raw_checks = [raw_prefix_check(extract, core, value) for value in extra]
    prefixes = input_prefix_checks(core, signal, legacy, legacy_source, trend, ready, books, snapshots, material)
    for name, expected in raw_sha.items():
        assert digest(ROOT / name) == expected, ('準備中の原本変更', name)
    for name, expected in code_sha.items():
        assert digest(ROOT / name) == expected, ('準備中のコード変更', name)
    proof = dict(全合格=True, 追加確認場=SESSION, 人工=art, 原本と品質=diagnostics,
                 価格分離診断=price_diagnostics, 旧列型形状一致配列数=schemas,
                 原本接頭の再抽出=raw_checks, 実入力の未来切断=prefixes,
                 価格時計の制限='CurrentPriceTime代理時計上のstrict過去。共通の実受信時計は保存されていない。',
                 旧入口の因果源='300秒窓・15秒気配進行及び旧中立/発火規則。全場高安・終端価格・損益は入口へ使わない。',
                 元31再生成=False, 元31キャッシュ変更=False, 新場損益閲覧=0, 新場損益計算=0,
                 売買実行=0, 選定=0, API取得=0, 実注文=0, 原本SHA256=raw_sha, 直接使用コードSHA256=code_sha)
    save('追加入力の人工と原本及び実接頭検査.json', proof)
    save('material_holdout.pkl', material)
    metadata = dict(sessions=[SESSION], accounts=2, references=references, rows=diagnostics,
                    added_session=SESSION, unseen_session=SESSION, 新場原本診断=diagnostics,
                    原本SHA256=raw_sha, 直接使用コードSHA256=code_sha,
                    入力SHA256={str((HERE / name).relative_to(ROOT)): digest(HERE / name)
                                 for name in ('material_holdout.pkl', '追加入力の人工と原本及び実接頭検査.json',
                                              '入力準備前の素材登録.json')},
                    入力='旧31場はこのloaderへ混ぜず、一場だけを不変条件の追加確認に渡す。',
                    時刻='代理価格時計上strict time<grid-1秒、同時計先頭、最大古さ30秒。実受信時計ではない。',
                    新場損益閲覧=0, 新場損益計算=0, 売買実行=0, 選定=0, API取得=0, 実注文=0)
    save('metadata.json', metadata)
    loaded = DATA.load_inputs()
    for name in material:
        equal(material[name], loaded[name])
    print('追加Night一場二口座の入力準備・原本接頭・未来不変・保存往復が完了。売買と損益は0です', flush=True)


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        index = 1
        while (HERE / f'入力準備不合格_{index:05d}.json').exists():
            index += 1
        save(f'入力準備不合格_{index:05d}.json', dict(全合格=False, 例外型=type(error).__name__,
             内容=str(error), 診断=traceback.format_exc(), 実行時準備コードSHA256=digest(Path(__file__)),
             新場損益閲覧=0, 新場損益計算=0, 売買実行=0, 選定=0, API取得=0, 実注文=0))
        raise
