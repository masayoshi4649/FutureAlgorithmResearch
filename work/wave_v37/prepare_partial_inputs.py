"""既存の監査済み列を再利用し、B06の窓変更2列だけを新規生成する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent/'wave_v35'))
import deterioration_signals as source
sys.path.insert(0, str(HERE))
import partial_inputs as adapter


def digest(path: Path) -> str:
    """機能: 読取・生成資料を内容のSHAで結ぶ。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> object:
    """機能: UTF-8固定JSONを読む。

    引数: path (Path)。返り値: JSON内容 (object)。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def save(path: Path, value: object) -> None:
    """機能: 有限のJSONを作業領域へ保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def reject_network(*args: object, **kwargs: object) -> None:
    """機能: 保存入力作業からの通信を拒否する。

    引数: args/kwargs (object)。返り値: なし (None)、常に例外。
    """
    raise RuntimeError('保存済み原本だけを使う')


def specs() -> list[dict]:
    """機能: B06の窓だけを96/144秒へ変えた2つの固有仕様を返す。

    引数: なし。返り値: 新仕様 (list[dict])。悪化・回復のどちらへ渡すかは呼出側で独立指定。
    """
    base = next(spec for spec in source.catalog() if spec['id'] == 'B06')
    output = []
    for scale in (.8, 1.2):
        changed = deepcopy(base)
        changed['id'] = f'B06__W{round(scale*100):03d}'
        changed['params']['window_seconds'] = base['params']['window_seconds'] * scale
        assert {k: v for k, v in changed['params'].items() if k != 'window_seconds'} == {
            k: v for k, v in base['params'].items() if k != 'window_seconds'}
        assert changed['params']['peer_delay_seconds'] == changed['params']['freshness_seconds'] == 60.
        output.append(changed)
    return output


def frozen_design() -> dict:
    """機能: 損益未読で入力の再利用範囲・数値変更・乱数契約を固定する。

    引数: なし。返り値: 固定仕様 (dict)。
    """
    value = dict(再利用入口=[dict(id=h, clock_scale=scale) for h in adapter.SIGNALS
        for scale in ((.8, 1., 1.2) if h == 'H019' else (1.,))],
        再利用条件=list(adapter.CONDITIONS), 新固有窓=specs(),
        診断対応=['悪化窓0.8・回復窓1', '悪化窓1.2・回復窓1', '悪化窓1・回復窓0.8', '悪化窓1・回復窓1.2'],
        公開元='source_rowはready配列行。rawseqはready.seq[source_row]。同時刻も配列行順を守る。',
        timer有効='公開後60秒内かつevents.validによる自市場窓品質。方向0は可、peer同意不要。',
        乱数='v37|seed|session|symbol|source rawseq のSHA256先頭8byte little bit0。0:+1/1:-1を元B06方向へ乗算。',
        乱数seed=list(range(64)), 乱数情報保持='元B06の非0機会と同一公開元での持続を保つ。市場情報なしとは呼ばない。',
        旧条件数値変更=False, 新損益読取=False, 売買再生=False, 現在保存物使用=False, API取得数=0)
    path = HERE/'partial_input_design.json'
    if path.exists(): assert read(path) == value
    else: save(path, value)
    return value


def reused_paths() -> list[Path]:
    """機能: 今回が直接参照する旧配列と証拠表だけを列挙する。

    引数: なし。返り値: 旧14入口・8方向・8証拠の30パス (list[Path])。
    """
    value = [adapter.entry_artifact(h, scale) for h in adapter.SIGNALS
        for scale in ((.8, 1., 1.2) if h == 'H019' else (1.,))]
    value += [adapter.condition_artifact(c, evidence=evidence) for c in adapter.CONDITIONS for evidence in (False, True)]
    assert len(value) == len(set(value)) == 30
    return value


