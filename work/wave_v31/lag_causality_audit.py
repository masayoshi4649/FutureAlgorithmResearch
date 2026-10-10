"""方向の遅延と開始待機を、損益を使わず独立な時系列参照で監査する。"""

from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
import pickle
import socket
import sys
import urllib.request
from zoneinfo import ZoneInfo

import numpy as np
from numba import njit

HERE = Path(__file__).resolve().parent
V30 = HERE.parent / 'wave_v30'
OLD = HERE.parent / 'wave_v23'
sys.dont_write_bytecode = True
sys.path.insert(0, str(V30))
from context_structure_audit import read, save, digest, original_hashes, reject_network


@njit
def independent_indices(times: np.ndarray, seconds: float) -> np.ndarray:
    """機能: 二ポインタでその時点までに観測された遅延元行を独立計算する。

    引数: times (ndarray[float]) は非減少時刻、seconds (float) は非負遅延。
    返り値: 参照行番号 (ndarray[int64])。履歴なしは−1、0秒は現在行。
    """
    output = np.full(len(times), -1, np.int64)
    if seconds == 0:
        return np.arange(len(times), dtype=np.int64)
    pointer = -1
    for row in range(len(times)):
        threshold = times[row] - seconds
        while pointer + 1 <= row and times[pointer + 1] <= threshold:
            pointer += 1
        output[row] = pointer
    return output


def expected_lanes(times: np.ndarray, lanes: tuple[np.ndarray, ...], seconds: float,
                   wait_only: bool) -> tuple[np.ndarray, ...]:
    """機能: 遅延3列又は共通の入口開始フラグ付き現在3列を独立生成する。

    引数: times (ndarray)、lanes (tuple[ndarray,...]) は入口/C/S、seconds (float)、wait_only (bool)。
    返り値: 期待する入口/C/S (tuple[ndarray,...])。
    """
    indices = independent_indices(times, seconds)
    present = indices >= 0
    delayed = []
    for values in lanes:
        out = np.zeros(len(times), np.int8)
        out[present] = values[indices[present]]
        delayed.append(out)
    if not wait_only:
        return tuple(delayed)
    gate = np.maximum.accumulate(np.abs(delayed[0])) != 0
    return tuple(np.where(gate, values, 0).astype(np.int8) for values in lanes)


def same(actual: tuple[np.ndarray, ...], expected: tuple[np.ndarray, ...], label: str) -> None:
    """機能: 3列を型と値を含めて照合し、現在値や入力変更を見逃さない。

    引数: actual/expected (tuple[ndarray,...])、label (str)。返り値: なし (None)。
    """
    assert len(actual) == len(expected) == 3, label
    for lane, wanted in zip(actual, expected):
        assert lane.dtype == np.int8 and np.isin(lane, [-1, 0, 1]).all(), label
        np.testing.assert_array_equal(lane, wanted, err_msg=label)


def signature(arrays: tuple[np.ndarray, ...]) -> str:
    """機能: 入力配列の変更がないことを指紋で検査する。

    引数: arrays (tuple[ndarray,...])。返り値: SHA256 (str)。
    """
    value = hashlib.sha256()
    for array in arrays:
        value.update(str((array.shape, array.dtype)).encode())
        value.update(array.tobytes())
    return value.hexdigest()


