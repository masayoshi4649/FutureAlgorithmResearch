"""減量・復元の全固定条件を、影を毎回作り直す因果・反射検査へ結ぶ。"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import partial_runner as runner
import partial_engine_audit as fixtures

engine = runner.engine
design = runner.design
api = runner.inputs
INPUTS, FIXED = {}, {}
REPRESENTATIVE = ('2026-09-22_Night', '2026-09-29_Day')
CURVES = ('curve', 'atr_curve', 'control_curve', 'slot_curve')
EVENTS = dict(trades=7, orders=0, cycles=2, prepare_events=1, entry_preparations=1,
              slot_events=0, adjustment_events=0, budget_events=0)
SHADOW_FIELDS = engine.FIELDS + ('plans', 'prepare_events', 'entry_preparations')


def read(path: Path) -> object:
    """機能: 通常又は圧縮JSONを読み込む。

    引数: path (Path)。返り値: 内容 (object)。
    """
    content = path.read_bytes()
    return json.loads(gzip.decompress(content) if path.suffix == '.gz' else content)


def save(path: Path, value: object) -> None:
    """機能: 日本語JSONを有限値だけで保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    path.write_bytes(gzip.compress(content, mtime=0) if path.suffix == '.gz' else content)


def digest(path: Path) -> str:
    """機能: 指紋を計算する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exact(a: np.ndarray, b: np.ndarray, name: str) -> None:
    """機能: 型・形状・欠測位置を含め配列を厳密照合する。

    引数: a/b (ndarray)、name (str)。返り値: なし (None)。
    """
    assert a.dtype == b.dtype and a.shape == b.shape, name
    assert np.array_equal(a, b, equal_nan=True), name


def close(a: np.ndarray, b: np.ndarray, name: str) -> None:
    """機能: 反射の価格加減算だけに固定の丸め許容を使う。

    引数: a/b (ndarray)、name (str)。返り値: なし (None)。
    """
    assert a.shape == b.shape, name
    np.testing.assert_allclose(a, b, rtol=0, atol=1e-6, equal_nan=True, err_msg=name)


def clipped(ready: dict, count: int) -> dict:
    """機能: 既知の場定数を保持して原本行だけ切断する。

    引数: ready (dict)、count (int)。返り値: 短縮入力 (dict)。
    """
    n = len(ready['last'])
    return {k: v[:count].copy() if isinstance(v, np.ndarray) and v.ndim and len(v) == n else v
            for k, v in ready.items()}


def replay(ready: dict, columns: tuple, config: dict, spec: dict) -> dict:
    """機能: 変更された入力から影と実枠を順に新規生成する。

    引数: ready/config/spec (dict)、columns (tuple[ndarray,...])。返り値: 実結果と独立影 (dict)。
    保存済み影・主runnerのキャッシュを一切受け取らない。
    """
    state, bad, bad_source, good, good_source, valid = columns
    shadow = engine.make_shadow(ready, state, config, spec['observed_fill'])
    return engine.run(ready, state, config, bad, bad_source, good, good_source, spec['policy'],
        observed_fill=spec['observed_fill'], detail=True, shadow=shadow, good_valid=valid)


def prefix(actual: dict, changed: dict, count: int) -> None:
    """機能: 過去の影計画・実枠・判断・約定を全列で厳密比較する。

    引数: actual/changed (dict)、count (int)。返り値: なし (None)。
    全期間statsは切断で変わるため対象にせず、行曲線と発生済み記録を全数照合する。
    """
    for field in CURVES:
        exact(actual[field][:count], changed[field][:count], field)
    for field, column in EVENTS.items():
        a, b = actual[field], changed[field]
        exact(a[a[:, column] < count], b[b[:, column] < count], field)
    left, right = actual['shadow'], changed['shadow']
    for field in ('curve', 'atr_curve', 'plans'):
        exact(left[field][:count], right[field][:count], '影/' + field)
    for field, column in EVENTS.items():
        if field not in left:
            continue
        a, b = left[field], right[field]
        exact(a[a[:, column] < count], b[b[:, column] < count], '影/' + field)


def reflected_result(actual: dict, mirror: dict, center: float, with_control: bool) -> None:
    """機能: 価格・全方向を同時反射した約定・保有・予算・枠を別変換で比較する。

    引数: actual/mirror (dict)、center (float)、with_control (bool)。返り値: なし (None)。
    """
    for field in ('trades', 'orders', 'cycles', 'curve', 'stats', 'atr_curve', 'prepare_events', 'entry_preparations'):
        expected = actual[field].copy()
        if field == 'trades':
            expected[:, 2] *= -1; expected[:, 4:6] = center - expected[:, 4:6]
        elif field == 'orders':
            expected[:, 3] *= -1; expected[:, 5] = center - expected[:, 5]
        elif field == 'cycles':
            expected[:, 8] *= -1
        elif field == 'curve':
            expected[:, [2, 3]] = expected[:, [3, 2]]
            expected[:, 5] += center * expected[:, 6]; expected[:, 6] *= -1
        elif field == 'stats':
            expected[[2, 3]] = expected[[3, 2]]
        elif field == 'atr_curve':
            expected[:, 0] *= -1
            expected[:, [4, 6, 8]] = center - expected[:, [4, 6, 8]]
        elif field == 'prepare_events':
            expected[:, 2] *= -1; expected[:, 3] = center - expected[:, 3]
        close(mirror[field], expected, '反射/' + field)
    if with_control:
        expected = actual['control_curve'].copy(); expected[:, 3] *= -1
        close(mirror['control_curve'], expected, '反射/管理')
        exact(mirror['slot_curve'], actual['slot_curve'], '反射/枠')
        expected = actual['slot_events'].copy()
        expected[:, 6] *= -1; expected[:, 7] = center - expected[:, 7]
        close(mirror['slot_events'], expected, '反射/枠イベント')
        close(mirror['adjustment_events'], actual['adjustment_events'], '反射/調整')
        close(mirror['budget_events'], actual['budget_events'], '反射/予算')
    else:
        # 初期化値や失効後の旧水準は注文に使われないため、使われる計画の価格だけ反射する。
        a, b = actual['plans'], mirror['plans']
        P = {name: i for i, name in enumerate(engine.PLAN_COLUMNS)}
        signed = ('direction', 'pending_direction')
        prices = ('anchor', 'extreme', 'stop_level', 'trail_level', 'split_level', 'pending_level')
        for name, index in P.items():
            if name in signed:
                close(b[:, index], -a[:, index], '影計画/' + name)
            elif name in prices:
                active = a[:, P['pending_direction']] != 0 if name == 'pending_level' else a[:, P['direction']] != 0
                close(b[active, index], center - a[active, index], '影計画/' + name)
            else:
                close(b[:, index], a[:, index], '影計画/' + name)


def audit_one(ready: dict, columns: tuple, config: dict, spec: dict) -> tuple[dict, dict]:
    """機能: 一入力の基準・切断・未来改変・上下反射を独立再生する。

    引数: ready/config/spec (dict)、columns (tuple)。返り値: 検査記録・基準結果 (tuple[dict,dict])。
    """
    n = len(ready['last']); cut = max(2, int(n * .37))
    duplicates = np.flatnonzero(np.diff(ready['time_s']) == 0) + 1
    future_cut = int(duplicates[np.argmin(abs(duplicates - int(n * .73)))]) if len(duplicates) else max(2, int(n * .73))
    actual = replay(ready, columns, config, spec)
    short = replay(clipped(ready, cut), tuple(v[:cut].copy() for v in columns), config, spec)
    prefix(actual, short, cut); del short
    changed = deepcopy(ready)
    changed['last'][future_cut:] = ready['last'][future_cut] + (np.arange(n - future_cut) % 71 + 100) * ready['tick']
    changed['atr'][future_cut:] = np.maximum(np.nan_to_num(ready['atr'][future_cut:], nan=1.) * 1.7, ready['tick'] * 2)
    alternate = [v.copy() for v in columns]
    for index in (0, 1, 3):
        alternate[index][future_cut:] = np.where(alternate[index][future_cut:] == 1, -1, 1)
    for index in (2, 4):
        alternate[index][future_cut:] = np.arange(future_cut, n)
    alternate[5][future_cut:] = ~alternate[5][future_cut:]
    other = replay(changed, tuple(alternate), config, spec)
    prefix(actual, other, future_cut); del other
    center = float(2 * np.ceil(np.max(ready['last'][np.isfinite(ready['last'])]) / ready['tick']) * ready['tick'])
    reflected = dict(ready, last=center - ready['last'])
    reflected_columns = tuple(-v if i in (0, 1, 3) else v.copy() for i, v in enumerate(columns))
    mirror = replay(reflected, reflected_columns, config, spec)
    reflected_result(actual, mirror, center, True)
    reflected_result(actual['shadow'], mirror['shadow'], center, False)
    return dict(原本行数=n, prefix行=cut, future行=future_cut, 同時刻群途中=bool(len(duplicates)),
                prefix一致=True, future一致=True, reflection一致=True, 影新規再生成数=4), actual


def synthetic() -> dict:
    """機能: 人工全363条件と乱数64条件を同じ監査経路へ流し、監査器の負例を拒否する。

    引数: なし。返り値: 人工検査の件数と記録 (dict)。新実相場の損益は読まない。
    """
    checks = []
    args = fixtures.fixture([100, 101, 103, 100, 103, 104, 100, 99, 101, 104, 100, 98, 95], (2, 6, 10), (4, 8))
    ready, state, config, bad, source, good, good_source = args
    ready['time_s'][:9] = [0, 1, 2, 3, 123, 123, 124, 245, 246]
    ready.update(session='人工', symbol='TOPIX')
    specs = design.catalog() + design.supplementary()
    for spec in specs:
        # 人工fixtureの公開機会だけへ全方針を適用し、基礎入力の意味は実データと混同しない。
        columns = (state, bad, source, good, good_source, np.ones(len(state), bool))
        if spec['random_seed'] is not None:
            columns = (*columns[:3], api.randomize_recovery(good, good_source, ready, ('人工', 'TOPIX'), spec['random_seed']), good_source, columns[5])
        checked, _ = audit_one(ready, columns, config, spec)
        checks.append(dict(id=spec['id'], **checked))
    primary = next(s for s in specs if s['primary'])
    columns = (state, bad, source, good, good_source, np.ones(len(state), bool))
    reference = replay(ready, columns, config, primary)
    rejected = []
    corrupt = deepcopy(reference); corrupt['control_curve'][1, 0] += 1
    try:
        prefix(reference, corrupt, 4)
    except AssertionError:
        rejected.append('過去管理列改変')
    else:
        raise AssertionError('過去の列改変を見逃した')
    corrupt = deepcopy(reference); corrupt['shadow']['plans'][1, 33] += 1
    try:
        prefix(reference, corrupt, 4)
    except AssertionError:
        rejected.append('過去影計画改変')
    else:
        raise AssertionError('影計画の改変を見逃した')
    changed = dict(ready, last=ready['last'] + 1.)
    try:
        engine.run(changed, state, config, bad, source, good, good_source, primary['policy'], shadow=reference['shadow'], good_valid=columns[5])
    except ValueError:
        rejected.append('変形入力への旧影流用')
    else:
        raise AssertionError('旧影キャッシュを受理した')
    bad_source = source.copy(); bad_source[2] = 3
    try:
        replay(ready, (state, bad, bad_source, good, good_source, columns[5]), config, primary)
    except ValueError:
        rejected.append('未来公開行参照')
    else:
        raise AssertionError('未来根拠を受理した')
    return dict(全合格=True, 人工条件数=len(checks), 検査=checks, 負例拒否数=len(rejected), 負例=rejected, 新実相場損益=False)


def source_paths() -> set[Path]:
    """機能: 入力固定と注文実装・監査実装を指紋へ結ぶ。

    引数: なし。返り値: 参照集合 (set[Path])。
    """
    paths = {Path(__file__), HERE / 'partial_causality_selftest.json', HERE / 'partial_input_fixed.json',
             HERE / 'partial_runner.py', HERE / 'partial_design.py', HERE / 'partial_engine_audit.py',
             HERE / 'engine_partial_restore.py', HERE / 'engine_shadow_plan.py', HERE / 'partial_inputs.py',
             HERE.parent / 'wave_v23/inputs.pkl', HERE.parent / 'wave_v35/探索条件の固定.json'}
    material = read(HERE / 'partial_input_fixed.json')
    for name, sha in material['SHA256'].items():
        assert digest(ROOT / name) == sha, name
        paths.add(ROOT / name)
    return paths


def prepare() -> dict:
    """機能: 全条件の対象・境界・許容・実装指紋を新損益前に固定する。

    引数: なし。返り値: 事前固定 (dict)。
    """
    path = HERE / 'partial_causality_fixed.json'
    specs = design.catalog() + design.supplementary()
    rules = dict(全条件ID=[s['id'] for s in specs], 代表期間=list(REPRESENTATIVE), 銘柄=['TOPIX', 'NK225'],
        主案全26=design.PRIMARY_ID, 主条件数=363, 補助条件数=64, 全検査入力数=427 * 4 + 22,
        主検査入力数=363 * 4 + 22, 補助検査入力数=64 * 4,
        prefix='37%原本行を残す。場末定数は変更しない。',
        future='73%近傍の同時刻群途中から価格/ATR/入口/悪化/回復/根拠行/公開品質を変更する。',
        reflection='価格C-p、入口/悪化/回復すべて反転。元方向×乱数符号も同じ公開元のまま反射。',
        影='基準・切断・未来変更・反射のすべてでmake_shadowを再実行。主runner影キャッシュを利用しない。',
        比較='全行曲線・枠・公開後判断・返済・注文・完結組・準備・独立影計画。切断statsのみ終端が違うため直接比較しない。',
        厳密='prefix/futureの配列は型・形状・全要素完全一致。', 反射許容=dict(rtol=0, atol=1e-6),
        保存照合='基準の全FIELDSと影9配列のshape/dtype/SHAを主保存fingerprintsへ完全一致。',
        全条件波別監査='partial_wave_audit.pyで全427×8を注文会計から検査。',
        結果前選別なし=True, 新実相場損益未読=True, API取得数=0)
    if path.exists():
        fixed = read(path); assert fixed['規則'] == rules
        for relative, sha in fixed['SHA256'].items(): assert digest(ROOT / relative) == sha, relative
        return fixed
    checks = synthetic(); save(HERE / 'partial_causality_selftest.json', checks)
    fixed = dict(規則=rules, 合成検査合格=True,
        固定日時=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
        SHA256={p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(source_paths())})
    save(path, fixed)
    return fixed


def initialize() -> None:
    """機能: 通信を拒否し固定済み入力と参照仕様だけを読む。

    引数: なし。返り値: なし (None)。
    """
    global INPUTS, FIXED
    socket.socket.connect = runner.reject_network; socket.create_connection = runner.reject_network
    INPUTS = pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    FIXED = read(HERE / '探索条件の固定.json')
    api.initialize(INPUTS)
    runner.INPUTS = INPUTS


def evaluate(spec: dict, supplementary: bool) -> dict:
    """機能: 指定条件の固定代表期間を全変換検査し、保存指紋へ接続する。

    引数: spec (dict)、supplementary (bool)。返り値: 条件単位の監査明細 (dict)。
    """
    destination = HERE / ('supplementary' if supplementary else '')
    ledger_path = destination / 'ledgers' / (spec['id'] + '.json.gz')
    ledgers = read(ledger_path)
    by_key = {(r['session'], r['symbol']): r for r in ledgers}
    assert len(ledgers) == len(by_key) == 26 and set(by_key) == set(INPUTS)
    rows = []
    for key, ready in sorted(INPUTS.items()):
        if not spec['primary'] and key[0] not in REPRESENTATIVE:
            continue
        columns = runner.columns(spec, key)
        config = runner.base.managers.make_config(FIXED['manager'], key[1], ready)
        row, actual = audit_one(ready, columns, config, spec)
        expected = by_key[key]
        assert runner.fingerprints(actual) == expected['result_fingerprints']
        assert runner.fingerprints(actual['shadow'], SHADOW_FIELDS) == expected['shadow_fingerprints']
        for name in runner.STORED:
            a = actual[name]
            b = np.asarray(expected[name], dtype=a.dtype).reshape(a.shape)
            exact(a, b, '保存/' + name)
        rows.append(dict(session=key[0], symbol=key[1], 保存全指紋一致=True, **row))
    assert len(rows) == (26 if spec['primary'] else 4)
    result = dict(id=spec['id'], 全合格=True, 入力数=len(rows), 検査=rows,
        主保存SHA256=digest(ledger_path), 監査固定SHA256=digest(HERE / 'partial_causality_fixed.json'))
    save(destination / 'partial_causality_details' / (spec['id'] + '.json'), result)
    return result


def main() -> None:
    """機能: 事前合成固定のみ、又は起動証跡後の全条件因果監査を実行する。

    引数: --prepare/--supplementary (bool)、--workers (int)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser(); parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--supplementary', action='store_true'); parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    socket.socket.connect = runner.reject_network; socket.create_connection = runner.reject_network
    fixed = prepare()
    if args.prepare:
        print('427人工条件と負例を通過。因果監査対象1730入力を新損益前に固定。', flush=True)
        return
    guard = read(HERE / '起動前監査.json')
    assert guard['実行可能'] and guard['探索固定SHA256'] == digest(HERE / '探索条件の固定.json')
    destination = HERE / ('supplementary' if args.supplementary else '')
    specs = design.supplementary() if args.supplementary else design.catalog()
    assert read(destination / '主再生の完了.json')['全条件数'] == len(specs)
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize) as pool:
        jobs = [pool.submit(evaluate, spec, args.supplementary) for spec in specs]
        for job in as_completed(jobs):
            rows.append(job.result())
            print(f'{len(rows)}/{len(specs)} 因果・反射一致', flush=True)
    count = sum(r['入力数'] for r in rows)
    assert count == (256 if args.supplementary else 1474)
    prepare()
    payload = dict(全合格=True, 条件数=len(specs), 入力数=count, prefix数=count, future数=count,
        reflection数=count, 影新規再生成数=count * 4, 全結果指紋一致=True,
        結果=sorted(rows, key=lambda r: r['id']), 監査規則=fixed,
        探索固定SHA256=digest(HERE / '探索条件の固定.json'), 現在保存物使用=False, API取得数=0)
    save(destination / 'partial_causality_audit.json', payload)
    print(dict(全合格=True, 条件数=len(specs), 入力数=count), flush=True)


if __name__ == '__main__':
    main()
