"""既知25場の気配入力を統合し、最終約定値を持たない共通キャッシュを作る。"""

import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
INPUT_KEYS = ('seq', 'time_s', 'start', 'limit', 'symbol', 'session', 'tick')
QUOTE_KEYS = ('seq', 'time_s', 'bid', 'ask', 'mid')


def digest(path: Path) -> str:
    """機能: キャッシュの内容を分割読込して SHA256 を作る。

    引数: path(Path) は既存ファイル。
    返り値: SHA256 文字列(str)。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(4 * 1024 * 1024):
            result.update(block)
    return result.hexdigest()


def main() -> None:
    """機能: 既知23場と既知追加2場を結合し、時計と気配の一致を照合する。

    引数: なし。
    返り値: なし(None)。売買損益・原本最終価格・新しいセッションは使用しない。
    """
    inputs, quotes, sources = {}, {}, {}
    for directory in (ROOT / 'work/wave_v59', ROOT / 'work/wave_v59/holdout'):
        source_inputs = pickle.loads((directory / 'inputs.pkl').read_bytes())
        source_quotes = pickle.loads((directory / 'quotes.pkl').read_bytes())
        assert not set(inputs).intersection(source_inputs)
        assert set(source_inputs) == set(source_quotes)
        inputs.update({key: {name: value[name] for name in INPUT_KEYS} for key, value in source_inputs.items()})
        quotes.update({key: {name: value[name] for name in QUOTE_KEYS} for key, value in source_quotes.items()})
        for name in ('inputs.pkl', 'quotes.pkl'):
            sources[str((directory / name).relative_to(ROOT))] = digest(directory / name)
    assert len(inputs) == 50 and len(set(key[0] for key in inputs)) == 25
    details = []
    for key, ready in inputs.items():
        quote = quotes[key]
        assert 'last' not in ready and 'last' not in quote
        np.testing.assert_array_equal(ready['seq'], quote['seq'])
        np.testing.assert_array_equal(ready['time_s'], quote['time_s'])
        assert np.all(np.diff(ready['seq']) > 0) and np.all(np.diff(ready['time_s']) >= 0)
        assert np.all(quote['bid'] > 0) and np.all(quote['ask'] > quote['bid'])
        np.testing.assert_array_equal(quote['mid'], (quote['bid'] + quote['ask']) / 2.)
        assert ready['time_s'][0] >= ready['start'] and ready['time_s'][-1] > ready['limit']
        details.append({'セッション': key[0], '銘柄': key[1], '有効行数': len(ready['seq']),
                        '場開始': ready['start'], '返済判断期限': ready['limit'],
                        '最終観測時計': float(ready['time_s'][-1])})
    WORK.mkdir(parents=True, exist_ok=True)
    for name, value in (('inputs.pkl', inputs), ('quotes.pkl', quotes)):
        (WORK / name).write_bytes(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL))
    evidence = {'合格': True, '既知セッション数': 25, '口座数': 50,
                '有効行数': sum(len(x['seq']) for x in inputs.values()), '未見検証ではない': True,
                '最終約定値不採用': True, '入力許可キー': INPUT_KEYS, '気配許可キー': QUOTE_KEYS,
                '場内返済判断時刻': 'Day 15:35 / Night 翌05:50。観測は通常各5分後まで保存。',
                '入力元SHA256': sources, '口座別': details}
    (WORK / '共通入力照合.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in evidence.items() if k not in ('口座別', '入力元SHA256')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
