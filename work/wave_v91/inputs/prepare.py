"""保存済み追加デイを旧仕様で準備し、旧30場を変更せず接続する。"""

from datetime import datetime, timezone, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import socket
import sys
import types

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EXTRA = '2026-10-12_Day'
SYMBOLS = ('TOPIX', 'NK225')
JST = timezone(timedelta(hours=9))


def module(name, path):
    """
    機能: 旧資料を専用名で読み込み、旧ファイルを変更しない。
    引数: name (str)、path (Path)。
    返り値: object の読取モジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def digest(path):
    """
    機能: 入出力の内容指紋を一定メモリーで求める。
    引数: path (Path)。
    返り値: str のSHA256。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def read(path):
    """
    機能: 損益を持たない入力又は仕様だけを読む。
    引数: path (Path)。
    返り値: object の保存内容。
    """
    assert not any(part in ('results', 'ledgers', 'analysis', 'review') for part in path.parts)
    with path.open('rb') as stream:
        return pickle.load(stream) if path.suffix == '.pkl' else json.load(stream)


def save(name, value):
    """
    機能: 新しい担当入力領域だけへ出力する。
    引数: name (str)、value (object)。
    返り値: None。
    """
    path = HERE / name
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    if path.suffix == '.pkl':
        with path.open('wb') as stream:
            pickle.dump(value, stream, protocol=5)
    else:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def deny(*args, **kwargs):
    """
    機能: 保存入力の準備中のネットワーク通信を禁止する。
    引数: args (tuple)、kwargs (dict)。
    返り値: None。呼出し時は例外で停止する。
    """
    raise RuntimeError('保存入力の準備は通信しない')


def clipped(record, count):
    """
    機能: 同時計先頭の前方参照検査用に未来行を除く。
    引数: record (dict)、count (int)。
    返り値: dict の過去接頭部。
    """
    return {name: value[:count] if isinstance(value, np.ndarray) and value.ndim else value
            for name, value in record.items()}


def equal(left, right):
    """
    機能: ネストした入力を欠損込みで照合する。
    引数: left、right (object)。
    返り値: int の照合配列数。
    """
    if isinstance(left, dict):
        assert left.keys() == right.keys()
        return sum(equal(left[name], right[name]) for name in left)
    if isinstance(left, np.ndarray):
        np.testing.assert_array_equal(left, right)
        return 1
    assert left == right
    return 0


def price_record(key, ready, feature):
    """
    機能: 旧83と同じ現在値・気配・原本行の互換列を作る。
    引数: key (tuple[str,str])、ready、feature (dict)。
    返り値: dict の価格入力。現在値を気配内へ変更しない。
    """
    size = len(ready['seq'])
    result = dict(time_s=ready['time_s'], price=ready['last'], seq=ready['seq'],
                  source_i=np.arange(size, dtype=np.int32), session=key[0], symbol=key[1],
                  tick=float(ready['tick']), start=float(ready['start']), end=float(ready['limit']) + 300.,
                  limit=float(ready['limit']), bid=feature['bid'], ask=feature['ask'])
    result['price_valid'] = np.isfinite(result['price']) & (result['price'] > 0)
    result['quote_valid'] = (np.isfinite(result['bid']) & np.isfinite(result['ask'])
                             & (result['bid'] > 0) & (result['bid'] < result['ask']))
    assert result['price_valid'].all() and result['quote_valid'].all()
    return result


def raw_samples(key, record):
    """
    機能: 新入力の7行と原本同seqの価格・時計・気配を直接照合する。
    引数: key (tuple[str,str])、record (dict)。
    返り値: list[dict] の照合根拠。
    """
    indices = np.unique(np.linspace(0, len(record['seq']) - 1, 7, dtype=np.int64))
    wanted = {int(record['seq'][i]): int(i) for i in indices}
    output = []
    path = ROOT / 'book' / key[1] / (key[0] + '.jsonl')
    with path.open('rb') as stream:
        for seq, line in enumerate(stream):
            if seq not in wanted:
                continue
            i = wanted[seq]
            raw = json.loads(line)
            stamp = datetime.fromisoformat(raw['CurrentPriceTime']).timestamp()
            assert stamp == record['time_s'][i]
            assert raw['CurrentPrice'] == record['price'][i]
            assert raw['Buy1']['Price'] == record['bid'][i]
            assert raw['Sell1']['Price'] == record['ask'][i]
            output.append(dict(i=i, seq=seq, time=raw['CurrentPriceTime'], price=raw['CurrentPrice'],
                               bid=raw['Buy1']['Price'], ask=raw['Sell1']['Price']))
    assert len(output) == len(indices)
    return output


