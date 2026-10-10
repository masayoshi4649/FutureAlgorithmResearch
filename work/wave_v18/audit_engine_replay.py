"""上限だけを引数化した監査用コピーで縮小数量の約定経路を確認する。"""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import pickle
import time

import numpy as np

OUT = Path(__file__).resolve().parent
SOURCE = OUT.parent / 'wave_v17'
METHODS = ['M3_逆_A03', 'M3_逆_A00', 'M2_逆_A00', 'M2_逆_A01']


def main() -> None:
    """機能: 元ソースを保存し、上限だけ変えたコピーの全約定経路を照合する。

    引数: なし。返り値: なし (None)。パラメータ探索・通信・原本変更はしない。
    """
    started = time.time()
    original_path = SOURCE / 'engine.py'
    source = original_path.read_text(encoding='utf-8')
    original_hash = hashlib.sha256(original_path.read_bytes()).hexdigest()
    replacements = {
        'us_open, par, detail):': ('us_open, par, detail, cap):', 1),
        '100-int(': ('cap-int(', 2),
        'inv[1]<100:': ('inv[1]<cap:', 1),
        'inv[0]<100 and': ('inv[0]<cap and', 1),
        "ready['start'],ready['limit'],ready['us_open'],par,detail)":
            ("ready['start'],ready['limit'],ready['us_open'],par,detail,config['audit_cap'])", 1),
    }
    for old, (new, count) in replacements.items():
        assert source.count(old) == count, (old, source.count(old))
        source = source.replace(old, new)
    source = source.replace('100枚', '指定上限枚数')
    source = source.replace('time/price/atr/state/par (ndarray)、tick/start/end/us_open (float)、detail (bool)',
                            'time/price/atr/state/par (ndarray)、tick/start/end/us_open (float)、detail (bool)、cap (int)')
    copied_path = OUT / 'audit_engine_scaled.py'
    copied_path.write_text(source, encoding='utf-8')
    engine = importlib.import_module('audit_engine_scaled')
    configs = {r['id']: r for r in json.loads((SOURCE / '全条件一覧.json').read_text(encoding='utf-8'))}
    states = pickle.loads((SOURCE / '主方向状態.pkl').read_bytes())
    blocks = pickle.loads((SOURCE / '全返済と組.pkl').read_bytes())
    inputs = {}
    for stage in ['development', 'holdout']:
        inputs.update(pickle.loads((OUT.parent / 'wave_v16' / f'入力_{stage}.pkl').read_bytes()))
    data = json.loads((OUT / 'scale_data.json').read_text(encoding='utf-8'))
    comparisons, trade_rows, cells = 0, 0, []
    for method in data['methods']:
        for symbol, primary in method['variants'].items():
            for mode, variant in [('主案', primary), ('一律縮小', primary['uniform'])]:
                k = variant['config']['quantity_factor']
                config = dict(configs[method['id']])
                config['initial_qty'] = int(config['initial_qty'] * k)
                config['add_qty'] = int(config['add_qty'] * k)
                config['audit_cap'] = variant['config']['position_cap']
                for row in variant['sessions']:
                    session = row['session']
                    ready = inputs[(session, symbol)]
                    direction = np.ascontiguousarray(states[(session, symbol)][config['signal']] * config['sign'], dtype=np.int8)
                    result = engine.run(ready, direction, config)
                    old = blocks[(method['id'], session, symbol)]
                    expected_trades = old['trades'].copy()
                    expected_trades[:, [3, 10]] *= k
                    np.testing.assert_allclose(result['trades'], expected_trades, rtol=1e-12, atol=1e-8)
                    expected_cycles = old['cycles'].copy()
                    expected_cycles[:, [3, 4, 6, 7]] *= k
                    np.testing.assert_allclose(result['cycles'], expected_cycles, rtol=1e-12, atol=1e-8)
                    multiplier = data['products'][symbol]['multiplier']
                    mapping = [(0, 'net_yen', multiplier), (1, 'drawdown_yen', multiplier), (2, 'max_long', 1),
                               (3, 'max_short', 1), (4, 'max_gross', 1), (5, 'max_net', 1),
                               (7, 'min_equity_yen', multiplier), (8, 'max_equity_yen', multiplier)]
                    for index, field, scale in mapping:
                        np.testing.assert_allclose(result['stats'][index]*scale, row[field], rtol=1e-10, atol=1e-5)
                    assert result['stats'][9] == result['stats'][10] == 0
                    assert result['stats'][6] < 1e-5
                    comparisons += expected_trades.size + expected_cycles.size + len(mapping)
                    trade_rows += len(expected_trades)
                    cells.append(dict(配分=mode, 手法=method['id'], 銘柄=symbol, セッション=session, 約定経路一致=True))
    assert hashlib.sha256(original_path.read_bytes()).hexdigest() == original_hash
    output = dict(合格=True, セル数=len(cells), 比較数=comparisons, 返済行数=trade_rows,
                  原本不変=True, 現在API取得数=0, パラメータ探索数=0,
                  元ソースSHA256=original_hash, 監査コピーSHA256=hashlib.sha256(copied_path.read_bytes()).hexdigest(),
                  変更内容='元エンジンを監査用ファイルへ複製し、100枚上限の4か所をcap引数へ変更。初期枚数と追加枚数を同率にして再生。その他の価格・時間条件は変更なし。',
                  結果='160セル全てで、元返済の約定価格・時刻・方向・理由・組番号が不変。数量・損益・損失予算・最大枚数が所定倍率と一致。',
                  経過秒=time.time()-started, セル=cells)
    (OUT / 'audit_engine_replay.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in output.items() if k != 'セル'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
