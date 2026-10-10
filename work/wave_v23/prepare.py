"""既知13セッションの固定原本入力と板特徴を、新規探索専用に準備する。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys

import pandas as pd


OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
sys.dont_write_bytecode = True


def module(path: Path, name: str):
    """機能: 旧コードを変更せず固有名で読み込む。

    引数: path (Path)、name (str)。返り値: モジュール (module)。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def digest(path: Path) -> str:
    """機能: 原本内容のSHA256を確認する。

    引数: path (Path)。返り値: ハッシュ (str)。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1048576):
            value.update(chunk)
    return value.hexdigest()


def main() -> None:
    """機能: 原本照合後に26入力と解放済み板特徴を保存する。

    引数: なし。返り値: なし (None)。現在APIは使用しない。
    """
    OUT.mkdir(exist_ok=True)
    ledger = json.loads((ROOT / 'M3_逆_A00_360分版/セッション損益.json').read_text(encoding='utf-8'))
    expected = {}
    for row in ledger['records']:
        expected.update(row['source_hashes'])
    for path, expected_hash in expected.items():
        assert digest(ROOT / path) == expected_hash, path
    inputs, features = {}, {}
    for stage in ['development', 'holdout']:
        inputs.update(pickle.loads((ROOT / 'work/wave_v16' / f'入力_{stage}.pkl').read_bytes()))
    for (session, symbol), ready in inputs.items():
        folder = 'wave_v16' if session >= '2026-09-24_Night' else 'wave_v13'
        features[(session, symbol)] = pd.read_csv(ROOT / 'work' / folder / 'features' / f'{symbol}_{session}.csv')
    reference = module(ROOT / 'work/wave_v16/reference.py', 'fresh_reference')
    reference.previous.OUT = OUT
    for session in ['2026-09-28_Day', '2026-09-28_Night', '2026-09-29_Day']:
        feature_root = ROOT / 'work/wave_v21' / session / 'features'
        if not feature_root.exists():
            feature_root = ROOT / 'work/wave_v20/features'
        inputs.update(reference.previous.build_inputs([session], allow_holdout=True, roots={session: (ROOT, feature_root)}))
        for symbol in ['TOPIX', 'NK225']:
            features[(session, symbol)] = pd.read_csv(feature_root / f'{symbol}_{session}.csv')
    assert len(inputs) == len(features) == 26
    for key, ready in inputs.items():
        assert ready['time_s'][-1] > ready['limit']
        frame = features[key]
        assert (frame.source_last_seq < frame.seq).all()
        assert (frame.source_time_s < frame.time_s).all()
    for name, value in [('inputs.pkl', inputs), ('features.pkl', features)]:
        with (OUT / name).open('wb') as stream:
            pickle.dump(value, stream, pickle.HIGHEST_PROTOCOL)
    audit = dict(全期間既読=True, セッション数=13, 銘柄別入力数=len(inputs), 原本SHA256=expected,
                 入力行数={f'{s}/{k}': len(v['time_s']) for (s, k), v in inputs.items()}, 現在API取得数=0)
    (OUT / '入力確認.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print('13セッション・26入力を準備しました。', flush=True)


if __name__ == '__main__':
    main()
