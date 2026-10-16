"""金融実行を拒絶したまま、旧Dayと追加Nightの102入力互換を照合する。"""

import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys
import traceback

import numba
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import prepare as input_prepare

DATA = input_prepare.DATA
SESSION = input_prepare.SESSION
SYMBOLS = input_prepare.SYMBOLS
OLD_SESSION = '2026-10-12_Day'
CODE_NAMES = ('work/wave_v102/strategy.py', 'work/wave_v102/catalog.py',
              'work/wave_v94/strategy.py', 'work/wave_v93/strategy.py',
              'work/wave_v92/strategy.py', 'work/wave_v91/strategy.py',
              'work/wave_v90/strategy.py')


def array_hashes(value: object, prefix: str = '') -> dict:
    """
    機能: 準備前後で比較するため入力配列の型、形状及び内容指紋を取る。
    引数: value(object)は入力、prefix(str)は親欄名。
    返り値: dict[str,dict]は配列ごとの指紋。
    """
    if isinstance(value, np.ndarray):
        return {prefix: dict(dtype=str(value.dtype), shape=list(value.shape),
                             SHA256=hashlib.sha256(value.tobytes()).hexdigest())}
    if isinstance(value, dict):
        output = {}
        for name, child in value.items():
            output.update(array_hashes(child, prefix + '/' + str(name)))
        return output
    return {}


def slice_grid(value: object, count: int) -> object:
    """
    機能: 格子を基準とするネスト配列の未来部分を除く。
    引数: value(object)は格子欄、count(int)は過去格子数。
    返り値: objectは同じ欄構造の接頭部。
    """
    if isinstance(value, np.ndarray):
        return value[:count]
    if isinstance(value, dict):
        return {name: slice_grid(child, count) for name, child in value.items()}
    return value


def prefix_material(material: dict, cutoff: float) -> dict:
    """
    機能: 自・相手原板、独立LP、各格子及び候補を同じ代理時計で未来切断する。
    引数: material(dict)は追加一場素材、cutoff(float)は排他的切断秒。
    返り値: dictは現102のprepareへ渡す未来を含まない入力。
    """
    count = int(np.searchsorted(material['grids'][SESSION]['grid'], cutoff, side='left'))
    cuts = {key: int(np.searchsorted(value['time_s'], cutoff, side='left'))
            for key, value in material['prices'].items()}
    raw_cuts = {key: int(np.searchsorted(value['time_s'], cutoff, side='left'))
                for key, value in material['raw_last_records'].items()}
    trend = material['trend_prices']['I3'][SESSION]
    candidate_count = int(np.searchsorted(trend['candidate_grid'], cutoff, side='left'))
    output = dict(material)
    for name in ('prices', 'features', 'execution_lp_index'):
        output[name] = {key: input_prepare.clipped(value, cuts[key]) if isinstance(value, dict)
                        else value[:cuts[key]] for key, value in material[name].items()}
    output['raw_last_records'] = {key: input_prepare.clipped(value, raw_cuts[key])
                                 for key, value in material['raw_last_records'].items()}
    output['grids'] = {SESSION: slice_grid(material['grids'][SESSION], count)}
    output['entries'] = {SESSION: slice_grid(material['entries'][SESSION], count)}
    output['legacy'] = {key: {name: values[:candidate_count] if name != 'candidates' else
                            values[(values[:, 0] < candidate_count) & (values[:, 1] < cuts[key])]
                            for name, values in item.items()} for key, item in material['legacy'].items()}
    output['price_lanes'] = {}
    for lane, sessions in material['price_lanes'].items():
        value = sessions[SESSION]
        markets = {}
        for symbol, market in value['markets'].items():
            clipped_market = {name: slice_grid(content, count) for name, content in market.items()
                              if name != 'price_quality'}
            if 'price_quality' in market:
                clipped_market['price_quality'] = slice_grid(market['price_quality'], cuts[(SESSION, symbol)])
            markets[symbol] = clipped_market
        output['price_lanes'][lane] = {SESSION: dict(grid=value['grid'][:count], markets=markets)}
    output['trend_prices'] = {'I3': {SESSION: dict(grid=trend['grid'][:count],
        candidate_grid=trend['candidate_grid'][:candidate_count],
        candidate_positions=trend['candidate_positions'][:candidate_count],
        markets={symbol: slice_grid(value, count) for symbol, value in trend['markets'].items()})}}
    DATA.immutable(output)
    return output