def inherited_evidence() -> dict:
    """機能: 過去監査SHAを継承し、使う旧実体と原本78が不変か確認する。

    引数: なし。返り値: 継承した指紋と検査範囲 (dict)。旧信号の大規模再計算はしない。
    """
    fixed_path = adapter.PRIOR/'conditional_input_fixed.json'
    audit_path = adapter.PRIOR/'input_causality_before_pnl.json'
    fixed, audit = read(fixed_path), read(audit_path)
    assert fixed['全構造監査合格'] and audit['構造監査合格'] and audit['全監査完了']
    assert fixed['SHA256'][audit_path.relative_to(ROOT).as_posix()] == digest(audit_path)
    paths = reused_paths() + [HERE.parent/'wave_v23/inputs.pkl', HERE.parent/'wave_v23/features_depth.pkl',
        adapter.PRIOR/'deterioration_signals.py', adapter.PRIOR/'deterioration_design_fixed.json']
    hashes = {}
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        assert digest(path) == fixed['SHA256'][relative]
        hashes[relative] = fixed['SHA256'][relative]
    original = audit['原本78SHA256']
    assert len(original) == 78
    for relative, expected in original.items(): assert digest(ROOT/relative) == expected
    hashes.update({p.relative_to(ROOT).as_posix(): digest(p) for p in (fixed_path, audit_path)})
    return dict(旧入力監査継承=True, 旧大規模因果再検査=False, 再利用配列数=22, 再利用証拠表数=8,
        再利用元SHA256=hashes, 原本78SHA256=original)


def save_arrays(path: Path, values: dict) -> None:
    """機能: 新規配列を保存し、再実行時は全値同一を要求して上書きしない。

    引数: path (Path)、values (dict[str,ndarray])。返り値: なし (None)。
    """
    path.parent.mkdir(exist_ok=True)
    if path.exists():
        with np.load(path, allow_pickle=False) as previous:
            assert set(previous.files) == set(values)
            for key, value in values.items(): np.testing.assert_array_equal(previous[key], value)
    else:
        np.savez_compressed(path, **values)


def main() -> None:
    """機能: 再利用30実体と新窓2方向/2証拠を、売買なしで準備する。

    引数: なし。返り値: なし (None)。
    """
    socket.socket.connect = reject_network; socket.create_connection = reject_network
    frozen_design()
    inherited = inherited_evidence()
    inputs = pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    features = pickle.loads((HERE.parent/'wave_v23/features_depth.pkl').read_bytes())
    new_paths, records = [], []
    source.clear_cache()
    for spec in specs():
        result = source.build(spec, inputs, features)
        arrays, evidence = {}, {}
        for key, item in result.items():
            name = '|'.join(key)
            arrays.update({'direction::'+name: item['direction'], 'source_row::'+name: item['source_row'],
                'event_index::'+name: item['source_event_index']})
            evidence.update({name+'::'+column: item['events'][column].to_numpy() for column in item['events']})
            records.append(dict(id=spec['id'], session=key[0], symbol=key[1], 原本行数=len(item['direction']),
                証拠イベント数=len(item['events'])))
        for folder, values in (('deterioration', arrays), ('evidence', evidence)):
            path = HERE/folder/(spec['id']+'.npz'); save_arrays(path, values); new_paths.append(path)
    source.clear_cache()
    hashes = {**inherited['再利用元SHA256'], **{path.relative_to(ROOT).as_posix(): digest(path)
        for path in [Path(__file__), HERE/'partial_inputs.py', HERE/'partial_input_design.json', *new_paths]}}
    save(HERE/'partial_input_artifacts.json', dict(再利用=inherited, 新方向列数=2, 新証拠表数=2,
        新方向入力数=52, 新方向=records, SHA256=hashes, 新損益読取=False, 売買再生=False,
        現在保存物使用=False, API取得数=0))
    print('旧14入口・8条件を再利用、B06窓96/144秒の52入力だけ新規生成。', flush=True)


if __name__ == '__main__':
    main()
