"""根のcoupled LP入力部品を、旧源点・独立価格式・未来切断で損益前検査する。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DRIVER = ROOT / 'work/wave_v94/prepare_inputs.py'
CORE = ROOT / 'work/wave_v94/inputs/core.py'
OLD = ROOT / 'work/wave_v77/inputs/core.py'


def module(name: str, path: Path) -> object:
    """
    機能: mainを実行しない純入力部品を固有名で読み取る。
    引数: name (str)、path (Path)。
    返り値: object は読取モジュール。保存生成や売買を呼ばない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def equal(a: np.ndarray, b: np.ndarray, label: str) -> None:
    """
    機能: 未定義値を含む配列を独立比較する。
    引数: a/b (ndarray)、label (str)。
    返り値: None。不一致は項目名付き例外。
    """
    if np.issubdtype(a.dtype, np.floating) or np.issubdtype(b.dtype, np.floating):
        np.testing.assert_allclose(a, b, rtol=0, atol=1e-8, equal_nan=True, err_msg=label)
    else:
        np.testing.assert_array_equal(a, b, err_msg=label)


def fixture(old: object, fault: bool) -> tuple:
    """
    機能: 同時計重複と任意の旧深板/原行障害を持つ人工旧入力を作る。
    引数: old (object) は旧v77入力関数、fault (bool)。
    返り値: tuple はrecord、旧market、grid。
    """
    times = np.repeat(np.arange(0., 721.), 2)
    mid = 1000. + np.floor(np.arange(len(times)) / 7) % 9
    seq = np.arange(len(times), dtype=np.int64)
    reset = np.zeros(len(times), bool)
    reset[0] = True
    valid = np.ones(len(times), bool)
    if fault:
        valid[400:402] = False
        reset[400:403] = True
        seq[600:] += 2
        reset[600] = True
    record = dict(time_s=times, seq=seq, price=mid.copy(), tick=.5)
    ready = dict(time_s=times, seq=seq, tick=.5, last=mid.copy())
    book = dict(bid=mid-.25, ask=mid+.25, mid=mid, last=mid.copy(),
                valid=valid, reset=reset, bid_qty=np.full(len(times), 100.), ask_qty=np.full(len(times), 100.),
                best_ofi=np.zeros(len(times)))
    snapshot = {'valid': np.ones(len(times), bool)}
    for name in old.LEGACY.SNAPSHOT_FIELDS:
        snapshot[name] = np.zeros(len(times))
    grid = np.arange(2., 719., 5.)
    market = old.market_features(grid, 1, ready, book, snapshot)
    return record, market, grid


def source_check(output: dict, old: dict, record: dict) -> None:
    """
    機能: currentと全窓の端点・資格・clock・rawseqを旧入力へ独立照合する。
    引数: output/old/record (dict)。
    返り値: None。価格派生値は別式で検査する。
    """
    current = output['current']
    for field in ('index', 'age', 'actual_age', 'valid'):
        equal(current[field], old['current'][field], 'current.' + field)
    for i, index in enumerate(current['index']):
        assert current['raw_seq'][i] == (-1 if index < 0 else record['seq'][index])
        assert np.isnan(current['time_s'][i]) if index < 0 else current['time_s'][i] == record['time_s'][index]
    for seconds, original in old['windows'].items():
        new = output['windows'][seconds]
        for field in ('old', 'now', 'old_age', 'source_valid', 'same_row', 'reset_or_invalid_cross', 'unique_observations'):
            equal(new[field], original[field], f'window{seconds}.{field}')
    for seconds, original in old['ranges'].items():
        for field in ('old', 'now', 'source_valid', 'unique_observations'):
            equal(output['ranges'][seconds][field], original[field], f'range{seconds}.{field}')


def value_oracle(output: dict, old: dict, record: dict) -> None:
    """
    機能: LPの変位・総変動・ER・高安を、正式高安部品を呼ばないループで照合する。
    引数: output/old/record (dict)。
    返り値: None。
    """
    times, values = record['time_s'], record['price']
    first = np.array([i for i in range(len(times)) if i == 0 or times[i] != times[i-1]])
    positions = {int(index): j for j, index in enumerate(first)}
    now = old['current']['index']
    for seconds, source in old['windows'].items():
        new = output['windows'][seconds]
        for g in range(len(now)):
            if not source['source_valid'][g]:
                assert np.isnan(new['displacement'][g]) and np.isnan(new['total_variation'][g]) and np.isnan(new['efficiency'][g])
                continue
            a, b = int(source['old'][g]), int(source['now'][g])
            pa, pb = positions[a], positions[b]
            observation = values[first[pa:pb+1]]
            displacement = float(values[b] - values[a])
            variation = sum(abs(float(y-x)) for x, y in zip(observation, observation[1:]))
            assert abs(new['displacement'][g] - displacement) < 1e-8
            assert abs(new['total_variation'][g] - variation) < 1e-8
            assert abs(new['ret_bp'][g] - displacement / values[a] * 10000) < 1e-8
            if variation > 0:
                assert abs(new['efficiency'][g] - abs(displacement) / variation) < 1e-8
            else:
                assert np.isnan(new['efficiency'][g]) and new['zero_variation'][g]
    for seconds, source in old['ranges'].items():
        new = output['ranges'][seconds]
        for g in np.flatnonzero(source['source_valid']):
            a, b = int(source['old'][g]), int(source['now'][g])
            observation = values[first[positions[a]:positions[b]]]
            high, low = float(max(observation)), float(min(observation))
            assert new['high'][g] == high and new['low'][g] == low and new['width'][g] == high-low
            if high > low:
                assert new['position_valid'][g]
                assert abs(new['position'][g] - (values[b]-low)/(high-low)) < 1e-8
            else:
                assert not new['position_valid'][g] and np.isnan(new['position'][g])


