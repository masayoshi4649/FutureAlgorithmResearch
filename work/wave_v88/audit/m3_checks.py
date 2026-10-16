"""M3の観測約定への変更が初回建値と出口へ一貫して及ぶことを人工確認する。"""

import json
import os
from pathlib import Path
import numpy as np
import execution_checks as common


def main():
    """
    機能: 売買反射・両商品で入口飛越しと停止・追尾飛越しを検査する。
    引数: なし。
    返り値: None。新実データの収支は計算しない。
    """
    import numba
    os.environ['NUMBA_CACHE_DIR'] = str(common.HERE / 'cache_m3')
    numba.config.CACHE_DIR = str(common.HERE / 'cache_m3')
    current = common.module('監査88M3観測', common.WORK / 'm3_engine.py')
    old = common.module('監査88M3旧指定', common.ROOT / 'work/wave_v19/engine.py')
    config = json.loads((common.ROOT / 'M3_逆_A00_360分版/固定条件.json').read_text(encoding='utf-8'))['一枚でのエンジン設定']
    files = [common.WORK / 'm3_engine.py', common.ROOT / 'work/wave_v19/engine.py', Path(__file__)]
    hashes = {str(p.relative_to(common.ROOT)): common.hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    records = []
    for symbol in ('TOPIX', 'NK225'):
        for side in (-1, 1):
            for name, path in (('観測建値からの停止', [100, 105, 102, 100, 100, 90, 90, 90]),
                               ('入口飛越しと追尾線飛越し', [100, 105, 110, 109, 106, 104, 100, 100])):
                factor = 1 if symbol == 'TOPIX' else 20
                prices = np.asarray(path, float)
                if side < 0:
                    prices = 200 - prices
                prices *= factor
                ready = dict(last=prices, time_s=np.arange(len(prices), dtype=float) + 1200,
                    atr=np.full(len(prices), 4. * factor), tick=.5 * factor, start=0., limit=10000., us_open=20000.)
                signal = np.full(len(prices), side, np.int8)
                observed = current.run(ready, signal, config, detail=True, observed_fill=True)
                specified = current.run(ready, signal, config, detail=True, observed_fill=False)
                legacy = old.run(ready, signal, config, detail=True)
                for key in legacy:
                    np.testing.assert_array_equal(specified[key], legacy[key])
                assert observed['orders'][0, 0] == 1 and observed['orders'][0, 5] == prices[1]
                for order in observed['orders']:
                    assert order[1] < order[0] and order[5] == prices[int(order[0])]
                if name == '観測建値からの停止':
                    assert observed['orders'][1, 0] == 3 and observed['orders'][1, 6] == 1
                    assert specified['orders'][1, 0] == 5
                else:
                    assert observed['orders'][1, 0] == 6 and observed['orders'][1, 6] == 2
                    assert observed['orders'][1, 5] != specified['orders'][1, 5]
                for count in range(1, len(prices)):
                    reduced = dict(ready, last=prices[:count], time_s=ready['time_s'][:count], atr=ready['atr'][:count])
                    prefix = current.run(reduced, signal[:count], config, detail=True, observed_fill=True)
                    for key, column in (('orders', 0), ('trades', 7), ('cycles', 2)):
                        np.testing.assert_array_equal(prefix[key], observed[key][observed[key][:, column] < count])
                    np.testing.assert_array_equal(prefix['curve'], observed['curve'][:count])
                records.append(dict(商品=symbol, 方向=side, 検査=name, 新規行=int(observed['orders'][0, 0]),
                    観測新規価格=float(observed['orders'][0, 5]), 返済行=int(observed['orders'][1, 0]),
                    観測返済価格=float(observed['orders'][1, 5]), 指定モデル旧完全一致=True))
    assert hashes == {str(p.relative_to(common.ROOT)): common.hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    common.save('M3観測建値と価格飛越しの人工検査.json', dict(全合格=True, 検査数=len(records),
        未来切断地点数=len(records) * 7, 検査=records, コードSHA256=hashes))
    print(json.dumps(dict(全合格=True, 検査数=len(records)), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
