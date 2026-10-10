"""追加六口座を途中で打ち切り、過去ティック特徴の不変性を検査する。"""

from concurrent.futures import ProcessPoolExecutor
import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
EXTRACTOR = HERE.parents[1] / 'wave_v57' / 'features.py'


def check_one(args: tuple) -> tuple:
    """機能: 原本の前半だけから特徴とイベントを独立再生成する。

    引数: args(tuple:口座キー、価格入力dict、切断長int)。返り値: キー、短い特徴、イベント(tuple)。
    """
    key, ready, size = args
    spec = importlib.util.spec_from_file_location('tick69_prefix_extract', EXTRACTOR)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    features, events, _ = module.extract_one(key, ready, max_valid_rows=size)
    return key, features, events


def main() -> None:
    """機能: 追加六口座の前半再抽出が全件抽出の前半と一致するか検査する。

    引数: なし。返り値: なし(None)。売買結果と現在APIは参照しない。
    """
    with (HERE / 'inputs.pkl').open('rb') as stream:
        inputs = pickle.load(stream)
    with (HERE / 'features.pkl').open('rb') as stream:
        full = pickle.load(stream)
    with (HERE / 'events.pkl').open('rb') as stream:
        events = pickle.load(stream)
    manifest = json.loads((HERE / '入力と特徴の照合.json').read_text(encoding='utf8'))
    keys = [(row['セッション'], row['銘柄']) for row in manifest['口座別'] if row['新規抽出']]
    rows = []
    args = [(key, inputs[key], len(inputs[key]['seq']) // 2) for key in keys]
    with ProcessPoolExecutor(max_workers=4) as pool:
        for key, partial, ev in pool.map(check_one, args):
            size = len(partial['seq'])
            for name, data in partial.items():
                np.testing.assert_array_equal(data, full[key][name][:size])
            np.testing.assert_array_equal(ev, events[key][events[key]['i'] < size])
            rows.append(dict(セッション=key[0], 銘柄=key[1], 切断有効行数=size,
                過去全特徴一致=True, 過去補充完了一致=True, 補充完了数=len(ev)))
    out = dict(合格=True, 対象口座数=len(rows), 将来行を削除して再抽出=True,
        原本書換数=0, 現在API取得数=0, 売買結果参照=False, 口座別=rows)
    (HERE / '追加特徴の途中切断検査.json').write_text(
        json.dumps(out, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf8')
    print(f'追加{len(rows)}口座の前半全特徴・イベントが一致', flush=True)


if __name__ == '__main__':
    main()