def prefix_prepared(prepared: dict, material: dict, cutoff: float) -> dict:
    """
    機能: 全場のpreparedから、同じ原板行・格子・候補までの過去比較範囲を作る。
    引数: prepared/material(dict)、cutoff(float)は排他的切断秒。
    返り値: dictは切断入力から生成したpreparedの独立した比較対象。
    """
    count = int(np.searchsorted(material['grids'][SESSION]['grid'], cutoff, side='left'))
    candidate_count = int(np.searchsorted(material['trend_prices']['I3'][SESSION]['candidate_grid'], cutoff, side='left'))
    output = {}
    record_fields = ('mapped', 'quality', 'reset', 'event', 'execution_lp_index')
    for key, value in prepared.items():
        cut = int(np.searchsorted(value['record']['time_s'], cutoff, side='left'))
        signal = {name: content[:cut] if name in record_fields else content[:count]
                  if isinstance(content, np.ndarray) else content for name, content in value['signal'].items()}
        candidates = {name: content[:candidate_count] if name != 'candidates' else
                      content[(content[:, 0] < candidate_count) & (content[:, 1] < cut)]
                      for name, content in value['trend_candidate_state'].items()}
        output[key] = dict(record=input_prepare.clipped(value['record'], cut), signal=signal,
            trend_candidate_state=candidates,
            trend_lp_allowed={side: flags[:count] for side, flags in value['trend_lp_allowed'].items()},
            entry_support_base=value['entry_support_base'][:count], reference_open=value['reference_open'])
    return output


def old_one() -> tuple[dict, dict]:
    """
    機能: 不変cacheから旧Day一場だけを切り出し、再抽出や金融再生なしに互換見本を組む。
    引数: なし。
    返り値: tuple[dict,dict]は旧一場素材と読取資料の指紋。
    """
    paths = [ROOT / 'work/wave_v91/inputs/material_extra.pkl',
             ROOT / 'work/wave_v91/inputs/metadata.json',
             ROOT / 'work/wave_v94/prepared_r1/price_lanes.pkl',
             ROOT / 'work/wave_v94/prepared_r1/raw_last_records.pkl',
             ROOT / 'work/wave_v95/prepared/trend_prices.pkl']
    fingerprints = {str(path.relative_to(ROOT)): DATA.digest(path) for path in paths}
    old = input_prepare.read(paths[0])
    old['metadata'] = input_prepare.read(paths[1])
    keys = {(OLD_SESSION, symbol) for symbol in SYMBOLS}
    for name in ('prices', 'features', 'legacy'):
        assert set(old[name]) == keys
    saved = input_prepare.read(paths[2])
    lanes = {lane: {OLD_SESSION: sessions[OLD_SESSION]} for lane, sessions in saved.items()}
    del saved
    helper = input_prepare.module('互換確認用旧I0価格欄94の読取', ROOT / 'work/wave_v94/data_r1.py')
    lanes['I0'] = {OLD_SESSION: dict(grid=old['grids'][OLD_SESSION]['grid'], markets={symbol:
                    helper.old_price_channel(old['grids'][OLD_SESSION]['markets'][symbol], old['prices'][OLD_SESSION, symbol])
                    for symbol in SYMBOLS})}
    old['price_lanes'] = lanes
    saved = input_prepare.read(paths[3])
    old['raw_last_records'] = {key: saved[key] for key in keys}
    del saved
    saved = input_prepare.read(paths[4])
    old['trend_prices'] = {'I3': {OLD_SESSION: saved['I3'][OLD_SESSION]}}
    old['execution_lp_index'] = {key: saved['execution_lp_index'][key] for key in keys}
    del saved
    DATA.immutable(old)
    return old, fingerprints


