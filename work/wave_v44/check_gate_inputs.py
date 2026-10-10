"""旧A0影だけを再生成し、新しい悪化許可列の入力因果性を確認する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import profit_gate as gate

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent/'wave_v38'))
import adaptive_runner as old


def digest(path: Path) -> str:
    """機能: 旧入力と今回の検査実装を内容で結合する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1048576): h.update(block)
    return h.hexdigest()


def clipped(ready: dict, count: int) -> dict:
    """機能: 原本時刻が同じ行の途中も、行順を保って切断する。

    引数: ready (dict)、count (int)。返り値: 原本配列を複写した入力 (dict)。
    """
    n = len(ready['last'])
    return {k: v[:count].copy() if isinstance(v, np.ndarray) and v.ndim and len(v) == n else v
            for k, v in ready.items()}


def exact(left: tuple, right: tuple, count: int) -> None:
    """機能: 方向・元公開行・全許可証拠の過去範囲を厳密照合する。

    引数: left/right (tuple)、count (int)。返り値: なし (None)。
    """
    for a, b in zip(left[:2], right[:2]): np.testing.assert_array_equal(a[:count], b[:count])
    assert set(left[2]) == set(right[2])
    for name in left[2]: np.testing.assert_array_equal(left[2][name][:count], right[2][name][:count])


def main() -> None:
    """機能: 全26の旧影を独立再生成し、全16入力仕様の情報時点を確認する。

    引数: なし。返り値: なし (None)。新ゲートを実口座へ渡さず、新戦略収支を計算しない。
    元入口・B00の因果性は既存入力監査へSHA結合し、ここでは列合成と影を再検査する。
    """
    old.initialize()
    assert Path(old.engine.shadow_engine.__file__).resolve() == HERE.parent/'wave_v38/engine_shadow_plan.py'
    spec = next(s for s in old.FIXED['conditions'] if s['id'] == 'H019__B00_RB00_F25_N1__R1__V000')
    paths = [Path(__file__), HERE/'profit_gate.py', HERE/'check_profit_gate.py', HERE/'check_profit_gate.json',
             HERE.parent/'wave_v23/inputs.pkl', HERE.parent/'wave_v38/branch_input_runtime_fixed.json',
             HERE.parent/'wave_v38/engine_shadow_plan.py', HERE.parent/'wave_v38/engine_partial_restore.py',
             HERE.parent/'wave_v38/adaptive_runner.py', HERE.parent/'wave_v38/探索条件の固定.json']
    # ----------------------------------------
    # 利用する旧列だけの実体と既存入力監査を全て照合し、価格・窓自体の再探索はしない。
    prior = old.read(HERE.parent/'wave_v38/branch_input_runtime_fixed.json')
    prior_sha = prior.get('SHA256', prior.get('参照SHA256', prior.get('参照資料SHA256', {})))
    assert prior_sha, '既存入力の固定指紋がありません'
    for name, value in prior_sha.items(): assert digest(ROOT/name) == value, name
    references = {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}
    specs = [(0., 'direction')]+[(t, m) for t in gate.THRESHOLDS[1:] for m in gate.MODES]
    rows = []
    for key, ready in sorted(old.INPUTS.items()):
        state, bad, source, *_ = old.columns(spec, key)
        valid = old.inputs.publication_valid('B00', key, 1.)
        config = old.base.managers.make_config(old.FIXED['manager'], key[1], ready)
        full = old.engine.make_shadow(ready, state, config, False, 0.)
        n = len(state); a = max(2, int(n*.37))
        repeated = np.flatnonzero(np.diff(ready['time_s']) == 0)+1
        b = int(repeated[np.argmin(abs(repeated-int(n*.73)))]) if len(repeated) else int(n*.73)
        cases = []
        for end in (a, b):
            r = clipped(ready, end)
            sh = old.engine.make_shadow(r, state[:end].copy(), config, False, 0.)
            np.testing.assert_array_equal(sh['plans'], full['plans'][:end])
            cases.append((end, r, sh, bad[:end], source[:end], valid[:end]))
        future = clipped(ready, n); future['last'][b:] += ready['tick']*37; future['atr'][b:] *= 3
        state_future = state.copy(); state_future[b:] *= -1
        bad_future = bad.copy(); bad_future[b:] *= -1
        source_future = source.copy(); source_future[b:] = np.arange(b, n)
        valid_future = valid.copy(); valid_future[b:] = ~valid_future[b:]
        future_shadow = old.engine.make_shadow(future, state_future, config, False, 0.)
        np.testing.assert_array_equal(future_shadow['plans'][:b], full['plans'][:b])
        mirror = clipped(ready, n); center = 2.*float(ready['last'][0]); mirror['last'] = center-ready['last']
        reflected = old.engine.make_shadow(mirror, -state, config, False, 0.)
        for threshold, mode in specs:
            actual = gate.gate_bad(ready, full, bad, source, threshold, mode=mode, valid=valid)
            np.testing.assert_array_equal(actual[1], source)
            if threshold == 0: np.testing.assert_array_equal(actual[0], bad)
            for end, r, sh, x, sr, v in cases:
                short = gate.gate_bad(r, sh, x, sr, threshold, mode=mode, valid=v)
                exact(actual, short, end)
            changed = gate.gate_bad(future, future_shadow, bad_future, source_future, threshold, mode=mode, valid=valid_future)
            exact(actual, changed, b)
            reflected_gate = gate.gate_bad(mirror, reflected, -bad, source, threshold, mode=mode, valid=valid)
            np.testing.assert_array_equal(reflected_gate[0], -actual[0])
            np.testing.assert_array_equal(reflected_gate[1], actual[1])
            for name in actual[2]:
                np.testing.assert_allclose(reflected_gate[2][name], actual[2][name], rtol=0, atol=1e-8)
            rows.append(dict(session=key[0], symbol=key[1], threshold_atr=threshold, mode=mode,
                             先頭切断一致=True, 同時刻境界一致=True, 未来変更一致=True, 上下反射一致=True,
                             元公開行不変=True, 旧方向恒等=threshold == 0, 原本行数=n,
                             切断行=a, 同時刻側切断行=b, 元方向SHA256=hashlib.sha256(bad.tobytes()).hexdigest(),
                             許可方向SHA256=hashlib.sha256(actual[0].tobytes()).hexdigest()))
        print('|'.join(key)+' 入力16仕様の影再生成・許可境界一致', flush=True)
        del full, future_shadow, reflected, cases, actual, changed, reflected_gate
    for name, value in references.items(): assert digest(ROOT/name) == value, name
    assert len(rows) == 26*16
    value = dict(全合格=True, 全入力数=26, 入力仕様数=16, 全セル数=len(rows),
                 先頭切断件数=416, 同時刻境界件数=416, 未来変更件数=416, 上下反射件数=416,
                 旧方向恒等件数=26, 元公開行全不変=True, 結果=rows, 参照SHA256=references,
                 旧入力参照SHA256=prior_sha, 旧A0影のみ再生成=True, 新戦略売買再生=False,
                 新損益資料読取=False, API取得数=0)
    (HERE/'gate_input_audit.json').write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print('全416入力セルの因果・反射検査完了。新ゲートの経済結果は未再生。', flush=True)


if __name__ == '__main__':
    main()
