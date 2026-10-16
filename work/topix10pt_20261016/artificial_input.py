"""原入力を使わず、現在値採用と閉足公開の因果性を合成原行で確認する。"""

from datetime import datetime, timezone
import ast
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import input as subject

ROOT = HERE.parents[1]
OUT = HERE / 'input_artificial'
CHECKS = []


# ----------------------------------------


def check(name: str, condition: bool) -> None:
    """
    機能: 合成検査の一項目を記録し、不成立を停止させる。
    引数: name(str)、condition(bool) は名称と成否。
    返り値: None。不成立を消さず最終Falseにも残す。
    """
    CHECKS.append(dict(項目=name, 合格=bool(condition)))
    assert condition, name


def equal(name: str, actual: np.ndarray, expected: np.ndarray) -> None:
    """
    機能: NaNを同じ未知として配列の型・値を比較する。
    引数: name(str)、actual/expected(ndarray) は名称と実値・期待値。
    返り値: None。有限値を未知や0へ変換しない。
    """
    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-12, equal_nan=True, err_msg=name)
    check(name, actual.shape == expected.shape)


def stamp(value: float) -> str:
    """
    機能: 合成epoch秒をtimezone付き文字列へ変換する。
    引数: value(float) は合成時刻。
    返り値: str はUTC日時。実時刻やAPIを参照しない。
    """
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def record(at: float, price: float | None, row: int = 0, tick: float = .5) -> dict:
    """
    機能: 十段と公表出来高を持つ合成原JSONを作る。
    引数: at(float)、price(float|None)、row(int)、tick(float) は時計・現在値・合成連番・呼値。
    返り値: dict は合成原行。実銘柄データを読む処理はない。
    """
    center = 4000 if tick == .5 else 60000
    raw = dict(Symbol='合成のみ', SymbolName='合成先物', Exchange=2,
               CurrentPrice=price, CurrentPriceTime=stamp(at),
               TradingVolume=100 + row, TradingVolumeTime=stamp(at))
    for level in range(10):
        raw[f'Buy{level + 1}'] = dict(Price=center - level * tick, Qty=10 + row + level)
        raw[f'Sell{level + 1}'] = dict(Price=center + (level + 1) * tick, Qty=12 + row + level)
    return raw


def arrays(records: list[dict], start: float, end: float) -> dict:
    """
    機能: 合成原JSONだけから採点に渡す最小列を作る。
    引数: records(list[dict])、start/end(float) は合成行と観測窓。
    返り値: dict は原列と公開出来高資格。
    """
    result = subject.parse_records(records)
    usable, delta = subject.volume_contract(result, start, end)
    result['volume_delta_usable'], result['volume_delta'] = usable, delta
    return result