def synthetic_check(transform) -> dict:
    """機能: 同値時刻・飛び・境界・待機解除を人工入力だけで反証する。

    引数: transform (callable) は times/lanes/seconds/wait_only を受ける変換。
    返り値: 合成検査件数 (dict)。
    """
    times = np.array([0., 0., 1., 1., 1799., 1800., 1800., 1801., 3599., 3600., 5400.])
    lanes = (np.array([0, 1, -1, 0, 1, -1, 0, 1, 0, -1, 1], np.int8),
             np.array([1, 0, 1, -1, 0, 1, -1, 0, 1, 0, 1], np.int8),
             np.array([-1, 1, 0, 1, -1, 0, 1, -1, 0, 1, -1], np.int8))
    count = 0
    for seconds, wait in ((0., False), (1800., False), (3600., False), (1800., True), (3600., True)):
        full = transform(times, lanes, seconds, wait)
        same(full, expected_lanes(times, lanes, seconds, wait), '合成独立asof')
        for cut in range(1, len(times) + 1):
            same(transform(times[:cut], tuple(v[:cut] for v in lanes), seconds, wait),
                 tuple(v[:cut] for v in full), '同値時刻を途中で切断')
        same(transform(times, tuple(-v for v in lanes), seconds, wait), tuple(-v for v in full), '合成上下反射')
        same(transform(times + 1000000, lanes, seconds, wait), full, '合成時刻平行移動')
        for entry in (np.zeros(len(times), np.int8), np.ones(len(times), np.int8), -np.ones(len(times), np.int8)):
            changed = (entry, lanes[1], lanes[2])
            same(transform(times, changed, seconds, wait), expected_lanes(times, changed, seconds, wait), '入口依存の共有開始フラグ')
        count += 1
    old_bad = lanes[0][np.searchsorted(times, times, side='right') - 1]
    assert not np.array_equal(old_bad, lanes[0]), '0秒asofの先取り反例が有効でなければならない'
    positive = independent_indices(times, 1800.)
    assert positive[5] == 1 and positive[6] == 1 and positive[7] == 3
    assert np.all(positive < np.arange(len(times)))
    return dict(合成5変形=count, 全11切断の同値時刻監査=count * len(times),
                上下反射=count, 時間平行移動=count, 入口共有フラグ反例=count * 3,
                ゼロ秒asof先取り反例=True, 遅延境界ちょうど=True)


def check_case(transform, ready: dict, lanes: tuple[np.ndarray, ...]) -> dict:
    """機能: 一区間の全5変形を独立生成・未来切断・将来変更で照合する。

    引数: transform (callable)、ready (dict)、lanes (tuple[ndarray,...]) は入口/C/S。
    返り値: 検査件数と各変形の指紋 (dict)。売買再生や損益参照は行わない。
    """
    times = ready['time_s']
    assert np.isfinite(times).all() and np.all(np.diff(times) >= 0)
    assert all(len(v) == len(times) and v.dtype == np.int8 for v in lanes)
    before = signature((ready['time_s'], ready['seq'], ready['last'], ready['atr']) + lanes)
    counters = dict(独立変形照合=0, 同一行ゼロ遅延=0, prefix列数=0, 未来方向改変列数=0,
                    未来時刻改変列数=0, 上下反射列数=0, 時刻平行移動列数=0)
    fingerprints = {}
    variants = (('V000', 0., False), ('V030', 1800., False), ('V060', 3600., False),
                ('W030', 1800., True), ('W060', 3600., True))
    for identifier, seconds, wait in variants:
        actual = transform(times, lanes, seconds, wait)
        wanted = expected_lanes(times, lanes, seconds, wait)
        same(actual, wanted, '全入力の独立二ポインタ照合')
        fingerprints[identifier] = signature(actual)
        counters['独立変形照合'] += 3
        if seconds == 0:
            same(actual, lanes, '0秒は現在行identity')
            counters['同一行ゼロ遅延'] += 3
        else:
            indices = independent_indices(times, seconds)
            valid = indices >= 0
            assert np.all(indices[valid] < np.arange(len(times))[valid])
            assert np.all(times[indices[valid]] <= times[valid] - seconds)
        for fraction in (.27, .63):
            cut = max(2, min(len(times) - 1, int(len(times) * fraction)))
            same(transform(times[:cut], tuple(v[:cut] for v in lanes), seconds, wait),
                 tuple(v[:cut] for v in actual), '実データprefix')
            counters['prefix列数'] += 3
            changed = tuple(v.copy() for v in lanes)
            for column in changed:
                column[cut:] = np.where(column[cut:] == 0, 1, -column[cut:])
            same(tuple(v[:cut] for v in transform(times, changed, seconds, wait)),
                 tuple(v[:cut] for v in actual), '未来方向変更')
            counters['未来方向改変列数'] += 3
            changed_times = times.copy()
            changed_times[cut:] += 86400.
            same(tuple(v[:cut] for v in transform(changed_times, lanes, seconds, wait)),
                 tuple(v[:cut] for v in actual), '未来時刻変更')
            counters['未来時刻改変列数'] += 3
        same(transform(times, tuple(-v for v in lanes), seconds, wait),
             tuple(-v for v in actual), '実データ上下反射')
        counters['上下反射列数'] += 3
        same(transform(times + 86400., lanes, seconds, wait), actual, '実データ時刻平行移動')
        counters['時刻平行移動列数'] += 3
    assert before == signature((ready['time_s'], ready['seq'], ready['last'], ready['atr']) + lanes)
    return dict(**counters, 同値時刻の隣接行数=int(np.sum(np.diff(times) == 0)),
                各変形SHA256=fingerprints, 価格ATRと元入力不変=True)


