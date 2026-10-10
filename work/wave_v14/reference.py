"""前回の凍結済み再生器を変更せず、今回の既知入力へ接続する。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import pickle
import sys


OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
OLD = ROOT/'work/wave_v13'
sys.path.insert(0, str(OLD))
_spec = importlib.util.spec_from_file_location('v14_previous_research', OLD/'research.py')
previous = importlib.util.module_from_spec(_spec)
sys.modules['v14_previous_research'] = previous
_spec.loader.exec_module(previous)
import exact_engine as engine
sys.path.pop(0)
previous.OUT = OUT
TRAIN = [*previous.TRAIN, '2026-09-24_Day']
KNOWN_NIGHT = '2026-09-24_Night'
KNOWN_CUTOFF = '2026-09-24T23:19:00+09:00'
SYMBOLS = ['NK225', 'TOPIX']


def save(path: Path, value: object) -> None:
    """機能: 非有限値を明示して日本語の結果を保存する。

    引数: path (Path)、value (object)。返り値: None。
    """
    previous.save(path, value)


def load_inputs() -> dict:
    """機能: 既に閲覧済みの７完全セッションと前回ナイト前半を読み込む。

    引数: なし。返り値: (セッション,銘柄)をキーとする準備済み入力 (dict)。
    原本・旧コード・旧結果の書換えや、現在データの通信は行わない。
    """
    target = OUT/'既知入力.pkl'
    if target.exists():
        with target.open('rb') as stream:
            return pickle.load(stream)
    with (OLD/'学習入力.pkl').open('rb') as stream:
        prepared = pickle.load(stream)
    prepared.update(previous.build_inputs(['2026-09-24_Day'], allow_holdout=True))
    prepared.update(previous.build_inputs([KNOWN_NIGHT], roots={KNOWN_NIGHT:(OLD/'live', OLD/'live/features')}))
    with target.open('wb') as stream:
        pickle.dump(prepared, stream, protocol=pickle.HIGHEST_PROTOCOL)
    save(OUT/'既知入力の用途.json', dict(探索=TRAIN, 診断のみ=KNOWN_NIGHT,
         既知部分の締切=KNOWN_CUTOFF, 注意='ナイト前半は前回閲覧済み。今回の未知検証には数えない。',
         入力=[dict(セッション=s, 銘柄=k, 行数=len(v['seq']), 最初=float(v['time_s'][0]),
                    最後=float(v['time_s'][-1])) for (s,k),v in prepared.items()]))
    return prepared


if __name__ == '__main__':
    prepared = load_inputs()
    print(json.dumps(dict(セル数=len(prepared), 行数=sum(len(v['seq']) for v in prepared.values()),
                          現在通信=0), ensure_ascii=False))
