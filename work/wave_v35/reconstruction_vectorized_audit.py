"""独立会計の極値走査変更について、人工値・破損拒否・旧全値同一を確認する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
import sys
import time
import urllib.request

import numpy as np

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import conditional_accounting_audit as audit
import accounting_reconstruction_vectorized as accelerated

ORIGINAL = audit.previous.reconstruct


def reject_network(*args: object, **kwargs: object) -> None:
    """機能: 合成検査中のネットワーク通信を拒否する。

    引数: args/kwargs (object) は任意の呼出引数。返り値: なし (None)、必ず例外。
    """
    raise AssertionError('通信禁止の人工会計比較')


def compare_reconstruction(ready: dict, result: dict, symbol: str,
                           closed: bool = True) -> tuple[dict, dict]:
    """機能: 同一の台帳・曲線を旧新版へ渡し、全返り値を完全照合する。

    引数: ready/result (dict)、symbol (str)、closed (bool)。
    返り値: 高速版の集計・全時系列 (tuple[dict,dict])。実監査への接続は呼出側が管理する。
    """
    old_summary, old_series = ORIGINAL(ready, result, symbol, closed)
    summary, series = accelerated.reconstruct(ready, result, symbol, closed)
    assert summary == old_summary, '全集計値の厳密一致'
    assert set(series) == set(old_series)
    for name in series:
        np.testing.assert_array_equal(series[name], old_series[name], err_msg='全行完全一致/' + name)
    return summary, series


def rejected_same(ready: dict, result: dict, symbol: str) -> None:
    """機能: 破損した同じ入力を旧新版がともに拒否することを確認する。

    引数: ready/result (dict)、symbol (str)。返り値: なし (None)。
    """
    errors = []
    for method in (ORIGINAL, accelerated.reconstruct):
        try:
            method(ready, result, symbol)
        except (AssertionError, ValueError, IndexError) as error:
            errors.append(type(error).__name__)
        else:
            errors.append('通過')
    assert errors[0] == errors[1] and errors[0] != '通過', errors


def artificial() -> dict:
    """機能: 両銘柄・両方向・部分返済・飛値・同時刻・未返済接頭辞を同一照合する。

    引数: なし。返り値: 合成検査記録 (dict)。実相場の新規損益は計算しない。
    """
    sequence = np.tile(np.array([100., 96., 98., 104., 111., 118., 120., 110., 103., 90., 94., 99.]), 20)
    n = len(sequence) + 2
    ready = dict(time_s=np.r_[np.floor(np.arange(n - 2) / 2.) * 10., 1300., 1301.], seq=np.arange(n),
        last=np.r_[sequence, sequence[-1], sequence[-1]], atr=np.full(n, 4.), tick=1., start=-1200.,
        limit=1300., us_open=np.inf, symbol='TOPIX', session='合成Day')
    entry = np.where(np.arange(n) % 51 < 25, 1, -1).astype(np.int8)
    direction = np.where(np.arange(n) % 3 == 0, 0, -entry).astype(np.int8)
    source = np.where(direction != 0, np.maximum(np.arange(n) - 1, 0), -1).astype(np.int64)
    tracking = np.resize(np.array([np.nan, 1., 2., 8., np.inf, -1., 4.]), n)
    manager = audit.read(HERE / '探索条件の固定.json')['manager']
    count = 0
    sample = None
    for symbol in ('TOPIX', 'NK225'):
        for reflected in (False, True):
            current = dict(ready, symbol=symbol, last=200. - ready['last'] if reflected else ready['last'])
            state, adverse = (-entry, -direction) if reflected else (entry, direction)
            config = audit.MANAGERS.make_config(manager, symbol, current)
            for mode in (0, 1, 2):
                for observed in (False, True):
                    spec = dict(width_mode=mode, observed_fill=observed)
                    result = audit.helper.replay(current, state, adverse, source, config, spec, tracking)
                    for value in (result, result['shadow']):
                        compare_reconstruction(current, value, symbol)
                        count += 1
                    if sample is None and len(result['trades']) > 0:
                        sample = current, result, config
                    # ----------------------------------------
                    # 完全返済を強制しない接頭辞も、同じ未返済状態として旧新版へ渡す。
                    cut = 80
                    shorter = audit.previous.clipped(current, cut)
                    partial = audit.helper.replay(shorter, state[:cut], adverse[:cut], source[:cut],
                        config, spec, tracking[:cut])
                    compare_reconstruction(shorter, partial, symbol, closed=False)
                    count += 1
            neutral = np.zeros(n, np.int8)
            flat = audit.helper.replay(current, neutral, neutral, np.full(n, -1, np.int64), config,
                                       dict(width_mode=0, observed_fill=False), tracking)
            assert not len(flat['orders'])
            compare_reconstruction(current, flat, symbol)
            count += 1
    assert sample is not None
    current, result, config = sample
    broken = []
    invalid_price = dict(current, last=current['last'].copy())
    invalid_price['last'][3] = np.nan
    rejected_same(invalid_price, result, current['symbol']); broken.append('原本価格NaN')
    invalid_price = dict(current, last=current['last'].copy())
    invalid_price['last'][3] = 0.
    rejected_same(invalid_price, result, current['symbol']); broken.append('原本価格ゼロ')
    invalid_time = dict(current, time_s=current['time_s'].copy())
    invalid_time['time_s'][3] = -100.
    rejected_same(invalid_time, result, current['symbol']); broken.append('原本時刻逆転')
    # ----------------------------------------
    # 入力列・所有元・同一行約定・残玉・損失額・全行時価などを破壊し省略がないことを確認する。
    mutations = [('orders', 0, 1, float(result['orders'][0, 0])),
                 ('orders', 0, 4, 11.), ('orders', 0, 5, np.inf),
                 ('trades', 0, 1, 100000.), ('trades', 0, 3, 100.),
                 ('trades', 0, 10, float(result['trades'][0, 10] + 1.)),
                 ('curve', 50, 0, float(result['curve'][50, 0] + 1.)),
                 ('curve', 50, 2, float(result['curve'][50, 2] + 1.)),
                 ('cycles', 0, 3, float(result['cycles'][0, 3] + 1.)),
                 ('cycles', 0, 6, float(result['cycles'][0, 6] + 1.))]
    for key, row, column, value in mutations:
        changed = dict(result, **{key: result[key].copy()})
        changed[key][row, column] = value
        rejected_same(current, changed, current['symbol'])
        broken.append(f'{key}/{row}/{column}')
    changed = dict(result, stats=result['stats'].copy()); changed['stats'][2] += 1.
    rejected_same(current, changed, current['symbol']); broken.append('stats最大保有')
    return dict(人工完全一致数=count, 破損同拒否数=len(broken), 破損検査=broken,
                全集計値完全一致=True, 全現金保有時価実現列完全一致=True,
                未返済接頭辞検査=True, 無約定検査=True, 新実相場再生=False)


def main() -> None:
    """機能: 合成旧新版同一性とファイル不変を保存する。

    引数: なし。返り値: なし (None)。旧ファイル・原本・現在データを変更しない。
    """
    socket.create_connection = reject_network
    socket.socket.connect = reject_network
    urllib.request.urlopen = reject_network
    original_path = HERE.parent / 'wave_v29' / 'selected_accounting_audit.py'
    original_hash = hashlib.sha256(original_path.read_bytes()).hexdigest()
    started = time.perf_counter()
    result = artificial()
    assert hashlib.sha256(original_path.read_bytes()).hexdigest() == original_hash
    result.update(全合格=True, 所要秒=time.perf_counter() - started, 旧独立会計SHA256=original_hash,
        新独立会計SHA256=hashlib.sha256(Path(accelerated.__file__).read_bytes()).hexdigest(),
        監査実装SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        旧コード不変=True, API取得数=0, 現在保存物読取=False,
        実績15条件検査='signals の全監査比較で実施する。ここは人工・破損検査のみ。')
    (HERE / 'reconstruction_vectorized_audit.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('全合格', '人工完全一致数', '破損同拒否数', '所要秒')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