def reference(records: list[dict], start: float, end: float) -> tuple[list[int], dict]:
    """
    機能: NumPy集約を使わず原行を逐次読み、現在値と過去足の公開を参照計算する。
    引数: records(list[dict])、start/end(float) は合成行と窓。
    返り値: tuple[list[int],dict] は採用原行と公開済み足。板や将来行を参照しない。
    """
    maximum, selected, state, published = -math.inf, [], {}, {}
    previous_bucket = None
    for row, raw in enumerate(records):
        value, at = raw.get('CurrentPrice'), raw.get('CurrentPriceTime')
        if isinstance(value, bool) or value is None or not isinstance(at, str):
            continue
        try:
            value, at = float(value), datetime.fromisoformat(at).timestamp()
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or value <= 0 or not math.isfinite(at) or not start <= at < end or at < maximum:
            continue
        maximum = max(maximum, at)
        bucket = int((at - start) // 60)
        if previous_bucket is not None and bucket != previous_bucket:
            for old in tuple(state):
                if old < bucket and old not in published:
                    values = state[old]
                    published[old] = dict(open=values[0], high=max(values), low=min(values), close=values[-1],
                                          anchor=value, pub_raw_row=row)
        state.setdefault(bucket, []).append(value)
        selected.append(row)
        previous_bucket = bucket
    return selected, published


def prefix_checks(records: list[dict], start: float, end: float, tick: float, name: str) -> None:
    """
    機能: 接頭ごとの公開済み足と原価格を独立逐次期待および長い接尾と比較する。
    引数: records(list[dict])、start/end/tick(float)、name(str) は合成原行と条件。
    返り値: None。接尾が過去の公開値を変えないことを確認する。
    """
    full = subject.prepare_session(arrays(records, start, end), start, end, tick)
    for length in range(1, len(records) + 1):
        current = subject.prepare_session(arrays(records[:length], start, end), start, end, tick)
        expected_rows, expected = reference(records[:length], start, end)
        equal(f'{name}接頭{length}現在値', current['prices']['raw_row_index'], np.asarray(expected_rows, np.int64))
        check(f'{name}接頭{length}確定足数', current['bars']['valid'].sum() == len(expected))
        for bucket, wanted in expected.items():
            for field, value in wanted.items():
                check(f'{name}接頭{length}足{bucket}{field}', current['bars'][field][bucket] == value)
        for field, value in current['bars'].items():
            selected = current['bars']['closed']
            equal(f'{name}接頭{length}公表不変{field}', value[selected], full['bars'][field][selected])


def load_source(path: Path, name: str) -> object:
    """
    機能: SOURCE_ONLYの既生成元を同bytes私有コピーからimportする。
    引数: path(Path)、name(str) はsource位置と私有module名。
    返り値: object は実行module。原NPZや旧JITを呼ばない。
    """
    target = OUT / 'source' / f'{name}.py'
    target.parent.mkdir(parents=True, exist_ok=True)
    data = path.read_bytes()
    target.write_bytes(data)
    spec = importlib.util.spec_from_file_location(name, target)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_correction(path: Path) -> dict:
    """
    機能: 旧訂正sourceから純配列関数だけをASTでそのまま取り出す。
    引数: path(Path) は旧source位置。
    返り値: dict は名前空間。DATA読取依存や旧実データの処理は実行しない。
    """
    source = path.read_text(encoding='utf-8')
    tree = ast.parse(source)
    node = next(value for value in tree.body if isinstance(value, ast.FunctionDef) and value.name == 'correct_arrays')
    namespace = dict(np=np, CHANGED=('volume_delta_usable', 'volume_delta'))
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


def main() -> None:
    """
    機能: 現在値・空分・book・出来高系譜・loader・相手足の合成検査を完走し証跡を保存する。
    引数: なし。
    返り値: None。実入力・実金融・APIの読取と実行はすべて0。
    """
    OUT.mkdir(parents=True, exist_ok=True)
    proof = dict(全合格=False, 実原NPZ=0, 実JSONL=0, 既金融=0, 新金融=0, API=0)
    destination = OUT / '現在値採用と閉足公開及び二入力生成元同値の純人工_v2.json'
    assert not destination.exists()
    start, end = subject.bounds('2026-10-14_Day')
    end = start + 600
    try:
        for tick in (.5, 10):
            center = 4000 if tick == .5 else 60000
            offsets = [-20, 1, 4, 4, 65, 40, 120, 125, 240, 245, 300, 600]
            records = [record(start + offset, center + index * tick, index, tick) for index, offset in enumerate(offsets)]
            records[4]['CurrentPrice'] = None
            records[6]['Buy1']['Price'] = records[6]['Sell1']['Price']
            records[7]['Buy1']['Price'] = records[7]['Sell1']['Price'] + tick
            records[8]['Buy1']['Price'] = None
            records[9]['Sell1']['Qty'] = None
            prefix_checks(records, start, end, tick, f'呼値{tick}')
            prepared = subject.prepare_session(arrays(records, start, end), start, end, tick)
            check('場末観測でcomplete', prepared['diagnostics']['window_complete'])
            check('EOFだけはcompleteなし', not subject.prepare_session(arrays(records[:-1], start, end), start, end, tick)['diagnostics']['window_complete'])
            check('不正Last時計だけでは公開しない', prepared['bars']['pub_raw_row'][0] == 6)
            check('場開始前は採用しない', 0 not in prepared['prices']['raw_row_index'])
            check('同clock二行を原順に保持', prepared['diagnostics']['same_clock_accepted'] == 1)
            check('Last不正で進んだ時計を最大時計へ使わない', 5 in prepared['prices']['raw_row_index'])
            check('空足は未知でoriginなし', not prepared['bars']['valid'][1] and math.isnan(prepared['bars']['anchor'][1]))
            check('未確定最終足は未知', not prepared['bars']['valid'][5] and math.isnan(prepared['bars']['close'][5]))
            check('BBO四異常でもLast採用', all(row in prepared['prices']['raw_row_index'] for row in (6, 7, 8, 9)))
            check('BBO異常理由を別bit', all(prepared['diagnostics']['book_reasons_accepted'][str(bit)] >= 1 for bit in (1, 16, 32, 128)))

        # ----------------------------------------
        # Cont式と距離重みは簡単な3観測のFraction算術で別計算する。
        raw = [record(start + offset, 4000 + index * .5, index) for index, offset in enumerate((1, 2, 3, 61))]
        for index, quantity in enumerate((10, 14, 12, 10)):
            raw[index]['Buy1']['Qty'], raw[index]['Sell1']['Qty'] = quantity, 10
        prepared = subject.prepare_session(arrays(raw, start, end), start, end)
        imbalance = sum((Fraction(0), Fraction(4, 24), Fraction(2, 22)), Fraction()) / 3
        check('L1比平均はFraction一致', math.isclose(prepared['bars']['book_imbalance'][0], float(imbalance), abs_tol=1e-12))
        check('Cont同価格quantity差2遷移の規格化', math.isclose(prepared['bars']['book_ofi'][0], 2 / 6))
        check('Cont分境界を跨がない', prepared['bars']['book_flow_count'][0] == 2 and prepared['bars']['book_flow_count'][1] == 0)
        check('正常気配率とflow資格', prepared['bars']['book_quote_valid'][0])
        expected_depth = []
        for current in raw[:3]:
            qb = sum((Fraction(current[f'Buy{level + 1}']['Qty'], 1 + level) for level in range(10)), Fraction())
            qa = sum((Fraction(current[f'Sell{level + 1}']['Qty'], 1 + level) for level in range(10)), Fraction())
            expected_depth.append((qb - qa) / (qb + qa))
        check('十段距離重みはFraction一致', math.isclose(prepared['bars']['book_depth'][0], float(sum(expected_depth, Fraction()) / 3), abs_tol=1e-12))
        for key in ('Buy1', 'Sell1'):
            damaged = json.loads(json.dumps(raw))
            damaged[1][key]['Qty'] = 0
            result = subject.prepare_session(arrays(damaged, start, end), start, end)
            check('数量未知はLast足を壊さない', result['bars']['valid'][0])
            check('数量不正隣接のflowを復元しない', result['bars']['book_flow_count'][0] == 0)
        empty = subject.prepare_session(arrays([], start, end), start, end)
        check('空合成は空価格と全未知足', len(empty['prices']['last']) == 0 and not empty['bars']['valid'].any())

        # ----------------------------------------
        # 生成元103とv2を合成JSONにだけ通し、現在値と出来高の同値を調べる。
        producer = load_source(ROOT / 'work/wave_v103/input/core.py', '旧44列の合成生成元')
        correction = load_correction(ROOT / 'work/wave_v103/input_v2/correction.py')
        raw = [record(start + offset, 4000 + index * .5, index) for index, offset in enumerate((0, 1, 2, 1, 4, 5, 6, 7, 8, 61, 62))]
        raw[2]['TradingVolumeTime'] = stamp(start + 3)
        raw[4]['TradingVolumeTime'] = stamp(start + 2)
        raw[5]['TradingVolume'] = 10
        raw[7]['CurrentPrice'] = None
        raw[8]['Buy1']['Price'] = None
        legacy, _ = producer.extract_rows(enumerate(raw), start, end)
        revised, _ = correction['correct_arrays'](legacy)
        extracted = arrays(raw, start, end)
        for field in extracted:
            if field in revised:
                equal(f'旧生成元と新JSONL抽出{field}', extracted[field], revised[field])
        a = subject.prepare_session(revised, start, end)
        b = subject.prepare_session(extracted, start, end)
        for group in ('prices', 'bars'):
            for field in a[group]:
                equal(f'44列とJSONLの同契約{group}{field}', a[group][field], b[group][field])
        synthetic = OUT / '合成のみ_44列.npz'
        np.savez_compressed(synthetic, **revised)
        data = synthetic.read_bytes()
        info = dict(path=synthetic.relative_to(ROOT).as_posix(), bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        old_loaded = subject.read_old(info)
        for field in revised:
            equal(f'旧NPZ合成一読{field}', old_loaded[field], revised[field])
        synthetic_jsonl = OUT / '合成のみ_原順.jsonl'
        payload = ''.join(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n' for row in raw).encode('utf-8')
        synthetic_jsonl.write_bytes(payload)
        info = dict(path=synthetic_jsonl.relative_to(ROOT).as_posix(), bytes=len(payload),
                    sha256=hashlib.sha256(payload).hexdigest(), bounds=[start, end])
        loaded = subject.read_jsonl(info)
        for field in extracted:
            equal(f'JSONL合成一読{field}', loaded[field], extracted[field])
        check('合成読取metadata同bytes', loaded['_read_metadata']['sha256'] == info['sha256'] and loaded['_read_metadata']['reads'] == 1)

        # ----------------------------------------
        # peerは前分制約と公開済み制約の両方を満たすものだけを選ぶ。
        peer = dict(t_s=np.arange(60, 420, 60, dtype=float), valid=np.ones(6, np.bool_),
                    pub_price_time_s=np.array([65, 180, 180, 300, 310, 370], float))
        own = dict(t_s=np.arange(60, 420, 60, dtype=float), valid=np.ones(6, np.bool_),
                   anchor=np.ones(6), pub_price_time_s=np.array([61, 121, 180, 241, 301, 361], float))
        matched = subject.strict_peer_join(own, peer)
        expected = []
        for row in range(6):
            possible = [i for i in range(6) if peer['valid'][i] and peer['t_s'][i] <= own['t_s'][row] - 60
                        and peer['pub_price_time_s'][i] <= own['pub_price_time_s'][row]]
            expected.append(possible[-1] if possible else -1)
        equal('相手前分かつ公開済の逐行選点', matched, np.asarray(expected, np.int64))
        check('同分は相手へ使わない', all(i < 0 or peer['t_s'][i] <= own['t_s'][r] - 60 for r, i in enumerate(matched)))
        peer['valid'][1] = False
        check('相手空分は遡った実在足のみ', subject.strict_peer_join(own, peer)[2] == 0)

        proof.update(全合格=True, 検査数=len(CHECKS), 検査=CHECKS,
            source_SHA256={str((HERE / name).relative_to(ROOT).as_posix()): hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                           for name in ('input.py', 'artificial_input.py')},
            生成元source_SHA256={str(path.relative_to(ROOT).as_posix()): hashlib.sha256(path.read_bytes()).hexdigest()
                               for path in (ROOT / 'work/wave_v103/input/core.py', ROOT / 'work/wave_v103/input_v2/correction.py')},
            範囲='合成現在値・板・旧生成元・合成NPZ/JSONLだけ。現在値到達の予測性能、実約定、利益は未測定。')
    except BaseException as error:
        proof.update(全合格=False, 検査数=len(CHECKS), 検査=CHECKS, error=repr(error))
        raise
    finally:
        destination.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査数=len(CHECKS), 実入力=0, 金融=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