def production_transform(times: np.ndarray, lanes: tuple[np.ndarray, ...],
                         seconds: float, wait_only: bool) -> tuple[np.ndarray, ...]:
    """機能: 監査する実装へ接続し、公開した参照元行も独立計算と照合する。

    引数: times (ndarray)、lanes (tuple[ndarray,...])、seconds (float)、wait_only (bool)。
    返り値: 実装が出力した入口/C/S (tuple[ndarray,...])。
    """
    sys.path.insert(0, str(HERE))
    import lag_design
    mode = 'identity' if seconds == 0 else ('start_only' if wait_only else 'lag')
    variants = [v for v in lag_design.catalog() if v['delay_seconds'] == seconds and v['mode'] == mode]
    assert len(variants) == 1
    output = lag_design.transform(times, *lanes, variants[0])
    assert len(output) == 4
    np.testing.assert_array_equal(output[3], independent_indices(times, seconds), err_msg='公開source行の独立照合')
    return tuple(output[:3])


def freeze() -> dict:
    """機能: 損益前の監査範囲と実装指紋を固定する。

    引数: なし。返り値: 固定した監査仕様 (dict)。
    """
    value = dict(固定日時=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
                 監査コードSHA256=digest(Path(__file__)), lag_design_SHA256=digest(HERE / 'lag_design.py'),
                 設計計画SHA256=digest(HERE / 'lag_audit_plan.md'),
                 旧構造監査SHA256=digest(V30 / 'context_structure_before_pnl.json'),
                 対象='12入口×26区間×5変形×入口/C/S。損益や順位を参照しない。',
                 独立参照='searchsortedの再利用なし。二ポインタで同時刻末尾と現在行順を照合する。',
                 時間境界='0秒identity。正遅延は30分/60分前以下の最後の過去行、履歴不足0。',
                 待機='遅延入口の過去非0の累積フラグ。C/Sも同じフラグで現在方向を解放する。',
                 全区間検査='27%/63%切断、同点の将来方向/時刻改変、上下反射、時刻平行移動。',
                 会計検査='別スクリプトで保存全420×26の会計・37%切断・73%将来改変・反射。',
                 通信='API0、現在保存物を使用しない。')
    path = HERE / 'lag_causality_fixed.json'
    if path.exists():
        old = read(path)
        assert {k: v for k, v in old.items() if k != '固定日時'} == {k: v for k, v in value.items() if k != '固定日時'}
        return old
    save(path, value)
    return value


