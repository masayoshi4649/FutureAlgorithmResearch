"""読取前に、診断対象選定と親の局所清算算術を自作資料だけで検査する。"""

import hashlib
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import diagnose


def main() -> None:
    """
    機能: 実結果と市場を読まずに、16対象上限・空候補・部分返済会計を検査する。
    引数: なし。
    返り値: None。計画前の人工証跡だけを保存する。
    """
    checks = []
    result = dict(selection={}, runs=[], portfolios=[])
    for symbol in ('TOPIX', 'NK225'):
        result['selection'][symbol] = dict(chosen=['単体'])
        for i in range(8):
            result['runs'].append(dict(symbol=symbol, session=f'場{i}', method='単体',
                                       net=-100+i if i < 3 else (1000 if i == 6 else 10)))
            result['portfolios'].append(dict(symbol=symbol, session=f'場{i}', method='PORT',
                                            net=-100+i if 3 <= i < 6 else (1000 if i == 7 else 10)))
    chosen = diagnose.targets(result)
    assert len(chosen) == 16
    checks.append('単体とPORTの最悪3・最大1が完全非重複でも16対象')
    for symbol in result['selection']:
        result['selection'][symbol]['chosen'] = []
    assert len(diagnose.targets(result)) == 8
    checks.append('単体選択なしでもPORTを診断し架空の単体を作らない')
    bars = dict(valid=np.array([True]), close=np.array([999.]), pub_raw_row=np.array([0], np.int64),
                pub_price_time_s=np.array([0.]), anchor=np.array([999.]))
    bid = np.array([999., 999., 1010., 1008.])
    ask = bid + 1
    for side in (1, -1):
        b, a = (bid, ask) if side == 1 else (2000-ask, 2000-bid)
        quotes = dict(row=np.arange(4), time=np.arange(4, dtype=float), bid=b, ask=a,
                      bq=np.full(4, 100.), aq=np.full(4, 100.))
        legs = np.array([[1, 1, 2, 1, 2, side, 1, 1000, 1000+side*10, 10000, 125/3, 41, 10000-125/3-41, 8, 0, .5],
                         [1, 1, 3, 1, 3, side, 2, 1000, 1000+side*8, 16000, 250/3, 83, 16000-250/3-83, 4, 0, .5]], float)
        actual = diagnose.parent_detail(legs, bars, quotes, dict(entry_mode=0, width=1000.), 3, 'TOPIX')
        assert actual['完結'] and abs(actual['親net']-25751) < 1e-8
        assert actual['順行最大価格幅'] == 10 and actual['最大順行から最後返済まで戻り幅'] == 2
        assert abs(actual['部分返済と費用込み親局所資産最大']-29751) < 1e-8
        assert all(v['返済判断原row'] is None for v in actual['exits'])
        checks.append(('買い' if side == 1 else '売り')+'の部分返済・注文別切捨て・局所清算と判断原row未知')
        json.dumps(diagnose.primitive(actual), allow_nan=False)
    assert diagnose.primitive(np.float64(np.nan)) is None
    assert diagnose.primitive(np.bool_(True)) is True
    checks.append('非有限はnull・numpy真偽はboolの保存原始型')
    files = (HERE/'diagnose.py', Path(__file__))
    proof = dict(全合格=True, 検査数=len(checks), 内容=checks,
                 診断source_SHA256={p.relative_to(diagnose.ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                 原市場=0, 結果本文=0, cache本文=0, 新金融=0, API=0)
    path = HERE/'保存cache診断の選定と部分清算及び未知保存の純人工.json'
    assert not path.exists()
    path.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査数=len(checks), 結果本文=0, cache本文=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
