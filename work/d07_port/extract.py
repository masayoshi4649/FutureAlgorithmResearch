"""保存D07約定と既存全原行特徴を、再探索せず移植検査へ分離する。"""

import gzip
import hashlib
import json
import pickle
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SOURCE = ROOT / 'work/sessiontrader143_port_20261025/fixtures_all'
TARGET = HERE / 'fixtures'


def digest(path):
    """内容指紋を求める。

    引数: path(Path)は読取資料。
    返り値: strはSHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    """保存行列と保存約定を照合し、期待値だけ別ファイルへ抽出する。

    引数: なし。
    返り値: None。売買関数を呼ばず、金融再生はしない。
    """
    TARGET.mkdir(parents=True, exist_ok=True)
    cases = []
    for source in sorted((ROOT/'work/research145_roles/orders').glob('*.npz')):
        scene = source.stem
        with (ROOT/f'work/research145_engine/cache/{scene}.pkl').open('rb') as stream:
            _, data, _, _, _ = pickle.load(stream)
        r, q = data['ready'], data['quotes']
        spec = json.loads(gzip.decompress((SOURCE/f'{scene}_input.json.gz').read_bytes()))
        matrices = spec['matrices']['NK225']
        raw_market = np.frombuffer(gzip.decompress((SOURCE/matrices['market']['file']).read_bytes()), '<f8').reshape(-1, 7)
        features = np.frombuffer(gzip.decompress((SOURCE/matrices['features']['file']).read_bytes()), '<f8').reshape(-1, 30)
        history = np.frombuffer(gzip.decompress((SOURCE/matrices['history']['file']).read_bytes()), '<f8').reshape(-1, 15)
        current = np.column_stack((r['time_s'], r['last'], q['bid'], q['ask'], q['quote_valid'], r['atr'], r['seq']))
        np.testing.assert_array_equal(raw_market, current, err_msg=scene+'原行')
        np.testing.assert_array_equal(features, data['features'][:,:30], err_msg=scene+'特徴')
        np.testing.assert_array_equal(history[:,1], data['features'][:,30], err_msg=scene+'MA20')
        with np.load(source) as archive:
            orders = archive['D07']
        if scene.endswith('_Day'):
            addon_path = ROOT/f'work/research145_engine/measurement/NK225_{scene}.npz'
            addon_key = 'A_V05'
        else:
            addon_path = ROOT/f'work/research145_roles/new_addon/{scene}.npz'
            addon_key = 'A_V16'
        with np.load(addon_path) as archive:
            addon = archive[addon_key]
        payload = {'session':scene, 'orders':orders.tolist(), 'addon':addon.tolist(),
            'source_sha256':digest(source), 'addon_sha256':digest(addon_path),
            '説明':'期待約定は判定入力へ渡さない。判断と約定時刻、数量、担当を照合する。'}
        path = TARGET/f'{scene}_expected.json.gz'
        path.write_bytes(gzip.compress(json.dumps(payload, ensure_ascii=False,allow_nan=False).encode('utf8'),mtime=0))
        cases.append({'session':scene, 'expected':path.name, 'rows':len(raw_market),
            'orders':len(orders), 'source_sha256':digest(source),
            'input_sha256':digest(SOURCE/f'{scene}_input.json.gz'),
            'legacy_sha256':digest(SOURCE/f'legacy/{scene}_legacy.json.gz')})
        print(scene, len(raw_market), len(orders), flush=True)
    result = {'source_directory':'../../sessiontrader143_port_20261025/fixtures_all',
        'cases':cases, 'purpose':'D07の独立Go移植照合。既存保存結果を新しい優位性証拠に数えない。',
        'new_financial_replays':0}
    (TARGET/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')


if __name__ == '__main__':
    main()