def main() -> None:
    """機能: 遅延変換を損益前に全入力で監査し、全合格後だけ開始用JSONを保存する。

    引数: なし。返り値: なし (None)。売買エンジンを実行しない。
    """
    socket.socket.connect = reject_network
    socket.create_connection = reject_network
    urllib.request.OpenerDirector.open = reject_network
    assert not list((HERE / 'summaries').glob('*.json')), '構造監査は新対照の損益前に行う'
    protocol = freeze()
    synthetic = synthetic_check(production_transform)
    originals = original_hashes()
    old = read(V30 / '探索条件の固定.json')
    assert len(old['signals']) == 12
    inputs = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    assert len(inputs) == 26
    input_hash = digest(OLD / 'inputs.pkl')
    output, source_hashes = [], {}
    for spec in old['signals']:
        columns = []
        for folder in ('directions', 'contexts', 'contexts_own'):
            path = V30 / folder / f"{spec['id']}.npz"
            source_hashes[str(path)] = digest(path)
            with np.load(path) as archive:
                assert set(archive.files) == {'|'.join(key) for key in inputs}
                columns.append({key: archive['|'.join(key)] for key in inputs})
        for key, ready in inputs.items():
            checked = check_case(production_transform, ready, tuple(col[key] for col in columns))
            output.append(dict(signal=spec['id'], session=key[0], symbol=key[1], **checked))
        print(spec['id'], '26区間×5変形の独立asof・未来除去一致', flush=True)
    assert len(output) == 312
    assert input_hash == digest(OLD / 'inputs.pkl')
    assert source_hashes == {path: digest(Path(path)) for path in source_hashes}
    assert originals == original_hashes()
    assert freeze() == protocol
    fields = ('独立変形照合', '同一行ゼロ遅延', 'prefix列数', '未来方向改変列数',
              '未来時刻改変列数', '上下反射列数', '時刻平行移動列数')
    result = dict(構造検査合格=True, 損益参照前=True, 売買再生実行=False, 全入口数=12, 全入力数=312,
                  全変形数=5, 全方向列数=4680, 検査件数={name: sum(r[name] for r in output) for name in fields},
                  同値時刻の隣接行数_1入力分=sum(int(np.sum(np.diff(r['time_s']) == 0)) for r in inputs.values()),
                  合成検査=synthetic, 監査固定=protocol, lag_design_SHA256=protocol['lag_design_SHA256'],
                  入力SHA256=input_hash, 元3列SHA256=source_hashes, 原本78SHA256=originals,
                  各入力=output, API取得数=0, 現在データ使用=False,
                  解釈='遅延で参加時刻・方向・保有撤回が変わる。鮮度だけの純粋な因果効果ではない。')
    save(HERE / 'lag_causality_audit.json', result)
    save(HERE / 'lag_causality_before_pnl.json', result)
    lines = ['# 遅延と待機の損益前独立監査', '',
             '12入口×26区間×5変形×3列＝4,680列は独立二ポインタ参照と完全一致した。売買損益は参照していない。', '',
             '- V000は現在行そのもの。同値時刻の後続行を拾う一般asofを使っていない。',
             '- V030/V060は現在より前の行だけを参照し、履歴不足は0。遅延境界ちょうどを含める。',
             '- W030/W060は同じ遅延入口の初回非0まで3列を0にし、その行以降は現在の3列を使う。',
             '- 全入力で27%/63%切断、将来方向変更、将来時刻変更、売買反射、時間平行移動が一致した。',
             '- 合成の同時刻途中切断と0秒asof先取り反例を確認。価格・ATR・seq・原方向は変えていない。',
             '- 原本78ファイルと元方向3列・入力のSHAは前後不変。APIと現在保存物は使用していない。',
             '', 'これは遅延変換の因果性の検査であり、鮮度だけの純効果を証明しない。参加時刻と保有撤回も変化する。']
    (HERE / 'lag_causality_audit.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print({k: result[k] for k in ('構造検査合格', '全入力数', '全方向列数', '検査件数')}, flush=True)


if __name__ == '__main__':
    main()