def main() -> None:
    """
    機能: 禁止関数を塞いで現102入力の互換、旧欄形状及び未来不変を照合する。
    引数: なし。
    返り値: None。prepared作成だけを行い、売買、損益、選定及び通信を行わない。
    """
    socket.socket.connect = input_prepare.deny
    socket.create_connection = input_prepare.deny
    before = {name: DATA.digest(ROOT / name) for name in CODE_NAMES}
    before[str(Path(__file__).relative_to(ROOT))] = DATA.digest(Path(__file__))
    strategy = input_prepare.module('追加ナイト入力互換だけを確認する102', ROOT / 'work/wave_v102/strategy.py')
    catalog = input_prepare.module('追加ナイトの金融未実行定義だけを読む102', ROOT / 'work/wave_v102/catalog.py')
    # ----------------------------------------
    # 読取モジュールが保有する執行入口を塞ぎ、金融再生を実行できない状態にする。
    trapped = []
    for name, value in list(sys.modules.items()):
        filename = getattr(value, '__file__', None)
        if filename is None or not Path(filename).resolve().is_relative_to(ROOT / 'work'):
            continue
        for field in ('play', 'execute', 'backtest'):
            if hasattr(value, field):
                setattr(value, field, input_prepare.deny)
                trapped.append(name + '.' + field)
    config = catalog.catalog()[0]
    material = DATA.load_inputs()
    hashes = array_hashes(material)
    new = strategy.prepare(material, config)
    assert set(new) == {(SESSION, symbol) for symbol in SYMBOLS}
    assert hashes == array_hashes(material), 'preparedで入力を上書きしてはいけません'
    old, old_sources = old_one()
    old_hashes = array_hashes(old)
    old_prepared = strategy.prepare(old, config)
    assert old_hashes == array_hashes(old)
    schemas = []
    for symbol in SYMBOLS:
        arrays = input_prepare.schema_equal(old_prepared[OLD_SESSION, symbol], new[SESSION, symbol])
        schemas.append(dict(商品=symbol, 一致欄配列数=arrays,
                            旧prepared欄=list(old_prepared[OLD_SESSION, symbol]),
                            新prepared欄=list(new[SESSION, symbol]),
                            入口支持列数=new[SESSION, symbol]['entry_support_base'].shape[1],
                            損失反転源列数=new[SESSION, symbol]['signal']['loss_observations'].shape[1]))
    checks = []
    start = material['prices'][SESSION, 'TOPIX']['start']
    for offset in (900., 3600.):
        cutoff = start + offset
        prefix = prefix_material(material, cutoff)
        made = strategy.prepare(prefix, config)
        count = input_prepare.equal(made, prefix_prepared(new, material, cutoff))
        checks.append(dict(開始後秒=offset, 一致配列数=count, 金融再生=0))
    for name, expected in {**before, **old_sources}.items():
        assert DATA.digest(ROOT / name) == expected, ('入力互換確認中の変更', name)
    result = dict(全合格=True, 追加確認場=SESSION, 比較見本場=OLD_SESSION,
                  固定先頭config=config['id'], configの役割='既存prepareの共通入力互換確認だけ。金融条件の採用や選定ではない。',
                  prepared構造照合=schemas, preparedの実接頭照合=checks,
                  新material上書きなし=True, 旧material上書きなし=True,
                  金融入口を塞いだ関数=trapped, 旧入力cacheSHA256=old_sources,
                  互換確認コードSHA256=before,
                  完成追加入力SHA256={str((HERE / name).relative_to(ROOT)): DATA.digest(HERE / name)
                     for name in ('data.py', 'prepare.py', 'metadata.json', 'material_holdout.pkl',
                                  '入力準備前の素材登録.json', '追加入力の人工と原本及び実接頭検査.json')},
                  新場損益閲覧=0, 新場損益計算=0, 売買実行=0, 選定=0, API取得=0, 実注文=0)
    input_prepare.save('現102のprepareと旧Day欄及び未来不変の入力互換.json', result)
    print('現102のprepare互換、旧Day prepared構造、実接頭2時点及び原入力不変が一致。金融再生は0です', flush=True)


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        index = 1
        while (HERE / f'入力互換不合格_{index:05d}.json').exists():
            index += 1
        input_prepare.save(f'入力互換不合格_{index:05d}.json', dict(全合格=False,
             例外型=type(error).__name__, 内容=str(error), 診断=traceback.format_exc(),
             コードSHA256=DATA.digest(Path(__file__)), 新場損益閲覧=0, 新場損益計算=0,
             売買実行=0, 選定=0, API取得=0, 実注文=0))
        raise