def compare_common(output: dict, old: dict) -> None:
    """
    機能: LPが旧midと同値なら共通価格の派生列が全て一致することを検査する。
    引数: output/old (dict)。
    返り値: None。新rawseq等の追加メタデータは価格列と別扱い。
    """
    equal(output['current']['value'], old['current']['mid'], '同値current')
    for seconds, source in old['windows'].items():
        for field in output['windows'][seconds].keys() & source.keys():
            equal(output['windows'][seconds][field], source[field], f'同値window{seconds}.{field}')
    for seconds, source in old['ranges'].items():
        for field in output['ranges'][seconds].keys() & source.keys():
            equal(output['ranges'][seconds][field], source[field], f'同値range{seconds}.{field}')


def prefix_market(old: dict, mask: np.ndarray) -> dict:
    """
    機能: 同じ過去格子の旧源点情報だけを選び、価格入力prefixへ接続する。
    引数: old (dict)、mask (ndarray[bool])。
    返り値: dict は切断対象の旧market。
    """
    return {kind: {k: v[mask].copy() for k, v in values.items()} if kind == 'current'
            else {seconds: {k: v[mask].copy() for k, v in values.items()} for seconds, values in values.items()}
            for kind, values in old.items() if kind in ('current', 'windows', 'ranges')}


def output_prefix_check(full: dict, short: dict, mask: np.ndarray) -> None:
    """
    機能: 過去格子の全出力について切断又は未来改変の不変性を確認する。
    引数: full/short (dict)、mask (ndarray[bool])。
    返り値: None。
    """
    for kind in ('current', 'windows', 'ranges'):
        if kind == 'current':
            groups = [(full[kind], short[kind])]
        else:
            groups = [(full[kind][seconds], short[kind][seconds]) for seconds in full[kind]]
        for a, b in groups:
            for field in a:
                equal(a[field][mask], b[field], '未来不変.' + kind + '.' + field)


def main() -> None:
    """
    機能: coupled LPだけを人工入力で独立検査し、新53の損益を見ずに証拠を保存する。
    引数: なし。
    返り値: None。全62生成driverのmainも売買部品も呼ばない。
    """
    driver, core, old = module('根coupledLP94の独立検査', DRIVER), module('根価格部品94の人工読取', CORE), module('旧77価格だけの比較', OLD)
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (DRIVER, CORE, OLD)}
    checks, prefix_count, poison_count = [], 0, 0
    for fault in (False, True):
        record, market, grid = fixture(old, fault)
        before = pickle.dumps((record, market), protocol=5)
        same = driver.coupled_last_features(record, market, core)
        source_check(same, market, record)
        value_oracle(same, market, record)
        compare_common(same, market)
        changed = deepcopy(record)
        changed['price'] += np.floor(np.arange(len(record['price'])) / 13) % 5
        output = driver.coupled_last_features(changed, market, core)
        source_check(output, market, changed)
        value_oracle(output, market, changed)
        flat = deepcopy(record)
        flat['price'][:] = 1000.
        flattened = driver.coupled_last_features(flat, market, core)
        source_check(flattened, market, flat)
        value_oracle(flattened, market, flat)
        assert all(np.isnan(v['efficiency']).all() for v in flattened['windows'].values())
        assert all(not v['position_valid'].any() for v in flattened['ranges'].values())
        for cut in (61, 121, 301, 401, 601, 701, 1001, 1201, 1441):
            mask = grid <= record['time_s'][cut-1] + 1
            short_record = {k: v[:cut].copy() if isinstance(v, np.ndarray) else v for k, v in changed.items()}
            short_market = prefix_market(market, mask)
            short = driver.coupled_last_features(short_record, short_market, core)
            output_prefix_check(output, short, mask)
            prefix_count += 1
            poisoned = deepcopy(changed)
            poisoned['price'][cut:] += 100. + np.arange(len(changed['price'])-cut) % 19
            altered = driver.coupled_last_features(poisoned, market, core)
            output_prefix_check(altered, short, mask)
            poison_count += 1
        assert before == pickle.dumps((record, market), protocol=5), '旧source又は入力を上書きしました'
        checks.append({'旧入力に障害あり': fault, '源点資格全一致': True, '独立価格式一致': True,
                       'midとLP同値の共通価格全列一致': True, '平坦LPのERを捏造しない': True,
                       '旧入力のバイト不変': True})
    result = {'全人工合格': True, '対象': '根coupled_last_featuresだけ。価格入力の純部品検査。',
              '検査': checks, '未来切断': prefix_count, '未来価格改変': poison_count,
              'sameclock切断': '全cutは同clock先頭直後を含む奇数行。後続同clockの価格を改変しても過去出力は不変。',
              '参照SHA256': hashes, '理論コードSHA256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              '制限': '記録済みretained LPは有限正という既存入力契約を使用。全原本LP欠測の扱いはrawLP部品の別監査。真受信時計の証明ではない。',
              '全62生成を実行': 0, '新条件売買実行': 0, '新損益計算': 0, 'API取得': 0, '実注文': 0}
    path = HERE / '旧源点を保つLP値対照の独立人工及び未来不変.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'保存先': str(path), 'SHA256': hashlib.sha256(path.read_bytes()).hexdigest(),
                      '未来切断': prefix_count, '未来価格改変': poison_count, '新損益計算': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
