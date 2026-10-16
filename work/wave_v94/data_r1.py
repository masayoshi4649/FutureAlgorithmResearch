"""旧執行素材を変更せず、四つの独立価格チャンネルを接続する第1修正版。"""

import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAME = '不変の全31素材93の読取94'
spec = importlib.util.spec_from_file_location(NAME, HERE.parent / 'wave_v93/data.py')
previous = importlib.util.module_from_spec(spec)
sys.modules[NAME] = previous
spec.loader.exec_module(previous)
digest = previous.digest


def immutable(value: object) -> None:
    """
    機能: 配列を読み取り専用にして入力の上書きを拒絶する。
    引数: value(object)。配列、辞書又は列。
    返り値: None。
    """
    if isinstance(value, np.ndarray):
        value.flags.writeable = False
    elif isinstance(value, dict):
        for child in value.values():
            immutable(child)
    elif isinstance(value, (tuple, list)):
        for child in value:
            immutable(child)


def old_price_channel(market: dict, record: dict) -> dict:
    """
    機能: 旧価格欄を独立した名前空間で公開し、元の執行・板素材は保持する。
    引数: market(dict)は旧格子特徴、record(dict)は旧原板執行系列。
    返り値: dict。I0の中値価格current/windows/ranges。
    """
    current = market['current']
    source = current['index']
    safe = np.maximum(source, 0)
    raw_seq = record['seq'][safe].copy()
    raw_seq[source < 0] = -1
    clock = record['time_s'][safe].copy()
    clock[source < 0] = np.nan
    price = dict(index=source, raw_seq=raw_seq, time_s=clock, value=current['mid'],
                 mid=current['mid'], last=current['last'], valid=current['valid'],
                 age=current['age'], actual_age=current['actual_age'])
    return dict(source_kind='旧完全板資格を結合した中値価格', current=price,
                windows=market['windows'], ranges=market['ranges'])


def load_inputs(verify: bool = True) -> dict:
    """
    機能: 旧31場の執行素材と、別保存した価格四系統を指紋確認付きで接続する。
    引数: verify(bool)。保存指紋の一致を確認するか。
    返り値: dict。旧material欄及びprice_lanes。損益・将来ラベルは含まない。
    """
    material = previous.load_inputs(verify=verify)
    folder = HERE / 'prepared_r1'
    metadata_path = folder / 'metadata.json'
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    assert metadata['全31既知'] and metadata['新未見確認場数'] == 0
    assert metadata['sessions'] == material['metadata']['sessions'] and metadata['口座数'] == 62
    if verify:
        for group in ('旧入力SHA256', '新コードSHA256', '新入力SHA256'):
            for relative, expected in metadata[group].items():
                assert digest(ROOT / relative) == expected, (group, relative)
    with (folder / 'price_lanes.pkl').open('rb') as stream:
        lanes = pickle.load(stream)
    assert set(lanes) == {'I1', 'I2', 'I3'}
    lanes['I0'] = {session: dict(grid=values['grid'], markets={symbol:
        old_price_channel(values['markets'][symbol], material['prices'][session, symbol])
        for symbol in ('TOPIX', 'NK225')}) for session, values in material['grids'].items()}
    for profile in lanes.values():
        assert set(profile) == set(material['grids'])
        for session, values in profile.items():
            np.testing.assert_array_equal(values['grid'], material['grids'][session]['grid'])
            assert set(values['markets']) == {'TOPIX', 'NK225'}
            for market in values['markets'].values():
                current = market['current']
                valid = current['valid']
                assert (current['time_s'][valid] < values['grid'][valid] - 1.).all()
                assert (current['raw_seq'][valid] >= 0).all()
    material['price_lanes'] = lanes
    material['price_metadata'] = metadata
    material['paths'] = [*material['paths'], metadata_path, folder / 'price_lanes.pkl',
                         folder / 'raw_last_records.pkl', Path(__file__),
                         HERE / 'prepare_inputs_r1.py', HERE / '結果前の設計案_r1.json',
                         HERE / 'inputs_r1/core.py', HERE / 'inputs_r1/last_price.py', HERE / 'inputs_r1/strict_board.py',
                         HERE / 'inputs_r1/価格資格と原LPの人工正負及び未来不変.json',
                         HERE / 'inputs_r1/価格資格と原LPの分離設計.json']
    immutable(material)
    return material
