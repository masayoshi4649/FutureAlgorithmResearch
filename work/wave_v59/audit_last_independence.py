"""最終約定値だけを極端に変更しても、中値由来の特徴と入口が変わらないかを監査する。"""

import hashlib
import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd

import features
import signals


HERE = Path(__file__).resolve().parent


def main() -> None:
    """機能: 旧46口座の last を改変し、表示2列以外の特徴と全入口の不変性を調べる。

    引数: なし。
    返り値: なし(None)。原本、確定キャッシュ、売買結果、新2場には変更や参照を行わない。
    """
    inputs = pickle.loads((HERE / 'inputs.pkl').read_bytes())
    quotes = pickle.loads((HERE / 'quotes.pkl').read_bytes())
    saved = pickle.loads((HERE / 'features.pkl').read_bytes())
    candidates = pickle.loads((HERE / '入口候補.pkl').read_bytes())
    assert len(inputs) == 46
    records = []
    for key, ready in inputs.items():
        altered = dict(ready)
        altered['last'] = ready['last'] * 1000. + np.arange(len(ready['last'])) * ready['tick']
        for setting in features.SETTINGS:
            frame = features.build_features(altered, quotes[key], setting)
            original = saved[key][setting['id']]
            display_columns = ['last', 'session_open']
            pd.testing.assert_frame_equal(frame.drop(columns=display_columns), original.drop(columns=display_columns), check_exact=True)
            assert not np.array_equal(frame['last'], original['last'])
            assert not np.array_equal(frame['session_open'], original['session_open'])
            found = signals.candidates(frame, float(quotes[key]['mid'][0]), float(ready['tick']))
            for family, rows in found.items():
                np.testing.assert_array_equal(rows, candidates[key][setting['id']][family])
            records.append({'セッション': key[0], '銘柄': key[1], '設定': setting['id'],
                            '監査表示2列の変化': True, 'その他全特徴一致': True, '全6入口一致': True})
    result = {'合格': True, '口座数': 46, '特徴比較数': len(records), '入口比較数': len(records) * 6,
              '改変': 'last = 元last×1000 + 原本有効行位置×tick。全行を変更。',
              '変化を許す表示列': ['last', 'session_open'], 'その他特徴と入口は完全一致': True,
              '損益参照': False, '新2場参照': False,
              '対象コードSHA256': {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                              for name in ('features.py', 'signals.py')}, '詳細': records}
    (HERE / '最終約定値への非依存監査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != '詳細'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