def causal_checks(core, signal, legacy, grid, ready, book, snapshots, base_grid, base_entry, base_legacy):
    """
    機能: 新場を複数時点で未来切断し、価格窓・入口の過去不変を検証する。
    引数: core、signal、legacy (object)、grid (ndarray)、ready、book、snapshots (dict)、
        base_grid、base_entry、base_legacy (dict)。
    返り値: dict の因果検査。損益計算や未来ラベルは作らない。
    """
    rows = []
    start = ready[(EXTRA, 'TOPIX')]['start']
    for offset in (450., 900., 1800., 3600., 7200., 10800., 14400., 18000., 21600., 24000.):
        cutoff = start + offset
        cuts = {key: int(np.searchsorted(value['time_s'], cutoff, side='left')) for key, value in ready.items()}
        prefix_ready = {key: clipped(value, cuts[key]) for key, value in ready.items()}
        prefix_book = {key: clipped(value, cuts[key]) for key, value in book.items()}
        prefix_snap = {key: clipped(value, cuts[key]) for key, value in snapshots.items()}
        short_grid = grid[grid < cutoff]
        value = dict(grid=short_grid, markets={symbol: core.market_features(
            short_grid, 1, prefix_ready[(EXTRA, symbol)], prefix_book[(EXTRA, symbol)], prefix_snap[(EXTRA, symbol)])
            for symbol in SYMBOLS})
        expected = dict(grid=short_grid, markets={symbol: {kind:
            ({name: column[:len(short_grid)] for name, column in content.items()} if kind == 'current' else
             {window: {name: column[:len(short_grid)] for name, column in item.items()}
              for window, item in content.items()})
            for kind, content in base_grid['markets'][symbol].items()} for symbol in SYMBOLS})
        count = equal(value, expected)
        entry = signal.build({EXTRA: value}, prefix_ready)[EXTRA]
        count += equal(entry, {name: (column[:len(short_grid)] if isinstance(column, np.ndarray) else
            {sub: {field: values[:len(short_grid)] for field, values in content.items()}
             for sub, content in column.items()}) for name, column in base_entry.items()})
        legacy_grid = np.arange(start + 300., ready[(EXTRA, 'TOPIX')]['limit'] - 300., 15.)
        prefix_legacy_grid = legacy_grid[legacy_grid < cutoff]
        generated = legacy.build_extra(legacy.legacy_source, prefix_legacy_grid, prefix_ready, prefix_book, 1)
        for key, result in generated.items():
            expected_legacy = {name: (content[:len(prefix_legacy_grid)] if name != 'candidates' else
                content[(content[:, 0] < len(prefix_legacy_grid)) & (content[:, 1] < cuts[key])])
                for name, content in base_legacy[key].items()}
            count += equal(result, expected_legacy)
        rows.append(dict(cutoff=datetime.fromtimestamp(cutoff, JST).isoformat(), cuts={'|'.join(key): value for key, value in cuts.items()},
                         grid_count=len(short_grid), equal_arrays=count))
    strict = []
    for symbol in SYMBOLS:
        market = base_grid['markets'][symbol]
        times = ready[(EXTRA, symbol)]['time_s']
        current = market['current']['index']; good = current >= 0
        assert (times[current[good]] < grid[good] - 1.).all()
        assert (np.searchsorted(times, times[current[good]], side='left') == current[good]).all()
        for window, item in market['windows'].items():
            old = item['old']; good = old >= 0
            assert (times[old[good]] < grid[good] - 1. - window).all()
        strict.append(dict(symbol=symbol,格子現在端点のstrict過去=True,同clock先頭=True,窓始点のstrict過去=True))
    return dict(全合格=True,切断数=len(rows),接頭部=rows,厳密過去=strict,
                時計制限='原時計CurrentPriceTime上の過去性。共通受信時計がないため受信時点の証明ではない。')


