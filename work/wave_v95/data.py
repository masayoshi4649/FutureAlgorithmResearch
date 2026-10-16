"""全31既知場の旧執行素材と、新正常約定価格の15秒・300秒窓を別源で接続する。"""

import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SYMBOLS = ('TOPIX', 'NK225')


def module(name: str, path: Path) -> object:
    """
    機能: 同名モジュールの衝突を避け、保存入力の読取部品を接続する。
    引数: name(str)、path(Path)。
    返り値: objectは読取モジュール。旧入力を変更しない。
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


previous = module('独立価格と旧執行94の読取95', HERE.parent / 'wave_v94/data_r1.py')
digest = previous.digest


def read(path: Path) -> object:
    """
    機能: 保存された入力及び入力指紋だけを読む。
    引数: path(Path)は対象の位置。
    返り値: objectはJSON又はpickleの内容。
    """
    if path.suffix == '.pkl':
        with path.open('rb') as stream:
            return pickle.load(stream)
    return json.loads(path.read_text(encoding='utf-8'))


def load_inputs(verify: bool = True) -> dict:
    """
    機能: 旧BBO・Q・OFI・入口を維持し、独立LP窓と執行行対応を追加する。
    引数: verify(bool)は全保存指紋を照合するか。
    返り値: dictは旧material、trend_prices、raw_last_records、execution_lp_index。
    現在API、売買結果及び将来ラベルは読み込まない。
    """
    material = previous.load_inputs(verify=verify)
    folder = HERE / 'prepared'
    metadata_path = folder / 'metadata.json'
    metadata = read(metadata_path)
    assert metadata['全31既知'] and metadata['sessions'] == material['metadata']['sessions']
    if verify:
        for group in ('旧入力SHA256', '新コードSHA256', '新入力SHA256'):
            for relative, expected in metadata[group].items():
                assert digest(ROOT / relative) == expected, relative
    raw_path = HERE.parent / 'wave_v94/prepared_r1/raw_last_records.pkl'
    material['raw_last_records'] = read(raw_path)
    saved = read(folder / 'trend_prices.pkl')
    material['trend_prices'] = {'I3': saved['I3']}
    material['execution_lp_index'] = saved['execution_lp_index']
    assert set(material['raw_last_records']) == set(material['prices'])
    assert len(material['execution_lp_index']) == 62
    for session, values in material['trend_prices']['I3'].items():
        np.testing.assert_array_equal(values['grid'], material['grids'][session]['grid'])
        np.testing.assert_array_equal(values['candidate_grid'], values['grid'][values['candidate_positions']])
        for symbol in SYMBOLS:
            key = session, symbol
            record = material['prices'][key]
            raw = material['raw_last_records'][key]
            indexes = material['execution_lp_index'][key]
            np.testing.assert_array_equal(raw['seq'][indexes], record['seq'])
            np.testing.assert_array_equal(raw['time_s'][indexes], record['time_s'])
            np.testing.assert_array_equal(raw['last'][indexes], record['price'])
            assert values['candidate_grid'].size == material['legacy'][key]['states'].size
    material['paths'] = [*material['paths'], raw_path, metadata_path, folder / 'trend_prices.pkl',
                         Path(__file__), HERE / 'prepare_prices.py']
    material['trend_metadata'] = metadata
    previous.immutable(material)
    return material
