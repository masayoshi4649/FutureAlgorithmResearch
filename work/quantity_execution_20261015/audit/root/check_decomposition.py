"""実脚の中値・気配横断・税込料金と可逆台帳を純人工へ接続する。"""

from __future__ import annotations

from fractions import Fraction
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys
from types import SimpleNamespace

import numpy as np

from check_finance_source import functions

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = BASE.parents[1]
OWNED = BASE / 'audit/owned'
sys.path.insert(0, str(OWNED))
from cash_reference import PRODUCTS, order_fee
from connect_execution_v2 import materialize, select_config
from execution_expectations import fixtures


def exact(value) -> Fraction:
    """
    機能: 表示可能な数値を独立した有理数へ変換する。
    引数: value(int|float) 人工値。
    返り値: Fraction 十進文字列からの厳密値。
    """
    return Fraction(str(value))


def main() -> None:
    """
    機能: 完成源の診断と保存を先固定純経路のBBO・注文料へ照合する。
    引数: なし。
    返り値: None。保存するのは所有域の小合成台帳だけ。
    """
    sys.path.insert(0, str(OWNED / '完成三源の私有複製'))
    import engine
    import catalog
    namespace = functions(('primitive','curve_pack','curve_unpack','save_ledger','diagnose'),
                          dict(np=np, gzip=gzip, pickle=pickle, hashlib=hashlib,
                               catalog=catalog, Path=Path, plan=SimpleNamespace(ROOT=ROOT)))
    outdir = HERE / '純人工台帳'
    assert not outdir.exists(), '純保存の初版も再実行しない'
    namespace['OUT'] = outdir
    checks = 0
    examples = []
    for fixture in fixtures():
        p = next(x for x in PRODUCTS if x.symbol == fixture['symbol'])
        arrays, signal, policy = materialize(p.symbol, fixture['side'], fixture['ticks'])
        daily = engine.simulate(arrays, signal, p.symbol, 0., 2000., float(p.tick), policy, select_config(catalog, 2, fixture['mode']))
        result = namespace['diagnose'](daily, arrays, p.symbol)
        midpoint, cross, fees, net = Fraction(), Fraction(), 0, Fraction()
        for actual, saved in zip(daily['actual_legs'], result['parent_breakdown'][0]['legs']):
            a, b, q, side = (int(actual[k]) for k in ('entry_row','exit_row','q','side'))
            b0,a0,b1,a1 = (exact(arrays[k][i]) for i,k in ((a,'bid'),(a,'ask'),(b,'bid'),(b,'ask')))
            entry, exitprice = (a0,b1) if side == 1 else (b0,a1)
            gross = side * (exitprice - entry) * q * p.multiplier
            direction = side * ((b1+a1)/2 - (b0+a0)/2) * q * p.multiplier
            burden = ((a0-b0)+(a1-b1))/2 * q * p.multiplier
            allocated = Fraction(order_fee(p,p.quantity) * q, p.quantity)
            fee = order_fee(p,q)
            assert gross == direction - burden
            assert exact(actual['gross_yen']) == gross
            assert exact(actual['entry_fee_allocated']) == allocated and exact(actual['exit_fee']) == fee
            assert exact(actual['net_yen']) == gross - allocated - fee
            assert saved['q'] == q and saved['side'] == side and saved['entry_row'] == a and saved['exit_row'] == b
            for label,i in (('新規',a),('返済',b)):
                for name in ('raw_seq','price_time_s','bid','ask','bid_qty','ask_qty'):
                    assert saved[label][name] == arrays[name][i]
                    checks += 1
            midpoint += direction; cross += burden; fees += allocated + fee; net += gross-allocated-fee
            checks += 5
        assert exact(result['中値差粗損益']) == midpoint
        assert exact(result['気配差負担']) == cross
        assert exact(result['手数料']) == fees
        assert exact(result['収支']) == net == fixture['net']
        assert len(result['parent_breakdown']) == 1
        for key,value in (('中値差粗損益',midpoint),('気配差負担',cross),('手数料',fees),('収支',net)):
            assert exact(result['parent_breakdown'][0][key]) == value
            checks += 1
        checks += 5
        if fixture['mode'] == 3:
            path = outdir / (fixture['name'] + '.pkl.gz')
            info = namespace['save_ledger'](daily, path)
            raw = path.read_bytes()
            assert hashlib.sha256(raw).hexdigest() == info['SHA256'] and len(raw) == info['bytes']
            restored = pickle.loads(gzip.decompress(raw))
            assert 'price_valid_mask' not in restored and 'execution_normal_mask' not in restored and 'curve' not in restored
            np.testing.assert_array_equal(namespace['curve_unpack'](restored['curve_rle']),daily['curve'])
            for name in ('orders','actual_order_legs','parents','publication_events','execution_events','control_events'):
                np.testing.assert_array_equal(restored[name],daily[name])
            np.testing.assert_array_equal(daily['curve'][:,14].astype(bool),daily['price_valid_mask'])
            np.testing.assert_array_equal(daily['curve'][:,15].astype(bool),daily['execution_normal_mask'])
            checks += 10
        examples.append(dict(商品=p.symbol, 方向=fixture['side'], 出口=fixture['mode'], 中値差=float(midpoint), 気配横断=float(cross), 税込実料金=float(fees), 収支=float(net)))
    output = HERE / '各脚気配と税込注文料の独立分解及び可逆合成台帳の接続.json'
    proof = dict(全合格=True, 確認数=checks, source_SHA256={'finance.py':hashlib.sha256((BASE/'finance.py').read_bytes()).hexdigest(),
                  'engine.py':hashlib.sha256((BASE/'engine.py').read_bytes()).hexdigest()},
                 独立源_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 具体例=examples,
                 範囲='先固定16純経路の診断。中値差は取引できた利益ではなく、実気配からの恒等式。追加税・追加遅延費を二重控除しない。',
                 合成台帳保存=4, 原入力=0, 原NPZ=0, 実金融台帳=0, 過去金融=0, API=0)
    output.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,確認数=checks),ensure_ascii=False))


if __name__ == '__main__':
    main()