def main():
    """
    機能: 追加デイの入力を旧仕様で固定し、旧30場の指紋参照へ接続する。
    引数: なし。
    返り値: None。新旧損益結果の閲覧・計算、API、実注文は0。
    """
    socket.socket.connect = deny
    socket.create_connection = deny
    assert not (HERE / 'metadata.json').exists(), '完成入力は上書きしない'
    old_data = module('保存入力90の読取91', ROOT / 'work/wave_v90/data.py')
    prior = old_data.load_inputs()
    old_fingerprints = {str(path.relative_to(ROOT)): digest(path) for path in prior['paths']}
    old_fingerprints['work/wave_v90/data.py'] = digest(ROOT / 'work/wave_v90/data.py')
    assert len(prior['metadata']['sessions']) == 30 and EXTRA not in prior['grids']
    core = module('価格入力77の読取91', ROOT / 'work/wave_v77/inputs/core.py')
    old_core = sys.modules.get('core')
    sys.modules['core'] = core
    prepare = module('保存入力77の抽出91', ROOT / 'work/wave_v77/inputs/prepare.py')
    if old_core is None:
        sys.modules.pop('core', None)
    else:
        sys.modules['core'] = old_core
    prepare.EXTRA = EXTRA
    extra = [prepare.extract_extra(symbol) for symbol in SYMBOLS]
    ready = {value[0]: value[1] for value in extra}
    book = {value[0]: value[2] for value in extra}
    snapshots = {value[0]: value[3] for value in extra}
    prices = {key: price_record(key, ready[key], book[key]) for key in ready}
    features = {key: dict(quality=np.asarray(book[key]['valid'] & prices[key]['quote_valid'] &
        (prices[key]['ask'] - prices[key]['bid'] <= 2 * prices[key]['tick'] + 1e-9), bool),
        reset=np.asarray(book[key]['reset'], bool)) for key in ready}
    grid = core.session_features(ready, book, snapshots, EXTRA, 1)
    signal = module('入口77の読取91', ROOT / 'work/wave_v77/signals.py')
    entry = signal.build({EXTRA: grid}, ready)[EXTRA]
    package = types.ModuleType('inputs'); package.__path__ = [str(ROOT / 'work/wave_v75/inputs')]
    previous_inputs = sys.modules.get('inputs'); previous_inputs_core = sys.modules.get('inputs.core')
    sys.modules['inputs'] = package
    legacy_core = module('inputs.core', ROOT / 'work/wave_v75/inputs/core.py')
    legacy_source = module('共同入口75の読取91', ROOT / 'work/wave_v75/signals.py')
    legacy = module('旧候補77の追加91', ROOT / 'work/wave_v77/prepared/prepare_legacy.py')
    legacy.EXTRA = EXTRA; legacy.legacy_source = legacy_source
    legacy_grid = legacy_core.session_sync(ready, book, EXTRA, delays=(1,), step=15., max_age=30.)['grid']
    candidates = legacy.build_extra(legacy_source, legacy_grid, ready, book, 1)
    if previous_inputs is None:
        sys.modules.pop('inputs', None)
    else:
        sys.modules['inputs'] = previous_inputs
    if previous_inputs_core is None:
        sys.modules.pop('inputs.core', None)
    else:
        sys.modules['inputs.core'] = previous_inputs_core
    refs = module('参照始値74の読取91', ROOT / 'work/wave_v74/inputs/prepare_refs.py')
    references = dict(prior['metadata']['references'])
    diagnostics = []
    for key, record, feature, snapshot, audit, probe in extra:
        reference = refs.opening_ref(key, record, probe)
        assert reference['known_from_i'] == 0
        predecessor = ('2026-10-09_Night', key[1])
        previous = prior['prices'][predecessor]
        previous_audit = next(item for item in prior['metadata']['extra_raw_audit'] if item['symbol'] == key[1])
        latest = refs.last_current(ROOT / 'book' / key[1] / (predecessor[0] + '.jsonl'),
                                   previous_audit['raw_rows'], previous['start'], previous['end'])
        previous_ready = dict(previous, last=previous['price'])
        references['|'.join(key)] = dict(session=key[0], symbol=key[1], ref_open=reference,
            ref_prev=refs.previous_ref(key, record, predecessor, {predecessor: previous_ready},
                                     {predecessor: dict(latest=latest, end=previous['end'])}))
        quote_times = record['time_s']; gaps = np.diff(quote_times)
        audit['first_time_text'] = datetime.fromtimestamp(audit['first_time'], JST).isoformat()
        audit['last_time_text'] = datetime.fromtimestamp(audit['last_time'], JST).isoformat()
        audit['latest_price_time_text'] = datetime.fromtimestamp(probe['latest']['time'], JST).isoformat()
        audit['通常区切り以後の有効気配行数'] = int((quote_times >= record['limit']).sum())
        audit['観測終端までの有効気配不足秒'] = float(record['limit'] + 300. - quote_times[-1])
        audit['gap_seconds_quantiles'] = [float(value) for value in np.quantile(gaps, [0, .5, .9, .99, 1])]
        audit['gap_over_30sec'] = int((gaps > 30.).sum())
        audit['gap_over_120sec'] = int((gaps > 120.).sum())
        audit['price_outside_quotes'] = int(((record['last'] < feature['bid']) | (record['last'] > feature['ask'])).sum())
        price_steps = np.abs(np.diff(record['last']))
        quote_steps = np.r_[np.abs(np.diff(feature['bid'])), np.abs(np.diff(feature['ask']))]
        audit['ラージ呼値'] = record['tick']
        audit['観測現在値の非ゼロ最小差分'] = float(price_steps[price_steps > 0].min())
        audit['観測気配の非ゼロ最小差分'] = float(quote_steps[quote_steps > 0].min())
        audit['原本同seq抜取'] = raw_samples(key, prices[key])
        audit['通常15時35分清算の可否'] = bool(audit['通常区切り以後の有効気配行数'] > 0)
        audit['途中場ではない'] = bool(probe['latest']['time'] >= record['limit'])
        diagnostics.append(audit)
        print(f"{key[1]} 新保存場抽出 {audit['n']:,}行 最終有効 {audit['last_time_text']}", flush=True)
    proof = causal_checks(core, signal, legacy, grid['grid'], ready, book, snapshots, grid, entry, candidates)
    save('追加Dayの原本と品質及び因果検査.json', dict(全合格=True, 追加場=EXTRA,
        原本と品質=diagnostics, 未来切断検査=proof, 損益閲覧=0, 損益計算=0, API取得=0, 実注文=0))
    material = dict(prices=prices, grids={EXTRA: grid}, legacy=candidates, entries={EXTRA: entry}, features=features)
    save('material_extra.pkl', material)
    sessions = sorted([*prior['metadata']['sessions'], EXTRA])
    metadata = dict(sessions=sessions, accounts=62, references=references,
        existing30=prior['metadata']['sessions'], added_session=EXTRA, unseen_session=EXTRA,
        extra_raw_audit=diagnostics, 新場原本診断=diagnostics,
        rows=[*prior['metadata']['rows'], *[dict(session=item['session'], symbol=item['symbol'],
            n=item['n'], start=item['start'], limit=item['limit'], tick=item['tick'],
            first_time=item['first_time'], last_time=item['last_time'], valid_rows=item['valid_rows'],
            reset_rows=item['reset_rows']) for item in diagnostics]],
        開示区分='旧30場は既知。追加2026-10-12_Dayは入力準備のみで損益未閲覧。旧30による候補固定後に答え合わせとして再生する。',
        windows=list(core.WINDOWS), ranges=list(core.RANGES), flow_windows=[15, 30],
        delays=[1], grid_seconds=5, max_age=30,
        単位=prior['metadata']['単位'], 効率=prior['metadata']['効率'],
        レンジ=prior['metadata']['レンジ'], 可用性=prior['metadata']['可用性'],
        接続方式='旧30場素材を読取専用で参照し、追加1場の最小pickleだけ保存。ロード時に全31場62口座を返す。',
        時刻='CurrentPriceTimeは最終約定代理時計。同時計先頭とstrict time<grid-1秒。真の共通受信時計は保存なし。',
        旧指紋=old_fingerprints, 新入力指紋={'material_extra.pkl': digest(HERE / 'material_extra.pkl')},
        新コード指紋={str(path.relative_to(ROOT)): digest(path) for path in [Path(__file__), HERE / 'data.py']},
        直接使用旧コード指紋={str(path.relative_to(ROOT)): digest(path) for path in [
            ROOT / 'work/wave_v77/inputs/core.py', ROOT / 'work/wave_v77/inputs/prepare.py',
            ROOT / 'work/wave_v8/raw_features.py', ROOT / 'work/wave_v57/features.py',
            ROOT / 'work/wave_v77/signals.py', ROOT / 'work/wave_v77/prepared/prepare_legacy.py',
            ROOT / 'work/wave_v75/signals.py', ROOT / 'work/wave_v75/inputs/core.py',
            ROOT / 'work/wave_v74/inputs/prepare_refs.py']},
        損益閲覧=0, 損益計算=0, API取得=0, 実注文=0)
    save('metadata.json', metadata)
    for relative, expected in old_fingerprints.items():
        assert digest(ROOT / relative) == expected
    loaded = module('完成入力91の読取確認', HERE / 'data.py').load_inputs()
    assert len(loaded['prices']) == len(loaded['legacy']) == len(loaded['features']) == 62
    assert len(loaded['grids']) == len(loaded['entries']) == 31
    checked = sum(equal({key: loaded[name][key] for key in prior[name]}, prior[name])
                  for name in ('prices', 'grids', 'legacy', 'entries', 'features'))
    save('全31場の接続照合.json', dict(全合格=True, 場数=31, 口座数=62, 旧30不変照合配列数=checked,
        旧30再生成=False, 追加場のみ新生成=True, 新Day通常清算可能=all(
            item['通常15時35分清算の可否'] for item in diagnostics), 損益閲覧=0, 損益計算=0,
        API取得=0, 実注文=0, SHA256={name: digest(HERE / name) for name in (
            'material_extra.pkl', 'metadata.json', '追加Dayの原本と品質及び因果検査.json')}))
    print('保存31場62口座、旧30不変、追加Day因果検査と入力接続が完了', flush=True)


if __name__ == '__main__':
    main()
