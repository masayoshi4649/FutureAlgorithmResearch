"""入口部品の旧結果一致・原本順・未来独立性を売買なしで検査する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys
import urllib.request

import numpy as np
import pandas as pd

import component_signals as signals


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / 'wave_v43'))
from check_window_signals import slice_inputs, transformed


def sha(path: Path) -> str:
    """機能: 保存入力と旧実装の不変性を内容指紋で確認する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(8388608):
            digest.update(block)
    return digest.hexdigest()


def save(path: Path, value: dict) -> None:
    """機能: 非有限数を許さず日本語の検査記録を保存する。

    引数: path (Path)、value (dict)。返り値: なし (None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')


def deny(*args: object, **kwargs: object) -> None:
    """機能: この信号検査からの新しいデータ通信を拒否する。

    引数: 任意 (object)。返り値: なし (None)、例外。
    """
    raise AssertionError('新しいデータは取得しません')


def candle_copy(keys: list, label: str, cutoff: float | None, pivots: dict | None) -> Path:
    """機能: 旧13セッションの足を新作業内だけへ複写して変形する。

    引数: keys (list[tuple])、label (str)、cutoff (float|None)、pivots (dict|None)。
    返り値: 未来変更又は上下反射を加えた確定足の参照根 (Path)。
    """
    output = (HERE / 'component_audit_candles' / label).resolve()
    assert output.is_relative_to((HERE / 'component_audit_candles').resolve())
    for key in keys:
        assert key[0] != '2026-09-29_Night'
        frame = pd.read_csv(ROOT / 'candle_1min' / key[1] / (key[0]+'.csv'))
        if cutoff is not None:
            release = pd.to_datetime(frame.time).dt.as_unit('ns').astype('int64').to_numpy(float)/1e9+120
            mask = release >= cutoff
            for column in ('open', 'high', 'low', 'close', 'volume'):
                frame[column] = frame[column].astype(float)
                frame.loc[mask, column] = frame.loc[mask, column]*1.7+7000
            frame.loc[mask, 'closed'] = True
            if 'volume_complete' in frame:
                frame.loc[mask, 'volume_complete'] = True
        if pivots is not None:
            pivot = pivots[key]
            high, low = frame.high.copy(), frame.low.copy()
            for column in ('open', 'close'):
                frame[column] = 2*pivot-frame[column]
            frame['high'], frame['low'] = 2*pivot-low, 2*pivot-high
        target = output / 'candle_1min' / key[1] / (key[0]+'.csv')
        target.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(target, index=False, encoding='utf-8')
    return output


def calculate(inputs: dict, features: dict, root: Path) -> dict:
    """機能: 指定根と入力から全26仕様を損益なしで計算する。

    引数: inputs/features (dict)、root (Path)。返り値: 仕様ID別方向列 (dict)。
    """
    signals.set_root(root)
    return {spec['id']: signals.build(spec, inputs, features) for spec in signals.catalog()}


def synthetic() -> dict:
    """機能: 部品の丸め・相手公開境界・同秒順序・不使用指定を検査する。

    引数: なし。返り値: 人工検査の記録 (dict)。
    """
    hierarchy = signals.HIERARCHY
    rounding = {str(scale): [hierarchy._size(value*scale) for value in (15, 60, 3, 30)]
                for scale in signals.SCALES}
    assert list(rounding.values()) == [[12, 48, 2, 24], [15, 60, 3, 30], [18, 72, 4, 36]]
    model = {('人工', 'TOPIX'): dict(time_s=np.array([0.]), direction=np.array([1])),
             ('人工', 'NK225'): dict(time_s=np.array([0., 100.]), direction=np.array([-1, 1]))}
    for multiplier in signals.SCALES:
        delay = hierarchy._size(60*multiplier)
        params = signals.legacy_spec(signals.specification(peer_scale=multiplier))['params']
        actual = hierarchy._allowed(('人工', 'TOPIX'),
            np.array([delay-.01, delay, 100+delay-.01, 100+delay]), model, params)
        np.testing.assert_array_equal(actual, [0, 0, 0, 1])
    params = signals.legacy_spec(signals.specification(peer_confirm=False))['params']
    np.testing.assert_array_equal(hierarchy._allowed(('人工', 'TOPIX'), np.array([1., 101.]),
        {('人工', 'TOPIX'): model[('人工', 'TOPIX')]}, params), [1, 1])
    direction, _, _ = hierarchy._entry_filter(np.array([10, 11, 12]), np.array([100., 100., 101.]),
        np.ones(3, np.int8), np.array([11]), np.array([100.]), np.ones(1, np.int8),
        np.array([.1]), np.zeros(1), 1, 1.)
    np.testing.assert_array_equal(direction, [0, 1, 1])
    direction, _, _ = hierarchy._entry_filter(np.arange(5), np.arange(5, dtype=float),
        np.array([1, 1, 0, 1, 1]), np.array([0]), np.array([0.]), np.array([1]),
        np.array([.1]), np.zeros(1), 1, 1.)
    np.testing.assert_array_equal(direction, [1, 1, 0, 0, 0])
    rejected = 0
    for kwargs in ({'main_scale': .9}, {'short_confirm': 1}, {'peer_confirm': 1},
                   {'main_scale': True}, {'peer_confirm': False, 'peer_scale': .8},
                   {'short_confirm': False, 'short_scale': .8}):
        try:
            signals.specification(**kwargs)
        except ValueError:
            rejected += 1
    assert rejected == 6
    return dict(全合格=True,丸め窓=rounding,相手48_60_72秒境界=True,
        相手なしは相手データ不要=True,同秒後続行を先取りしない=True,旧支持の復活禁止=True,不正指定拒否数=rejected)


def main() -> None:
    """機能: 旧26入力の一致と各676件の因果検査を完了して入口列を保存する。

    引数: なし。返り値: なし (None)。新ナイト・新損益・売買注文器は読まない。
    """
    socket.create_connection = deny
    socket.socket.connect = deny
    urllib.request.urlopen = deny
    proof = synthetic()
    references = [HERE/'component_signals.py', Path(__file__),
        HERE.parent/'wave_v27/hierarchy_signals.py', HERE.parent/'wave_v27/hierarchy_design_fixed.json',
        HERE.parent/'wave_v23/signals.py', HERE.parent/'wave_v23/inputs.pkl',
        HERE.parent/'wave_v23/features_depth.pkl', HERE.parent/'wave_v43/check_window_signals.py']
    references += [HERE.parent/f'wave_v27/directions/H{code}.npz' for code in ('016', '017', '018', '019')]
    references += [HERE.parent/f'wave_v43/members/C{code}.npz' for code in ('080', '120')]
    before = {path.relative_to(ROOT).as_posix(): sha(path) for path in references}
    inputs = pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    features = pickle.loads((HERE.parent/'wave_v23/features_depth.pkl').read_bytes())
    assert len(inputs) == 26 and not any(key[0] == '2026-09-29_Night' for key in inputs)
    for key in inputs:
        path = ROOT/'candle_1min'/key[1]/(key[0]+'.csv')
        before[path.relative_to(ROOT).as_posix()] = sha(path)
    baseline = calculate(inputs, features, ROOT)
    equality = []
    for spec, path in [(signals.specification(peer_confirm=peer, short_confirm=short),
                       HERE.parent/f'wave_v27/directions/H{16+int(peer)+2*int(short):03d}.npz')
                      for peer in (False, True) for short in (False, True)] + [
                          (signals.specification(main_scale=scale, short_scale=scale),
                           HERE.parent/f'wave_v43/members/C{round(scale*100):03d}.npz') for scale in (.8, 1.2)]:
        with np.load(path) as archive:
            assert set(archive.files) == {'|'.join(key) for key in inputs}
            for key in inputs:
                np.testing.assert_array_equal(baseline[spec['id']][key], archive['|'.join(key)])
                equality.append(dict(id=spec['id'],session=key[0],symbol=key[1],旧資料=path.relative_to(ROOT).as_posix()))
    assert len(equality) == 156
    print('旧H019・相手短期除去4仕様と旧複合2倍率：156入力完全一致', flush=True)
    # ----------------------------------------
    # 共通時計での切断・未来改変と、原本同秒途中のseq切断を別検査する。
    rows = []
    for session in sorted({key[0] for key in inputs}):
        keys = [(session, symbol) for symbol in ('TOPIX', 'NK225')]
        own = {key: inputs[key] for key in keys}
        frames = {key: features[key] for key in keys}
        start = max(value['start'] for value in own.values())
        end = min(value['time_s'][-1] for value in own.values())
        cutoff = start+(end-start)*.37
        counts = {key: int(np.searchsorted(value['time_s'], cutoff, side='left')) for key, value in own.items()}
        sliced, sf = slice_inputs(own, frames, counts)
        partial = calculate(sliced, sf, ROOT)
        future_cut = start+(end-start)*.73
        changed, cf, _ = transformed(own, frames, future_cut)
        future = calculate(changed, cf, candle_copy(keys, 'future_'+session, future_cut, None))
        mirrored, mf, pivots = transformed(own, frames, None)
        reflected = calculate(mirrored, mf, candle_copy(keys, 'reflection_'+session, None, pivots))
        for spec in signals.catalog():
            for key in keys:
                identifier = spec['id']
                original = baseline[identifier][key]
                future_n = int(np.searchsorted(own[key]['time_s'], future_cut, side='left'))
                np.testing.assert_array_equal(partial[identifier][key], original[:counts[key]])
                np.testing.assert_array_equal(future[identifier][key][:future_n], original[:future_n])
                np.testing.assert_array_equal(reflected[identifier][key], -original)
                rows.append(dict(id=identifier,session=key[0],symbol=key[1],全行=len(original),
                    prefix一致=True,未来改変一致=True,上下反射一致=True))
        for key in keys:
            times = own[key]['time_s']
            duplicates = np.flatnonzero(times[1:] == times[:-1])+1
            duplicates = duplicates[(duplicates > 1) & (duplicates < len(times)-1)]
            assert len(duplicates)
            count = int(duplicates[np.argmin(np.abs(duplicates-int(len(times)*.73)))])
            keep = {other: len(own[other]['seq']) for other in keys}
            keep[key] = count
            sliced, sf = slice_inputs(own, frames, keep)
            tied = calculate(sliced, sf, ROOT)
            for spec in signals.catalog():
                identifier = spec['id']
                np.testing.assert_array_equal(tied[identifier][key], baseline[identifier][key][:count])
                row = next(value for value in rows if value['id'] == identifier and
                           (value['session'], value['symbol']) == key)
                row.update(同秒切断一致=True,同秒切断行=count)
        print(session+'：全26仕様の途中切断・未来改変・反射・同秒seqが一致', flush=True)
    assert len(rows) == 676 and all(row.get('同秒切断一致') for row in rows)
    signals.set_root(ROOT)
    outputs = {}
    (HERE/'component_entries').mkdir(exist_ok=True)
    for identifier, directions in baseline.items():
        path = HERE/'component_entries'/(identifier+'.npz')
        np.savez_compressed(path, **{'|'.join(key): value for key, value in sorted(directions.items())})
        with np.load(path) as archive:
            for key, value in directions.items():
                np.testing.assert_array_equal(value, archive['|'.join(key)])
        outputs[path.relative_to(ROOT).as_posix()] = sha(path)
    for path, digest in before.items():
        assert sha(ROOT/path) == digest, path
    audit = dict(全合格=True,条件数=26,入力数=26,方向セル数=676,旧一致数=156,
        中央H019全26一致=True,prefix数=676,未来改変数=676,反射数=676,同秒切断数=676,
        人工=proof,旧一致=equality,検査=rows,条件=signals.catalog(),参照SHA256=before,
        出力SHA256=outputs,売買再生=False,新損益読取=False,新ナイト読取=False,API取得数=0)
    save(HERE/'component_signal_audit.json', audit)
    save(HERE/'component_signals_fixed.json', dict(全合格=True,条件=signals.catalog(),
        参照SHA256=before,入口保存列SHA256=outputs,
        監査SHA256=sha(HERE/'component_signal_audit.json'),売買再生=False,新損益読取=False))
    print('入口26条件、旧一致156、因果検査676×4：全合格。売買損益未計算', flush=True)


if __name__ == '__main__':
    main()
